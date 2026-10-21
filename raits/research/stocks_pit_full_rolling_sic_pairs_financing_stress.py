from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_FINANCING_STRESS_2026-09-17"
SOURCE_DAILY = Path("STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17_DAILY.csv")
SOURCE_VARIANT = "sic_pairs_quarterly_z2_hold10"
START_CAPITAL = 100_000.0
FINANCING_ANNUAL_RATE = 0.025
LEVERAGES = (1.0, 2.0, 3.0, 5.0)

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peak = equity.cummax()
    return float((equity - peak).min()), float((equity / peak - 1.0).min())


def sharpe(pnl: pd.Series) -> float:
    std = float(pnl.std())
    return float(pnl.mean() / std * math.sqrt(252)) if std > 0 else float("nan")


def cagr(equity: pd.Series, dates: pd.Series) -> float:
    years = max((dates.max() - dates.min()).days / 365.25, 1e-9)
    return float((equity.iloc[-1] / START_CAPITAL) ** (1.0 / years) - 1.0)


def load_source() -> pd.DataFrame:
    x = pd.read_csv(SOURCE_DAILY, parse_dates=["date"])
    x = x[x["variant"].eq(SOURCE_VARIANT)].sort_values("date").copy()
    x["start_equity"] = x["equity"] - x["daily_pnl"]
    x["gross_return_rate"] = (x["daily_pnl"] + x["trade_cost"] + x["borrow_cost"]) / x["start_equity"]
    x["trade_cost_rate"] = x["trade_cost"] / x["start_equity"]
    x["borrow_cost_rate"] = x["borrow_cost"] / x["start_equity"]
    return x


def simulate(source: pd.DataFrame, leverage: float) -> pd.DataFrame:
    equity = START_CAPITAL
    rows = []
    for row in source.itertuples(index=False):
        gross_pnl = equity * float(row.gross_return_rate) * leverage
        trade_cost = equity * float(row.trade_cost_rate) * leverage
        borrow_cost = equity * float(row.borrow_cost_rate) * leverage
        financed_gross = max(float(row.gross_exposure) * leverage - 1.0, 0.0)
        financing_cost = equity * financed_gross * FINANCING_ANNUAL_RATE / 252.0
        daily_pnl = gross_pnl - trade_cost - borrow_cost - financing_cost
        equity += daily_pnl
        rows.append(
            {
                "variant": f"quarterly_hold10_{leverage:g}x",
                "date": row.date,
                "daily_pnl": daily_pnl,
                "equity": equity,
                "gross_pnl_before_costs": gross_pnl,
                "trade_cost": trade_cost,
                "borrow_cost": borrow_cost,
                "financing_cost": financing_cost,
                "gross_exposure": float(row.gross_exposure) * leverage,
            }
        )
    out = pd.DataFrame(rows)
    out["year"] = out["date"].dt.year
    return out


def summary_row(daily: pd.DataFrame, leverage: float) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": daily["variant"].iloc[0],
        "leverage": leverage,
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "grossPnlBeforeCosts": float(daily["gross_pnl_before_costs"].sum()),
        "tradeCost": float(daily["trade_cost"].sum()),
        "borrowCost": float(daily["borrow_cost"].sum()),
        "financingCost": float(daily["financing_cost"].sum()),
        "avgGrossExposure": float(daily["gross_exposure"].mean()),
        "maxGrossExposure": float(daily["gross_exposure"].max()),
    }


def yearly_rows(daily: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for (variant, year), group in daily.groupby(["variant", "year"], sort=True):
        curve = START_CAPITAL + group["daily_pnl"].cumsum()
        dd, dd_pct = max_drawdown(curve)
        rows.append(
            {
                "variant": variant,
                "year": int(year),
                "pnl": float(group["daily_pnl"].sum()),
                "ddDollarSubset": dd,
                "ddPctSubset": dd_pct,
                "sharpe": sharpe(group["daily_pnl"]),
                "financingCost": float(group["financing_cost"].sum()),
            }
        )
    return rows


def main() -> None:
    source = load_source()
    frames = []
    summaries = []
    yearly = []
    for leverage in LEVERAGES:
        daily = simulate(source, leverage)
        frames.append(daily)
        summaries.append(summary_row(daily, leverage))
        yearly.extend(yearly_rows(daily))
        print("PAIR_STRESS", summaries[-1], flush=True)

    all_daily = pd.concat(frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    base = frames[0]
    source_end = float(source["equity"].iloc[-1])
    rebuilt_end = float(base["equity"].iloc[-1])
    qa = pd.DataFrame(
        [{"sourceVariant": SOURCE_VARIANT, "sourceEndEquity": source_end, "rebuilt1xEndEquity": rebuilt_end, "absoluteDifference": abs(source_end - rebuilt_end)}]
    )
    qa.to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_rolling_sic_pairs_financing_stress.py",
        "input": str(SOURCE_DAILY),
        "source_variant": SOURCE_VARIANT,
        "method": "Replay frozen quarterly-hold10 daily gross returns and proportional turnover/borrow at pre-registered gross multipliers; charge 2.5% annual financing on daily gross exposure above 1x.",
        "leverage_family": list(LEVERAGES),
        "rule_selection_effect": "None. Pair formation, signals and trades remain frozen from the source result; this isolates post-selection scaling and financing effects without rule re-selection.",
        "sample_label": "Research/touched 2018-2024 only. 2023-2024 is touched, not clean unseen OOS. No 2025-2026 opened.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(DAILY_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, DAILY_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
