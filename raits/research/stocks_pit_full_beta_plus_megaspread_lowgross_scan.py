from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_BETA_PLUS_MEGASPREAD_LOWGROSS_SCAN_2026-09-14"
AUDIT_DAILY = Path("STOCKS_PIT_FULL_BETA_PLUS_MEGASPREAD_AUDIT_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0
BASE_SPREAD_WEIGHT = 3.0
FINANCING_ANNUAL_RATE = 0.025
SHORT_BORROW_ANNUAL_RATE = 0.01

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Fixed low-gross family: no variant is chosen from old-62 behavior.
VARIANTS = [
    {"variant": "spy075_spread050_fin25_borrow1", "spy_scale": 0.75, "spread_weight": 0.50},
    {"variant": "spy100_spread050_fin25_borrow1", "spy_scale": 1.00, "spread_weight": 0.50},
    {"variant": "spy125_spread050_fin25_borrow1", "spy_scale": 1.25, "spread_weight": 0.50},
    {"variant": "spy075_spread100_fin25_borrow1", "spy_scale": 0.75, "spread_weight": 1.00},
    {"variant": "spy100_spread100_fin25_borrow1", "spy_scale": 1.00, "spread_weight": 1.00},
    {"variant": "spy125_spread100_fin25_borrow1", "spy_scale": 1.25, "spread_weight": 1.00},
    {"variant": "spy075_spread150_fin25_borrow1", "spy_scale": 0.75, "spread_weight": 1.50},
    {"variant": "spy100_spread150_fin25_borrow1", "spy_scale": 1.00, "spread_weight": 1.50},
    {"variant": "spy125_spread150_fin25_borrow1", "spy_scale": 1.25, "spread_weight": 1.50},
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


def add_periods(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.copy()
    x["year"] = x["date"].dt.year
    x["split"] = np.select(
        [x["year"].le(2021), x["year"].eq(2022), x["year"].ge(2023)],
        ["2018_2021_research", "2022_stress", "2023_2024_touched"],
        default="other",
    )
    return x


def simulate(base: pd.DataFrame, spec: dict[str, float | str]) -> pd.DataFrame:
    x = base.sort_values("date").copy()
    spread_scale = float(spec["spread_weight"]) / BASE_SPREAD_WEIGHT
    spy_scale = float(spec["spy_scale"])
    equity = START_CAPITAL
    rows = []
    for row in x.itertuples(index=False):
        spy_ret = spy_scale * float(row.spy_ret)
        spy_exposure = spy_scale * float(row.spy_exposure)
        spread_ret_gross = spread_scale * float(row.spread_ret_gross)
        spread_cost_ret = spread_scale * float(row.spread_cost_ret)
        spread_gross = spread_scale * max(float(row.gross_exposure) - float(row.spy_exposure), 0.0)
        short_gross = spread_gross / 2.0
        gross_exposure = spy_exposure + spread_gross
        excess_gross = max(gross_exposure - 1.0, 0.0)
        financing_drag = excess_gross * FINANCING_ANNUAL_RATE / 252.0
        borrow_drag = short_gross * SHORT_BORROW_ANNUAL_RATE / 252.0
        daily_ret = spy_ret + spread_ret_gross - spread_cost_ret - financing_drag - borrow_drag
        daily_pnl = equity * daily_ret
        equity += daily_pnl
        rows.append(
            {
                "variant": spec["variant"],
                "date": row.date,
                "spy_scale": spy_scale,
                "spread_weight": float(spec["spread_weight"]),
                "spy_ret": spy_ret,
                "spread_ret_gross": spread_ret_gross,
                "spread_cost_ret": spread_cost_ret,
                "financing_drag_ret": financing_drag,
                "borrow_drag_ret": borrow_drag,
                "daily_ret": daily_ret,
                "daily_pnl": daily_pnl,
                "equity": equity,
                "gross_exposure": gross_exposure,
                "net_exposure": spy_exposure,
                "short_gross": short_gross,
            }
        )
    return add_periods(pd.DataFrame(rows))


def summary_row(daily: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": daily["variant"].iloc[0],
        "spyScale": float(daily["spy_scale"].iloc[0]),
        "spreadWeight": float(daily["spread_weight"].iloc[0]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "avgGrossExposure": float(daily["gross_exposure"].mean()),
        "maxGrossExposure": float(daily["gross_exposure"].max()),
        "avgDailyFinancingDragBp": float(daily["financing_drag_ret"].mean() * 10_000),
        "avgDailyBorrowDragBp": float(daily["borrow_drag_ret"].mean() * 10_000),
        "days": int(len(daily)),
    }


def period_rows(daily: pd.DataFrame) -> list[dict[str, object]]:
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
                "avgGrossExposure": float(group["gross_exposure"].mean()),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    base = pd.read_csv(AUDIT_DAILY, parse_dates=["date"])
    frames = []
    summaries = []
    for spec in VARIANTS:
        daily = simulate(base, spec)
        frames.append(daily)
        summary = summary_row(daily)
        summaries.append(summary)
        print("LOWGROSS", summary, flush=True)
    all_daily = pd.concat(frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily)).to_csv(YEARLY_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_beta_plus_megaspread_lowgross_scan.py",
        "input": str(AUDIT_DAILY),
        "method": "Pre-registered low-gross rescaling of fixed 6.171 constituent-audited SPY vt16 plus top62/top200 spread stream, with financing and borrow drag included from the start.",
        "financing_annual_rate": FINANCING_ANNUAL_RATE,
        "short_borrow_annual_rate": SHORT_BORROW_ANNUAL_RATE,
        "variants": VARIANTS,
        "sample_label": "Research/touched 2018-2024 only; no 2025-2026 OOS opened.",
        "rule_selection_effect": "None inside this diagnostic. Variant grid fixed before running.",
        "old_62_usage": "None; inherited PIT market-cap top62/top200 from section 6.171.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
