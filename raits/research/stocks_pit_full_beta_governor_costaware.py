from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_BETA_GOVERNOR_COSTAWARE_2026-09-14"
BENCH_DAILY = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0
FINANCING_ANNUAL_RATE = 0.025
TURNOVER_COST_BPS = 4.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

VARIANTS = [
    {"base": "market_cap_top62_equal_weight", "target_vol": 0.20, "cap": 2.0, "riskoff": 0.50, "ret20_cut": -0.08, "vol20_cut": 0.25},
    {"base": "market_cap_top62_equal_weight", "target_vol": 0.25, "cap": 2.5, "riskoff": 0.50, "ret20_cut": -0.08, "vol20_cut": 0.25},
    {"base": "market_cap_top62_equal_weight", "target_vol": 0.25, "cap": 2.0, "riskoff": 0.50, "ret20_cut": -0.08, "vol20_cut": 0.25},
    {"base": "market_cap_top62_equal_weight", "target_vol": 0.25, "cap": 2.5, "riskoff": 0.00, "ret20_cut": -0.08, "vol20_cut": 0.25},
    {"base": "market_cap_top62_equal_weight", "target_vol": 0.25, "cap": 2.5, "riskoff": 0.50, "ret20_cut": -0.05, "vol20_cut": 0.25},
    {"base": "market_cap_top62_equal_weight", "target_vol": 0.25, "cap": 2.5, "riskoff": 0.50, "ret20_cut": -0.08, "vol20_cut": 0.30},
    {"base": "spy_buy_hold", "target_vol": 0.20, "cap": 2.0, "riskoff": 0.50, "ret20_cut": -0.08, "vol20_cut": 0.25},
    {"base": "spy_buy_hold", "target_vol": 0.25, "cap": 2.5, "riskoff": 0.50, "ret20_cut": -0.08, "vol20_cut": 0.25},
    {"base": "spy_buy_hold", "target_vol": 0.25, "cap": 2.0, "riskoff": 0.50, "ret20_cut": -0.08, "vol20_cut": 0.25},
    {"base": "spy_buy_hold", "target_vol": 0.25, "cap": 2.5, "riskoff": 0.00, "ret20_cut": -0.08, "vol20_cut": 0.25},
    {"base": "spy_buy_hold", "target_vol": 0.25, "cap": 2.5, "riskoff": 0.50, "ret20_cut": -0.05, "vol20_cut": 0.25},
    {"base": "spy_buy_hold", "target_vol": 0.25, "cap": 2.5, "riskoff": 0.50, "ret20_cut": -0.08, "vol20_cut": 0.30},
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


def base_returns() -> pd.DataFrame:
    x = pd.read_csv(BENCH_DAILY, parse_dates=["date"])
    x = x[x["variant"].isin({spec["base"] for spec in VARIANTS})].sort_values(["variant", "date"]).copy()
    x["equity_lag"] = x.groupby("variant")["equity"].shift(1).fillna(START_CAPITAL)
    x["ret"] = x["daily_pnl"] / x["equity_lag"]
    return x[["variant", "date", "ret"]].copy()


def variant_name(spec: dict[str, object]) -> str:
    base = "top62" if spec["base"] == "market_cap_top62_equal_weight" else "spy"
    return (
        f"{base}_vt{int(float(spec['target_vol']) * 100)}"
        f"_cap{int(float(spec['cap']) * 100)}"
        f"_riskoff{int(float(spec['riskoff']) * 100)}"
        f"_ret20{int(abs(float(spec['ret20_cut'])) * 100)}"
        f"_vol20{int(float(spec['vol20_cut']) * 100)}"
    )


def simulate(spec: dict[str, object], streams: pd.DataFrame) -> pd.DataFrame:
    x = streams[streams["variant"].eq(spec["base"])].sort_values("date").copy()
    realized_vol = x["ret"].rolling(20, min_periods=20).std().shift(1) * math.sqrt(252)
    ret20 = (1.0 + x["ret"]).rolling(20, min_periods=20).apply(np.prod, raw=True).shift(1) - 1.0
    raw_exposure = (float(spec["target_vol"]) / realized_vol.replace(0.0, np.nan)).clip(0.0, float(spec["cap"])).fillna(1.0)
    riskoff_mask = (ret20 <= float(spec["ret20_cut"])) | (realized_vol >= float(spec["vol20_cut"]))
    x["exposure"] = raw_exposure.where(~riskoff_mask, float(spec["riskoff"]))
    x["riskoff"] = riskoff_mask.fillna(False)

    equity = START_CAPITAL
    prev_exposure = 0.0
    rows = []
    cost_rate = TURNOVER_COST_BPS / 10_000.0
    for row in x.itertuples(index=False):
        exposure = float(row.exposure)
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
                "base_ret": float(row.ret),
                "exposure": exposure,
                "riskoff": bool(row.riskoff),
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
    return {
        "variant": daily["variant"].iloc[0],
        "base": spec["base"],
        "targetVol": float(spec["target_vol"]),
        "cap": float(spec["cap"]),
        "riskoffExposure": float(spec["riskoff"]),
        "ret20Cut": float(spec["ret20_cut"]),
        "vol20Cut": float(spec["vol20_cut"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "avgExposure": float(daily["exposure"].mean()),
        "maxExposure": float(daily["exposure"].max()),
        "pctRiskoffDays": float(daily["riskoff"].mean()),
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
                "avgExposure": float(group["exposure"].mean()),
                "pctRiskoffDays": float(group["riskoff"].mean()),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    streams = base_returns()
    frames = []
    summaries = []
    for spec in VARIANTS:
        daily = simulate(spec, streams)
        frames.append(daily)
        summary = summary_row(daily, spec)
        summaries.append(summary)
        print("GOVERNOR", summary, flush=True)
    all_daily = pd.concat(frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly_rows(all_daily)).to_csv(YEARLY_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_beta_governor_costaware.py",
        "input": str(BENCH_DAILY),
        "method": "Pre-registered cost-aware long-only beta governor using lagged 20-day return and lagged 20-day realized volatility.",
        "financing_annual_rate": FINANCING_ANNUAL_RATE,
        "turnover_cost_bps": TURNOVER_COST_BPS,
        "variants": VARIANTS,
        "sample_label": "Research/touched 2018-2024 only; no 2025-2026 OOS opened.",
        "leakage_controls": "All guard inputs are shifted one day. No old manual 62 ticker list. Market-cap top62 stream comes from PIT benchmark section 6.148.",
        "rule_selection_effect": "None inside this diagnostic. Variant grid fixed before running.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
