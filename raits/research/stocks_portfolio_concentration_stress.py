from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


START_CAPITAL = 50_000.0
DETAIL = Path("STOCKS_PORTFOLIO_ATTRIBUTION_AUDIT_TRADE_DETAIL_2026-09-09.csv")
SUMMARY = Path("STOCKS_PORTFOLIO_ATTRIBUTION_AUDIT_SUMMARY_2026-09-09.csv")
OUT = Path("STOCKS_PORTFOLIO_CONCENTRATION_STRESS_2026-09-09.csv")
CAP_DETAIL_OUT = Path("STOCKS_PORTFOLIO_TICKER_DAY_CAP_DETAIL_2026-09-09.csv")


def max_drawdown(pnl: pd.Series) -> float:
    eq = START_CAPITAL + pnl.cumsum()
    return float((eq - eq.cummax()).min())


def summarize(portfolio: str, label: str, detail: pd.DataFrame, exact_baseline_pnl: float | None = None) -> dict[str, object]:
    daily = detail.groupby("date")["weighted_pnl"].sum().sort_index()
    yearly = detail.assign(year=detail["date"].dt.year).groupby("year")["weighted_pnl"].sum()
    total = float(daily.sum())
    row: dict[str, object] = {
        "portfolio": portfolio,
        "stress": label,
        "attrPnl": total,
        "exactBaselinePnl": exact_baseline_pnl if exact_baseline_pnl is not None else np.nan,
        "pnlVsExactBaseline": total - exact_baseline_pnl if exact_baseline_pnl is not None else np.nan,
        "attrDd": max_drawdown(daily),
        "attrSharpe": float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else np.nan,
        "rawEntries": int(len(detail)),
        "uniqueTickerDates": int(detail.drop_duplicates(["date", "ticker"]).shape[0]),
        "tickers": int(detail["ticker"].nunique()),
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
    }
    ticker = detail.groupby("ticker")["weighted_pnl"].sum().sort_values(ascending=False)
    if len(ticker):
        row["topTicker"] = str(ticker.index[0])
        row["topTickerPnl"] = float(ticker.iloc[0])
        row["topTickerShare"] = float(ticker.iloc[0] / total) if total > 0 else np.nan
        row["top5Share"] = float(ticker.head(5).sum() / total) if total > 0 else np.nan
        row["top10Share"] = float(ticker.head(10).sum() / total) if total > 0 else np.nan
        row["top20Share"] = float(ticker.head(20).sum() / total) if total > 0 else np.nan
    return row


def cap_ticker_day(detail: pd.DataFrame, cap_abs: float) -> pd.DataFrame:
    td = detail.groupby(["date", "ticker"])["weighted_pnl"].sum().reset_index()
    td["capped_ticker_day_pnl"] = td["weighted_pnl"].clip(lower=-cap_abs, upper=cap_abs)
    td["scale"] = np.where(td["weighted_pnl"].abs() > 1e-12, td["capped_ticker_day_pnl"] / td["weighted_pnl"], 0.0)
    out = detail.merge(td[["date", "ticker", "scale"]], on=["date", "ticker"], how="left")
    out["weighted_pnl"] = out["weighted_pnl"] * out["scale"].fillna(1.0)
    out["capAbs"] = cap_abs
    return out.drop(columns=["scale"])


def main() -> None:
    detail = pd.read_csv(DETAIL, parse_dates=["date"])
    summary = pd.read_csv(SUMMARY).set_index("portfolio")
    rows = []
    cap_details = []
    for portfolio, g in detail.groupby("portfolio", sort=False):
        exact = float(summary.loc[portfolio, "pnl"])
        rows.append(summarize(portfolio, "baseline_attribution", g, exact))
        top = g.groupby("ticker")["weighted_pnl"].sum().sort_values(ascending=False)
        for n in [1, 3, 5, 10, 20, 50]:
            drop = set(top.head(n).index)
            stressed = g[~g["ticker"].isin(drop)].copy()
            row = summarize(portfolio, f"drop_top_{n}_tickers", stressed, exact)
            row["droppedTickers"] = ",".join(top.head(n).index)
            rows.append(row)
        for cap in [250.0, 500.0, 750.0, 1000.0, 1500.0, 2000.0]:
            capped = cap_ticker_day(g, cap)
            rows.append(summarize(portfolio, f"cap_ticker_day_abs_{int(cap)}", capped, exact))
            if cap in {500.0, 1000.0}:
                cap_details.append(capped.assign(stress=f"cap_ticker_day_abs_{int(cap)}"))
    pd.DataFrame(rows).to_csv(OUT, index=False)
    if cap_details:
        pd.concat(cap_details, ignore_index=True).to_csv(CAP_DETAIL_OUT, index=False)
    print("WROTE", OUT, CAP_DETAIL_OUT)


if __name__ == "__main__":
    main()
