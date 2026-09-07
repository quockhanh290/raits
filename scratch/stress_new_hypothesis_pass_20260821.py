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


ACCOUNT = 50_000.0


@dataclass(frozen=True)
class Rule:
    name: str
    family: str
    direction: str
    instruments: tuple[str, ...] = ("MNQ", "MES")
    breadth_min: int = 3
    wide_min: int = 2
    setup_time: str = "11:00"
    entry_start: str = "11:05"
    entry_end: str = "13:00"
    rr: float = 2.0
    exit_time: str = "15:55"
    max_stop_pct: float = 0.018
    stop_pad: float = 0.001


RULES = [
    # Morning stress continues only if the post-11:00 tape breaks the morning low.
    Rule("late_break_1100_b3_rr2_x1555", "late_break", "SHORT", breadth_min=3, wide_min=2),
    Rule("late_break_1100_b4_rr2_x1555", "late_break", "SHORT", breadth_min=4, wide_min=2),
    Rule("late_break_1130_b3_rr2_x1555", "late_break", "SHORT", breadth_min=3, wide_min=2, setup_time="11:30", entry_start="11:35"),
    # Failed stress: morning selloff, then reclaim VWAP after 11:30. Included as a non-hedge control.
    Rule("failed_stress_reclaim_1130_b3_long_x1555", "reclaim", "LONG", breadth_min=3, wide_min=2, setup_time="11:30", entry_start="11:35", rr=1.5),
    # Midday volatility expansion: no fixed 10:xx signal, trade only a fresh range break after noon.
    Rule("midday_expansion_1200_b3_rr2_x1555", "midday_expansion", "SHORT", breadth_min=3, wide_min=2, setup_time="12:00", entry_start="12:05", entry_end="14:00"),
]


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


def parse_time(hhmm: str):
    return pd.Timestamp(hhmm).time()


def vwap(bars: pd.DataFrame) -> float:
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    vol = bars["volume"]
    return float((tp * vol).sum() / vol.sum()) if float(vol.sum()) > 0 else float(bars["close"].iloc[-1])


def first_break_short(g: pd.DataFrame, level: float, start: str, end: str) -> tuple[pd.Timestamp, float] | None:
    sub = g[(g.index.time >= parse_time(start)) & (g.index.time <= parse_time(end))]
    for ts, bar in sub.iterrows():
        if float(bar["low"]) < level:
            return ts, min(float(bar["open"]), level)
    return None


def first_reclaim_long(g: pd.DataFrame, level: float, start: str, end: str) -> tuple[pd.Timestamp, float] | None:
    sub = g[(g.index.time >= parse_time(start)) & (g.index.time <= parse_time(end))]
    for ts, bar in sub.iterrows():
        if float(bar["high"]) > level:
            return ts, max(float(bar["open"]), level)
    return None


def exit_trade(g: pd.DataFrame, direction: str, entry_ts: pd.Timestamp, stop: float, target: float, end_time: str):
    fwd = g[(g.index > entry_ts) & (g.index.time <= parse_time(end_time))]
    if fwd.empty:
        return None
    exit_px = float(fwd.iloc[-1]["close"])
    reason = "time"
    exit_ts = fwd.index[-1]
    for ts, bar in fwd.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])
        op = float(bar["open"])
        if direction == "SHORT":
            if high >= stop:
                return (stop if low <= stop else op), "stop", ts
            if low <= target:
                return (target if high >= target else op), "target", ts
        else:
            if low <= stop:
                return (stop if high >= stop else op), "stop", ts
            if high >= target:
                return (target if low <= target else op), "target", ts
        exit_px = float(bar["close"])
        exit_ts = ts
    return exit_px, reason, exit_ts


def day_context(day_1m: pd.DataFrame, setup_time: str) -> dict | None:
    bars5 = resample_5m(day_1m).between_time("09:30", "15:55")
    rth = day_1m.between_time("09:30", "16:00")
    pre = bars5[bars5.index.time <= parse_time(setup_time)]
    sig = bars5[bars5.index.time == parse_time(setup_time)]
    if rth.empty or len(pre) < 8 or sig.empty:
        return None
    open_px = float(rth.iloc[0]["open"])
    sig_close = float(sig.iloc[-1]["close"])
    vw = vwap(pre)
    hi = float(pre["high"].max())
    lo = float(pre["low"].min())
    return {
        "signal_time": sig.index[-1],
        "known_time": sig.index[-1] + pd.Timedelta(minutes=5),
        "open": open_px,
        "signal_close": sig_close,
        "vwap": vw,
        "pre_high": hi,
        "pre_low": lo,
        "range_pct": (hi - lo) / open_px if open_px else 0.0,
        "ret_from_open": sig_close / open_px - 1.0 if open_px else 0.0,
        "below_stress": sig_close < open_px and sig_close < vw,
    }


def peer_features(ctxs: list[dict]) -> dict:
    return {
        "below_count": sum(1 for c in ctxs if c["below_stress"]),
        "wide_count": sum(1 for c in ctxs if c["range_pct"] >= 0.008),
        "avg_ret": float(np.mean([c["ret_from_open"] for c in ctxs])) if ctxs else 0.0,
        "avg_range": float(np.mean([c["range_pct"] for c in ctxs])) if ctxs else 0.0,
    }


def classify_event(feat: dict) -> str:
    if feat["below_count"] >= 4 and feat["wide_count"] >= 3:
        return "broad-late-liquidation"
    if feat["below_count"] >= 4:
        return "full-breadth-late-selloff"
    if feat["below_count"] >= 3 and feat["avg_ret"] <= -0.006:
        return "deep-morning-selloff"
    if feat["wide_count"] >= 3:
        return "wide-midday-chop"
    return "weak"


def cluster_ids(days: list[pd.Timestamp]) -> dict[pd.Timestamp, str]:
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
    dfs = {n: clip(load_parquet(str(Path(data_dir) / data_filename(c))), start, end) for n, c in BASKET.items()}
    sessions = pd.DatetimeIndex(sorted({
        pd.Timestamp(x).tz_localize(None).normalize()
        for x in dfs["MES"].index.normalize().unique()
    }))
    return dfs, costs, sessions


def build_rule(dfs: dict[str, pd.DataFrame], costs: dict, rule: Rule) -> pd.DataFrame:
    frames = {}
    ctxs = {}
    for inst, df in dfs.items():
        for day_ts, g in df.groupby(df.index.normalize()):
            day = pd.Timestamp(day_ts).tz_localize(None).normalize()
            ctx = day_context(g, rule.setup_time)
            if ctx is None:
                continue
            frames[(day, inst)] = g
            ctxs[(day, inst)] = ctx

    active = []
    feats = {}
    for day in sorted({d for d, _ in ctxs}):
        peers = [ctxs[(day, inst)] for inst in BASKET if (day, inst) in ctxs]
        if len(peers) < 4:
            continue
        feat = peer_features(peers)
        if feat["below_count"] >= rule.breadth_min and feat["wide_count"] >= rule.wide_min:
            active.append(day)
            feats[day] = feat
    clusters = cluster_ids(active)

    trades = []
    for day in active:
        feat = feats[day]
        for inst in rule.instruments:
            ctx = ctxs.get((day, inst))
            g = frames.get((day, inst))
            if ctx is None or g is None:
                continue
            if not ctx["below_stress"]:
                continue
            if rule.family == "reclaim":
                entry_found = first_reclaim_long(g, ctx["vwap"], rule.entry_start, rule.entry_end)
                stop = ctx["pre_low"] * (1.0 - rule.stop_pad)
                if entry_found is None:
                    continue
                entry_ts, entry = entry_found
                stop_dist = entry - stop
                target = entry + rule.rr * stop_dist
            else:
                level = ctx["pre_low"]
                entry_found = first_break_short(g, level, rule.entry_start, rule.entry_end)
                stop = ctx["pre_high"] * (1.0 + rule.stop_pad)
                if entry_found is None:
                    continue
                entry_ts, entry = entry_found
                stop_dist = stop - entry
                target = entry - rule.rr * stop_dist
            if stop_dist <= 0 or stop_dist / entry > rule.max_stop_pct:
                continue
            exited = exit_trade(g, rule.direction, entry_ts, stop, target, rule.exit_time)
            if exited is None:
                continue
            exit_px, reason, exit_ts = exited
            if rule.direction == "SHORT":
                pnl = (entry - exit_px) * BASKET[inst].point_value - costs[inst].round_turn_cost()
            else:
                pnl = (exit_px - entry) * BASKET[inst].point_value - costs[inst].round_turn_cost()
            trades.append({
                "variant": rule.name,
                "family": rule.family,
                "instrument": inst,
                "direction": rule.direction,
                "entry_day": day,
                "entry_time": entry_ts,
                "exit_time": exit_ts,
                "signal_time": ctx["signal_time"],
                "known_time": ctx["known_time"],
                "entry": entry,
                "exit": exit_px,
                "stop": stop,
                "target": target,
                "pnl": pnl,
                "exit_reason": reason,
                "event_cluster": clusters[day],
                "event_subtype": classify_event(feat),
                "signal_after_entry": int(ctx["known_time"] > entry_ts),
                "same_bar_exit": int(exit_ts == entry_ts),
            })
    return pd.DataFrame(trades)


def context_cache(dfs: dict[str, pd.DataFrame], setup_times: set[str]):
    frames = {}
    ctx_cache = {t: dict() for t in setup_times}
    for inst, df in dfs.items():
        for day_ts, g in df.groupby(df.index.normalize()):
            day = pd.Timestamp(day_ts).tz_localize(None).normalize()
            frames[(day, inst)] = g
            for setup_time in setup_times:
                ctx = day_context(g, setup_time)
                if ctx is None:
                    continue
                ctx_cache[setup_time][(day, inst)] = ctx
    return frames, ctx_cache


def build_rule_cached(cache, costs: dict, rule: Rule) -> pd.DataFrame:
    frames, ctx_cache = cache
    ctxs = ctx_cache[rule.setup_time]
    active = []
    feats = {}
    for day in sorted({d for d, _ in ctxs}):
        peers = [ctxs[(day, inst)] for inst in BASKET if (day, inst) in ctxs]
        if len(peers) < 4:
            continue
        feat = peer_features(peers)
        if feat["below_count"] >= rule.breadth_min and feat["wide_count"] >= rule.wide_min:
            active.append(day)
            feats[day] = feat
    clusters = cluster_ids(active)

    trades = []
    for day in active:
        feat = feats[day]
        for inst in rule.instruments:
            ctx = ctxs.get((day, inst))
            g = frames.get((day, inst))
            if ctx is None or g is None or not ctx["below_stress"]:
                continue
            if rule.family == "reclaim":
                entry_found = first_reclaim_long(g, ctx["vwap"], rule.entry_start, rule.entry_end)
                stop = ctx["pre_low"] * (1.0 - rule.stop_pad)
                if entry_found is None:
                    continue
                entry_ts, entry = entry_found
                stop_dist = entry - stop
                target = entry + rule.rr * stop_dist
            else:
                entry_found = first_break_short(g, ctx["pre_low"], rule.entry_start, rule.entry_end)
                stop = ctx["pre_high"] * (1.0 + rule.stop_pad)
                if entry_found is None:
                    continue
                entry_ts, entry = entry_found
                stop_dist = stop - entry
                target = entry - rule.rr * stop_dist
            if stop_dist <= 0 or stop_dist / entry > rule.max_stop_pct:
                continue
            exited = exit_trade(g, rule.direction, entry_ts, stop, target, rule.exit_time)
            if exited is None:
                continue
            exit_px, reason, exit_ts = exited
            pnl = ((entry - exit_px) if rule.direction == "SHORT" else (exit_px - entry)) * BASKET[inst].point_value
            pnl -= costs[inst].round_turn_cost()
            trades.append({
                "variant": rule.name,
                "family": rule.family,
                "instrument": inst,
                "direction": rule.direction,
                "entry_day": day,
                "entry_time": entry_ts,
                "exit_time": exit_ts,
                "signal_time": ctx["signal_time"],
                "known_time": ctx["known_time"],
                "entry": entry,
                "exit": exit_px,
                "stop": stop,
                "target": target,
                "pnl": pnl,
                "exit_reason": reason,
                "event_cluster": clusters[day],
                "event_subtype": classify_event(feat),
                "signal_after_entry": int(ctx["known_time"] > entry_ts),
                "same_bar_exit": int(exit_ts == entry_ts),
            })
    return pd.DataFrame(trades)


def dense_daily(trades: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.Series:
    s = pd.Series(0.0, index=sessions)
    if not trades.empty:
        daily = trades.groupby("entry_day")["pnl"].sum()
        daily.index = pd.DatetimeIndex([pd.Timestamp(x).normalize() for x in daily.index])
        s = s.add(daily, fill_value=0.0)
    return s


def maxdd(daily: pd.Series) -> float:
    eq = daily.cumsum()
    return float((eq.cummax() - eq).max()) if len(eq) else 0.0


def summary(trades: pd.DataFrame, sessions: pd.DatetimeIndex, slip_mult: float = 1.0) -> dict:
    if trades.empty:
        return {"trades": 0, "days": 0, "clusters": 0, "net": 0.0, "pf": math.inf, "sharpe": 0.0, "calmar": 0.0, "maxdd": 0.0}
    work = trades.copy()
    if slip_mult != 1.0:
        work["pnl"] = work["pnl"] - 2.0 * (slip_mult - 1.0)
    daily = dense_daily(work, sessions)
    m = metrics(daily)
    dd = maxdd(daily)
    gp = float(work.loc[work["pnl"] > 0, "pnl"].sum())
    gl = float(-work.loc[work["pnl"] < 0, "pnl"].sum())
    return {
        "trades": int(len(work)),
        "days": int(work["entry_day"].nunique()),
        "clusters": int(work["event_cluster"].nunique()),
        "net": float(work["pnl"].sum()),
        "pf": gp / gl if gl else math.inf,
        "sharpe": float(m.get("sharpe", 0.0)),
        "calmar": float(m.get("calmar", 0.0)),
        "maxdd": dd,
        "target_rate": float((work["exit_reason"] == "target").mean()),
        "stop_rate": float((work["exit_reason"] == "stop").mean()),
        "signal_after_entry": int(work["signal_after_entry"].sum()),
        "same_bar_exit": int(work["same_bar_exit"].sum()),
    }


def bootstrap_events(trades: pd.DataFrame, n: int = 1000, seed: int = 7) -> dict:
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


def wfo(cands: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    all_clusters = sorted(set().union(*[set(df["event_cluster"]) for df in cands.values() if not df.empty]))
    rows = []
    for i, cluster in enumerate(all_clusters):
        if i < 8:
            continue
        train_clusters = set(all_clusters[:i])
        best = None
        best_score = -1e18
        for name, df in cands.items():
            tr = df[df["event_cluster"].isin(train_clusters)] if not df.empty else df
            if len(tr) < 10:
                continue
            s = summary(tr, pd.DatetimeIndex(sorted(pd.Timestamp(x).normalize() for x in tr["entry_day"].unique())))
            score = s["net"] if s["pf"] >= 1.05 else s["net"] - 1000.0
            if score > best_score:
                best_score = score
                best = name
        if best is None:
            continue
        test = cands[best][cands[best]["event_cluster"] == cluster]
        rows.append({
            "test_cluster": cluster,
            "selected": best,
            "trades": int(len(test)),
            "net": float(test["pnl"].sum()) if not test.empty else 0.0,
            "pf": summary(test, pd.DatetimeIndex([pd.Timestamp(x).normalize() for x in test["entry_day"].unique()]))["pf"] if not test.empty else math.inf,
        })
    wf = pd.DataFrame(rows)
    if wf.empty:
        return wf, {"total": 0.0, "best": 0.0, "without_best": 0.0, "best_share": 0.0, "final4": 0.0, "pass": False}
    total = float(wf["net"].sum())
    best = float(wf["net"].max())
    return wf, {
        "total": total,
        "best": best,
        "without_best": total - best,
        "best_share": best / total if total > 0 else math.inf,
        "final4": float(wf.tail(4)["net"].sum()),
        "positive": int((wf["net"] > 0).sum()),
        "folds": int(len(wf)),
        "pass": bool(total > 0 and total - best > 0 and best <= 0.5 * total and float(wf.tail(4)["net"].sum()) >= 0),
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
    cache = context_cache(dfs, {r.setup_time for r in RULES})
    cands = {r.name: build_rule_cached(cache, costs, r) for r in RULES}
    rows = []
    for r in RULES:
        df = cands[r.name]
        s = summary(df, sessions)
        s2 = summary(df, sessions, slip_mult=2.0)
        s3 = summary(df, sessions, slip_mult=3.0)
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
            "sig_after": s["signal_after_entry"],
            "same_bar": s["same_bar_exit"],
            "slip2x": fmt_money(s2["net"]),
            "slip3x": fmt_money(s3["net"]),
            "boot_p_pos": f"{b['p_pos']:.2f}",
            "boot_p5": fmt_money(b["p5"]),
        })
    rows.sort(key=lambda x: float(x["net"].replace("$", "").replace(",", "")), reverse=True)
    wf, gate = wfo(cands)

    lines = [f"## {which}", "", "Candidate table:", ""]
    lines.append(table(rows, ["name", "trades", "days", "clusters", "net", "pf", "calmar", "maxdd", "sig_after", "same_bar", "slip2x", "slip3x", "boot_p_pos", "boot_p5"]))
    lines += ["", "WFO gate:", ""]
    lines.append(table([{
        "total": fmt_money(gate["total"]),
        "best": fmt_money(gate["best"]),
        "without_best": fmt_money(gate["without_best"]),
        "best_share": "inf" if math.isinf(gate["best_share"]) else f"{gate['best_share']:.2f}",
        "final4": fmt_money(gate["final4"]),
        "positive": gate.get("positive", 0),
        "folds": gate.get("folds", 0),
        "pass": gate["pass"],
    }], ["total", "best", "without_best", "best_share", "final4", "positive", "folds", "pass"]))
    lines += ["", "By year for best standalone row:", ""]
    best_name = rows[0]["name"] if rows else RULES[0].name
    best_df = cands[best_name]
    if not best_df.empty:
        by_year = best_df.assign(year=pd.to_datetime(best_df["entry_day"]).dt.year).groupby("year").agg(
            trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")
        )
        lines.append(by_year.to_string())
        lines += ["", "By instrument/subtype:", ""]
        lines.append(best_df.groupby("instrument").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
        lines.append("")
        lines.append(best_df.groupby("event_subtype").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
    print(which, rows[:2], gate)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--report", default="scratch/stress_new_hypothesis_pass_20260821_report.md")
    args = ap.parse_args()
    parts = [
        "# Stress New Hypothesis Pass - 2026-08-21",
        "",
        "Scratch-only. No production code modified.",
        "",
        "These rules do not use daily Stress labels and do not tune around the 10:15/10:20 breadth detector.",
        "",
    ]
    for w in args.which:
        parts.append(run(w))
        parts.append("")
    Path(args.report).write_text("\n".join(parts), encoding="utf-8")
    print(args.report)


if __name__ == "__main__":
    main()
