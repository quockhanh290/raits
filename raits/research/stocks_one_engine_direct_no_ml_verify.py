from __future__ import annotations

from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import stocks_databento_daily_xs_mtm as broad_src
import stocks_databento_daily_xs_mtm_dd_overlay as broad_overlay
import stocks_daily_xs_ret5_bottom_h20_full as local_xs
import stocks_intraday_focused_rule_miner as intraday_gen
import stocks_one_engine_mtm_portfolio as engine
import stocks_wfo_clean_retest as yday_gen


SUMMARY_OUT = Path("STOCKS_ONE_ENGINE_DIRECT_NO_ML_SUMMARY_2026-09-09.csv")
EQUITY_OUT = Path("STOCKS_ONE_ENGINE_DIRECT_NO_ML_EQUITY_2026-09-09.csv")
TRADES_OUT = Path("STOCKS_ONE_ENGINE_DIRECT_NO_ML_TRADES_2026-09-09.csv")
VERIFY_OUT = Path("STOCKS_ONE_ENGINE_DIRECT_NO_ML_VERIFY_2026-09-09.csv")

CANON_SUMMARY = Path("STOCKS_ONE_ENGINE_MTM_PORTFOLIO_2026-09-09.csv")
TOLERANCE = 1e-8

DIRECT_PORTFOLIOS = [
    "A_no_ml_all_cap40",
    "A_no_ml_top40_cap40",
    "B_no_ml_all_cap40",
    "B_no_ml_top40_cap40",
    "A_no_ml_intraday_full_cap40",
    "B_no_ml_intraday_full_cap40",
]


def build_broad_trades() -> pd.DataFrame:
    _, trades, _ = broad_src.simulate(broad_src.load_panel(), broad_overlay.config())
    return trades


def build_yday_trades() -> pd.DataFrame:
    bars_path = Path("raits/data/cache/window_debug_5min.pkl")
    with bars_path.open("rb") as f:
        bars = pickle.load(f)
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
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def build_intraday_trades() -> pd.DataFrame:
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
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def build_direct_no_ml_signals() -> pd.DataFrame:
    daily_px = engine.load_daily_prices()
    intraday_px = engine.load_intraday_prices()
    exit20 = engine.nth_exit_dates(daily_px, 20)

    signals = []

    broad = build_broad_trades()
    broad = broad[(broad["entry_date"] >= engine.START) & (broad["entry_date"] <= engine.END)].copy()
    b = broad.rename(columns={"entry_date": "date", "symbol": "ticker", "planned_exit_date": "exit_date"})
    b["ticker"] = b["ticker"].astype(str)
    b["sleeve"] = "broad_adv10_g2_dd85"
    b["side"] = 1
    b["hold_days"] = 20
    b["entry_style"] = "daily_open"
    b["exit_style"] = "daily_close"
    b["base_notional"] = b["entry_notional"].astype(float)
    b["raw_strength"] = -b["ret5"].astype(float)
    signals.append(b[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    local = local_xs.build()
    local = local[(local["date"] >= engine.START) & (local["date"] <= engine.END)].copy()
    local = local.merge(exit20, on=["date", "ticker"], how="left").rename(columns={"exit_date_20": "exit_date"})
    local["sleeve"] = "local_xs_full_s10"
    local["side"] = 1
    local["hold_days"] = 20
    local["entry_style"] = "daily_open"
    local["exit_style"] = "daily_close"
    local["base_pnl"] = local["pnl"].astype(float)
    local["base_notional"] = engine.infer_notional(local["base_pnl"], local["ret"])
    local["raw_strength"] = -local["ret5_pre_clean"].astype(float)
    signals.append(local[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    yday = build_yday_trades()
    yday = yday[(yday["date"] >= engine.START) & (yday["date"] <= engine.END) & (yday["wfo_mode"].eq("rolling3"))].copy()
    yday["sleeve"] = "yday_ex6_actual"
    yday["side"] = 1
    yday["hold_days"] = 0
    yday["entry_style"] = np.where(yday["entry_time"].astype(str).str.contains("09:35"), "entry935", "open930")
    yday["exit_style"] = "exit1555"
    yday["exit_date"] = yday["date"]
    yday["base_pnl"] = yday["pnl"].astype(float)
    yday["base_notional"] = engine.infer_notional(yday["base_pnl"], yday["gross_ret"])
    yday["raw_strength"] = 1.0
    signals.append(yday[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    intraday = build_intraday_trades()
    intraday = intraday[(intraday["date"] >= engine.START) & (intraday["date"] <= engine.END)].copy()

    ex10 = intraday[
        intraday["dropSet"].astype(str).str.contains("DE", regex=False)
        & intraday["slots"].eq(20)
    ].copy()
    ex10["sleeve"] = "intraday_ex10"
    ex10["side"] = np.where(ex10["side"].eq("short"), -1, 1)
    ex10["hold_days"] = 0
    ex10["entry_style"] = "entry935"
    ex10["exit_style"] = "exit1555"
    ex10["exit_date"] = ex10["date"]
    ex10["base_pnl"] = ex10["ret"].astype(float)
    ex10["base_notional"] = 1.0
    ex10["raw_strength"] = ex10["train_score"].astype(float)
    signals.append(ex10[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    full = intraday[intraday["dropSet"].eq("FULL")].copy()
    full["sleeve"] = "intraday_full"
    full["side"] = np.where(full["side"].eq("short"), -1, 1)
    full["hold_days"] = 0
    full["entry_style"] = "entry935"
    full["exit_style"] = "exit1555"
    full["exit_date"] = full["date"]
    full["base_pnl"] = full["ret"].astype(float)
    full["base_notional"] = 1.0
    full["raw_strength"] = full["train_score"].astype(float)
    signals.append(full[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    sig = pd.concat(signals, ignore_index=True)
    sig["date"] = pd.to_datetime(sig["date"])
    sig["exit_date"] = pd.to_datetime(sig["exit_date"])
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


def main() -> None:
    daily_px = engine.load_daily_prices()
    signals = build_direct_no_ml_signals()

    summaries = []
    equities = []
    trades = []
    for name in DIRECT_PORTFOLIOS:
        summary, eq, tr = engine.simulate(name, engine.PORTFOLIOS[name], signals, daily_px)
        summaries.append(summary)
        equities.append(eq)
        trades.append(tr)
        print(name, summary, flush=True)

    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(SUMMARY_OUT, index=False)
    pd.concat(equities, ignore_index=True).to_csv(EQUITY_OUT, index=False)
    pd.concat(trades, ignore_index=True).to_csv(TRADES_OUT, index=False)

    canon = pd.read_csv(CANON_SUMMARY)
    canon = canon[canon["portfolio"].isin(DIRECT_PORTFOLIOS)].set_index("portfolio")
    direct = summary_df.set_index("portfolio")
    numeric_cols = [c for c in direct.columns if c in canon.columns and pd.api.types.is_numeric_dtype(direct[c])]

    rows = []
    for portfolio in DIRECT_PORTFOLIOS:
        diffs = (direct.loc[portfolio, numeric_cols].astype(float) - canon.loc[portfolio, numeric_cols].astype(float)).abs()
        max_diff = float(diffs.max())
        status = "MATCH" if max_diff <= TOLERANCE else "DRIFT_VS_LEGACY_STREAM_CSV"
        rows.append(
            {
                "portfolio": portfolio,
                "status": status,
                "tolerance": TOLERANCE,
                "maxAbsDiff": max_diff,
                "diffColumns": int((diffs > 0.0).sum()),
                "pnl": float(direct.loc[portfolio, "pnl"]),
                "canonicalPnl": float(canon.loc[portfolio, "pnl"]),
                "deltaPnl": float(direct.loc[portfolio, "pnl"] - canon.loc[portfolio, "pnl"]),
                "dd": float(direct.loc[portfolio, "dd"]),
                "canonicalDd": float(canon.loc[portfolio, "dd"]),
                "deltaDd": float(direct.loc[portfolio, "dd"] - canon.loc[portfolio, "dd"]),
                "sharpe": float(direct.loc[portfolio, "sharpe"]),
                "canonicalSharpe": float(canon.loc[portfolio, "sharpe"]),
                "deltaSharpe": float(direct.loc[portfolio, "sharpe"] - canon.loc[portfolio, "sharpe"]),
            }
        )

    verify = pd.DataFrame(rows)
    verify.to_csv(VERIFY_OUT, index=False)
    print(verify.to_string(index=False))
    print("WROTE", SUMMARY_OUT, EQUITY_OUT, TRADES_OUT, VERIFY_OUT)


if __name__ == "__main__":
    main()
