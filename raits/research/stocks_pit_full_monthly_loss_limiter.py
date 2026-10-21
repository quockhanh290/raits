from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_MONTHLY_LOSS_LIMITER_2026-09-14"
BETA_CAL_DAILY = Path("STOCKS_PIT_FULL_BETA_PLUS_CALENDAR_OVERLAY_2026-09-14_DAILY.csv")
BETA_DAILY = Path("STOCKS_PIT_FULL_BETA_VOLTARGET_EXPANSION_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0
TURNOVER_COST_BPS = 4.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

VARIANTS = [
    {"source_file": "beta_cal", "source": "spyvt20c200_plus_spy_first5_x10_fin25_cost4", "mtd_cut": -0.05, "riskoff": 0.25},
    {"source_file": "beta_cal", "source": "spyvt20c200_plus_spy_first5_x10_fin25_cost4", "mtd_cut": -0.08, "riskoff": 0.25},
    {"source_file": "beta_cal", "source": "spyvt16c150_plus_spy_first5_x10_fin25_cost4", "mtd_cut": -0.05, "riskoff": 0.25},
    {"source_file": "beta_cal", "source": "spyvt16c150_plus_spy_first5_x10_fin25_cost4", "mtd_cut": -0.08, "riskoff": 0.25},
    {"source_file": "beta_cal", "source": "spyvt16c150_plus_top62_first5_x10_fin25_cost4", "mtd_cut": -0.05, "riskoff": 0.25},
    {"source_file": "beta_cal", "source": "spyvt16c150_plus_top62_first5_x10_fin25_cost4", "mtd_cut": -0.08, "riskoff": 0.25},
    {"source_file": "beta", "source": "top62_vt25_cap250", "mtd_cut": -0.05, "riskoff": 0.25},
    {"source_file": "beta", "source": "top62_vt25_cap250", "mtd_cut": -0.08, "riskoff": 0.25},
    {"source_file": "beta", "source": "spy_vt20_cap200", "mtd_cut": -0.05, "riskoff": 0.25},
    {"source_file": "beta", "source": "spy_vt20_cap200", "mtd_cut": -0.08, "riskoff": 0.25},
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


def load_streams() -> pd.DataFrame:
    cal = pd.read_csv(BETA_CAL_DAILY, parse_dates=["date"])
    cal = cal[["variant", "date", "daily_ret"]].assign(source_file="beta_cal")
    beta = pd.read_csv(BETA_DAILY, parse_dates=["date"])
    beta = beta.sort_values(["variant", "date"]).copy()
    beta["equity_lag"] = beta.groupby("variant")["equity"].shift(1).fillna(START_CAPITAL)
    beta["daily_ret"] = beta["daily_pnl"] / beta["equity_lag"]
    beta = beta[["variant", "date", "daily_ret"]].assign(source_file="beta")
    return pd.concat([cal, beta], ignore_index=True)


def variant_name(spec: dict[str, object]) -> str:
    stem = str(spec["source"]).replace("_", "")
    return f"{stem}_mtd{int(abs(float(spec['mtd_cut'])) * 100)}_riskoff{int(float(spec['riskoff']) * 100)}"


def simulate(spec: dict[str, object], streams: pd.DataFrame) -> pd.DataFrame:
    x = streams[
        streams["source_file"].eq(spec["source_file"]) & streams["variant"].eq(spec["source"])
    ].sort_values("date")
    equity = START_CAPITAL
    month_start_equity = START_CAPITAL
    current_month = None
    prev_scale = 1.0
    rows = []
    cost_rate = TURNOVER_COST_BPS / 10_000.0

    for row in x.itertuples(index=False):
        month = row.date.to_period("M")
        if current_month != month:
            current_month = month
            month_start_equity = equity
            prev_scale = 1.0
        prior_mtd = equity / month_start_equity - 1.0
        scale = float(spec["riskoff"]) if prior_mtd <= float(spec["mtd_cut"]) else 1.0
        turnover_drag = abs(scale - prev_scale) * cost_rate
        daily_ret = scale * float(row.daily_ret) - turnover_drag
        daily_pnl = equity * daily_ret
        equity += daily_pnl
        rows.append(
            {
                "variant": variant_name(spec),
                "source": spec["source"],
                "date": row.date,
                "source_ret": float(row.daily_ret),
                "prior_mtd": prior_mtd,
                "scale": scale,
                "riskoff": scale < 1.0,
                "turnover_drag_ret": turnover_drag,
                "daily_ret": daily_ret,
                "daily_pnl": daily_pnl,
                "equity": equity,
            }
        )
        prev_scale = scale
    out = pd.DataFrame(rows)
    out["year"] = out["date"].dt.year
    return out


def summary_row(daily: pd.DataFrame, spec: dict[str, object]) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": daily["variant"].iloc[0],
        "source": spec["source"],
        "mtdCut": float(spec["mtd_cut"]),
        "riskoffScale": float(spec["riskoff"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "pctRiskoffDays": float(daily["riskoff"].mean()),
        "avgScale": float(daily["scale"].mean()),
        "turnoverCost": float((daily["turnover_drag_ret"] * daily["equity"].shift(1).fillna(START_CAPITAL)).sum()),
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
                "pctRiskoffDays": float(group["riskoff"].mean()),
                "avgScale": float(group["scale"].mean()),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    streams = load_streams()
    frames = []
    summaries = []
    for spec in VARIANTS:
        daily = simulate(spec, streams)
        frames.append(daily)
        summary = summary_row(daily, spec)
        summaries.append(summary)
        print("MONTH_LIMIT", summary, flush=True)
    all_daily = pd.concat(frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly_rows(all_daily)).to_csv(YEARLY_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_monthly_loss_limiter.py",
        "inputs": [str(BETA_CAL_DAILY), str(BETA_DAILY)],
        "method": "Pre-registered monthly loss limiter using prior month-to-date strategy equity return; scale resets each month.",
        "turnover_cost_bps": TURNOVER_COST_BPS,
        "variants": VARIANTS,
        "sample_label": "Research/touched 2018-2024 only; no 2025-2026 OOS opened.",
        "leakage_controls": "Daily scale uses only prior close month-to-date strategy equity return. No ticker picking and no old manual 62 list.",
        "rule_selection_effect": "None inside diagnostic. Source streams and MTD thresholds fixed before running.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
