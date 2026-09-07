"""Stop / risk audit of the combined research candidate (2026-08-22).

SCRATCH-ONLY. Reads production code and captured artifacts; writes only under
scratch/. Nothing in futures/, global_index/, raits/ is modified.

ANCHOR GATE (section 0). This script re-implements the combined replay so it can
instrument it. A self-written replay is worthless until it reproduces a number
somebody else already published, so section 0 rebuilds two published rows and
refuses to print anything downstream unless both match to the dollar:

  floor  R4-only                       net +$29,046   MaxDD $6,209
  floor  combined skip_same_symbol 5%  net +$72,732   MaxDD $4,923

Usage:
  python scratch/combined_stop_risk_audit_20260822.py --which floor vault2025 vault2026
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.calm_a_combined_replay_20260822 as calm_a_base
import scratch.calm_a_disaster_stop_probe_20260822 as dis
import scratch.calm_nkd_switch_vs_current_20260822 as calm_nkd
import scratch.stress_switch_full_replay_20260822 as full
import scratch.stress_with_nkd_probe_20260822 as nkd_base
from futures.basket import BASKET
from futures._validated_core import daily_atr_series
from futures.circuit_breaker import CircuitBreaker
from global_index import specs as gi_specs
from global_index.deploy_sim import metrics
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard, Position, entry_priority_key
from scratch.normal_sleeve_fill_audit import ACCOUNT, R4, _real_risk

OUT_MD = Path("scratch/combined_stop_risk_audit_20260822_report.md")
OUT_JSON = Path("scratch/combined_stop_risk_audit_20260822.json")

ANCHORS = {"r4_only_net": 29046.0, "r4_only_dd": 6209.0,
           "combined_net": 72732.0, "combined_dd": 4923.0}

# stop_basis used when the Normal / current-NKD artifacts were generated
# (scratch/normal_promotion_regen_audit_20260821.py:110 -> Cfg(..., stop_basis=2.0))
ARTIFACT_STOP_BASIS = 2.0
ARTIFACT_RISK_MULT = 2.5        # scratch/normal_promotion_variant_matrix_20260821.py:80
ARM_HOURS = 14 + 5 / 60         # scratch/harness.py ARM_LIVE


def money(x):
    return f"${x:,.0f}"


def pct(x):
    return f"{100 * x:.1f}%"


def f2(x):
    if x is None:
        return "n/a"
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return "inf" if math.isinf(x) else "n/a"
    return f"{x:.2f}"


def tbl(rows, cols):
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def naive(ts):
    t = pd.Timestamp(ts)
    return t.tz_localize(None) if t.tzinfo is not None else t


# ---------------------------------------------------------------------------
# instrumented combined replay (mirror of calm_a_combined_replay.replay)
# ---------------------------------------------------------------------------
def make_guard(calm_cap: float) -> MultiClusterGuard:
    return MultiClusterGuard(clusters={
        "roska4_swing": ClusterBudget("roska4_swing", 0.050, 0.044),
        "roska4_stress": ClusterBudget("roska4_stress", 0.10, None),
        "global_nkd": ClusterBudget("global_nkd", 0.060, 0.060),
        "roska4_calm": ClusterBudget("roska4_calm", calm_cap, None),
    }, account=ACCOUNT)


def load_all(which):
    if which not in calm_a_base.DATA_CACHE:
        r4, current_nkd, prices, extra = nkd_base.load_r4_and_nkd(which)
        stress = extra["stress"]
        calm_nkd_df = calm_nkd.load_calm_nkd(which, extra["meta"])
        calm_a_base.DATA_CACHE[which] = (r4, current_nkd, prices, extra, stress, calm_nkd_df)
    return calm_a_base.DATA_CACHE[which]


def instrumented_replay(which, calm_cap=0.05, overlap="skip_same_symbol", slip=2.0,
                        calm_df=None, include_calm=True):
    """Same control flow as calm_a_combined_replay.replay, plus a ledger of every
    booked cashflow and every simultaneous same-symbol pair."""
    r4, current_nkd, prices, extra, stress, calm_nkd_df = load_all(which)
    calm_a = (calm_df if calm_df is not None
              else calm_a_base.load_calm_a(which, extra["meta"], slip))
    if not include_calm:
        calm_a = calm_a.iloc[0:0]
    guard = make_guard(calm_cap)
    breaker = CircuitBreaker(account=ACCOUNT)
    realized, open_pos, equity, cur_day = {}, [], ACCOUNT, None
    st = {"taken": {c: 0 for c in guard.clusters}, "rejected": {c: 0 for c in guard.clusters},
          "halted": 0, "stress_closed_r4": 0, "stress_closed_calm": 0,
          "calm_closed_current_nkd": 0, "suppressed_current_nkd": 0,
          "suppressed_current_nkd_pnl": 0.0, "suppressed_calm_same_symbol": 0,
          "suppressed_calm_pnl": 0.0, "suppressed_normal_by_stress": 0,
          "suppressed_normal_by_stress_pnl": 0.0, "stress_switch_delta": 0.0,
          "calm_switch_delta": 0.0, "forced_close_missing_price": 0,
          "forced_close_missing_pnl": 0.0, "double_booked": 0, "double_booked_pnl": 0.0}
    ledger = []
    booked_ids = {}

    pieces = [p for p in (r4, stress, current_nkd, calm_nkd_df, calm_a)
              if p is not None and not p.empty]
    entries = pd.concat(pieces, ignore_index=True)
    by_time, times = {}, set()
    for _, r in entries.iterrows():
        o = r.to_dict()
        ets, xts = pd.Timestamp(o["entry_time"]), pd.Timestamp(o["exit_time"])
        by_time.setdefault(ets, []).append(o)
        times.add(ets)
        times.add(xts)

    def book(ts, tr, kind, pnl):
        nonlocal equity
        equity += float(pnl)
        d = naive(ts).normalize()
        realized[d] = realized.get(d, 0.0) + float(pnl)
        tid = tr.get("trade_id", "?")
        booked_ids[tid] = booked_ids.get(tid, 0) + 1
        ledger.append((str(ts), tid, kind, float(pnl)))
        if booked_ids[tid] > 1:
            st["double_booked"] += 1
            st["double_booked_pnl"] += float(pnl)

    overlaps = []

    def note_overlap(ts, newpos, newtr):
        for p, t in open_pos:
            if p.instrument == newtr["instrument"]:
                overlaps.append(dict(ts=str(ts), inst=p.instrument,
                                     held_src=t["source"], held_dir=t["direction"],
                                     held_cluster=p.cluster, new_src=newtr["source"],
                                     new_dir=newtr["direction"], new_cluster=newpos.cluster,
                                     opposite=int(t["direction"] != newtr["direction"]),
                                     cross_cluster=int(p.cluster != newpos.cluster)))

    for ts in sorted(times):
        day = naive(ts).normalize()
        if cur_day is None or day != cur_day:
            breaker.start_day(equity)
            cur_day = day
        still = []
        for pos, tr in open_pos:
            if pd.Timestamp(tr["exit_time"]) <= ts:
                book(ts, tr, "exit", float(tr["pnl_sized"]))
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

            if src == "normal_nkd_filtered_bucket" and any(t["source"] == "calm_nkd" for _, t in open_pos):
                st["suppressed_current_nkd"] += 1
                st["suppressed_current_nkd_pnl"] += float(tr["pnl_sized"])
                continue

            if src == "calm_nkd":
                survivors = [(p, t) for p, t in open_pos
                             if not (p.instrument == "MNKD" and t["source"] == "normal_nkd_filtered_bucket")]
                proposed = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(proposed, [p for p, _ in survivors])
                if not ok:
                    st["rejected"][cluster] += 1
                    continue
                for _, old in [(p, t) for p, t in open_pos
                               if p.instrument == "MNKD" and t["source"] == "normal_nkd_filtered_bucket"]:
                    ep = calm_nkd.early_nkd_pnl(old, float(tr["entry"]))
                    book(ts, old, "forced_close_by_calm_nkd", ep)
                    st["calm_closed_current_nkd"] += 1
                    st["calm_switch_delta"] += ep - float(old["pnl_sized"])
                open_pos = survivors
                note_overlap(ts, proposed, tr)
                st["taken"][cluster] += 1
                open_pos.append((proposed, tr))
                continue

            if src == "calm_a_pcloc_not_deep":
                if overlap in ("skip_same_symbol", "stress_overrides_calm"):
                    if any(p.instrument == inst and p.cluster in ("roska4_swing", "roska4_stress")
                           for p, _ in open_pos):
                        st["suppressed_calm_same_symbol"] += 1
                        st["suppressed_calm_pnl"] += float(tr["pnl_sized"])
                        continue
                pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(pos, [p for p, _ in open_pos])
                if ok:
                    note_overlap(ts, pos, tr)
                    st["taken"][cluster] += 1
                    open_pos.append((pos, tr))
                else:
                    st["rejected"][cluster] += 1
                continue

            if cluster == "roska4_stress":
                survivors = [(p, t) for p, t in open_pos if not (
                    p.instrument == inst and (
                        p.cluster == "roska4_swing"
                        or (overlap == "stress_overrides_calm" and p.cluster == "roska4_calm")))]
                proposed = Position(inst, tr["direction"], int(tr.get("qty", 1)),
                                    float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(proposed, [p for p, _ in survivors])
                if not ok:
                    st["rejected"][cluster] += 1
                    continue
                closing = [(p, t) for p, t in open_pos
                           if p.instrument == inst and p.cluster in ("roska4_swing", "roska4_calm")]
                for p, old in closing:
                    px = full.price_at_or_after(prices[inst], ts)
                    if px is None:
                        st["forced_close_missing_price"] += 1
                        st["forced_close_missing_pnl"] += float(old["pnl_sized"])
                        continue
                    if p.cluster == "roska4_calm":
                        ep = calm_a_base.early_calm_pnl(old, px, slip)
                        st["stress_closed_calm"] += 1
                    else:
                        ep = full.early_pnl(old, px, full.costs_for_basket(slippage_ticks=2.0))
                        st["stress_closed_r4"] += 1
                        st["stress_switch_delta"] += ep - float(old["pnl_sized"])
                    book(ts, old, "forced_close_by_stress", ep)
                open_pos = survivors
                note_overlap(ts, proposed, tr)
                st["taken"][cluster] += 1
                open_pos.append((proposed, tr))
                continue

            if cluster == "roska4_swing" and any(p.instrument == inst and p.cluster == "roska4_stress"
                                                 for p, _ in open_pos):
                st["suppressed_normal_by_stress"] += 1
                st["suppressed_normal_by_stress_pnl"] += float(tr["pnl_sized"])
                continue

            pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
            ok, _ = guard.admits(pos, [p for p, _ in open_pos])
            if ok:
                note_overlap(ts, pos, tr)
                st["taken"][cluster] += 1
                open_pos.append((pos, tr))
            else:
                st["rejected"][cluster] += 1

    return pd.Series(realized).sort_index(), st, ledger, overlaps, entries


# ---------------------------------------------------------------------------
# section 0 - anchor gate
# ---------------------------------------------------------------------------
def anchor_gate(which="floor"):
    checks = []
    r4 = load_all(which)[0]
    d0, _ = full.replay_intraday(r4, r4.iloc[0:0], {}, 0.10)
    m0 = metrics(d0)
    checks.append(("SC1 R4-only net", round(m0["pnl"]), ANCHORS["r4_only_net"]))
    checks.append(("SC2 R4-only MaxDD", round(m0["maxdd"]), ANCHORS["r4_only_dd"]))
    d1, st1, ledger, ov, entries = instrumented_replay(which, 0.05, "skip_same_symbol", 2.0)
    m1 = metrics(d1)
    checks.append(("SC3 combined net", round(m1["pnl"]), ANCHORS["combined_net"]))
    checks.append(("SC4 combined MaxDD", round(m1["maxdd"]), ANCHORS["combined_dd"]))
    checks.append(("SC5 ledger sum == daily sum", round(sum(x[3] for x in ledger), 2),
                   round(float(d1.sum()), 2)))
    checks.append(("SC6 entries non-empty", int(len(entries) > 0), 1))
    checks.append(("SC7 calm A legs present", int(st1["taken"]["roska4_calm"] > 0), 1))
    ok = all(abs(float(a) - float(b)) <= 1.0 for _, a, b in checks)
    return ok, checks, (d1, st1, ledger, ov, entries)


# ---------------------------------------------------------------------------
# section 1/2 - stop existence, declared risk vs true stop risk
# ---------------------------------------------------------------------------
def sleeve_frames(which):
    r4, current_nkd, prices, extra, stress, calm_nkd_df = load_all(which)
    calm_a = calm_a_base.load_calm_a(which, extra["meta"], 2.0)
    return dict(normal_r4=r4, current_nkd=current_nkd, calm_nkd=calm_nkd_df,
                stress=stress, calm_a=calm_a), extra, prices


def raw_reasons(which):
    """reason field per instrument straight from the promotion artifact."""
    raw = json.loads(full.NORMAL_PROMOTION_FILES[which].read_text(encoding="utf-8"))
    out = {}
    for inst, lst in raw["filtered"].items():
        for t in lst:
            out.setdefault(inst, []).append(t)
    return out, raw


def stop_distance_check(which, extra):
    """Falsifiable check of the claim 'Normal / current-NKD stop is a FIXED stop at
    stop_basis x daily ATR anchored on the entry price'.

    If true, every CHANDELIER exit must sit at entry -+ 2.0 x daily ATR to within
    rounding. If the engine were ratcheting, or the stop were the 2.5 x 5-min-ATR
    engine default, this check goes red."""
    per_inst, raw = raw_reasons(which)
    meta = extra["meta"]
    rows = []
    for inst, lst in per_inst.items():
        m = meta[inst]
        ratios = []
        for t in lst:
            if t["reason"] != "CHANDELIER":
                continue
            ed = naive(pd.Timestamp(t["day"]))
            da = m["atr"].asof(ed)
            if da is None or pd.isna(da) or float(da) <= 0:
                continue
            dist = abs(float(t["entry"]) - float(t["exit"]))
            ratios.append(dist / float(da))
        if not ratios:
            continue
        a = np.array(ratios)
        rows.append(dict(inst=inst, n=len(a), median=float(np.median(a)),
                         p10=float(np.percentile(a, 10)), p90=float(np.percentile(a, 90)),
                         within_1pct=int(np.sum(np.abs(a - ARTIFACT_STOP_BASIS) <= 0.01 * ARTIFACT_STOP_BASIS))))
    return rows


def calm_nkd_stop_distance(which):
    src = pd.read_csv(calm_nkd.CALM_NKD_TRADES)
    src = src[(src["window"] == calm_nkd.WINDOW_MAP[which]) & (src["variant"] == calm_nkd.VARIANT)]
    if src.empty:
        return None
    _, _, _, extra, _, _ = load_all(which)
    m = extra["meta"]["MNKD"]
    ratios, dists = [], []
    for _, t in src.iterrows():
        if t["reason"] not in ("CHANDELIER", "GAP"):
            continue
        ed = naive(pd.Timestamp(t["day"]))
        da = m["atr"].asof(ed)
        if da is None or pd.isna(da) or float(da) <= 0:
            continue
        dist = abs(float(t["entry"]) - float(t["exit"]))
        ratios.append(dist / float(da))
        dists.append(dist * m["pv"])
    a = np.array(ratios)
    return dict(n=int(len(a)), median_x_datr=float(np.median(a)),
                p90_x_datr=float(np.percentile(a, 90)),
                median_loss_dollars=float(np.median(dists)))


def risk_vs_realized(df, label, risk_col="risk_sized", pnl_col="pnl_sized"):
    if df is None or df.empty:
        return dict(sleeve=label, n=0)
    r = df[risk_col].astype(float)
    p = df[pnl_col].astype(float)
    loss = -p.clip(upper=0.0)
    over = loss > r
    worst = float((loss / r).max()) if len(r) else float("nan")
    return dict(sleeve=label, n=int(len(df)),
                med_risk=float(r.median()), p90_risk=float(r.quantile(0.90)),
                max_risk=float(r.max()), max_loss=float(loss.max()),
                n_over=int(over.sum()), pct_over=float(over.mean()),
                worst_ratio=worst)


# ---------------------------------------------------------------------------
# section 3 - unfillable-stop / gap-through replication of harness _correct
# ---------------------------------------------------------------------------
def unfillable_stop_scan(which, extra):
    """Replicate scratch/harness.py::_correct on the promotion artifact.

    _correct exists because the arming model only MASKS stop hits before the arm
    instant; the first bar at/after arming still books a fill at the stop price
    even when the market is already through it. fix_fill was False when the
    artifacts were generated, so the candidate book contains those fills."""
    from futures._validated_core import _swing_cache
    import scratch.normal_promotion_variant_matrix_20260821 as vm
    raw = json.loads(full.NORMAL_PROMOTION_FILES[which].read_text(encoding="utf-8"))
    frames = vm.load_frames(raw)
    meta = extra["meta"]
    out = []
    for inst, lst in raw["filtered"].items():
        df = frames[inst]
        cache = _swing_cache(df, daily_atr_series(df))
        ts_map, hl = cache.get("ts", {}), cache["hl"]
        pv = meta[inst]["pv"]
        n, tot, worst = 0, 0.0, 0.0
        # funnel counters - a zero result is only meaningful if the funnel is non-empty
        n_next_day = n_at_arm_bar = n_w_le0 = 0
        arm_gaps = []
        for t in lst:
            if t["reason"] != "CHANDELIER":
                continue
            d0 = naive(pd.Timestamp(t["day"])).normalize()
            d1 = naive(pd.Timestamp(t["exit_day"])).normalize()
            if d1 != d0 + pd.Timedelta(days=1):
                continue
            n_next_day += 1
            dts = ts_map.get(d1)
            if dts is None or not len(dts):
                continue
            nv = dts.tz_localize(None) if dts.tz is not None else dts
            arm = d1 + pd.Timedelta(hours=ARM_HOURS)
            j = int(np.searchsorted(np.asarray(nv), np.datetime64(arm)))
            et = t.get("exit_time")
            if j >= len(nv) or et is None:
                continue
            et = naive(pd.Timestamp(et))
            if et != pd.Timestamp(nv[j]):
                arm_gaps.append(str(et - pd.Timestamp(nv[j])))
                continue
            n_at_arm_bar += 1
            op = float(hl[d1][2][j])
            stp = float(t["exit"])
            w = (stp - op) if t["direction"] == "LONG" else (op - stp)
            if w > 0:
                n += 1
                tot += w * pv
                worst = max(worst, w * pv)
            else:
                n_w_le0 += 1
        out.append(dict(inst=inst, n_unfillable=n, dollars=tot, worst=worst,
                        n_chandelier=sum(1 for t in lst if t["reason"] == "CHANDELIER"),
                        n_exit_next_day=n_next_day, n_exit_at_arm_bar=n_at_arm_bar,
                        n_arm_bar_open_not_through=n_w_le0,
                        sample_offsets=arm_gaps[:5]))
    return out


def stop_fill_feasibility(which, extra):
    """Direct, engine-independent version of the same question: for every stop exit
    booked at the stop price, was the market already through the stop at the moment
    the stop is armed? Independent of _correct's exit_day == day+1 restriction."""
    import scratch.normal_promotion_variant_matrix_20260821 as vm
    raw = json.loads(full.NORMAL_PROMOTION_FILES[which].read_text(encoding="utf-8"))
    frames = vm.load_frames(raw)
    meta = extra["meta"]
    rows = []
    for inst, lst in raw["filtered"].items():
        df = frames[inst]
        pv = meta[inst]["pv"]
        n_stop = n_through = 0
        dollars = 0.0
        worst = 0.0
        for t in lst:
            if t["reason"] not in ("CHANDELIER",):
                continue
            n_stop += 1
            xt = pd.Timestamp(t["exit_time"])
            if xt.tzinfo is None and df.index.tz is not None:
                xt = xt.tz_localize(df.index.tz)
            bar = df[df.index == xt]
            if bar.empty:
                continue
            op = float(bar.iloc[0]["open"])
            stp = float(t["exit"])
            w = (stp - op) if t["direction"] == "LONG" else (op - stp)
            if w > 1e-9:
                n_through += 1
                dollars += w * pv
                worst = max(worst, w * pv)
        rows.append(dict(inst=inst, n_stop_exits=n_stop, n_bar_opened_through=n_through,
                         dollars=dollars, worst=worst))
    return rows


def risk_breach_detail(df, label, top=6):
    if df is None or df.empty:
        return []
    d = df.copy()
    d["_loss"] = -d["pnl_sized"].astype(float).clip(upper=0.0)
    d["_ratio"] = d["_loss"] / d["risk_sized"].astype(float)
    d = d[d["_ratio"] > 1.0].sort_values("_ratio", ascending=False).head(top)
    return [dict(sleeve=label, trade_id=r.get("trade_id"), inst=r["instrument"],
                 direction=r["direction"], day=str(r["day"]),
                 reason=str(r.get("exit_reason", "")), entry=float(r["entry"]),
                 exit=float(r["exit"]), stop=(float(r["stop"]) if pd.notna(r.get("stop", np.nan)) else None),
                 risk=float(r["risk_sized"]), loss=float(r["_loss"]),
                 ratio=float(r["_ratio"])) for _, r in d.iterrows()]


def sleeve_standalone(df, label):
    if df is None or df.empty:
        return dict(sleeve=label, n=0)
    p = df["pnl_sized"].astype(float)
    w = p[p > 0].sum()
    l = -p[p < 0].sum()
    return dict(sleeve=label, n=int(len(p)), net=float(p.sum()),
                pf=(float(w / l) if l > 1e-9 else float("inf")),
                win_rate=float((p > 0).mean()), med_win=float(p[p > 0].median()) if (p > 0).any() else 0.0,
                med_loss=float(p[p < 0].median()) if (p < 0).any() else 0.0,
                max_loss=float(p.min()))


# ---------------------------------------------------------------------------
# section 5 - MAE / MFE for the intraday sleeves
# ---------------------------------------------------------------------------
def intraday_mae_mfe(which, sleeve, df, frames):
    rows = []
    for _, t in df.iterrows():
        inst = t["instrument"]
        g = frames.get(inst)
        if g is None:
            continue
        e0, e1 = pd.Timestamp(t["entry_time"]), pd.Timestamp(t["exit_time"])
        if e0.tzinfo is None and g.index.tz is not None:
            e0 = e0.tz_localize(g.index.tz)
            e1 = e1.tz_localize(g.index.tz)
        seg = g[(g.index >= e0) & (g.index <= e1)]
        if seg.empty:
            continue
        pv = BASKET[inst].point_value
        entry = float(t["entry"])
        qty = int(t.get("qty", 1) or 1)
        if t["direction"] == "LONG":
            mae = (entry - float(seg["low"].min())) * pv * qty
            mfe = (float(seg["high"].max()) - entry) * pv * qty
        else:
            mae = (float(seg["high"].max()) - entry) * pv * qty
            mfe = (entry - float(seg["low"].min())) * pv * qty
        rows.append(dict(sleeve=sleeve, inst=inst, mae=max(mae, 0.0), mfe=max(mfe, 0.0),
                         risk=float(t["risk_sized"])))
    return pd.DataFrame(rows)


def mae_summary(mae_df):
    out = []
    if mae_df is None or mae_df.empty:
        return out
    for (sl, inst), g in mae_df.groupby(["sleeve", "inst"]):
        ratio = g["mae"] / g["risk"]
        out.append(dict(sleeve=sl, inst=inst, n=int(len(g)),
                        med_mae=float(g["mae"].median()), max_mae=float(g["mae"].max()),
                        med_mfe=float(g["mfe"].median()),
                        med_mae_over_risk=float(ratio.median()),
                        p90_mae_over_risk=float(ratio.quantile(0.90)),
                        max_mae_over_risk=float(ratio.max()),
                        n_mae_gt_risk=int((ratio > 1.0).sum())))
    return out


# ---------------------------------------------------------------------------
# section 8 - fill / timing audit
# ---------------------------------------------------------------------------
def fill_timing(which, sleeves, frames, bar_minutes=None):
    """bar_minutes: sleeves whose entry_time labels a 5-minute bar must be checked
    against that whole 5-minute window, not the 1-minute bar at the same label.
    The swing sleeves fill at the CLOSE of the labelled 5-minute resume bar."""
    bar_minutes = bar_minutes or {}
    rows = []
    for name, df in sleeves.items():
        if df is None or df.empty:
            rows.append(dict(sleeve=name, n=0))
            continue
        span = pd.Timedelta(minutes=bar_minutes.get(name, 1))
        n_out_entry = n_out_exit = n_sig_after = n_same_bar = n_missing = 0
        for _, t in df.iterrows():
            inst = t["instrument"]
            g = frames.get(inst)
            e0, e1 = pd.Timestamp(t["entry_time"]), pd.Timestamp(t["exit_time"])
            if e1 <= e0:
                n_same_bar += 1
            if "signal_after_entry" in t and int(t.get("signal_after_entry") or 0):
                n_sig_after += 1
            elif "signal_time" in t and pd.notna(t.get("signal_time")):
                if pd.Timestamp(t["signal_time"]) > e0:
                    n_sig_after += 1
            if g is None:
                n_missing += 1
                continue
            tz = g.index.tz
            a = e0.tz_localize(tz) if (e0.tzinfo is None and tz is not None) else e0
            b = e1.tz_localize(tz) if (e1.tzinfo is None and tz is not None) else e1
            eb = g[(g.index >= a) & (g.index < a + span)]
            xb = g[(g.index >= b) & (g.index < b + span)]
            if eb.empty or xb.empty:
                n_missing += 1
                continue
            ep, xp = float(t["entry"]), float(t["exit"])
            if not (float(eb["low"].min()) - 0.011 <= ep <= float(eb["high"].max()) + 0.011):
                n_out_entry += 1
            if not (float(xb["low"].min()) - 0.011 <= xp <= float(xb["high"].max()) + 0.011):
                n_out_exit += 1
        rows.append(dict(sleeve=name, n=int(len(df)), outside_entry_bar=n_out_entry,
                         outside_exit_bar=n_out_exit, signal_after_entry=n_sig_after,
                         same_or_before_bar_exit=n_same_bar, missing_bars=n_missing))
    return rows


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
def run_window(which):
    res = {}
    ok, checks, (daily, st, ledger, ov, entries) = anchor_gate(which) if which == "floor" else (
        True, [], instrumented_replay(which, 0.05, "skip_same_symbol", 2.0))
    res["anchor_ok"] = bool(ok)
    res["anchor_checks"] = [dict(name=n, got=float(a), want=float(b)) for n, a, b in checks]
    if which == "floor" and not ok:
        return res

    sleeves, extra, prices = sleeve_frames(which)
    m = metrics(daily)
    res["combined"] = dict(net=float(m["pnl"]), maxdd=float(m["maxdd"]),
                           calmar=float(m["calmar"]), pf=float(m["pf"]))
    res["state"] = {k: v for k, v in st.items()}
    res["overlaps"] = ov
    res["overlap_summary"] = {}
    if ov:
        odf = pd.DataFrame(ov)
        res["overlap_summary"] = dict(
            total=int(len(odf)),
            cross_cluster=int(odf["cross_cluster"].sum()),
            opposite_direction=int(odf["opposite"].sum()),
            by_pair={f"{a}|{b}": int(c) for (a, b), c in
                     odf.groupby(["held_cluster", "new_cluster"]).size().items()})

    res["stop_distance_normal"] = stop_distance_check(which, extra)
    res["calm_nkd_stop_distance"] = calm_nkd_stop_distance(which)
    res["risk_vs_realized"] = [risk_vs_realized(sleeves[k], k) for k in
                               ("normal_r4", "current_nkd", "calm_nkd", "stress", "calm_a")]

    # Calm A with the ATR15 disaster stop (spec D): true stop risk in the cap
    dis_frames = dis.load_price_frames(which)
    calm_a15 = dis.build_calm_trades(which, dis.StopSpec("atr15", "atr", 1.5),
                                     extra["meta"], dis_frames)
    res["risk_vs_realized"].append(risk_vs_realized(calm_a15, "calm_a_atr15"))
    d15, st15, led15, ov15, _ = instrumented_replay(which, 0.05, "skip_same_symbol", 2.0,
                                                    calm_df=calm_a15)
    m15 = metrics(d15)
    res["combined_atr15"] = dict(net=float(m15["pnl"]), maxdd=float(m15["maxdd"]),
                                 calmar=float(m15["calmar"]),
                                 double_booked=st15["double_booked"],
                                 double_booked_pnl=st15["double_booked_pnl"],
                                 stress_closed_calm=st15["stress_closed_calm"])

    res["unfillable_stop"] = unfillable_stop_scan(which, extra)
    res["stop_fill_feasibility"] = stop_fill_feasibility(which, extra)
    res["standalone"] = [sleeve_standalone(sleeves[k], k) for k in
                         ("normal_r4", "current_nkd", "calm_nkd", "stress", "calm_a")]
    res["standalone"].append(sleeve_standalone(calm_a15, "calm_a_atr15"))
    res["risk_breaches"] = []
    for k, lbl in ((sleeves["normal_r4"], "normal_r4"), (sleeves["stress"], "stress"),
                   (calm_a15, "calm_a_atr15"), (sleeves["calm_nkd"], "calm_nkd"),
                   (sleeves["current_nkd"], "current_nkd")):
        res["risk_breaches"] += risk_breach_detail(k, lbl)

    # MAE / MFE - intraday sleeves only (Calm A and Stress live inside one session)
    mae_rows = []
    mae_rows.append(intraday_mae_mfe(which, "calm_a_atr15", calm_a15, dis_frames))
    if not sleeves["stress"].empty:
        mae_rows.append(intraday_mae_mfe(which, "stress_mnq", sleeves["stress"], prices))
    mae_df = pd.concat([x for x in mae_rows if x is not None and not x.empty], ignore_index=True) \
        if any(x is not None and not x.empty for x in mae_rows) else pd.DataFrame()
    res["mae"] = mae_summary(mae_df)

    import scratch.normal_promotion_variant_matrix_20260821 as vm
    raw_art = json.loads(full.NORMAL_PROMOTION_FILES[which].read_text(encoding="utf-8"))
    fill_frames = vm.load_frames(raw_art)          # MES/MNQ/MYM/M2K + MNKD, native tz
    res["fill_timing"] = fill_timing(which, dict(
        normal_r4=sleeves["normal_r4"], current_nkd=sleeves["current_nkd"],
        calm_nkd=sleeves["calm_nkd"], stress=sleeves["stress"],
        calm_a=sleeves["calm_a"], calm_a_atr15=calm_a15), fill_frames,
        bar_minutes=dict(normal_r4=5, current_nkd=5, calm_nkd=5))
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    a = ap.parse_args()
    out = {}
    for w in a.which:
        print(f"[run] {w}", flush=True)
        out[w] = run_window(w)
        print(f"[done] {w} anchor_ok={out[w]['anchor_ok']}", flush=True)
    OUT_JSON.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT_JSON)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
