from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_meta_signal_ranker_proxy as ranker


START = pd.Timestamp("2023-03-28")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 50_000.0
OUT = Path("STOCKS_META_RANKER_NOTIONAL_CAP_PROXY_2026-09-09.csv")
STREAMS = Path("STOCKS_ALL_SLEEVE_LIBRARY_DAILY_STREAMS_2026-09-08.csv")


def max_drawdown(pnl: pd.Series) -> float:
    eq = START_CAPITAL + pnl.cumsum()
    return float((eq - eq.cummax()).min())


def summarize(daily: pd.DataFrame, pnl: pd.Series) -> dict[str, object]:
    yearly = pd.DataFrame({"date": daily["date"], "pnl": pnl}).assign(year=lambda x: x["date"].dt.year).groupby("year")["pnl"].sum()
    years = (daily["date"].max() - daily["date"].min()).days / 365.25
    ending = START_CAPITAL + float(pnl.sum())
    return {
        "pnl": float(pnl.sum()),
        "cagr": float((ending / START_CAPITAL) ** (1 / years) - 1),
        "dd": max_drawdown(pnl.reset_index(drop=True)),
        "sharpe": float(pnl.mean() / pnl.std() * np.sqrt(252)) if pnl.std() > 0 else np.nan,
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
    }


def scale_to_stream(df: pd.DataFrame, stream_total: float) -> pd.DataFrame:
    out = df.copy()
    raw = float(out["base_pnl"].sum())
    scale = stream_total / raw if abs(raw) > 1e-12 else 0.0
    out["stream_pnl"] = out["base_pnl"] * scale
    out["stream_notional"] = out["base_notional"].abs() * abs(scale)
    return out


def load_stream_totals() -> pd.Series:
    streams = pd.read_csv(STREAMS, parse_dates=["date"])
    streams = streams[(streams["date"] >= START) & (streams["date"] <= END)]
    return streams.sum(numeric_only=True)


def load_detail_with_notional() -> pd.DataFrame:
    stream_totals = load_stream_totals()
    rows = []

    broad = pd.read_csv("STOCKS_DATABENTO_DAILY_XS_MTM_DD_OVERLAY_BEST_TRADES_2026-09-08.csv", parse_dates=["entry_date"])
    broad = broad[(broad["entry_date"] >= START) & (broad["entry_date"] <= END)].copy()
    broad_attr = ranker.load_detail()
    broad_attr = broad_attr[broad_attr["sleeve"].eq("broad_adv10_g2_dd85")][["date", "ticker", "stream_pnl"]].copy()
    broad_attr["base_notional"] = broad_attr["stream_pnl"].abs() * 0.0 + float(broad["entry_notional"].median())
    # Broad entries are equal-sized at entry in the source simulator. Use source entry_notional where possible.
    bnot = broad.rename(columns={"entry_date": "date", "symbol": "ticker"})[["date", "ticker", "entry_notional"]]
    bnot["ticker"] = bnot["ticker"].astype(str)
    broad_attr = broad_attr.merge(bnot, on=["date", "ticker"], how="left")
    broad_attr["stream_notional"] = broad_attr["entry_notional"].fillna(broad_attr["base_notional"]).abs()
    broad_attr["sleeve"] = "broad_adv10_g2_dd85"
    rows.append(broad_attr[["date", "ticker", "sleeve", "stream_pnl", "stream_notional"]])

    local = pd.read_csv("STOCKS_DAILY_XS_RET5_BOTTOM_H20_FULL_TRADES_2026-09-08.csv", parse_dates=["date"])
    local = local[(local["date"] >= START) & (local["date"] <= END)].copy()
    local["base_pnl"] = local["pnl"].astype(float)
    local["base_notional"] = np.where(local["ret"].abs() > 1e-12, local["base_pnl"] / local["ret"], 0.0)
    local = local.rename(columns={"ticker": "ticker"})[["date", "ticker", "base_pnl", "base_notional"]]
    local["sleeve"] = "local_xs_full_s10"
    rows.append(scale_to_stream(local, float(stream_totals["local_xs_full_s10"]))[["date", "ticker", "sleeve", "stream_pnl", "stream_notional"]])

    ml = pd.read_csv("STOCKS_ML_RANKER_TARGETED_TRADES_NOLOOK_2026-09-08.csv", parse_dates=["entry_date"], low_memory=False)
    ml = ml[
        (ml["entry_date"] >= START)
        & (ml["entry_date"] <= END)
        & (ml["entry"].eq("0935"))
        & (ml["slots"].eq(20))
        & (ml["dropSet"].eq("META+TSLA+NVDA+AMD+BA+NFLX"))
    ].copy()
    ml["base_pnl"] = ml["pnl"].astype(float)
    ml["base_notional"] = np.where(ml["ret"].abs() > 1e-12, ml["base_pnl"] / ml["ret"], 0.0)
    ml = ml.rename(columns={"entry_date": "date"})[["date", "ticker", "base_pnl", "base_notional"]]
    ml["sleeve"] = "ml_ex6_0935_s20"
    rows.append(scale_to_stream(ml, float(stream_totals["ml_ex6_0935_s20"]))[["date", "ticker", "sleeve", "stream_pnl", "stream_notional"]])

    yday = pd.read_csv("STOCKS_WFO_CLEAN_RETEST_MAX1_80_TRADES_2026-09-08.csv", parse_dates=["date"])
    yday = yday[(yday["date"] >= START) & (yday["date"] <= END) & (yday["wfo_mode"].eq("rolling3"))].copy()
    yday["base_pnl"] = yday["pnl"].astype(float)
    yday["base_notional"] = np.where(yday["gross_ret"].abs() > 1e-12, yday["base_pnl"] / yday["gross_ret"], 0.0)
    yday = yday[["date", "ticker", "base_pnl", "base_notional"]]
    yday["sleeve"] = "yday_ex6_actual"
    rows.append(scale_to_stream(yday, float(stream_totals["yday_ex6_actual"]))[["date", "ticker", "sleeve", "stream_pnl", "stream_notional"]])

    intraday = pd.read_csv("STOCKS_INTRADAY_FOCUSED_RULES_TRADES_2026-09-08.csv", parse_dates=["date"])
    intraday = intraday[
        (intraday["date"] >= START)
        & (intraday["date"] <= END)
        & (intraday["dropSet"].astype(str).str.contains("DE", regex=False))
        & (intraday["slots"].eq(20))
    ].copy()
    intraday["base_pnl"] = intraday["ret"].astype(float)
    intraday["base_notional"] = 1.0
    intraday = intraday[["date", "ticker", "base_pnl", "base_notional"]]
    intraday["sleeve"] = "intraday_ex10"
    rows.append(scale_to_stream(intraday, float(stream_totals["intraday_ex10"]))[["date", "ticker", "sleeve", "stream_pnl", "stream_notional"]])

    out = pd.concat(rows, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    out["ticker"] = out["ticker"].astype(str)
    return out


def apply_notional_cap(picks: pd.DataFrame, cap_abs: float | None) -> pd.DataFrame:
    out = picks.copy()
    if cap_abs is None:
        out["cap_scale"] = 1.0
        out["pnl_capped"] = out["pnl"]
        out["notional_capped"] = out["notional"]
        return out
    scale = np.minimum(1.0, cap_abs / out["notional"].replace(0.0, np.nan).abs())
    out["cap_scale"] = scale.fillna(1.0)
    out["pnl_capped"] = out["pnl"] * out["cap_scale"]
    out["notional_capped"] = out["notional"] * out["cap_scale"]
    return out


def main() -> None:
    signals = ranker.load_signals()
    detail = load_detail_with_notional()
    merged = signals.merge(detail, on=["date", "ticker", "sleeve"], how="inner")
    all_dates = pd.DataFrame({"date": sorted(merged["date"].drop_duplicates())})
    rows = []

    for portfolio, weights in ranker.PORTFOLIOS.items():
        x = merged[merged["sleeve"].isin(weights)].copy()
        x["weight"] = x["sleeve"].map(weights).astype(float)
        x["weighted_pnl"] = x["stream_pnl"] * x["weight"]
        x["weighted_notional"] = x["stream_notional"] * x["weight"]
        x["weighted_strength"] = x["strength"] * x["weight"]
        td = (
            x.groupby(["date", "ticker"])
            .agg(
                sleeveCount=("sleeve", "nunique"),
                strengthAvg=("strength", "mean"),
                weightedStrength=("weighted_strength", "sum"),
                pnl=("weighted_pnl", "sum"),
                notional=("weighted_notional", "sum"),
            )
            .reset_index()
        )
        td["rankScore"] = td["sleeveCount"] + td["weightedStrength"]
        td = td.sort_values(["date", "rankScore", "strengthAvg"], ascending=[True, False, False])

        for top_k in [0, 40, 30, 20]:
            picks = td if top_k == 0 else td.groupby("date", group_keys=False).head(top_k).copy()
            for cap_pct in [None, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.75, 1.00]:
                cap_abs = None if cap_pct is None else START_CAPITAL * cap_pct
                capped = apply_notional_cap(picks, cap_abs)
                daily = all_dates.merge(capped.groupby("date")["pnl_capped"].sum().reset_index(), on="date", how="left").fillna({"pnl_capped": 0.0})
                s = summarize(daily, daily["pnl_capped"])
                ticker = capped.groupby("ticker")["pnl_capped"].sum().sort_values(ascending=False)
                rows.append(
                    {
                        "portfolio": portfolio,
                        "topK": "all" if top_k == 0 else top_k,
                        "capPctNav": "none" if cap_pct is None else cap_pct,
                        "capDollarsAt50k": "none" if cap_abs is None else cap_abs,
                        "tickerDates": int(len(picks)),
                        "avgTickerDatesPerDay": float(picks.groupby("date").size().mean()),
                        "avgNotionalPerTickerDate": float(picks["notional"].mean()),
                        "p95NotionalPerTickerDate": float(picks["notional"].quantile(0.95)),
                        "maxNotionalPerTickerDate": float(picks["notional"].max()),
                        "cappedTickerDates": int((capped["cap_scale"] < 1.0).sum()),
                        "avgCapScale": float(capped["cap_scale"].mean()),
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
