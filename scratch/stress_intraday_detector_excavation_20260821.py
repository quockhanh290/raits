from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import load_parquet, resample_5m
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket
from global_index.deploy_sim import metrics
from scratch.harness import ARGV
from scratch.stress_sleeve_validation import daily_from_trades, split_table


ACCOUNT = 50_000.0


@dataclass(frozen=True)
class Detector:
    name: str
    signal_end: str
    entry_mode: str = "next_open"  # next_open | break_low
    entry_deadline: str = "11:30"
    end_time: str = "14:00"
    rr: float = 2.0
    stop_ref: str = "swing_high"  # swing_high | vwap_high | recent_high
    stop_pad: float = 0.001
    max_stop_pct: float = 0.015
    below_min: int = 3
    wide_min: int = 0
    gap_down_min: int = 0
    avg_range_min: float = 0.0
    avg_gap_max: float = 1.0
    instruments: tuple[str, ...] = ("MNQ", "MES")


def parse_time(hhmm: str) -> dtime:
    return pd.Timestamp(hhmm).time()


def arg_from(argv: list[str], flag: str, default=None):
    if flag not in argv:
        return default
    return argv[argv.index(flag) + 1]


def clip(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    if start:
        df = df[df.index >= pd.Timestamp(start).tz_localize(df.index.tz)]
    if end:
        df = df[df.index <= pd.Timestamp(end).tz_localize(df.index.tz)]
    return df


def vwap(bars: pd.DataFrame) -> float:
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    vol = bars["volume"]
    return float((tp * vol).sum() / vol.sum()) if float(vol.sum()) > 0 else float(bars["close"].iloc[-1])


def first_at_or_after(g: pd.DataFrame, hhmm: str) -> tuple[pd.Timestamp, float] | None:
    sub = g[g.index.time >= parse_time(hhmm)]
    if sub.empty:
        return None
    return sub.index[0], float(sub.iloc[0]["open"])


def exit_short(fwd: pd.DataFrame, stop: float, target: float, end_time: str) -> tuple[float, str, pd.Timestamp]:
    fwd = fwd[fwd.index.time <= parse_time(end_time)]
    if fwd.empty:
        raise ValueError("empty forward")
    exit_px = float(fwd.iloc[-1]["close"])
    reason = "time"
    exit_ts = fwd.index[-1]
    for ts, bar in fwd.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])
        op = float(bar["open"])
        if high >= stop:
            return (stop if low <= stop else op), "stop", ts
        if low <= target:
            return (target if high >= target else op), "target", ts
        exit_px = float(bar["close"])
        exit_ts = ts
    return exit_px, reason, exit_ts


def day_context(day_1m: pd.DataFrame, signal_end: str) -> dict | None:
    bars5 = resample_5m(day_1m).between_time("09:30", "15:55")
    sig = bars5[bars5.index.time == parse_time(signal_end)]
    rth = day_1m.between_time("09:30", "16:00")
    if len(bars5) < 8 or sig.empty or rth.empty:
        return None
    pre = bars5[bars5.index.time <= parse_time(signal_end)]
    if len(pre) < 3:
        return None
    prior = day_1m[day_1m.index < rth.index[0]]
    gap = 0.0
    if not prior.empty:
        pc = float(prior.iloc[-1]["close"])
        gap = (float(rth.iloc[0]["open"]) - pc) / pc if pc else 0.0
    open_px = float(rth.iloc[0]["open"])
    sig_close = float(sig.iloc[-1]["close"])
    vw = vwap(pre)
    return {
        "signal_time": sig.index[-1],
        "signal_close": sig_close,
        "open": open_px,
        "vwap": vw,
        "pre_high": float(pre["high"].max()),
        "pre_low": float(pre["low"].min()),
        "range_pct": float(pre["high"].max() - pre["low"].min()) / open_px if open_px else 0.0,
        "ret_from_open": sig_close / open_px - 1.0 if open_px else 0.0,
        "gap": gap,
    }


def peer_features(ctxs: list[dict]) -> dict:
    below = [c for c in ctxs if c["signal_close"] < c["vwap"] and c["signal_close"] < c["open"]]
    wide = [c for c in ctxs if c["range_pct"] >= 0.0075]
    gap_down = [c for c in ctxs if c["gap"] <= -0.0025]
    return {
        "below_count": len(below),
        "wide_count": len(wide),
        "gap_down_count": len(gap_down),
        "avg_range_pct": float(np.mean([c["range_pct"] for c in ctxs])) if ctxs else 0.0,
        "avg_gap": float(np.mean([c["gap"] for c in ctxs])) if ctxs else 0.0,
        "avg_ret_from_open": float(np.mean([c["ret_from_open"] for c in ctxs])) if ctxs else 0.0,
    }


def classify_event(feat: dict) -> str:
    if feat["gap_down_count"] >= 2 and feat["below_count"] >= 3:
        return "gap-liquidation"
    if feat["below_count"] >= 4 and feat["wide_count"] >= 3:
        return "broad-liquidation"
    if feat["below_count"] >= 3 and feat["avg_ret_from_open"] <= -0.003:
        return "opening-selloff"
    if feat["wide_count"] >= 3:
        return "wide-chop"
    return "weak"


def passes_detector(det: Detector, feat: dict) -> bool:
    return (
        feat["below_count"] >= det.below_min
        and feat["wide_count"] >= det.wide_min
        and feat["gap_down_count"] >= det.gap_down_min
        and feat["avg_range_pct"] >= det.avg_range_min
        and feat["avg_gap"] <= det.avg_gap_max
    )


def entry_for_detector(day_1m: pd.DataFrame, ctx: dict, det: Detector) -> tuple[pd.Timestamp, float] | None:
    if det.entry_mode == "next_open":
        return first_at_or_after(day_1m, pd.Timestamp(ctx["signal_time"]).strftime("%H:%M"))
    if det.entry_mode != "break_low":
        raise ValueError(det.entry_mode)
    scan = day_1m[
        (day_1m.index > ctx["signal_time"])
        & (day_1m.index.time <= parse_time(det.entry_deadline))
    ]
    for ts, bar in scan.iterrows():
        if float(bar["close"]) < ctx["pre_low"]:
            return ts, float(bar["close"])
    return None


def stop_for_detector(day_1m: pd.DataFrame, ctx: dict, det: Detector, entry_ts: pd.Timestamp) -> float:
    if det.stop_ref == "swing_high":
        return ctx["pre_high"] * (1.0 + det.stop_pad)
    if det.stop_ref == "vwap_high":
        return max(ctx["vwap"], ctx["pre_high"]) * (1.0 + det.stop_pad)
    if det.stop_ref == "recent_high":
        recent = day_1m[(day_1m.index <= entry_ts)].tail(30)
        return float(recent["high"].max()) * (1.0 + det.stop_pad)
    raise ValueError(det.stop_ref)


def build_trade(day_1m: pd.DataFrame, ctx: dict, det: Detector, cost, point_value: float) -> dict | None:
    if ctx["signal_close"] >= ctx["vwap"] or ctx["signal_close"] >= ctx["open"]:
        return None
    entry = entry_for_detector(day_1m, ctx, det)
    if entry is None:
        return None
    entry_ts, entry_px = entry
    stop = stop_for_detector(day_1m, ctx, det, entry_ts)
    stop_dist = stop - entry_px
    if stop_dist <= 0 or stop_dist / entry_px > det.max_stop_pct:
        return None
    target = entry_px - det.rr * stop_dist
    fwd = day_1m[(day_1m.index > entry_ts) & (day_1m.index.time <= parse_time(det.end_time))]
    if fwd.empty:
        return None
    exit_px, reason, exit_ts = exit_short(fwd, stop, target, det.end_time)
    points = entry_px - exit_px
    return {
        "entry": entry_px,
        "entry_time": entry_ts,
        "signal_time": ctx["signal_time"],
        "exit": exit_px,
        "exit_time": exit_ts,
        "exit_reason": reason,
        "stop": stop,
        "target": target,
        "stop_dist_pct": stop_dist / entry_px,
        "points": points,
        "pnl": points * point_value - cost.round_turn_cost(),
    }


def detectors() -> list[Detector]:
    return [
        Detector("liq_0945_b3_rr15_x1400", "09:45", rr=1.5, below_min=3, end_time="14:00"),
        Detector("liq_1000_b3_rr15_x1400", "10:00", rr=1.5, below_min=3, end_time="14:00"),
        Detector("liq_1020_b3_rr15_x1400", "10:20", rr=1.5, below_min=3, end_time="14:00"),
        Detector("liq_1020_b4_rr2_x1555", "10:20", rr=2.0, below_min=4, end_time="15:55"),
        Detector("liq_1045_b3_rr15_x1400", "10:45", rr=1.5, below_min=3, end_time="14:00"),
        Detector("liq_1045_b3_rr2_x1555", "10:45", rr=2.0, below_min=3, end_time="15:55"),
        Detector("wide_1020_b3_w3_rr15", "10:20", rr=1.5, below_min=3, wide_min=3, end_time="14:00"),
        Detector("wide_1045_b3_w3_rr15", "10:45", rr=1.5, below_min=3, wide_min=3, end_time="14:00"),
        Detector("gap_1020_b3_g2_rr15", "10:20", rr=1.5, below_min=3, gap_down_min=2, end_time="14:00"),
        Detector("gap_1045_b3_g2_rr15", "10:45", rr=1.5, below_min=3, gap_down_min=2, end_time="14:00"),
        Detector("break_0945_b3_rr15", "09:45", entry_mode="break_low", rr=1.5, below_min=3, stop_ref="recent_high", stop_pad=0.0005, max_stop_pct=0.0125, end_time="14:00"),
        Detector("break_1045_b3_rr15", "10:45", entry_mode="break_low", rr=1.5, below_min=3, stop_ref="recent_high", stop_pad=0.0005, max_stop_pct=0.0125, end_time="14:00"),
        Detector("break_1100_b3_rr15", "11:00", entry_mode="break_low", rr=1.5, below_min=3, stop_ref="recent_high", stop_pad=0.0005, max_stop_pct=0.0125, end_time="14:00"),
    ]


def event_cluster_ids(days: list[pd.Timestamp]) -> dict[pd.Timestamp, str]:
    out = {}
    last = None
    cluster = 0
    for day in sorted(set(pd.Timestamp(d).normalize() for d in days)):
        if last is None or (day - last).days > 3:
            cluster += 1
        out[day] = f"E{cluster:03d}"
        last = day
    return out


def load_window(which: str):
    argv = list(ARGV[which])
    data_dir = arg_from(argv, "--data-dir")
    start = arg_from(argv, "--start")
    end = arg_from(argv, "--end")
    costs = costs_for_basket(slippage_ticks=float(arg_from(argv, "--slippage-ticks", 2.0)))
    dfs = {
        name: clip(load_parquet(str(Path(data_dir) / data_filename(contract))), start, end)
        for name, contract in BASKET.items()
    }
    sessions = pd.DatetimeIndex(sorted({
        pd.Timestamp(x).tz_localize(None).normalize()
        for x in dfs["MES"].index.normalize().unique()
    }))
    return dfs, costs, sessions


def build_all(dfs: dict[str, pd.DataFrame], costs: dict, dets: list[Detector]) -> dict[str, pd.DataFrame]:
    by_signal: dict[str, dict[tuple[pd.Timestamp, str], dict]] = {}
    frames: dict[tuple[pd.Timestamp, str], pd.DataFrame] = {}
    needed_times = sorted(set(d.signal_end for d in dets))
    for inst, df in dfs.items():
        for day_ts, day_1m in df.groupby(df.index.normalize()):
            day = pd.Timestamp(day_ts).tz_localize(None).normalize()
            frames[(day, inst)] = day_1m
            for signal_end in needed_times:
                ctx = day_context(day_1m, signal_end)
                if ctx is not None:
                    by_signal.setdefault(signal_end, {})[(day, inst)] = ctx

    raw: dict[str, list[dict]] = {d.name: [] for d in dets}
    for det in dets:
        ctxs = by_signal.get(det.signal_end, {})
        all_days = sorted({d for d, _ in ctxs})
        active_days = []
        day_feats = {}
        for day in all_days:
            peers = [ctxs[(day, inst)] for inst in BASKET if (day, inst) in ctxs]
            if len(peers) < 4:
                continue
            feat = peer_features(peers)
            if not passes_detector(det, feat):
                continue
            active_days.append(day)
            day_feats[day] = feat
        clusters = event_cluster_ids(active_days)
        for day in active_days:
            feat = day_feats[day]
            for inst in det.instruments:
                ctx = ctxs.get((day, inst))
                day_1m = frames.get((day, inst))
                if ctx is None or day_1m is None:
                    continue
                tr = build_trade(day_1m, ctx, det, costs[inst], BASKET[inst].point_value)
                if tr is None:
                    continue
                row = {
                    **tr,
                    "variant": det.name,
                    "inst": inst,
                    "day": day,
                    "year": day.year,
                    "direction": "SHORT",
                    "event_cluster": clusters[day],
                    "event_subtype": classify_event(feat),
                    **feat,
                }
                raw[det.name].append(row)
    return {
        name: pd.DataFrame(rows).sort_values(["day", "inst"]).reset_index(drop=True)
        if rows else pd.DataFrame(columns=[
            "variant", "inst", "day", "pnl", "event_cluster", "event_subtype",
            "exit_reason", "entry_time", "signal_time", "exit_time",
        ])
        for name, rows in raw.items()
    }


def pf(tr: pd.DataFrame) -> float:
    if tr.empty:
        return math.inf
    wins = float(tr.loc[tr["pnl"] > 0, "pnl"].sum())
    losses = float(-tr.loc[tr["pnl"] < 0, "pnl"].sum())
    return wins / losses if losses else math.inf


def dense_daily(tr: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.Series:
    if tr.empty:
        return pd.Series(0.0, index=sessions)
    sparse = daily_from_trades(tr)
    use = sessions[(sessions >= sparse.index.min()) & (sessions <= sparse.index.max())]
    dense = pd.Series(0.0, index=use)
    dense.loc[sparse.index] = sparse.values
    return dense


def row(name: str, tr: pd.DataFrame, sessions: pd.DatetimeIndex) -> dict:
    daily = dense_daily(tr, sessions)
    m = metrics(daily)
    return {
        "name": name,
        "trades": int(len(tr)),
        "days": int(tr["day"].nunique()) if not tr.empty else 0,
        "clusters": int(tr["event_cluster"].nunique()) if not tr.empty else 0,
        "net": float(tr["pnl"].sum()) if not tr.empty else 0.0,
        "pf": pf(tr),
        "sharpe": float(m["sharpe"]),
        "calmar": float(m["calmar"]),
        "maxdd": float(m["maxdd"]),
        "target_rate": float((tr["exit_reason"] == "target").mean()) if not tr.empty else 0.0,
        "stop_rate": float((tr["exit_reason"] == "stop").mean()) if not tr.empty else 0.0,
    }


def chronological_wfo(cands: dict[str, pd.DataFrame], min_prior: int = 8) -> pd.DataFrame:
    clusters = sorted({
        c for tr in cands.values()
        for c in tr.get("event_cluster", pd.Series(dtype=str)).dropna().unique()
        if c
    })
    rows = []
    for i, cluster in enumerate(clusters):
        prior = clusters[:i]
        if len(prior) < min_prior:
            continue
        scores = {}
        for name, tr in cands.items():
            train = tr[tr["event_cluster"].isin(prior)] if not tr.empty else tr
            scores[name] = float(train["pnl"].sum()) if not train.empty else -math.inf
        selected = max(scores, key=scores.get)
        test = cands[selected]
        test = test[test["event_cluster"] == cluster] if not test.empty else test
        subtype = str(test["event_subtype"].iloc[0]) if not test.empty else "no selected trade"
        rows.append({
            "test_cluster": cluster,
            "selected": selected,
            "event_subtype": subtype,
            "trades": int(len(test)),
            "net": float(test["pnl"].sum()) if not test.empty else 0.0,
            "pf": pf(test),
        })
    return pd.DataFrame(rows)


def concentration_gate(folds: pd.DataFrame) -> dict:
    if folds.empty:
        return {"total": 0.0, "best": 0.0, "without_best": 0.0, "best_share": math.inf, "final4": 0.0, "positive": 0, "folds": 0, "pass": False}
    nets = folds["net"].astype(float)
    total = float(nets.sum())
    best = float(nets.max())
    without_best = total - best
    return {
        "total": total,
        "best": best,
        "without_best": without_best,
        "best_share": best / total if total > 0 else math.inf,
        "final4": float(nets.tail(4).sum()),
        "positive": int((nets > 0).sum()),
        "folds": int(len(nets)),
        "pass": bool(total > 0 and without_best > 0 and (best / total if total > 0 else math.inf) <= 0.5 and float(nets.tail(4).sum()) >= 0),
    }


def fmt_money(v: float) -> str:
    return f"${v:,.0f}"


def md_table(rows: list[dict], fields: list[str]) -> str:
    out = ["| " + " | ".join(fields) + " |", "| " + " | ".join("---" for _ in fields) + " |"]
    for r in rows:
        vals = []
        for f in fields:
            v = r.get(f, "")
            if isinstance(v, float):
                if f in {"net", "maxdd", "total", "best", "without_best", "final4"}:
                    vals.append(fmt_money(v))
                elif math.isinf(v):
                    vals.append("inf")
                else:
                    vals.append(f"{v:.2f}")
            else:
                vals.append(str(v))
        out.append("| " + " | ".join(vals) + " |")
    return "\n".join(out)


def run_window(which: str) -> dict:
    dfs, costs, sessions = load_window(which)
    cands = build_all(dfs, costs, detectors())
    summaries = pd.DataFrame([row(name, tr, sessions) for name, tr in cands.items()])
    summaries = summaries.sort_values(["net", "pf", "trades"], ascending=[False, False, False])
    eligible = {
        r["name"]: cands[r["name"]]
        for _, r in summaries.iterrows()
        if int(r["clusters"]) >= 8 and int(r["trades"]) >= 20
    }
    folds = chronological_wfo(eligible, min_prior=8)
    gate = concentration_gate(folds)
    return {"which": which, "cands": cands, "summaries": summaries, "eligible": eligible, "folds": folds, "gate": gate}


def report_for(r: dict) -> list[str]:
    top = r["summaries"].head(40)
    lines = [
        f"## {r['which']}",
        "",
        "Top intraday-only detector candidates:",
        "",
        md_table(top.to_dict("records"), ["name", "trades", "days", "clusters", "net", "pf", "sharpe", "calmar", "maxdd", "target_rate", "stop_rate"]),
        "",
        "Eligible candidate WFO uses only variants with at least 8 clusters and 20 trades.",
        "",
        "Chronological event WFO:",
        "",
        md_table(r["folds"].to_dict("records"), ["test_cluster", "event_subtype", "selected", "trades", "net", "pf"]) if not r["folds"].empty else "_insufficient folds_",
        "",
        "Concentration gate:",
        "",
        md_table([r["gate"]], ["total", "best", "without_best", "best_share", "final4", "positive", "folds", "pass"]),
        "",
    ]
    for name in top["name"].head(5):
        tr = r["cands"][name]
        lines += [
            f"By subtype for `{name}`:",
            "",
            split_table(tr, "event_subtype").reset_index().to_string(index=False) if not tr.empty else "_empty_",
            "",
        ]
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--report", default="scratch/stress_intraday_detector_excavation_20260821_report.md")
    args = ap.parse_args()
    report = [
        "# Stress Intraday Detector Excavation - 2026-08-21",
        "",
        "Scope: scratch-only. No production code modified.",
        "",
        "This pass does not use daily Stress labels. Candidates are activated only by",
        "intraday-known morning conditions: cross-index below-open/below-VWAP breadth,",
        "opening range expansion, gap-down breadth, or breakdown through the morning low.",
        "",
    ]
    results = []
    for which in args.which:
        print(f"\n=== {which} ===", flush=True)
        r = run_window(which)
        results.append(r)
        for _, x in r["summaries"].head(12).iterrows():
            print(
                f"{x['name']:<32} n={int(x['trades']):>4} cl={int(x['clusters']):>3} "
                f"net={fmt_money(float(x['net'])):>9} pf={float(x['pf']):>5.2f} "
                f"cal={float(x['calmar']):>5.2f} dd={fmt_money(float(x['maxdd'])):>8}"
            )
        g = r["gate"]
        print(f"WFO total={fmt_money(g['total'])} without_best={fmt_money(g['without_best'])} final4={fmt_money(g['final4'])} pass={g['pass']}")
        report += report_for(r)
    floor = next((x for x in results if x["which"] == "floor"), results[0])
    report += ["## Verdict", ""]
    if floor["gate"]["pass"]:
        report += [
            "A floor intraday-only detector passed the concentration gate. This requires",
            "separate holdout verification before any paper/deploy discussion.",
        ]
    else:
        report += [
            "No robust intraday-only Stress detector was found. Standalone rows may look",
            "profitable, but the floor event-WFO/concentration gate still fails.",
        ]
    report.append("")
    Path(args.report).write_text("\n".join(report), encoding="utf-8")
    print(f"\nwrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
