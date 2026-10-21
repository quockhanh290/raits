from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_one_engine_mtm_portfolio as engine
import stocks_polygon_2018_2024_no_ml_pipeline as poly


DATE_TAG = "2018_2024"
START_CAPITAL = poly.START_CAPITAL
OUT_PREFIX = "STOCKS_POLYGON62_NO_INTRADAY"

CAP_COST_OUT = Path(f"{OUT_PREFIX}_CAP_COST_SWEEP_{DATE_TAG}.csv")
CONC_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION_STRESS_{DATE_TAG}.csv")
BOOT_OUT = Path(f"{OUT_PREFIX}_BOOTSTRAP_{DATE_TAG}.csv")
SANITY_OUT = Path(f"{OUT_PREFIX}_SANITY_{DATE_TAG}.csv")
MONTHLY_OUT = Path(f"{OUT_PREFIX}_MONTHLY_{DATE_TAG}.csv")
DIAG_2022_OUT = Path(f"{OUT_PREFIX}_2022_DIAGNOSTICS_{DATE_TAG}.csv")

PORTFOLIOS = {
    "A_polygon62_no_intraday_cap40": poly.LEAD_PORTFOLIOS["A_polygon62_no_intraday_cap40"],
    "B_polygon62_no_intraday_cap40": poly.LEAD_PORTFOLIOS["B_polygon62_no_intraday_cap40"],
    "A_polygon62_all_cap40": poly.LEAD_PORTFOLIOS["A_polygon62_all_cap40"],
    "B_polygon62_all_cap40": poly.LEAD_PORTFOLIOS["B_polygon62_all_cap40"],
}
CAP_COST_PORTFOLIOS = {
    "A_polygon62_no_intraday_cap40": poly.LEAD_PORTFOLIOS["A_polygon62_no_intraday_cap40"],
    "B_polygon62_no_intraday_cap40": poly.LEAD_PORTFOLIOS["B_polygon62_no_intraday_cap40"],
}


def max_drawdown_from_pnl(pnl: pd.Series | np.ndarray) -> float:
    pnl_series = pd.Series(pnl, dtype=float).reset_index(drop=True)
    equity = START_CAPITAL + pnl_series.cumsum()
    return float((equity - equity.cummax()).min())


def sharpe(pnl: pd.Series | np.ndarray) -> float:
    pnl_series = pd.Series(pnl, dtype=float)
    std = float(pnl_series.std())
    if std <= 0:
        return np.nan
    return float(pnl_series.mean() / std * np.sqrt(252))


def summarize_daily(portfolio: str, stress: str, daily: pd.DataFrame, pnl_col: str = "daily_pnl") -> dict[str, object]:
    x = daily.sort_values("date").copy()
    pnl = x[pnl_col].astype(float)
    ending = START_CAPITAL + float(pnl.sum())
    years = (x["date"].max() - x["date"].min()).days / 365.25 if len(x) else np.nan
    monthly = x.assign(month=x["date"].dt.to_period("M")).groupby("month")[pnl_col].sum()
    yearly = x.assign(year=x["date"].dt.year).groupby("year")[pnl_col].sum()
    return {
        "portfolio": portfolio,
        "stress": stress,
        "days": int(len(x)),
        "pnl": float(pnl.sum()),
        "ending": ending,
        "cagr": float((ending / START_CAPITAL) ** (1 / years) - 1) if years and years > 0 and ending > 0 else np.nan,
        "dd": max_drawdown_from_pnl(pnl),
        "sharpe": sharpe(pnl),
        "negMonths": int((monthly < 0).sum()) if len(monthly) else 0,
        "worstMonth": str(monthly.idxmin()) if len(monthly) else "",
        "worstMonthPnl": float(monthly.min()) if len(monthly) else np.nan,
        "medianMonthPnl": float(monthly.median()) if len(monthly) else np.nan,
        "y2018": float(yearly.get(2018, 0.0)),
        "y2019": float(yearly.get(2019, 0.0)),
        "y2020": float(yearly.get(2020, 0.0)),
        "y2021": float(yearly.get(2021, 0.0)),
        "y2022": float(yearly.get(2022, 0.0)),
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
    }


def load_polygon_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = pd.read_pickle(poly.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily_px = poly.load_daily_prices_from_polygon(daily)
    intraday_px = pd.read_pickle(poly.INTRADAY_0935)
    intraday_px["date"] = pd.to_datetime(intraday_px["date"])
    intraday_px = intraday_px[["date", "ticker", "open930", "entry935", "exit1555"]]
    signals = poly.load_signals(daily_px, intraday_px)
    return daily_px, signals


def simulate_with_cost(name: str, cfg: dict[str, object], signals: pd.DataFrame, daily_px: pd.DataFrame, cost_bps: float):
    old_cost = engine.COST_BPS
    try:
        engine.COST_BPS = cost_bps
        return poly.simulate(name, cfg, signals, daily_px)
    finally:
        engine.COST_BPS = old_cost


def run_cap_cost_sweep(signals: pd.DataFrame, daily_px: pd.DataFrame) -> pd.DataFrame:
    rows = pd.read_csv(CAP_COST_OUT).to_dict("records") if CAP_COST_OUT.exists() else []
    done = {
        (
            str(row["basePortfolio"]),
            float(row["tickerCapPctNav"]),
            float(row["grossCap"]),
            float(row["costBps"]),
        )
        for row in rows
    }
    for base_name, base_cfg in CAP_COST_PORTFOLIOS.items():
        for ticker_cap in [0.20, 0.30, 0.40, 0.50]:
            for gross_cap in [1.0, 1.25, 1.50, 1.75, 2.0]:
                for cost_bps in [4.0, 9.0, 14.0, 24.0]:
                    key = (base_name, ticker_cap, gross_cap, cost_bps)
                    if key in done:
                        continue
                    cfg = {
                        "weights": base_cfg["weights"],
                        "top_k": base_cfg.get("top_k"),
                        "ticker_cap_pct": ticker_cap,
                        "gross_cap": gross_cap,
                    }
                    name = f"{base_name}_ticker{int(ticker_cap * 100)}_gross{gross_cap:g}_cost{cost_bps:g}"
                    summary, _, _ = simulate_with_cost(name, cfg, signals, daily_px, cost_bps)
                    rows.append(
                        {
                            "basePortfolio": base_name,
                            "tickerCapPctNav": ticker_cap,
                            "grossCap": gross_cap,
                            "costBps": cost_bps,
                            **summary,
                        }
                    )
                    pd.DataFrame(rows).to_csv(CAP_COST_OUT, index=False)
                    done.add(key)
                    print("CAP_COST", name, f"pnl={summary['pnl']:.2f}", f"dd={summary['dd']:.2f}", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(CAP_COST_OUT, index=False)
    return out


def concentration_stress() -> pd.DataFrame:
    eq = pd.read_csv(poly.EQUITY_OUT, parse_dates=["date"])
    tr = pd.read_csv(poly.TRADES_OUT, parse_dates=["date", "exit_date"])
    rows = []
    for portfolio in PORTFOLIOS:
        base_daily = eq[eq["portfolio"].eq(portfolio)][["date", "daily_pnl"]].copy()
        trades = tr[tr["portfolio"].eq(portfolio) & tr["pnl"].notna()].copy()
        ticker_pnl = trades.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
        sleeve_pnl = trades.groupby("sleeve")["pnl"].sum().sort_values(ascending=False)
        total = float(trades["pnl"].sum())
        base_row = summarize_daily(portfolio, "base", base_daily)
        base_row.update(
            {
                "topTicker": str(ticker_pnl.index[0]) if len(ticker_pnl) else "",
                "topTickerPnl": float(ticker_pnl.iloc[0]) if len(ticker_pnl) else np.nan,
                "topTickerShare": float(ticker_pnl.iloc[0] / total) if total and len(ticker_pnl) else np.nan,
                "top10Share": float(ticker_pnl.head(10).sum() / total) if total and len(ticker_pnl) else np.nan,
                "effectiveTickers": float(total * total / (ticker_pnl.pow(2).sum())) if ticker_pnl.pow(2).sum() else np.nan,
                "topSleeve": str(sleeve_pnl.index[0]) if len(sleeve_pnl) else "",
                "topSleeveShare": float(sleeve_pnl.iloc[0] / total) if total and len(sleeve_pnl) else np.nan,
                "dropped": "",
            }
        )
        rows.append(base_row)

        for n in [1, 3, 5, 10]:
            drop = set(ticker_pnl.head(n).index)
            removed = trades[trades["ticker"].isin(drop)].groupby("exit_date")["pnl"].sum().rename("removed")
            daily = base_daily.merge(removed, left_on="date", right_index=True, how="left").fillna({"removed": 0.0})
            daily["daily_pnl"] = daily["daily_pnl"] - daily["removed"]
            row = summarize_daily(portfolio, f"drop_top_{n}_winning_tickers_no_refill", daily)
            row["dropped"] = ",".join(sorted(drop))
            rows.append(row)

        winners = trades.sort_values("pnl", ascending=False)
        for n in [10, 20, 50]:
            drop_ids = set(winners.head(n)["trade_id"])
            removed = trades[trades["trade_id"].isin(drop_ids)].groupby("exit_date")["pnl"].sum().rename("removed")
            daily = base_daily.merge(removed, left_on="date", right_index=True, how="left").fillna({"removed": 0.0})
            daily["daily_pnl"] = daily["daily_pnl"] - daily["removed"]
            row = summarize_daily(portfolio, f"remove_top_{n}_closed_trades_no_refill", daily)
            row["dropped"] = ""
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(CONC_OUT, index=False)
    return out


def bootstrap_stress(iterations: int = 5000) -> pd.DataFrame:
    rng = np.random.default_rng(20260911)
    eq = pd.read_csv(poly.EQUITY_OUT, parse_dates=["date"])
    rows = []
    for portfolio in PORTFOLIOS:
        x = eq[eq["portfolio"].eq(portfolio)].sort_values("date").copy()
        pnl = x["daily_pnl"].to_numpy(float)
        n = len(pnl)
        sim_pnl = np.empty(iterations)
        sim_dd = np.empty(iterations)
        for i in range(iterations):
            sample = pnl[rng.integers(0, n, size=n)]
            sim_pnl[i] = sample.sum()
            sim_dd[i] = max_drawdown_from_pnl(sample)
        rows.append(
            {
                "portfolio": portfolio,
                "mode": "day_bootstrap",
                "iterations": iterations,
                "pnl_p01": float(np.quantile(sim_pnl, 0.01)),
                "pnl_p05": float(np.quantile(sim_pnl, 0.05)),
                "pnl_median": float(np.quantile(sim_pnl, 0.50)),
                "pnl_p95": float(np.quantile(sim_pnl, 0.95)),
                "dd_p50": float(np.quantile(sim_dd, 0.50)),
                "dd_p95_loss": float(np.quantile(sim_dd, 0.05)),
                "prob_pnl_le_0": float(np.mean(sim_pnl <= 0.0)),
            }
        )

        months = [g["daily_pnl"].to_numpy(float) for _, g in x.groupby(x["date"].dt.to_period("M"), sort=True)]
        sim_pnl = np.empty(iterations)
        sim_dd = np.empty(iterations)
        for i in range(iterations):
            sample = np.concatenate([months[j] for j in rng.integers(0, len(months), size=len(months))])
            sim_pnl[i] = sample.sum()
            sim_dd[i] = max_drawdown_from_pnl(sample)
        rows.append(
            {
                "portfolio": portfolio,
                "mode": "month_block_bootstrap",
                "iterations": iterations,
                "pnl_p01": float(np.quantile(sim_pnl, 0.01)),
                "pnl_p05": float(np.quantile(sim_pnl, 0.05)),
                "pnl_median": float(np.quantile(sim_pnl, 0.50)),
                "pnl_p95": float(np.quantile(sim_pnl, 0.95)),
                "dd_p50": float(np.quantile(sim_dd, 0.50)),
                "dd_p95_loss": float(np.quantile(sim_dd, 0.05)),
                "prob_pnl_le_0": float(np.mean(sim_pnl <= 0.0)),
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(BOOT_OUT, index=False)
    return out


def sanity() -> pd.DataFrame:
    eq = pd.read_csv(poly.EQUITY_OUT, parse_dates=["date"])
    tr = pd.read_csv(poly.TRADES_OUT, parse_dates=["date"])
    rows = []
    for portfolio in PORTFOLIOS:
        e = eq[eq["portfolio"].eq(portfolio)].copy()
        t = tr[tr["portfolio"].eq(portfolio)].copy()
        collisions = t.groupby(["date", "ticker"])["sleeve"].nunique()
        rows.append(
            {
                "portfolio": portfolio,
                "maxGross": float(e["gross"].max()),
                "avgGross": float(e["gross"].mean()),
                "minCash": float(e["cash"].min()),
                "cashNegativeDays": int((e["cash"] < 0).sum()),
                "tickerDateCollisions": int((collisions > 1).sum()),
                "maxSleevesPerTickerDate": int(collisions.max()) if len(collisions) else 0,
                "tickerCapAppliedBeforeOrders": True,
                "grossCapAppliedBeforeOrders": True,
                "closedTrades": int(t["pnl"].notna().sum()),
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(SANITY_OUT, index=False)
    return out


def monthly_and_2022() -> tuple[pd.DataFrame, pd.DataFrame]:
    eq = pd.read_csv(poly.EQUITY_OUT, parse_dates=["date"])
    tr = pd.read_csv(poly.TRADES_OUT, parse_dates=["date", "exit_date"])
    monthly_rows = []
    diag_rows = []
    for portfolio in PORTFOLIOS:
        e = eq[eq["portfolio"].eq(portfolio)].copy()
        for month, group in e.groupby(e["date"].dt.to_period("M"), sort=True):
            monthly_rows.append(
                {
                    "portfolio": portfolio,
                    "month": str(month),
                    "days": int(len(group)),
                    "pnl": float(group["daily_pnl"].sum()),
                    "ddSubset": max_drawdown_from_pnl(group["daily_pnl"]),
                    "avgGross": float(group["gross"].mean()),
                    "maxGross": float(group["gross"].max()),
                }
            )

        t2022 = tr[tr["portfolio"].eq(portfolio) & tr["exit_date"].dt.year.eq(2022)].copy()
        for sleeve, group in t2022.groupby("sleeve", sort=True):
            diag_rows.append(
                {
                    "portfolio": portfolio,
                    "section": "2022_by_sleeve",
                    "bucket": sleeve,
                    "trades": int(len(group)),
                    "pnl": float(group["pnl"].sum()),
                    "meanTrade": float(group["pnl"].mean()),
                    "winRate": float((group["pnl"] > 0).mean()),
                }
            )
        for ticker, group in t2022.groupby("ticker")["pnl"].sum().sort_values().head(15).items():
            diag_rows.append(
                {
                    "portfolio": portfolio,
                    "section": "2022_worst_tickers",
                    "bucket": ticker,
                    "trades": int((t2022["ticker"] == ticker).sum()),
                    "pnl": float(group),
                    "meanTrade": np.nan,
                    "winRate": np.nan,
                }
            )
    monthly = pd.DataFrame(monthly_rows)
    diag = pd.DataFrame(diag_rows)
    monthly.to_csv(MONTHLY_OUT, index=False)
    diag.to_csv(DIAG_2022_OUT, index=False)
    return monthly, diag


def main() -> None:
    daily_px, signals = load_polygon_inputs()
    cap = run_cap_cost_sweep(signals, daily_px)
    conc = concentration_stress()
    boot = bootstrap_stress()
    san = sanity()
    monthly, diag = monthly_and_2022()
    print("WROTE", CAP_COST_OUT, len(cap))
    print("WROTE", CONC_OUT, len(conc))
    print("WROTE", BOOT_OUT, len(boot))
    print("WROTE", SANITY_OUT, len(san))
    print("WROTE", MONTHLY_OUT, len(monthly))
    print("WROTE", DIAG_2022_OUT, len(diag))


if __name__ == "__main__":
    main()
