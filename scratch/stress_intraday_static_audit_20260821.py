from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, daily_atr_series, label_regimes
from futures.basket import BASKET
from futures.swing_tf import SwingTFEngine, costs_for_basket
from global_index.deploy_sim import metrics
from scratch.harness import ARGV
from scratch.stress_intraday_detector_excavation_20260821 import (
    Detector,
    arg_from,
    build_all,
    fmt_money,
    load_window,
    md_table,
    pf,
)
from scratch.stress_sleeve_validation import daily_from_trades, split_table


ACCOUNT = 50_000.0
FROZEN = Detector("liq_1020_b4_rr2_x1555", "10:20", rr=2.0, below_min=4, end_time="15:55")
CAUSAL_DELAY = Detector("liq_1020_b4_rr2_x1555_delay1025", "10:20", rr=2.0, below_min=4, end_time="15:55")


def known_after(ts: pd.Timestamp) -> pd.Timestamp:
    # Resample labels are left-edge 5-minute bars. A bar stamped 10:20 is fully
    # known at 10:25, not at 10:20.
    return pd.Timestamp(ts) + pd.Timedelta(minutes=5)


def load_labels(which: str) -> dict[pd.Timestamp, str]:
    argv = list(ARGV[which])
    regime_csv = arg_from(argv, "--regime-csv", "spy_daily_live.csv")
    hmm_fit_end = arg_from(argv, "--hmm-fit-end", "2024-12-31")
    labels = label_regimes(benchmark_daily(regime_csv), "2018-01-01", 3, hmm_fit_end)
    return {pd.Timestamp(k).normalize(): str(v) for k, v in labels.items()}


def sessions_from_dfs(dfs: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(sorted({
        pd.Timestamp(x).tz_localize(None).normalize()
        for x in dfs["MES"].index.normalize().unique()
    }))


def dense_daily(tr: pd.DataFrame, sessions: pd.DatetimeIndex, extra_cost_per_leg: float = 0.0) -> pd.Series:
    if tr.empty:
        return pd.Series(0.0, index=sessions)
    work = tr.copy()
    work["pnl"] = work["pnl"].astype(float) - extra_cost_per_leg
    sparse = daily_from_trades(work)
    use = sessions[(sessions >= sparse.index.min()) & (sessions <= sparse.index.max())]
    dense = pd.Series(0.0, index=use)
    dense.loc[sparse.index] = sparse.values
    return dense


def summarize(name: str, tr: pd.DataFrame, sessions: pd.DatetimeIndex, extra_cost_per_leg: float = 0.0) -> dict:
    if tr.empty:
        return {"name": name, "trades": 0, "days": 0, "clusters": 0, "net": 0.0, "pf": math.inf, "sharpe": 0.0, "calmar": math.inf, "maxdd": 0.0}
    work = tr.copy()
    work["pnl"] = work["pnl"].astype(float) - extra_cost_per_leg
    m = metrics(dense_daily(work, sessions))
    return {
        "name": name,
        "trades": int(len(work)),
        "days": int(work["day"].nunique()),
        "clusters": int(work["event_cluster"].nunique()) if "event_cluster" in work else 0,
        "net": float(work["pnl"].sum()),
        "pf": pf(work),
        "sharpe": float(m["sharpe"]),
        "calmar": float(m["calmar"]),
        "maxdd": float(m["maxdd"]),
        "target_rate": float((work["exit_reason"] == "target").mean()),
        "stop_rate": float((work["exit_reason"] == "stop").mean()),
    }


def build_candidate(which: str) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], pd.DatetimeIndex]:
    dfs, costs, sessions = load_window(which)
    raw = build_all(dfs, costs, [FROZEN])
    tr = raw[FROZEN.name].copy()
    # Causal repair: the same signal bar can only be used at 10:25. Reprice by
    # shifting entry to the first bar at/after known_after(signal_time), keeping
    # the same signal and same stop/target formula.
    delayed_rows = []
    by_inst_day = {
        inst: {pd.Timestamp(d).tz_localize(None).normalize(): g for d, g in df.groupby(df.index.normalize())}
        for inst, df in dfs.items()
    }
    for _, r in tr.iterrows():
        day = pd.Timestamp(r["day"]).normalize()
        inst = str(r["inst"])
        g = by_inst_day[inst][day]
        et = known_after(pd.Timestamp(r["signal_time"]))
        entry_bar = g[g.index >= et]
        entry_bar = entry_bar[entry_bar.index.time <= pd.Timestamp("15:55").time()]
        if entry_bar.empty:
            continue
        entry_ts = entry_bar.index[0]
        entry_px = float(entry_bar.iloc[0]["open"])
        stop = float(r["stop"])
        stop_dist = stop - entry_px
        if stop_dist <= 0 or stop_dist / entry_px > FROZEN.max_stop_pct:
            continue
        target = entry_px - FROZEN.rr * stop_dist
        fwd = g[(g.index > entry_ts) & (g.index.time <= pd.Timestamp("15:55").time())]
        if fwd.empty:
            continue
        # Local copy to avoid importing private helper.
        exit_px = float(fwd.iloc[-1]["close"])
        reason = "time"
        exit_ts = fwd.index[-1]
        for ts, bar in fwd.iterrows():
            high = float(bar["high"])
            low = float(bar["low"])
            op = float(bar["open"])
            if high >= stop:
                exit_px = stop if low <= stop else op
                reason = "stop"
                exit_ts = ts
                break
            if low <= target:
                exit_px = target if high >= target else op
                reason = "target"
                exit_ts = ts
                break
        out = dict(r)
        out.update({
            "variant": CAUSAL_DELAY.name,
            "entry": entry_px,
            "entry_time": entry_ts,
            "exit": exit_px,
            "exit_time": exit_ts,
            "exit_reason": reason,
            "target": target,
            "stop_dist_pct": stop_dist / entry_px,
            "points": entry_px - exit_px,
            "pnl": (entry_px - exit_px) * BASKET[inst].point_value - costs[inst].round_turn_cost(),
        })
        delayed_rows.append(out)
    delayed = pd.DataFrame(delayed_rows).reset_index(drop=True) if delayed_rows else tr.iloc[0:0].copy()
    return {"as_measured": tr, "causal_delay1025": delayed}, dfs, sessions


def timing_audit(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"signal_after_entry": 0, "same_bar_exit": 0, "outside_exit_bar": 0, "needs_delay": 0}
    sig_after = 0
    same_bar = 0
    needs_delay = 0
    for _, r in tr.iterrows():
        sig_known = known_after(pd.Timestamp(r["signal_time"]))
        entry = pd.Timestamp(r["entry_time"])
        if sig_known > entry:
            sig_after += 1
        if pd.Timestamp(r["exit_time"]) <= entry:
            same_bar += 1
        if entry < sig_known:
            needs_delay += 1
    return {"signal_after_entry": sig_after, "same_bar_exit": same_bar, "outside_exit_bar": 0, "needs_delay": needs_delay}


def swing_positions(dfs: dict[str, pd.DataFrame], labels: dict[pd.Timestamp, str], costs: dict) -> list[dict]:
    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)
    out = []
    for inst, trades in swing.items():
        for t in trades:
            out.append({
                "inst": inst,
                "d0": pd.Timestamp(t["day"]).normalize(),
                "d1": pd.Timestamp(t["exit_day"]).normalize(),
                "dir": t["direction"],
            })
    return out


def overlap(open_positions: list[dict], tr: pd.DataFrame) -> dict:
    held = opposite = 0
    net = gross = 0.0
    days = set()
    for _, r in tr.iterrows():
        day = pd.Timestamp(r["day"]).normalize()
        matches = [
            p for p in open_positions
            if p["inst"] == r["inst"] and p["d0"] < day <= p["d1"]
        ]
        if matches:
            held += 1
            if any(p["dir"] != r["direction"] for p in matches):
                opposite += 1
                pnl = float(r["pnl"])
                net += pnl
                gross += abs(pnl)
                days.add(day)
    return {"held": held, "opposite": opposite, "conflict_days": len(days), "opposite_net": net, "opposite_gross": gross}


def calm_overlap(which: str, tr: pd.DataFrame) -> dict:
    paths = {
        "floor": Path("scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_is.csv"),
        "vault2025": Path("scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_2025.csv"),
        "vault2026": Path("scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_2026.csv"),
    }
    path = paths.get(which)
    if path is None or not path.exists() or tr.empty:
        return {"held": 0, "opposite": 0, "conflict_days": 0, "opposite_net": 0.0, "opposite_gross": 0.0}
    calm = pd.read_csv(path)
    if calm.empty or "variant" not in calm:
        return {"held": 0, "opposite": 0, "conflict_days": 0, "opposite_net": 0.0, "opposite_gross": 0.0}
    calm = calm[calm["variant"] == "on_neg_fade_mod001_010_x1555"].copy()
    if calm.empty:
        return {"held": 0, "opposite": 0, "conflict_days": 0, "opposite_net": 0.0, "opposite_gross": 0.0}
    calm["day"] = pd.to_datetime(calm["day"]).dt.normalize()
    keys = set(zip(calm["day"], calm["inst"]))
    held = opposite = 0
    net = gross = 0.0
    days = set()
    for _, r in tr.iterrows():
        key = (pd.Timestamp(r["day"]).normalize(), str(r["inst"]))
        if key not in keys:
            continue
        held += 1
        # Calm candidate is LONG; this Stress candidate is SHORT.
        opposite += 1
        pnl = float(r["pnl"])
        net += pnl
        gross += abs(pnl)
        days.add(key[0])
    return {"held": held, "opposite": opposite, "conflict_days": len(days), "opposite_net": net, "opposite_gross": gross}


def bootstrap_event(tr: pd.DataFrame, seed: int = 42, n_iter: int = 5000) -> dict:
    if tr.empty:
        return {"events": 0, "p_pos": 0.0, "p5": 0.0, "p50": 0.0, "p95": 0.0}
    vals = tr.groupby("event_cluster")["pnl"].sum().to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    draws = rng.choice(vals, size=(n_iter, len(vals)), replace=True).sum(axis=1)
    return {
        "events": int(len(vals)),
        "p_pos": float((draws > 0).mean()),
        "p5": float(np.percentile(draws, 5)),
        "p50": float(np.percentile(draws, 50)),
        "p95": float(np.percentile(draws, 95)),
    }


def slippage_value_per_extra_tick(tr: pd.DataFrame) -> pd.Series:
    return tr["inst"].map(lambda i: BASKET[str(i)].tick_value * 2.0)


def run_window(which: str) -> dict:
    variants, dfs, sessions = build_candidate(which)
    labels = load_labels(which)
    argv = list(ARGV[which])
    costs = costs_for_basket(slippage_ticks=float(arg_from(argv, "--slippage-ticks", 2.0)))
    sw = swing_positions(dfs, labels, costs)
    rows = []
    for name, tr in variants.items():
        base = summarize(name, tr, sessions)
        slip2x = summarize(name + "_slip2x", tr, sessions, extra_cost_per_leg=float(slippage_value_per_extra_tick(tr).mean()) if not tr.empty else 0.0)
        slip3x = summarize(name + "_slip3x", tr, sessions, extra_cost_per_leg=2.0 * float(slippage_value_per_extra_tick(tr).mean()) if not tr.empty else 0.0)
        rows.append(base | {
            "timing": timing_audit(tr),
            "swing_overlap": overlap(sw, tr),
            "calm_overlap": calm_overlap(which, tr),
            "bootstrap": bootstrap_event(tr),
            "slip2x_net": slip2x["net"],
            "slip3x_net": slip3x["net"],
        })
    return {"which": which, "variants": variants, "sessions": sessions, "rows": rows}


def report_window(r: dict) -> list[str]:
    lines = [f"## {r['which']}", ""]
    rows = r["rows"]
    lines += [
        "Static candidate audit:",
        "",
        md_table(rows, ["name", "trades", "days", "clusters", "net", "pf", "sharpe", "calmar", "maxdd", "target_rate", "stop_rate", "slip2x_net", "slip3x_net"]),
        "",
        "Timing audit:",
        "",
        md_table([{"name": x["name"], **x["timing"]} for x in rows], ["name", "signal_after_entry", "needs_delay", "same_bar_exit", "outside_exit_bar"]),
        "",
        "Swing same-symbol overlap:",
        "",
        md_table([{"name": x["name"], **x["swing_overlap"]} for x in rows], ["name", "held", "opposite", "conflict_days", "opposite_net", "opposite_gross"]),
        "",
        "Calm same-symbol overlap (`on_neg_fade_mod001_010_x1555` saved logs):",
        "",
        md_table([{"name": x["name"], **x["calm_overlap"]} for x in rows], ["name", "held", "opposite", "conflict_days", "opposite_net", "opposite_gross"]),
        "",
        "Event bootstrap:",
        "",
        md_table([{"name": x["name"], **x["bootstrap"]} for x in rows], ["name", "events", "p_pos", "p5", "p50", "p95"]),
        "",
    ]
    for name, tr in r["variants"].items():
        lines += [
            f"By instrument/year/subtype for `{name}`:",
            "",
            split_table(tr, "inst").reset_index().to_string(index=False) if not tr.empty else "_empty_",
            "",
            split_table(tr, "year").reset_index().to_string(index=False) if not tr.empty else "_empty_",
            "",
            split_table(tr, "event_subtype").reset_index().to_string(index=False) if not tr.empty else "_empty_",
            "",
        ]
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--report", default="scratch/stress_intraday_static_candidate_audit_20260821_report.md")
    args = ap.parse_args()
    report = [
        "# Stress Intraday Static Candidate Audit - 2026-08-21",
        "",
        "Scope: scratch-only. No production code modified.",
        "",
        "Frozen candidate: `liq_1020_b4_rr2_x1555` from the intraday detector pass.",
        "Critical check: the 5-minute bar stamped 10:20 is not known until 10:25, so this",
        "report measures both the as-measured version and a causal 10:25 entry repair.",
        "",
    ]
    for which in args.which:
        print(f"\n=== {which} ===", flush=True)
        r = run_window(which)
        for x in r["rows"]:
            t = x["timing"]
            o = x["swing_overlap"]
            print(
                f"{x['name']:<20} n={x['trades']:>4} net={fmt_money(x['net']):>9} "
                f"pf={x['pf']:.2f} cal={x['calmar']:.2f} timing={t['signal_after_entry']} "
                f"swing_opp={o['opposite']}/{x['trades']} calm_opp={x['calm_overlap']['opposite']}/{x['trades']}"
            )
        report += report_window(r)
    report += [
        "## Verdict",
        "",
        "If `signal_after_entry` is non-zero for the as-measured row, the standalone",
        "intraday-detector headline must be discarded in favor of the causal-delay row.",
        "",
    ]
    Path(args.report).write_text("\n".join(report), encoding="utf-8")
    print(f"\nwrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
