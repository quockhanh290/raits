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


SETUPS = ("10:30", "11:30", "13:00")
INSTRUMENT_SETS = {
    "mnq": ("MNQ",),
    "mnqmes": ("MNQ", "MES"),
}


@dataclass(frozen=True)
class Rule:
    name: str
    family: str
    direction: str
    instruments: tuple[str, ...]
    setup_time: str
    entry_start: str
    entry_end: str
    exit_time: str
    rr: float
    breadth_min: int
    gapdown_min: int = 0
    wide_min: int = 0
    avg_ret_max: float | None = None
    avg_gap_max: float | None = None
    max_stop_pct: float = 0.02
    stop_pad: float = 0.001


def arg_from(argv: list[str], flag: str, default=None):
    if flag not in argv:
        return default
    return argv[argv.index(flag) + 1]


def parse_time(hhmm: str):
    return pd.Timestamp(hhmm).time()


def add_minutes(hhmm: str, minutes: int) -> str:
    return (pd.Timestamp(hhmm) + pd.Timedelta(minutes=minutes)).strftime("%H:%M")


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


def build_day_cache(dfs: dict[str, pd.DataFrame]):
    frames: dict[tuple[pd.Timestamp, str], pd.DataFrame] = {}
    prev_close: dict[tuple[pd.Timestamp, str], float | None] = {}
    ctx: dict[tuple[pd.Timestamp, str, str], dict] = {}
    for inst, df in dfs.items():
        last_close = None
        for day_ts, g in df.groupby(df.index.normalize()):
            day = pd.Timestamp(day_ts).tz_localize(None).normalize()
            rth = g.between_time("09:30", "16:00")
            if rth.empty:
                continue
            frames[(day, inst)] = g
            prev_close[(day, inst)] = last_close
            bars5 = resample_5m(g).between_time("09:30", "15:55")
            day_open = float(rth.iloc[0]["open"])
            for setup_time in SETUPS:
                pre = bars5[bars5.index.time <= parse_time(setup_time)]
                sig = bars5[bars5.index.time == parse_time(setup_time)]
                if len(pre) < 3 or sig.empty:
                    continue
                sig_close = float(sig.iloc[-1]["close"])
                vw = vwap(pre)
                hi = float(pre["high"].max())
                lo = float(pre["low"].min())
                gap = day_open / last_close - 1.0 if last_close else np.nan
                start = add_minutes(setup_time, 5)
                end = "12:30" if setup_time <= "10:30" else ("14:30" if setup_time <= "13:00" else "15:30")
                low_break = first_low_break(g, lo, start, end)
                vwap_reject = first_retest_reject(g, vw, lo, start, end)
                reclaim = first_reclaim_hold(g, vw, hi, start, end)
                ctx[(day, inst, setup_time)] = {
                    "signal_time": sig.index[-1],
                    "known_time": sig.index[-1] + pd.Timedelta(minutes=5),
                    "open": day_open,
                    "signal_close": sig_close,
                    "vwap": vw,
                    "pre_high": hi,
                    "pre_low": lo,
                    "range_pct": (hi - lo) / day_open if day_open else 0.0,
                    "ret_from_open": sig_close / day_open - 1.0 if day_open else 0.0,
                    "gap": gap,
                    "below": sig_close < day_open and sig_close < vw,
                    "above": sig_close > day_open and sig_close > vw,
                    "gapdown": bool(np.isfinite(gap) and gap <= -0.004),
                    "deep_gapdown": bool(np.isfinite(gap) and gap <= -0.008),
                    "wide": (hi - lo) / day_open >= 0.008 if day_open else False,
                    "low_break": low_break,
                    "vwap_reject": vwap_reject,
                    "reclaim": reclaim,
                }
            last_close = float(rth.iloc[-1]["close"])
    return frames, ctx


def peer_features(ctxs: list[dict]) -> dict:
    gaps = [c["gap"] for c in ctxs if np.isfinite(c["gap"])]
    return {
        "below_count": sum(1 for c in ctxs if c["below"]),
        "above_count": sum(1 for c in ctxs if c["above"]),
        "gapdown_count": sum(1 for c in ctxs if c["gapdown"]),
        "deep_gapdown_count": sum(1 for c in ctxs if c["deep_gapdown"]),
        "wide_count": sum(1 for c in ctxs if c["wide"]),
        "avg_ret": float(np.mean([c["ret_from_open"] for c in ctxs])),
        "avg_gap": float(np.mean(gaps)) if gaps else 0.0,
        "avg_range": float(np.mean([c["range_pct"] for c in ctxs])),
    }


def first_low_break(g: pd.DataFrame, level: float, start: str, end: str):
    sub = g[(g.index.time >= parse_time(start)) & (g.index.time <= parse_time(end))]
    hit = sub[sub["low"] < level]
    if hit.empty:
        return None
    ts = hit.index[0]
    return ts, min(float(hit.iloc[0]["open"]), level)


def first_high_break(g: pd.DataFrame, level: float, start: str, end: str):
    sub = g[(g.index.time >= parse_time(start)) & (g.index.time <= parse_time(end))]
    hit = sub[sub["high"] > level]
    if hit.empty:
        return None
    ts = hit.index[0]
    return ts, max(float(hit.iloc[0]["open"]), level)


def first_retest_reject(g: pd.DataFrame, vwap_level: float, low_level: float, start: str, end: str):
    sub = g[(g.index.time >= parse_time(start)) & (g.index.time <= parse_time(end))]
    if sub.empty:
        return None
    touched = (sub["high"] >= vwap_level).cummax()
    hit = sub[touched & (sub["low"] < low_level)]
    if hit.empty:
        return None
    ts = hit.index[0]
    return ts, min(float(hit.iloc[0]["open"]), low_level)


def first_reclaim_hold(g: pd.DataFrame, vwap_level: float, high_level: float, start: str, end: str):
    sub = g[(g.index.time >= parse_time(start)) & (g.index.time <= parse_time(end))]
    if sub.empty:
        return None
    reclaimed = (sub["high"] > vwap_level).cummax()
    hit = sub[reclaimed & (sub["high"] > high_level)]
    if hit.empty:
        return None
    ts = hit.index[0]
    return ts, max(float(hit.iloc[0]["open"]), high_level)


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


def cluster_ids(days: list[pd.Timestamp]) -> dict[pd.Timestamp, str]:
    out = {}
    last = None
    cluster = 0
    for d in sorted(set(pd.Timestamp(x).normalize() for x in days)):
        if last is None or (d - last).days > 3:
            cluster += 1
        out[d] = f"E{cluster:03d}"
        last = d
    return out


def generate_rules() -> list[Rule]:
    rules: list[Rule] = []
    for setup in SETUPS:
        start = add_minutes(setup, 5)
        end = "12:30" if setup <= "10:30" else ("14:30" if setup <= "13:00" else "15:30")
        for inst_name, insts in INSTRUMENT_SETS.items():
            for rr in (2.0,):
                for exit_time in ("15:55",):
                    for breadth in (3, 4):
                        rules.append(Rule(
                            f"cont_short_{setup}_b{breadth}_{inst_name}_rr{str(rr).replace('.', '')}_x{exit_time.replace(':', '')}",
                            "cont_short", "SHORT", insts, setup, start, end, exit_time, rr,
                            breadth_min=breadth, gapdown_min=0, wide_min=0, avg_ret_max=-0.002,
                        ))
                        rules.append(Rule(
                            f"gap_cont_short_{setup}_b{breadth}_{inst_name}_rr{str(rr).replace('.', '')}_x{exit_time.replace(':', '')}",
                            "cont_short", "SHORT", insts, setup, start, end, exit_time, rr,
                            breadth_min=breadth, gapdown_min=2, wide_min=0, avg_ret_max=None, avg_gap_max=-0.002,
                        ))
                    rules.append(Rule(
                        f"vwap_reject_{setup}_b3_{inst_name}_rr{str(rr).replace('.', '')}_x{exit_time.replace(':', '')}",
                        "vwap_reject", "SHORT", insts, setup, start, end, exit_time, rr,
                        breadth_min=3, gapdown_min=0, wide_min=1, avg_ret_max=-0.001,
                    ))
                    rules.append(Rule(
                        f"reclaim_long_{setup}_b3_{inst_name}_rr{str(rr).replace('.', '')}_x{exit_time.replace(':', '')}",
                        "reclaim_long", "LONG", insts, setup, start, end, exit_time, rr,
                        breadth_min=3, gapdown_min=0, wide_min=0, avg_ret_max=-0.002,
                    ))
    return rules


def active_days(frames: dict, ctx: dict, rule: Rule) -> tuple[list[pd.Timestamp], dict[pd.Timestamp, dict]]:
    days = sorted({d for d, _, setup in ctx if setup == rule.setup_time})
    out = []
    feats = {}
    for day in days:
        peers = [ctx[(day, inst, rule.setup_time)] for inst in BASKET if (day, inst, rule.setup_time) in ctx]
        if len(peers) < 4:
            continue
        f = peer_features(peers)
        if f["below_count"] < rule.breadth_min:
            continue
        if f["gapdown_count"] < rule.gapdown_min:
            continue
        if f["wide_count"] < rule.wide_min:
            continue
        if rule.avg_ret_max is not None and f["avg_ret"] > rule.avg_ret_max:
            continue
        if rule.avg_gap_max is not None and f["avg_gap"] > rule.avg_gap_max:
            continue
        out.append(day)
        feats[day] = f
    return out, feats


def build_rule(frames: dict, ctx: dict, costs: dict, rule: Rule) -> pd.DataFrame:
    days, feats = active_days(frames, ctx, rule)
    clusters = cluster_ids(days)
    rows = []
    for day in days:
        feat = feats[day]
        for inst in rule.instruments:
            c = ctx.get((day, inst, rule.setup_time))
            g = frames.get((day, inst))
            if c is None or g is None or not c["below"]:
                continue
            if rule.family == "vwap_reject":
                found = c["vwap_reject"]
            elif rule.family == "reclaim_long":
                found = c["reclaim"]
            else:
                found = c["low_break"]
            if found is None:
                continue
            entry_ts, entry = found
            if rule.direction == "SHORT":
                stop = c["pre_high"] * (1.0 + rule.stop_pad)
                dist = stop - entry
                target = entry - rule.rr * dist
            else:
                stop = c["pre_low"] * (1.0 - rule.stop_pad)
                dist = entry - stop
                target = entry + rule.rr * dist
            if dist <= 0 or dist / entry > rule.max_stop_pct:
                continue
            exited = exit_trade(g, rule.direction, entry_ts, stop, target, rule.exit_time)
            if exited is None:
                continue
            exit_px, reason, exit_ts = exited
            gross = (entry - exit_px) if rule.direction == "SHORT" else (exit_px - entry)
            pnl = gross * BASKET[inst].point_value - costs[inst].round_turn_cost()
            rows.append({
                "variant": rule.name,
                "family": rule.family,
                "instrument": inst,
                "direction": rule.direction,
                "day": day,
                "entry_time": entry_ts,
                "signal_time": c["signal_time"],
                "known_time": c["known_time"],
                "exit_time": exit_ts,
                "pnl": pnl,
                "exit_reason": reason,
                "event_cluster": clusters[day],
                "below_count": feat["below_count"],
                "gapdown_count": feat["gapdown_count"],
                "wide_count": feat["wide_count"],
                "avg_ret": feat["avg_ret"],
                "avg_gap": feat["avg_gap"],
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


def bootstrap_events(trades: pd.DataFrame, n: int = 1000, seed: int = 37) -> dict:
    if trades.empty:
        return {"p_pos": 0.0, "p5": 0.0, "best_share": 0.0}
    vals = trades.groupby("event_cluster")["pnl"].sum().to_numpy(float)
    rng = np.random.default_rng(seed)
    sims = np.array([rng.choice(vals, size=len(vals), replace=True).sum() for _ in range(n)])
    total = float(vals.sum())
    best = float(vals.max()) if len(vals) else 0.0
    return {
        "p_pos": float((sims > 0).mean()),
        "p5": float(np.percentile(sims, 5)),
        "best_share": best / total if total > 0 else math.inf,
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


def measure_window(which: str, rules: list[Rule]):
    dfs, costs, sessions = load_window(which)
    frames, ctx = build_day_cache(dfs)
    cands = {}
    rows = []
    for i, rule in enumerate(rules, 1):
        df = build_rule(frames, ctx, costs, rule)
        cands[rule.name] = df
        s = summarize(df, sessions)
        s3 = summarize(df, sessions, 3.0)
        b = bootstrap_events(df)
        rows.append({
            "name": rule.name,
            "family": rule.family,
            "dir": rule.direction,
            "inst": "/".join(rule.instruments),
            "trades": s["trades"],
            "days": s["days"],
            "clusters": s["clusters"],
            "net_raw": s["net"],
            "pf_raw": s["pf"],
            "calmar_raw": s["calmar"],
            "maxdd_raw": s["maxdd"],
            "slip3_raw": s3["net"],
            "boot_p5_raw": b["p5"],
            "best_share_raw": b["best_share"],
            "sig": s["sig"],
            "same": s["same"],
            "net": fmt_money(s["net"]),
            "pf": fmt_pf(s["pf"]),
            "calmar": f"{s['calmar']:.2f}",
            "maxdd": fmt_money(s["maxdd"]),
            "slip3": fmt_money(s3["net"]),
            "boot_p5": fmt_money(b["p5"]),
            "best_share": "inf" if math.isinf(b["best_share"]) else f"{b['best_share']:.2f}",
        })
    return rows, cands, sessions


def score_row(row: dict, oos25: dict | None, oos26: dict | None) -> float:
    if row["trades"] < 20 or row["net_raw"] <= 0 or row["pf_raw"] < 1.15 or row["sig"] or row["same"]:
        return -1e9
    score = row["net_raw"] + 500.0 * (row["pf_raw"] - 1.0) - row["maxdd_raw"] * 0.25
    if row["slip3_raw"] <= 0:
        score -= 3000
    if row["boot_p5_raw"] < 0:
        score += row["boot_p5_raw"] * 0.5
    if row["best_share_raw"] > 0.5:
        score -= 1500 * min(row["best_share_raw"], 3.0)
    for oos in (oos25, oos26):
        if not oos or oos["trades"] == 0:
            score -= 1000
        elif oos["net_raw"] < 0:
            score += 2.0 * oos["net_raw"] - 1000
        else:
            score += min(oos["net_raw"], 2000)
    return score


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="scratch/stress_open_search_20260821_report.md")
    args = ap.parse_args()

    rules = generate_rules()
    floor_rows, floor_cands, _ = measure_window("floor", rules)
    prelim = sorted(
        [
            r for r in floor_rows
            if r["trades"] >= 15 and r["net_raw"] > 0 and r["pf_raw"] >= 1.10 and not r["sig"] and not r["same"]
        ],
        key=lambda r: (
            r["net_raw"]
            + 500.0 * (r["pf_raw"] - 1.0)
            - 0.25 * r["maxdd_raw"]
            + min(r["boot_p5_raw"], 0.0) * 0.25
        ),
        reverse=True,
    )[:30]
    shortlist_names = {r["name"] for r in prelim}
    shortlist_rules = [r for r in rules if r.name in shortlist_names]
    rows25, _, _ = measure_window("vault2025", shortlist_rules)
    rows26, _, _ = measure_window("vault2026", shortlist_rules)
    by25 = {r["name"]: r for r in rows25}
    by26 = {r["name"]: r for r in rows26}
    for r in floor_rows:
        r["score"] = score_row(r, by25.get(r["name"]), by26.get(r["name"]))
        r["oos25"] = by25.get(r["name"], {}).get("net", "")
        r["oos25_trades"] = by25.get(r["name"], {}).get("trades", "")
        r["oos26"] = by26.get(r["name"], {}).get("net", "")
        r["oos26_trades"] = by26.get(r["name"], {}).get("trades", "")
    ranked = sorted(floor_rows, key=lambda r: r["score"], reverse=True)
    viable = [r for r in ranked if r["score"] > -1e8]
    top = viable[:20]

    lines = [
        "# Stress Open Search - 2026-08-21",
        "",
        "Scratch-only broad candidate excavation. No production code modified.",
        "",
        "Search rules:",
        "",
        "- no same-day daily Stress regime label;",
        "- every setup bar is treated as known only five minutes after its timestamp;",
        "- families include continuation shorts, gap-continuation shorts, VWAP-reject shorts, and reclaim longs;",
        "- instruments are searched as `MNQ`, `MES`, and `MNQ/MES` fixed variants;",
        "- ranking penalizes single-cluster concentration, negative 3x slippage, negative OOS, zero OOS trades, and fill/timing failures.",
        "",
        f"Rules searched: {len(rules)}",
        "",
        "## Top Robustness-Ranked Floor Candidates With OOS",
        "",
    ]
    lines.append(table(top, ["name", "family", "dir", "inst", "trades", "days", "clusters", "net", "pf", "calmar", "maxdd", "slip3", "boot_p5", "best_share", "oos25", "oos25_trades", "oos26", "oos26_trades"]))
    lines += ["", "## Top Floor Net Candidates", ""]
    floor_net = sorted(floor_rows, key=lambda r: r["net_raw"], reverse=True)[:20]
    lines.append(table(floor_net, ["name", "family", "dir", "inst", "trades", "days", "clusters", "net", "pf", "calmar", "maxdd", "slip3", "boot_p5", "best_share", "oos25", "oos25_trades", "oos26", "oos26_trades"]))

    if top:
        best = top[0]["name"]
        df = floor_cands[best]
        lines += ["", f"## Best Candidate Autopsy: `{best}`", ""]
        lines.append(df.assign(year=pd.to_datetime(df["day"]).dt.year).groupby("year").agg(
            trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")
        ).to_string())
        lines += ["", "By instrument:", ""]
        lines.append(df.groupby("instrument").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
        lines += ["", "By exit reason:", ""]
        lines.append(df.groupby("exit_reason").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
        lines += ["", "Interpretation:", ""]
        lines.append("- This is a discovery table, not a promotion table. The selected candidate must be rerun in a narrower follow-up with event-WFO and overlap/insurance scoring.")
        lines.append("- If the top row is LONG, it is a Stress-regime/reversal strategy rather than a crash hedge; do not compare it directly with short hedge sleeves.")
    else:
        lines += ["", "No candidate passed the coarse viability score."]

    Path(args.report).write_text("\n".join(lines), encoding="utf-8")
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
