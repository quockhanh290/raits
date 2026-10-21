from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


START = pd.Timestamp("2023-03-28")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 50_000.0

STREAMS = Path("STOCKS_ALL_SLEEVE_LIBRARY_DAILY_STREAMS_2026-09-08.csv")
SUMMARY_OUT = Path("STOCKS_PORTFOLIO_ATTRIBUTION_AUDIT_SUMMARY_2026-09-09.csv")
SLEEVE_OUT = Path("STOCKS_PORTFOLIO_ATTRIBUTION_AUDIT_BY_SLEEVE_2026-09-09.csv")
TICKER_OUT = Path("STOCKS_PORTFOLIO_ATTRIBUTION_AUDIT_BY_TICKER_2026-09-09.csv")
OVERLAP_OUT = Path("STOCKS_PORTFOLIO_ATTRIBUTION_AUDIT_OVERLAP_2026-09-09.csv")
DAY_OUT = Path("STOCKS_PORTFOLIO_ATTRIBUTION_AUDIT_DAILY_RISK_2026-09-09.csv")
DETAIL_OUT = Path("STOCKS_PORTFOLIO_ATTRIBUTION_AUDIT_TRADE_DETAIL_2026-09-09.csv")


PORTFOLIOS = {
    "candidate_A_core04_clean4_sat04": {
        "broad_adv10_g2_dd85": 0.40,
        "local_xs_full_s10": 0.40,
        "ml_ex6_0935_s20": 0.40,
        "yday_ex6_actual": 0.40,
        "intraday_ex10": 0.40,
    },
    "candidate_B_equal_clean_prior": {
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


def load_streams() -> pd.DataFrame:
    df = pd.read_csv(STREAMS, parse_dates=["date"])
    return df[(df["date"] >= START) & (df["date"] <= END)].copy()


def load_panel_close() -> pd.Series:
    px = pd.read_parquet(
        "raits/data/cache/research_daily/databento_ohlcv1d.parquet",
        columns=["symbol", "date", "close"],
    )
    px["date"] = pd.to_datetime(px["date"])
    px = px[(px["date"] >= START) & (px["date"] <= END)]
    return px.set_index(["date", "symbol"])["close"]


def scale_to_stream(df: pd.DataFrame, stream_total: float) -> pd.DataFrame:
    raw = float(df["base_pnl"].sum())
    out = df.copy()
    out["scale_to_stream"] = stream_total / raw if abs(raw) > 1e-12 else np.nan
    out["stream_pnl"] = out["base_pnl"] * out["scale_to_stream"].fillna(0.0)
    return out


def sleeve_trades(streams: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    close_lookup = load_panel_close()
    close_df = close_lookup.reset_index().sort_values(["symbol", "date"])
    last_close_by_symbol = close_df.groupby("symbol").tail(1).set_index("symbol")[["date", "close"]]

    broad = pd.read_csv("STOCKS_DATABENTO_DAILY_XS_MTM_DD_OVERLAY_BEST_TRADES_2026-09-08.csv", parse_dates=["entry_date", "planned_exit_date"])
    broad = broad[(broad["entry_date"] >= START) & (broad["entry_date"] <= END)].copy()
    b_rows = []
    for _, t in broad.iterrows():
        key = (pd.Timestamp(t["planned_exit_date"]), str(t["symbol"]))
        exit_date = pd.Timestamp(t["planned_exit_date"])
        if key in close_lookup.index:
            exit_px = float(close_lookup.loc[key])
        elif str(t["symbol"]) in last_close_by_symbol.index:
            exit_date = pd.Timestamp(last_close_by_symbol.loc[str(t["symbol"]), "date"])
            exit_px = float(last_close_by_symbol.loc[str(t["symbol"]), "close"])
        else:
            continue
        shares = float(t["shares"])
        cost_rate = 4.0 / 10_000.0
        pnl = shares * (exit_px - float(t["entry_price"])) - float(t["entry_cost"]) - shares * exit_px * cost_rate
        b_rows.append(
            {
                "sleeve": "broad_adv10_g2_dd85",
                "date": pd.Timestamp(t["entry_date"]),
                "mark_exit_date": exit_date,
                "ticker": str(t["symbol"]),
                "base_pnl": pnl,
                "hold_days": 20,
                "entry_style": "daily_open",
            }
        )
    rows.append(scale_to_stream(pd.DataFrame(b_rows), float(streams["broad_adv10_g2_dd85"].sum())))

    local = pd.read_csv("STOCKS_DAILY_XS_RET5_BOTTOM_H20_FULL_TRADES_2026-09-08.csv", parse_dates=["date"])
    local = local[(local["date"] >= START) & (local["date"] <= END)].copy()
    local_rows = local.rename(columns={"ticker": "ticker", "pnl": "base_pnl"})[["date", "ticker", "base_pnl"]].copy()
    local_rows["sleeve"] = "local_xs_full_s10"
    local_rows["hold_days"] = 20
    local_rows["entry_style"] = "daily_open_to_close_h20"
    rows.append(scale_to_stream(local_rows, float(streams["local_xs_full_s10"].sum())))

    ml = pd.read_csv("STOCKS_ML_RANKER_TARGETED_TRADES_NOLOOK_2026-09-08.csv", parse_dates=["entry_date"], low_memory=False)
    ml = ml[
        (ml["entry_date"] >= START)
        & (ml["entry_date"] <= END)
        & (ml["entry"].eq("0935"))
        & (ml["slots"].eq(20))
        & (ml["dropSet"].eq("META+TSLA+NVDA+AMD+BA+NFLX"))
    ].copy()
    ml_rows = ml.rename(columns={"entry_date": "date", "ticker": "ticker", "pnl": "base_pnl"})[["date", "ticker", "base_pnl"]].copy()
    ml_rows["sleeve"] = "ml_ex6_0935_s20"
    ml_rows["hold_days"] = 0
    ml_rows["entry_style"] = "0935_to_close"
    rows.append(scale_to_stream(ml_rows, float(streams["ml_ex6_0935_s20"].sum())))

    yday = pd.read_csv("STOCKS_WFO_CLEAN_RETEST_MAX1_80_TRADES_2026-09-08.csv", parse_dates=["date"])
    yday = yday[(yday["date"] >= START) & (yday["date"] <= END) & (yday["wfo_mode"].eq("rolling3"))].copy()
    yday_rows = yday.rename(columns={"ticker": "ticker", "pnl": "base_pnl"})[["date", "ticker", "base_pnl"]].copy()
    yday_rows["sleeve"] = "yday_ex6_actual"
    yday_rows["hold_days"] = 0
    yday_rows["entry_style"] = "0930_or_0935_to_1555"
    rows.append(scale_to_stream(yday_rows, float(streams["yday_ex6_actual"].sum())))

    intraday = pd.read_csv("STOCKS_INTRADAY_FOCUSED_RULES_TRADES_2026-09-08.csv", parse_dates=["date"])
    intraday = intraday[
        (intraday["date"] >= START)
        & (intraday["date"] <= END)
        & (intraday["dropSet"].astype(str).str.contains("DE", regex=False))
        & (intraday["slots"].eq(20))
    ].copy()
    # Use return-dollar scaling so attribution sums to the daily stream total.
    intraday_rows = intraday.rename(columns={"ticker": "ticker", "ret": "base_pnl"})[["date", "ticker", "base_pnl"]].copy()
    intraday_rows["sleeve"] = "intraday_ex10"
    intraday_rows["hold_days"] = 0
    intraday_rows["entry_style"] = "0935_to_close"
    rows.append(scale_to_stream(intraday_rows, float(streams["intraday_ex10"].sum())))

    out = pd.concat(rows, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    out["ticker"] = out["ticker"].astype(str)
    return out


def portfolio_pnl(streams: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    pnl = pd.Series(0.0, index=streams.index)
    for name, weight in weights.items():
        pnl = pnl + streams[name].fillna(0.0) * weight
    return pnl


def main() -> None:
    streams = load_streams()
    trades = sleeve_trades(streams)

    summary_rows = []
    sleeve_rows = []
    ticker_rows = []
    daily_rows = []
    detail_rows = []

    for portfolio, weights in PORTFOLIOS.items():
        p = portfolio_pnl(streams, weights)
        eq = START_CAPITAL + p.cumsum()
        years = (streams["date"].max() - streams["date"].min()).days / 365.25
        yearly = pd.DataFrame({"date": streams["date"], "pnl": p}).assign(year=lambda x: x["date"].dt.year).groupby("year")["pnl"].sum()
        summary_rows.append(
            {
                "portfolio": portfolio,
                "start": streams["date"].min().date(),
                "end": streams["date"].max().date(),
                "years": years,
                "pnl": float(p.sum()),
                "ending": float(eq.iloc[-1]),
                "totalReturn": float(p.sum() / START_CAPITAL),
                "simpleAnnualReturn": float((p.sum() / START_CAPITAL) / years),
                "cagr": float((eq.iloc[-1] / START_CAPITAL) ** (1 / years) - 1),
                "dd": max_drawdown(p),
                "ddPctStartCapital": max_drawdown(p) / START_CAPITAL,
                "sharpe": float(p.mean() / p.std() * np.sqrt(252)) if p.std() > 0 else np.nan,
                "y2023": float(yearly.get(2023, 0.0)),
                "y2024": float(yearly.get(2024, 0.0)),
                "totalWeight": float(sum(weights.values())),
                "streamReconError": float(p.sum() - sum(streams[k].sum() * w for k, w in weights.items())),
            }
        )

        wt_trades = trades[trades["sleeve"].isin(weights)].copy()
        wt_trades["weighted_pnl"] = wt_trades["stream_pnl"] * wt_trades["sleeve"].map(weights).astype(float)
        wt_trades["portfolio"] = portfolio
        detail_rows.append(wt_trades)

        sleeve = wt_trades.groupby("sleeve").agg(
            rawEntries=("ticker", "size"),
            uniqueTickerDates=("ticker", lambda s: 0),
            weightedPnl=("weighted_pnl", "sum"),
            avgHoldDays=("hold_days", "mean"),
        ).reset_index()
        unique_td = wt_trades.drop_duplicates(["sleeve", "date", "ticker"]).groupby("sleeve").size()
        sleeve["uniqueTickerDates"] = sleeve["sleeve"].map(unique_td).fillna(0).astype(int)
        sleeve["pnlShare"] = sleeve["weightedPnl"] / float(p.sum())
        sleeve_rows.append(sleeve)

        ticker = wt_trades.groupby("ticker").agg(
            rawEntries=("ticker", "size"),
            sleeves=("sleeve", "nunique"),
            weightedPnl=("weighted_pnl", "sum"),
        ).sort_values("weightedPnl", ascending=False).reset_index()
        ticker["portfolio"] = portfolio
        ticker["pnlShare"] = ticker["weightedPnl"] / float(p.sum())
        ticker["cumPnlShare"] = ticker["weightedPnl"].cumsum() / float(p.sum())
        ticker_rows.append(ticker)

        daily = pd.DataFrame({"date": streams["date"], "dailyPnl": p})
        daily["portfolio"] = portfolio
        daily["equity"] = START_CAPITAL + daily["dailyPnl"].cumsum()
        daily["drawdown"] = daily["equity"] - daily["equity"].cummax()
        entries_by_day = wt_trades.groupby("date").size()
        unique_by_day = wt_trades.drop_duplicates(["date", "ticker"]).groupby("date").size()
        daily["rawEntries"] = daily["date"].map(entries_by_day).fillna(0).astype(int)
        daily["uniqueTickerEntries"] = daily["date"].map(unique_by_day).fillna(0).astype(int)
        daily_rows.append(daily)

    all_entries = trades.copy()
    overlap = all_entries.groupby(["date", "ticker"]).agg(
        rawEntries=("sleeve", "size"),
        sleeves=("sleeve", lambda x: ",".join(sorted(set(x)))),
        sleeveCount=("sleeve", "nunique"),
        streamPnl=("stream_pnl", "sum"),
    ).reset_index()
    overlap = overlap.sort_values(["rawEntries", "sleeveCount", "streamPnl"], ascending=[False, False, False])

    pd.DataFrame(summary_rows).to_csv(SUMMARY_OUT, index=False)
    pd.concat(sleeve_rows, ignore_index=True).to_csv(SLEEVE_OUT, index=False)
    pd.concat(ticker_rows, ignore_index=True).to_csv(TICKER_OUT, index=False)
    overlap.to_csv(OVERLAP_OUT, index=False)
    pd.concat(daily_rows, ignore_index=True).to_csv(DAY_OUT, index=False)
    pd.concat(detail_rows, ignore_index=True).to_csv(DETAIL_OUT, index=False)
    print("WROTE", SUMMARY_OUT, SLEEVE_OUT, TICKER_OUT, OVERLAP_OUT, DAY_OUT, DETAIL_OUT)


if __name__ == "__main__":
    main()
