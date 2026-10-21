from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_BETA_SIGNAL_MIX_2026-09-14"
NO_INTRADAY_EQUITY = Path("STOCKS_PIT_FULL_NO_INTRADAY_NOWARMUP_2018_2024_EQUITY.csv")
MCAP_BETA_DAILY = Path("STOCKS_PIT_FULL_MCAP_BETA_RISK_CONTROL_2026-09-14_DAILY.csv")
BETA_EXPANSION_DAILY = Path("STOCKS_PIT_FULL_BETA_VOLTARGET_EXPANSION_2026-09-14_DAILY.csv")

START_CAPITAL = 100_000.0
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SPLIT_OUT = Path(f"{OUT_PREFIX}_SPLITS.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CORR_OUT = Path(f"{OUT_PREFIX}_CORRELATION.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

VARIANTS = [
    {"variant": "top62_vt12_plus_B05", "beta": "top62_voltarget_12pct_cap100", "beta_weight": 1.0, "signal_weight": 0.5},
    {"variant": "top62_vt12_plus_B10", "beta": "top62_voltarget_12pct_cap100", "beta_weight": 1.0, "signal_weight": 1.0},
    {"variant": "top62_vt16_plus_B05", "beta": "top62_vt16_cap150", "beta_weight": 1.0, "signal_weight": 0.5},
    {"variant": "top62_vt16_plus_B10", "beta": "top62_vt16_cap150", "beta_weight": 1.0, "signal_weight": 1.0},
    {"variant": "top62_vt20_plus_B05", "beta": "top62_vt20_cap200", "beta_weight": 1.0, "signal_weight": 0.5},
    {"variant": "spy_vt16_plus_B05", "beta": "spy_vt16_cap150", "beta_weight": 1.0, "signal_weight": 0.5},
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


def load_signal_returns() -> pd.DataFrame:
    eq = pd.read_csv(NO_INTRADAY_EQUITY, parse_dates=["date"])
    eq = eq[eq["portfolio"].eq("B_pit_full_no_intraday_nowarmup_cap40")].copy()
    eq = eq.sort_values("date")
    eq["equity_lag"] = eq["equity"].shift(1).fillna(START_CAPITAL)
    eq["signal_ret"] = eq["daily_pnl"] / eq["equity_lag"]
    return eq[["date", "signal_ret"]]


def load_beta_returns() -> pd.DataFrame:
    parts = []
    for path in (MCAP_BETA_DAILY, BETA_EXPANSION_DAILY):
        x = pd.read_csv(path, parse_dates=["date"])
        x = x.sort_values(["variant", "date"])
        x["equity_lag"] = x.groupby("variant")["equity"].shift(1).fillna(START_CAPITAL)
        x["beta_ret"] = x["daily_pnl"] / x["equity_lag"]
        parts.append(x[["variant", "date", "beta_ret"]])
    return pd.concat(parts, ignore_index=True)


def add_periods(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.copy()
    x["year"] = x["date"].dt.year
    x["split"] = np.select(
        [x["year"].le(2021), x["year"].eq(2022), x["year"].ge(2023)],
        ["2018_2021_research", "2022_stress", "2023_2024_touched"],
        default="other",
    )
    return x


def simulate(spec: dict[str, object], beta: pd.DataFrame, signal: pd.DataFrame) -> pd.DataFrame:
    b = beta[beta["variant"].eq(spec["beta"])].copy()
    x = b.merge(signal, on="date", how="inner").sort_values("date")
    equity = START_CAPITAL
    rows = []
    for row in x.itertuples(index=False):
        mixed_ret = float(spec["beta_weight"]) * float(row.beta_ret) + float(spec["signal_weight"]) * float(row.signal_ret)
        daily_pnl = equity * mixed_ret
        equity += daily_pnl
        rows.append(
            {
                "variant": spec["variant"],
                "date": row.date,
                "beta": spec["beta"],
                "beta_ret": float(row.beta_ret),
                "signal_ret": float(row.signal_ret),
                "mixed_ret": mixed_ret,
                "beta_weight": float(spec["beta_weight"]),
                "signal_weight": float(spec["signal_weight"]),
                "daily_pnl": daily_pnl,
                "equity": equity,
                "grossBudget": float(spec["beta_weight"]) + float(spec["signal_weight"]),
            }
        )
    return add_periods(pd.DataFrame(rows))


def summary_row(spec: dict[str, object], daily: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "beta": spec["beta"],
        "betaWeight": float(spec["beta_weight"]),
        "signalWeight": float(spec["signal_weight"]),
        "grossBudget": float(spec["beta_weight"]) + float(spec["signal_weight"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
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


def corr_rows(all_daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variant, group in all_daily.groupby("variant", sort=True):
        rows.append(
            {
                "variant": variant,
                "corrBetaSignal": float(group["beta_ret"].corr(group["signal_ret"])),
                "meanBetaRet": float(group["beta_ret"].mean()),
                "meanSignalRet": float(group["signal_ret"].mean()),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    signal = load_signal_returns()
    beta = load_beta_returns()
    frames = []
    summaries = []
    for spec in VARIANTS:
        daily = simulate(spec, beta, signal)
        frames.append(daily)
        summary = summary_row(spec, daily)
        summaries.append(summary)
        print("VARIANT", spec["variant"], summary, flush=True)
    all_daily = pd.concat(frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "year")).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "split")).to_csv(SPLIT_OUT, index=False)
    corr_rows(all_daily).to_csv(CORR_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_beta_signal_mix.py",
        "inputs": [str(NO_INTRADAY_EQUITY), str(MCAP_BETA_DAILY), str(BETA_EXPANSION_DAILY)],
        "sample_label": "Research/in-sample diagnostics across 2018-2024. 2023-2024 is touched validation, not clean unseen OOS.",
        "method": "Fixed daily return mix of causal benchmark beta-voltarget stream and broad PIT B no-intraday signal stream.",
        "variants": VARIANTS,
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "old_62_usage": "None; signal stream is full broad PIT B nowarmup, beta streams are market-cap/SPY benchmark streams.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SPLIT_OUT), str(CORR_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, CORR_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
