from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, daily_atr_series, label_regimes, load_parquet
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket


def trading_day_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    local = idx.normalize()
    evening = np.array([t >= pd.Timestamp("18:00").time() for t in idx.time])
    out = np.where(evening, local + pd.Timedelta(days=1), local)
    return pd.DatetimeIndex(out).tz_localize(None).normalize()


def first_at_or_after(g: pd.DataFrame, hhmm: str, col: str = "open") -> tuple[pd.Timestamp, float] | None:
    sub = g[g.index.time >= pd.Timestamp(hhmm).time()]
    if sub.empty:
        return None
    return sub.index[0], float(sub.iloc[0][col])


def price_inside_bar(price: float, bar: pd.Series) -> bool:
    px = float(price)
    lo = float(bar["low"])
    hi = float(bar["high"])
    eps = max(abs(px), abs(lo), abs(hi), 1.0) * 1e-9
    return lo - eps <= px <= hi + eps


def calm_labels(calm_days_csv: str | None, regime_csv: str, train_end: str, fit_end: str) -> dict:
    if calm_days_csv and Path(calm_days_csv).exists():
        days = pd.read_csv(calm_days_csv, usecols=["day"])["day"].dropna().unique()
        return {pd.Timestamp(x).normalize(): "Calm" for x in days}
    return label_regimes(benchmark_daily(regime_csv), train_end, 3, fit_end)


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "pnl": 0.0, "pf": 0.0, "exp": 0.0}
    pnl = df["pnl"].astype(float)
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    return {"n": int(len(df)), "pnl": float(pnl.sum()), "pf": gw / gl if gl else math.inf, "exp": float(pnl.mean())}


def run_window(args, data_dir: str, start: str, end: str, fit_end: str, calm_days_csv: str) -> pd.DataFrame:
    labels = calm_labels(calm_days_csv, args.regime_csv, args.hmm_train_end, fit_end)
    costs = costs_for_basket(slippage_ticks=args.slippage_ticks)
    rows = []
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    for inst, contract in BASKET.items():
        if inst not in set(args.instruments):
            continue
        df0 = load_parquet(str(Path(data_dir) / data_filename(contract)))
        atr = daily_atr_series(df0)
        ss = s.tz_localize(df0.index.tz)
        ee = e.tz_localize(df0.index.tz) + pd.Timedelta(days=1)
        df = df0[(df0.index >= ss - pd.Timedelta(days=1)) & (df0.index <= ee)].copy()
        df["tday"] = trading_day_index(df.index)
        pv = BASKET[inst].point_value
        cost = costs[inst].round_turn_cost()
        for day, g in df.groupby("tday"):
            day = pd.Timestamp(day).normalize()
            if day < s or day > e or labels.get(day) != "Calm":
                continue
            rth = g.between_time("09:30", "15:59")
            pre = g[(g.index.time >= pd.Timestamp("18:00").time()) | (g.index.time < pd.Timestamp("09:30").time())]
            if len(rth) < 160 or len(pre) < 30:
                continue
            entry = first_at_or_after(rth, "09:30", "open")
            exit_bar = first_at_or_after(rth, args.exit_time, "open")
            if not entry or not exit_bar:
                continue
            overnight_ret = float(pre.iloc[-1]["close"] / pre.iloc[0]["open"] - 1.0)
            if not (args.min_overnight < overnight_ret <= args.max_overnight):
                continue
            entry_ts, entry_px = entry
            exit_ts, exit_px = exit_bar
            if pd.Timestamp(exit_ts) <= pd.Timestamp(entry_ts):
                continue
            exit_row = rth.loc[exit_ts]
            entry_row = rth.loc[entry_ts]
            path = rth[(rth.index > entry_ts) & (rth.index <= exit_ts)]
            if path.empty:
                continue
            min_low = float(path["low"].min())
            max_high = float(path["high"].max())
            mae_pts = max(0.0, float(entry_px) - min_low)
            mfe_pts = max(0.0, max_high - float(entry_px))
            pnl_pts = float(exit_px) - float(entry_px)
            av = atr.asof(day)
            if av is None or pd.isna(av):
                av = float(atr.median())
            rows.append({
                "inst": inst,
                "day": day.date().isoformat(),
                "year": int(day.year),
                "entry_time": entry_ts,
                "exit_time": exit_ts,
                "entry": float(entry_px),
                "exit": float(exit_px),
                "pnl": pnl_pts * pv - cost,
                "mae_pts": mae_pts,
                "mfe_pts": mfe_pts,
                "mae_dollars": mae_pts * pv,
                "mfe_dollars": mfe_pts * pv,
                "atr": float(av),
                "mae_atr": mae_pts / float(av) if av else np.nan,
                "mfe_atr": mfe_pts / float(av) if av else np.nan,
                "overnight_ret": overnight_ret,
                "outside_exit_bar": 0 if price_inside_bar(exit_px, exit_row) else 1,
                "outside_entry_bar": 0 if price_inside_bar(entry_px, entry_row) else 1,
                "signal_after_entry": 1 if pre.index.max() >= entry_ts else 0,
            })
    return pd.DataFrame(rows)


def print_profile(df: pd.DataFrame, title: str) -> None:
    print(f"\n=== {title} ===")
    if df.empty:
        print("no trades")
        return
    st = stats(df)
    print(
        f"trades={st['n']} pnl=${st['pnl']:,.0f} pf={st['pf']:.2f} exp=${st['exp']:.2f} "
        f"outside_exit_bar={int(df['outside_exit_bar'].sum())} "
        f"outside_entry_bar={int(df['outside_entry_bar'].sum())} "
        f"signal_after_entry={int(df['signal_after_entry'].sum())}"
    )
    for col in ["mae_dollars", "mae_atr", "mfe_dollars", "mfe_atr"]:
        q = df[col].quantile([0.5, 0.75, 0.9, 0.95, 0.99])
        print(f"{col:<12} p50={q.loc[0.5]:8.2f} p75={q.loc[0.75]:8.2f} p90={q.loc[0.9]:8.2f} p95={q.loc[0.95]:8.2f} p99={q.loc[0.99]:8.2f}")
    print("-- by instrument --")
    for inst, g in df.groupby("inst"):
        gs = stats(g)
        print(f"  {inst:<4} n={gs['n']:4d} pnl=${gs['pnl']:8,.0f} pf={gs['pf']:5.2f} "
              f"mae_atr_p95={g['mae_atr'].quantile(0.95):5.2f} mae$_p95={g['mae_dollars'].quantile(0.95):7.0f}")
    print("-- worst 10 by final pnl --")
    cols = ["day", "inst", "pnl", "mae_dollars", "mae_atr", "mfe_dollars", "overnight_ret"]
    for _, r in df.sort_values("pnl").head(10)[cols].iterrows():
        print(f"  {r.day} {r.inst:<4} pnl=${r.pnl:8.0f} mae=${r.mae_dollars:7.0f} maeATR={r.mae_atr:5.2f} mfe=${r.mfe_dollars:7.0f} on={r.overnight_ret:7.3%}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    ap.add_argument("--data-dir-2025", default="data/cache/futures/frozen_2025_sim")
    ap.add_argument("--data-dir-2026", default="data/cache/futures")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end-is", default="2022-12-31")
    ap.add_argument("--hmm-fit-end-oos", default="2024-12-31")
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--instruments", nargs="+", default=["MES", "MNQ", "MYM"])
    ap.add_argument("--min-overnight", type=float, default=-0.010)
    ap.add_argument("--max-overnight", type=float, default=-0.001)
    ap.add_argument("--exit-time", default="15:55")
    ap.add_argument("--out-prefix", default="scratch/calm_neg_overnight_mae_profile")
    ap.add_argument("--calm-days-is", default="scratch/calm_drift_basket_big_is.csv")
    ap.add_argument("--calm-days-2025", default="scratch/calm_drift_basket_big_2025.csv")
    ap.add_argument("--calm-days-2026", default="scratch/calm_drift_basket_big_2026.csv")
    args = ap.parse_args()

    windows = [
        ("is", args.data_dir, "2018-01-01", "2024-12-31", args.hmm_fit_end_is, args.calm_days_is),
        ("2025", args.data_dir_2025, "2025-01-01", "2025-12-31", args.hmm_fit_end_oos, args.calm_days_2025),
        ("2026", args.data_dir_2026, "2026-01-01", "2026-08-19", args.hmm_fit_end_oos, args.calm_days_2026),
    ]
    for name, data_dir, start, end, fit_end, calm_csv in windows:
        df = run_window(args, data_dir, start, end, fit_end, calm_csv)
        path = f"{args.out_prefix}_{name}.csv"
        df.to_csv(path, index=False)
        print(f"wrote {path} rows={len(df)}")
        print_profile(df, name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
