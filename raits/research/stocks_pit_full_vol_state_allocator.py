from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_VOL_STATE_ALLOCATOR_2026-09-14"
BENCH_DAILY = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")
BETA_DAILY = Path("STOCKS_PIT_FULL_BETA_VOLTARGET_EXPANSION_2026-09-14_DAILY.csv")
RISK_DAILY = Path("STOCKS_PIT_FULL_MCAP_BETA_RISK_CONTROL_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SPLIT_OUT = Path(f"{OUT_PREFIX}_SPLITS.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Pre-registered volatility-state allocator. State is computed from trailing
# benchmark returns shifted by one day; no variant is selected after measuring.
VARIANTS = [
    {"variant": "top62_vt25_broadvol20_25_else_vt16", "risk_on": "top62_vt25_cap250", "risk_off": "top62_vt16_cap150", "state_source": "broad_pit_equal_weight", "lookback": 20, "vol_threshold": 0.25},
    {"variant": "top62_vt25_broadvol20_30_else_vt16", "risk_on": "top62_vt25_cap250", "risk_off": "top62_vt16_cap150", "state_source": "broad_pit_equal_weight", "lookback": 20, "vol_threshold": 0.30},
    {"variant": "top62_vt25_broadvol20_25_else_vt12", "risk_on": "top62_vt25_cap250", "risk_off": "top62_voltarget_12pct_cap100", "state_source": "broad_pit_equal_weight", "lookback": 20, "vol_threshold": 0.25},
    {"variant": "top62_vt25_broadvol20_25_else_cash", "risk_on": "top62_vt25_cap250", "risk_off": "cash", "state_source": "broad_pit_equal_weight", "lookback": 20, "vol_threshold": 0.25},
    {"variant": "top62_vt25_broadvol60_22_else_vt16", "risk_on": "top62_vt25_cap250", "risk_off": "top62_vt16_cap150", "state_source": "broad_pit_equal_weight", "lookback": 60, "vol_threshold": 0.22},
    {"variant": "top62_vt25_spyvol20_25_else_spyvt16", "risk_on": "top62_vt25_cap250", "risk_off": "spy_vt16_cap150", "state_source": "spy_buy_hold", "lookback": 20, "vol_threshold": 0.25},
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


def state_frame(streams: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    source = streams[streams["variant"].eq(spec["state_source"])][["date", "ret"]].sort_values("date").copy()
    lookback = int(spec["lookback"])
    source["realized_vol"] = source["ret"].rolling(lookback, min_periods=lookback).std().shift(1) * math.sqrt(252)
    source["risk_on_state"] = (source["realized_vol"] <= float(spec["vol_threshold"])).fillna(True)
    return source[["date", "realized_vol", "risk_on_state"]]


def simulate(spec: dict[str, object], streams: pd.DataFrame) -> pd.DataFrame:
    on = streams[streams["variant"].eq(spec["risk_on"])][["date", "ret"]].rename(columns={"ret": "ret_on"})
    if spec["risk_off"] == "cash":
        off = on[["date"]].assign(ret_off=0.0)
    else:
        off = streams[streams["variant"].eq(spec["risk_off"])][["date", "ret"]].rename(columns={"ret": "ret_off"})
    x = on.merge(off, on="date", how="inner").merge(state_frame(streams, spec), on="date", how="inner")
    x = x.sort_values("date")
    x["chosen_ret"] = np.where(x["risk_on_state"], x["ret_on"], x["ret_off"])
    equity = START_CAPITAL
    rows = []
    for row in x.itertuples(index=False):
        daily_pnl = equity * float(row.chosen_ret)
        equity += daily_pnl
        rows.append(
            {
                "variant": spec["variant"],
                "date": row.date,
                "risk_on": spec["risk_on"],
                "risk_off": spec["risk_off"],
                "state_source": spec["state_source"],
                "realized_vol": float(row.realized_vol) if not pd.isna(row.realized_vol) else np.nan,
                "risk_on_state": bool(row.risk_on_state),
                "ret_on": float(row.ret_on),
                "ret_off": float(row.ret_off),
                "chosen_ret": float(row.chosen_ret),
                "daily_pnl": daily_pnl,
                "equity": equity,
            }
        )
    return add_periods(pd.DataFrame(rows))


def summary_row(spec: dict[str, object], daily: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "riskOn": spec["risk_on"],
        "riskOff": spec["risk_off"],
        "stateSource": spec["state_source"],
        "lookback": int(spec["lookback"]),
        "volThreshold": float(spec["vol_threshold"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "pctRiskOffDays": float((~daily["risk_on_state"]).mean()),
        "avgRealizedVol": float(daily["realized_vol"].mean()),
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
                "pctRiskOffDays": float((~group["risk_on_state"]).mean()),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    bench = returns_from_daily(BENCH_DAILY)
    beta = returns_from_daily(BETA_DAILY)
    risk = returns_from_daily(RISK_DAILY)
    streams = pd.concat([bench, beta, risk], ignore_index=True)
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
        "script": "raits/research/stocks_pit_full_vol_state_allocator.py",
        "inputs": [str(BENCH_DAILY), str(BETA_DAILY), str(RISK_DAILY)],
        "sample_label": "Research/in-sample diagnostics across 2018-2024. 2023-2024 is touched validation, not clean unseen OOS.",
        "method": "Pre-registered volatility-state allocator. Risk-on stream is top62_vt25; risk-off stream chosen by trailing realized vol state shifted by one day.",
        "variants": VARIANTS,
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "old_62_usage": "None.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SPLIT_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
