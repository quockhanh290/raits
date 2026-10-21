from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_MCAP_MOMENTUM_RISK_CONTROL_2026-09-14"
MOM_DAILY = Path("STOCKS_PIT_FULL_MCAP_MOMENTUM_MONTHLY_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SPLIT_OUT = Path(f"{OUT_PREFIX}_SPLITS.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

VARIANTS = [
    {"base": "pool500_ret60_top20_gross100", "variant": "pool500_ret60_top20_vt20_cap150", "target_vol": 0.20, "max_exposure": 1.5},
    {"base": "pool500_ret60_top20_gross100", "variant": "pool500_ret60_top20_vt25_cap150", "target_vol": 0.25, "max_exposure": 1.5},
    {"base": "pool500_ret60_top10_gross100", "variant": "pool500_ret60_top10_vt20_cap150", "target_vol": 0.20, "max_exposure": 1.5},
    {"base": "pool200_ret60_top20_gross100", "variant": "pool200_ret60_top20_vt20_cap150", "target_vol": 0.20, "max_exposure": 1.5},
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


def load_daily() -> pd.DataFrame:
    x = pd.read_csv(MOM_DAILY, parse_dates=["date"])
    x = x.sort_values(["variant", "date"]).copy()
    x["base_equity_lag"] = x.groupby("variant")["equity"].shift(1).fillna(START_CAPITAL)
    x["base_ret"] = x["daily_pnl"] / x["base_equity_lag"]
    return x


def simulate(spec: dict[str, object], source: pd.DataFrame) -> pd.DataFrame:
    base = source[source["variant"].eq(spec["base"])].copy()
    realized = base["base_ret"].rolling(20, min_periods=20).std().shift(1) * math.sqrt(252)
    exposure = float(spec["target_vol"]) / realized.replace(0.0, np.nan)
    base["exposure"] = exposure.clip(lower=0.0, upper=float(spec["max_exposure"])).fillna(1.0)
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
    return add_periods(pd.DataFrame(rows))


def add_periods(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.copy()
    x["year"] = x["date"].dt.year
    x["split"] = np.select(
        [x["year"].le(2021), x["year"].eq(2022), x["year"].ge(2023)],
        ["2018_2021_research", "2022_stress", "2023_2024_touched"],
        default="other",
    )
    return x


def summary_row(spec: dict[str, object], daily: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "base": spec["base"],
        "targetVol": spec["target_vol"],
        "maxExposure": spec["max_exposure"],
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "avgExposure": float(daily["exposure"].mean()),
        "minExposure": float(daily["exposure"].min()),
        "maxExposureRealized": float(daily["exposure"].max()),
        "pctDaysLevered": float((daily["exposure"] > 1.001).mean()),
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


def main() -> None:
    source = load_daily()
    frames = []
    summaries = []
    for spec in VARIANTS:
        daily = simulate(spec, source)
        frames.append(daily)
        summaries.append(summary_row(spec, daily))
        print("VARIANT", spec["variant"], summaries[-1], flush=True)
    all_daily = pd.concat(frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "year")).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "split")).to_csv(SPLIT_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_mcap_momentum_risk_control.py",
        "input": str(MOM_DAILY),
        "sample_label": "Research/in-sample diagnostics across 2018-2024. 2023-2024 is touched validation, not clean unseen OOS.",
        "causality": "Vol target exposure uses trailing 20-day base strategy volatility shifted by one day.",
        "variants": VARIANTS,
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SPLIT_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
