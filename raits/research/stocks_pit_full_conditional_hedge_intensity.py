from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_CONDITIONAL_HEDGE_INTENSITY_2026-09-14"
BENCH_DAILY = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")
BETA_DAILY = Path("STOCKS_PIT_FULL_BETA_VOLTARGET_EXPANSION_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SPLIT_OUT = Path(f"{OUT_PREFIX}_SPLITS.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Pre-registered follow-up to section 6.158:
# only broad-PIT hedge intensity and a single longer trigger are varied.
VARIANTS = [
    {"variant": "top62_vt20_short_broad75_broad20m5", "base": "top62_vt20_cap200", "hedge": "broad_pit_equal_weight", "hedge_weight": 0.75, "trigger": "broad_pit_equal_weight", "lookback": 20, "threshold": -0.05},
    {"variant": "top62_vt20_short_broad100_broad20m5", "base": "top62_vt20_cap200", "hedge": "broad_pit_equal_weight", "hedge_weight": 1.0, "trigger": "broad_pit_equal_weight", "lookback": 20, "threshold": -0.05},
    {"variant": "top62_vt25_short_broad75_broad20m5", "base": "top62_vt25_cap250", "hedge": "broad_pit_equal_weight", "hedge_weight": 0.75, "trigger": "broad_pit_equal_weight", "lookback": 20, "threshold": -0.05},
    {"variant": "top62_vt25_short_broad100_broad20m5", "base": "top62_vt25_cap250", "hedge": "broad_pit_equal_weight", "hedge_weight": 1.0, "trigger": "broad_pit_equal_weight", "lookback": 20, "threshold": -0.05},
    {"variant": "top62_vt20_short_broad75_broad60m10", "base": "top62_vt20_cap200", "hedge": "broad_pit_equal_weight", "hedge_weight": 0.75, "trigger": "broad_pit_equal_weight", "lookback": 60, "threshold": -0.10},
    {"variant": "top62_vt25_short_broad75_broad60m10", "base": "top62_vt25_cap250", "hedge": "broad_pit_equal_weight", "hedge_weight": 0.75, "trigger": "broad_pit_equal_weight", "lookback": 60, "threshold": -0.10},
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


def returns_from_daily(path: Path, variant_col: str = "variant") -> pd.DataFrame:
    x = pd.read_csv(path, parse_dates=["date"])
    x = x.sort_values([variant_col, "date"]).copy()
    x["equity_lag"] = x.groupby(variant_col)["equity"].shift(1).fillna(START_CAPITAL)
    x["ret"] = x["daily_pnl"] / x["equity_lag"]
    return x[[variant_col, "date", "ret"]].rename(columns={variant_col: "variant"})


def add_periods(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.copy()
    x["year"] = x["date"].dt.year
    x["split"] = np.select(
        [x["year"].le(2021), x["year"].eq(2022), x["year"].ge(2023)],
        ["2018_2021_research", "2022_stress", "2023_2024_touched"],
        default="other",
    )
    return x


def simulate(spec: dict[str, object], beta: pd.DataFrame, bench: pd.DataFrame) -> pd.DataFrame:
    base = beta[beta["variant"].eq(spec["base"])][["date", "ret"]].rename(columns={"ret": "base_ret"})
    hedge = bench[bench["variant"].eq(spec["hedge"])][["date", "ret"]].rename(columns={"ret": "hedge_ret"})
    trigger = bench[bench["variant"].eq(spec["trigger"])][["date", "ret"]].sort_values("date").copy()
    lookback = int(spec["lookback"])
    trigger["trail"] = (1.0 + trigger["ret"]).rolling(lookback, min_periods=lookback).apply(np.prod, raw=True).shift(1) - 1.0
    trigger["hedge_on"] = trigger["trail"] <= float(spec["threshold"])
    x = base.merge(hedge, on="date", how="inner").merge(trigger[["date", "trail", "hedge_on"]], on="date", how="inner")
    x = x.sort_values("date")
    equity = START_CAPITAL
    rows = []
    for row in x.itertuples(index=False):
        hedge_weight = float(spec["hedge_weight"]) if bool(row.hedge_on) else 0.0
        mixed_ret = float(row.base_ret) - hedge_weight * float(row.hedge_ret)
        daily_pnl = equity * mixed_ret
        equity += daily_pnl
        rows.append(
            {
                "variant": spec["variant"],
                "date": row.date,
                "base": spec["base"],
                "hedge": spec["hedge"],
                "base_ret": float(row.base_ret),
                "hedge_ret": float(row.hedge_ret),
                "trail_trigger": float(row.trail) if not pd.isna(row.trail) else np.nan,
                "hedge_on": bool(row.hedge_on),
                "hedge_weight": hedge_weight,
                "mixed_ret": mixed_ret,
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
        "hedge": spec["hedge"],
        "trigger": spec["trigger"],
        "hedgeWeight": float(spec["hedge_weight"]),
        "lookback": int(spec["lookback"]),
        "threshold": float(spec["threshold"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "pctDaysHedged": float(daily["hedge_on"].mean()),
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
                "pctDaysHedged": float(group["hedge_on"].mean()),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    beta = returns_from_daily(BETA_DAILY)
    bench = returns_from_daily(BENCH_DAILY)
    frames = []
    summaries = []
    for spec in VARIANTS:
        daily = simulate(spec, beta, bench)
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
        "script": "raits/research/stocks_pit_full_conditional_hedge_intensity.py",
        "inputs": [str(BENCH_DAILY), str(BETA_DAILY)],
        "sample_label": "Research/in-sample diagnostics across 2018-2024. 2023-2024 is touched validation, not clean unseen OOS.",
        "method": "Pre-registered follow-up to section 6.158: vary only broad-PIT hedge intensity and one longer broad-PIT trigger.",
        "variants": VARIANTS,
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "old_62_usage": "None.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SPLIT_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
