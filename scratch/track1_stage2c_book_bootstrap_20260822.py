"""scratch/track1_stage2c_book_bootstrap_20260822.py — Stage 2C. Offline. Scratch only.

Builds an ACTUAL Track 1 bootstrap and proves it reproduces Track 1, rather than proving it
reproduces the legacy per-instrument checkpoint.

What Stage 2B's checkpoint cannot do, and why
---------------------------------------------
The Stage 2B file records one thing per instrument: the swing engine's open position. The
Track 1 book carries strictly more than that across a day boundary, and every one of these
changes which trades are ADMITTED, not merely how they are reported:

    open_pos          each open position with its cluster and risk — the cap gate reads it
    equity            drives the circuit breaker, which can refuse every entry for a day
    peak_equity       CircuitBreaker keeps it ACROSS days; drawdown is measured from it
    _day_start_equity the -4% daily rule is measured from it
    cur_day           decides when start_day() re-bases that rule
    booked            the double-settlement detector

Seeding only the engine positions would resume a book whose breaker thinks it is at its
all-time peak. So the deliverable here is a bootstrap of the BOOK, and Stage 2B's file is
one component of it.

The equivalence gate on this file's own honesty
-----------------------------------------------
`replay` below is a re-host of `combined_repaired_replay_20260822.replay_repaired` with two
seams added (`resume`, `stop_after`). A second copy of a decision rule is exactly what this
project has been bitten by, so the copy is not trusted: with both seams unused it must
reproduce the original function's daily series and every counter EXACTLY, for every policy
and window, and `main` refuses to go further if it does not. The original is the anchor.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import pandas as pd  # noqa: E402

import scratch.calm_a_combined_replay_20260822 as calm_a_base  # noqa: E402
import scratch.calm_nkd_switch_vs_current_20260822 as calm_nkd  # noqa: E402
import scratch.combined_repaired_replay_20260822 as comb  # noqa: E402
import scratch.combined_stop_risk_audit_20260822 as audit  # noqa: E402
import scratch.stress_switch_full_replay_20260822 as full  # noqa: E402
from global_index.deploy_sim import metrics  # noqa: E402
from global_index.net_exposure_multi import Position, entry_priority_key  # noqa: E402
from scratch.normal_sleeve_fill_audit import ACCOUNT  # noqa: E402

OUT_DEFAULT = "scratch/track1_book_bootstrap_20260822.json"


def use_variant(which: str, variant: str) -> None:
    """Point the book at one of the 2x2 variant trade tables.

    Both the committed `replay_repaired` and the re-host read the same module-level path
    table, so the equivalence gate keeps its meaning under a swap: the two are still being
    fed identical inputs. The per-window cache has to be dropped or the swap is silent.
    """
    import json as _json

    import scratch.stress_switch_full_replay_20260822 as _full
    src = Path("scratch/track1_variants_20260822") / f"{which}__{variant}.json"
    if not src.exists():
        raise SystemExit(f"variant table not built: {src}")
    payload = _json.loads(src.read_text(encoding="utf-8"))
    ref = _json.loads(Path(
        f"scratch/normal_promotion_trades_{which}_20260821.json").read_text(encoding="utf-8"))
    ref["filtered"] = payload["trades"]
    out = src.parent / "committed_shape" / f"{which}__{variant}__committed_shape.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json.dumps(ref, indent=1), encoding="utf-8")
    _full.NORMAL_PROMOTION_FILES[which] = out
    calm_a_base.DATA_CACHE.pop(which, None)


def _day(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return (t.tz_localize(None) if t.tz is not None else t).normalize()


# ---------------------------------------------------------------------------
# the re-hosted loop
# ---------------------------------------------------------------------------
def replay(which: str, policy, *, resume: dict | None = None,
           stop_after: pd.Timestamp | None = None) -> tuple[pd.Series, dict, dict, list]:
    """Returns (daily, stats, end_state, events).

    `events` is the ordered list of settlements — the ordered trade list the equivalence
    proof compares. Counting trades or summing P&L would let two different books with the
    same total pass as equal.
    """
    r4, current_nkd, prices, extra, stress, calm_nkd_df = audit.load_all(which)
    calm_a = comb.load_calm_a_atr15(which, extra["meta"])
    if not policy.include_calm_nkd_switch:
        calm_nkd_df = calm_nkd_df.iloc[0:0]
    guard = comb.make_guard()
    breaker = full.CircuitBreaker(account=ACCOUNT)

    open_pos: list[tuple[Position, dict]] = []
    realized: dict[pd.Timestamp, float] = {}
    booked: dict[str, int] = {}
    equity = ACCOUNT
    cur_day = None
    st = {"taken": {c: 0 for c in guard.clusters},
          "rejected": {c: 0 for c in guard.clusters},
          "family_rejected": 0, "halted": 0, "stress_closed_r4": 0,
          "stress_closed_calm": 0, "stress_switch_delta": 0.0,
          "calm_closed_current_nkd": 0, "calm_switch_delta": 0.0,
          "suppressed_current_nkd": 0, "suppressed_current_nkd_pnl": 0.0,
          "suppressed_calm_same_symbol": 0, "suppressed_calm_pnl": 0.0,
          "suppressed_normal_same_symbol": 0, "suppressed_normal_pnl": 0.0,
          "double_booked": 0}

    entries = pd.concat([p for p in (r4, stress, current_nkd, calm_nkd_df, calm_a)
                         if not p.empty], ignore_index=True)
    by_trade_id = {}
    by_time: dict[pd.Timestamp, list[dict]] = {}
    times = set()
    for _, row in entries.iterrows():
        tr = row.to_dict()
        by_trade_id[tr.get("trade_id")] = tr
        by_time.setdefault(pd.Timestamp(tr["entry_time"]), []).append(tr)
        times.add(pd.Timestamp(tr["entry_time"]))
        times.add(pd.Timestamp(tr["exit_time"]))

    # The cut is an ABSOLUTE INSTANT, never a calendar day. The loop runs in absolute order
    # while `_day()` strips the timezone without converting, so a Tokyo-dated MNKD event can
    # carry the NEXT local date while occurring EARLIER than that afternoon's ET events. A
    # day-keyed cut therefore is not a prefix of the sequence: on floor it left two events on
    # 2022-01-10 in neither half, and the resumed book silently skipped a Stress override.
    cut_instant = None
    if stop_after is not None:
        st_ts = pd.Timestamp(stop_after)
        if st_ts == st_ts.normalize():
            # A bare date means "the last event still inside that local day".
            elig = [t for t in times if _day(t) <= _day(st_ts)]
        else:
            # An explicit instant is used as given, which is the only way to place a cut
            # INSIDE a trading day — needed to exercise anything the next start_day() resets.
            elig = [t for t in times if t <= st_ts]
        if not elig:
            raise SystemExit(f"cut {stop_after} precedes every event in {which}")
        cut_instant = max(elig)

    resume_from = None
    if resume is not None:
        # Rebuild every carried value. A missing one here is not a rounding difference: the
        # breaker would resume from the wrong peak and refuse or allow a whole day of entries.
        equity = float(resume["equity"])
        cur_day = pd.Timestamp(resume["cur_day"]) if resume.get("cur_day") else None
        breaker.peak_equity = float(resume["peak_equity"])
        breaker._day_start_equity = (None if resume.get("day_start_equity") is None
                                     else float(resume["day_start_equity"]))
        booked = dict(resume.get("booked", {}))
        for h in resume["open_pos"]:
            tr = by_trade_id[h["trade_id"]]
            open_pos.append((Position(h["instrument"], h["direction"], int(h["qty"]),
                                      float(h["risk"]), h["cluster"]), tr))
        if not resume.get("cut_instant"):
            raise SystemExit("bootstrap has no cut_instant — it was written by the old "
                             "day-keyed cut and cannot be resumed correctly")
        resume_from = pd.Timestamp(resume["cut_instant"])

    events: list[dict] = []

    def book(ts, tr, pnl: float):
        nonlocal equity
        d = _day(ts)
        equity += float(pnl)
        realized[d] = realized.get(d, 0.0) + float(pnl)
        tid = tr.get("trade_id", "?")
        booked[tid] = booked.get(tid, 0) + 1
        if booked[tid] > 1:
            st["double_booked"] += 1
        events.append({"ts": str(ts), "trade_id": tid, "cluster": tr.get("cluster"),
                       "instrument": tr.get("instrument"), "pnl": round(float(pnl), 6)})

    end_state = None
    for ts in sorted(times):
        if resume_from is not None and ts <= resume_from:
            continue
        day = _day(ts)
        if cut_instant is not None and ts > cut_instant:
            break
        if cur_day is None or day != cur_day:
            breaker.start_day(equity)
            cur_day = day
        still = []
        for pos, tr in open_pos:
            if pd.Timestamp(tr["exit_time"]) <= ts:
                book(ts, tr, float(tr["pnl_sized"]))
            else:
                still.append((pos, tr))
        open_pos = still
        breaker.update(equity)
        allow = breaker.status(equity).get("allow_new_entries", True)

        for tr in sorted(by_time.get(ts, []), key=entry_priority_key):
            if not allow:
                st["halted"] += 1
                continue
            src, inst, cluster = tr["source"], tr["instrument"], tr["cluster"]
            open_positions = [p for p, _ in open_pos]

            if src == "normal_nkd_filtered_bucket" and any(
                    t["source"] == "calm_nkd" for _, t in open_pos):
                st["suppressed_current_nkd"] += 1
                st["suppressed_current_nkd_pnl"] += float(tr["pnl_sized"])
                continue

            if src == "calm_nkd":
                survivors = [(p, t) for p, t in open_pos
                             if not (p.instrument == "MNKD"
                                     and t["source"] == "normal_nkd_filtered_bucket")]
                proposed = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(proposed, [p for p, _ in survivors])
                if not ok:
                    st["rejected"][cluster] += 1
                    continue
                for _, old in [(p, t) for p, t in open_pos
                               if p.instrument == "MNKD"
                               and t["source"] == "normal_nkd_filtered_bucket"]:
                    ep = calm_nkd.early_nkd_pnl(old, float(tr["entry"]) + comb.OFFSET[which])
                    book(ts, old, ep)
                    st["calm_closed_current_nkd"] += 1
                    st["calm_switch_delta"] += ep - float(old["pnl_sized"])
                open_pos = survivors
                st["taken"][cluster] += 1
                open_pos.append((proposed, tr))
                continue

            if src == "calm_a_pcloc_not_deep":
                if any(p.instrument == inst and p.cluster in ("roska4_swing", "roska4_stress")
                       for p, _ in open_pos):
                    st["suppressed_calm_same_symbol"] += 1
                    st["suppressed_calm_pnl"] += float(tr["pnl_sized"])
                    continue
                pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(pos, open_positions)
                if ok and not comb.family_admits(pos, open_positions, policy):
                    ok = False
                    st["family_rejected"] += 1
                if ok:
                    st["taken"][cluster] += 1
                    open_pos.append((pos, tr))
                else:
                    st["rejected"][cluster] += 1
                continue

            if cluster == "roska4_stress":
                survivors = [(p, t) for p, t in open_pos
                             if not (p.instrument == inst
                                     and p.cluster in ("roska4_swing", "roska4_calm"))]
                proposed = Position(inst, tr["direction"], int(tr.get("qty", 1)),
                                    float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(proposed, [p for p, _ in survivors])
                if not ok:
                    st["rejected"][cluster] += 1
                    continue
                for p, old in [(p, t) for p, t in open_pos
                               if p.instrument == inst
                               and p.cluster in ("roska4_swing", "roska4_calm")]:
                    px = full.price_at_or_after(prices[inst], ts)
                    if px is None:
                        continue
                    if p.cluster == "roska4_calm":
                        ep = calm_a_base.early_calm_pnl(old, px, 2.0)
                        st["stress_closed_calm"] += 1
                    else:
                        ep = full.early_pnl(old, px, full.costs_for_basket(slippage_ticks=2.0))
                        st["stress_closed_r4"] += 1
                        st["stress_switch_delta"] += ep - float(old["pnl_sized"])
                    book(ts, old, ep)
                open_pos = survivors
                st["taken"][cluster] += 1
                open_pos.append((proposed, tr))
                continue

            if cluster == "roska4_swing":
                if any(p.instrument == inst and p.cluster in ("roska4_stress", "roska4_calm")
                       for p, _ in open_pos):
                    st["suppressed_normal_same_symbol"] += 1
                    st["suppressed_normal_pnl"] += float(tr["pnl_sized"])
                    continue
                pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(pos, open_positions)
                if ok and not comb.family_admits(pos, open_positions, policy):
                    ok = False
                    st["family_rejected"] += 1
                if ok:
                    st["taken"][cluster] += 1
                    open_pos.append((pos, tr))
                else:
                    st["rejected"][cluster] += 1
                continue

            pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
            ok, _ = guard.admits(pos, open_positions)
            if ok:
                st["taken"][cluster] += 1
                open_pos.append((pos, tr))
            else:
                st["rejected"][cluster] += 1

    if stop_after is not None:
        end_state = snapshot(which, policy, _day(stop_after), open_pos, equity, breaker,
                             booked, realized, st, cut_instant=cut_instant)
    if end_state is None:
        end_state = snapshot(which, policy, cur_day, open_pos, equity, breaker,
                             booked, realized, st)
    return pd.Series(realized).sort_index(), st, end_state, events


def snapshot(which, policy, day, open_pos, equity, breaker, booked, realized, st,
             cut_instant=None) -> dict:
    return {
        "schema": 2, "route": "track1_candidate", "window": which,
        "policy": policy.name, "cut": None if day is None else str(pd.Timestamp(day).date()),
        # The value a resume actually splits on. `cut` is the human-readable label.
        "cut_instant": None if cut_instant is None else str(cut_instant),
        "equity": float(equity),
        "peak_equity": float(breaker.peak_equity),
        "day_start_equity": (None if breaker._day_start_equity is None
                             else float(breaker._day_start_equity)),
        "cur_day": None if day is None else str(pd.Timestamp(day).date()),
        "open_pos": [{"trade_id": t.get("trade_id"), "instrument": p.instrument,
                      "direction": p.direction, "qty": int(p.contracts),
                      "risk": float(p.risk_dollars),
                      "cluster": p.cluster, "source": t.get("source"),
                      "exit_time": str(t.get("exit_time"))}
                     for p, t in open_pos],
        "booked": dict(booked),
        "realized_to_date": round(float(sum(realized.values())), 6),
        "sleeves_open": {c: sum(1 for p, _ in open_pos if p.cluster == c)
                         for c in ("roska4_swing", "global_nkd", "roska4_calm",
                                   "roska4_stress")},
    }


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------
def equivalence_gate(windows) -> dict:
    """The re-host must equal the committed function before it is allowed to prove anything."""
    rows = []
    for which in windows:
        for pol in comb.POLICIES:
            calm_a_base.DATA_CACHE.pop(which, None)
            d_ref, st_ref = comb.replay_repaired(which, pol)
            calm_a_base.DATA_CACHE.pop(which, None)
            d_new, st_new, _, ev = replay(which, pol)
            same_daily = (len(d_ref) == len(d_new)
                          and bool((d_ref.round(6).values == d_new.round(6).values).all())
                          and list(d_ref.index) == list(d_new.index))
            rows.append({"window": which, "policy": pol.name,
                         "days": int(len(d_ref)), "events": len(ev),
                         "daily_same": same_daily, "stats_same": st_ref == st_new,
                         "net_ref": float(d_ref.sum()), "net_new": float(d_new.sum())})
    return {"rows": rows,
            "all_ok": all(r["daily_same"] and r["stats_same"] for r in rows)
                      and all(r["events"] > 0 for r in rows)}


def _ev_key(e) -> tuple:
    return (e["ts"], e["trade_id"], e["cluster"], e["instrument"], f"{e['pnl']:.6f}")


def reproduce(which: str, policy, cut: str) -> dict:
    """Full Track 1 vs resume-from-bootstrap Track 1."""
    calm_a_base.DATA_CACHE.pop(which, None)
    d_full, st_full, end_full, ev_full = replay(which, policy)

    calm_a_base.DATA_CACHE.pop(which, None)
    _dh, _sh, boot, ev_head = replay(which, policy, stop_after=pd.Timestamp(cut))

    calm_a_base.DATA_CACHE.pop(which, None)
    d_res, st_res, end_res, ev_res = replay(which, policy, resume=boot)

    # Filter on the same instant the split used. Filtering on the day here would re-introduce
    # the bug the split just fixed, one layer up.
    ci = pd.Timestamp(boot["cut_instant"])
    exp = [e for e in ev_full if pd.Timestamp(e["ts"]) > ci]
    got = list(ev_res)
    first = next((i for i in range(max(len(exp), len(got)))
                  if (_ev_key(exp[i]) if i < len(exp) else None)
                  != (_ev_key(got[i]) if i < len(got) else None)), None)

    m_full_tail = metrics(d_full[d_full.index > _day(ci)])
    m_res = metrics(d_res)
    return {
        "window": which, "policy": policy.name, "cut": cut,
        "bootstrap": boot,
        "events_expected": len(exp), "events_resumed": len(got),
        "events_exact": [_ev_key(e) for e in exp] == [_ev_key(e) for e in got],
        "first_event_diff": first,
        "open_pos_exact": (sorted(json.dumps(p, sort_keys=True) for p in end_full["open_pos"])
                           == sorted(json.dumps(p, sort_keys=True) for p in end_res["open_pos"])),
        "equity_full": end_full["equity"], "equity_resumed_plus_head":
            round(boot["equity"] + m_res["pnl"], 6),
        "metrics_full_tail": m_full_tail, "metrics_resumed": m_res,
        "metrics_exact": all(abs(m_full_tail[k] - m_res[k]) < 1e-6
                             for k in ("pnl", "maxdd")),
        "net_full_window": float(d_full.sum()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["vault2026"])
    ap.add_argument("--cut", default="2026-05-29")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--variant", default=None,
                    help="swap in one of the 2x2 variant tables, e.g. production_gate_on")
    a = ap.parse_args()

    if a.variant:
        for w in a.which:
            use_variant(w, a.variant)
        print("variant in force: " + a.variant)
        print()

    print("EQUIVALENCE GATE — the re-hosted loop against the committed one")
    gate = equivalence_gate(a.which)
    for r in gate["rows"]:
        print(f"  {'OK ' if r['daily_same'] and r['stats_same'] else 'XX '}"
              f"{r['window']:10s} {r['policy'][:34]:34s} days={r['days']:4d} "
              f"events={r['events']:4d} net={r['net_new']:>10,.0f}")
    if not gate["all_ok"]:
        print("\nREFUSED: the re-host is not the committed book. Nothing below would mean "
              "anything.")
        return 1
    print("  gate passed\n")

    out = {"gate": gate, "runs": []}
    for which in a.which:
        for pol in comb.POLICIES:
            r = reproduce(which, pol, a.cut)
            out["runs"].append(r)
            ok = r["events_exact"] and r["open_pos_exact"] and r["metrics_exact"]
            print(f"  {'OK ' if ok else 'XX '}{which:10s} {pol.name[:34]:34s} "
                  f"cut={a.cut} events {r['events_resumed']}/{r['events_expected']} "
                  f"pos={'exact' if r['open_pos_exact'] else 'DIFF'} "
                  f"net_tail={r['metrics_resumed']['pnl']:>9,.0f}"
                  + ("" if ok else f"  first diff at {r['first_event_diff']}"))
    Path(a.out).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(f"\n{a.out}")
    return 0 if all(r["events_exact"] and r["open_pos_exact"] and r["metrics_exact"]
                    for r in out["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
