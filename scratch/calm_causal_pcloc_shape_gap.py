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


def daily_rth(data_dir: str, inst: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    df = load_parquet(str(Path(data_dir) / data_filename(BASKET[inst])))
    start_tz = (start - pd.Timedelta(days=10)).tz_localize(df.index.tz)
    end_tz = (end + pd.Timedelta(days=1)).tz_localize(df.index.tz)
    df = df[(df.index >= start_tz) & (df.index <= end_tz)]
    rth = df.between_time("09:30", "15:59").copy()
    rth["day"] = pd.to_datetime(rth.index.date)
    rows = []
    for day, g in rth.groupby("day", sort=True):
        if g.empty:
            continue
        # Match the causal excavation convention: only full RTH sessions that
        # have a 15:55 bar can become the prior session for shape/gap features.
        if g[g.index.time >= pd.Timestamp("15:55").time()].empty:
            continue
        o = float(g.iloc[0]["open"])
        h = float(g["high"].max())
        l = float(g["low"].min())
        c = float(g.iloc[-1]["close"])
        rng = h - l
        rows.append(
            {
                "day": pd.Timestamp(day).normalize(),
                "inst": inst,
                "rth_open": o,
                "rth_high": h,
                "rth_low": l,
                "rth_close": c,
                "rth_ret": c / o - 1.0,
                "rth_range_pct": rng / o if o else np.nan,
                "body_to_range": abs(c - o) / rng if rng > 0 else np.nan,
                "close_loc": (c - l) / rng if rng > 0 else np.nan,
            }
        )
    out = pd.DataFrame(rows).sort_values("day")
    prev = out.copy()
    for col in ["rth_open", "rth_high", "rth_low", "rth_close", "rth_ret", "rth_range_pct", "body_to_range", "close_loc"]:
        out[f"prev_{col}"] = prev[col].shift(1)
    out["prev_session_day"] = out["day"].shift(1)
    out["gap_from_prev_rth_close"] = out["rth_open"] / out["prev_rth_close"] - 1.0
    out["open_loc_prev_range"] = (out["rth_open"] - out["prev_rth_low"]) / (out["prev_rth_high"] - out["prev_rth_low"])
    return out


def add_shape_features(trades: pd.DataFrame, data_dir: str) -> pd.DataFrame:
    frames = []
    for inst, g in trades.groupby("inst"):
        feat = daily_rth(data_dir, inst, g["day"].min(), g["day"].max())
        cols = [
            "day",
            "inst",
            "prev_rth_ret",
            "prev_rth_range_pct",
            "prev_body_to_range",
            "prev_close_loc",
            "prev_session_day",
            "gap_from_prev_rth_close",
            "open_loc_prev_range",
        ]
        frames.append(g.merge(feat[cols], on=["day", "inst"], how="left", suffixes=("", "_rth")))
    out = pd.concat(frames, ignore_index=True)
    needed = ["prev_rth_range_pct", "gap_from_prev_rth_close", "open_loc_prev_range"]
    if out[needed].isna().any().any():
        raise ValueError("missing shape/gap features")
    return out


def thresholds(is_df: pd.DataFrame) -> dict:
    d = is_df[is_df["inst"].isin(["MES", "MNQ"])].copy()
    return {
        "range_p50": float(d["prev_rth_range_pct"].quantile(0.50)),
        "range_p60": float(d["prev_rth_range_pct"].quantile(0.60)),
        "range_p70": float(d["prev_rth_range_pct"].quantile(0.70)),
        "range_p80": float(d["prev_rth_range_pct"].quantile(0.80)),
        "body_p50": float(d["prev_body_to_range"].quantile(0.50)),
        "body_p70": float(d["prev_body_to_range"].quantile(0.70)),
        "gap_p10": float(d["gap_from_prev_rth_close"].quantile(0.10)),
        "gap_p90": float(d["gap_from_prev_rth_close"].quantile(0.90)),
    }


def masks(df: pd.DataFrame, t: dict) -> dict[str, pd.Series]:
    mes_mnq = df["inst"].isin(["MES", "MNQ"])
    gap = df["gap_from_prev_rth_close"]
    openloc = df["open_loc_prev_range"]
    rng = df["prev_rth_range_pct"]
    body = df["prev_body_to_range"]
    prevret = df["prev_rth_ret"]
    inside_open = (openloc >= 0.0) & (openloc <= 1.0)
    small_gap = (gap >= -0.005) & (gap <= 0.005)
    ok_gap = (gap >= -0.010) & (gap <= 0.010)
    not_deep_gap = gap >= -0.010
    not_up_gap = gap <= 0.005
    orderly_down = (prevret < 0.0) & (rng <= t["range_p70"]) & (body <= t["body_p70"])
    trend_down = (prevret < 0.0) & (body >= t["body_p50"])
    return {
        "mes_mnq": mes_mnq,
        "mes_mnq_inside_open": mes_mnq & inside_open,
        "mes_mnq_small_gap": mes_mnq & small_gap,
        "mes_mnq_ok_gap": mes_mnq & ok_gap,
        "mes_mnq_not_deep_gap": mes_mnq & not_deep_gap,
        "mes_mnq_not_up_gap": mes_mnq & not_up_gap,
        "mes_mnq_range_le60": mes_mnq & (rng <= t["range_p60"]),
        "mes_mnq_range_le70": mes_mnq & (rng <= t["range_p70"]),
        "mes_mnq_range_le80": mes_mnq & (rng <= t["range_p80"]),
        "mes_mnq_body_le70": mes_mnq & (body <= t["body_p70"]),
        "mes_mnq_trend_down": mes_mnq & trend_down,
        "mes_mnq_orderly_down": mes_mnq & orderly_down,
        "mes_mnq_inside_ok_gap": mes_mnq & inside_open & ok_gap,
        "mes_mnq_inside_not_deep": mes_mnq & inside_open & not_deep_gap,
        "mes_mnq_range70_ok_gap": mes_mnq & (rng <= t["range_p70"]) & ok_gap,
        "mes_mnq_orderly_inside": mes_mnq & orderly_down & inside_open,
        "mes_mnq_trend_inside": mes_mnq & trend_down & inside_open,
        "mes_mnq_no_gap_extreme": mes_mnq & (gap >= t["gap_p10"]) & (gap <= t["gap_p90"]),
    }


def summarize(df: pd.DataFrame, window: str, t: dict) -> pd.DataFrame:
    rows = []
    for name, mask in masks(df, t).items():
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
                "audit": int(g[AUDIT_COLS].sum().sum()) if not g.empty else 0,
                "gap_med": float(g["gap_from_prev_rth_close"].median()) if not g.empty else np.nan,
                "prev_range_med": float(g["prev_rth_range_pct"].median()) if not g.empty else np.nan,
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
            f"posI={int(r['pos_inst'])} MES/MNQ=${r['mes_net']:.0f}/{r['mnq_net']:.0f}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--is-trades", default="scratch/calm_causal_lag1_excavation_is.csv")
    ap.add_argument("--oos-2025", default="scratch/calm_causal_lag1_excavation_2025.csv")
    ap.add_argument("--oos-2026", default="scratch/calm_causal_lag1_excavation_2026.csv")
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    ap.add_argument("--data-dir-2025", default="data/cache/futures/frozen_2025_sim")
    ap.add_argument("--data-dir-2026", default="data/cache/futures")
    ap.add_argument("--out-prefix", default="scratch/calm_causal_pcloc_shape_gap")
    ap.add_argument("--select-limit", type=int, default=8)
    ap.add_argument("--bootstrap-iters", type=int, default=5000)
    args = ap.parse_args()

    is_df = add_shape_features(load_trades(args.is_trades), args.data_dir)
    t = thresholds(is_df)
    pd.DataFrame([t]).to_csv(f"{args.out_prefix}_thresholds.csv", index=False)
    is_df.to_csv(f"{args.out_prefix}_is.csv", index=False)
    s_is = summarize(is_df, "is", t)
    s_is.to_csv(f"{args.out_prefix}_is_summary.csv", index=False)
    print("thresholds=" + ", ".join(f"{k}={v:.6f}" for k, v in t.items()))
    print_summary("IS shape/gap", s_is)
    selected = select(s_is, args.select_limit)
    print("\nselected_before_oos=" + (",".join(selected) if selected else "NONE"))
    if not selected:
        return 0

    o25 = add_shape_features(load_trades(args.oos_2025), args.data_dir_2025)
    o26 = add_shape_features(load_trades(args.oos_2026), args.data_dir_2026)
    pooled = pd.concat([o25, o26], ignore_index=True)
    for name, df in [("2025", o25), ("2026_sanity", o26), ("pooled_sanity", pooled)]:
        df.to_csv(f"{args.out_prefix}_{name}.csv", index=False)
        s = summarize(df, name, t)
        s.to_csv(f"{args.out_prefix}_{name}_summary.csv", index=False)
        print_summary(name, s, selected)

    rng = np.random.default_rng(20260821)
    rows = []
    for filt in selected:
        for name, df in [("2025", o25), ("pooled_sanity", pooled)]:
            g = df[masks(df, t)[filt].fillna(False)]
            rows.append({"window": name, "filter": filt, **stats(g), **bootstrap(g, args.bootstrap_iters, rng)})
    boot = pd.DataFrame(rows).sort_values(["window", "net"], ascending=[True, False])
    boot.to_csv(f"{args.out_prefix}_bootstrap.csv", index=False)
    print("\n=== Bootstrap ===")
    print(boot.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
