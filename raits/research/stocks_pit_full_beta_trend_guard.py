from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_BETA_TREND_GUARD_2026-09-14"
BENCH_DAILY = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SPLIT_OUT = Path(f"{OUT_PREFIX}_SPLITS.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

VARIANTS = [
    {"base": "market_cap_top62_equal_weight", "variant": "top62_vt25_cap250_trail20m5_half", "target_vol": 0.25, "max_exposure": 2.5, "lookback": 20, "threshold": -0.05, "guard_mult": 0.5},
    {"base": "market_cap_top62_equal_weight", "variant": "top62_vt25_cap250_trail60m10_half", "target_vol": 0.25, "max_exposure": 2.5, "lookback": 60, "threshold": -0.10, "guard_mult": 0.5},
    {"base": "market_cap_top62_equal_weight", "variant": "top62_vt20_cap200_trail20m5_half", "target_vol": 0.20, "max_exposure": 2.0, "lookback": 20, "threshold": -0.05, "guard_mult": 0.5},
    {"base": "market_cap_top62_equal_weight", "variant": "top62_vt20_cap200_trail60m10_half", "target_vol": 0.20, "max_exposure": 2.0, "lookback": 60, "threshold": -0.10, "guard_mult": 0.5},
    {"base": "spy_buy_hold", "variant": "spy_vt20_cap200_trail20m5_half", "target_vol": 0.20, "max_exposure": 2.0, "lookback": 20, "threshold": -0.05, "guard_mult": 0.5},
    {"base": "spy_buy_hold", "variant": "spy_vt20_cap200_trail60m10_half", "target_vol": 0.20, "max_exposure": 2.0, "lookback": 60, "threshold": -0.10, "guard_mult": 0.5},
]


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peak = equity.cummax()
    dd = equity - peak
    dd_pct = equity / peak - 1.0
    return float(dd.min()), float(dd_pct.min())


def sharpe(pnl: pd.Series) -> float:
    std = float(pnl.std())
    if std <= 0:
        return float("nan")
    return float(pnl.mean() / std * math.sqrt(252))


def cagr(equity: pd.Series, dates: pd.Series) -> float:
    years = max((dates.max() - dates.min()).days / 365.25, 1e-9)
    return float((equity.iloc[-1] / START_CAPITAL) ** (1.0 / years) - 1.0)


def load_base_daily() -> pd.DataFrame:
    daily = pd.read_csv(BENCH_DAILY, parse_dates=["date"])
    keep = {str(v["base"]) for v in VARIANTS}
    daily = daily[daily["variant"].isin(keep)].copy()
    daily = daily.sort_values(["variant", "date"])
    daily["base_equity_lag"] = daily.groupby("variant")["equity"].shift(1).fillna(START_CAPITAL)
    daily["base_ret"] = daily["daily_pnl"] / daily["base_equity_lag"]
    return daily


def add_periods(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.copy()
    x["year"] = x["date"].dt.year
    x["split"] = np.select(
        [x["year"].le(2021), x["year"].eq(2022), x["year"].ge(2023)],
        ["2018_2021_research", "2022_stress", "2023_2024_touched"],
        default="other",
    )
    return x


def simulate(spec: dict[str, object], source: pd.DataFrame) -> pd.DataFrame:
    base = source[source["variant"].eq(spec["base"])].copy()
    realized = base["base_ret"].rolling(20, min_periods=20).std().shift(1) * math.sqrt(252)
    vol_exposure = float(spec["target_vol"]) / realized.replace(0.0, np.nan)
    vol_exposure = vol_exposure.clip(lower=0.0, upper=float(spec["max_exposure"])).fillna(1.0)
    trail = (1.0 + base["base_ret"]).rolling(int(spec["lookback"]), min_periods=int(spec["lookback"])).apply(np.prod, raw=True).shift(1) - 1.0
    guard = pd.Series(np.where(trail <= float(spec["threshold"]), float(spec["guard_mult"]), 1.0), index=base.index)
    base["exposure"] = vol_exposure * guard
    base["trend_guard_active"] = guard < 1.0
    equity = START_CAPITAL
    rows = []
    for row in base.itertuples(index=False):
        daily_pnl = equity * float(row.exposure) * float(row.base_ret)
        equity += daily_pnl
        rows.append(
            {
                "variant": spec["variant"],
                "base": spec["base"],
                "date": row.date,
                "base_ret": float(row.base_ret),
                "exposure": float(row.exposure),
                "trend_guard_active": bool(row.trend_guard_active),
                "daily_pnl": daily_pnl,
                "equity": equity,
            }
        )
    return add_periods(pd.DataFrame(rows))


def summary_row(spec: dict[str, object], daily: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "base": spec["base"],
        "targetVol": float(spec["target_vol"]),
        "maxExposure": float(spec["max_exposure"]),
        "lookback": int(spec["lookback"]),
        "threshold": float(spec["threshold"]),
        "guardMult": float(spec["guard_mult"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "avgExposure": float(daily["exposure"].mean()),
        "minExposure": float(daily["exposure"].min()),
        "maxExposureRealized": float(daily["exposure"].max()),
        "pctDaysGuarded": float(daily["trend_guard_active"].mean()),
    }


def period_rows(daily: pd.DataFrame, period_col: str) -> list[dict[str, object]]:
    rows = []
    for (variant, period), group in daily.groupby(["variant", period_col], sort=True):
        curve = START_CAPITAL + group["daily_pnl"].cumsum()
        dd, dd_pct = max_drawdown(curve)
        rows.append(
            {
                "variant": variant,
                period_col: period,
                "pnl": float(group["daily_pnl"].sum()),
                "ddDollarSubset": dd,
                "ddPctSubset": dd_pct,
                "sharpe": sharpe(group["daily_pnl"]),
                "avgExposure": float(group["exposure"].mean()),
                "pctDaysGuarded": float(group["trend_guard_active"].mean()),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    source = load_base_daily()
    frames = []
    summaries = []
    for spec in VARIANTS:
        daily = simulate(spec, source)
        frames.append(daily)
        summary = summary_row(spec, daily)
        summaries.append(summary)
        print("VARIANT", spec["variant"], summary, flush=True)
    all_daily = pd.concat(frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "year")).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "split")).to_csv(SPLIT_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_beta_trend_guard.py",
        "input": str(BENCH_DAILY),
        "sample_label": "Research/in-sample diagnostics across 2018-2024. 2023-2024 is touched validation, not clean unseen OOS.",
        "causality": "Vol target and trailing return guard both use trailing data shifted by one day.",
        "variants": VARIANTS,
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "stop_condition": "About 25% CAGR with low drawdown.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SPLIT_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
