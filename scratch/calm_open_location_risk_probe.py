from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import daily_atr_series, load_parquet
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket


AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "days": 0, "net": 0.0, "pf": 0.0, "avg": 0.0, "maxdd": 0.0}
    pnl = df["pnl"].astype(float)
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    return {
        "n": int(len(df)),
        "days": int(df["day"].nunique()),
        "net": float(pnl.sum()),
        "pf": gw / gl if gl else math.inf,
        "avg": float(pnl.mean()),
        "maxdd": float((eq.cummax() - eq).max()) if len(eq) else 0.0,
    }


def price_inside(price: float, row: pd.Series) -> bool:
    px = float(price)
    lo = float(row["low"])
    hi = float(row["high"])
    eps = max(abs(px), abs(lo), abs(hi), 1.0) * 1e-9
    return lo - eps <= px <= hi + eps


def parse_ts(col: pd.Series) -> pd.Series:
    return pd.to_datetime(col, utc=True).dt.tz_convert("America/New_York")


def load_trades(path: str, variant: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in AUDIT_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing audit columns: {missing}")
    if int(df[AUDIT_COLS].sum().sum()) != 0:
        raise ValueError(f"{path} audit failed: {df[AUDIT_COLS].sum().to_dict()}")
    df = df[df["variant"] == variant].copy()
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    df["entry_time"] = parse_ts(df["entry_time"])
    df["exit_time"] = parse_ts(df["exit_time"])
    return df


def replay_window(trades: pd.DataFrame, data_dir: str, slippage_ticks: float) -> pd.DataFrame:
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=slippage_ticks).items()}
    rows = []
    for inst, g in trades.groupby("inst"):
        df = load_parquet(str(Path(data_dir) / data_filename(BASKET[inst])))
        start = g["entry_time"].min() - pd.Timedelta(days=2)
        end = g["exit_time"].max() + pd.Timedelta(days=1)
        df = df[(df.index >= start) & (df.index <= end)]
        atr = daily_atr_series(df)
        pv = BASKET[inst].point_value
        cost = costs[inst]
        for _, r in g.iterrows():
            entry_ts = r["entry_time"]
            exit_ts = r["exit_time"]
            day = pd.Timestamp(r["day"]).normalize()
            entry = float(r["entry"])
            path = df[(df.index > entry_ts) & (df.index <= exit_ts)]
            if path.empty:
                continue
            scheduled_bar = path.loc[exit_ts] if exit_ts in path.index else path.iloc[-1]
            scheduled_exit = float(scheduled_bar["open"])
            av = atr.asof(day)
            if av is None or pd.isna(av):
                av = float(atr.median())
            mae_pts = max(0.0, entry - float(path["low"].min()))
            mfe_pts = max(0.0, float(path["high"].max()) - entry)
            for name, mult in [("nostop", None), ("stop15atr", 1.5), ("stop20atr", 2.0)]:
                exit_px = scheduled_exit
                final_ts = exit_ts
                reason = "time"
                outside = 0 if price_inside(exit_px, scheduled_bar) else 1
                if mult is not None:
                    stop_px = entry - float(av) * mult
                    hit = path[path["low"] <= stop_px]
                    if not hit.empty:
                        final_ts = hit.index[0]
                        bar = hit.iloc[0]
                        exit_px = stop_px if price_inside(stop_px, bar) else float(bar["open"])
                        reason = "stop"
                        outside = 0 if price_inside(exit_px, bar) else 1
                rows.append(
                    {
                        "variant": f"{r['variant']}_{name}",
                        "base_variant": r["variant"],
                        "inst": inst,
                        "direction": "LONG",
                        "day": day.date().isoformat(),
                        "year": int(day.year),
                        "entry_time": entry_ts,
                        "exit_time": final_ts,
                        "entry": entry,
                        "exit": exit_px,
                        "pnl": (exit_px - entry) * pv - cost,
                        "exit_reason": reason,
                        "atr": float(av),
                        "mae_pts": mae_pts,
                        "mfe_pts": mfe_pts,
                        "mae_atr": mae_pts / float(av) if av else np.nan,
                        "mfe_atr": mfe_pts / float(av) if av else np.nan,
                        "outside_exit_bar": outside,
                        "outside_entry_bar": int(r["outside_entry_bar"]),
                        "signal_after_entry": int(r["signal_after_entry"]),
                    }
                )
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, window: str) -> pd.DataFrame:
    rows = []
    for variant, g in df.groupby("variant"):
        st = stats(g)
        by_inst = g.groupby("inst")["pnl"].sum()
        rows.append(
            {
                "window": window,
                "variant": variant,
                **st,
                "stops": int((g["exit_reason"] == "stop").sum()),
                "pos_inst": int((by_inst > 0).sum()),
                "mae_atr_p50": float(g["mae_atr"].median()),
                "mae_atr_p90": float(g["mae_atr"].quantile(0.90)),
                "mae_atr_p95": float(g["mae_atr"].quantile(0.95)),
                "mfe_atr_p50": float(g["mfe_atr"].median()),
                "outside_exit_bar": int(g["outside_exit_bar"].sum()),
                "outside_entry_bar": int(g["outside_entry_bar"].sum()),
                "signal_after_entry": int(g["signal_after_entry"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["net", "pf"], ascending=False)


def print_summary(summary: pd.DataFrame, title: str) -> None:
    print(f"\n=== {title} ===")
    for _, r in summary.iterrows():
        print(
            f"{r['variant']:<58} n={int(r['n']):>4} net=${r['net']:>8,.0f} "
            f"pf={r['pf']:>5.2f} avg=${r['avg']:>7.2f} dd=${r['maxdd']:>7,.0f} "
            f"stops={int(r['stops']):>3} posI={int(r['pos_inst'])} "
            f"maeATR p50/p90/p95={r['mae_atr_p50']:.2f}/{r['mae_atr_p90']:.2f}/{r['mae_atr_p95']:.2f} "
            f"audit={int(r['outside_exit_bar'])}/{int(r['outside_entry_bar'])}/{int(r['signal_after_entry'])}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="openloc_lower_third_long_e1000_x1555")
    ap.add_argument("--is-trades", default="scratch/calm_open_location_drift_delay_sensitivity_is.csv")
    ap.add_argument("--oos-2025", default="scratch/calm_open_location_drift_delay_sensitivity_2025.csv")
    ap.add_argument("--oos-2026", default="scratch/calm_open_location_drift_delay_sensitivity_2026.csv")
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    ap.add_argument("--data-dir-2025", default="data/cache/futures/frozen_2025_sim")
    ap.add_argument("--data-dir-2026", default="data/cache/futures")
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--out-prefix", default="scratch/calm_open_location_risk_probe")
    args = ap.parse_args()

    windows = [
        ("is", args.is_trades, args.data_dir),
        ("2025", args.oos_2025, args.data_dir_2025),
        ("2026", args.oos_2026, args.data_dir_2026),
    ]
    all_summaries = []
    for window, trade_path, data_dir in windows:
        trades = load_trades(trade_path, args.variant)
        replay = replay_window(trades, data_dir, args.slippage_ticks)
        replay.to_csv(f"{args.out_prefix}_{window}.csv", index=False)
        summary = summarize(replay, window)
        summary.to_csv(f"{args.out_prefix}_{window}_summary.csv", index=False)
        all_summaries.append(summary)
        print_summary(summary, window)

    pooled = pd.concat(
        [
            pd.read_csv(f"{args.out_prefix}_2025.csv"),
            pd.read_csv(f"{args.out_prefix}_2026.csv"),
        ],
        ignore_index=True,
    )
    pooled["day"] = pd.to_datetime(pooled["day"]).dt.normalize()
    pooled_summary = summarize(pooled, "oos_pooled")
    pooled_summary.to_csv(f"{args.out_prefix}_oos_pooled_summary.csv", index=False)
    print_summary(pooled_summary, "2025+2026 pooled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
