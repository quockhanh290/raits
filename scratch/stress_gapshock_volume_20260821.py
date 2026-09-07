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
    vol_filter: str
    relvol_min: float = 1.2
    min_gapdown: float = -0.004
    setup_time: str = "10:30"
    entry_start: str = "10:40"
    entry_end: str = "12:30"
    exit_time: str = "15:55"
    rr: float = 2.0
    max_stop_pct: float = 0.018
    stop_pad: float = 0.001


RULES = [
    Rule("gapshock_mnqmes_base", ("MNQ", "MES"), "none"),
    Rule("gapshock_mnq_base", ("MNQ",), "none"),
    Rule("gapshock_mnqmes_cumvol12", ("MNQ", "MES"), "cum"),
    Rule("gapshock_mnq_cumvol12", ("MNQ",), "cum"),
    Rule("gapshock_mnqmes_breakvol12", ("MNQ", "MES"), "break"),
    Rule("gapshock_mnq_breakvol12", ("MNQ",), "break"),
    Rule("gapshock_mnqmes_bothvol12", ("MNQ", "MES"), "both"),
    Rule("gapshock_mnq_bothvol12", ("MNQ",), "both"),
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


def build_frames(dfs: dict[str, pd.DataFrame]):
    frames, prev = {}, {}
    for inst, df in dfs.items():
        last = None
        for day_ts, g in df.groupby(df.index.normalize()):
            day = pd.Timestamp(day_ts).tz_localize(None).normalize()
            rth = g.between_time("09:30", "16:00")
            if rth.empty:
                continue
            frames[(day, inst)] = g
            prev[(day, inst)] = last
            last = float(rth.iloc[-1]["close"])
    return frames, prev


def volume_baselines(frames: dict) -> dict:
    hist = {inst: [] for inst in BASKET}
    out = {}
    for day in sorted({d for d, _ in frames}):
        for inst in BASKET:
            g = frames.get((day, inst))
            if g is None:
                continue
            cum = float(g.between_time("09:30", "10:30")["volume"].sum())
            # Median volume of bars that can be entry/break bars; causal prior days only.
            br = float(g[(g.index.time >= parse_time("10:40")) & (g.index.time <= parse_time("12:30"))]["volume"].median())
            h = hist[inst]
            out[(day, inst)] = {
                "cum_med20": float(np.median([x[0] for x in h[-20:]])) if len(h) >= 10 else np.nan,
                "break_med20": float(np.median([x[1] for x in h[-20:]])) if len(h) >= 10 else np.nan,
            }
            hist[inst].append((cum, br if not np.isnan(br) else 0.0))
    return out


def context(g: pd.DataFrame, prev_close: float | None, base: dict | None):
    if prev_close is None or base is None:
        return None
    bars5 = resample_5m(g).between_time("09:30", "15:55")
    rth = g.between_time("09:30", "16:00")
    pre = bars5[bars5.index.time <= parse_time("10:30")]
    sig = bars5[bars5.index.time == parse_time("10:30")]
    if rth.empty or len(pre) < 8 or sig.empty:
        return None
    op = float(rth.iloc[0]["open"])
    close = float(sig.iloc[-1]["close"])
    vw = vwap(pre)
    cumvol = float(g.between_time("09:30", "10:30")["volume"].sum())
    cum_rel = cumvol / base["cum_med20"] if base["cum_med20"] and not np.isnan(base["cum_med20"]) else np.nan
    return {
        "signal_time": sig.index[-1],
        "known_time": sig.index[-1] + pd.Timedelta(minutes=5),
        "open": op,
        "gap": op / prev_close - 1.0,
        "close": close,
        "vwap": vw,
        "pre_high": float(pre["high"].max()),
        "pre_low": float(pre["low"].min()),
        "below": close < op and close < vw,
        "cum_relvol": cum_rel,
        "break_med20": base["break_med20"],
    }


def first_break(g: pd.DataFrame, level: float, start: str, end: str, break_med20: float):
    sub = g[(g.index.time >= parse_time(start)) & (g.index.time <= parse_time(end))]
    for ts, bar in sub.iterrows():
        if float(bar["low"]) < level:
            br_rel = float(bar["volume"]) / break_med20 if break_med20 and not np.isnan(break_med20) else np.nan
            return ts, min(float(bar["open"]), level), br_rel
    return None


def exit_short(g: pd.DataFrame, entry_ts: pd.Timestamp, stop: float, target: float):
    fwd = g[(g.index > entry_ts) & (g.index.time <= parse_time("15:55"))]
    if fwd.empty:
        return None
    ex = float(fwd.iloc[-1]["close"])
    reason = "time"
    xt = fwd.index[-1]
    for ts, bar in fwd.iterrows():
        high, low, op = float(bar["high"]), float(bar["low"]), float(bar["open"])
        if high >= stop:
            return (stop if low <= stop else op), "stop", ts
        if low <= target:
            return (target if high >= target else op), "target", ts
        ex, xt = float(bar["close"]), ts
    return ex, reason, xt


def clusters(days):
    out, last, n = {}, None, 0
    for day in sorted(set(pd.Timestamp(x).normalize() for x in days)):
        if last is None or (day - last).days > 3:
            n += 1
        out[day] = f"E{n:03d}"
        last = day
    return out


def passes_volume(rule: Rule, peer_ctxs: list[dict], br_rel: float) -> bool:
    if rule.vol_filter == "none":
        return True
    cum_ok = sum(1 for c in peer_ctxs if not np.isnan(c["cum_relvol"]) and c["cum_relvol"] >= rule.relvol_min) >= 3
    br_ok = not np.isnan(br_rel) and br_rel >= rule.relvol_min
    if rule.vol_filter == "cum":
        return cum_ok
    if rule.vol_filter == "break":
        return br_ok
    if rule.vol_filter == "both":
        return cum_ok and br_ok
    raise ValueError(rule.vol_filter)


def build_rule(frames: dict, prev: dict, bases: dict, costs: dict, rule: Rule) -> pd.DataFrame:
    ctxs = {}
    for key, g in frames.items():
        c = context(g, prev.get(key), bases.get(key))
        if c is not None:
            ctxs[key] = c
    active = []
    for day in sorted({d for d, _ in ctxs}):
        peers = [ctxs[(day, inst)] for inst in BASKET if (day, inst) in ctxs]
        if len(peers) == 4 and sum(c["gap"] <= rule.min_gapdown for c in peers) >= 3 and sum(c["below"] for c in peers) == 4:
            active.append(day)
    cid = clusters(active)
    rows = []
    for day in active:
        peer_ctxs = [ctxs[(day, inst)] for inst in BASKET if (day, inst) in ctxs]
        for inst in rule.instruments:
            c, g = ctxs.get((day, inst)), frames.get((day, inst))
            if c is None or g is None or not c["below"]:
                continue
            found = first_break(g, c["pre_low"], rule.entry_start, rule.entry_end, c["break_med20"])
            if found is None:
                continue
            entry_ts, entry, br_rel = found
            if not passes_volume(rule, peer_ctxs, br_rel):
                continue
            stop = c["pre_high"] * (1.0 + rule.stop_pad)
            dist = stop - entry
            if dist <= 0 or dist / entry > rule.max_stop_pct:
                continue
            target = entry - rule.rr * dist
            exited = exit_short(g, entry_ts, stop, target)
            if exited is None:
                continue
            exit_px, reason, exit_ts = exited
            pnl = (entry - exit_px) * BASKET[inst].point_value - costs[inst].round_turn_cost()
            rows.append({
                "variant": rule.name,
                "instrument": inst,
                "day": day,
                "entry_time": entry_ts,
                "known_time": c["known_time"],
                "exit_time": exit_ts,
                "pnl": pnl,
                "exit_reason": reason,
                "event_cluster": cid[day],
                "cum_relvol": c["cum_relvol"],
                "break_relvol": br_rel,
                "signal_after_entry": int(c["known_time"] > entry_ts),
                "same_bar_exit": int(exit_ts == entry_ts),
            })
    return pd.DataFrame(rows)


def dense_daily(trades, sessions):
    s = pd.Series(0.0, index=sessions)
    if trades.empty:
        return s
    d = trades.groupby("day")["pnl"].sum()
    d.index = pd.DatetimeIndex([pd.Timestamp(x).normalize() for x in d.index])
    return s.add(d, fill_value=0.0)


def summarize(trades, sessions, slip=1.0):
    if trades.empty:
        return dict(trades=0, days=0, clusters=0, net=0.0, pf=math.inf, calmar=0.0, maxdd=0.0, sig=0, same=0)
    work = trades.copy()
    if slip != 1.0:
        work["pnl"] = work["pnl"] - 2.0 * (slip - 1.0)
    daily = dense_daily(work, sessions)
    m = metrics(daily)
    gp = float(work.loc[work["pnl"] > 0, "pnl"].sum())
    gl = float(-work.loc[work["pnl"] < 0, "pnl"].sum())
    eq = daily.cumsum()
    dd = float((eq.cummax() - eq).max())
    return dict(trades=len(work), days=work["day"].nunique(), clusters=work["event_cluster"].nunique(),
                net=float(work["pnl"].sum()), pf=gp / gl if gl else math.inf,
                calmar=float(m["calmar"]), maxdd=dd,
                sig=int(work["signal_after_entry"].sum()), same=int(work["same_bar_exit"].sum()))


def boot(trades, n=1000):
    if trades.empty:
        return dict(p_pos=0.0, p5=0.0)
    vals = trades.groupby("event_cluster")["pnl"].sum().to_numpy(float)
    rng = np.random.default_rng(41)
    sims = np.array([rng.choice(vals, len(vals), replace=True).sum() for _ in range(n)])
    return dict(p_pos=float((sims > 0).mean()), p5=float(np.percentile(sims, 5)))


def fmt_money(x):
    return f"${x:,.0f}"


def fmt_pf(x):
    return "inf" if math.isinf(x) else f"{x:.2f}"


def table(rows, cols):
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def run(which):
    dfs, costs, sessions = load_window(which)
    frames, prev = build_frames(dfs)
    bases = volume_baselines(frames)
    rows = []
    for rule in RULES:
        tr = build_rule(frames, prev, bases, costs, rule)
        s, s2, s3, b = summarize(tr, sessions), summarize(tr, sessions, 2.0), summarize(tr, sessions, 3.0), boot(tr)
        rows.append({
            "name": rule.name,
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
    rows.sort(key=lambda r: float(r["net"].replace("$", "").replace(",", "")), reverse=True)
    print(which, rows[:3])
    return "\n".join([f"## {which}", "", table(rows, ["name", "trades", "days", "clusters", "net", "pf", "calmar", "maxdd", "sig_after", "same_bar", "slip2x", "slip3x", "boot_p_pos", "boot_p5"])])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--rules", nargs="*", default=None)
    ap.add_argument("--report", default="scratch/stress_gapshock_volume_20260821_report.md")
    args = ap.parse_args()
    global RULES
    if args.rules:
        wanted = set(args.rules)
        RULES = [r for r in RULES if r.name in wanted]
    parts = [
        "# Stress Gap-Shock Volume Confirmation - 2026-08-21",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Tests volume confirmation on the strict gap-shock sleeve only.",
        "Volume baselines use prior-day-only rolling medians, so filters are causal.",
        "",
    ]
    for which in args.which:
        parts.append(run(which))
        parts.append("")
    Path(args.report).write_text("\n".join(parts), encoding="utf-8")
    print(args.report)


if __name__ == "__main__":
    main()
