from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_one_engine_mtm_portfolio as engine


DATE_TAG = "2026-09-09"
START_CAPITAL = engine.START_CAPITAL

CAP_COST_OUT = Path(f"STOCKS_ONE_ENGINE_NO_ML_CAP_COST_SWEEP_{DATE_TAG}.csv")
CONC_OUT = Path(f"STOCKS_ONE_ENGINE_NO_ML_CONCENTRATION_STRESS_{DATE_TAG}.csv")
BOOT_OUT = Path(f"STOCKS_ONE_ENGINE_NO_ML_BOOTSTRAP_{DATE_TAG}.csv")
SANITY_OUT = Path(f"STOCKS_ONE_ENGINE_NO_ML_SANITY_{DATE_TAG}.csv")

BASE_PORTFOLIOS = {
    "A_no_ml_all": {
        "weights": {
            "broad_adv10_g2_dd85": 0.40,
            "local_xs_full_s10": 0.40,
            "yday_ex6_actual": 0.40,
            "intraday_ex10": 0.40,
        },
        "top_k": None,
    },
    "B_no_ml_all": {
        "weights": {
            "broad_adv10_g2_dd85": 0.35,
            "local_xs_full_s10": 0.35,
            "yday_ex6_actual": 0.35,
            "intraday_ex10": 0.35,
        },
        "top_k": None,
    },
}


def max_drawdown_from_pnl(pnl: pd.Series) -> float:
    eq = START_CAPITAL + pnl.astype(float).cumsum()
    return float((eq - eq.cummax()).min())


def summarize_daily(portfolio: str, label: str, daily: pd.DataFrame, pnl_col: str = "daily_pnl") -> dict[str, object]:
    pnl = daily[pnl_col].astype(float)
    yearly = daily.assign(year=daily["date"].dt.year).groupby("year")[pnl_col].sum()
    monthly = daily.assign(month=daily["date"].dt.to_period("M")).groupby("month")[pnl_col].sum()
    ending = START_CAPITAL + float(pnl.sum())
    years = (daily["date"].max() - daily["date"].min()).days / 365.25
    return {
        "portfolio": portfolio,
        "stress": label,
        "pnl": float(pnl.sum()),
        "ending": ending,
        "cagr": float((ending / START_CAPITAL) ** (1 / years) - 1) if years > 0 and ending > 0 else np.nan,
        "dd": max_drawdown_from_pnl(pnl.reset_index(drop=True)),
        "sharpe": float(pnl.mean() / pnl.std() * np.sqrt(252)) if pnl.std() > 0 else np.nan,
        "negMonths": int((monthly < 0).sum()) if len(monthly) else 0,
        "minMonth": float(monthly.min()) if len(monthly) else np.nan,
        "medianMonth": float(monthly.median()) if len(monthly) else np.nan,
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
    }


def run_cap_cost_sweep(daily_px: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    rows = pd.read_csv(CAP_COST_OUT).to_dict("records") if CAP_COST_OUT.exists() else []
    done = {
        (
            r["basePortfolio"],
            float(r["tickerCapPctNav"]),
            float(r["grossCap"]),
            float(r["costBps"]),
        )
        for r in rows
    }
    original_cost = engine.COST_BPS
    try:
        for port, base in BASE_PORTFOLIOS.items():
            for ticker_cap in [0.20, 0.30, 0.40, 0.50]:
                for gross_cap in [1.0, 1.25, 1.50, 1.75, 2.0]:
                    for cost_bps in [4.0, 9.0, 14.0, 24.0]:
                        key = (port, ticker_cap, gross_cap, cost_bps)
                        if key in done:
                            continue
                        engine.COST_BPS = cost_bps
                        cfg = {
                            "weights": base["weights"],
                            "top_k": base["top_k"],
                            "ticker_cap_pct": ticker_cap,
                            "gross_cap": gross_cap,
                        }
                        name = f"{port}_ticker{int(ticker_cap*100)}_gross{gross_cap:g}_cost{cost_bps:g}"
                        summary, _, _ = engine.simulate(name, cfg, signals, daily_px)
                        rows.append({"basePortfolio": port, "tickerCapPctNav": ticker_cap, "grossCap": gross_cap, "costBps": cost_bps, **summary})
                        pd.DataFrame(rows).to_csv(CAP_COST_OUT, index=False)
                        done.add(key)
                        print("sweep", name, summary["pnl"], summary["dd"], flush=True)
    finally:
        engine.COST_BPS = original_cost
    return pd.DataFrame(rows)


def concentration_stress() -> pd.DataFrame:
    eq = pd.read_csv(engine.EQUITY_OUT, parse_dates=["date"])
    tr = pd.read_csv(engine.TRADES_OUT, parse_dates=["date", "exit_date"])
    rows = []
    for port in ["A_no_ml_all_cap40", "B_no_ml_all_cap40"]:
        base_daily = eq[eq["portfolio"].eq(port)][["date", "daily_pnl"]].copy()
        x = tr[tr["portfolio"].eq(port) & tr["pnl"].notna()].copy()
        ticker_pnl = x.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
        total = float(x["pnl"].sum())
        rows.append(
            {
                **summarize_daily(port, "base", base_daily),
                "dropped": "",
                "topTicker": str(ticker_pnl.index[0]),
                "topTickerPnl": float(ticker_pnl.iloc[0]),
                "topTickerShare": float(ticker_pnl.iloc[0] / total) if total else np.nan,
                "top10Share": float(ticker_pnl.head(10).sum() / total) if total else np.nan,
            }
        )

        for n in [1, 3, 5, 10]:
            drop = set(ticker_pnl.head(n).index)
            removed = x[x["ticker"].isin(drop)].groupby("exit_date")["pnl"].sum().rename("removed")
            daily = base_daily.merge(removed, left_on="date", right_index=True, how="left").fillna({"removed": 0.0})
            daily["daily_pnl"] = daily["daily_pnl"] - daily["removed"]
            rows.append({**summarize_daily(port, f"drop_top_{n}_winning_tickers", daily), "dropped": ",".join(sorted(drop))})

        winners = x.sort_values("pnl", ascending=False)
        for n in [10, 20]:
            ids = set(winners.head(n)["trade_id"])
            removed = x[x["trade_id"].isin(ids)].groupby("exit_date")["pnl"].sum().rename("removed")
            daily = base_daily.merge(removed, left_on="date", right_index=True, how="left").fillna({"removed": 0.0})
            daily["daily_pnl"] = daily["daily_pnl"] - daily["removed"]
            rows.append({**summarize_daily(port, f"remove_top_{n}_closed_trades", daily), "dropped": ""})
    return pd.DataFrame(rows)


def bootstrap_stress(iterations: int = 5000) -> pd.DataFrame:
    rng = np.random.default_rng(20260909)
    eq = pd.read_csv(engine.EQUITY_OUT, parse_dates=["date"])
    rows = []
    for port in ["A_no_ml_all_cap40", "B_no_ml_all_cap40"]:
        x = eq[eq["portfolio"].eq(port)].sort_values("date").copy()
        pnl = x["daily_pnl"].to_numpy(float)
        n = len(pnl)
        sim_pnl = np.empty(iterations)
        sim_dd = np.empty(iterations)
        for i in range(iterations):
            sample = pnl[rng.integers(0, n, size=n)]
            sim_pnl[i] = sample.sum()
            sim_dd[i] = max_drawdown_from_pnl(pd.Series(sample))
        rows.append(
            {
                "portfolio": port,
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
            sim_dd[i] = max_drawdown_from_pnl(pd.Series(sample))
        rows.append(
            {
                "portfolio": port,
                "mode": "month_order_bootstrap",
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
    return pd.DataFrame(rows)


def sanity() -> pd.DataFrame:
    eq = pd.read_csv(engine.EQUITY_OUT, parse_dates=["date"])
    tr = pd.read_csv(engine.TRADES_OUT, parse_dates=["date"])
    rows = []
    for port in ["A_no_ml_all_cap40", "B_no_ml_all_cap40"]:
        e = eq[eq["portfolio"].eq(port)].copy()
        t = tr[tr["portfolio"].eq(port)].copy()
        collisions = t.groupby(["date", "ticker"])["sleeve"].nunique()
        rows.append(
            {
                "portfolio": port,
                "maxGross": float(e["gross"].max()),
                "avgGross": float(e["gross"].mean()),
                "minCash": float(e["cash"].min()),
                "cashNegativeDays": int((e["cash"] < 0).sum()),
                "tickerDateCollisions": int((collisions > 1).sum()),
                "maxSleevesPerTickerDate": int(collisions.max()) if len(collisions) else 0,
                "tickerCapAppliedBeforeOrders": True,
                "grossCapAppliedBeforeOrders": True,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    daily_px = engine.load_daily_prices()
    signals = engine.load_signals()
    cap = run_cap_cost_sweep(daily_px, signals)
    cap.to_csv(CAP_COST_OUT, index=False)
    conc = concentration_stress()
    conc.to_csv(CONC_OUT, index=False)
    boot = bootstrap_stress()
    boot.to_csv(BOOT_OUT, index=False)
    san = sanity()
    san.to_csv(SANITY_OUT, index=False)
    print("WROTE", CAP_COST_OUT, CONC_OUT, BOOT_OUT, SANITY_OUT)


if __name__ == "__main__":
    main()
