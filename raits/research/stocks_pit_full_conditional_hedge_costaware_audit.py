from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_CONDITIONAL_HEDGE_COSTAWARE_AUDIT_2026-09-17"
BENCH_DAILY = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")
BENCH_CONTRIB = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_TICKER_CONTRIB.csv")
BETA_DAILY = Path("STOCKS_PIT_FULL_BETA_VOLTARGET_EXPANSION_2026-09-14_DAILY.csv")
START_CAPITAL = 100_000.0
TURNOVER_COST_BPS = 4.0
FINANCING_ANNUAL_RATE = 0.025
SHORT_BORROW_ANNUAL_RATE = 0.01
BASE_VARIANT = "top62_vt20_cap200"
TOP62_VARIANT = "market_cap_top62_equal_weight"
BROAD_VARIANT = "broad_pit_equal_weight"

# Frozen follow-up to sections 6.158-6.159. No trigger or rule changes.
VARIANTS = [
    {"variant": "top62_vt20_broadhedge50_costaware", "hedge_weight": 0.50},
    {"variant": "top62_vt20_broadhedge75_costaware", "hedge_weight": 0.75},
]

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peak = equity.cummax()
    return float((equity - peak).min()), float((equity / peak - 1.0).min())


def sharpe(pnl: pd.Series) -> float:
    std = float(pnl.std())
    return float(pnl.mean() / std * math.sqrt(252)) if std > 0 else float("nan")


def cagr(equity: pd.Series, dates: pd.Series) -> float:
    years = max((dates.max() - dates.min()).days / 365.25, 1e-9)
    return float((equity.iloc[-1] / START_CAPITAL) ** (1.0 / years) - 1.0)


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    bench = pd.read_csv(BENCH_DAILY, parse_dates=["date"])
    bench = bench[bench["variant"].isin([TOP62_VARIANT, BROAD_VARIANT])].copy()
    bench = bench.sort_values(["variant", "date"])
    bench["equity_lag"] = bench.groupby("variant")["equity"].shift(1).fillna(START_CAPITAL)

    frames = []
    for chunk in pd.read_csv(BENCH_CONTRIB, chunksize=500_000):
        keep = chunk[chunk["variant"].isin([TOP62_VARIANT, BROAD_VARIANT])]
        if not keep.empty:
            frames.append(keep)
    contrib = pd.concat(frames, ignore_index=True)
    contrib["date"] = pd.to_datetime(contrib["date"])
    contrib = contrib.merge(bench[["variant", "date", "equity_lag", "names"]], on=["variant", "date"], how="inner")
    contrib["component_ret"] = contrib["pnl"] / contrib["equity_lag"]
    return bench, contrib


def control_frame(bench: pd.DataFrame) -> pd.DataFrame:
    beta = pd.read_csv(BETA_DAILY, parse_dates=["date"])
    beta = beta[beta["variant"].eq(BASE_VARIANT)][["date", "exposure"]].copy()
    broad = bench[bench["variant"].eq(BROAD_VARIANT)][["date", "daily_ret"]].sort_values("date").copy()
    broad["trail20"] = (1.0 + broad["daily_ret"]).rolling(20, min_periods=20).apply(np.prod, raw=True).shift(1) - 1.0
    broad["hedge_on"] = broad["trail20"] <= -0.05
    return beta.merge(broad[["date", "trail20", "hedge_on"]], on="date", how="inner")


def effective_ticker_count(by_ticker: pd.Series) -> float:
    positive = by_ticker[by_ticker > 0]
    source = positive if positive.sum() > 0 else by_ticker.abs()
    total = float(source.sum())
    if total <= 0:
        return 0.0
    weights = source / total
    return float(1.0 / weights.pow(2).sum())


def concentration_row(variant: str, contrib: pd.DataFrame) -> dict[str, object]:
    by_ticker = contrib.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
    total = float(by_ticker.sum())
    denominator = total if total > 0 else float(by_ticker.abs().sum())
    row: dict[str, object] = {
        "variant": variant,
        "tickers": int(len(by_ticker)),
        "effectiveTickerCount": effective_ticker_count(by_ticker),
        "topTicker": str(by_ticker.index[0]),
    }
    for n in (1, 3, 5, 10):
        top = float(by_ticker.head(n).sum())
        row[f"top{n}Pnl"] = top
        row[f"top{n}Share"] = top / denominator if denominator else float("nan")
    return row


def simulate(
    spec: dict[str, object], bench: pd.DataFrame, contrib: pd.DataFrame, controls: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    hedge_weight = float(spec["hedge_weight"])
    ctrl = controls.copy()
    ctrl["hedge_exposure"] = np.where(ctrl["hedge_on"], hedge_weight, 0.0)

    top = contrib[contrib["variant"].eq(TOP62_VARIANT)].merge(ctrl[["date", "exposure"]], on="date", how="inner")
    top["target_weight"] = top["exposure"] / top["names"]
    top["portfolio_ret_component"] = top["component_ret"] * top["exposure"]
    broad = contrib[contrib["variant"].eq(BROAD_VARIANT)].merge(ctrl[["date", "hedge_exposure"]], on="date", how="inner")
    broad["target_weight"] = -broad["hedge_exposure"] / broad["names"]
    broad["portfolio_ret_component"] = -broad["component_ret"] * broad["hedge_exposure"]

    components = pd.concat(
        [top[["date", "ticker", "target_weight", "portfolio_ret_component"]], broad[["date", "ticker", "target_weight", "portfolio_ret_component"]]],
        ignore_index=True,
    ).groupby(["date", "ticker"], as_index=False).sum()
    weights = components.pivot(index="date", columns="ticker", values="target_weight").fillna(0.0).sort_index()
    returns = components.pivot(index="date", columns="ticker", values="portfolio_ret_component").fillna(0.0).reindex(weights.index)
    changes = weights.diff().fillna(weights)
    turnover = changes.abs().sum(axis=1)
    gross = weights.abs().sum(axis=1)
    net = weights.sum(axis=1)
    short_gross = weights.clip(upper=0).abs().sum(axis=1)

    equity = START_CAPITAL
    daily_rows = []
    contrib_rows = []
    ctrl_by_date = ctrl.set_index("date")
    cost_rate = TURNOVER_COST_BPS / 10_000.0
    for date in weights.index:
        ticker_returns = returns.loc[date]
        gross_ret = float(ticker_returns.sum())
        turnover_cost = equity * float(turnover.loc[date]) * cost_rate
        borrow_cost = equity * float(short_gross.loc[date]) * SHORT_BORROW_ANNUAL_RATE / 252.0
        financing_cost = equity * max(float(gross.loc[date]) - 1.0, 0.0) * FINANCING_ANNUAL_RATE / 252.0
        pnl_by_ticker = equity * ticker_returns
        if turnover_cost > 0 and float(turnover.loc[date]) > 0:
            pnl_by_ticker -= changes.loc[date].abs() / float(turnover.loc[date]) * turnover_cost
        if borrow_cost > 0 and float(short_gross.loc[date]) > 0:
            pnl_by_ticker -= weights.loc[date].clip(upper=0).abs() / float(short_gross.loc[date]) * borrow_cost
        if financing_cost > 0 and float(gross.loc[date]) > 0:
            pnl_by_ticker -= weights.loc[date].abs() / float(gross.loc[date]) * financing_cost
        daily_pnl = float(pnl_by_ticker.sum())
        equity += daily_pnl
        contrib_rows.extend(
            {"variant": spec["variant"], "date": date, "ticker": ticker, "pnl": float(pnl)}
            for ticker, pnl in pnl_by_ticker.items()
            if float(pnl) != 0.0
        )
        daily_rows.append(
            {
                "variant": spec["variant"],
                "date": date,
                "daily_pnl": daily_pnl,
                "equity": equity,
                "gross_ret_before_costs": gross_ret,
                "turnover_cost": turnover_cost,
                "borrow_cost": borrow_cost,
                "financing_cost": financing_cost,
                "turnover": float(turnover.loc[date]),
                "gross_exposure": float(gross.loc[date]),
                "net_exposure": float(net.loc[date]),
                "short_gross": float(short_gross.loc[date]),
                "hedge_on": bool(ctrl_by_date.at[date, "hedge_on"]),
            }
        )
    daily = pd.DataFrame(daily_rows)
    daily["year"] = daily["date"].dt.year
    return daily, pd.DataFrame(contrib_rows)


def summary_row(spec: dict[str, object], daily: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "hedgeWeight": float(spec["hedge_weight"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "turnoverCost": float(daily["turnover_cost"].sum()),
        "borrowCost": float(daily["borrow_cost"].sum()),
        "financingCost": float(daily["financing_cost"].sum()),
        "avgGrossExposure": float(daily["gross_exposure"].mean()),
        "maxGrossExposure": float(daily["gross_exposure"].max()),
        "pctDaysHedged": float(daily["hedge_on"].mean()),
    }


def yearly_rows(daily: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for (variant, year), group in daily.groupby(["variant", "year"], sort=True):
        curve = START_CAPITAL + group["daily_pnl"].cumsum()
        dd, dd_pct = max_drawdown(curve)
        rows.append({"variant": variant, "year": int(year), "pnl": float(group["daily_pnl"].sum()), "ddDollarSubset": dd, "ddPctSubset": dd_pct, "sharpe": sharpe(group["daily_pnl"])})
    return rows


def main() -> None:
    bench, contrib = load_inputs()
    controls = control_frame(bench)
    summaries = []
    yearly = []
    concentration = []
    daily_frames = []
    contrib_frames = []
    for spec in VARIANTS:
        daily, ticker_contrib = simulate(spec, bench, contrib, controls)
        summaries.append(summary_row(spec, daily))
        yearly.extend(yearly_rows(daily))
        concentration.append(concentration_row(str(spec["variant"]), ticker_contrib))
        daily_frames.append(daily)
        contrib_frames.append(ticker_contrib)
        print("HEDGE_AUDIT", summaries[-1], flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    qa = pd.DataFrame([{"contribRows": len(contrib), "dates": controls["date"].nunique(), "top62Tickers": contrib[contrib["variant"].eq(TOP62_VARIANT)]["ticker"].nunique(), "broadTickers": contrib[contrib["variant"].eq(BROAD_VARIANT)]["ticker"].nunique()}])
    qa.to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_conditional_hedge_costaware_audit.py",
        "inputs": [str(BENCH_DAILY), str(BENCH_CONTRIB), str(BETA_DAILY)],
        "method": "Constituent-level rebuild of top62 vt20 plus lagged broad-PIT 20-day-loss conditional short hedge; target weights net overlapping constituents before costs.",
        "costs": f"{TURNOVER_COST_BPS} bps full target-vector turnover, {SHORT_BORROW_ANNUAL_RATE:.1%} annual borrow on net short gross, and {FINANCING_ANNUAL_RATE:.1%} annual financing on gross above 1x.",
        "sample_label": "Research/touched 2018-2024 only. 2023-2024 is touched, not clean unseen OOS. No 2025-2026 opened.",
        "leakage_controls": "Base vol target and broad 20-day trigger are shifted/causal source rules; PIT benchmark constituents are rebuilt daily; no old manual 62 list.",
        "rule_selection_effect": "None. The 50% and 75% hedge rows were frozen from prior diagnostics; this audit changes accounting/costs only.",
        "trade_selection_effect": "Full daily target vectors, overlap netting, constituent refill and costs are rebuilt; no PnL subtraction.",
        "variants": VARIANTS,
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(DAILY_OUT), str(CONTRIB_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, DAILY_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
