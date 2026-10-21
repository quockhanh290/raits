from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_meta_signal_ranker_proxy as ranker


START_CAPITAL = 50_000.0
OUT = Path("STOCKS_META_RANKER_CAP_PROXY_2026-09-09.csv")


def max_drawdown(pnl: pd.Series) -> float:
    eq = START_CAPITAL + pnl.cumsum()
    return float((eq - eq.cummax()).min())


def summarize(daily: pd.DataFrame, pnl: pd.Series) -> dict[str, object]:
    yearly = pd.DataFrame({"date": daily["date"], "pnl": pnl}).assign(year=lambda x: x["date"].dt.year).groupby("year")["pnl"].sum()
    monthly = pd.DataFrame({"date": daily["date"], "pnl": pnl}).assign(month=lambda x: x["date"].dt.to_period("M")).groupby("month")["pnl"].sum()
    years = (daily["date"].max() - daily["date"].min()).days / 365.25
    ending = START_CAPITAL + float(pnl.sum())
    return {
        "pnl": float(pnl.sum()),
        "totalReturn": float(pnl.sum() / START_CAPITAL),
        "cagr": float((ending / START_CAPITAL) ** (1 / years) - 1),
        "dd": max_drawdown(pnl.reset_index(drop=True)),
        "sharpe": float(pnl.mean() / pnl.std() * np.sqrt(252)) if pnl.std() > 0 else np.nan,
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
        "negMonths": int((monthly < 0).sum()),
        "minMonth": float(monthly.min()) if len(monthly) else np.nan,
    }


def cap_ticker_day(td: pd.DataFrame, cap_abs: float | None) -> pd.DataFrame:
    out = td.copy()
    if cap_abs is None:
        out["pnl_capped"] = out["pnl"]
    else:
        out["pnl_capped"] = out["pnl"].clip(lower=-cap_abs, upper=cap_abs)
    return out


def main() -> None:
    signals = ranker.load_signals()
    detail = ranker.load_detail()
    merged = signals.merge(detail, on=["date", "ticker", "sleeve"], how="inner")
    all_dates = pd.DataFrame({"date": sorted(merged["date"].drop_duplicates())})

    rows = []
    for portfolio, weights in ranker.PORTFOLIOS.items():
        x = merged[merged["sleeve"].isin(weights)].copy()
        x["weight"] = x["sleeve"].map(weights).astype(float)
        x["weighted_pnl"] = x["stream_pnl"] * x["weight"]
        x["weighted_strength"] = x["strength"] * x["weight"]
        td = (
            x.groupby(["date", "ticker"])
            .agg(
                sleeveCount=("sleeve", "nunique"),
                strengthAvg=("strength", "mean"),
                weightedStrength=("weighted_strength", "sum"),
                pnl=("weighted_pnl", "sum"),
            )
            .reset_index()
        )
        td["rankScore"] = td["sleeveCount"] + td["weightedStrength"]
        td = td.sort_values(["date", "rankScore", "strengthAvg"], ascending=[True, False, False])

        for top_k in [20, 30, 40, 50, 0]:
            picks = td if top_k == 0 else td.groupby("date", group_keys=False).head(top_k).copy()
            for cap in [None, 250.0, 500.0, 750.0, 1000.0, 1500.0]:
                capped = cap_ticker_day(picks, cap)
                daily = all_dates.merge(capped.groupby("date")["pnl_capped"].sum().reset_index(), on="date", how="left").fillna({"pnl_capped": 0.0})
                ticker = capped.groupby("ticker")["pnl_capped"].sum().sort_values(ascending=False)
                s = summarize(daily, daily["pnl_capped"])
                rows.append(
                    {
                        "portfolio": portfolio,
                        "topK": "all" if top_k == 0 else top_k,
                        "capAbs": "none" if cap is None else int(cap),
                        "tickerDates": int(len(picks)),
                        "avgTickerDatesPerDay": float(picks.groupby("date").size().mean()),
                        "topTicker": str(ticker.index[0]) if len(ticker) else "",
                        "topTickerShare": float(ticker.iloc[0] / s["pnl"]) if s["pnl"] > 0 and len(ticker) else np.nan,
                        "top5Share": float(ticker.head(5).sum() / s["pnl"]) if s["pnl"] > 0 and len(ticker) else np.nan,
                        "top10Share": float(ticker.head(10).sum() / s["pnl"]) if s["pnl"] > 0 and len(ticker) else np.nan,
                        **s,
                    }
                )
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
