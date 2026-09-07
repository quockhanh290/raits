"""Track 1 — production feasibility audit. SCRATCH-ONLY.

No production file is modified. Nothing is committed.

GATE: the replay below is a re-implementation with instrumentation, so it must first
reproduce Track 1's published net and worst drawdown to the cent in all three windows.
If it does not, nothing downstream is reported.

Sections
  A  broker-relevant event log for every switch, force-close and suppression
  B  cap audit: admission-time versus carried exposure, every cluster
  C  item 6 - max-hold exit pre-empting the armed stop, on the TAKEN set only
  D  item 9 - stop armed at 14:00 (production) versus 14:05 (artifacts)
  E  item 10 - 5-minute timestamp semantics and whether it can reorder anything
  F  fill audit for all four sleeves

  python scratch/track1_production_feasibility_audit_20260822.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.calm_a_combined_replay_20260822 as calm_a_base
import scratch.combined_repaired_replay_20260822 as rep
import scratch.combined_stop_risk_audit_20260822 as audit
import scratch.normal_promotion_variant_matrix_20260821 as vm
import scratch.stress_switch_full_replay_20260822 as full
from futures._validated_core import daily_atr_series
from futures.basket import BASKET
from global_index.deploy_sim import metrics
from global_index import specs as gi_specs
from global_index.net_exposure_multi import Position, entry_priority_key
from scratch.normal_sleeve_fill_audit import ACCOUNT

OUT_JSON = Path("scratch/track1_production_feasibility_audit_20260822.json")

# The signal-path regeneration running in parallel OVERWRITES the promotion artifacts in
# place. Read from an untouched snapshot taken before it started, so the two jobs cannot
# race on the same file and this audit is measured on a fixed input.
_SNAP = Path(r"C:/Users/quock/AppData/Local/Temp/claude/d--raits/a3f30637-d2ee-4eaf-a6b1-b64e18c01c77/scratchpad/artifact_backup")
if _SNAP.is_dir():
    for _w in ("floor", "vault2025", "vault2026"):
        _f = _SNAP / f"normal_promotion_trades_{_w}_20260821.json"
        if _f.exists():
            full.NORMAL_PROMOTION_FILES[_w] = _f
TRACK1 = "risk_clean_no_calm_nkd_family_cap_5_44"
PUBLISHED = {"floor": (64902.91, 4845.31), "vault2025": (13236.11, 4631.53),
             "vault2026": (8259.85, 4797.44)}
FAMILY = ("roska4_swing", "roska4_calm")
ARM_PROD, ARM_ARTIFACT = 14.0, 14 + 5 / 60
STOP_BASIS = 2.0


def naive(ts):
    t = pd.Timestamp(ts)
    return t.tz_localize(None) if t.tzinfo is not None else t


def policy_track1():
    return [p for p in rep.POLICIES if p.name == TRACK1][0]


# ---------------------------------------------------------------------------
# A + B: instrumented Track 1 replay with a broker event log
# ---------------------------------------------------------------------------
def replay_track1(which: str):
    policy = policy_track1()
    r4, current_nkd, prices, extra, stress, calm_nkd_df = audit.load_all(which)
    calm_a = rep.load_calm_a_atr15(which, extra["meta"])
    calm_nkd_df = calm_nkd_df.iloc[0:0]            # Track 1 excludes Calm-NKD entirely
    guard = rep.make_guard()
    breaker = full.CircuitBreaker(account=ACCOUNT)
    open_pos, realized, equity, cur_day = [], {}, ACCOUNT, None

    events, violations = [], []
    entered, settled = {}, {}
    exposure = []          # (ts, cause, cluster_state)
    taken_rows = []

    def ev(ts, kind, **kw):
        events.append(dict(ts=str(ts), kind=kind, **kw))

    def invariants(ts, where):
        by_inst = {}
        for p, t in open_pos:
            by_inst.setdefault(p.instrument, []).append((p, t))
        for inst, lst in by_inst.items():
            if len(lst) > 1:
                violations.append(dict(ts=str(ts), where=where, kind="same_symbol_stack",
                                       inst=inst,
                                       legs=[f"{p.cluster}/{t['source']}/{t['direction']}"
                                             for p, t in lst]))
            dirs = {t["direction"] for _, t in lst}
            if len(dirs) > 1:
                violations.append(dict(ts=str(ts), where=where, kind="opposite_direction",
                                       inst=inst, dirs=sorted(dirs)))

    def snap(ts, cause):
        st = {}
        for cname in guard.clusters:
            ps = [p for p, _ in open_pos if p.cluster == cname]
            lo = sum(p.risk_dollars for p in ps if p.direction == "LONG")
            sh = sum(p.risk_dollars for p in ps if p.direction == "SHORT")
            st[cname] = (max(lo, sh) / ACCOUNT, abs(lo - sh) / ACCOUNT)
        fam = [p for p, _ in open_pos if p.cluster in FAMILY]
        lo = sum(p.risk_dollars for p in fam if p.direction == "LONG")
        sh = sum(p.risk_dollars for p in fam if p.direction == "SHORT")
        st["FAMILY"] = (max(lo, sh) / ACCOUNT, abs(lo - sh) / ACCOUNT)
        exposure.append((str(ts), cause, st))

    def book(ts, tr, pnl, kind):
        nonlocal equity
        equity += float(pnl)
        realized[naive(ts).normalize()] = realized.get(naive(ts).normalize(), 0.0) + float(pnl)
        tid = tr.get("trade_id", "?")
        settled[tid] = settled.get(tid, 0) + 1
        ev(ts, kind, trade_id=tid, inst=tr["instrument"], cluster=tr["cluster"],
           direction=tr["direction"], pnl=round(float(pnl), 2))

    entries = pd.concat([p for p in (r4, stress, current_nkd, calm_a) if not p.empty],
                        ignore_index=True)
    by_time, times = {}, set()
    for _, row in entries.iterrows():
        tr = row.to_dict()
        et, xt = pd.Timestamp(tr["entry_time"]), pd.Timestamp(tr["exit_time"])
        by_time.setdefault(et, []).append(tr)
        times.add(et)
        times.add(xt)

    for ts in sorted(times):
        day = naive(ts).normalize()
        if cur_day is None or day != cur_day:
            breaker.start_day(equity)
            cur_day = day
        still = []
        for pos, tr in open_pos:
            if pd.Timestamp(tr["exit_time"]) <= ts:
                book(ts, tr, float(tr["pnl_sized"]), "EXIT")
            else:
                still.append((pos, tr))
        if len(still) != len(open_pos):
            open_pos = still
            snap(ts, "after_exit")
        breaker.update(equity)
        allow = breaker.status(equity).get("allow_new_entries", True)

        for tr in sorted(by_time.get(ts, []), key=entry_priority_key):
            if not allow:
                ev(ts, "HALTED_BY_BREAKER", inst=tr["instrument"], cluster=tr["cluster"])
                continue
            src, inst, cluster = tr["source"], tr["instrument"], tr["cluster"]
            open_positions = [p for p, _ in open_pos]

            if src == "calm_a_pcloc_not_deep":
                if any(p.instrument == inst and p.cluster in ("roska4_swing", "roska4_stress")
                       for p, _ in open_pos):
                    ev(ts, "SUPPRESS", cluster=cluster, inst=inst,
                       reason="same_symbol_normal_or_stress_open")
                    continue
                pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, why = guard.admits(pos, open_positions)
                if ok and not rep.family_admits(pos, open_positions, policy):
                    ok, why = False, "family_cap"
                if ok:
                    open_pos.append((pos, tr))
                    entered[tr["trade_id"]] = 1
                    taken_rows.append(tr)
                    ev(ts, "ENTRY", cluster=cluster, inst=inst, direction=tr["direction"],
                       qty=1, risk=round(float(tr["risk_sized"]), 2))
                    ev(ts, "PLACE_STOP", cluster=cluster, inst=inst,
                       stop=float(tr["stop"]) if tr.get("stop") is not None else None)
                    invariants(ts, "after_calm_entry")
                    snap(ts, "entry_calm")
                else:
                    ev(ts, "REJECT", cluster=cluster, inst=inst, reason=str(why))
                continue

            if cluster == "roska4_stress":
                survivors = [(p, t) for p, t in open_pos
                             if not (p.instrument == inst and p.cluster in FAMILY)]
                proposed = Position(inst, tr["direction"], int(tr.get("qty", 1)),
                                    float(tr["risk_sized"]), cluster)
                ok, why = guard.admits(proposed, [p for p, _ in survivors])
                if not ok:
                    # the whole point of testing admission against the POST-close book:
                    # a rejected Stress must leave the existing book untouched
                    ev(ts, "REJECT", cluster=cluster, inst=inst, reason=str(why),
                       note="no force-close performed")
                    continue
                victims = [(p, t) for p, t in open_pos
                           if p.instrument == inst and p.cluster in FAMILY]
                for p, old in victims:
                    px = full.price_at_or_after(prices[inst], ts)
                    if px is None:
                        violations.append(dict(ts=str(ts), where="force_close",
                                               kind="missing_price_position_dropped",
                                               inst=inst, cluster=p.cluster))
                        continue
                    ev(ts, "CANCEL_STOP", cluster=p.cluster, inst=inst,
                       note="must precede the close or the flat account carries a live stop")
                    epnl = (calm_a_base.early_calm_pnl(old, px, 2.0) if p.cluster == "roska4_calm"
                            else full.early_pnl(old, px, full.costs_for_basket(slippage_ticks=2.0)))
                    book(ts, old, epnl, "FORCE_CLOSE")
                    ev(ts, "AWAIT_CLOSE_CONFIRM", inst=inst, cluster=p.cluster)
                open_pos = survivors
                invariants(ts, "after_force_close")
                open_pos.append((proposed, tr))
                entered[tr["trade_id"]] = 1
                taken_rows.append(tr)
                ev(ts, "ENTRY", cluster=cluster, inst=inst, direction=tr["direction"],
                   qty=int(tr.get("qty", 1)), risk=round(float(tr["risk_sized"]), 2),
                   after_force_close=len(victims))
                ev(ts, "PLACE_STOP", cluster=cluster, inst=inst, stop=float(tr["stop"]))
                invariants(ts, "after_stress_entry")
                snap(ts, "entry_stress")
                continue

            if cluster == "roska4_swing":
                if any(p.instrument == inst and p.cluster in ("roska4_stress", "roska4_calm")
                       for p, _ in open_pos):
                    ev(ts, "SUPPRESS", cluster=cluster, inst=inst,
                       reason="same_symbol_stress_or_calm_open")
                    continue
                pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, why = guard.admits(pos, open_positions)
                if ok and not rep.family_admits(pos, open_positions, policy):
                    ok, why = False, "family_cap"
                if ok:
                    open_pos.append((pos, tr))
                    entered[tr["trade_id"]] = 1
                    taken_rows.append(tr)
                    ev(ts, "ENTRY", cluster=cluster, inst=inst, direction=tr["direction"],
                       qty=1, risk=round(float(tr["risk_sized"]), 2))
                    invariants(ts, "after_normal_entry")
                    snap(ts, "entry_normal")
                else:
                    ev(ts, "REJECT", cluster=cluster, inst=inst, reason=str(why))
                continue

            pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
            ok, why = guard.admits(pos, open_positions)
            if ok:
                open_pos.append((pos, tr))
                entered[tr["trade_id"]] = 1
                taken_rows.append(tr)
                ev(ts, "ENTRY", cluster=cluster, inst=inst, direction=tr["direction"], qty=1,
                   risk=round(float(tr["risk_sized"]), 2))
                invariants(ts, "after_nkd_entry")
                snap(ts, "entry_nkd")
            else:
                ev(ts, "REJECT", cluster=cluster, inst=inst, reason=str(why))

    daily = pd.Series(realized).sort_index()
    return dict(daily=daily, events=events, violations=violations, entered=entered,
                settled=settled, exposure=exposure, taken=pd.DataFrame(taken_rows),
                prices=prices, extra=extra, calm_a=calm_a, stress=stress,
                r4=r4, nkd=current_nkd)


# ---------------------------------------------------------------------------
# C + D: the two replay-underlayer items, on the TAKEN set
# ---------------------------------------------------------------------------
def swing_taken(res):
    t = res["taken"]
    if t.empty:
        return t
    return t[t["source"].isin(["normal_r4_filtered", "normal_nkd_filtered_bucket"])]


def item6_and_item9(which, res):
    raw = json.loads(full.NORMAL_PROMOTION_FILES[which].read_text(encoding="utf-8"))
    frames = vm.load_frames(raw)
    nkd_inst = raw["nkd_instrument"]
    taken = swing_taken(res)
    taken_keys = {(r["instrument"], naive(pd.Timestamp(r["day"])).normalize())
                  for _, r in taken.iterrows()}
    i6 = dict(scanned=0, armed=0, hits=0, delta=0.0, worst=0.0, rows=[])
    i9 = dict(scanned=0, touched_1400_1405=0, delta=0.0, rows=[])
    for inst, lst in raw["filtered"].items():
        df = frames[inst]
        tz = df.index.tz
        datr = daily_atr_series(df)
        pv = (gi_specs.SPECS[nkd_inst] if inst == nkd_inst else BASKET[inst]).point_value
        for t in lst:
            d0 = naive(pd.Timestamp(t["day"])).normalize()
            if (inst, d0) not in taken_keys:
                continue
            da = datr.asof(d0)
            da = float(da) if (da is not None and not pd.isna(da)) else float(datr.median())
            entry = float(t["entry"])
            stop = entry - STOP_BASIS * da if t["direction"] == "LONG" else entry + STOP_BASIS * da
            xt = pd.Timestamp(t["exit_time"])
            if xt.tzinfo is None and tz is not None:
                xt = xt.tz_localize(tz)
            cost = (float(t["points"]) * pv) - float(t["pnl"])

            # ---- item 9: is the stop touched in the 14:00-14:05 window of the arm day?
            arm_day = d0 + pd.Timedelta(days=1)
            w0 = (arm_day + pd.Timedelta(hours=ARM_PROD))
            w1 = (arm_day + pd.Timedelta(hours=ARM_ARTIFACT))
            w0 = w0.tz_localize(tz) if tz is not None else w0
            w1 = w1.tz_localize(tz) if tz is not None else w1
            if w1 <= xt:
                i9["scanned"] += 1
                seg = df[(df.index >= w0) & (df.index < w1)]
                if not seg.empty:
                    hit = (float(seg["low"].min()) <= stop if t["direction"] == "LONG"
                           else float(seg["high"].max()) >= stop)
                    if hit:
                        i9["touched_1400_1405"] += 1
                        pts = (stop - entry) if t["direction"] == "LONG" else (entry - stop)
                        alt = pts * pv - cost
                        i9["delta"] += alt - float(t["pnl"])
                        i9["rows"].append(dict(inst=inst, day=str(t["day"]),
                                               booked=float(t["pnl"]), if_armed_1400=alt))

            # ---- item 6: max-hold pre-empting an armed stop
            if t["reason"] != "MAX_HOLD":
                continue
            i6["scanned"] += 1
            arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=ARM_ARTIFACT)
            arm = arm.tz_localize(tz) if tz is not None else arm
            if arm >= xt:
                continue
            i6["armed"] += 1
            xday = naive(xt).normalize()
            xday = xday.tz_localize(tz) if tz is not None else xday
            seg = df[(df.index >= max(arm, xday)) & (df.index < xt)]
            if seg.empty:
                continue
            touched = (float(seg["low"].min()) <= stop if t["direction"] == "LONG"
                       else float(seg["high"].max()) >= stop)
            if not touched:
                continue
            pts = (stop - entry) if t["direction"] == "LONG" else (entry - stop)
            alt = pts * pv - cost
            d = float(t["pnl"]) - alt
            i6["hits"] += 1
            i6["delta"] += d
            i6["worst"] = min(i6["worst"], d)
            i6["rows"].append(dict(inst=inst, day=str(t["day"]), exit_day=str(t["exit_day"]),
                                   booked=float(t["pnl"]), if_stop_first=alt, delta=d))
    return i6, i9


# ---------------------------------------------------------------------------
# E: 5-minute timestamp semantics
# ---------------------------------------------------------------------------
def item10(res):
    """A swing entry is stamped at the START of its 5-minute resume bar but fills at
    that bar's CLOSE, five minutes later. Anything stamped inside that window is
    ordered after the entry here but would in reality happen at or before the fill."""
    taken = res["taken"]
    if taken.empty:
        return dict(swing_entries=0, exits_inside_fill_window=0, cases=[])
    sw = taken[taken["source"].isin(["normal_r4_filtered", "normal_nkd_filtered_bucket"])]
    others = pd.concat([res["calm_a"], res["stress"], res["r4"], res["nkd"]],
                       ignore_index=True)
    cases = []
    for _, e in sw.iterrows():
        t0 = pd.Timestamp(e["entry_time"])
        t1 = t0 + pd.Timedelta(minutes=5)
        for _, o in others.iterrows():
            xt = pd.Timestamp(o["exit_time"])
            if xt.tzinfo != t0.tzinfo:
                continue
            if t0 < xt <= t1:
                cases.append(dict(swing_entry=str(t0), swing_inst=e["instrument"],
                                  other_exit=str(xt), other_inst=o["instrument"],
                                  other_cluster=o["cluster"],
                                  same_family=bool(o["cluster"] in FAMILY
                                                   and e["cluster"] in FAMILY)))
    return dict(swing_entries=int(len(sw)), exits_inside_fill_window=len(cases),
                family_relevant=sum(1 for c in cases if c["same_family"]),
                cases=cases[:10])


# ---------------------------------------------------------------------------
# F: fill audit
# ---------------------------------------------------------------------------
def fill_audit(which, res):
    raw = json.loads(full.NORMAL_PROMOTION_FILES[which].read_text(encoding="utf-8"))
    frames = vm.load_frames(raw)
    out = []
    sleeves = dict(normal_r4=(res["r4"], 5), current_nkd=(res["nkd"], 5),
                   stress_mnq=(res["stress"], 1), calm_a=(res["calm_a"], 1))
    for name, (d, span_min) in sleeves.items():
        if d is None or d.empty:
            out.append(dict(sleeve=name, n=0))
            continue
        n_oe = n_ox = n_sig = n_same = n_miss = n_imp = 0
        imp_usd = 0.0
        span = pd.Timedelta(minutes=span_min)
        for _, t in d.iterrows():
            inst = t["instrument"]
            df = frames.get(inst)
            e0, e1 = pd.Timestamp(t["entry_time"]), pd.Timestamp(t["exit_time"])
            if e1 <= e0:
                n_same += 1
            if int(t.get("signal_after_entry", 0) or 0):
                n_sig += 1
            if df is None:
                n_miss += 1
                continue
            tz = df.index.tz
            a = e0.tz_localize(tz) if (e0.tzinfo is None and tz is not None) else e0
            b = e1.tz_localize(tz) if (e1.tzinfo is None and tz is not None) else e1
            eb = df[(df.index >= a) & (df.index < a + span)]
            xb = df[(df.index >= b) & (df.index < b + span)]
            if eb.empty or xb.empty:
                n_miss += 1
                continue
            if not (float(eb["low"].min()) - 0.011 <= float(t["entry"]) <= float(eb["high"].max()) + 0.011):
                n_oe += 1
            if not (float(xb["low"].min()) - 0.011 <= float(t["exit"]) <= float(xb["high"].max()) + 0.011):
                n_ox += 1
            # impossible stop fill: booked at the stop on a bar that already opened past it
            stp = t.get("stop")
            reason = str(t.get("exit_reason", ""))
            if stp is not None and not pd.isna(stp) and reason == "stop":
                op = float(xb.iloc[0]["open"])
                w = (float(stp) - op) if t["direction"] == "LONG" else (op - float(stp))
                if w > 1e-9:
                    n_imp += 1
                    imp_usd += w * BASKET[inst].point_value * int(t.get("qty", 1) or 1)
        out.append(dict(sleeve=name, n=int(len(d)), outside_entry_bar=n_oe,
                        outside_exit_bar=n_ox, signal_after_entry=n_sig,
                        same_or_before_bar_exit=n_same, missing_bars=n_miss,
                        impossible_stop_fills=n_imp, impossible_dollars=imp_usd))
    return out


# ---------------------------------------------------------------------------
def main() -> int:
    out = {}
    ok_all = True
    for which in ("floor", "vault2025", "vault2026"):
        print(f"[run] {which}", flush=True)
        res = replay_track1(which)
        m = metrics(res["daily"])
        want_net, want_dd = PUBLISHED[which]
        gate = (abs(m["pnl"] - want_net) < 0.01) and (abs(m["maxdd"] - want_dd) < 0.01)
        ok_all &= gate
        print(f"  gate net {m['pnl']:.2f} vs {want_net} | dd {m['maxdd']:.2f} vs {want_dd} "
              f"-> {gate}", flush=True)
        if not gate:
            out[which] = dict(gate=False, net=m["pnl"], maxdd=m["maxdd"])
            continue

        ev = pd.DataFrame(res["events"])
        kinds = ev["kind"].value_counts().to_dict() if not ev.empty else {}
        forced = ev[ev["kind"] == "FORCE_CLOSE"] if not ev.empty else pd.DataFrame()
        i6, i9 = item6_and_item9(which, res)
        exp = res["exposure"]
        cap = {}
        for cname in list(rep.make_guard().clusters) + ["FAMILY"]:
            g = [s[2][cname][0] for s in exp]
            n = [s[2][cname][1] for s in exp]
            ga = [s[2][cname][0] for s in exp if s[1].startswith("entry")]
            na = [s[2][cname][1] for s in exp if s[1].startswith("entry")]
            cap[cname] = dict(carried_gross_peak=max(g) if g else 0.0,
                              carried_net_peak=max(n) if n else 0.0,
                              admission_gross_peak=max(ga) if ga else 0.0,
                              admission_net_peak=max(na) if na else 0.0,
                              n_obs=len(g))
        out[which] = dict(
            gate=True, net=float(m["pnl"]), maxdd=float(m["maxdd"]),
            pf=float(m["pf"]), calmar=float(m["calmar"]), sharpe=float(m["sharpe"]),
            event_kinds=kinds,
            n_force_close=int(len(forced)),
            force_close_pnl=float(forced["pnl"].sum()) if len(forced) else 0.0,
            force_close_detail=forced.to_dict("records")[:20] if len(forced) else [],
            violations=res["violations"],
            positions_entered=len(res["entered"]), positions_settled=len(res["settled"]),
            settled_twice=sum(1 for v in res["settled"].values() if v > 1),
            never_settled=len([k for k in res["entered"] if k not in res["settled"]]),
            item6=i6, item9=i9, item10=item10(res), fill=fill_audit(which, res), cap=cap)
        print(f"  events {kinds} | forced={out[which]['n_force_close']} "
              f"violations={len(res['violations'])} | item6 hits={i6['hits']} "
              f"delta=${i6['delta']:.2f} | item9 touched={i9['touched_1400_1405']}",
              flush=True)
    out["gate_all"] = bool(ok_all)
    OUT_JSON.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT_JSON)
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
