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

from futures._validated_core import benchmark_daily, label_regimes, load_parquet, resample_5m
from futures.basket import BASKET, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from global_index.deploy_sim import metrics
from scratch.harness import ARGV
from scratch.stress_sleeve_validation import daily_from_trades, split_table


ACCOUNT = 50_000.0


@dataclass(frozen=True)
class Rule:
    name: str
    instruments: tuple[str, ...] = ("MNQ", "MES")
    below_min: int = 4
    wide_min: int = 0
    rr: float = 2.0
    end_time: str = "15:55"
    max_stop_pct: float = 0.015
    stop_pad: float = 0.001


RULES = [
    Rule("causal1015_b4_rr2_x1555"),
    Rule("causal1015_b4_wide3_rr2_x1555", wide_min=3),
    Rule("causal1015_b4_rr15_x1400", rr=1.5, end_time="14:00"),
    Rule("causal1015_b4_mnq_rr2_x1555", instruments=("MNQ",)),
    Rule("causal1015_b3_rr2_x1555", below_min=3),
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


def context(day_1m: pd.DataFrame) -> dict | None:
    bars5 = resample_5m(day_1m).between_time("09:30", "15:55")
    sig = bars5[bars5.index.time == parse_time("10:15")]
    entry = first_at_or_after(day_1m, "10:20")
    rth = day_1m.between_time("09:30", "16:00")
    if len(bars5) < 12 or sig.empty or entry is None or rth.empty:
        return None
    pre = bars5[bars5.index.time <= parse_time("10:15")]
    if len(pre) < 4:
        return None
    open_px = float(rth.iloc[0]["open"])
    sig_close = float(sig.iloc[-1]["close"])
    return {
        "signal_time": sig.index[-1],
        "known_time": sig.index[-1] + pd.Timedelta(minutes=5),
        "entry_time": entry[0],
        "entry": entry[1],
        "signal_close": sig_close,
        "open": open_px,
        "vwap": vwap(pre),
        "pre_high": float(pre["high"].max()),
        "pre_low": float(pre["low"].min()),
        "range_pct": float(pre["high"].max() - pre["low"].min()) / open_px if open_px else 0.0,
        "ret_from_open": sig_close / open_px - 1.0 if open_px else 0.0,
    }


def peer_features(ctxs: list[dict]) -> dict:
    return {
        "below_count": sum(1 for c in ctxs if c["signal_close"] < c["vwap"] and c["signal_close"] < c["open"]),
        "wide_count": sum(1 for c in ctxs if c["range_pct"] >= 0.0075),
        "avg_range_pct": float(np.mean([c["range_pct"] for c in ctxs])) if ctxs else 0.0,
        "avg_ret_from_open": float(np.mean([c["ret_from_open"] for c in ctxs])) if ctxs else 0.0,
    }


def classify_event(feat: dict) -> str:
    if feat["below_count"] >= 4 and feat["wide_count"] >= 3:
        return "broad-liquidation"
    if feat["below_count"] >= 4:
        return "full-breadth-selloff"
    if feat["below_count"] >= 3 and feat["avg_ret_from_open"] <= -0.003:
        return "opening-selloff"
    if feat["wide_count"] >= 3:
        return "wide-chop"
    return "weak"


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
    dfs = {n: clip(load_parquet(str(Path(data_dir) / data_filename(c))), start, end) for n, c in BASKET.items()}
    sessions = pd.DatetimeIndex(sorted({
        pd.Timestamp(x).tz_localize(None).normalize()
        for x in dfs["MES"].index.normalize().unique()
    }))
    return argv, dfs, costs, sessions


def build_rules(dfs: dict[str, pd.DataFrame], costs: dict) -> dict[str, pd.DataFrame]:
    frames = {}
    ctxs = {}
    for inst, df in dfs.items():
        for day_ts, g in df.groupby(df.index.normalize()):
            day = pd.Timestamp(day_ts).tz_localize(None).normalize()
            ctx = context(g)
            if ctx is None:
                continue
            frames[(day, inst)] = g
            ctxs[(day, inst)] = ctx

    out = {r.name: [] for r in RULES}
    for rule in RULES:
        active = []
        feats = {}
        for day in sorted({d for d, _ in ctxs}):
            peers = [ctxs[(day, inst)] for inst in BASKET if (day, inst) in ctxs]
            if len(peers) < 4:
                continue
            feat = peer_features(peers)
            if feat["below_count"] < rule.below_min or feat["wide_count"] < rule.wide_min:
                continue
            active.append(day)
            feats[day] = feat
        clusters = event_cluster_ids(active)
        for day in active:
            feat = feats[day]
            for inst in rule.instruments:
                ctx = ctxs.get((day, inst))
                g = frames.get((day, inst))
                if ctx is None or g is None:
                    continue
                if ctx["signal_close"] >= ctx["vwap"] or ctx["signal_close"] >= ctx["open"]:
                    continue
                entry_ts = ctx["entry_time"]
                entry = float(ctx["entry"])
                stop = float(ctx["pre_high"]) * (1.0 + rule.stop_pad)
                stop_dist = stop - entry
                if stop_dist <= 0 or stop_dist / entry > rule.max_stop_pct:
                    continue
                target = entry - rule.rr * stop_dist
                fwd = g[(g.index > entry_ts) & (g.index.time <= parse_time(rule.end_time))]
                if fwd.empty:
                    continue
                exit_px, reason, exit_ts = exit_short(fwd, stop, target, rule.end_time)
                pnl = (entry - exit_px) * BASKET[inst].point_value - costs[inst].round_turn_cost()
                out[rule.name].append({
                    "variant": rule.name,
                    "inst": inst,
                    "day": day,
                    "year": day.year,
                    "direction": "SHORT",
                    "signal_time": ctx["signal_time"],
                    "known_time": ctx["known_time"],
                    "entry_time": entry_ts,
                    "exit_time": exit_ts,
                    "entry": entry,
                    "exit": exit_px,
                    "stop": stop,
                    "target": target,
                    "stop_dist_pct": stop_dist / entry,
                    "points": entry - exit_px,
                    "pnl": pnl,
                    "exit_reason": reason,
                    "event_cluster": clusters[day],
                    "event_subtype": classify_event(feat),
                    **feat,
                })
    return {
        k: pd.DataFrame(v).sort_values(["day", "inst"]).reset_index(drop=True)
        if v else pd.DataFrame(columns=["variant", "inst", "day", "pnl", "event_cluster", "event_subtype", "entry_time", "known_time", "exit_time"])
        for k, v in out.items()
    }


def pf(tr: pd.DataFrame) -> float:
    if tr.empty:
        return math.inf
    wins = float(tr.loc[tr["pnl"] > 0, "pnl"].sum())
    losses = float(-tr.loc[tr["pnl"] < 0, "pnl"].sum())
    return wins / losses if losses else math.inf


def dense_daily(tr: pd.DataFrame, sessions: pd.DatetimeIndex, extra_cost: float = 0.0) -> pd.Series:
    if tr.empty:
        return pd.Series(0.0, index=sessions)
    work = tr.copy()
    work["pnl"] = work["pnl"].astype(float) - extra_cost
    sparse = daily_from_trades(work)
    use = sessions[(sessions >= sparse.index.min()) & (sessions <= sparse.index.max())]
    dense = pd.Series(0.0, index=use)
    dense.loc[sparse.index] = sparse.values
    return dense


def extra_tick_cost(tr: pd.DataFrame) -> float:
    if tr.empty:
        return 0.0
    return float(tr["inst"].map(lambda i: BASKET[str(i)].tick_value * 2.0).mean())


def summary(name: str, tr: pd.DataFrame, sessions: pd.DatetimeIndex, extra_cost: float = 0.0) -> dict:
    if tr.empty:
        return {"name": name, "trades": 0, "days": 0, "clusters": 0, "net": 0.0, "pf": math.inf, "sharpe": 0.0, "calmar": math.inf, "maxdd": 0.0}
    work = tr.copy()
    work["pnl"] = work["pnl"].astype(float) - extra_cost
    m = metrics(dense_daily(work, sessions))
    return {
        "name": name,
        "trades": int(len(work)),
        "days": int(work["day"].nunique()),
        "clusters": int(work["event_cluster"].nunique()),
        "net": float(work["pnl"].sum()),
        "pf": pf(work),
        "sharpe": float(m["sharpe"]),
        "calmar": float(m["calmar"]),
        "maxdd": float(m["maxdd"]),
        "target_rate": float((work["exit_reason"] == "target").mean()),
        "stop_rate": float((work["exit_reason"] == "stop").mean()),
        "signal_after_entry": int((work["known_time"] > work["entry_time"]).sum()),
        "same_bar_exit": int((work["exit_time"] <= work["entry_time"]).sum()),
        "slip2x_net": float((work["pnl"] - extra_tick_cost(work)).sum()),
        "slip3x_net": float((work["pnl"] - 2.0 * extra_tick_cost(work)).sum()),
    }


def load_swing_positions(which: str, dfs: dict[str, pd.DataFrame], costs: dict) -> list[dict]:
    argv = list(ARGV[which])
    labels = label_regimes(
        benchmark_daily(arg_from(argv, "--regime-csv", "spy_daily_live.csv")),
        "2018-01-01",
        3,
        arg_from(argv, "--hmm-fit-end", "2024-12-31"),
    )
    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)
    return [
        {
            "inst": inst,
            "d0": pd.Timestamp(t["day"]).normalize(),
            "d1": pd.Timestamp(t["exit_day"]).normalize(),
            "dir": t["direction"],
        }
        for inst, trades in swing.items()
        for t in trades
    ]


def overlap(open_positions: list[dict], tr: pd.DataFrame) -> dict:
    held = opposite = 0
    gross = net = 0.0
    days = set()
    for _, r in tr.iterrows():
        day = pd.Timestamp(r["day"]).normalize()
        matches = [p for p in open_positions if p["inst"] == r["inst"] and p["d0"] < day <= p["d1"]]
        if not matches:
            continue
        held += 1
        if any(p["dir"] != r["direction"] for p in matches):
            opposite += 1
            pnl = float(r["pnl"])
            gross += abs(pnl)
            net += pnl
            days.add(day)
    return {"held": held, "opposite": opposite, "conflict_days": len(days), "opposite_net": net, "opposite_gross": gross}


def calm_overlap(which: str, tr: pd.DataFrame) -> dict:
    paths = {
        "floor": Path("scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_is.csv"),
        "vault2025": Path("scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_2025.csv"),
        "vault2026": Path("scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_2026.csv"),
    }
    p = paths.get(which)
    if p is None or not p.exists() or tr.empty:
        return {"held": 0, "opposite": 0, "conflict_days": 0, "opposite_net": 0.0, "opposite_gross": 0.0}
    calm = pd.read_csv(p)
    calm = calm[calm["variant"] == "on_neg_fade_mod001_010_x1555"].copy()
    calm["day"] = pd.to_datetime(calm["day"]).dt.normalize()
    keys = set(zip(calm["day"], calm["inst"]))
    held = opposite = 0
    gross = net = 0.0
    days = set()
    for _, r in tr.iterrows():
        key = (pd.Timestamp(r["day"]).normalize(), str(r["inst"]))
        if key not in keys:
            continue
        held += 1
        opposite += 1
        pnl = float(r["pnl"])
        gross += abs(pnl)
        net += pnl
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


def chronological_wfo(cands: dict[str, pd.DataFrame], min_prior: int = 8) -> pd.DataFrame:
    clusters = sorted({c for tr in cands.values() for c in tr.get("event_cluster", pd.Series(dtype=str)).dropna().unique() if c})
    rows = []
    for i, cluster in enumerate(clusters):
        prior = clusters[:i]
        if len(prior) < min_prior:
            continue
        scores = {name: float(tr[tr["event_cluster"].isin(prior)]["pnl"].sum()) if not tr.empty else -math.inf for name, tr in cands.items()}
        selected = max(scores, key=scores.get)
        test = cands[selected]
        test = test[test["event_cluster"] == cluster] if not test.empty else test
        rows.append({
            "test_cluster": cluster,
            "selected": selected,
            "event_subtype": str(test["event_subtype"].iloc[0]) if not test.empty else "no selected trade",
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
    share = best / total if total > 0 else math.inf
    final4 = float(nets.tail(4).sum())
    return {"total": total, "best": best, "without_best": without_best, "best_share": share, "final4": final4, "positive": int((nets > 0).sum()), "folds": int(len(nets)), "pass": bool(total > 0 and without_best > 0 and share <= 0.5 and final4 >= 0)}


def md_table(rows: list[dict], fields: list[str]) -> str:
    out = ["| " + " | ".join(fields) + " |", "| " + " | ".join("---" for _ in fields) + " |"]
    for r in rows:
        vals = []
        for f in fields:
            v = r.get(f, "")
            if isinstance(v, float):
                if f in {"net", "maxdd", "slip2x_net", "slip3x_net", "opposite_net", "opposite_gross", "p5", "p50", "p95", "total", "best", "without_best", "final4"}:
                    vals.append(f"${v:,.0f}")
                elif math.isinf(v):
                    vals.append("inf")
                else:
                    vals.append(f"{v:.2f}")
            else:
                vals.append(str(v))
        out.append("| " + " | ".join(vals) + " |")
    return "\n".join(out)


def run_window(which: str) -> dict:
    argv, dfs, costs, sessions = load_window(which)
    cands = build_rules(dfs, costs)
    sw = load_swing_positions(which, dfs, costs)
    rows = []
    details = []
    for name, tr in cands.items():
        s = summary(name, tr, sessions)
        s["swing"] = overlap(sw, tr)
        s["calm"] = calm_overlap(which, tr)
        s["bootstrap"] = bootstrap_event(tr)
        rows.append(s)
        details.append((name, tr))
    folds = chronological_wfo(cands)
    return {"which": which, "rows": rows, "details": details, "folds": folds, "gate": concentration_gate(folds)}


def report_window(r: dict) -> list[str]:
    rows = sorted(r["rows"], key=lambda x: (x["net"], x["pf"]), reverse=True)
    lines = [
        f"## {r['which']}",
        "",
        "Candidate table:",
        "",
        md_table(rows, ["name", "trades", "days", "clusters", "net", "pf", "sharpe", "calmar", "maxdd", "target_rate", "stop_rate", "signal_after_entry", "same_bar_exit", "slip2x_net", "slip3x_net"]),
        "",
        "Swing overlap:",
        "",
        md_table([{"name": x["name"], **x["swing"]} for x in rows], ["name", "held", "opposite", "conflict_days", "opposite_net", "opposite_gross"]),
        "",
        "Calm overlap:",
        "",
        md_table([{"name": x["name"], **x["calm"]} for x in rows], ["name", "held", "opposite", "conflict_days", "opposite_net", "opposite_gross"]),
        "",
        "Event bootstrap:",
        "",
        md_table([{"name": x["name"], **x["bootstrap"]} for x in rows], ["name", "events", "p_pos", "p5", "p50", "p95"]),
        "",
        "Chronological event WFO:",
        "",
        md_table(r["folds"].to_dict("records"), ["test_cluster", "selected", "event_subtype", "trades", "net", "pf"]) if not r["folds"].empty else "_insufficient folds_",
        "",
        "WFO concentration gate:",
        "",
        md_table([r["gate"]], ["total", "best", "without_best", "best_share", "final4", "positive", "folds", "pass"]),
        "",
    ]
    for name, tr in r["details"]:
        if tr.empty:
            continue
        lines += [
            f"By year/instrument/subtype for `{name}`:",
            "",
            split_table(tr, "year").reset_index().to_string(index=False),
            "",
            split_table(tr, "inst").reset_index().to_string(index=False),
            "",
            split_table(tr, "event_subtype").reset_index().to_string(index=False),
            "",
        ]
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--report", default="scratch/stress_intraday_1015_causal_pass_20260821_report.md")
    args = ap.parse_args()
    report = [
        "# Stress Intraday 10:15-Close Causal Pass - 2026-08-21",
        "",
        "Scope: scratch-only. No production code modified.",
        "",
        "Rules use the fully closed 5-minute bar stamped 10:15 and enter at the 10:20",
        "1-minute open. They do not use daily Stress labels.",
        "",
    ]
    for which in args.which:
        print(f"\n=== {which} ===", flush=True)
        r = run_window(which)
        for x in sorted(r["rows"], key=lambda y: (y["net"], y["pf"]), reverse=True):
            print(f"{x['name']:<34} n={x['trades']:>4} net={x['net']:>9,.0f} pf={x['pf']:.2f} cal={x['calmar']:.2f} sig_after={x['signal_after_entry']} swing_opp={x['swing']['opposite']}")
        print(f"WFO total={r['gate']['total']:,.0f} without_best={r['gate']['without_best']:,.0f} final4={r['gate']['final4']:,.0f} pass={r['gate']['pass']}")
        report += report_window(r)
    report += [
        "## Verdict",
        "",
        "Read the floor WFO gate plus OOS/slippage/overlap together. A standalone",
        "positive row is not enough for this branch.",
        "",
    ]
    Path(args.report).write_text("\n".join(report), encoding="utf-8")
    print(f"\nwrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
