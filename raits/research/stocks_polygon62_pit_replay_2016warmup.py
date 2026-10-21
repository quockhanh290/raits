from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_polygon_2018_2024_no_ml_pipeline as poly


START = pd.Timestamp("2018-01-01")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = poly.START_CAPITAL

PIT_FILTER = Path(
    "raits/data/cache/stocks_survivorship/polygon_universe_bulk/"
    "daily_20180102_20241231_resumable/"
    "liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/"
    "filtered_daily_universe.parquet"
)

OUT_PREFIX = "STOCKS_POLYGON62_PIT_REPLAY_2016WARMUP_2018_2024"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
EQUITY_OUT = Path(f"{OUT_PREFIX}_EQUITY.csv")
TRADES_OUT = Path(f"{OUT_PREFIX}_TRADES.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
GATE_QA_OUT = Path(f"{OUT_PREFIX}_GATE_QA.csv")
GATE_DAILY_OUT = Path(f"{OUT_PREFIX}_GATE_DAILY.csv")
GATE_REASON_OUT = Path(f"{OUT_PREFIX}_GATE_REASON.csv")


PORTFOLIOS = {
    "A_polygon62_no_intraday_cap40_PIT": poly.LEAD_PORTFOLIOS["A_polygon62_no_intraday_cap40"],
    "B_polygon62_no_intraday_cap40_PIT": poly.LEAD_PORTFOLIOS["B_polygon62_no_intraday_cap40"],
    "A_polygon62_all_cap40_PIT": poly.LEAD_PORTFOLIOS["A_polygon62_all_cap40"],
    "B_polygon62_all_cap40_PIT": poly.LEAD_PORTFOLIOS["B_polygon62_all_cap40"],
}


def configure_poly() -> None:
    poly.BARS = Path("raits/data/cache/window_debug_5min_POLYGON_2016WARMUP_2018_2024_62.pkl")
    poly.DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_POLYGON62_2016WARMUP_2018_2024.pkl")
    poly.INTRADAY_0935 = Path("raits/data/cache/stocks_intraday_0935_features_POLYGON62_2016WARMUP_2018_2024.pkl")
    poly.GAP_RVOL30 = Path("raits/data/cache/stocks_gap_rvol30_features_POLYGON62_2016WARMUP_2018_2024.pkl")

    poly.BROAD_TRADES = Path("STOCKS_POLYGON62_BROAD_ADV10_G2_DD85_TRADES_2016WARMUP_2018_2024.csv")
    poly.LOCAL_TRADES = Path("STOCKS_POLYGON62_LOCAL_XS_FULL_S10_TRADES_2016WARMUP_2018_2024.csv")
    poly.YDAY_TRADES = Path("STOCKS_POLYGON62_YDAY_EX6_ACTUAL_TRADES_2016WARMUP_2018_2024.csv")
    poly.INTRADAY_TRADES = Path("STOCKS_POLYGON62_INTRADAY_FOCUSED_TRADES_2016WARMUP_2018_2024.csv")

    poly.START = START
    poly.END = END


def load_daily_prices_scoring_window() -> pd.DataFrame:
    daily = pd.read_pickle(poly.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    px = poly.load_daily_prices_from_polygon(daily)
    px["date"] = pd.to_datetime(px["date"])
    return px[(px["date"] >= START) & (px["date"] <= END)].copy()


def load_intraday_prices() -> pd.DataFrame:
    intraday = pd.read_pickle(poly.INTRADAY_0935)
    intraday["date"] = pd.to_datetime(intraday["date"])
    return intraday[["date", "ticker", "open930", "entry935", "exit1555"]].copy()


def load_pit_gate() -> pd.DataFrame:
    if not PIT_FILTER.exists():
        raise SystemExit(f"missing PIT filter artifact: {PIT_FILTER}")
    gate = pd.read_parquet(
        PIT_FILTER,
        columns=[
            "date",
            "ticker",
            "security_id",
            "eligible_final",
            "reason_excluded",
            "has_current_daily_bar",
            "liquidity_metric_source",
        ],
    )
    gate["date"] = pd.to_datetime(gate["date"])
    gate["ticker"] = gate["ticker"].astype(str)
    gate = gate[(gate["date"] >= START) & (gate["date"] <= END)].copy()
    return gate


def apply_pit_gate(signals: pd.DataFrame, gate: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    exact_gate = gate[
        [
            "date",
            "ticker",
            "security_id",
            "eligible_final",
            "reason_excluded",
            "has_current_daily_bar",
            "liquidity_metric_source",
        ]
    ].drop_duplicates(["date", "ticker"])
    merged = signals.merge(exact_gate, on=["date", "ticker"], how="left")
    merged["pit_gate_mode"] = np.where(merged["eligible_final"].notna(), "exact_ticker", "")

    missing_mask = merged["eligible_final"].isna()
    if missing_mask.any():
        ticker_security_ids = (
            gate[["ticker", "security_id"]]
            .dropna()
            .drop_duplicates()
            .rename(columns={"ticker": "signal_ticker"})
        )
        alias_gate = gate[
            [
                "date",
                "ticker",
                "security_id",
                "eligible_final",
                "reason_excluded",
                "has_current_daily_bar",
                "liquidity_metric_source",
            ]
        ].rename(columns={"ticker": "pit_ticker"})
        alias_candidates = (
            merged.loc[missing_mask, ["date", "ticker"]]
            .drop_duplicates()
            .rename(columns={"ticker": "signal_ticker"})
            .merge(ticker_security_ids, on="signal_ticker", how="left")
            .merge(alias_gate, on=["date", "security_id"], how="left")
            .dropna(subset=["pit_ticker"])
        )
        if not alias_candidates.empty:
            alias_candidates["alias_rank"] = np.where(alias_candidates["eligible_final"].astype(bool), 0, 1)
            alias_candidates = alias_candidates.sort_values(["date", "signal_ticker", "alias_rank", "pit_ticker"])
            alias_candidates = alias_candidates.drop_duplicates(["date", "signal_ticker"])
            alias_candidates = alias_candidates.rename(columns={"signal_ticker": "ticker"})
            fill_cols = [
                "security_id",
                "eligible_final",
                "reason_excluded",
                "has_current_daily_bar",
                "liquidity_metric_source",
            ]
            merged = merged.merge(
                alias_candidates[["date", "ticker", "pit_ticker", *fill_cols]],
                on=["date", "ticker"],
                how="left",
                suffixes=("", "_alias"),
            )
            has_alias = merged["eligible_final"].isna() & merged["eligible_final_alias"].notna()
            for col in fill_cols:
                merged.loc[has_alias, col] = merged.loc[has_alias, f"{col}_alias"]
                merged = merged.drop(columns=[f"{col}_alias"])
            merged.loc[has_alias, "pit_gate_mode"] = "security_alias:" + merged.loc[has_alias, "pit_ticker"].astype(str)
            merged = merged.drop(columns=["pit_ticker"])

    merged["pit_gate_present"] = merged["eligible_final"].notna()
    merged["eligible_final"] = pd.Series(
        np.where(merged["eligible_final"].isna(), False, merged["eligible_final"]),
        index=merged.index,
    ).astype(bool)
    merged["pit_reason"] = merged["reason_excluded"].fillna("missing_from_pit_universe").astype(str)
    merged.loc[merged["eligible_final"], "pit_reason"] = ""
    kept = merged[merged["eligible_final"]].copy()

    qa_rows = []
    for sleeve, group in merged.groupby("sleeve", sort=True):
        removed = group[~group["eligible_final"]]
        qa_rows.append(
            {
                "sleeve": sleeve,
                "signals_before": int(len(group)),
                "signals_after": int(group["eligible_final"].sum()),
                "signals_removed": int((~group["eligible_final"]).sum()),
                "removed_pct": float((~group["eligible_final"]).mean()) if len(group) else 0.0,
                "missing_from_pit": int((~group["pit_gate_present"]).sum()),
                "security_alias_rows": int(group["pit_gate_mode"].astype(str).str.startswith("security_alias").sum()),
                "ticker_fallback_rows": int((group["liquidity_metric_source"].fillna("") == "ticker_fallback").sum()),
                "unique_tickers_before": int(group["ticker"].nunique()),
                "unique_tickers_after": int(kept[kept["sleeve"].eq(sleeve)]["ticker"].nunique()),
            }
        )
    qa = pd.DataFrame(qa_rows)

    daily = (
        merged.groupby(["date", "sleeve"], as_index=False)
        .agg(
            signals_before=("ticker", "count"),
            signals_after=("eligible_final", "sum"),
            missing_from_pit=("pit_gate_present", lambda s: int((~s.astype(bool)).sum())),
        )
        .sort_values(["date", "sleeve"])
    )
    reasons = (
        merged[~merged["eligible_final"]]
        .groupby(["sleeve", "pit_reason"], as_index=False)
        .agg(rows=("ticker", "count"), unique_tickers=("ticker", "nunique"))
        .sort_values(["sleeve", "rows"], ascending=[True, False])
    )
    return kept.drop(columns=["pit_reason"]), qa, daily, reasons


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


def write_yearly_metrics(eq: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for portfolio, group_port in eq.groupby("portfolio", sort=True):
        for year, group in group_port.assign(year=group_port["date"].dt.year).groupby("year", sort=True):
            curve = group["daily_pnl"].cumsum()
            rows.append(
                {
                    "portfolio": portfolio,
                    "year": int(year),
                    "days": int(len(group)),
                    "pnl": float(group["daily_pnl"].sum()),
                    "ddSubset": float((curve - curve.cummax()).min()),
                    "sharpe": sharpe(group["daily_pnl"]),
                    "avgGross": float(group["gross"].mean()),
                    "maxGross": float(group["gross"].max()),
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(YEARLY_OUT, index=False)
    return out


def main() -> None:
    configure_poly()
    daily_px = load_daily_prices_scoring_window()
    intraday_px = load_intraday_prices()
    signals = poly.load_signals(daily_px, intraday_px)
    gate = load_pit_gate()
    gated_signals, gate_qa, gate_daily, gate_reasons = apply_pit_gate(signals, gate)

    gate_qa.to_csv(GATE_QA_OUT, index=False)
    gate_daily.to_csv(GATE_DAILY_OUT, index=False)
    gate_reasons.to_csv(GATE_REASON_OUT, index=False)
    print("PIT_GATE", gate_qa.to_string(index=False), flush=True)

    summaries = []
    equities = []
    trades = []
    for name, cfg in PORTFOLIOS.items():
        summary, eq, tr = poly.simulate(name, cfg, gated_signals, daily_px)
        summaries.append(summary)
        equities.append(eq)
        trades.append(tr)
        print("PIT_ENGINE", name, summary, flush=True)

    summary_df = pd.DataFrame(summaries)
    equity_df = pd.concat(equities, ignore_index=True)
    trades_df = pd.concat(trades, ignore_index=True)
    summary_df.to_csv(SUMMARY_OUT, index=False)
    equity_df.to_csv(EQUITY_OUT, index=False)
    trades_df.to_csv(TRADES_OUT, index=False)
    write_yearly_metrics(equity_df)
    print("WROTE", SUMMARY_OUT, EQUITY_OUT, TRADES_OUT, YEARLY_OUT, GATE_QA_OUT, flush=True)


if __name__ == "__main__":
    main()
