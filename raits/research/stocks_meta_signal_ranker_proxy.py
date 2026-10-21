from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


START = pd.Timestamp("2023-03-28")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 50_000.0

DETAIL = Path("STOCKS_PORTFOLIO_ATTRIBUTION_AUDIT_TRADE_DETAIL_2026-09-09.csv")
OUT = Path("STOCKS_META_SIGNAL_RANKER_PROXY_2026-09-09.csv")
PICKS_OUT = Path("STOCKS_META_SIGNAL_RANKER_PROXY_PICKS_2026-09-09.csv")


PORTFOLIOS = {
    "A_core04_clean4_sat04": {
        "broad_adv10_g2_dd85": 0.40,
        "local_xs_full_s10": 0.40,
        "ml_ex6_0935_s20": 0.40,
        "yday_ex6_actual": 0.40,
        "intraday_ex10": 0.40,
    },
    "B_equal_clean_prior": {
        "broad_adv10_g2_dd85": 0.35,
        "local_xs_full_s10": 0.35,
        "ml_ex6_0935_s20": 0.35,
        "yday_ex6_actual": 0.35,
        "intraday_ex10": 0.35,
    },
}


def max_drawdown(pnl: pd.Series) -> float:
    eq = START_CAPITAL + pnl.cumsum()
    return float((eq - eq.cummax()).min())


def normalize_strength(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["strength"] = out.groupby(["date", "sleeve"])["raw_strength"].rank(pct=True, method="average")
    out["strength"] = out["strength"].fillna(1.0)
    return out


def load_signals() -> pd.DataFrame:
    rows = []

    broad = pd.read_csv("STOCKS_DATABENTO_DAILY_XS_MTM_DD_OVERLAY_BEST_TRADES_2026-09-08.csv", parse_dates=["entry_date"])
    broad = broad[(broad["entry_date"] >= START) & (broad["entry_date"] <= END)].copy()
    rows.append(
        pd.DataFrame(
            {
                "date": broad["entry_date"],
                "ticker": broad["symbol"].astype(str),
                "sleeve": "broad_adv10_g2_dd85",
                "raw_strength": -broad["ret5"].astype(float),
            }
        )
    )

    local = pd.read_csv("STOCKS_DAILY_XS_RET5_BOTTOM_H20_FULL_TRADES_2026-09-08.csv", parse_dates=["date"])
    local = local[(local["date"] >= START) & (local["date"] <= END)].copy()
    rows.append(
        pd.DataFrame(
            {
                "date": local["date"],
                "ticker": local["ticker"].astype(str),
                "sleeve": "local_xs_full_s10",
                "raw_strength": -local["ret5_pre_clean"].astype(float),
            }
        )
    )

    ml = pd.read_csv("STOCKS_ML_RANKER_TARGETED_TRADES_NOLOOK_2026-09-08.csv", parse_dates=["entry_date"], low_memory=False)
    ml = ml[
        (ml["entry_date"] >= START)
        & (ml["entry_date"] <= END)
        & (ml["entry"].eq("0935"))
        & (ml["slots"].eq(20))
        & (ml["dropSet"].eq("META+TSLA+NVDA+AMD+BA+NFLX"))
    ].copy()
    rows.append(
        pd.DataFrame(
            {
                "date": ml["entry_date"],
                "ticker": ml["ticker"].astype(str),
                "sleeve": "ml_ex6_0935_s20",
                "raw_strength": ml["pred"].astype(float),
            }
        )
    )

    yday = pd.read_csv("STOCKS_WFO_CLEAN_RETEST_MAX1_80_TRADES_2026-09-08.csv", parse_dates=["date"])
    yday = yday[(yday["date"] >= START) & (yday["date"] <= END) & (yday["wfo_mode"].eq("rolling3"))].copy()
    rows.append(
        pd.DataFrame(
            {
                "date": yday["date"],
                "ticker": yday["ticker"].astype(str),
                "sleeve": "yday_ex6_actual",
                "raw_strength": 1.0,
            }
        )
    )

    intraday = pd.read_csv("STOCKS_INTRADAY_FOCUSED_RULES_TRADES_2026-09-08.csv", parse_dates=["date"])
    intraday = intraday[
        (intraday["date"] >= START)
        & (intraday["date"] <= END)
        & (intraday["dropSet"].astype(str).str.contains("DE", regex=False))
        & (intraday["slots"].eq(20))
    ].copy()
    rows.append(
        pd.DataFrame(
            {
                "date": intraday["date"],
                "ticker": intraday["ticker"].astype(str),
                "sleeve": "intraday_ex10",
                "raw_strength": intraday["train_score"].astype(float),
            }
        )
    )

    out = pd.concat(rows, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    out = out.drop_duplicates(["date", "ticker", "sleeve"])
    return normalize_strength(out)


def load_detail() -> pd.DataFrame:
    detail = pd.read_csv(DETAIL, parse_dates=["date"])
    # stream_pnl is independent of portfolio weights; use one portfolio copy only.
    detail = detail[detail["portfolio"].eq("candidate_A_core04_clean4_sat04")].copy()
    return detail[["date", "ticker", "sleeve", "stream_pnl"]]


def summarize(daily: pd.DataFrame, pnl_col: str) -> dict[str, object]:
    pnl = daily[pnl_col].astype(float)
    yearly = daily.assign(year=daily["date"].dt.year).groupby("year")[pnl_col].sum()
    monthly = daily.assign(month=daily["date"].dt.to_period("M")).groupby("month")[pnl_col].sum()
    return {
        "pnl": float(pnl.sum()),
        "dd": max_drawdown(pnl.reset_index(drop=True)),
        "sharpe": float(pnl.mean() / pnl.std() * np.sqrt(252)) if pnl.std() > 0 else np.nan,
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
        "negMonths": int((monthly < 0).sum()),
        "minMonth": float(monthly.min()) if len(monthly) else np.nan,
        "medianMonth": float(monthly.median()) if len(monthly) else np.nan,
    }


def main() -> None:
    signals = load_signals()
    detail = load_detail()
    merged = signals.merge(detail, on=["date", "ticker", "sleeve"], how="inner")

    all_dates = pd.DataFrame({"date": sorted(merged["date"].drop_duplicates())})
    rows = []
    pick_rows = []
    for portfolio, weights in PORTFOLIOS.items():
        x = merged[merged["sleeve"].isin(weights)].copy()
        x["weight"] = x["sleeve"].map(weights).astype(float)
        x["weighted_pnl"] = x["stream_pnl"] * x["weight"]
        x["weighted_strength"] = x["strength"] * x["weight"]

        base_td = (
            x.groupby(["date", "ticker"])
            .agg(
                sleeveCount=("sleeve", "nunique"),
                strengthSum=("strength", "sum"),
                strengthAvg=("strength", "mean"),
                weightedStrength=("weighted_strength", "sum"),
                pnl=("weighted_pnl", "sum"),
                sleeves=("sleeve", lambda s: ",".join(sorted(set(s)))),
            )
            .reset_index()
        )
        base_daily = all_dates.merge(base_td.groupby("date")["pnl"].sum().reset_index(), on="date", how="left").fillna({"pnl": 0.0})
        base_summary = summarize(base_daily, "pnl")
        rows.append(
            {
                "portfolio": portfolio,
                "rankMode": "baseline_all_signals",
                "topK": 0,
                "tickerDates": int(len(base_td)),
                "avgTickerDatesPerDay": float(base_td.groupby("date").size().mean()),
                **base_summary,
            }
        )

        for rank_mode in ["sleeveCount", "strengthSum", "weightedStrength", "hybrid"]:
            td = base_td.copy()
            if rank_mode == "hybrid":
                td["rankScore"] = td["sleeveCount"] + td["weightedStrength"]
            else:
                td["rankScore"] = td[rank_mode]
            td = td.sort_values(["date", "rankScore", "strengthAvg"], ascending=[True, False, False])
            for k in [5, 10, 20, 30, 40, 50]:
                picks = td.groupby("date", group_keys=False).head(k).copy()
                daily = all_dates.merge(picks.groupby("date")["pnl"].sum().reset_index(), on="date", how="left").fillna({"pnl": 0.0})
                s = summarize(daily, "pnl")
                ticker = picks.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
                rows.append(
                    {
                        "portfolio": portfolio,
                        "rankMode": rank_mode,
                        "topK": k,
                        "tickerDates": int(len(picks)),
                        "avgTickerDatesPerDay": float(picks.groupby("date").size().mean()),
                        "topTicker": str(ticker.index[0]) if len(ticker) else "",
                        "topTickerShare": float(ticker.iloc[0] / s["pnl"]) if s["pnl"] > 0 and len(ticker) else np.nan,
                        "top5Share": float(ticker.head(5).sum() / s["pnl"]) if s["pnl"] > 0 and len(ticker) else np.nan,
                        "top10Share": float(ticker.head(10).sum() / s["pnl"]) if s["pnl"] > 0 and len(ticker) else np.nan,
                        **s,
                    }
                )
                if portfolio.startswith("A_") and rank_mode in {"hybrid", "weightedStrength"} and k in {10, 20, 30}:
                    pick_rows.append(picks.assign(portfolio=portfolio, rankMode=rank_mode, topK=k))

    pd.DataFrame(rows).to_csv(OUT, index=False)
    pd.concat(pick_rows, ignore_index=True).to_csv(PICKS_OUT, index=False)
    print("WROTE", OUT, PICKS_OUT)


if __name__ == "__main__":
    main()
