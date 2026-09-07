from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
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
from scratch.stress_new_hypothesis_pass_20260821 import (
    clip,
    cluster_ids,
    exit_trade,
    fmt_money,
    fmt_pf,
    parse_time,
    table,
    vwap,
)


@dataclass(frozen=True)
class Rule:
    name: str
    family: str
    direction: str = "SHORT"
    instruments: tuple[str, ...] = ("MNQ", "MES")
    setup_time: str = "10:30"
    entry_start: str = "10:35"
    entry_end: str = "14:30"
    breadth_min: int = 3
    gap_min: int = 3
    rr: float = 2.0
    exit_time: str = "15:55"
    stop_pad: float = 0.001
    max_stop_pct: float = 0.02


RULES = [
    Rule("gapdown_break_1030_b3_rr2_x1555", "gap_break", setup_time="10:30", entry_start="10:35", entry_end="12:30"),
    Rule("gapdown_break_1130_b3_rr2_x1555", "gap_break", setup_time="11:30", entry_start="11:35", entry_end="13:30"),
    Rule("vwap_reject_1200_b3_rr2_x1555", "vwap_reject", setup_time="12:00", entry_start="12:05", entry_end="14:00"),
    Rule("late_day_break_1400_b3_rr2_x1555", "late_day_break", setup_time="14:00", entry_start="14:05", entry_end="15:15"),
    Rule("late_day_break_1400_b4_rr2_x1555", "late_day_break", setup_time="14:00", entry_start="14:05", entry_end="15:15", breadth_min=4),
]


def arg_from(argv: list[str], flag: str, default=None):
    if flag not in argv:
        return default
    return argv[argv.index(flag) + 1]


def load_window(which: str):
    argv = list(ARGV[which])
    data_dir = arg_from(argv, "--data-dir")
    start = arg_from(argv, "--start")
    end = arg_from(argv, "--end")
    costs = costs_for_basket(slippage_ticks=float(arg_from(argv, "--slippage-ticks", 2.0)))
    dfs = {n: clip(load_parquet(str(Path(data_dir) / data_filename(c))), start, end) for n, c in BASKET.items()}
    sessions = pd.DatetimeIndex(sorted({
        pd.Timestamp(x).tz_localize(None).normalize()
        for x in dfs["MES"].index.normalize().unique()
    }))
    return dfs, costs, sessions


def build_daily_frames(dfs: dict[str, pd.DataFrame]):
    frames = {}
    prev_close = {}
    for inst, df in dfs.items():
        last_close = None
        for day_ts, g in df.groupby(df.index.normalize()):
            day = pd.Timestamp(day_ts).tz_localize(None).normalize()
            rth = g.between_time("09:30", "16:00")
            if rth.empty:
                continue
            frames[(day, inst)] = g
            prev_close[(day, inst)] = last_close
            last_close = float(rth.iloc[-1]["close"])
    return frames, prev_close


def context(g: pd.DataFrame, prev_close: float | None, setup_time: str) -> dict | None:
    if prev_close is None:
        return None
    bars5 = resample_5m(g).between_time("09:30", "15:55")
    rth = g.between_time("09:30", "16:00")
    pre = bars5[bars5.index.time <= parse_time(setup_time)]
    sig = bars5[bars5.index.time == parse_time(setup_time)]
    if rth.empty or len(pre) < 8 or sig.empty:
        return None
    day_open = float(rth.iloc[0]["open"])
    sig_close = float(sig.iloc[-1]["close"])
    vw = vwap(pre)
    hi = float(pre["high"].max())
    lo = float(pre["low"].min())
    gap = day_open / prev_close - 1.0
    ret = sig_close / day_open - 1.0
    return {
        "signal_time": sig.index[-1],
        "known_time": sig.index[-1] + pd.Timedelta(minutes=5),
        "open": day_open,
        "prev_close": prev_close,
        "gap": gap,
        "signal_close": sig_close,
        "vwap": vw,
        "pre_high": hi,
        "pre_low": lo,
        "range_pct": (hi - lo) / day_open if day_open else 0.0,
        "below": sig_close < day_open and sig_close < vw,
        "gapdown": gap <= -0.004,
        "ret_from_open": ret,
    }


def peer_features(ctxs: list[dict]) -> dict:
    return {
        "below_count": sum(1 for c in ctxs if c["below"]),
        "gapdown_count": sum(1 for c in ctxs if c["gapdown"]),
        "avg_gap": float(np.mean([c["gap"] for c in ctxs])) if ctxs else 0.0,
        "avg_ret": float(np.mean([c["ret_from_open"] for c in ctxs])) if ctxs else 0.0,
    }


def first_low_break(g: pd.DataFrame, level: float, start: str, end: str):
    sub = g[(g.index.time >= parse_time(start)) & (g.index.time <= parse_time(end))]
    for ts, bar in sub.iterrows():
        if float(bar["low"]) < level:
            return ts, min(float(bar["open"]), level)
    return None


def first_vwap_reject(g: pd.DataFrame, vwap_level: float, low_level: float, start: str, end: str):
    sub = g[(g.index.time >= parse_time(start)) & (g.index.time <= parse_time(end))]
    touched = False
    for ts, bar in sub.iterrows():
        if float(bar["high"]) >= vwap_level:
            touched = True
        if touched and float(bar["low"]) < low_level:
            return ts, min(float(bar["open"]), low_level)
    return None


def event_type(feat: dict) -> str:
    if feat["gapdown_count"] >= 3 and feat["below_count"] >= 4:
        return "gapdown-full-breadth"
    if feat["gapdown_count"] >= 3:
        return "gapdown"
    if feat["below_count"] >= 4:
        return "late-full-breadth"
    return "weak"


def build_rule(cache, costs: dict, rule: Rule) -> pd.DataFrame:
    frames, prev_close = cache
    ctxs = {}
    for key, g in frames.items():
        ctx = context(g, prev_close.get(key), rule.setup_time)
        if ctx is not None:
            ctxs[key] = ctx

    active = []
    feats = {}
    for day in sorted({d for d, _ in ctxs}):
        peers = [ctxs[(day, inst)] for inst in BASKET if (day, inst) in ctxs]
        if len(peers) < 4:
            continue
        feat = peer_features(peers)
        if feat["below_count"] >= rule.breadth_min and feat["gapdown_count"] >= rule.gap_min:
            active.append(day)
            feats[day] = feat
    clusters = cluster_ids(active)

    trades = []
    for day in active:
        feat = feats[day]
        for inst in rule.instruments:
            ctx = ctxs.get((day, inst))
            g = frames.get((day, inst))
            if ctx is None or g is None or not ctx["below"]:
                continue
            if rule.family == "vwap_reject":
                found = first_vwap_reject(g, ctx["vwap"], ctx["pre_low"], rule.entry_start, rule.entry_end)
            else:
                found = first_low_break(g, ctx["pre_low"], rule.entry_start, rule.entry_end)
            if found is None:
                continue
            entry_ts, entry = found
            stop = ctx["pre_high"] * (1.0 + rule.stop_pad)
            stop_dist = stop - entry
            if stop_dist <= 0 or stop_dist / entry > rule.max_stop_pct:
                continue
            target = entry - rule.rr * stop_dist
            exited = exit_trade(g, "SHORT", entry_ts, stop, target, rule.exit_time)
            if exited is None:
                continue
            exit_px, reason, exit_ts = exited
            pnl = (entry - exit_px) * BASKET[inst].point_value - costs[inst].round_turn_cost()
            trades.append({
                "variant": rule.name,
                "family": rule.family,
                "instrument": inst,
                "direction": "SHORT",
                "entry_day": day,
                "entry_time": entry_ts,
                "exit_time": exit_ts,
                "signal_time": ctx["signal_time"],
                "known_time": ctx["known_time"],
                "pnl": pnl,
                "exit_reason": reason,
                "event_cluster": clusters[day],
                "event_subtype": event_type(feat),
                "signal_after_entry": int(ctx["known_time"] > entry_ts),
                "same_bar_exit": int(exit_ts == entry_ts),
            })
    return pd.DataFrame(trades)


def dense_daily(trades: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.Series:
    out = pd.Series(0.0, index=sessions)
    if trades.empty:
        return out
    daily = trades.groupby("entry_day")["pnl"].sum()
    daily.index = pd.DatetimeIndex([pd.Timestamp(x).normalize() for x in daily.index])
    return out.add(daily, fill_value=0.0)


def maxdd(daily: pd.Series) -> float:
    eq = daily.cumsum()
    return float((eq.cummax() - eq).max()) if len(eq) else 0.0


def summary(trades: pd.DataFrame, sessions: pd.DatetimeIndex, slip_mult: float = 1.0) -> dict:
    if trades.empty:
        return {"trades": 0, "days": 0, "clusters": 0, "net": 0.0, "pf": math.inf, "calmar": 0.0, "maxdd": 0.0, "sig": 0, "same": 0}
    work = trades.copy()
    if slip_mult != 1.0:
        work["pnl"] = work["pnl"] - 2.0 * (slip_mult - 1.0)
    daily = dense_daily(work, sessions)
    m = metrics(daily)
    gp = float(work.loc[work["pnl"] > 0, "pnl"].sum())
    gl = float(-work.loc[work["pnl"] < 0, "pnl"].sum())
    return {
        "trades": int(len(work)),
        "days": int(work["entry_day"].nunique()),
        "clusters": int(work["event_cluster"].nunique()),
        "net": float(work["pnl"].sum()),
        "pf": gp / gl if gl else math.inf,
        "calmar": float(m.get("calmar", 0.0)),
        "maxdd": maxdd(daily),
        "sig": int(work["signal_after_entry"].sum()),
        "same": int(work["same_bar_exit"].sum()),
    }


def bootstrap_events(trades: pd.DataFrame, n: int = 1000, seed: int = 11) -> dict:
    if trades.empty:
        return {"p_pos": 0.0, "p5": 0.0}
    vals = trades.groupby("event_cluster")["pnl"].sum().to_numpy(float)
    rng = np.random.default_rng(seed)
    sims = np.array([rng.choice(vals, size=len(vals), replace=True).sum() for _ in range(n)])
    return {"p_pos": float((sims > 0).mean()), "p5": float(np.percentile(sims, 5))}


def wfo(cands: dict[str, pd.DataFrame]) -> dict:
    clusters = sorted(set().union(*[set(df["event_cluster"]) for df in cands.values() if not df.empty]))
    rows = []
    for i, c in enumerate(clusters):
        if i < 8:
            continue
        train = set(clusters[:i])
        best = None
        best_score = -1e18
        for name, df in cands.items():
            tr = df[df["event_cluster"].isin(train)] if not df.empty else df
            if len(tr) < 10:
                continue
            net = float(tr["pnl"].sum())
            gp = float(tr.loc[tr["pnl"] > 0, "pnl"].sum())
            gl = float(-tr.loc[tr["pnl"] < 0, "pnl"].sum())
            pf = gp / gl if gl else math.inf
            score = net if pf >= 1.05 else net - 1000.0
            if score > best_score:
                best_score = score
                best = name
        if best is None:
            continue
        test = cands[best][cands[best]["event_cluster"] == c]
        rows.append(float(test["pnl"].sum()) if not test.empty else 0.0)
    if not rows:
        return {"total": 0.0, "best": 0.0, "without_best": 0.0, "final4": 0.0, "positive": 0, "folds": 0, "pass": False}
    total = float(sum(rows))
    best = float(max(rows))
    final4 = float(sum(rows[-4:]))
    return {"total": total, "best": best, "without_best": total - best, "final4": final4, "positive": int(sum(x > 0 for x in rows)), "folds": len(rows), "pass": bool(total > 0 and total - best > 0 and best <= 0.5 * total and final4 >= 0)}


def run(which: str) -> str:
    dfs, costs, sessions = load_window(which)
    cache = build_daily_frames(dfs)
    cands = {r.name: build_rule(cache, costs, r) for r in RULES}
    rows = []
    for r in RULES:
        df = cands[r.name]
        s = summary(df, sessions)
        s2 = summary(df, sessions, 2.0)
        s3 = summary(df, sessions, 3.0)
        b = bootstrap_events(df)
        rows.append({
            "name": r.name,
            "trades": s["trades"],
            "days": s["days"],
            "clusters": s["clusters"],
            "net": fmt_money(s["net"]),
            "pf": fmt_pf(s["pf"]),
            "calmar": f"{s['calmar']:.2f}",
            "maxdd": fmt_money(s["maxdd"]),
            "sig_after": s["sig"],
            "same_bar": s["same"],
            "slip2x": fmt_money(s2["net"]),
            "slip3x": fmt_money(s3["net"]),
            "boot_p_pos": f"{b['p_pos']:.2f}",
            "boot_p5": fmt_money(b["p5"]),
        })
    rows.sort(key=lambda x: float(x["net"].replace("$", "").replace(",", "")), reverse=True)
    gate = wfo(cands)
    lines = [f"## {which}", "", table(rows, ["name", "trades", "days", "clusters", "net", "pf", "calmar", "maxdd", "sig_after", "same_bar", "slip2x", "slip3x", "boot_p_pos", "boot_p5"]), "", "WFO gate:", ""]
    lines.append(table([{
        "total": fmt_money(gate["total"]),
        "best": fmt_money(gate["best"]),
        "without_best": fmt_money(gate["without_best"]),
        "final4": fmt_money(gate["final4"]),
        "positive": gate["positive"],
        "folds": gate["folds"],
        "pass": gate["pass"],
    }], ["total", "best", "without_best", "final4", "positive", "folds", "pass"]))
    best_name = rows[0]["name"]
    best_df = cands[best_name]
    if not best_df.empty:
        lines += ["", f"Best split for `{best_name}`:", ""]
        lines.append(best_df.assign(year=pd.to_datetime(best_df["entry_day"]).dt.year).groupby("year").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
        lines += ["", best_df.groupby("event_subtype").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string()]
    print(which, rows[:2], gate)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--rules", nargs="*", default=None)
    ap.add_argument("--report", default="scratch/stress_new_hypothesis_pass2_20260821_report.md")
    args = ap.parse_args()
    global RULES
    if args.rules:
        wanted = set(args.rules)
        RULES = [r for r in RULES if r.name in wanted]
    parts = ["# Stress New Hypothesis Pass 2 - 2026-08-21", "", "Scratch-only. No production code modified.", ""]
    for w in args.which:
        parts.append(run(w))
        parts.append("")
    Path(args.report).write_text("\n".join(parts), encoding="utf-8")
    print(args.report)


if __name__ == "__main__":
    main()
