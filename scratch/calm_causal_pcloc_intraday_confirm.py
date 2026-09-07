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


AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]
BASE = "lag1calm_pcloc_bottom_down_long_e1000_x1555"


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


def add_first30_features(trades: pd.DataFrame, data_dir: str) -> pd.DataFrame:
    frames = []
    for inst, g in trades.groupby("inst"):
        g = g.copy()
        g["_entry_by_day"] = g.groupby("day")["entry"].transform("first")
        df = load_parquet(str(Path(data_dir) / data_filename(BASKET[inst])))
        start = g["day"].min() - pd.Timedelta(days=1)
        end = g["day"].max() + pd.Timedelta(days=1)
        df = df[(df.index >= start.tz_localize(df.index.tz)) & (df.index <= end.tz_localize(df.index.tz))]
        rth = df.between_time("09:30", "15:59").copy()
        rth["day"] = pd.to_datetime(rth.index.date)
        pre10_by_day = {
            pd.Timestamp(day).normalize(): day_df.between_time("09:30", "09:59")
            for day, day_df in rth.groupby("day", sort=False)
        }
        entry_by_day = g.drop_duplicates("day").set_index("day")["_entry_by_day"]
        rows = []
        for day in sorted(g["day"].unique()):
            d = pd.Timestamp(day).normalize()
            pre_entry = pre10_by_day.get(d)
            if pre_entry is None or pre_entry.empty:
                continue
            p0930 = float(pre_entry.iloc[0]["open"])
            hi = float(pre_entry["high"].max())
            lo = float(pre_entry["low"].min())
            c0959 = float(pre_entry["close"].iloc[-1])
            entry = float(entry_by_day.loc[d])
            rows.append(
                {
                    "day": d,
                    "inst": inst,
                    "p0930": p0930,
                    "pre10_high": hi,
                    "pre10_low": lo,
                    "pre10_close": c0959,
                    "pre10_ret": c0959 / p0930 - 1.0,
                    "entry_vs_open": entry / p0930 - 1.0,
                    "pre10_range_pct": (hi - lo) / p0930,
                    "entry_loc_pre10": (entry - lo) / (hi - lo) if hi > lo else np.nan,
                }
            )
        feat = pd.DataFrame(rows)
        frames.append(g.drop(columns=["_entry_by_day"]).merge(feat, on=["day", "inst"], how="left"))
    return pd.concat(frames, ignore_index=True)


def masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    all_true = pd.Series(True, index=df.index)
    no_mym = df["inst"].isin(["MES", "MNQ"])
    ge_open = df["entry_vs_open"] >= 0.0
    not_weak = df["entry_vs_open"] >= -0.001
    upper_half = df["entry_loc_pre10"] >= 0.50
    range005 = df["pre10_range_pct"] <= 0.005
    range0075 = df["pre10_range_pct"] <= 0.0075
    return {
        "base_all": all_true,
        "no_mym": no_mym,
        "ge_open": ge_open,
        "not_weak": not_weak,
        "upper_half": upper_half,
        "range005": range005,
        "range0075": range0075,
        "no_mym_ge_open": no_mym & ge_open,
        "no_mym_not_weak": no_mym & not_weak,
        "no_mym_upper_half": no_mym & upper_half,
        "no_mym_range005": no_mym & range005,
        "no_mym_range0075": no_mym & range0075,
        "no_mym_not_weak_range0075": no_mym & not_weak & range0075,
        "no_mym_upper_half_range0075": no_mym & upper_half & range0075,
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
    for _, r in tbl.head(30).iterrows():
        print(
            f"{r['filter']:<28} n={int(r['n']):>4} days={int(r['days']):>3} "
            f"net=${r['net']:>8,.0f} pf={r['pf']:>5.2f} avg=${r['avg']:>7.2f} "
            f"dd=${r['maxdd']:>7,.0f} posY={int(r['pos_years'])}/{int(r['years'])} "
            f"posI={int(r['pos_inst'])} MES/MNQ/MYM=${r['mes_net']:.0f}/{r['mnq_net']:.0f}/{r['mym_net']:.0f}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--is-trades", default="scratch/calm_causal_lag1_excavation_is.csv")
    ap.add_argument("--oos-2025", default="scratch/calm_causal_lag1_excavation_2025.csv")
    ap.add_argument("--oos-2026", default="scratch/calm_causal_lag1_excavation_2026.csv")
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    ap.add_argument("--data-dir-2025", default="data/cache/futures/frozen_2025_sim")
    ap.add_argument("--data-dir-2026", default="data/cache/futures")
    ap.add_argument("--out-prefix", default="scratch/calm_causal_pcloc_intraday_confirm")
    ap.add_argument("--select-limit", type=int, default=6)
    ap.add_argument("--bootstrap-iters", type=int, default=5000)
    args = ap.parse_args()

    is_df = add_first30_features(load_trades(args.is_trades), args.data_dir)
    is_df.to_csv(f"{args.out_prefix}_is.csv", index=False)
    s_is = summarize(is_df, "is")
    s_is.to_csv(f"{args.out_prefix}_is_summary.csv", index=False)
    print_summary("IS first-30 confirmation", s_is)
    selected = select(s_is, args.select_limit)
    print("\nselected_before_oos=" + (",".join(selected) if selected else "NONE"))
    if not selected:
        return 0

    o25 = add_first30_features(load_trades(args.oos_2025), args.data_dir_2025)
    o26 = add_first30_features(load_trades(args.oos_2026), args.data_dir_2026)
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
