from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import load_parquet
from futures.basket import BASKET, data_filename


BASE = "lag1calm_pcloc_bottom_down_long_e1000_x1555"
AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]


def load_trades(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in AUDIT_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing audit columns: {missing}")
    df = df[df["variant"] == BASE].copy()
    if int(df[AUDIT_COLS].sum().sum()) != 0:
        raise ValueError(f"{path} audit failed")
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    return df


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


def daily_pre10_features(data_dir: str, inst: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    df = load_parquet(str(Path(data_dir) / data_filename(BASKET[inst])))
    start_tz = (start - pd.Timedelta(days=90)).tz_localize(df.index.tz)
    end_tz = (end + pd.Timedelta(days=1)).tz_localize(df.index.tz)
    df = df[(df.index >= start_tz) & (df.index <= end_tz)]
    rth = df.between_time("09:30", "15:59").copy()
    rth["day"] = pd.to_datetime(rth.index.date)
    rows = []
    for day, day_df in rth.groupby("day", sort=True):
        pre = day_df.between_time("09:30", "09:59")
        if pre.empty:
            continue
        p0930 = float(pre.iloc[0]["open"])
        hi = float(pre["high"].max())
        lo = float(pre["low"].min())
        c0959 = float(pre["close"].iloc[-1])
        rows.append(
            {
                "day": pd.Timestamp(day).normalize(),
                "inst": inst,
                "pre10_volume": float(pre["volume"].sum()),
                "pre10_range_pct": (hi - lo) / p0930,
                "pre10_ret": c0959 / p0930 - 1.0,
                "pre10_close": c0959,
                "pre10_high": hi,
                "pre10_low": lo,
                "p0930": p0930,
            }
        )
    out = pd.DataFrame(rows).sort_values("day")
    # Strictly causal volume baseline: prior sessions only.
    out["vol_med20"] = out["pre10_volume"].rolling(20, min_periods=10).median().shift(1)
    out["vol_med60"] = out["pre10_volume"].rolling(60, min_periods=20).median().shift(1)
    out["vol_mean20"] = out["pre10_volume"].rolling(20, min_periods=10).mean().shift(1)
    out["vol_mean60"] = out["pre10_volume"].rolling(60, min_periods=20).mean().shift(1)
    out["vol_ratio20"] = out["pre10_volume"] / out["vol_med20"]
    out["vol_ratio60"] = out["pre10_volume"] / out["vol_med60"]
    return out


def add_volume_features(trades: pd.DataFrame, data_dir: str) -> pd.DataFrame:
    frames = []
    for inst, g in trades.groupby("inst"):
        g = g.copy()
        feat = daily_pre10_features(data_dir, inst, g["day"].min(), g["day"].max())
        m = g.merge(feat, on=["day", "inst"], how="left")
        m["entry_loc_pre10"] = np.where(
            m["pre10_high"] > m["pre10_low"],
            (m["entry"].astype(float) - m["pre10_low"]) / (m["pre10_high"] - m["pre10_low"]),
            np.nan,
        )
        m["entry_vs_open"] = m["entry"].astype(float) / m["p0930"] - 1.0
        frames.append(m)
    return pd.concat(frames, ignore_index=True)


def masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    all_true = pd.Series(True, index=df.index)
    mes_mnq = df["inst"].isin(["MES", "MNQ"])
    low60 = df["vol_ratio60"] <= 0.80
    normal60 = df["vol_ratio60"] <= 1.00
    cap120 = df["vol_ratio60"] <= 1.20
    cap150 = df["vol_ratio60"] <= 1.50
    high120 = df["vol_ratio60"] >= 1.20
    high150 = df["vol_ratio60"] >= 1.50
    upper = df["entry_loc_pre10"] >= 0.50
    not_weak = df["entry_vs_open"] >= -0.001
    quiet_range = df["pre10_range_pct"] <= 0.0075
    tight_range = df["pre10_range_pct"] <= 0.005
    return {
        "base_all": all_true,
        "mes_mnq": mes_mnq,
        "mes_mnq_vol60_le080": mes_mnq & low60,
        "mes_mnq_vol60_le100": mes_mnq & normal60,
        "mes_mnq_vol60_le120": mes_mnq & cap120,
        "mes_mnq_vol60_le150": mes_mnq & cap150,
        "mes_mnq_vol60_080_120": mes_mnq & (df["vol_ratio60"] >= 0.80) & cap120,
        "mes_mnq_vol60_080_150": mes_mnq & (df["vol_ratio60"] >= 0.80) & cap150,
        "mes_mnq_quiet_vol": mes_mnq & normal60 & quiet_range,
        "mes_mnq_tight_vol": mes_mnq & normal60 & tight_range,
        "mes_mnq_normal_notweak": mes_mnq & normal60 & not_weak,
        "mes_mnq_normal_upper": mes_mnq & normal60 & upper,
        "mes_mnq_spike_upper": mes_mnq & high120 & upper,
        "mes_mnq_bigspike_upper": mes_mnq & high150 & upper,
        "mes_mnq_spike_notweak": mes_mnq & high120 & not_weak,
    }


def summarize(df: pd.DataFrame, window: str) -> pd.DataFrame:
    rows = []
    for name, mask in masks(df).items():
        g = df[mask.fillna(False)].copy()
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum() if not g.empty else pd.Series(dtype=float)
        by_inst = g.groupby("inst")["pnl"].sum() if not g.empty else pd.Series(dtype=float)
        rows.append(
            {
                "window": window,
                "filter": name,
                **st,
                "pos_years": int((by_year > 0).sum()),
                "years": int(len(by_year)),
                "pos_inst": int((by_inst > 0).sum()),
                "top_year_share": float(by_year.max() / st["net"]) if st["net"] > 0 and not by_year.empty else 1.0,
                "mes_net": float(by_inst.get("MES", 0.0)),
                "mnq_net": float(by_inst.get("MNQ", 0.0)),
                "mym_net": float(by_inst.get("MYM", 0.0)),
                "vol_ratio60_med": float(g["vol_ratio60"].median()) if not g.empty else np.nan,
                "audit": int(g[AUDIT_COLS].sum().sum()) if not g.empty else 0,
            }
        )
    return pd.DataFrame(rows).sort_values(["net", "pf"], ascending=False)


def select(summary: pd.DataFrame, limit: int) -> list[str]:
    keep = summary[
        (summary["n"] >= 200)
        & (summary["net"] >= 5_000)
        & (summary["pf"] >= 1.15)
        & (summary["pos_years"] >= 5)
        & (summary["pos_inst"] >= 2)
        & (summary["top_year_share"] <= 0.75)
        & (summary["audit"] == 0)
    ]
    return keep.sort_values(["net", "pf"], ascending=False)["filter"].head(limit).tolist()


def bootstrap(df: pd.DataFrame, iters: int, rng: np.random.Generator) -> dict:
    if df.empty:
        return {"p05": 0.0, "p50": 0.0, "p95": 0.0, "p_pos": 0.0}
    daily = df.groupby("day")["pnl"].sum().to_numpy(dtype=float)
    draws = rng.choice(daily, size=(iters, len(daily)), replace=True).sum(axis=1)
    return {
        "p05": float(np.percentile(draws, 5)),
        "p50": float(np.percentile(draws, 50)),
        "p95": float(np.percentile(draws, 95)),
        "p_pos": float((draws > 0).mean()),
    }


def print_summary(title: str, summary: pd.DataFrame, filters: list[str] | None = None) -> None:
    print(f"\n=== {title} ===")
    tbl = summary if filters is None else summary[summary["filter"].isin(filters)]
    for _, r in tbl.head(40).iterrows():
        print(
            f"{r['filter']:<28} n={int(r['n']):>4} days={int(r['days']):>3} "
            f"net=${r['net']:>8,.0f} pf={r['pf']:>5.2f} avg=${r['avg']:>7.2f} "
            f"dd=${r['maxdd']:>7,.0f} posY={int(r['pos_years'])}/{int(r['years'])} "
            f"posI={int(r['pos_inst'])} MES/MNQ/MYM=${r['mes_net']:.0f}/{r['mnq_net']:.0f}/{r['mym_net']:.0f} "
            f"vol60med={r['vol_ratio60_med']:.2f}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--is-trades", default="scratch/calm_causal_lag1_excavation_is.csv")
    ap.add_argument("--oos-2025", default="scratch/calm_causal_lag1_excavation_2025.csv")
    ap.add_argument("--oos-2026", default="scratch/calm_causal_lag1_excavation_2026.csv")
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    ap.add_argument("--data-dir-2025", default="data/cache/futures/frozen_2025_sim")
    ap.add_argument("--data-dir-2026", default="data/cache/futures")
    ap.add_argument("--out-prefix", default="scratch/calm_causal_pcloc_volume_overlay")
    ap.add_argument("--select-limit", type=int, default=6)
    ap.add_argument("--bootstrap-iters", type=int, default=5000)
    args = ap.parse_args()

    is_df = add_volume_features(load_trades(args.is_trades), args.data_dir)
    is_df.to_csv(f"{args.out_prefix}_is.csv", index=False)
    s_is = summarize(is_df, "is")
    s_is.to_csv(f"{args.out_prefix}_is_summary.csv", index=False)
    print_summary("IS volume overlay", s_is)
    selected = select(s_is, args.select_limit)
    print("\nselected_before_oos=" + (",".join(selected) if selected else "NONE"))
    if not selected:
        return 0

    o25 = add_volume_features(load_trades(args.oos_2025), args.data_dir_2025)
    o26 = add_volume_features(load_trades(args.oos_2026), args.data_dir_2026)
    pooled = pd.concat([o25, o26], ignore_index=True)
    for name, df in [("2025", o25), ("2026", o26), ("oos_pooled", pooled)]:
        df.to_csv(f"{args.out_prefix}_{name}.csv", index=False)
        s = summarize(df, name)
        s.to_csv(f"{args.out_prefix}_{name}_summary.csv", index=False)
        print_summary(name, s, selected)

    rng = np.random.default_rng(20260821)
    rows = []
    for filt in selected:
        g = pooled[masks(pooled)[filt].fillna(False)]
        rows.append({"filter": filt, **stats(g), **bootstrap(g, args.bootstrap_iters, rng)})
    boot = pd.DataFrame(rows).sort_values("net", ascending=False)
    boot.to_csv(f"{args.out_prefix}_oos_bootstrap.csv", index=False)
    print("\n=== OOS bootstrap ===")
    print(boot.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
