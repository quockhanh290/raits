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

from futures._validated_core import benchmark_daily, daily_atr_series, label_regimes, load_parquet, resample_5m
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket
from global_index.deploy_sim import metrics
from scratch.harness import ARGV


@dataclass(frozen=True)
class Variant:
    name: str
    family: str = "confirmed_1020"
    breadth: str = "breadth3"
    instruments: tuple[str, ...] = ("MNQ", "MES")
    rr: float = 2.0
    entry_time: str = "10:20"
    end_time: str = "14:00"
    stop_pad: float = 0.001
    max_stop_pct: float = 0.015
    range_threshold_pct: float = 0.0075
    partial_r: float | None = None
    runner_rr: float | None = None


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


def atr_asof(atr: pd.Series, day) -> float:
    val = atr.asof(pd.Timestamp(day))
    if val is None or pd.isna(val):
        val = float(atr.median())
    return float(val)


def parse_time(hhmm: str) -> dtime:
    return pd.Timestamp(hhmm).time()


def vwap(bars: pd.DataFrame) -> float:
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    vol = bars["volume"]
    return float((tp * vol).sum() / vol.sum()) if float(vol.sum()) > 0 else float(bars["close"].iloc[-1])


def first_at_or_after(g: pd.DataFrame, hhmm: str, col: str = "open") -> tuple[pd.Timestamp, float] | None:
    sub = g[g.index.time >= parse_time(hhmm)]
    if sub.empty:
        return None
    return sub.index[0], float(sub.iloc[0][col])


def context(day_1m: pd.DataFrame, entry_time: str) -> dict | None:
    bars5 = resample_5m(day_1m).between_time("09:30", "14:00")
    signal_bar = bars5[bars5.index.time == dtime(10, 15)]
    entry_bar = first_at_or_after(day_1m, entry_time, "open")
    if len(bars5) < 10 or signal_bar.empty or entry_bar is None:
        return None
    pre = bars5[bars5.index.time <= dtime(10, 15)]
    swing = bars5[(bars5.index.time >= dtime(9, 45)) & (bars5.index.time <= dtime(10, 15))]
    open_px = float(bars5.iloc[0]["open"])
    morning_range = float(pre["high"].max() - pre["low"].min())
    entry_ts, entry_px = entry_bar
    rth = day_1m.between_time("09:30", "16:00")
    prior = day_1m[day_1m.index < rth.index[0]] if not rth.empty else pd.DataFrame()
    gap = 0.0
    if not prior.empty and not rth.empty:
        prior_close = float(prior.iloc[-1]["close"])
        gap = (float(rth.iloc[0]["open"]) - prior_close) / prior_close if prior_close else 0.0
    return {
        "entry": entry_px,
        "entry_time": entry_ts,
        "signal_time": signal_bar.index[-1],
        "signal_close": float(signal_bar.iloc[-1]["close"]),
        "open": open_px,
        "vwap": vwap(pre),
        "swing_high": float(swing["high"].max()),
        "range_pct": morning_range / open_px if open_px else 0.0,
        "gap": gap,
    }


def exit_short(fwd: pd.DataFrame, stop: float, target: float, end_time: str) -> tuple[float, str, pd.Timestamp]:
    fwd = fwd[fwd.index.time <= parse_time(end_time)]
    if fwd.empty:
        raise ValueError("empty forward path")
    exit_px = float(fwd.iloc[-1]["close"])
    reason = "eod"
    exit_ts = fwd.index[-1]
    for ts, bar in fwd.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])
        open_px = float(bar["open"])
        if high >= stop:
            return (stop if low <= stop else open_px), "stop", ts
        if low <= target:
            return (target if high >= target else open_px), "target", ts
        exit_px = float(bar["close"])
        exit_ts = ts
    return exit_px, reason, exit_ts


def partial_runner_exit_short(
    fwd: pd.DataFrame,
    entry: float,
    stop: float,
    partial_target: float,
    runner_target: float,
    end_time: str,
) -> tuple[float, str, pd.Timestamp, float | None, pd.Timestamp | None, float]:
    fwd = fwd[fwd.index.time <= parse_time(end_time)]
    if fwd.empty:
        raise ValueError("empty forward path")
    partial_px = None
    partial_ts = None
    exit_px = float(fwd.iloc[-1]["close"])
    exit_ts = fwd.index[-1]
    reason = "eod"
    for ts, bar in fwd.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])
        open_px = float(bar["open"])
        if partial_px is None:
            if high >= stop:
                px = stop if low <= stop else open_px
                return px, "stop_pre_partial", ts, None, None, entry - px
            if low <= partial_target:
                partial_px = partial_target if high >= partial_target else open_px
                partial_ts = ts
                continue
        if partial_px is not None:
            if high >= entry:
                px = entry if low <= entry else open_px
                return px, "breakeven_after_partial", ts, partial_px, partial_ts, (
                    0.5 * (entry - partial_px) + 0.5 * (entry - px)
                )
            if low <= runner_target:
                px = runner_target if high >= runner_target else open_px
                return px, "runner_target", ts, partial_px, partial_ts, (
                    0.5 * (entry - partial_px) + 0.5 * (entry - px)
                )
        exit_px = float(bar["close"])
        exit_ts = ts
    if partial_px is None:
        points = entry - exit_px
    else:
        points = 0.5 * (entry - partial_px) + 0.5 * (entry - exit_px)
    return exit_px, reason, exit_ts, partial_px, partial_ts, points


def late_continuation_short(day_1m: pd.DataFrame, ctx: dict, variant: Variant) -> dict | None:
    if ctx["signal_close"] >= ctx["vwap"] or ctx["signal_close"] >= ctx["open"]:
        return None
    scan = day_1m[(day_1m.index.time >= dtime(11, 0)) & (day_1m.index.time <= dtime(12, 0))]
    if scan.empty:
        return None
    low_so_far = float(day_1m[day_1m.index.time <= dtime(10, 20)]["low"].min())
    for ts, bar in scan.iterrows():
        close = float(bar["close"])
        if close >= low_so_far:
            continue
        entry = close
        stop = max(ctx["vwap"], float(scan.loc[:ts, "high"].max())) * (1.0 + variant.stop_pad / 2.0)
        stop_dist = stop - entry
        if stop_dist <= 0 or stop_dist / entry > variant.max_stop_pct:
            return None
        target = entry - variant.rr * stop_dist
        fwd = day_1m[(day_1m.index > ts) & (day_1m.index.time <= parse_time(variant.end_time))]
        if fwd.empty:
            return None
        exit_px, reason, exit_ts = exit_short(fwd, stop, target, variant.end_time)
        return {
            "entry": entry,
            "entry_time": ts,
            "signal_time": ctx["signal_time"],
            "exit": exit_px,
            "exit_reason": reason,
            "exit_time": exit_ts,
            "stop": stop,
            "target": target,
            "points": entry - exit_px,
            "partial_exit": np.nan,
            "partial_time": None,
        }
    return None


def passes_breadth(variant: Variant, peer_contexts: list[dict]) -> bool:
    below_count = sum(
        1 for c in peer_contexts
        if c["signal_close"] < c["vwap"] and c["signal_close"] < c["open"]
    )
    if variant.breadth == "breadth3":
        return below_count >= 3
    if variant.breadth == "wide_range3":
        wide_count = sum(1 for c in peer_contexts if c["range_pct"] >= variant.range_threshold_pct)
        return below_count >= 3 and wide_count >= 3
    raise ValueError(f"unknown breadth {variant.breadth}")


def event_features(peer_contexts: list[dict]) -> dict:
    below_count = sum(
        1 for c in peer_contexts
        if c["signal_close"] < c["vwap"] and c["signal_close"] < c["open"]
    )
    wide_count = sum(1 for c in peer_contexts if c["range_pct"] >= 0.0075)
    avg_range = float(np.mean([c["range_pct"] for c in peer_contexts])) if peer_contexts else 0.0
    avg_sig_ret = float(np.mean([(c["signal_close"] / c["open"] - 1.0) for c in peer_contexts])) if peer_contexts else 0.0
    avg_gap = float(np.mean([c.get("gap", 0.0) for c in peer_contexts])) if peer_contexts else 0.0
    return {
        "below_count": below_count,
        "wide_count": wide_count,
        "avg_range_pct": avg_range,
        "avg_sig_ret": avg_sig_ret,
        "avg_gap": avg_gap,
    }


def classify_event(feat: dict) -> str:
    if feat["below_count"] >= 3 and (feat["wide_count"] >= 3 or feat["avg_gap"] <= -0.0025):
        return "crash-gap/liquidation"
    if feat["below_count"] >= 3 and feat["avg_sig_ret"] <= -0.0025:
        return "bear-trend continuation"
    if feat["wide_count"] >= 3 and feat["avg_sig_ret"] > -0.0025:
        return "high-range reversal"
    return "false stress / chop"


def event_cluster_ids(event_days: pd.DataFrame) -> dict[pd.Timestamp, str]:
    if event_days.empty:
        return {}
    out = {}
    last_day = None
    cluster_no = 0
    for day in event_days["day"].drop_duplicates().sort_values():
        day = pd.Timestamp(day).normalize()
        if last_day is None or (day - last_day).days > 3:
            cluster_no += 1
        out[day] = f"E{cluster_no:03d}"
        last_day = day
    return out


def build_event_day_table(contexts: dict[tuple[pd.Timestamp, str], dict]) -> pd.DataFrame:
    rows = []
    for day in sorted({d for d, _ in contexts}):
        peer_contexts = [contexts[(day, peer)] for peer in BASKET if (day, peer) in contexts]
        feat = event_features(peer_contexts)
        rows.append({"day": day, "event_subtype": classify_event(feat), **feat})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    clusters = event_cluster_ids(out)
    out["event_cluster"] = out["day"].map(clusters)
    return out


def build_variant(
    dfs: dict[str, pd.DataFrame],
    labels: dict[pd.Timestamp, str],
    costs: dict,
    atrs: dict[str, pd.Series],
    variant: Variant,
) -> tuple[pd.DataFrame, dict]:
    contexts = {}
    frames = {}
    for inst, df in dfs.items():
        for day_ts, day_1m in df.groupby(df.index.normalize()):
            day = pd.Timestamp(day_ts).tz_localize(None).normalize()
            if labels.get(day) != "Stress":
                continue
            ctx = context(day_1m, variant.entry_time)
            if ctx is None:
                continue
            contexts[(day, inst)] = ctx
            frames[(day, inst)] = day_1m
    event_days = build_event_day_table(contexts)
    event_meta = event_days.set_index("day").to_dict("index") if not event_days.empty else {}

    rows = []
    audit = {
        "outside_exit_bar": 0,
        "signal_after_entry": 0,
        "same_bar_exit": 0,
        "missing_forward": 0,
        "by_inst": {},
    }
    for (day, inst), ctx in contexts.items():
        if inst not in variant.instruments:
            continue
        peer_contexts = [contexts[(day, peer)] for peer in BASKET if (day, peer) in contexts]
        if not passes_breadth(variant, peer_contexts):
            continue
        day_1m = frames[(day, inst)]
        if variant.family == "late_cont_break":
            built = late_continuation_short(day_1m, ctx, variant)
            if built is None:
                continue
        else:
            if ctx["signal_close"] >= ctx["vwap"] or ctx["signal_close"] >= ctx["open"]:
                continue
            entry = ctx["entry"]
            stop = ctx["swing_high"] * (1.0 + variant.stop_pad)
            stop_dist = stop - entry
            if stop_dist <= 0 or stop_dist / entry > variant.max_stop_pct:
                continue
            target = entry - variant.rr * stop_dist
            fwd = day_1m[(day_1m.index > ctx["entry_time"]) & (day_1m.index.time <= parse_time(variant.end_time))]
            if fwd.empty:
                audit["missing_forward"] += 1
                continue
            if variant.partial_r is not None and variant.runner_rr is not None:
                partial_target = entry - variant.partial_r * stop_dist
                runner_target = entry - variant.runner_rr * stop_dist
                exit_px, reason, exit_ts, partial_px, partial_ts, points = partial_runner_exit_short(
                    fwd, entry, stop, partial_target, runner_target, variant.end_time
                )
            else:
                exit_px, reason, exit_ts = exit_short(fwd, stop, target, variant.end_time)
                partial_px = np.nan
                partial_ts = None
                points = entry - exit_px
            built = {
                "entry": entry,
                "entry_time": ctx["entry_time"],
                "signal_time": ctx["signal_time"],
                "exit": exit_px,
                "exit_reason": reason,
                "exit_time": exit_ts,
                "stop": stop,
                "target": target,
                "points": points,
                "partial_exit": partial_px,
                "partial_time": partial_ts,
            }
        if built["signal_time"] > built["entry_time"]:
            audit["signal_after_entry"] += 1
        if built["exit_time"] <= built["entry_time"]:
            audit["same_bar_exit"] += 1
        exit_bar = day_1m.loc[[built["exit_time"]]] if built["exit_time"] in day_1m.index else pd.DataFrame()
        if not exit_bar.empty:
            hi = float(exit_bar.iloc[0]["high"])
            lo = float(exit_bar.iloc[0]["low"])
            if not (lo <= built["exit"] <= hi):
                audit["outside_exit_bar"] += 1
        pv = BASKET[inst].point_value
        pnl = built["points"] * pv - costs[inst].round_turn_cost()
        path = day_1m[(day_1m.index >= built["entry_time"]) & (day_1m.index <= built["exit_time"])]
        atr = atr_asof(atrs[inst], day)
        adverse_pts = float(path["high"].max() - built["entry"]) if not path.empty else np.nan
        favorable_pts = float(built["entry"] - path["low"].min()) if not path.empty else np.nan
        meta = event_meta.get(day, {})
        rows.append({
            "variant": variant.name,
            "family": variant.family,
            "inst": inst,
            "day": day,
            "year": day.year,
            "event_subtype": meta.get("event_subtype", "unknown"),
            "event_cluster": meta.get("event_cluster", ""),
            "below_count": meta.get("below_count", np.nan),
            "wide_count": meta.get("wide_count", np.nan),
            "avg_range_pct": meta.get("avg_range_pct", np.nan),
            "entry": round(built["entry"], 2),
            "exit": round(built["exit"], 2),
            "partial_exit": round(float(built["partial_exit"]), 2) if built["partial_exit"] is not None and not pd.isna(built["partial_exit"]) else np.nan,
            "entry_time": built["entry_time"],
            "signal_time": built["signal_time"],
            "exit_time": built["exit_time"],
            "partial_time": built["partial_time"],
            "direction": "SHORT",
            "pnl": round(float(pnl), 2),
            "points": round(float(built["points"]), 2),
            "stop": round(float(built["stop"]), 2),
            "target": round(float(built["target"]), 2),
            "stop_dist": float(built["stop"] - built["entry"]),
            "stop_dist_pct": float((built["stop"] - built["entry"]) / built["entry"]),
            "daily_atr": atr,
            "mae_pts": -adverse_pts,
            "mfe_pts": favorable_pts,
            "mae_atr": -adverse_pts / atr if atr else np.nan,
            "mfe_atr": favorable_pts / atr if atr else np.nan,
            "exit_reason": built["exit_reason"],
            "range_pct": ctx["range_pct"],
        })
        audit["by_inst"][inst] = audit["by_inst"].get(inst, 0) + 1
    return pd.DataFrame(rows), audit


def daily_from_trades(tr: pd.DataFrame) -> pd.Series:
    if tr.empty:
        return pd.Series(dtype=float)
    return tr.groupby("day")["pnl"].sum().sort_index()


def summary_row(name: str, tr: pd.DataFrame, account: float) -> dict:
    daily = daily_from_trades(tr)
    m = metrics(daily)
    years = max((pd.Timestamp(daily.index[-1]) - pd.Timestamp(daily.index[0])).days / 365.25, 0.1) if len(daily) else 1.0
    wins = tr[tr["pnl"] > 0]["pnl"].sum() if not tr.empty else 0.0
    losses = -tr[tr["pnl"] < 0]["pnl"].sum() if not tr.empty else 0.0
    return {
        "name": name,
        "trades": int(len(tr)),
        "net": float(tr["pnl"].sum()) if not tr.empty else 0.0,
        "pf": float(wins / losses) if losses else math.inf,
        "sharpe": float(m["sharpe"]),
        "calmar": float(m["calmar"]),
        "maxdd": float(m["maxdd"]),
        "maxdd_pct": float(m["maxdd"] / account * 100.0),
        "ret_yr_pct": float(m["pnl"] / account / years * 100.0) if account else 0.0,
        "avg": float(tr["pnl"].mean()) if not tr.empty else 0.0,
        "median": float(tr["pnl"].median()) if not tr.empty else 0.0,
        "worst": float(tr["pnl"].min()) if not tr.empty else 0.0,
        "target_rate": float((tr["exit_reason"] == "target").mean()) if not tr.empty else 0.0,
        "stop_rate": float((tr["exit_reason"] == "stop").mean()) if not tr.empty else 0.0,
    }


def bootstrap(values: np.ndarray, n_iter: int, rng: np.random.Generator) -> dict:
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return {"p_pos": 0.0, "p5": 0.0, "p50": 0.0, "p95": 0.0}
    draws = rng.choice(values, size=(n_iter, len(values)), replace=True).sum(axis=1)
    return {
        "p_pos": float((draws > 0).mean()),
        "p5": float(np.percentile(draws, 5)),
        "p50": float(np.percentile(draws, 50)),
        "p95": float(np.percentile(draws, 95)),
    }


def print_summary(title: str, rows: list[dict]) -> None:
    print(f"\n=== {title} ===")
    for r in rows:
        print(
            f"{r['name']:<18} n={r['trades']:>4} net=${r['net']:>8,.0f} pf={r['pf']:>5.2f} "
            f"sharpe={r['sharpe']:>5.2f} calmar={r['calmar']:>5.2f} "
            f"maxdd=${r['maxdd']:>7,.0f}({r['maxdd_pct']:>4.1f}%) avg=${r['avg']:>6.2f} "
            f"med=${r['median']:>6.2f} worst=${r['worst']:>7.2f} target={r['target_rate']:>4.1%} stop={r['stop_rate']:>4.1%}"
        )


def split_table(tr: pd.DataFrame, key: str) -> pd.DataFrame:
    if tr.empty:
        return pd.DataFrame()
    out = tr.groupby(key).agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean"))
    gross_win = tr[tr["pnl"] > 0].groupby(key)["pnl"].sum()
    gross_loss = -tr[tr["pnl"] < 0].groupby(key)["pnl"].sum()
    out["pf"] = gross_win.reindex(out.index).fillna(0) / gross_loss.reindex(out.index).replace(0, np.nan)
    return out.fillna(np.inf)


def print_split(title: str, tbl: pd.DataFrame) -> None:
    print(f"\n-- {title} --")
    if tbl.empty:
        print("  empty")
        return
    for idx, r in tbl.iterrows():
        print(f"  {idx}: n={int(r['trades'])} net=${r['net']:,.0f} pf={r['pf']:.2f} avg=${r['avg']:.2f}")


def chronological_event_wfo(trades_by_variant: dict[str, pd.DataFrame], candidates: list[str], account: float) -> pd.DataFrame:
    clusters = sorted({
        c for tr in trades_by_variant.values()
        for c in tr.get("event_cluster", pd.Series(dtype=str)).dropna().unique()
        if c
    })
    rows = []
    for i, cluster in enumerate(clusters):
        prior = clusters[:i]
        if len(prior) < 3:
            continue
        scores = {}
        for name in candidates:
            tr = trades_by_variant[name]
            train = tr[tr["event_cluster"].isin(prior)]
            scores[name] = float(train["pnl"].sum()) if not train.empty else -math.inf
        selected = max(scores, key=scores.get)
        test = trades_by_variant[selected]
        test = test[test["event_cluster"] == cluster]
        row = summary_row(selected, test, account)
        subtype = ""
        for tr in trades_by_variant.values():
            sample = tr[tr.get("event_cluster", pd.Series(dtype=str)) == cluster]
            if not sample.empty:
                subtype = str(sample["event_subtype"].iloc[0])
                break
        if not subtype:
            subtype = "no selected-variant trade"
        rows.append({
            "train_clusters": len(prior),
            "test_cluster": cluster,
            "event_subtype": subtype,
            "selected": selected,
            **row,
        })
    return pd.DataFrame(rows)


def print_event_views(which: str, trades_by_variant: dict[str, pd.DataFrame], base_name: str, account: float) -> pd.DataFrame:
    base = trades_by_variant[base_name]
    print_split(f"{which} {base_name} by event subtype", split_table(base, "event_subtype"))
    print_split(f"{which} {base_name} by event cluster", split_table(base, "event_cluster"))
    candidates = [k for k in trades_by_variant if k in {
        "breadth3_mnq_mes",
        "wide3_mnq_mes",
        "rr15",
        "rr25",
        "exit1200",
        "exit1555",
        "delay1025",
        "late_cont_break",
        "partial1r_run25",
    }]
    folds = chronological_event_wfo(trades_by_variant, candidates, account)
    print(f"\n-- {which} chronological event-cluster WFO --")
    if folds.empty:
        print("  insufficient event clusters")
        return folds
    for _, r in folds.iterrows():
        print(
            f"  train_clusters={int(r['train_clusters']):>2} -> {r['test_cluster']:<35} "
            f"subtype={r['event_subtype']:<24} pick={r['selected']:<18} "
            f"n={int(r['trades']):>2} net=${r['net']:>7,.0f} pf={r['pf']:>5.2f}"
        )
    overall = summary_row("event_wfo", folds.rename(columns={"net": "pnl"}) if False else pd.DataFrame(), account)
    total = float(folds["net"].sum()) if "net" in folds else 0.0
    pos = int((folds["net"] > 0).sum()) if "net" in folds else 0
    print(f"  total held-out event PnL=${total:,.0f}; positive folds={pos}/{len(folds)}")
    return folds


def apply_risk_cap(tr: pd.DataFrame, account: float, cap_pct: float) -> pd.DataFrame:
    if tr.empty:
        return tr
    parts = []
    for _, g in tr.groupby("day"):
        used = 0.0
        for _, row in g.sort_values(["inst"]).iterrows():
            risk = row["daily_atr"] * 2.5 * BASKET[row["inst"]].point_value
            if used + risk <= account * cap_pct:
                parts.append(row)
                used += risk
    return pd.DataFrame(parts).reset_index(drop=True) if parts else tr.iloc[0:0]


def print_cap_proxy(title: str, base: pd.DataFrame, account: float) -> None:
    print(f"\n-- {title} cap proxy --")
    for cap in [0.025, 0.05, 0.075, 0.10]:
        tr = apply_risk_cap(base, account, cap)
        row = summary_row(f"cap{cap:.3f}", tr, account)
        print(f"  cap={cap:>5.1%} n={row['trades']:>3} net=${row['net']:>7,.0f} pf={row['pf']:>5.2f} calmar={row['calmar']:>5.2f} maxdd={row['maxdd_pct']:>4.1f}%")


def markdown_table(rows: list[dict], fields: list[str]) -> str:
    lines = ["| " + " | ".join(fields) + " |", "| " + " | ".join("---" for _ in fields) + " |"]
    for r in rows:
        vals = []
        for f in fields:
            v = r.get(f, "")
            if isinstance(v, float):
                if f in {"net", "maxdd", "avg", "worst"}:
                    vals.append(f"${v:,.0f}")
                elif f.endswith("_pct"):
                    vals.append(f"{v:.1f}%")
                else:
                    vals.append(f"{v:.2f}")
            else:
                vals.append(str(v))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def df_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_empty_"
    work = df.reset_index()
    fields = [str(c) for c in work.columns]
    rows = []
    for rec in work.to_dict("records"):
        row = {}
        for k, v in rec.items():
            if isinstance(v, float):
                row[str(k)] = f"{v:.2f}"
            else:
                row[str(k)] = v
        rows.append(row)
    return markdown_table(rows, fields)


def write_report(path: Path, collected: dict, account: float) -> None:
    lines = [
        "# Stress Sleeve Event Validation",
        "",
        "Scratch-only report. No production code change is implied.",
        "",
        "Candidate under review: Stress-only confirmed 10:20 liquidation SHORT, full 10:15-10:19 5m signal, MNQ/MES, stop = 09:45-10:15 swing high * 1.001, target 2R, exit by 14:00, 2 ticks/side.",
        "",
    ]
    for which, data in collected.items():
        rows = data["summary"]
        lines += [
            f"## {which}",
            "",
            markdown_table(rows, ["name", "trades", "net", "pf", "sharpe", "calmar", "maxdd_pct", "target_rate", "stop_rate"]),
            "",
            "Fill/timing audit for base:",
            "",
            f"- outside_exit_bar={data['audit'].get('outside_exit_bar', 0)}",
            f"- signal_after_entry={data['audit'].get('signal_after_entry', 0)}",
            f"- same_bar_exit={data['audit'].get('same_bar_exit', 0)}",
            "",
        ]
        base = data["base"]
        if not base.empty:
            lines += [
                "Base by event subtype:",
                "",
                df_markdown(split_table(base, "event_subtype")),
                "",
                "Base by instrument:",
                "",
                df_markdown(split_table(base, "inst")),
                "",
            ]
        folds = data.get("event_wfo", pd.DataFrame())
        if not folds.empty:
            show = folds[["test_cluster", "event_subtype", "selected", "trades", "net", "pf"]].copy()
            lines += [
                "Chronological held-out event-cluster WFO:",
                "",
                markdown_table(show.to_dict("records"), ["test_cluster", "event_subtype", "selected", "trades", "net", "pf"]),
                "",
                f"Held-out event total: ${float(folds['net'].sum()):,.0f}; positive folds: {int((folds['net'] > 0).sum())}/{len(folds)}.",
                "",
            ]
    lines += [
        "## Verdict",
        "",
        "Keep Stress as hedge only, not standalone alpha.",
        "",
        "Deploy-level hedge candidate to carry forward, conditionally: `breadth3_mnq_mes`, confirmed 10:20 SHORT, MNQ/MES, 2R target, 14:00 exit, stop at 09:45-10:15 swing high * 1.001, with a coarse Stress cap review around 7.5%-10%. The 2.5% cap is not a fair test because it suppresses the candidate in OOS; 5% is still marginal in the standalone cap proxy.",
        "",
        "Do not promote live until basket-level timing and broker mechanics are solved: the live signal must have the full 10:15-10:19 5m bar before entry, Stress needs explicit same-day exit/stop ownership, and same-symbol Normal/Calm/Stress netting risk must be handled.",
        "",
        "Reject as standalone robust alpha because 2018/2019/2020 carry is negative, event-cluster folds are not consistently positive, 2023-2024/2026 have no contribution, and the edge is a sparse crisis payoff rather than a smooth return stream.",
        "",
        f"Account assumption for cap/DD display: ${account:,.0f}.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--account", type=float, default=50_000.0)
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end-oos", default="2024-12-31")
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--bootstrap-iters", type=int, default=1000)
    ap.add_argument("--report", default="scratch/stress_sleeve_event_validation_report.md")
    args = ap.parse_args()

    variants = [
        Variant("breadth3_mnq_mes"),
        Variant("wide3_mnq_mes", breadth="wide_range3"),
        Variant("breadth3_all4", instruments=("MES", "MNQ", "MYM", "M2K")),
        Variant("breadth3_mnq", instruments=("MNQ",)),
        Variant("breadth3_mes", instruments=("MES",)),
        Variant("rr15", rr=1.5),
        Variant("rr25", rr=2.5),
        Variant("exit1200", end_time="12:00"),
        Variant("exit1555", end_time="15:55"),
        Variant("delay1025", entry_time="10:25"),
        Variant("late_cont_break", family="late_cont_break", rr=1.5),
        Variant("partial1r_run25", partial_r=1.0, runner_rr=2.5, rr=2.5),
    ]
    rng = np.random.default_rng(20260820)
    collected = {}

    print("Stress sleeve validation:")
    print("  signal: Stress only, full 10:15-10:19 5m confirmation, enter at/after configured entry time")
    print("  base: breadth3, MNQ/MES, SHORT 10:20, 2R target, stop=swing_high*1.001, exit <=14:00")

    for which in args.which:
        print(f"\n--- loading {which} ---", flush=True)
        argv = list(ARGV[which])
        data_dir = arg_from(argv, "--data-dir")
        start = arg_from(argv, "--start")
        end = arg_from(argv, "--end")
        regime_csv = arg_from(argv, "--regime-csv", args.regime_csv)
        hmm_fit_end = arg_from(argv, "--hmm-fit-end", args.hmm_fit_end_oos)
        dfs = {
            name: clip(load_parquet(str(Path(data_dir) / data_filename(contract))), start, end)
            for name, contract in BASKET.items()
        }
        print("  loaded dfs: " + ", ".join(f"{k}={len(v):,}" for k, v in dfs.items()), flush=True)
        atrs = {name: daily_atr_series(df) for name, df in dfs.items()}
        labels = label_regimes(benchmark_daily(regime_csv), args.hmm_train_end, 3, hmm_fit_end)
        costs = costs_for_basket(slippage_ticks=args.slippage_ticks)

        trades_by_variant = {}
        audits = {}
        rows = []
        for v in variants:
            tr, audit = build_variant(dfs, labels, costs, atrs, v)
            trades_by_variant[v.name] = tr
            audits[v.name] = audit
            rows.append(summary_row(v.name, tr, args.account))
            print(f"  built {v.name:<16} n={len(tr):>3} net=${tr['pnl'].sum() if not tr.empty else 0:,.0f}", flush=True)
        print_summary(which, rows)

        base = trades_by_variant["breadth3_mnq_mes"]
        audit = audits["breadth3_mnq_mes"]
        print(f"-- fill/timing audit {which} -- outside_exit_bar={audit['outside_exit_bar']} signal_after_entry={audit['signal_after_entry']} same_bar_exit={audit['same_bar_exit']} missing_forward={audit['missing_forward']} by_inst={audit['by_inst']}")
        print_split(f"{which} base by year", split_table(base, "year"))
        print_split(f"{which} base by instrument", split_table(base, "inst"))
        event_wfo = print_event_views(which, trades_by_variant, "breadth3_mnq_mes", args.account)
        if not base.empty:
            print(f"-- MAE/MFE {which} base -- mae_med={base['mae_atr'].median():.2f}ATR mae_p05={base['mae_atr'].quantile(0.05):.2f}ATR mfe_med={base['mfe_atr'].median():.2f}ATR mfe_p95={base['mfe_atr'].quantile(0.95):.2f}ATR")
            b_trade = bootstrap(base["pnl"].to_numpy(), args.bootstrap_iters, rng)
            b_daily = bootstrap(daily_from_trades(base).to_numpy(), args.bootstrap_iters, rng)
            print(f"-- bootstrap {which} base -- trade P(net>0)={b_trade['p_pos']:.3f} net5/50/95=${b_trade['p5']:,.0f}/${b_trade['p50']:,.0f}/${b_trade['p95']:,.0f}; daily P(net>0)={b_daily['p_pos']:.3f} net5/50/95=${b_daily['p5']:,.0f}/${b_daily['p50']:,.0f}/${b_daily['p95']:,.0f}")
            print_cap_proxy(f"{which} base", base, args.account)
        collected[which] = {
            "summary": rows,
            "audit": audit,
            "base": base,
            "event_wfo": event_wfo,
        }

    report_path = Path(args.report)
    write_report(report_path, collected, args.account)
    print(f"\nwrote report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
