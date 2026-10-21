from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_full_no_intraday_replay_nowarmup as base


OUT_PREFIX = "STOCKS_PIT_FULL_RESTRICTED62_NOWARMUP_2026-09-13"
POLY62_TRADES = Path("STOCKS_POLYGON62_PIT_REPLAY_2016WARMUP_2018_2024_TRADES.csv")

BROAD_TRADES = Path(f"{OUT_PREFIX}_BROAD_TRADES.csv")
LOCAL_TRADES = Path(f"{OUT_PREFIX}_LOCAL_TRADES.csv")
YDAY_TRADES = Path(f"{OUT_PREFIX}_YDAY_TRADES.csv")
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
TRADES_OUT = Path(f"{OUT_PREFIX}_TRADES.csv")
GATE_QA_OUT = Path(f"{OUT_PREFIX}_GATE_QA.csv")
COMPARE_OUT = Path(f"{OUT_PREFIX}_COMPARE_TO_POLY62_FROM_START.csv")
OVERLAP_OUT = Path(f"{OUT_PREFIX}_TRADE_KEY_OVERLAP.csv")


def poly62_tickers() -> set[str]:
    trades = pd.read_csv(POLY62_TRADES, usecols=["portfolio", "ticker"])
    return set(trades[trades["portfolio"].eq("B_polygon62_no_intraday_cap40_PIT")]["ticker"].astype(str).unique())


def configure_paths() -> None:
    base.configure_poly()
    base.BROAD_TRADES = BROAD_TRADES
    base.LOCAL_TRADES = LOCAL_TRADES
    base.YDAY_TRADES = YDAY_TRADES
    base.poly.BROAD_TRADES = BROAD_TRADES
    base.poly.LOCAL_TRADES = LOCAL_TRADES
    base.poly.YDAY_TRADES = YDAY_TRADES


def yearly(eq: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for portfolio, group_port in eq.groupby("portfolio", sort=True):
        for year, group in group_port.assign(year=group_port["date"].dt.year).groupby("year", sort=True):
            curve = group["daily_pnl"].cumsum()
            std = float(group["daily_pnl"].std())
            rows.append(
                {
                    "portfolio": portfolio,
                    "year": int(year),
                    "pnl": float(group["daily_pnl"].sum()),
                    "dd": float((curve - curve.cummax()).min()),
                    "sharpe": float(group["daily_pnl"].mean() / std * np.sqrt(252)) if std > 0 else np.nan,
                    "avgGross": float(group["gross"].mean()),
                    "maxGross": float(group["gross"].max()),
                }
            )
    return pd.DataFrame(rows)


def compare_to_poly62(restricted_trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    poly = pd.read_csv(POLY62_TRADES, parse_dates=["date"])
    poly = poly[poly["portfolio"].eq("B_polygon62_no_intraday_cap40_PIT")].copy()
    start = pd.to_datetime(restricted_trades["date"]).min()
    poly = poly[pd.to_datetime(poly["date"]).ge(start)].copy()
    restricted = restricted_trades[restricted_trades["portfolio"].eq("B_pit_restricted62_nowarmup_cap40")].copy()
    poly["source"] = "polygon62_warmup_from_restricted_start"
    restricted["source"] = "pit_restricted62_nowarmup"
    for df in (poly, restricted):
        df["year"] = pd.to_datetime(df["date"]).dt.year

    compare = (
        pd.concat([poly, restricted], ignore_index=True)
        .groupby(["source", "year", "sleeve"], as_index=False)
        .agg(trades=("pnl", "size"), pnl=("pnl", "sum"), avg_pnl=("pnl", "mean"), win_rate=("pnl", lambda s: float((s > 0).mean())))
    )

    keys = ["date", "ticker", "sleeve"]
    p = poly[keys + ["pnl"]].rename(columns={"pnl": "poly_pnl"})
    r = restricted[keys + ["pnl"]].rename(columns={"pnl": "restricted_pnl"})
    overlap = (
        p.merge(r, on=keys, how="outer", indicator=True)
        .groupby(["sleeve", "_merge"], observed=True, as_index=False)
        .agg(rows=("date", "size"), poly_pnl=("poly_pnl", "sum"), restricted_pnl=("restricted_pnl", "sum"))
    )
    return compare, overlap


def main() -> None:
    configure_paths()
    tickers = poly62_tickers()
    daily = pd.read_pickle(base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily62 = daily[daily["ticker"].astype(str).isin(tickers)].copy()
    intraday = pd.read_pickle(base.INTRADAY_0935)
    intraday["date"] = pd.to_datetime(intraday["date"])
    intraday62 = intraday[intraday["ticker"].astype(str).isin(tickers)].copy()

    base.poly.build_broad_trades(daily62)
    base.poly.build_local_trades(daily62)
    base.build_yday_trades_from_daily(daily62)

    daily_px = base.poly.load_daily_prices_from_polygon(daily62)
    daily_px["date"] = pd.to_datetime(daily_px["date"])
    intraday_px = intraday62[["date", "ticker", "open930", "entry935", "exit1555"]].copy()
    signals = base.load_signals_no_intraday(daily_px, intraday_px)
    gate = base.pit_gate.load_pit_gate()
    gated_signals, gate_qa, _, _ = base.pit_gate.apply_pit_gate(signals, gate)
    gate_qa.to_csv(GATE_QA_OUT, index=False)

    cfg = base.PORTFOLIOS["B_pit_full_no_intraday_nowarmup_cap40"]
    summary, eq, trades = base.poly.simulate("B_pit_restricted62_nowarmup_cap40", cfg, gated_signals, daily_px)
    pd.DataFrame([summary]).to_csv(SUMMARY_OUT, index=False)
    yearly(eq).to_csv(YEARLY_OUT, index=False)
    trades.to_csv(TRADES_OUT, index=False)
    compare, overlap = compare_to_poly62(trades)
    compare.to_csv(COMPARE_OUT, index=False)
    overlap.to_csv(OVERLAP_OUT, index=False)
    print("SUMMARY", summary, flush=True)
    print("COMPARE")
    print(compare.to_string(index=False), flush=True)
    print("OVERLAP")
    print(overlap.to_string(index=False), flush=True)
    print("WROTE", OUT_PREFIX, flush=True)


if __name__ == "__main__":
    main()
