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

from futures._validated_core import benchmark_daily, daily_atr_series, label_regimes, load_parquet
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket
from global_index.deploy_sim import metrics
from scratch.calm_candidate_deploy_probe import first_at_or_after, trading_day_index
from scratch.harness import ARGV


@dataclass(frozen=True)
class Variant:
    name: str
    exit_time: str = "15:55"
    stop_atr: float | None = None
    stop_start_time: str | None = None
    cutoff_time: str | None = None
    cutoff_atr: float | None = None
    partial_time: str | None = None
    partial_frac: float = 0.0


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


def stop_exit_long(path: pd.DataFrame, stop_px: float) -> tuple[pd.Timestamp, float] | None:
    for ts, row in path.iterrows():
        lo = float(row["low"])
        if lo <= stop_px:
            op = float(row["open"])
            return ts, op if op <= stop_px else stop_px
    return None


def cutoff_exit_long(rth: pd.DataFrame, cutoff_time: str, cutoff_px: float, final_ts: pd.Timestamp) -> tuple[pd.Timestamp, float] | None:
    bar = first_at_or_after(rth, cutoff_time, "open")
    if bar is None:
        return None
    ts, px = bar
    if ts > final_ts:
        return None
    return (ts, px) if px <= cutoff_px else None


def pnl_long(entry_px: float, exit_px: float, pv: float, cost_rt: float, size: float = 1.0) -> float:
    return ((exit_px - entry_px) * pv - cost_rt) * size


def build_trades(
    dfs: dict[str, pd.DataFrame],
    labels: dict[pd.Timestamp, str],
    costs: dict,
    atrs: dict[str, pd.Series],
    *,
    instruments: set[str],
    min_overnight: float,
    max_overnight: float,
    variant: Variant,
) -> tuple[pd.DataFrame, dict]:
    rows = []
    audit = {
        "signals": 0,
        "outside_exit_bar": 0,
        "signal_after_entry": 0,
        "missing_exit": 0,
        "missing_partial": 0,
        "by_inst": {},
    }
    for inst, df in dfs.items():
        if inst not in instruments:
            continue
        tdays = trading_day_index(df.index)
        pv = BASKET[inst].point_value
        cost_rt = costs[inst].round_turn_cost()
        for day, g in df.groupby(tdays):
            day = pd.Timestamp(day).normalize()
            if labels.get(day) != "Calm":
                continue
            rth = g.between_time("09:30", "15:59")
            pre = g[(g.index.time >= pd.Timestamp("18:00").time()) | (g.index.time < pd.Timestamp("09:30").time())]
            if len(rth) < 160 or len(pre) < 30:
                continue
            entry = first_at_or_after(rth, "09:30", "open")
            scheduled = first_at_or_after(rth, variant.exit_time, "open")
            if not entry or not scheduled:
                audit["missing_exit"] += 1
                continue
            overnight_ret = float(pre.iloc[-1]["close"] / pre.iloc[0]["open"] - 1.0)
            if not (min_overnight < overnight_ret <= max_overnight):
                continue
            audit["signals"] += 1
            entry_ts, entry_px = entry
            exit_ts, exit_px = scheduled
            if pd.Timestamp("09:30").time() > pd.Timestamp(entry_ts).time():
                audit["signal_after_entry"] += 1
            if exit_ts < entry_ts:
                audit["outside_exit_bar"] += 1
                continue
            path = rth[(rth.index >= entry_ts) & (rth.index <= exit_ts)]
            if path.empty:
                audit["missing_exit"] += 1
                continue
            atr = atr_asof(atrs[inst], day)
            stop_ts = None
            stop_px = np.nan
            final_ts, final_px, reason = exit_ts, exit_px, f"{variant.exit_time}_OPEN"
            if variant.cutoff_time and variant.cutoff_atr is not None:
                cpx = entry_px - variant.cutoff_atr * atr
                cut = cutoff_exit_long(rth, variant.cutoff_time, cpx, final_ts)
                if cut is not None:
                    final_ts, final_px = cut
                    reason = f"CUTOFF_{variant.cutoff_time}_{variant.cutoff_atr:g}xDATR"
                    path = rth[(rth.index >= entry_ts) & (rth.index <= final_ts)]
            if variant.stop_atr is not None:
                stop_px = entry_px - variant.stop_atr * atr
                stop_path = path
                if variant.stop_start_time:
                    start_bar = first_at_or_after(rth, variant.stop_start_time, "open")
                    if start_bar is not None:
                        stop_path = path[path.index >= start_bar[0]]
                stopped = stop_exit_long(stop_path, stop_px)
                if stopped is not None:
                    stop_ts, final_px = stopped
                    final_ts = stop_ts
                    reason = f"STOP_{variant.stop_atr:g}xDATR"
                    path = rth[(rth.index >= entry_ts) & (rth.index <= final_ts)]
            partial_pnl = 0.0
            partial_ts = None
            partial_px = np.nan
            if variant.partial_time and variant.partial_frac > 0:
                pbar = first_at_or_after(rth, variant.partial_time, "open")
                if pbar is None or pbar[0] > final_ts:
                    audit["missing_partial"] += 1
                else:
                    partial_ts, partial_px = pbar
                    partial_pnl = pnl_long(entry_px, partial_px, pv, cost_rt, variant.partial_frac)
            main_size = 1.0 - (variant.partial_frac if partial_ts is not None else 0.0)
            net_pnl = pnl_long(entry_px, final_px, pv, cost_rt, main_size) + partial_pnl
            lows = path["low"].astype(float)
            highs = path["high"].astype(float)
            mae_pts = float(lows.min() - entry_px)
            mfe_pts = float(highs.max() - entry_px)
            rows.append({
                "variant": variant.name,
                "inst": inst,
                "day": day,
                "year": day.year,
                "entry_time": entry_ts,
                "exit_time": final_ts,
                "scheduled_exit_time": exit_ts,
                "partial_time": partial_ts,
                "entry": float(entry_px),
                "exit": float(final_px),
                "partial_exit": float(partial_px) if not pd.isna(partial_px) else np.nan,
                "overnight_ret": overnight_ret,
                "daily_atr": atr,
                "stop_atr": variant.stop_atr if variant.stop_atr is not None else np.nan,
                "stop_px": float(stop_px) if not pd.isna(stop_px) else np.nan,
                "pnl": round(float(net_pnl), 2),
                "points": round(float(final_px - entry_px), 2),
                "mae_pts": mae_pts,
                "mfe_pts": mfe_pts,
                "mae_atr": mae_pts / atr if atr else np.nan,
                "mfe_atr": mfe_pts / atr if atr else np.nan,
                "exit_reason": reason,
            })
            audit["by_inst"][inst] = audit["by_inst"].get(inst, 0) + 1
    return pd.DataFrame(rows), audit


def build_all_variant_trades(
    dfs: dict[str, pd.DataFrame],
    labels: dict[pd.Timestamp, str],
    costs: dict,
    atrs: dict[str, pd.Series],
    *,
    instruments: set[str],
    min_overnight: float,
    max_overnight: float,
    variants: list[Variant],
) -> tuple[dict[str, pd.DataFrame], dict[str, dict]]:
    rows = {v.name: [] for v in variants}
    audits = {
        v.name: {
            "signals": 0,
            "outside_exit_bar": 0,
            "signal_after_entry": 0,
            "missing_exit": 0,
            "missing_partial": 0,
            "by_inst": {},
        }
        for v in variants
    }
    for inst, df in dfs.items():
        if inst not in instruments:
            continue
        tdays = trading_day_index(df.index)
        pv = BASKET[inst].point_value
        cost_rt = costs[inst].round_turn_cost()
        for day, g in df.groupby(tdays):
            day = pd.Timestamp(day).normalize()
            if labels.get(day) != "Calm":
                continue
            rth = g.between_time("09:30", "15:59")
            pre = g[(g.index.time >= pd.Timestamp("18:00").time()) | (g.index.time < pd.Timestamp("09:30").time())]
            if len(rth) < 160 or len(pre) < 30:
                continue
            entry = first_at_or_after(rth, "09:30", "open")
            if not entry:
                continue
            overnight_ret = float(pre.iloc[-1]["close"] / pre.iloc[0]["open"] - 1.0)
            if not (min_overnight < overnight_ret <= max_overnight):
                continue
            entry_ts, entry_px = entry
            atr = atr_asof(atrs[inst], day)
            exit_cache = {v.exit_time for v in variants}
            if any(v.partial_time for v in variants):
                exit_cache |= {v.partial_time for v in variants if v.partial_time}
            if any(v.cutoff_time for v in variants):
                exit_cache |= {v.cutoff_time for v in variants if v.cutoff_time}
            if any(v.stop_start_time for v in variants):
                exit_cache |= {v.stop_start_time for v in variants if v.stop_start_time}
            bars = {t: first_at_or_after(rth, t, "open") for t in exit_cache}
            for variant in variants:
                audit = audits[variant.name]
                audit["signals"] += 1
                scheduled = bars.get(variant.exit_time)
                if not scheduled:
                    audit["missing_exit"] += 1
                    continue
                exit_ts, exit_px = scheduled
                if exit_ts < entry_ts:
                    audit["outside_exit_bar"] += 1
                    continue
                path = rth[(rth.index >= entry_ts) & (rth.index <= exit_ts)]
                if path.empty:
                    audit["missing_exit"] += 1
                    continue
                stop_ts = None
                stop_px = np.nan
                final_ts, final_px, reason = exit_ts, exit_px, f"{variant.exit_time}_OPEN"
                if variant.cutoff_time and variant.cutoff_atr is not None:
                    cpx = entry_px - variant.cutoff_atr * atr
                    cut = cutoff_exit_long(rth, variant.cutoff_time, cpx, final_ts)
                    if cut is not None:
                        final_ts, final_px = cut
                        reason = f"CUTOFF_{variant.cutoff_time}_{variant.cutoff_atr:g}xDATR"
                        path = rth[(rth.index >= entry_ts) & (rth.index <= final_ts)]
                if variant.stop_atr is not None:
                    stop_px = entry_px - variant.stop_atr * atr
                    stop_path = path
                    if variant.stop_start_time:
                        start_bar = bars.get(variant.stop_start_time)
                        if start_bar is not None:
                            stop_path = path[path.index >= start_bar[0]]
                    stopped = stop_exit_long(stop_path, stop_px)
                    if stopped is not None:
                        stop_ts, final_px = stopped
                        final_ts = stop_ts
                        reason = f"STOP_{variant.stop_atr:g}xDATR"
                        path = rth[(rth.index >= entry_ts) & (rth.index <= final_ts)]
                partial_pnl = 0.0
                partial_ts = None
                partial_px = np.nan
                if variant.partial_time and variant.partial_frac > 0:
                    pbar = bars.get(variant.partial_time)
                    if pbar is None or pbar[0] > final_ts:
                        audit["missing_partial"] += 1
                    else:
                        partial_ts, partial_px = pbar
                        partial_pnl = pnl_long(entry_px, partial_px, pv, cost_rt, variant.partial_frac)
                main_size = 1.0 - (variant.partial_frac if partial_ts is not None else 0.0)
                net_pnl = pnl_long(entry_px, final_px, pv, cost_rt, main_size) + partial_pnl
                lows = path["low"].astype(float)
                highs = path["high"].astype(float)
                mae_pts = float(lows.min() - entry_px)
                mfe_pts = float(highs.max() - entry_px)
                rows[variant.name].append({
                    "variant": variant.name,
                    "inst": inst,
                    "day": day,
                    "year": day.year,
                    "entry_time": entry_ts,
                    "exit_time": final_ts,
                    "scheduled_exit_time": exit_ts,
                    "partial_time": partial_ts,
                    "entry": float(entry_px),
                    "exit": float(final_px),
                    "partial_exit": float(partial_px) if not pd.isna(partial_px) else np.nan,
                    "overnight_ret": overnight_ret,
                    "daily_atr": atr,
                    "stop_atr": variant.stop_atr if variant.stop_atr is not None else np.nan,
                    "stop_px": float(stop_px) if not pd.isna(stop_px) else np.nan,
                    "pnl": round(float(net_pnl), 2),
                    "points": round(float(final_px - entry_px), 2),
                    "mae_pts": mae_pts,
                    "mfe_pts": mfe_pts,
                    "mae_atr": mae_pts / atr if atr else np.nan,
                    "mfe_atr": mfe_pts / atr if atr else np.nan,
                    "exit_reason": reason,
                })
                audit["by_inst"][inst] = audit["by_inst"].get(inst, 0) + 1
    return {name: pd.DataFrame(r) for name, r in rows.items()}, audits


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
        "top5_share": top_share(tr, 5),
        "stop_rate": float((tr["exit_reason"].str.startswith("STOP")).mean()) if not tr.empty else 0.0,
    }


def top_share(tr: pd.DataFrame, n: int) -> float:
    if tr.empty or tr["pnl"].sum() <= 0:
        return 0.0
    return float(tr["pnl"].nlargest(min(n, len(tr))).sum() / tr["pnl"].sum())


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
            f"med=${r['median']:>6.2f} worst=${r['worst']:>7.2f} top5={r['top5_share']:>4.1%} stop={r['stop_rate']:>4.1%}"
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


def fold_report(trades_by_variant: dict[str, pd.DataFrame], candidates: list[str]) -> None:
    years = sorted({int(y) for tr in trades_by_variant.values() for y in tr.get("year", pd.Series(dtype=int)).unique()})
    print("\n=== rough WFO by prior-year net ===")
    print("fold train_years -> test_year | selected | test_net | test_pf | test_trades")
    for i, year in enumerate(years):
        train_years = [y for y in years[:i] if y < year]
        if len(train_years) < 3:
            continue
        scores = {}
        for name in candidates:
            tr = trades_by_variant[name]
            scores[name] = float(tr[tr["year"].isin(train_years)]["pnl"].sum())
        selected = max(scores, key=scores.get)
        test = trades_by_variant[selected]
        test = test[test["year"] == year]
        row = summary_row(selected, test, 50_000)
        print(f"{train_years[0]}-{train_years[-1]} -> {year} | {selected:<18} | ${row['net']:>7,.0f} | {row['pf']:>5.2f} | {row['trades']}")


def cap_by_day(tr: pd.DataFrame, max_positions: int, *, priority: str = "most_negative") -> pd.DataFrame:
    if tr.empty:
        return tr
    parts = []
    for _, g in tr.groupby("day"):
        if priority == "most_negative":
            g = g.sort_values(["overnight_ret", "inst"], ascending=[True, True])
        elif priority == "best_mae":
            g = g.sort_values(["mae_atr", "inst"], ascending=[False, True])
        else:
            g = g.sort_values("inst")
        parts.append(g.head(max_positions))
    return pd.concat(parts).sort_values(["day", "inst"]).reset_index(drop=True) if parts else tr.iloc[0:0]


def risk_proxy_stats(tr: pd.DataFrame, account: float) -> dict:
    if tr.empty:
        return {"max_daily_risk_pct": 0.0, "p95_daily_risk_pct": 0.0, "max_positions": 0}
    work = tr.copy()
    work["risk_proxy"] = work["daily_atr"] * work["inst"].map(lambda x: BASKET[x].point_value)
    daily_risk = work.groupby("day")["risk_proxy"].sum()
    daily_n = work.groupby("day").size()
    return {
        "max_daily_risk_pct": float(daily_risk.max() / account * 100.0),
        "p95_daily_risk_pct": float(daily_risk.quantile(0.95) / account * 100.0),
        "max_positions": int(daily_n.max()),
    }


def print_risk_policy(title: str, base: pd.DataFrame, account: float) -> None:
    candidates = {
        "all_3": base,
        "max2_mostneg": cap_by_day(base, 2, priority="most_negative"),
        "max1_mostneg": cap_by_day(base, 1, priority="most_negative"),
        "MES_only": base[base["inst"] == "MES"],
        "MNQ_only": base[base["inst"] == "MNQ"],
        "MYM_only": base[base["inst"] == "MYM"],
        "no_MYM": base[base["inst"].isin(["MES", "MNQ"])],
    }
    print(f"\n-- {title} risk/cap proxy --")
    for name, tr in candidates.items():
        row = summary_row(name, tr, account)
        rp = risk_proxy_stats(tr, account)
        print(
            f"  {name:<13} n={row['trades']:>4} net=${row['net']:>8,.0f} pf={row['pf']:>5.2f} "
            f"calmar={row['calmar']:>5.2f} maxdd={row['maxdd_pct']:>4.1f}% "
            f"max_pos={rp['max_positions']} risk_p95={rp['p95_daily_risk_pct']:.1f}% risk_max={rp['max_daily_risk_pct']:.1f}%"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end-oos", default="2024-12-31")
    ap.add_argument("--account", type=float, default=50_000.0)
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--instruments", nargs="+", default=["MES", "MNQ", "MYM"])
    ap.add_argument("--min-overnight", type=float, default=-0.010)
    ap.add_argument("--max-overnight", type=float, default=-0.001)
    ap.add_argument("--bootstrap-iters", type=int, default=2000)
    ap.add_argument("--variant-set", choices=["all", "pass1", "risk2"], default="all")
    args = ap.parse_args()

    pass1_variants = [
        Variant("x1200", "12:00"),
        Variant("x1400", "14:00"),
        Variant("x1555", "15:55"),
        Variant("x1555_stop05", "15:55", stop_atr=0.5),
        Variant("x1555_stop075", "15:55", stop_atr=0.75),
        Variant("x1555_stop10", "15:55", stop_atr=1.0),
        Variant("partial12_1555", "15:55", partial_time="12:00", partial_frac=0.5),
        Variant("partial14_1555", "15:55", partial_time="14:00", partial_frac=0.5),
    ]
    risk2_variants = [
        Variant("x1555", "15:55"),
        Variant("x1555_stop125", "15:55", stop_atr=1.25),
        Variant("x1555_stop15", "15:55", stop_atr=1.5),
        Variant("x1555_stop20", "15:55", stop_atr=2.0),
        Variant("stop075_1030", "15:55", stop_atr=0.75, stop_start_time="10:30"),
        Variant("stop075_1200", "15:55", stop_atr=0.75, stop_start_time="12:00"),
        Variant("cut1030_05", "15:55", cutoff_time="10:30", cutoff_atr=0.5),
        Variant("cut1200_05", "15:55", cutoff_time="12:00", cutoff_atr=0.5),
        Variant("cut1200_075", "15:55", cutoff_time="12:00", cutoff_atr=0.75),
    ]
    if args.variant_set == "pass1":
        variants = pass1_variants
    elif args.variant_set == "risk2":
        variants = risk2_variants
    else:
        seen = set()
        variants = []
        for v in pass1_variants + risk2_variants:
            if v.name not in seen:
                variants.append(v)
                seen.add(v.name)
    wfo_candidates = [v.name for v in variants if v.name != "x1555" or args.variant_set != "all"]
    rng = np.random.default_rng(20260820)

    print("Calm sleeve validation:")
    print(f"  signal: Calm only, LONG RTH open, overnight_ret in ({args.min_overnight:.3%}, {args.max_overnight:.3%}], inst={','.join(args.instruments)}")
    print("  fill law: entry RTH-open feasible price; exits use later bar open; stops use first feasible low crossing")

    all_for_docs = {}
    for which in args.which:
        print(f"\n--- loading {which} ---", flush=True)
        argv = list(ARGV[which])
        data_dir = arg_from(argv, "--data-dir")
        start = arg_from(argv, "--start")
        end = arg_from(argv, "--end")
        regime_csv = arg_from(argv, "--regime-csv", args.regime_csv)
        hmm_fit_end = arg_from(argv, "--hmm-fit-end", args.hmm_fit_end_oos)
        wanted = set(args.instruments)
        dfs = {
            name: clip(load_parquet(str(Path(data_dir) / data_filename(contract))), start, end)
            for name, contract in BASKET.items()
            if name in wanted
        }
        print(f"  loaded dfs: " + ", ".join(f"{k}={len(v):,}" for k, v in dfs.items()), flush=True)
        atrs = {name: daily_atr_series(df) for name, df in dfs.items()}
        print("  computed ATR", flush=True)
        labels = label_regimes(benchmark_daily(regime_csv), args.hmm_train_end, 3, hmm_fit_end)
        print(f"  labels={len(labels):,}", flush=True)
        costs = costs_for_basket(slippage_ticks=args.slippage_ticks)

        print("  build all variants", flush=True)
        trades_by_variant, audits = build_all_variant_trades(
            dfs,
            labels,
            costs,
            atrs,
            instruments=set(args.instruments),
            min_overnight=args.min_overnight,
            max_overnight=args.max_overnight,
            variants=variants,
        )
        rows = []
        for v in variants:
            tr = trades_by_variant[v.name]
            rows.append(summary_row(v.name, tr, args.account))
            print(f"    {v.name:<16} -> n={len(tr)} net=${tr['pnl'].sum() if not tr.empty else 0:,.0f}", flush=True)
        print_summary(which, rows)
        base = trades_by_variant["x1555"]
        print(f"-- fill audit {which} -- outside_exit_bar={audits['x1555']['outside_exit_bar']} signal_after_entry={audits['x1555']['signal_after_entry']} trades={len(base)} by_inst={audits['x1555']['by_inst']}")
        print_split(f"{which} x1555 by year", split_table(base, "year"))
        print_split(f"{which} x1555 by instrument", split_table(base, "inst"))
        if not base.empty:
            print(f"-- MAE/MFE {which} x1555 -- mae_med={base['mae_atr'].median():.2f}ATR mae_p05={base['mae_atr'].quantile(0.05):.2f}ATR mfe_med={base['mfe_atr'].median():.2f}ATR mfe_p95={base['mfe_atr'].quantile(0.95):.2f}ATR")
            b_trade = bootstrap(base["pnl"].to_numpy(), args.bootstrap_iters, rng)
            b_daily = bootstrap(daily_from_trades(base).to_numpy(), args.bootstrap_iters, rng)
            print(f"-- bootstrap {which} x1555 -- trade P(net>0)={b_trade['p_pos']:.3f} net5/50/95=${b_trade['p5']:,.0f}/${b_trade['p50']:,.0f}/${b_trade['p95']:,.0f}; daily P(net>0)={b_daily['p_pos']:.3f} net5/50/95=${b_daily['p5']:,.0f}/${b_daily['p50']:,.0f}/${b_daily['p95']:,.0f}")
            print_risk_policy(f"{which} x1555", base, args.account)
        if which == "floor":
            fold_report(trades_by_variant, [v.name for v in variants])
        all_for_docs[which] = {name: summary_row(name, tr, args.account) for name, tr in trades_by_variant.items()}

    print("\n=== event/macro data ===")
    candidates = list(Path(".").glob("*macro*")) + list(Path(".").glob("*event*")) + list(Path("data").glob("**/*macro*")) + list(Path("data").glob("**/*event*"))
    if candidates:
        for p in candidates[:20]:
            print(f"  found: {p}")
        print("  not joined in this first pass; requires schema mapping to trading days.")
    else:
        print("  no obvious macro/event calendar file found locally; skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
