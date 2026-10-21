from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_MCAP_BETA_RISK_CONTROL_2026-09-14"
BENCH_DAILY = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")

START_CAPITAL = 100_000.0
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SPLIT_OUT = Path(f"{OUT_PREFIX}_SPLITS.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

VARIANTS = [
    {"base": "market_cap_top62_equal_weight", "variant": "top62_voltarget_12pct_cap100", "mode": "voltarget", "target_vol": 0.12, "max_exposure": 1.0},
    {"base": "market_cap_top100_equal_weight", "variant": "top100_voltarget_12pct_cap100", "mode": "voltarget", "target_vol": 0.12, "max_exposure": 1.0},
    {"base": "market_cap_top62_equal_weight", "variant": "top62_trail20_loss8_half", "mode": "trail20_half", "threshold": -0.08, "risk_exposure": 0.5},
    {"base": "market_cap_top100_equal_weight", "variant": "top100_trail20_loss8_half", "mode": "trail20_half", "threshold": -0.08, "risk_exposure": 0.5},
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
    keep = {"market_cap_top62_equal_weight", "market_cap_top100_equal_weight", "spy_buy_hold"}
    daily = daily[daily["variant"].isin(keep)].copy()
    daily["base_equity_lag"] = daily.groupby("variant")["equity"].shift(1).fillna(START_CAPITAL)
    daily["base_ret"] = daily["daily_pnl"] / daily["base_equity_lag"]
    return daily.sort_values(["variant", "date"])


def exposure_series(base: pd.DataFrame, spec: dict[str, object]) -> pd.Series:
    ret = base["base_ret"].astype(float)
    if spec["mode"] == "voltarget":
        realized = ret.rolling(20, min_periods=20).std().shift(1) * math.sqrt(252)
        exposure = float(spec["target_vol"]) / realized.replace(0.0, np.nan)
        return exposure.clip(lower=0.0, upper=float(spec["max_exposure"])).fillna(1.0)
    if spec["mode"] == "trail20_half":
        trail20 = (1.0 + ret).rolling(20, min_periods=20).apply(np.prod, raw=True).shift(1) - 1.0
        return pd.Series(np.where(trail20 <= float(spec["threshold"]), float(spec["risk_exposure"]), 1.0), index=base.index)
    raise ValueError(f"unknown mode {spec['mode']}")


def simulate(spec: dict[str, object], base_daily: pd.DataFrame) -> pd.DataFrame:
    base = base_daily[base_daily["variant"].eq(spec["base"])].copy()
    base["exposure"] = exposure_series(base, spec)
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
                "daily_pnl": daily_pnl,
                "equity": equity,
            }
        )
    return pd.DataFrame(rows)


def summary_row(daily: pd.DataFrame, spec: dict[str, object]) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "base": spec["base"],
        "mode": spec["mode"],
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "avgExposure": float(daily["exposure"].mean()),
        "minExposure": float(daily["exposure"].min()),
        "pctDaysDerisked": float((daily["exposure"] < 0.999).mean()),
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
                "days": int(len(group)),
            }
        )
    return rows


def add_splits(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.copy()
    year = x["date"].dt.year
    x["split"] = np.select(
        [year <= 2021, year == 2022, year >= 2023],
        ["2018_2021_research", "2022_stress", "2023_2024_touched"],
        default="other",
    )
    x["year"] = year
    return x


def main() -> None:
    base_daily = load_base_daily()
    frames = []
    summaries = []
    for spec in VARIANTS:
        daily = simulate(spec, base_daily)
        daily = add_splits(daily)
        frames.append(daily)
        summaries.append(summary_row(daily, spec))
        print("VARIANT", spec["variant"], summaries[-1], flush=True)
    all_daily = pd.concat(frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "year")).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "split")).to_csv(SPLIT_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_mcap_beta_risk_control.py",
        "input": str(BENCH_DAILY),
        "variants": VARIANTS,
        "sample_label": "Research/in-sample diagnostics across 2018-2024. 2023-2024 is touched by prior research and not clean unseen OOS.",
        "causality": "Exposure for each date uses only trailing benchmark returns shifted by one day.",
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "old_62_usage": "None beyond benchmark daily file provenance already documented in 6.148.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SPLIT_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
