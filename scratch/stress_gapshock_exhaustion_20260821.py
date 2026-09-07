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
    instruments: tuple[str, ...] = ("MNQ", "MES")
    filt: str = "base"
    rr: float = 2.0
    min_gapdown: float = -0.004
    setup_time: str = "10:30"
    entry_start: str = "10:40"
    entry_end: str = "12:30"
    exit_time: str = "15:55"
    max_stop_pct: float = 0.018
    stop_pad: float = 0.001


RULES = [
    Rule("base_mnqmes"),
    Rule("base_mnq", instruments=("MNQ",)),
    Rule("not_deep_gap_mnqmes", filt="not_deep_gap"),
    Rule("not_extended_1030_mnqmes", filt="not_extended_1030"),
    Rule("not_deep_gap_or_extended_mnqmes", filt="not_deep_or_extended"),
    Rule("d1_not_crash_mnqmes", filt="d1_not_crash"),
    Rule("d1_close_weak_not_extreme_mnqmes", filt="d1_weak_not_extreme"),
    Rule("in_prior_range_open_mnqmes", filt="open_in_prior_range"),
    Rule("leadership_mnq_weakest_mnq", instruments=("MNQ",), filt="mnq_weakest"),
]


def arg_from(argv: list[str], flag: str, default=None):
    if flag not in argv:
        return default
    return argv[argv.index(flag) + 1]


def parse_time(hhmm: str):
    return pd.Timestamp(hhmm).time()


def clip(df, start, end):
    if start:
        df = df[df.index >= pd.Timestamp(start).tz_localize(df.index.tz)]
    if end:
        df = df[df.index <= pd.Timestamp(end).tz_localize(df.index.tz)]
    return df


def load_window(which):
    argv = list(ARGV[which])
    data_dir = arg_from(argv, "--data-dir")
    start = arg_from(argv, "--start")
    end = arg_from(argv, "--end")
    costs = costs_for_basket(slippage_ticks=float(arg_from(argv, "--slippage-ticks", 2.0)))
    dfs = {n: clip(load_parquet(str(Path(data_dir) / data_filename(c))), start, end) for n, c in BASKET.items()}
    sessions = pd.DatetimeIndex(sorted({pd.Timestamp(x).tz_localize(None).normalize() for x in dfs["MES"].index.normalize().unique()}))
    return dfs, costs, sessions


def vwap(bars):
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    vol = bars["volume"]
    return float((tp * vol).sum() / vol.sum()) if float(vol.sum()) > 0 else float(bars["close"].iloc[-1])


def frames_prev_stats(dfs):
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
            last = {
                "close": float(rth.iloc[-1]["close"]),
                "open": float(rth.iloc[0]["open"]),
                "high": float(rth["high"].max()),
                "low": float(rth["low"].min()),
            }
    return frames, prev


def context(g, p, setup_time):
    if p is None:
        return None
    bars5 = resample_5m(g).between_time("09:30", "15:55")
    rth = g.between_time("09:30", "16:00")
    pre = bars5[bars5.index.time <= parse_time(setup_time)]
    sig = bars5[bars5.index.time == parse_time(setup_time)]
    if rth.empty or len(pre) < 8 or sig.empty:
        return None
    op = float(rth.iloc[0]["open"])
    close = float(sig.iloc[-1]["close"])
    vw = vwap(pre)
    prev_range = max(float(p["high"] - p["low"]), 1e-9)
    return {
        "signal_time": sig.index[-1],
        "known_time": sig.index[-1] + pd.Timedelta(minutes=5),
        "open": op,
        "gap": op / p["close"] - 1.0,
        "close": close,
        "vwap": vw,
        "pre_high": float(pre["high"].max()),
        "pre_low": float(pre["low"].min()),
        "below": close < op and close < vw,
        "ret_1030_from_prev_close": close / p["close"] - 1.0,
        "d1_ret": p["close"] / p["open"] - 1.0,
        "d1_range_pct": prev_range / p["open"],
        "d1_close_loc": (p["close"] - p["low"]) / prev_range,
        "open_loc_prev_range": (op - p["low"]) / prev_range,
        "prior_low": p["low"],
        "prior_high": p["high"],
    }


def first_break(g, level, start, end):
    sub = g[(g.index.time >= parse_time(start)) & (g.index.time <= parse_time(end))]
    for ts, bar in sub.iterrows():
        if float(bar["low"]) < level:
            return ts, min(float(bar["open"]), level)
    return None


def exit_short(g, entry_ts, stop, target, exit_time):
    fwd = g[(g.index > entry_ts) & (g.index.time <= parse_time(exit_time))]
    if fwd.empty:
        return None
    ex, reason, xt = float(fwd.iloc[-1]["close"]), "time", fwd.index[-1]
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


def pass_filter(rule, inst, c, peers):
    if rule.filt == "mnq_weakest":
        rets = {name: ctx["ret_1030_from_prev_close"] for name, ctx in peers}
        return inst == "MNQ" and rets.get("MNQ", 0.0) <= min(rets.values()) + 1e-12
    avg_gap = float(np.mean([x["gap"] for x in peers]))
    avg_ext = float(np.mean([x["ret_1030_from_prev_close"] for x in peers]))
    if rule.filt == "base":
        return True
    if rule.filt == "not_deep_gap":
        return avg_gap > -0.012
    if rule.filt == "not_extended_1030":
        return avg_ext > -0.018
    if rule.filt == "not_deep_or_extended":
        return avg_gap > -0.012 and avg_ext > -0.018
    if rule.filt == "d1_not_crash":
        return float(np.mean([x["d1_ret"] for x in peers])) > -0.018
    if rule.filt == "d1_weak_not_extreme":
        avg_d1 = float(np.mean([x["d1_ret"] for x in peers]))
        avg_loc = float(np.mean([x["d1_close_loc"] for x in peers]))
        avg_rng = float(np.mean([x["d1_range_pct"] for x in peers]))
        return -0.018 < avg_d1 < -0.002 and avg_loc < 0.35 and avg_rng < 0.035
    if rule.filt == "open_in_prior_range":
        return all(-0.05 <= x["open_loc_prev_range"] <= 1.05 for x in peers)
    raise ValueError(rule.filt)


def build_rule(frames, prev, costs, rule):
    ctxs = {}
    for key, g in frames.items():
        c = context(g, prev.get(key), rule.setup_time)
        if c is not None:
            ctxs[key] = c
    active = []
    for day in sorted({d for d, _ in ctxs}):
        peers = [ctxs[(day, inst)] for inst in BASKET if (day, inst) in ctxs]
        if len(peers) == 4 and sum(x["gap"] <= rule.min_gapdown for x in peers) >= 3 and sum(x["below"] for x in peers) == 4:
            active.append(day)
    cid = clusters(active)
    rows = []
    for day in active:
        peer_pairs = [(inst, ctxs[(day, inst)]) for inst in BASKET if (day, inst) in ctxs]
        peer_ctxs = [x[1] for x in peer_pairs]
        for inst in rule.instruments:
            c, g = ctxs.get((day, inst)), frames.get((day, inst))
            if c is None or g is None or not c["below"]:
                continue
            if not pass_filter(rule, inst, c, peer_pairs if rule.filt == "mnq_weakest" else peer_ctxs):
                continue
            found = first_break(g, c["pre_low"], rule.entry_start, rule.entry_end)
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
                "variant": rule.name, "instrument": inst, "day": day,
                "entry_time": entry_ts, "known_time": c["known_time"], "exit_time": exit_ts,
                "pnl": pnl, "exit_reason": reason, "event_cluster": cid[day],
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


def boot(trades):
    if trades.empty:
        return dict(p_pos=0.0, p5=0.0)
    vals = trades.groupby("event_cluster")["pnl"].sum().to_numpy(float)
    rng = np.random.default_rng(51)
    sims = np.array([rng.choice(vals, len(vals), replace=True).sum() for _ in range(1000)])
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
    frames, prev = frames_prev_stats(dfs)
    rows = []
    for rule in RULES:
        tr = build_rule(frames, prev, costs, rule)
        s, s2, s3, b = summarize(tr, sessions), summarize(tr, sessions, 2.0), summarize(tr, sessions, 3.0), boot(tr)
        rows.append({
            "name": rule.name, "trades": s["trades"], "days": s["days"], "clusters": s["clusters"],
            "net": fmt_money(s["net"]), "pf": fmt_pf(s["pf"]), "calmar": f"{s['calmar']:.2f}",
            "maxdd": fmt_money(s["maxdd"]), "sig_after": s["sig"], "same_bar": s["same"],
            "slip2x": fmt_money(s2["net"]), "slip3x": fmt_money(s3["net"]),
            "boot_p_pos": f"{b['p_pos']:.2f}", "boot_p5": fmt_money(b["p5"]),
        })
    rows.sort(key=lambda x: float(x["net"].replace("$", "").replace(",", "")), reverse=True)
    print(which, rows[:3])
    return "\n".join([f"## {which}", "", table(rows, ["name", "trades", "days", "clusters", "net", "pf", "calmar", "maxdd", "sig_after", "same_bar", "slip2x", "slip3x", "boot_p_pos", "boot_p5"])])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--rules", nargs="*", default=None)
    ap.add_argument("--report", default="scratch/stress_gapshock_exhaustion_20260821_report.md")
    args = ap.parse_args()
    global RULES
    if args.rules:
        wanted = set(args.rules)
        RULES = [r for r in RULES if r.name in wanted]
    parts = [
        "# Stress Gap-Shock Exhaustion / D-1 Filters - 2026-08-21",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Tests controlled filters on strict gap-shock: deep-gap, 10:30 extension, D-1 crash/weak-close, open location, and MNQ leadership.",
        "",
    ]
    for which in args.which:
        parts.append(run(which))
        parts.append("")
    Path(args.report).write_text("\n".join(parts), encoding="utf-8")
    print(args.report)


if __name__ == "__main__":
    main()
