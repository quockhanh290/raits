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


@dataclass(frozen=True)
class Rule:
    name: str
    instruments: tuple[str, ...]
    entry_mode: str
    rr: float = 2.0
    setup_time: str = "10:30"
    known_after: str = "10:35"
    entry_start: str = "10:40"
    entry_end: str = "12:30"
    exit_time: str = "15:55"
    min_gapdown: float = -0.004
    max_stop_pct: float = 0.018
    stop_pad: float = 0.001


RULES = [
    Rule("gapshock_full_breadth_break_1040_mnq_mes_rr2", ("MNQ", "MES"), "break"),
    Rule("gapshock_full_breadth_break_1040_mnq_only_rr2", ("MNQ",), "break"),
    Rule("gapshock_full_breadth_retestfail_1040_mnq_mes_rr2", ("MNQ", "MES"), "retest_fail"),
]


def arg_from(argv: list[str], flag: str, default=None):
    if flag not in argv:
        return default
    return argv[argv.index(flag) + 1]


def parse_time(hhmm: str):
    return pd.Timestamp(hhmm).time()


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


def day_frames_and_prev(dfs: dict[str, pd.DataFrame]):
    frames = {}
    prev = {}
    for inst, df in dfs.items():
        last_close = None
        for day_ts, g in df.groupby(df.index.normalize()):
            day = pd.Timestamp(day_ts).tz_localize(None).normalize()
            rth = g.between_time("09:30", "16:00")
            if rth.empty:
                continue
            frames[(day, inst)] = g
            prev[(day, inst)] = last_close
            last_close = float(rth.iloc[-1]["close"])
    return frames, prev


def context(g: pd.DataFrame, prev_close: float | None, rule: Rule) -> dict | None:
    if prev_close is None:
        return None
    bars5 = resample_5m(g).between_time("09:30", rule.exit_time)
    rth = g.between_time("09:30", "16:00")
    pre = bars5[bars5.index.time <= parse_time(rule.setup_time)]
    sig = bars5[bars5.index.time == parse_time(rule.setup_time)]
    if rth.empty or len(pre) < 8 or sig.empty:
        return None
    op = float(rth.iloc[0]["open"])
    close = float(sig.iloc[-1]["close"])
    vw = vwap(pre)
    hi = float(pre["high"].max())
    lo = float(pre["low"].min())
    return {
        "signal_time": sig.index[-1],
        "known_time": sig.index[-1] + pd.Timedelta(minutes=5),
        "open": op,
        "prev_close": prev_close,
        "gap": op / prev_close - 1.0,
        "close": close,
        "vwap": vw,
        "pre_high": hi,
        "pre_low": lo,
        "below": close < op and close < vw,
        "full_range_pct": (hi - lo) / op if op else 0.0,
    }


def first_break(g: pd.DataFrame, level: float, start: str, end: str):
    sub = g[(g.index.time >= parse_time(start)) & (g.index.time <= parse_time(end))]
    for ts, bar in sub.iterrows():
        if float(bar["low"]) < level:
            return ts, min(float(bar["open"]), level)
    return None


def first_retest_fail(g: pd.DataFrame, vwap_level: float, low_level: float, start: str, end: str):
    sub = g[(g.index.time >= parse_time(start)) & (g.index.time <= parse_time(end))]
    touched_vwap = False
    for ts, bar in sub.iterrows():
        if float(bar["high"]) >= vwap_level:
            touched_vwap = True
        if touched_vwap and float(bar["low"]) < low_level:
            return ts, min(float(bar["open"]), low_level)
    return None


def exit_short(g: pd.DataFrame, entry_ts: pd.Timestamp, stop: float, target: float, exit_time: str):
    fwd = g[(g.index > entry_ts) & (g.index.time <= parse_time(exit_time))]
    if fwd.empty:
        return None
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


def event_clusters(days: list[pd.Timestamp]) -> dict[pd.Timestamp, str]:
    out = {}
    last = None
    cluster = 0
    for d in sorted(set(pd.Timestamp(x).normalize() for x in days)):
        if last is None or (d - last).days > 3:
            cluster += 1
        out[d] = f"E{cluster:03d}"
        last = d
    return out


def build_rule(frames: dict, prev: dict, costs: dict, rule: Rule) -> pd.DataFrame:
    ctxs = {}
    for key, g in frames.items():
        c = context(g, prev.get(key), rule)
        if c is not None:
            ctxs[key] = c

    active = []
    features = {}
    for day in sorted({d for d, _ in ctxs}):
        peers = [ctxs[(day, inst)] for inst in BASKET if (day, inst) in ctxs]
        if len(peers) != 4:
            continue
        gapdown_count = sum(1 for c in peers if c["gap"] <= rule.min_gapdown)
        below_count = sum(1 for c in peers if c["below"])
        if gapdown_count >= 3 and below_count == 4:
            active.append(day)
            features[day] = {
                "gapdown_count": gapdown_count,
                "below_count": below_count,
                "avg_gap": float(np.mean([c["gap"] for c in peers])),
                "avg_range_pct": float(np.mean([c["full_range_pct"] for c in peers])),
            }
    clusters = event_clusters(active)

    rows = []
    for day in active:
        feat = features[day]
        for inst in rule.instruments:
            c = ctxs.get((day, inst))
            g = frames.get((day, inst))
            if c is None or g is None or not c["below"]:
                continue
            if rule.entry_mode == "break":
                found = first_break(g, c["pre_low"], rule.entry_start, rule.entry_end)
            elif rule.entry_mode == "retest_fail":
                found = first_retest_fail(g, c["vwap"], c["pre_low"], rule.entry_start, rule.entry_end)
            else:
                raise ValueError(rule.entry_mode)
            if found is None:
                continue
            entry_ts, entry = found
            stop = c["pre_high"] * (1.0 + rule.stop_pad)
            dist = stop - entry
            if dist <= 0 or dist / entry > rule.max_stop_pct:
                continue
            target = entry - rule.rr * dist
            exited = exit_short(g, entry_ts, stop, target, rule.exit_time)
            if exited is None:
                continue
            exit_px, reason, exit_ts = exited
            pnl = (entry - exit_px) * BASKET[inst].point_value - costs[inst].round_turn_cost()
            rows.append({
                "variant": rule.name,
                "instrument": inst,
                "direction": "SHORT",
                "day": day,
                "entry_time": entry_ts,
                "signal_time": c["signal_time"],
                "known_time": c["known_time"],
                "exit_time": exit_ts,
                "entry": entry,
                "exit": exit_px,
                "stop": stop,
                "target": target,
                "pnl": pnl,
                "exit_reason": reason,
                "event_cluster": clusters[day],
                "event_subtype": "gapdown-full-breadth",
                "avg_gap": feat["avg_gap"],
                "avg_range_pct": feat["avg_range_pct"],
                "signal_after_entry": int(c["known_time"] > entry_ts),
                "same_bar_exit": int(exit_ts == entry_ts),
            })
    return pd.DataFrame(rows)


def dense_daily(trades: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.Series:
    s = pd.Series(0.0, index=sessions)
    if trades.empty:
        return s
    d = trades.groupby("day")["pnl"].sum()
    d.index = pd.DatetimeIndex([pd.Timestamp(x).normalize() for x in d.index])
    return s.add(d, fill_value=0.0)


def maxdd(daily: pd.Series) -> float:
    eq = daily.cumsum()
    return float((eq.cummax() - eq).max()) if len(eq) else 0.0


def summarize(trades: pd.DataFrame, sessions: pd.DatetimeIndex, slip_mult: float = 1.0) -> dict:
    if trades.empty:
        return {"trades": 0, "days": 0, "clusters": 0, "net": 0.0, "pf": math.inf, "calmar": 0.0, "sharpe": 0.0, "maxdd": 0.0, "sig": 0, "same": 0}
    work = trades.copy()
    if slip_mult != 1.0:
        work["pnl"] = work["pnl"] - 2.0 * (slip_mult - 1.0)
    daily = dense_daily(work, sessions)
    m = metrics(daily)
    gp = float(work.loc[work["pnl"] > 0, "pnl"].sum())
    gl = float(-work.loc[work["pnl"] < 0, "pnl"].sum())
    return {
        "trades": int(len(work)),
        "days": int(work["day"].nunique()),
        "clusters": int(work["event_cluster"].nunique()),
        "net": float(work["pnl"].sum()),
        "pf": gp / gl if gl else math.inf,
        "calmar": float(m["calmar"]),
        "sharpe": float(m["sharpe"]),
        "maxdd": maxdd(daily),
        "target_rate": float((work["exit_reason"] == "target").mean()),
        "stop_rate": float((work["exit_reason"] == "stop").mean()),
        "sig": int(work["signal_after_entry"].sum()),
        "same": int(work["same_bar_exit"].sum()),
    }


def bootstrap_events(trades: pd.DataFrame, n: int = 1000, seed: int = 21) -> dict:
    if trades.empty:
        return {"events": 0, "p_pos": 0.0, "p5": 0.0, "p50": 0.0, "p95": 0.0}
    vals = trades.groupby("event_cluster")["pnl"].sum().to_numpy(float)
    rng = np.random.default_rng(seed)
    sims = np.array([rng.choice(vals, size=len(vals), replace=True).sum() for _ in range(n)])
    return {
        "events": int(len(vals)),
        "p_pos": float((sims > 0).mean()),
        "p5": float(np.percentile(sims, 5)),
        "p50": float(np.percentile(sims, 50)),
        "p95": float(np.percentile(sims, 95)),
    }


def wfo(cands: dict[str, pd.DataFrame]) -> dict:
    clusters = sorted(set().union(*[set(df["event_cluster"]) for df in cands.values() if not df.empty]))
    rows = []
    for i, cluster in enumerate(clusters):
        if i < 8:
            continue
        train_clusters = set(clusters[:i])
        best = None
        best_score = -1e18
        for name, df in cands.items():
            train = df[df["event_cluster"].isin(train_clusters)] if not df.empty else df
            if len(train) < 8:
                continue
            gp = float(train.loc[train["pnl"] > 0, "pnl"].sum())
            gl = float(-train.loc[train["pnl"] < 0, "pnl"].sum())
            pf = gp / gl if gl else math.inf
            net = float(train["pnl"].sum())
            score = net if pf >= 1.05 else net - 1000.0
            if score > best_score:
                best = name
                best_score = score
        if best is None:
            continue
        test = cands[best][cands[best]["event_cluster"] == cluster]
        rows.append({
            "test_cluster": cluster,
            "selected": best,
            "trades": int(len(test)),
            "net": float(test["pnl"].sum()) if not test.empty else 0.0,
        })
    wf = pd.DataFrame(rows)
    if wf.empty:
        return {"total": 0.0, "best": 0.0, "without_best": 0.0, "final4": 0.0, "positive": 0, "folds": 0, "pass": False}
    total = float(wf["net"].sum())
    best = float(wf["net"].max())
    final4 = float(wf.tail(4)["net"].sum())
    return {
        "total": total,
        "best": best,
        "without_best": total - best,
        "final4": final4,
        "positive": int((wf["net"] > 0).sum()),
        "folds": int(len(wf)),
        "pass": bool(total > 0 and total - best > 0 and best <= 0.5 * total and final4 >= 0),
    }


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def fmt_pf(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def run(which: str) -> str:
    dfs, costs, sessions = load_window(which)
    frames, prev = day_frames_and_prev(dfs)
    cands = {r.name: build_rule(frames, prev, costs, r) for r in RULES}
    rows = []
    for r in RULES:
        df = cands[r.name]
        s = summarize(df, sessions)
        s2 = summarize(df, sessions, 2.0)
        s3 = summarize(df, sessions, 3.0)
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
            "target_rate": f"{s['target_rate']:.2f}" if s["trades"] else "0.00",
            "stop_rate": f"{s['stop_rate']:.2f}" if s["trades"] else "0.00",
            "sig_after": s["sig"],
            "same_bar": s["same"],
            "slip2x": fmt_money(s2["net"]),
            "slip3x": fmt_money(s3["net"]),
            "boot_p_pos": f"{b['p_pos']:.2f}",
            "boot_p5": fmt_money(b["p5"]),
        })
    rows.sort(key=lambda r: float(r["net"].replace("$", "").replace(",", "")), reverse=True)
    gate = wfo(cands)
    lines = [f"## {which}", "", "Candidate table:", ""]
    lines.append(table(rows, ["name", "trades", "days", "clusters", "net", "pf", "calmar", "maxdd", "target_rate", "stop_rate", "sig_after", "same_bar", "slip2x", "slip3x", "boot_p_pos", "boot_p5"]))
    lines += ["", "WFO gate:", ""]
    lines.append(table([{
        "total": fmt_money(gate["total"]),
        "best": fmt_money(gate["best"]),
        "without_best": fmt_money(gate["without_best"]),
        "final4": fmt_money(gate["final4"]),
        "positive": gate["positive"],
        "folds": gate["folds"],
        "pass": gate["pass"],
    }], ["total", "best", "without_best", "final4", "positive", "folds", "pass"]))
    best_name = rows[0]["name"] if rows else RULES[0].name
    best_df = cands[best_name]
    if not best_df.empty:
        lines += ["", f"Best split for `{best_name}`:", ""]
        lines.append(best_df.assign(year=pd.to_datetime(best_df["day"]).dt.year).groupby("year").agg(
            trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")
        ).to_string())
        lines += ["", best_df.groupby("instrument").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string()]
    print(which, rows[:2], gate)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--report", default="scratch/stress_gapshock_rebuild_20260821_report.md")
    args = ap.parse_args()
    parts = [
        "# Stress Gap-Shock Sleeve Rebuild - 2026-08-21",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Protocol frozen before reading this pass:",
        "",
        "- no daily Stress label;",
        "- event trigger is overnight gap-down in at least 3/4 R4 instruments plus 4/4 below open and VWAP at the 10:30 5-minute bar;",
        "- the 10:30 bar is treated as known at 10:35;",
        "- entries are allowed only from 10:40 onward;",
        "- SHORT only, stop at setup high * 1.001, target 2R, exit 15:55;",
        "- candidates are limited to MNQ/MES break, MNQ-only break, and MNQ/MES retest-fail.",
        "",
    ]
    for w in args.which:
        parts.append(run(w))
        parts.append("")
    Path(args.report).write_text("\n".join(parts), encoding="utf-8")
    print(args.report)


if __name__ == "__main__":
    main()
