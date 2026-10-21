from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_BREADTH_ALLOCATOR_2026-09-14"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
BENCH_DAILY = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")
BETA_DAILY = Path("STOCKS_PIT_FULL_BETA_VOLTARGET_EXPANSION_2026-09-14_DAILY.csv")

START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SPLIT_OUT = Path(f"{OUT_PREFIX}_SPLITS.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Pre-registered breadth/regime allocator. All breadth inputs are available before
# the simulated trading day via *_pre columns or current-row prev_dayret.
VARIANTS = [
    {
        "variant": "top62_vt25_if_ret20pos55_else_vt16",
        "base_on": "top62_vt25_cap250",
        "base_off": "top62_vt16_cap150",
        "condition": "ret20_pos_frac",
        "op": ">=",
        "threshold": 0.55,
    },
    {
        "variant": "top62_vt25_if_ret20pos60_else_vt16",
        "base_on": "top62_vt25_cap250",
        "base_off": "top62_vt16_cap150",
        "condition": "ret20_pos_frac",
        "op": ">=",
        "threshold": 0.60,
    },
    {
        "variant": "top62_vt25_if_adv5_52_else_vt16",
        "base_on": "top62_vt25_cap250",
        "base_off": "top62_vt16_cap150",
        "condition": "adv_prev_frac_ma5",
        "op": ">=",
        "threshold": 0.52,
    },
    {
        "variant": "top62_vt25_if_adv5_55_else_vt16",
        "base_on": "top62_vt25_cap250",
        "base_off": "top62_vt16_cap150",
        "condition": "adv_prev_frac_ma5",
        "op": ">=",
        "threshold": 0.55,
    },
    {
        "variant": "top62_vt25_if_ret20pos55_else_cash",
        "base_on": "top62_vt25_cap250",
        "base_off": "cash",
        "condition": "ret20_pos_frac",
        "op": ">=",
        "threshold": 0.55,
    },
    {
        "variant": "top62_vt25_if_adv5_52_else_cash",
        "base_on": "top62_vt25_cap250",
        "base_off": "cash",
        "condition": "adv_prev_frac_ma5",
        "op": ">=",
        "threshold": 0.52,
    },
    {
        "variant": "top62_vt25_if_washout35_else_vt16",
        "base_on": "top62_vt25_cap250",
        "base_off": "top62_vt16_cap150",
        "condition": "adv_prev_frac",
        "op": "<=",
        "threshold": 0.35,
    },
    {
        "variant": "top62_vt25_if_gapdown35_else_vt16",
        "base_on": "top62_vt25_cap250",
        "base_off": "top62_vt16_cap150",
        "condition": "gapdown_frac",
        "op": ">=",
        "threshold": 0.35,
    },
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


def load_breadth() -> pd.DataFrame:
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily = daily[(daily["date"] >= START) & (daily["date"] <= END)].copy()
    daily = daily.dropna(subset=["ticker", "prev_dayret", "ret20_pre", "gap"])
    breadth = (
        daily.groupby("date", sort=True)
        .agg(
            names=("ticker", "nunique"),
            adv_prev_frac=("prev_dayret", lambda s: float((s > 0).mean())),
            gapdown_frac=("gap", lambda s: float((s < -0.01).mean())),
            ret20_pos_frac=("ret20_pre", lambda s: float((s > 0).mean())),
            median_ret20=("ret20_pre", "median"),
            median_ret60=("ret60_pre", "median"),
        )
        .reset_index()
    )
    breadth["adv_prev_frac_ma5"] = breadth["adv_prev_frac"].rolling(5, min_periods=5).mean()
    return breadth


def add_periods(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.copy()
    x["year"] = x["date"].dt.year
    x["split"] = np.select(
        [x["year"].le(2021), x["year"].eq(2022), x["year"].ge(2023)],
        ["2018_2021_research", "2022_stress", "2023_2024_touched"],
        default="other",
    )
    return x


def condition_mask(x: pd.Series, op: str, threshold: float) -> pd.Series:
    if op == ">=":
        return x >= threshold
    if op == "<=":
        return x <= threshold
    raise ValueError(f"unsupported op: {op}")


def simulate(spec: dict[str, object], streams: pd.DataFrame, breadth: pd.DataFrame) -> pd.DataFrame:
    on = streams[streams["variant"].eq(spec["base_on"])][["date", "ret"]].rename(columns={"ret": "ret_on"})
    if spec["base_off"] == "cash":
        off = on[["date"]].assign(ret_off=0.0)
    else:
        off = streams[streams["variant"].eq(spec["base_off"])][["date", "ret"]].rename(columns={"ret": "ret_off"})
    x = on.merge(off, on="date", how="inner").merge(breadth, on="date", how="inner")
    x = x.sort_values("date")
    cond = condition_mask(x[str(spec["condition"])], str(spec["op"]), float(spec["threshold"])).fillna(False)
    x["risk_on"] = cond
    x["chosen_ret"] = np.where(x["risk_on"], x["ret_on"], x["ret_off"])
    equity = START_CAPITAL
    rows = []
    for row in x.itertuples(index=False):
        daily_pnl = equity * float(row.chosen_ret)
        equity += daily_pnl
        rows.append(
            {
                "variant": spec["variant"],
                "date": row.date,
                "base_on": spec["base_on"],
                "base_off": spec["base_off"],
                "condition": spec["condition"],
                "threshold": float(spec["threshold"]),
                "risk_on": bool(row.risk_on),
                "ret_on": float(row.ret_on),
                "ret_off": float(row.ret_off),
                "chosen_ret": float(row.chosen_ret),
                "daily_pnl": daily_pnl,
                "equity": equity,
                "adv_prev_frac": float(row.adv_prev_frac),
                "adv_prev_frac_ma5": float(row.adv_prev_frac_ma5) if not pd.isna(row.adv_prev_frac_ma5) else np.nan,
                "ret20_pos_frac": float(row.ret20_pos_frac),
                "gapdown_frac": float(row.gapdown_frac),
                "names": int(row.names),
            }
        )
    return add_periods(pd.DataFrame(rows))


def summary_row(spec: dict[str, object], daily: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "baseOn": spec["base_on"],
        "baseOff": spec["base_off"],
        "condition": spec["condition"],
        "op": spec["op"],
        "threshold": float(spec["threshold"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "pctRiskOnDays": float(daily["risk_on"].mean()),
        "avgNamesBreadth": float(daily["names"].mean()),
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
                "pctRiskOnDays": float(group["risk_on"].mean()),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    beta = returns_from_daily(BETA_DAILY)
    bench = returns_from_daily(BENCH_DAILY)
    streams = pd.concat([beta, bench], ignore_index=True)
    breadth = load_breadth()
    frames = []
    summaries = []
    for spec in VARIANTS:
        daily = simulate(spec, streams, breadth)
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
        "script": "raits/research/stocks_pit_full_breadth_allocator.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(BENCH_DAILY), str(BETA_DAILY)],
        "sample_label": "Research/in-sample diagnostics across 2018-2024. 2023-2024 is touched validation, not clean unseen OOS.",
        "method": "Pre-registered breadth allocator. Breadth uses prev_dayret, gap, and *_pre features available before the simulated trading day.",
        "variants": VARIANTS,
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "old_62_usage": "None.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SPLIT_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
