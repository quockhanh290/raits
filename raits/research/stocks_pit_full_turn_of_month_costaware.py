from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_TURN_OF_MONTH_COSTAWARE_2026-09-14"
BENCH_DAILY = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0
FINANCING_ANNUAL_RATE = 0.025
TURNOVER_COST_BPS = 4.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Ex-ante calendar windows. Positions use only trading-day index within each
# month, so there is no ticker-level selection or old-62 information.
VARIANTS = [
    {"base": "spy_buy_hold", "window": "last1_first3", "exposure": 3.0},
    {"base": "spy_buy_hold", "window": "last2_first3", "exposure": 2.5},
    {"base": "spy_buy_hold", "window": "first5", "exposure": 2.5},
    {"base": "market_cap_top62_equal_weight", "window": "last1_first3", "exposure": 3.0},
    {"base": "market_cap_top62_equal_weight", "window": "last2_first3", "exposure": 2.5},
    {"base": "market_cap_top62_equal_weight", "window": "first5", "exposure": 2.5},
    {"base": "market_cap_top100_equal_weight", "window": "last1_first3", "exposure": 3.0},
    {"base": "market_cap_top100_equal_weight", "window": "last2_first3", "exposure": 2.5},
    {"base": "market_cap_top100_equal_weight", "window": "first5", "exposure": 2.5},
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
    x = pd.read_csv(BENCH_DAILY, parse_dates=["date"])
    x = x[x["variant"].isin({spec["base"] for spec in VARIANTS})].sort_values(["variant", "date"]).copy()
    x["equity_lag"] = x.groupby("variant")["equity"].shift(1).fillna(START_CAPITAL)
    x["ret"] = x["daily_pnl"] / x["equity_lag"]
    return x[["variant", "date", "ret"]].copy()


def mark_calendar(x: pd.DataFrame) -> pd.DataFrame:
    out = x.sort_values("date").copy()
    month_key = out["date"].dt.to_period("M")
    out["td_from_start"] = out.groupby(month_key).cumcount() + 1
    out["td_from_end"] = out.groupby(month_key)["date"].transform("count") - out.groupby(month_key).cumcount()
    return out


def in_window(row: object, window: str) -> bool:
    if window == "last1_first3":
        return int(row.td_from_end) <= 1 or int(row.td_from_start) <= 3
    if window == "last2_first3":
        return int(row.td_from_end) <= 2 or int(row.td_from_start) <= 3
    if window == "first5":
        return int(row.td_from_start) <= 5
    raise ValueError(window)


def variant_name(spec: dict[str, object]) -> str:
    base = "top62" if spec["base"] == "market_cap_top62_equal_weight" else ("top100" if spec["base"] == "market_cap_top100_equal_weight" else "spy")
    return f"{base}_{spec['window']}_x{int(float(spec['exposure']) * 10):02d}_fin25_cost4"


def simulate(spec: dict[str, object], streams: pd.DataFrame) -> pd.DataFrame:
    x = streams[streams["variant"].eq(spec["base"])].copy()
    x = mark_calendar(x)
    equity = START_CAPITAL
    prev_exposure = 0.0
    rows = []
    cost_rate = TURNOVER_COST_BPS / 10_000.0
    for row in x.itertuples(index=False):
        exposure = float(spec["exposure"]) if in_window(row, str(spec["window"])) else 0.0
        turnover = abs(exposure - prev_exposure)
        financing_drag = max(exposure - 1.0, 0.0) * FINANCING_ANNUAL_RATE / 252.0
        turnover_drag = turnover * cost_rate
        daily_ret = exposure * float(row.ret) - financing_drag - turnover_drag
        daily_pnl = equity * daily_ret
        equity += daily_pnl
        rows.append(
            {
                "variant": variant_name(spec),
                "base": spec["base"],
                "date": row.date,
                "window": spec["window"],
                "base_ret": float(row.ret),
                "exposure": exposure,
                "active": exposure > 0,
                "turnover": turnover,
                "financing_drag_ret": financing_drag,
                "turnover_drag_ret": turnover_drag,
                "daily_ret": daily_ret,
                "daily_pnl": daily_pnl,
                "equity": equity,
            }
        )
        prev_exposure = exposure
    out = pd.DataFrame(rows)
    out["year"] = out["date"].dt.year
    return out


def summary_row(daily: pd.DataFrame, spec: dict[str, object]) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    active = daily[daily["active"]]
    return {
        "variant": daily["variant"].iloc[0],
        "base": spec["base"],
        "window": spec["window"],
        "exposure": float(spec["exposure"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "activeDays": int(daily["active"].sum()),
        "pctActiveDays": float(daily["active"].mean()),
        "avgActiveBaseRet": float(active["base_ret"].mean()) if not active.empty else np.nan,
        "avgInactiveBaseRet": float(daily.loc[~daily["active"], "base_ret"].mean()),
        "avgDailyFinancingDragBp": float(daily["financing_drag_ret"].mean() * 10_000),
        "avgDailyTurnoverDragBp": float(daily["turnover_drag_ret"].mean() * 10_000),
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
        print("TOM", summary, flush=True)
    all_daily = pd.concat(frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly_rows(all_daily)).to_csv(YEARLY_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_turn_of_month_costaware.py",
        "input": str(BENCH_DAILY),
        "method": "Pre-registered turn-of-month calendar timing on PIT benchmark streams, with financing and exposure-turnover cost.",
        "financing_annual_rate": FINANCING_ANNUAL_RATE,
        "turnover_cost_bps": TURNOVER_COST_BPS,
        "variants": VARIANTS,
        "sample_label": "Research/touched 2018-2024 only; no 2025-2026 OOS opened.",
        "leakage_controls": "Trading-day-of-month labels use only the calendar/trading dates in the benchmark file. No ticker picking, no old manual 62 list.",
        "rule_selection_effect": "None inside diagnostic. Calendar windows and exposures fixed before running.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
