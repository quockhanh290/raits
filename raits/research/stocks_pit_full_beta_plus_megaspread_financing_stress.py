from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_BETA_PLUS_MEGASPREAD_FINANCING_STRESS_2026-09-14"
AUDIT_DAILY = Path("STOCKS_PIT_FULL_BETA_PLUS_MEGASPREAD_AUDIT_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Diagnostic sensitivity only. This is not a newly optimized strategy family.
FINANCING_ANNUAL_RATES = [0.00, 0.025, 0.05, 0.075]
SHORT_BORROW_ANNUAL_RATES = [0.00, 0.01, 0.02, 0.05]


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


def simulate(daily: pd.DataFrame, financing_rate: float, short_borrow_rate: float) -> pd.DataFrame:
    x = daily.sort_values("date").copy()
    equity = START_CAPITAL
    rows = []
    for row in x.itertuples(index=False):
        spread_gross = max(float(row.gross_exposure) - float(row.spy_exposure), 0.0)
        short_gross = spread_gross / 2.0
        excess_gross = max(float(row.gross_exposure) - 1.0, 0.0)
        financing_drag = excess_gross * financing_rate / 252.0
        borrow_drag = short_gross * short_borrow_rate / 252.0
        stressed_ret = float(row.daily_ret) - financing_drag - borrow_drag
        daily_pnl = equity * stressed_ret
        equity += daily_pnl
        rows.append(
            {
                "variant": f"fin{financing_rate:.3f}_borrow{short_borrow_rate:.3f}",
                "date": row.date,
                "base_daily_ret": float(row.daily_ret),
                "financingAnnualRate": financing_rate,
                "shortBorrowAnnualRate": short_borrow_rate,
                "financing_drag_ret": financing_drag,
                "borrow_drag_ret": borrow_drag,
                "daily_ret": stressed_ret,
                "daily_pnl": daily_pnl,
                "equity": equity,
                "gross_exposure": float(row.gross_exposure),
                "spy_exposure": float(row.spy_exposure),
                "spread_gross": spread_gross,
                "short_gross": short_gross,
            }
        )
    out = pd.DataFrame(rows)
    out["year"] = out["date"].dt.year
    return out


def summary_row(daily: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": daily["variant"].iloc[0],
        "financingAnnualRate": float(daily["financingAnnualRate"].iloc[0]),
        "shortBorrowAnnualRate": float(daily["shortBorrowAnnualRate"].iloc[0]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "avgDailyFinancingDragBp": float(daily["financing_drag_ret"].mean() * 10_000),
        "avgDailyBorrowDragBp": float(daily["borrow_drag_ret"].mean() * 10_000),
        "days": int(len(daily)),
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
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    base = pd.read_csv(AUDIT_DAILY, parse_dates=["date"])
    frames = []
    summaries = []
    for financing_rate in FINANCING_ANNUAL_RATES:
        for short_borrow_rate in SHORT_BORROW_ANNUAL_RATES:
            daily = simulate(base, financing_rate, short_borrow_rate)
            frames.append(daily)
            summary = summary_row(daily)
            summaries.append(summary)
            print("STRESS", summary, flush=True)
    all_daily = pd.concat(frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly_rows(all_daily)).to_csv(YEARLY_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_beta_plus_megaspread_financing_stress.py",
        "inputs": [str(AUDIT_DAILY)],
        "method": "Apply pre-registered financing and short-borrow drag sensitivities to the fixed 6.171 audited daily return stream.",
        "financing_annual_rates": FINANCING_ANNUAL_RATES,
        "short_borrow_annual_rates": SHORT_BORROW_ANNUAL_RATES,
        "sample_label": "Research/touched 2018-2024 only; no 2025-2026 OOS opened.",
        "rule_selection_effect": "None. Sensitivity grid is diagnostic and not an optimized production rule.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
