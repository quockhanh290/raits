from __future__ import annotations

from pathlib import Path
import pickle

import numpy as np
import pandas as pd


PORTFOLIO = "B_polygon62_no_intraday_cap40"
START_CAPITAL = 50_000.0

EQUITY_IN = Path("STOCKS_POLYGON62_ONE_ENGINE_NO_ML_EQUITY_2018_2024.csv")
TRADES_IN = Path("STOCKS_POLYGON62_ONE_ENGINE_NO_ML_TRADES_2018_2024.csv")
FEATURES_IN = Path("raits/data/cache/stocks_clean_daily_features_POLYGON62_2018_2024.pkl")
BARS_IN = Path("raits/data/cache/window_debug_5min_POLYGON_2018_2024_62.pkl")

OUT = Path("STOCKS_POLYGON62_NEGATIVE_YEAR_DIAGNOSTICS_2018_2024.csv")


def max_drawdown(pnl: pd.Series) -> float:
    equity = START_CAPITAL + pnl.astype(float).cumsum()
    return float((equity - equity.cummax()).min())


def sharpe(pnl: pd.Series) -> float:
    std = float(pnl.std())
    if std <= 0:
        return np.nan
    return float(pnl.mean() / std * np.sqrt(252))


def monthly_spy() -> pd.DataFrame:
    with BARS_IN.open("rb") as f:
        bars = pickle.load(f)
    spy = bars["SPY"].copy().reset_index()
    spy = spy.rename(columns={spy.columns[0]: "ts"})
    spy["ts"] = pd.to_datetime(spy["ts"])
    spy["date"] = spy["ts"].dt.normalize()
    open_px = spy[spy["ts"].dt.strftime("%H:%M").eq("09:30")][["date", "open"]].rename(columns={"open": "open_0930"})
    close_px = spy[spy["ts"].dt.strftime("%H:%M").eq("15:55")][["date", "close"]].rename(columns={"close": "close_1555"})
    spy = open_px.merge(close_px, on="date", how="inner").sort_values("date")
    spy["spy_ret"] = spy["close_1555"].pct_change()
    return (
        spy.assign(month=spy["date"].dt.to_period("M"), year=spy["date"].dt.year)
        .groupby(["year", "month"])
        .agg(spyReturn=("spy_ret", lambda s: float((1.0 + s.dropna()).prod() - 1.0)))
        .reset_index()
        .assign(month=lambda x: x["month"].astype(str))
    )


def add_row(rows: list[dict[str, object]], section: str, bucket: str, year: int, **kwargs: object) -> None:
    row = {"portfolio": PORTFOLIO, "section": section, "bucket": bucket, "year": year}
    row.update(kwargs)
    rows.append(row)


def main() -> None:
    eq = pd.read_csv(EQUITY_IN, parse_dates=["date"])
    tr = pd.read_csv(TRADES_IN, parse_dates=["date", "exit_date"])
    eq = eq[eq["portfolio"].eq(PORTFOLIO)].sort_values("date").copy()
    tr = tr[tr["portfolio"].eq(PORTFOLIO)].copy()
    spy_m = monthly_spy()
    rows: list[dict[str, object]] = []

    eq["year"] = eq["date"].dt.year
    eq["month"] = eq["date"].dt.to_period("M")
    tr["entry_year"] = tr["date"].dt.year
    tr["exit_year"] = tr["exit_date"].dt.year
    tr["exit_month"] = tr["exit_date"].dt.to_period("M")

    for year in [2018, 2022]:
        eyear = eq[eq["year"].eq(year)].copy()
        add_row(
            rows,
            "year_equity",
            "total",
            year,
            days=len(eyear),
            pnl=float(eyear["daily_pnl"].sum()),
            dd=max_drawdown(eyear["daily_pnl"]),
            sharpe=sharpe(eyear["daily_pnl"]),
            avgGross=float(eyear["gross"].mean()),
            maxGross=float(eyear["gross"].max()),
        )

        months = (
            eyear.groupby("month")
            .agg(pnl=("daily_pnl", "sum"), dd=("daily_pnl", max_drawdown), avgGross=("gross", "mean"), maxGross=("gross", "max"))
            .reset_index()
        )
        months["year"] = months["month"].dt.year
        months["month"] = months["month"].astype(str)
        months = months.merge(spy_m, on=["year", "month"], how="left")
        for _, row in months.sort_values("pnl").iterrows():
            add_row(
                rows,
                "monthly",
                str(row["month"]),
                year,
                pnl=float(row["pnl"]),
                dd=float(row["dd"]),
                avgGross=float(row["avgGross"]),
                maxGross=float(row["maxGross"]),
                spyReturn=float(row["spyReturn"]) if pd.notna(row["spyReturn"]) else np.nan,
            )

        texit = tr[tr["exit_year"].eq(year) & tr["pnl"].notna()].copy()
        for sleeve, group in texit.groupby("sleeve", sort=True):
            add_row(
                rows,
                "closed_trade_by_sleeve",
                sleeve,
                year,
                trades=len(group),
                pnl=float(group["pnl"].sum()),
                meanTrade=float(group["pnl"].mean()),
                winRate=float((group["pnl"] > 0).mean()),
            )

        for ticker, group in texit.groupby("ticker"):
            pnl = float(group["pnl"].sum())
            add_row(
                rows,
                "closed_trade_by_ticker",
                ticker,
                year,
                trades=len(group),
                pnl=pnl,
                meanTrade=float(group["pnl"].mean()),
                winRate=float((group["pnl"] > 0).mean()),
            )

        for ticker, pnl in texit.groupby("ticker")["pnl"].sum().sort_values().head(15).items():
            group = texit[texit["ticker"].eq(ticker)]
            add_row(
                rows,
                "worst_tickers",
                ticker,
                year,
                trades=len(group),
                pnl=float(pnl),
                meanTrade=float(group["pnl"].mean()),
                winRate=float((group["pnl"] > 0).mean()),
            )

        for month, group in texit.groupby("exit_month", sort=True):
            add_row(
                rows,
                "closed_trade_by_exit_month",
                str(month),
                year,
                trades=len(group),
                pnl=float(group["pnl"].sum()),
                meanTrade=float(group["pnl"].mean()),
                winRate=float((group["pnl"] > 0).mean()),
            )

    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print("WROTE", OUT, len(out))


if __name__ == "__main__":
    main()
