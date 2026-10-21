from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_CALENDAR_RELATIVE_SPREAD_2026-09-14"
BENCH_DAILY = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0
FINANCING_ANNUAL_RATE = 0.025
SHORT_BORROW_ANNUAL_RATE = 0.01
TURNOVER_COST_BPS = 4.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Fixed family: calendar-timed relative spreads. This is a new ex-ante
# diagnostic, not leverage tuning of the failed always-on spread.
VARIANTS = [
    {"long": "market_cap_top62_equal_weight", "short": "market_cap_top200_equal_weight", "window": "first5", "spread_weight": 1.0},
    {"long": "market_cap_top62_equal_weight", "short": "market_cap_top200_equal_weight", "window": "first5", "spread_weight": 2.0},
    {"long": "market_cap_top62_equal_weight", "short": "market_cap_top200_equal_weight", "window": "last2_first3", "spread_weight": 1.0},
    {"long": "market_cap_top62_equal_weight", "short": "market_cap_top200_equal_weight", "window": "last2_first3", "spread_weight": 2.0},
    {"long": "market_cap_top62_equal_weight", "short": "market_cap_top500_equal_weight", "window": "first5", "spread_weight": 1.0},
    {"long": "market_cap_top62_equal_weight", "short": "market_cap_top500_equal_weight", "window": "first5", "spread_weight": 2.0},
    {"long": "market_cap_top100_equal_weight", "short": "market_cap_top500_equal_weight", "window": "first5", "spread_weight": 1.0},
    {"long": "market_cap_top100_equal_weight", "short": "market_cap_top500_equal_weight", "window": "first5", "spread_weight": 2.0},
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


def load_returns() -> pd.DataFrame:
    needed = {spec["long"] for spec in VARIANTS} | {spec["short"] for spec in VARIANTS}
    x = pd.read_csv(BENCH_DAILY, parse_dates=["date"])
    x = x[x["variant"].isin(needed)].sort_values(["variant", "date"]).copy()
    x["equity_lag"] = x.groupby("variant")["equity"].shift(1).fillna(START_CAPITAL)
    x["ret"] = x["daily_pnl"] / x["equity_lag"]
    return x[["variant", "date", "ret"]].copy()


def add_calendar(x: pd.DataFrame) -> pd.DataFrame:
    out = x.sort_values("date").copy()
    month_key = out["date"].dt.to_period("M")
    out["td_from_start"] = out.groupby(month_key).cumcount() + 1
    out["td_from_end"] = out.groupby(month_key)["date"].transform("count") - out.groupby(month_key).cumcount()
    return out


def active_window(row: object, window: str) -> bool:
    if window == "first5":
        return int(row.td_from_start) <= 5
    if window == "last2_first3":
        return int(row.td_from_end) <= 2 or int(row.td_from_start) <= 3
    raise ValueError(window)


def variant_name(spec: dict[str, object]) -> str:
    long = "top62" if "top62" in str(spec["long"]) else "top100"
    short = "top200" if "top200" in str(spec["short"]) else "top500"
    return f"{long}_{short}_{spec['window']}_spread{int(float(spec['spread_weight']) * 10):02d}_fin25_borrow1"


def simulate(spec: dict[str, object], streams: pd.DataFrame) -> pd.DataFrame:
    long = streams[streams["variant"].eq(spec["long"])][["date", "ret"]].rename(columns={"ret": "long_ret"})
    short = streams[streams["variant"].eq(spec["short"])][["date", "ret"]].rename(columns={"ret": "short_ret"})
    x = add_calendar(long.merge(short, on="date", how="inner"))
    equity = START_CAPITAL
    prev_active_weight = 0.0
    rows = []
    cost_rate = TURNOVER_COST_BPS / 10_000.0
    spread_weight = float(spec["spread_weight"])
    for row in x.itertuples(index=False):
        active = active_window(row, str(spec["window"]))
        active_weight = spread_weight if active else 0.0
        turnover = 2.0 * abs(active_weight - prev_active_weight)
        gross_exposure = 2.0 * active_weight
        short_gross = active_weight
        financing_drag = max(gross_exposure - 1.0, 0.0) * FINANCING_ANNUAL_RATE / 252.0
        borrow_drag = short_gross * SHORT_BORROW_ANNUAL_RATE / 252.0
        turnover_drag = turnover * cost_rate
        spread_ret = active_weight * (float(row.long_ret) - float(row.short_ret))
        daily_ret = spread_ret - financing_drag - borrow_drag - turnover_drag
        daily_pnl = equity * daily_ret
        equity += daily_pnl
        rows.append(
            {
                "variant": variant_name(spec),
                "date": row.date,
                "long": spec["long"],
                "short": spec["short"],
                "window": spec["window"],
                "long_ret": float(row.long_ret),
                "short_ret": float(row.short_ret),
                "spread_ret_gross": spread_ret,
                "financing_drag_ret": financing_drag,
                "borrow_drag_ret": borrow_drag,
                "turnover_drag_ret": turnover_drag,
                "daily_ret": daily_ret,
                "daily_pnl": daily_pnl,
                "equity": equity,
                "active": active,
                "gross_exposure": gross_exposure,
                "short_gross": short_gross,
                "turnover": turnover,
            }
        )
        prev_active_weight = active_weight
    out = pd.DataFrame(rows)
    out["year"] = out["date"].dt.year
    return out


def summary_row(daily: pd.DataFrame, spec: dict[str, object]) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    active = daily[daily["active"]]
    return {
        "variant": daily["variant"].iloc[0],
        "long": spec["long"],
        "short": spec["short"],
        "window": spec["window"],
        "spreadWeight": float(spec["spread_weight"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "activeDays": int(daily["active"].sum()),
        "pctActiveDays": float(daily["active"].mean()),
        "avgGrossExposure": float(daily["gross_exposure"].mean()),
        "maxGrossExposure": float(daily["gross_exposure"].max()),
        "activeAvgLongShortSpreadBp": float((active["long_ret"] - active["short_ret"]).mean() * 10_000) if not active.empty else np.nan,
        "avgDailyFinancingDragBp": float(daily["financing_drag_ret"].mean() * 10_000),
        "avgDailyBorrowDragBp": float(daily["borrow_drag_ret"].mean() * 10_000),
        "avgDailyTurnoverDragBp": float(daily["turnover_drag_ret"].mean() * 10_000),
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
                "pctActiveDays": float(group["active"].mean()),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    streams = load_returns()
    frames = []
    summaries = []
    for spec in VARIANTS:
        daily = simulate(spec, streams)
        frames.append(daily)
        summary = summary_row(daily, spec)
        summaries.append(summary)
        print("CAL_SPREAD", summary, flush=True)
    all_daily = pd.concat(frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly_rows(all_daily)).to_csv(YEARLY_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_calendar_relative_spread.py",
        "input": str(BENCH_DAILY),
        "method": "Pre-registered calendar-conditioned market-cap relative spread with financing, borrow, and turnover costs.",
        "financing_annual_rate": FINANCING_ANNUAL_RATE,
        "short_borrow_annual_rate": SHORT_BORROW_ANNUAL_RATE,
        "turnover_cost_bps": TURNOVER_COST_BPS,
        "variants": VARIANTS,
        "sample_label": "Research/touched 2018-2024 only; no 2025-2026 OOS opened.",
        "leakage_controls": "Calendar labels use trading-day order only. Long/short streams use PIT market-cap benchmarks from section 6.148. No old manual 62 ticker list.",
        "rule_selection_effect": "None inside diagnostic. Calendar windows, pairs, and weights fixed before running.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
