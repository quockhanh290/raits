from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_BETA_PLUS_MEGASPREAD_2026-09-14"
BETA_DAILY = Path("STOCKS_PIT_FULL_BETA_VOLTARGET_EXPANSION_2026-09-14_DAILY.csv")
SPREAD_DAILY = Path("STOCKS_PIT_FULL_MEGACAP_RELATIVE_SPREAD_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SPLIT_OUT = Path(f"{OUT_PREFIX}_SPLITS.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Pre-registered ensemble family. It combines a moderate beta sleeve with the
# low-DD mega-cap relative spread found in section 6.169.
VARIANTS = [
    {"variant": "top62_vt16_plus_top62_top200_spread2", "beta": "top62_vt16_cap150", "beta_weight": 1.0, "spread": "long_top62_short_top200_100_100", "spread_weight": 2.0},
    {"variant": "top62_vt16_plus_top62_top200_spread3", "beta": "top62_vt16_cap150", "beta_weight": 1.0, "spread": "long_top62_short_top200_100_100", "spread_weight": 3.0},
    {"variant": "top62_vt16_plus_top62_top200_spread4", "beta": "top62_vt16_cap150", "beta_weight": 1.0, "spread": "long_top62_short_top200_100_100", "spread_weight": 4.0},
    {"variant": "top62_vt20_plus_top62_top200_spread2", "beta": "top62_vt20_cap200", "beta_weight": 1.0, "spread": "long_top62_short_top200_100_100", "spread_weight": 2.0},
    {"variant": "top62_vt20_plus_top62_top500_spread2", "beta": "top62_vt20_cap200", "beta_weight": 1.0, "spread": "long_top62_short_top500_100_100", "spread_weight": 2.0},
    {"variant": "spy_vt16_plus_top62_top200_spread3", "beta": "spy_vt16_cap150", "beta_weight": 1.0, "spread": "long_top62_short_top200_100_100", "spread_weight": 3.0},
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
    ret_col = "daily_ret" if "daily_ret" in x.columns else None
    if ret_col:
        x["ret"] = x[ret_col]
    else:
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
    beta = streams[streams["variant"].eq(spec["beta"])][["date", "ret"]].rename(columns={"ret": "beta_ret"})
    spread = streams[streams["variant"].eq(spec["spread"])][["date", "ret"]].rename(columns={"ret": "spread_ret"})
    x = beta.merge(spread, on="date", how="inner").sort_values("date")
    equity = START_CAPITAL
    rows = []
    for row in x.itertuples(index=False):
        mixed_ret = float(spec["beta_weight"]) * float(row.beta_ret) + float(spec["spread_weight"]) * float(row.spread_ret)
        daily_pnl = equity * mixed_ret
        equity += daily_pnl
        rows.append(
            {
                "variant": spec["variant"],
                "date": row.date,
                "beta": spec["beta"],
                "spread": spec["spread"],
                "beta_ret": float(row.beta_ret),
                "spread_ret": float(row.spread_ret),
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
        "beta": spec["beta"],
        "betaWeight": float(spec["beta_weight"]),
        "spread": spec["spread"],
        "spreadWeight": float(spec["spread_weight"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "corrBetaSpread": float(daily["beta_ret"].corr(daily["spread_ret"])),
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
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    beta = returns_from_daily(BETA_DAILY)
    spread = returns_from_daily(SPREAD_DAILY)
    streams = pd.concat([beta, spread], ignore_index=True)
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
        "script": "raits/research/stocks_pit_full_beta_plus_megaspread.py",
        "inputs": [str(BETA_DAILY), str(SPREAD_DAILY)],
        "sample_label": "Research/in-sample diagnostics across 2018-2024. 2023-2024 is touched validation, not clean unseen OOS.",
        "method": "Pre-registered beta plus mega-cap relative-spread ensemble using existing daily return streams.",
        "variants": VARIANTS,
        "costs": "Inherits beta-stream assumptions; no extra spread borrow/financing/rebalance costs beyond source stream diagnostic.",
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "old_62_usage": "None.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SPLIT_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
