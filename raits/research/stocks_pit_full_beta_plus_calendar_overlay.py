from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_BETA_PLUS_CALENDAR_OVERLAY_2026-09-14"
BENCH_DAILY = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")
BETA_DAILY = Path("STOCKS_PIT_FULL_BETA_VOLTARGET_EXPANSION_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0
FINANCING_ANNUAL_RATE = 0.025
TURNOVER_COST_BPS = 4.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Fixed ensemble family: moderate beta sleeve plus first-five-trading-days
# calendar overlay. No old-62 ticker list and no per-ticker winner selection.
VARIANTS = [
    {"beta": "spy_vt16_cap150", "overlay_base": "spy_buy_hold", "overlay_exposure": 0.5},
    {"beta": "spy_vt16_cap150", "overlay_base": "spy_buy_hold", "overlay_exposure": 1.0},
    {"beta": "spy_vt20_cap200", "overlay_base": "spy_buy_hold", "overlay_exposure": 0.5},
    {"beta": "spy_vt20_cap200", "overlay_base": "spy_buy_hold", "overlay_exposure": 1.0},
    {"beta": "top62_vt16_cap150", "overlay_base": "market_cap_top62_equal_weight", "overlay_exposure": 0.5},
    {"beta": "top62_vt16_cap150", "overlay_base": "market_cap_top62_equal_weight", "overlay_exposure": 1.0},
    {"beta": "top62_vt20_cap200", "overlay_base": "market_cap_top62_equal_weight", "overlay_exposure": 0.5},
    {"beta": "top62_vt20_cap200", "overlay_base": "market_cap_top62_equal_weight", "overlay_exposure": 1.0},
    {"beta": "spy_vt16_cap150", "overlay_base": "market_cap_top62_equal_weight", "overlay_exposure": 0.5},
    {"beta": "spy_vt16_cap150", "overlay_base": "market_cap_top62_equal_weight", "overlay_exposure": 1.0},
    {"beta": "top62_vt16_cap150", "overlay_base": "spy_buy_hold", "overlay_exposure": 0.5},
    {"beta": "top62_vt16_cap150", "overlay_base": "spy_buy_hold", "overlay_exposure": 1.0},
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


def load_beta() -> pd.DataFrame:
    x = pd.read_csv(BETA_DAILY, parse_dates=["date"])
    x = x[x["variant"].isin({spec["beta"] for spec in VARIANTS})].sort_values(["variant", "date"]).copy()
    x["equity_lag"] = x.groupby("variant")["equity"].shift(1).fillna(START_CAPITAL)
    x["beta_ret"] = x["daily_pnl"] / x["equity_lag"]
    return x[["variant", "date", "beta_ret", "exposure"]].rename(columns={"variant": "beta", "exposure": "beta_exposure"})


def load_overlay_returns() -> pd.DataFrame:
    x = pd.read_csv(BENCH_DAILY, parse_dates=["date"])
    x = x[x["variant"].isin({spec["overlay_base"] for spec in VARIANTS})].sort_values(["variant", "date"]).copy()
    x["equity_lag"] = x.groupby("variant")["equity"].shift(1).fillna(START_CAPITAL)
    x["overlay_base_ret"] = x["daily_pnl"] / x["equity_lag"]
    x["month"] = x["date"].dt.to_period("M")
    x["td_from_start"] = x.groupby(["variant", "month"]).cumcount() + 1
    return x[["variant", "date", "overlay_base_ret", "td_from_start"]].rename(columns={"variant": "overlay_base"})


def variant_name(spec: dict[str, object]) -> str:
    beta = str(spec["beta"]).replace("_cap", "c").replace("_", "")
    overlay = "top62" if spec["overlay_base"] == "market_cap_top62_equal_weight" else "spy"
    return f"{beta}_plus_{overlay}_first5_x{int(float(spec['overlay_exposure']) * 10):02d}_fin25_cost4"


def simulate(spec: dict[str, object], beta: pd.DataFrame, overlay: pd.DataFrame) -> pd.DataFrame:
    b = beta[beta["beta"].eq(spec["beta"])]
    o = overlay[overlay["overlay_base"].eq(spec["overlay_base"])]
    x = b.merge(o, on="date", how="inner").sort_values("date")
    equity = START_CAPITAL
    prev_beta_exposure = 0.0
    prev_overlay_exposure = 0.0
    rows = []
    cost_rate = TURNOVER_COST_BPS / 10_000.0
    for row in x.itertuples(index=False):
        overlay_exposure = float(spec["overlay_exposure"]) if int(row.td_from_start) <= 5 else 0.0
        beta_exposure = float(row.beta_exposure)
        gross_exposure = beta_exposure + overlay_exposure
        turnover = abs(beta_exposure - prev_beta_exposure) + abs(overlay_exposure - prev_overlay_exposure)
        financing_drag = max(gross_exposure - 1.0, 0.0) * FINANCING_ANNUAL_RATE / 252.0
        turnover_drag = turnover * cost_rate
        overlay_ret = overlay_exposure * float(row.overlay_base_ret)
        daily_ret = float(row.beta_ret) + overlay_ret - financing_drag - turnover_drag
        daily_pnl = equity * daily_ret
        equity += daily_pnl
        rows.append(
            {
                "variant": variant_name(spec),
                "date": row.date,
                "beta": spec["beta"],
                "overlay_base": spec["overlay_base"],
                "beta_ret": float(row.beta_ret),
                "overlay_ret": overlay_ret,
                "daily_ret": daily_ret,
                "daily_pnl": daily_pnl,
                "equity": equity,
                "beta_exposure": beta_exposure,
                "overlay_exposure": overlay_exposure,
                "gross_exposure": gross_exposure,
                "turnover": turnover,
                "financing_drag_ret": financing_drag,
                "turnover_drag_ret": turnover_drag,
                "active_overlay": overlay_exposure > 0,
            }
        )
        prev_beta_exposure = beta_exposure
        prev_overlay_exposure = overlay_exposure
    out = pd.DataFrame(rows)
    out["year"] = out["date"].dt.year
    out["split"] = np.select(
        [out["year"].le(2021), out["year"].eq(2022), out["year"].ge(2023)],
        ["2018_2021_research", "2022_stress", "2023_2024_touched"],
        default="other",
    )
    return out


def summary_row(daily: pd.DataFrame, spec: dict[str, object]) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": daily["variant"].iloc[0],
        "beta": spec["beta"],
        "overlayBase": spec["overlay_base"],
        "overlayExposure": float(spec["overlay_exposure"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "avgGrossExposure": float(daily["gross_exposure"].mean()),
        "maxGrossExposure": float(daily["gross_exposure"].max()),
        "pctOverlayActive": float(daily["active_overlay"].mean()),
        "avgDailyFinancingDragBp": float(daily["financing_drag_ret"].mean() * 10_000),
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
                "avgGrossExposure": float(group["gross_exposure"].mean()),
                "pctOverlayActive": float(group["active_overlay"].mean()),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    beta = load_beta()
    overlay = load_overlay_returns()
    frames = []
    summaries = []
    for spec in VARIANTS:
        daily = simulate(spec, beta, overlay)
        frames.append(daily)
        summary = summary_row(daily, spec)
        summaries.append(summary)
        print("BETA_CAL", summary, flush=True)
    all_daily = pd.concat(frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly_rows(all_daily)).to_csv(YEARLY_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_beta_plus_calendar_overlay.py",
        "inputs": [str(BETA_DAILY), str(BENCH_DAILY)],
        "method": "Pre-registered moderate beta vol-target sleeve plus first-five-trading-days calendar overlay with financing and exposure-turnover cost.",
        "financing_annual_rate": FINANCING_ANNUAL_RATE,
        "turnover_cost_bps": TURNOVER_COST_BPS,
        "variants": VARIANTS,
        "sample_label": "Research/touched 2018-2024 only; no 2025-2026 OOS opened.",
        "leakage_controls": "Calendar labels use trading-day order only; beta streams and benchmark streams come from prior PIT diagnostics. No old manual 62 ticker list.",
        "rule_selection_effect": "None inside diagnostic. Variant grid fixed before running.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
