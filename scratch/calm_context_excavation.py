from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, load_parquet
from futures.basket import BASKET, data_filename


WINDOWS = {
    "is": ("scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_is.csv", "data/cache/futures/frozen_sim"),
    "2025": ("scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_2025.csv", "data/cache/futures/frozen_2025_sim"),
    "2026": ("scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_2026.csv", "data/cache/futures"),
}
RAW_VARIANT = "on_neg_fade_raw_x1555"
AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]


def trading_day_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    local = idx.normalize()
    evening = np.array([t >= pd.Timestamp("18:00").time() for t in idx.time])
    out = np.where(evening, local + pd.Timedelta(days=1), local)
    return pd.DatetimeIndex(out).tz_localize(None).normalize()


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"trades": 0, "days": 0, "net": 0.0, "pf": 0.0, "avg": 0.0, "maxdd": 0.0}
    pnl = df["pnl"].astype(float)
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    return {
        "trades": int(len(df)),
        "days": int(df["day"].nunique()),
        "net": float(pnl.sum()),
        "pf": gw / gl if gl else math.inf,
        "avg": float(pnl.mean()),
        "maxdd": float((eq.cummax() - eq).max()) if len(eq) else 0.0,
    }


def day_bootstrap(df: pd.DataFrame, iters: int, rng: np.random.Generator) -> dict:
    if df.empty:
        return {"p_pos": 0.0, "p05": 0.0, "p50": 0.0, "p95": 0.0}
    daily = df.groupby("day")["pnl"].sum().to_numpy(dtype=float)
    draws = rng.choice(daily, size=(iters, len(daily)), replace=True).sum(axis=1)
    return {
        "p_pos": float((draws > 0).mean()),
        "p05": float(np.percentile(draws, 5)),
        "p50": float(np.percentile(draws, 50)),
        "p95": float(np.percentile(draws, 95)),
    }


def meaningful_years(df: pd.DataFrame, min_trades: int = 20, min_days: int = 10) -> tuple[int, int]:
    if df.empty:
        return 0, 0
    y = df.groupby("year").agg(trades=("pnl", "size"), days=("day", "nunique"), net=("pnl", "sum"))
    y = y[(y["trades"] >= min_trades) | (y["days"] >= min_days)]
    return int((y["net"] > 0).sum()), int(len(y))


def load_raw_trades(path: str, window: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in AUDIT_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing audit columns: {missing}")
    audit = df[AUDIT_COLS].sum()
    if int(audit.sum()) != 0:
        raise ValueError(f"{path} audit failed: {audit.to_dict()}")
    df = df[df["variant"] == RAW_VARIANT].copy()
    df["window"] = window
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    return df


def rth_daily_context(data_dir: str, inst: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    df = load_parquet(str(Path(data_dir) / data_filename(BASKET[inst])))
    ss = (start - pd.Timedelta(days=10)).tz_localize(df.index.tz)
    ee = (end + pd.Timedelta(days=2)).tz_localize(df.index.tz)
    df = df[(df.index >= ss) & (df.index <= ee)].copy()
    rth = df.between_time("09:30", "15:59").copy()
    rth["day"] = trading_day_index(rth.index)
    grouped = rth.groupby("day", sort=True)
    out = grouped.agg(
        rth_open=("open", "first"),
        rth_high=("high", "max"),
        rth_low=("low", "min"),
        rth_close=("close", "last"),
        bars=("open", "size"),
    ).reset_index()
    out = out[out["bars"] >= 160].drop(columns=["bars"])
    out["inst"] = inst
    prev = out[["rth_open", "rth_high", "rth_low", "rth_close"]].shift(1)
    out["prev_open"] = prev["rth_open"]
    out["prev_high"] = prev["rth_high"]
    out["prev_low"] = prev["rth_low"]
    out["prev_close"] = prev["rth_close"]
    out["prev_ret"] = out["prev_close"] / out["prev_open"] - 1.0
    out["prev_range_pct"] = (out["prev_high"] - out["prev_low"]) / out["prev_close"]
    out["prev_range_med20"] = out["prev_range_pct"].rolling(20, min_periods=10).median().shift(1)
    out["open_gap_prev_close"] = out["rth_open"] / out["prev_close"] - 1.0
    denom = (out["prev_high"] - out["prev_low"]).replace(0, np.nan)
    out["open_loc_prev_range"] = (out["rth_open"] - out["prev_low"]) / denom
    return out


def spy_context(path: str) -> pd.DataFrame:
    close = benchmark_daily(path).sort_index()
    idx = pd.DatetimeIndex(close.index)
    close.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    ret = close.pct_change()
    out = pd.DataFrame(index=close.index)
    out["day"] = out.index
    out["spy_close_d1"] = close.shift(1)
    out["spy_sma50_d1"] = close.rolling(50).mean().shift(1)
    out["spy_above50_d1"] = out["spy_close_d1"] > out["spy_sma50_d1"]
    out["spy_rv20_d1"] = (ret.rolling(20).std() * math.sqrt(252)).shift(1)
    return out.reset_index(drop=True)


def attach_context(trades: pd.DataFrame, data_dir: str, spy: pd.DataFrame) -> pd.DataFrame:
    frames = []
    start = trades["day"].min()
    end = trades["day"].max()
    for inst, g in trades.groupby("inst"):
        ctx = rth_daily_context(data_dir, inst, start, end)
        frames.append(g.merge(ctx, on=["day", "inst"], how="left"))
    out = pd.concat(frames, ignore_index=True)
    out = out.merge(spy, on="day", how="left")
    out["prior_up"] = out["prev_ret"] > 0
    out["prior_down"] = out["prev_ret"] <= 0
    out["open_below_prev_low"] = out["rth_open"] < out["prev_low"]
    out["open_inside_prev_range"] = (out["rth_open"] >= out["prev_low"]) & (out["rth_open"] <= out["prev_high"])
    out["open_above_prev_close"] = out["rth_open"] > out["prev_close"]
    out["open_lower_third"] = out["open_loc_prev_range"] <= 1 / 3
    out["open_mid_third"] = (out["open_loc_prev_range"] > 1 / 3) & (out["open_loc_prev_range"] <= 2 / 3)
    out["open_upper_third"] = out["open_loc_prev_range"] > 2 / 3
    out["prior_compress20"] = out["prev_range_pct"] <= out["prev_range_med20"]
    out["prior_expand20"] = out["prev_range_pct"] > out["prev_range_med20"]
    out["spy_above50"] = out["spy_above50_d1"] == True
    out["spy_below50"] = out["spy_above50_d1"] == False
    out["spy_rv20_le20"] = out["spy_rv20_d1"] <= 0.20
    out["spy_rv20_gt20"] = out["spy_rv20_d1"] > 0.20
    out["bucket_m005_m002"] = (out["overnight_ret"] > -0.005) & (out["overnight_ret"] <= -0.002)
    return out


def variant_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "all_raw_neg": pd.Series(True, index=df.index),
        "prior_up": df["prior_up"],
        "prior_down": df["prior_down"],
        "open_below_prev_low": df["open_below_prev_low"],
        "open_inside_prev_range": df["open_inside_prev_range"],
        "open_lower_third": df["open_lower_third"],
        "open_mid_third": df["open_mid_third"],
        "open_upper_third": df["open_upper_third"],
        "prior_compress20": df["prior_compress20"],
        "prior_expand20": df["prior_expand20"],
        "spy_above50": df["spy_above50"],
        "spy_below50": df["spy_below50"],
        "spy_rv20_le20": df["spy_rv20_le20"],
        "spy_rv20_gt20": df["spy_rv20_gt20"],
        "prior_up_open_lower": df["prior_up"] & df["open_lower_third"],
        "prior_down_open_lower": df["prior_down"] & df["open_lower_third"],
        "inside_prior_up": df["open_inside_prev_range"] & df["prior_up"],
        "inside_prior_down": df["open_inside_prev_range"] & df["prior_down"],
        "compress_open_lower": df["prior_compress20"] & df["open_lower_third"],
        "expand_open_lower": df["prior_expand20"] & df["open_lower_third"],
        "seed_m005_m002": df["bucket_m005_m002"],
        "seed_m005_m002_prior_up": df["bucket_m005_m002"] & df["prior_up"],
        "seed_m005_m002_prior_down": df["bucket_m005_m002"] & df["prior_down"],
        "seed_m005_m002_inside": df["bucket_m005_m002"] & df["open_inside_prev_range"],
    }


def build_variant_rows(df: pd.DataFrame, window: str, iters: int, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for variant, mask in variant_masks(df).items():
        g = df[mask.fillna(False)].copy()
        st = stats(g)
        bs = day_bootstrap(g, iters, rng)
        py, my = meaningful_years(g)
        by_inst = g.groupby("inst")["pnl"].sum() if not g.empty else pd.Series(dtype=float)
        rows.append({
            "window": window,
            "variant": variant,
            **st,
            "p_pos": bs["p_pos"],
            "ci05": bs["p05"],
            "ci50": bs["p50"],
            "ci95": bs["p95"],
            "pos_meaningful_years": py,
            "meaningful_years": my,
            "pos_inst": int((by_inst > 0).sum()),
            "mes_net": float(by_inst.get("MES", 0.0)),
            "mnq_net": float(by_inst.get("MNQ", 0.0)),
            "mym_net": float(by_inst.get("MYM", 0.0)),
        })
    return pd.DataFrame(rows)


def select_is(summary: pd.DataFrame, limit: int) -> list[str]:
    is_rows = summary[summary["window"] == "is"].copy()
    eligible = is_rows[
        (is_rows["trades"] >= 250)
        & (is_rows["net"] >= 5_000)
        & (is_rows["pf"] >= 1.20)
        & (is_rows["pos_meaningful_years"] >= 5)
        & (is_rows["pos_inst"] >= 2)
    ].copy()
    eligible = eligible.sort_values(["net", "pf", "trades"], ascending=False)
    return eligible["variant"].head(limit).tolist()


def print_summary(summary: pd.DataFrame, variants: list[str]) -> None:
    for window in ["is", "2025", "2026", "oos_pooled"]:
        print(f"\n=== {window} selected/context ===")
        tbl = summary[(summary["window"] == window) & (summary["variant"].isin(variants))].sort_values("net", ascending=False)
        if tbl.empty:
            print("no rows")
            continue
        for _, r in tbl.iterrows():
            print(
                f"{r['variant']:<28} n={int(r['trades']):>4} days={int(r['days']):>3} "
                f"net=${r['net']:>8,.0f} pf={r['pf']:>5.2f} avg=${r['avg']:>6.2f} "
                f"p_pos={r['p_pos']:>5.3f} ci05/95=${r['ci05']:>7,.0f}/${r['ci95']:>7,.0f} "
                f"posY={int(r['pos_meaningful_years'])}/{int(r['meaningful_years'])} posI={int(r['pos_inst'])}"
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--bootstrap-iters", type=int, default=3000)
    ap.add_argument("--select-limit", type=int, default=6)
    ap.add_argument("--out-prefix", default="scratch/calm_context_excavation")
    args = ap.parse_args()

    rng = np.random.default_rng(20260821)
    spy = spy_context(args.regime_csv)
    window_frames = []
    summaries = []
    for window, (csv_path, data_dir) in WINDOWS.items():
        print(f"loading {window}", flush=True)
        raw = load_raw_trades(csv_path, window)
        ctx = attach_context(raw, data_dir, spy)
        window_frames.append(ctx)
        summaries.append(build_variant_rows(ctx, window, args.bootstrap_iters, rng))
    all_ctx = pd.concat(window_frames, ignore_index=True)
    oos = all_ctx[all_ctx["window"].isin(["2025", "2026"])].copy()
    summaries.append(build_variant_rows(oos, "oos_pooled", args.bootstrap_iters, rng))
    summary = pd.concat(summaries, ignore_index=True)

    selected = select_is(summary, args.select_limit)
    print("\n=== IS selected before OOS ===")
    print(",".join(selected) if selected else "NONE")
    display = list(dict.fromkeys(selected + ["all_raw_neg", "seed_m005_m002"]))
    print_summary(summary, display)

    summary_path = f"{args.out_prefix}_summary.csv"
    trades_path = f"{args.out_prefix}_trades.csv"
    summary.to_csv(summary_path, index=False)
    all_ctx.to_csv(trades_path, index=False)
    print(f"\nwrote {summary_path}")
    print(f"wrote {trades_path}")

    print("\n=== verdict ===")
    survivors = []
    for v in selected:
        isr = summary[(summary["window"] == "is") & (summary["variant"] == v)].iloc[0]
        oosr = summary[(summary["window"] == "oos_pooled") & (summary["variant"] == v)].iloc[0]
        if oosr["net"] > 0 and oosr["pf"] >= 1.10 and oosr["p_pos"] >= 0.80 and oosr["pos_inst"] >= 2:
            survivors.append(v)
            print(f"paper_seed={v} is_net=${isr['net']:,.0f} oos_net=${oosr['net']:,.0f} oos_p={oosr['p_pos']:.3f}")
        else:
            print(f"reject_oos={v} is_net=${isr['net']:,.0f} oos_net=${oosr['net']:,.0f} oos_p={oosr['p_pos']:.3f}")
    if not survivors:
        print("survivors=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
