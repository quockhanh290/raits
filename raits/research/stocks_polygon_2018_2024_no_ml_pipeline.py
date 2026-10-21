from __future__ import annotations

from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import stocks_databento_daily_xs_mtm_dd_overlay as broad_overlay
import stocks_feature_cache_builder as feature_builder
import stocks_intraday_focused_rule_miner as intraday_gen
import stocks_one_engine_mtm_portfolio as engine
import stocks_wfo_clean_retest as yday_gen


BARS = Path("raits/data/cache/window_debug_5min_POLYGON_2018_2024_62.pkl")
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_POLYGON62_2018_2024.pkl")
INTRADAY_0935 = Path("raits/data/cache/stocks_intraday_0935_features_POLYGON62_2018_2024.pkl")
GAP_RVOL30 = Path("raits/data/cache/stocks_gap_rvol30_features_POLYGON62_2018_2024.pkl")

BROAD_TRADES = Path("STOCKS_POLYGON62_BROAD_ADV10_G2_DD85_TRADES_2018_2024.csv")
LOCAL_TRADES = Path("STOCKS_POLYGON62_LOCAL_XS_FULL_S10_TRADES_2018_2024.csv")
YDAY_TRADES = Path("STOCKS_POLYGON62_YDAY_EX6_ACTUAL_TRADES_2018_2024.csv")
INTRADAY_TRADES = Path("STOCKS_POLYGON62_INTRADAY_FOCUSED_TRADES_2018_2024.csv")

SUMMARY_OUT = Path("STOCKS_POLYGON62_ONE_ENGINE_NO_ML_SUMMARY_2018_2024.csv")
EQUITY_OUT = Path("STOCKS_POLYGON62_ONE_ENGINE_NO_ML_EQUITY_2018_2024.csv")
TRADES_OUT = Path("STOCKS_POLYGON62_ONE_ENGINE_NO_ML_TRADES_2018_2024.csv")
SPLIT_OUT = Path("STOCKS_POLYGON62_ONE_ENGINE_NO_ML_SPLITS_2018_2024.csv")

START = pd.Timestamp("2018-01-01")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 50_000.0
COST_BPS = 4.0
LEAD_PORTFOLIOS = {
    "A_polygon62_all_cap40": {
        "weights": {
            "broad_adv10_g2_dd85": 0.40,
            "local_xs_full_s10": 0.40,
            "yday_ex6_actual": 0.40,
            "intraday_ex10": 0.40,
        },
        "top_k": None,
        "ticker_cap_pct": 0.40,
        "gross_cap": 2.0,
    },
    "B_polygon62_all_cap40": {
        "weights": {
            "broad_adv10_g2_dd85": 0.35,
            "local_xs_full_s10": 0.35,
            "yday_ex6_actual": 0.35,
            "intraday_ex10": 0.35,
        },
        "top_k": None,
        "ticker_cap_pct": 0.40,
        "gross_cap": 1.75,
    },
    "A_polygon62_no_intraday_cap40": {
        "weights": {
            "broad_adv10_g2_dd85": 0.40,
            "local_xs_full_s10": 0.40,
            "yday_ex6_actual": 0.40,
        },
        "top_k": None,
        "ticker_cap_pct": 0.40,
        "gross_cap": 2.0,
    },
    "B_polygon62_no_intraday_cap40": {
        "weights": {
            "broad_adv10_g2_dd85": 0.35,
            "local_xs_full_s10": 0.35,
            "yday_ex6_actual": 0.35,
        },
        "top_k": None,
        "ticker_cap_pct": 0.40,
        "gross_cap": 1.75,
    },
}


def load_bars() -> dict[str, pd.DataFrame]:
    with BARS.open("rb") as f:
        return pickle.load(f)


def build_features(bars: dict[str, pd.DataFrame]) -> None:
    daily = feature_builder.build_clean_daily(bars)
    rows_0935, rows_1000 = feature_builder.intraday_rows(bars)
    p935 = feature_builder.build_intraday_0935(rows_0935)
    p1000 = feature_builder.build_gap_rvol30(rows_1000, rows_0935)
    daily.to_pickle(DAILY_FEATURES)
    p935.to_pickle(INTRADAY_0935)
    p1000.to_pickle(GAP_RVOL30)
    print("FEATURES", len(daily), len(p935), len(p1000), flush=True)


def build_broad_trades(daily: pd.DataFrame) -> pd.DataFrame:
    panel = daily.rename(
        columns={
            "ticker": "symbol",
            "open_0930": "open",
            "close_1555": "close",
            "volume_0930": "volume",
        }
    )[["symbol", "date", "open", "close", "volume"]].copy()
    panel["dollar"] = panel["close"] * panel["volume"]
    panel = panel.sort_values(["symbol", "date"]).reset_index(drop=True)
    g = panel.groupby("symbol", sort=False)
    panel["adv20"] = g["dollar"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    prev_close = g["close"].shift(1)
    panel["ret5"] = prev_close / g["close"].shift(6) - 1.0
    for hold in [10, 20, 30]:
        panel[f"exit_date{hold}"] = g["date"].shift(-(hold - 1))
    panel["spy_vol20"] = np.nan
    panel = panel[(panel["date"] >= START) & (panel["date"] <= END)].replace([np.inf, -np.inf], np.nan)
    summary, trades, _ = broad_overlay.broad.simulate(panel, broad_overlay.config())
    trades.to_csv(BROAD_TRADES, index=False)
    print("BROAD", summary, flush=True)
    return trades


def build_local_trades(daily: pd.DataFrame) -> pd.DataFrame:
    daily = daily[daily["ticker"].ne("SPY")].sort_values(["ticker", "date"]).copy()
    g = daily.groupby("ticker", sort=False)
    prev_close = g["close_1555"].shift(1)
    daily["ret5_pre_clean"] = prev_close / g["close_1555"].shift(6) - 1.0
    daily["exit_close"] = g["close_1555"].shift(-19)
    daily["ret"] = daily["exit_close"] / daily["open_0930"] - 1.0
    data = daily.dropna(subset=["ret5_pre_clean", "ret", "open_0930", "exit_close"]).copy()
    data = data[(data["date"] >= START) & (data["date"] <= END)]
    data = data.sort_values(["date", "ret5_pre_clean", "ticker"])
    data["rank"] = data.groupby("date")["ret5_pre_clean"].rank(method="first", ascending=True)
    picks = data[data["rank"] <= 10].copy()
    picks["pnl"] = 200.0 * (picks["ret"] - 0.0004)
    out = picks[["date", "ticker", "ret5_pre_clean", "rank", "ret", "pnl"]].reset_index(drop=True)
    out.to_csv(LOCAL_TRADES, index=False)
    print("LOCAL rows", len(out), "pnl", float(out["pnl"].sum()), flush=True)
    return out


def build_yday_trades(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    daily, _ = yday_gen.build_daily_table(bars, "skip")
    pe_signals = yday_gen.build_pe_signals(daily, set())
    signal_by_rule = {rule.name: yday_gen.apply_rule(daily, rule) for rule in yday_gen.DECLARED_RULE_POOL}
    outputs = []
    for mode in ("anchored", "rolling3"):
        _, trades, _ = yday_gen.run_wfo(
            signal_by_rule,
            pe_signals,
            mode=mode,
            test_years=yday_gen.DEFAULT_TEST_YEARS,
            include_pe=False,
            start_capital=yday_gen.START_CAPITAL,
            position_pct=0.80,
            max_positions=1,
            cost_bps=yday_gen.DEFAULT_COST_BPS,
        )
        if not trades.empty:
            outputs.append(trades.assign(wfo_mode=mode))
    out = pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()
    out.to_csv(YDAY_TRADES, index=False)
    print("YDAY rows", len(out), "pnl", float(out["pnl"].sum()) if "pnl" in out else 0.0, flush=True)
    return out


def intraday_panels_from_polygon() -> pd.DataFrame:
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = intraday_gen.add_clean_daily_features(daily)
    keep = [
        "date",
        "ticker",
        "prev_dayret",
        "spy_prev_dayret",
        "ret3_pre_clean",
        "ret5_pre_clean",
        "ret10_pre_clean",
        "ret20_pre_clean",
        "gap",
    ]
    p935 = pd.read_pickle(INTRADAY_0935)
    p935["date"] = pd.to_datetime(p935["date"])
    p935 = p935.merge(daily[keep], on=["date", "ticker"], how="left")
    p935 = p935.rename(columns={"ret935_eod": "target", "rvol930": "rvol"})
    p935["entry"] = "0935"
    p1000 = pd.read_pickle(GAP_RVOL30)
    p1000["date"] = pd.to_datetime(p1000["date"])
    p1000 = p1000.merge(daily[keep], on=["date", "ticker"], how="left")
    if "gap_x" in p1000.columns:
        p1000["gap"] = p1000["gap_x"]
    p1000 = p1000.rename(columns={"ret1000_eod": "target", "rvol30": "rvol"})
    p1000["entry"] = "1000"
    p1000["first5_ret"] = np.nan
    cols = [
        "date",
        "ticker",
        "year",
        "entry",
        "target",
        "prev_dayret",
        "spy_prev_dayret",
        "gap",
        "first5_ret",
        "rvol",
        "ret3_pre_clean",
        "ret5_pre_clean",
        "ret10_pre_clean",
        "ret20_pre_clean",
    ]
    return pd.concat([p935[cols], p1000[cols]], ignore_index=True)


def build_intraday_trades() -> pd.DataFrame:
    original = intraday_gen.build_panels
    intraday_gen.build_panels = intraday_panels_from_polygon
    try:
        drops = [
            (),
            ("META", "TSLA", "NVDA", "AMD", "BA", "NFLX"),
            ("META", "TSLA", "NVDA", "AMD", "BA", "NFLX", "DE", "CVX", "ADBE", "PYPL"),
        ]
        outputs = []
        for drop in drops:
            _, trades = intraday_gen.run(drop)
            if trades.empty:
                continue
            trades = trades.sort_values(["date", "rule", "ticker"]).copy()
            trades["pnl"] = (
                intraday_gen.CAPITAL
                * intraday_gen.GROSS
                / trades.groupby("date")["ticker"].transform("count")
                * (trades["ret"] - intraday_gen.COST)
            )
            outputs.append(trades.assign(dropSet="+".join(drop) if drop else "FULL"))
        out = pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()
        out.to_csv(INTRADAY_TRADES, index=False)
        print("INTRADAY rows", len(out), "pnl", float(out["pnl"].sum()) if "pnl" in out else 0.0, flush=True)
        return out
    finally:
        intraday_gen.build_panels = original


def load_daily_prices_from_polygon(daily: pd.DataFrame) -> pd.DataFrame:
    px = daily[daily["ticker"].ne("SPY")].rename(columns={"open_0930": "open", "close_1555": "close"})
    return px[["date", "ticker", "open", "close"]].copy()


def nth_exit_dates(px: pd.DataFrame, hold: int) -> pd.DataFrame:
    out = px[["date", "ticker"]].drop_duplicates().sort_values(["ticker", "date"]).copy()
    out[f"exit_date_{hold}"] = out.groupby("ticker")["date"].shift(-(hold - 1))
    return out


def infer_notional(pnl: pd.Series, ret: pd.Series) -> pd.Series:
    out = (pnl.astype(float) / ret.astype(float).replace(0.0, np.nan)).abs()
    med = float(out.replace([np.inf, -np.inf], np.nan).dropna().median()) if out.notna().any() else 0.0
    return out.replace([np.inf, -np.inf], np.nan).fillna(med)


def load_signals(daily_px: pd.DataFrame, intraday_px: pd.DataFrame) -> pd.DataFrame:
    exit20 = nth_exit_dates(daily_px, 20)
    signals = []

    broad = pd.read_csv(BROAD_TRADES, parse_dates=["entry_date", "planned_exit_date"])
    b = broad.rename(columns={"entry_date": "date", "symbol": "ticker", "planned_exit_date": "exit_date"})
    b["sleeve"] = "broad_adv10_g2_dd85"
    b["side"] = 1
    b["hold_days"] = 20
    b["entry_style"] = "daily_open"
    b["exit_style"] = "daily_close"
    b["base_notional"] = b["entry_notional"].astype(float)
    b["raw_strength"] = -b["ret5"].astype(float)
    signals.append(b[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    local = pd.read_csv(LOCAL_TRADES, parse_dates=["date"])
    local = local.merge(exit20, on=["date", "ticker"], how="left").rename(columns={"exit_date_20": "exit_date"})
    local["sleeve"] = "local_xs_full_s10"
    local["side"] = 1
    local["hold_days"] = 20
    local["entry_style"] = "daily_open"
    local["exit_style"] = "daily_close"
    local["base_notional"] = infer_notional(local["pnl"], local["ret"])
    local["raw_strength"] = -local["ret5_pre_clean"].astype(float)
    signals.append(local[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    yday = pd.read_csv(YDAY_TRADES, parse_dates=["date"])
    yday = yday[yday["wfo_mode"].eq("rolling3")].copy()
    yday["sleeve"] = "yday_ex6_actual"
    yday["side"] = 1
    yday["hold_days"] = 0
    yday["entry_style"] = np.where(yday["entry_time"].astype(str).str.contains("09:35"), "entry935", "open930")
    yday["exit_style"] = "exit1555"
    yday["exit_date"] = yday["date"]
    yday["base_notional"] = infer_notional(yday["pnl"], yday["gross_ret"])
    yday["raw_strength"] = 1.0
    signals.append(yday[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    intraday = pd.read_csv(INTRADAY_TRADES, parse_dates=["date"])
    intraday = intraday[intraday["dropSet"].astype(str).str.contains("DE", regex=False) & intraday["slots"].eq(20)].copy()
    intraday["sleeve"] = "intraday_ex10"
    intraday["side"] = np.where(intraday["side"].eq("short"), -1, 1)
    intraday["hold_days"] = 0
    intraday["entry_style"] = "entry935"
    intraday["exit_style"] = "exit1555"
    intraday["exit_date"] = intraday["date"]
    intraday["base_notional"] = 1.0
    intraday["raw_strength"] = intraday["train_score"].astype(float)
    signals.append(intraday[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    sig = pd.concat(signals, ignore_index=True)
    sig["date"] = pd.to_datetime(sig["date"])
    sig["exit_date"] = pd.to_datetime(sig["exit_date"])
    sig = sig[(sig["date"] >= START) & (sig["date"] <= END)]
    sig = sig.dropna(subset=["exit_date", "base_notional", "raw_strength"])
    sig = sig.drop_duplicates(["date", "ticker", "sleeve", "entry_style", "exit_style"])
    sig["strength"] = sig.groupby(["date", "sleeve"])["raw_strength"].rank(pct=True, method="average").fillna(1.0)
    daily_entry = daily_px.rename(columns={"open": "daily_open", "close": "daily_close"})
    sig = sig.merge(daily_entry, on=["date", "ticker"], how="left")
    sig = sig.merge(intraday_px, on=["date", "ticker"], how="left")
    sig["entry_price"] = np.nan
    sig.loc[sig["entry_style"].eq("daily_open"), "entry_price"] = sig.loc[sig["entry_style"].eq("daily_open"), "daily_open"]
    sig.loc[sig["entry_style"].eq("entry935"), "entry_price"] = sig.loc[sig["entry_style"].eq("entry935"), "entry935"]
    sig.loc[sig["entry_style"].eq("open930"), "entry_price"] = sig.loc[sig["entry_style"].eq("open930"), "open930"]
    sig["exit_price_same_day"] = sig["exit1555"]
    return sig.dropna(subset=["entry_price"])


def price_for(price_day: pd.DataFrame, ticker: str, field: str, fallback: float) -> float:
    if ticker in price_day.index and pd.notna(price_day.loc[ticker, field]):
        return float(price_day.loc[ticker, field])
    return fallback


def simulate(name: str, cfg: dict[str, object], signals: pd.DataFrame, daily_px: pd.DataFrame) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    old_start = engine.START
    old_end = engine.END
    engine.START = START
    engine.END = END
    try:
        return engine.simulate(name, cfg, signals, daily_px)
    finally:
        engine.START = old_start
        engine.END = old_end


def split_metrics(eq: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, group in eq.groupby("portfolio"):
        for label, start, end in [
            ("2018_2020_train", pd.Timestamp("2018-01-01"), pd.Timestamp("2020-12-31")),
            ("2021_2022_train", pd.Timestamp("2021-01-01"), pd.Timestamp("2022-12-31")),
            ("2023_2024_locked_validation", pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31")),
        ]:
            x = group[(group["date"] >= start) & (group["date"] <= end)].copy()
            if x.empty:
                continue
            pnl = float(x["daily_pnl"].sum())
            rows.append(
                {
                    "portfolio": name,
                    "split": label,
                    "days": int(len(x)),
                    "pnl": pnl,
                    "ddOnSubsetOrder": float((x["daily_pnl"].cumsum() - x["daily_pnl"].cumsum().cummax()).min()),
                    "sharpe": float(x["daily_pnl"].mean() / x["daily_pnl"].std() * np.sqrt(252)) if x["daily_pnl"].std() > 0 else np.nan,
                    "avgGross": float(x["gross"].mean()),
                    "maxGross": float(x["gross"].max()),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    bars = load_bars()
    build_features(bars)
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    build_broad_trades(daily)
    build_local_trades(daily)
    build_yday_trades(bars)
    build_intraday_trades()

    daily_px = load_daily_prices_from_polygon(daily)
    intraday_px = pd.read_pickle(INTRADAY_0935).rename(columns={"open930": "open930", "entry935": "entry935", "exit1555": "exit1555"})
    intraday_px["date"] = pd.to_datetime(intraday_px["date"])
    intraday_px = intraday_px[["date", "ticker", "open930", "entry935", "exit1555"]]
    signals = load_signals(daily_px, intraday_px)

    summaries = []
    equities = []
    trades = []
    for name, cfg in LEAD_PORTFOLIOS.items():
        summary, eq, tr = simulate(name, cfg, signals, daily_px)
        summaries.append(summary)
        equities.append(eq)
        trades.append(tr)
        print("ENGINE", name, summary, flush=True)
    summary_df = pd.DataFrame(summaries)
    equity_df = pd.concat(equities, ignore_index=True)
    trades_df = pd.concat(trades, ignore_index=True)
    summary_df.to_csv(SUMMARY_OUT, index=False)
    equity_df.to_csv(EQUITY_OUT, index=False)
    trades_df.to_csv(TRADES_OUT, index=False)
    split_metrics(equity_df).to_csv(SPLIT_OUT, index=False)
    print("WROTE", SUMMARY_OUT, EQUITY_OUT, TRADES_OUT, SPLIT_OUT)


if __name__ == "__main__":
    main()
