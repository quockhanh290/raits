from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_MEGACAP_RELATIVE_SPREAD_2026-09-14"
BENCH_DAILY = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SPLIT_OUT = Path(f"{OUT_PREFIX}_SPLITS.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Pre-registered mega-cap relative-value spread family. This is a return-stream
# diagnostic; if a row passes, it must be rebuilt at constituent level with costs.
VARIANTS = [
    {"variant": "long_top62_short_broad_100_100", "long": "market_cap_top62_equal_weight", "short": "broad_pit_equal_weight", "long_weight": 1.0, "short_weight": 1.0, "target_vol": None, "max_exposure": 1.0},
    {"variant": "long_top62_short_top500_100_100", "long": "market_cap_top62_equal_weight", "short": "market_cap_top500_equal_weight", "long_weight": 1.0, "short_weight": 1.0, "target_vol": None, "max_exposure": 1.0},
    {"variant": "long_top62_short_top200_100_100", "long": "market_cap_top62_equal_weight", "short": "market_cap_top200_equal_weight", "long_weight": 1.0, "short_weight": 1.0, "target_vol": None, "max_exposure": 1.0},
    {"variant": "long_top62_short_broad_150_100", "long": "market_cap_top62_equal_weight", "short": "broad_pit_equal_weight", "long_weight": 1.5, "short_weight": 1.0, "target_vol": None, "max_exposure": 1.0},
    {"variant": "long_top62_short_broad_100_50", "long": "market_cap_top62_equal_weight", "short": "broad_pit_equal_weight", "long_weight": 1.0, "short_weight": 0.5, "target_vol": None, "max_exposure": 1.0},
    {"variant": "long_top62_short_broad_spread_vt16_cap300", "long": "market_cap_top62_equal_weight", "short": "broad_pit_equal_weight", "long_weight": 1.0, "short_weight": 1.0, "target_vol": 0.16, "max_exposure": 3.0},
    {"variant": "long_top62_short_broad_spread_vt25_cap400", "long": "market_cap_top62_equal_weight", "short": "broad_pit_equal_weight", "long_weight": 1.0, "short_weight": 1.0, "target_vol": 0.25, "max_exposure": 4.0},
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


def returns_from_daily(path: Path) -> pd.DataFrame:
    x = pd.read_csv(path, parse_dates=["date"])
    x = x.sort_values(["variant", "date"]).copy()
    x["equity_lag"] = x.groupby("variant")["equity"].shift(1).fillna(START_CAPITAL)
    x["ret"] = x["daily_pnl"] / x["equity_lag"]
    return x[["variant", "date", "ret"]].copy()


def add_periods(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.copy()
    x["year"] = x["date"].dt.year
    x["split"] = np.select(
        [x["year"].le(2021), x["year"].eq(2022), x["year"].ge(2023)],
        ["2018_2021_research", "2022_stress", "2023_2024_touched"],
        default="other",
    )
    return x


def simulate(spec: dict[str, object], streams: pd.DataFrame) -> pd.DataFrame:
    long = streams[streams["variant"].eq(spec["long"])][["date", "ret"]].rename(columns={"ret": "long_ret"})
    short = streams[streams["variant"].eq(spec["short"])][["date", "ret"]].rename(columns={"ret": "short_ret"})
    x = long.merge(short, on="date", how="inner").sort_values("date")
    x["base_spread_ret"] = float(spec["long_weight"]) * x["long_ret"] - float(spec["short_weight"]) * x["short_ret"]
    if spec["target_vol"] is None:
        x["exposure"] = 1.0
    else:
        realized = x["base_spread_ret"].rolling(20, min_periods=20).std().shift(1) * math.sqrt(252)
        exposure = float(spec["target_vol"]) / realized.replace(0.0, np.nan)
        x["exposure"] = exposure.clip(lower=0.0, upper=float(spec["max_exposure"])).fillna(1.0)
    equity = START_CAPITAL
    rows = []
    for row in x.itertuples(index=False):
        daily_ret = float(row.exposure) * float(row.base_spread_ret)
        daily_pnl = equity * daily_ret
        equity += daily_pnl
        rows.append(
            {
                "variant": spec["variant"],
                "date": row.date,
                "long": spec["long"],
                "short": spec["short"],
                "long_ret": float(row.long_ret),
                "short_ret": float(row.short_ret),
                "base_spread_ret": float(row.base_spread_ret),
                "exposure": float(row.exposure),
                "daily_ret": daily_ret,
                "daily_pnl": daily_pnl,
                "equity": equity,
            }
        )
    return add_periods(pd.DataFrame(rows))


def summary_row(spec: dict[str, object], daily: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "long": spec["long"],
        "short": spec["short"],
        "longWeight": float(spec["long_weight"]),
        "shortWeight": float(spec["short_weight"]),
        "targetVol": float(spec["target_vol"]) if spec["target_vol"] is not None else np.nan,
        "maxExposure": float(spec["max_exposure"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "avgExposure": float(daily["exposure"].mean()),
        "maxExposureRealized": float(daily["exposure"].max()),
        "corrLongShort": float(daily["long_ret"].corr(daily["short_ret"])),
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


def main() -> None:
    streams = returns_from_daily(BENCH_DAILY)
    frames = []
    summaries = []
    for spec in VARIANTS:
        daily = simulate(spec, streams)
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
        "script": "raits/research/stocks_pit_full_megacap_relative_spread.py",
        "inputs": [str(BENCH_DAILY)],
        "sample_label": "Research/in-sample diagnostics across 2018-2024. 2023-2024 is touched validation, not clean unseen OOS.",
        "method": "Pre-registered return-stream mega-cap relative-value spread: long market-cap top62 EW versus broad/top500/top200 EW benchmarks.",
        "variants": VARIANTS,
        "costs": "No additional short borrow, financing, or rebalance costs modeled; diagnostic is optimistic and must be rebuilt before promotion.",
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "old_62_usage": "None.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SPLIT_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
