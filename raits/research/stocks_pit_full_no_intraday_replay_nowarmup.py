from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_polygon_2018_2024_no_ml_pipeline as poly
import stocks_polygon62_pit_replay_2016warmup as pit_gate
import stocks_wfo_clean_retest as yday_gen


START = pd.Timestamp("2018-01-01")
END = pd.Timestamp("2024-12-31")
OUT_PREFIX = "STOCKS_PIT_FULL_NO_INTRADAY_NOWARMUP_2018_2024"

DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
INTRADAY_0935 = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
BROAD_TRADES = Path(f"{OUT_PREFIX}_BROAD_TRADES.csv")
LOCAL_TRADES = Path(f"{OUT_PREFIX}_LOCAL_TRADES.csv")
YDAY_TRADES = Path(f"{OUT_PREFIX}_YDAY_TRADES.csv")
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
EQUITY_OUT = Path(f"{OUT_PREFIX}_EQUITY.csv")
TRADES_OUT = Path(f"{OUT_PREFIX}_TRADES.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
GATE_QA_OUT = Path(f"{OUT_PREFIX}_GATE_QA.csv")
GATE_DAILY_OUT = Path(f"{OUT_PREFIX}_GATE_DAILY.csv")
GATE_REASON_OUT = Path(f"{OUT_PREFIX}_GATE_REASON.csv")

PORTFOLIOS = {
    "A_pit_full_no_intraday_nowarmup_cap40": poly.LEAD_PORTFOLIOS["A_polygon62_no_intraday_cap40"],
    "B_pit_full_no_intraday_nowarmup_cap40": poly.LEAD_PORTFOLIOS["B_polygon62_no_intraday_cap40"],
}


def configure_poly() -> None:
    poly.START = START
    poly.END = END
    poly.DAILY_FEATURES = DAILY_FEATURES
    poly.INTRADAY_0935 = INTRADAY_0935
    poly.BROAD_TRADES = BROAD_TRADES
    poly.LOCAL_TRADES = LOCAL_TRADES
    poly.YDAY_TRADES = YDAY_TRADES


def build_yday_trades_from_daily(daily: pd.DataFrame) -> pd.DataFrame:
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


def infer_notional(pnl: pd.Series, ret: pd.Series) -> pd.Series:
    out = (pnl.astype(float) / ret.astype(float).replace(0.0, np.nan)).abs()
    med = float(out.replace([np.inf, -np.inf], np.nan).dropna().median()) if out.notna().any() else 0.0
    return out.replace([np.inf, -np.inf], np.nan).fillna(med)


def load_signals_no_intraday(daily_px: pd.DataFrame, intraday_px: pd.DataFrame) -> pd.DataFrame:
    exit20 = poly.nth_exit_dates(daily_px, 20)
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


def write_yearly_metrics(eq: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for portfolio, group_port in eq.groupby("portfolio", sort=True):
        for year, group in group_port.assign(year=group_port["date"].dt.year).groupby("year", sort=True):
            curve = group["daily_pnl"].cumsum()
            std = float(group["daily_pnl"].std())
            rows.append(
                {
                    "portfolio": portfolio,
                    "year": int(year),
                    "days": int(len(group)),
                    "pnl": float(group["daily_pnl"].sum()),
                    "ddSubset": float((curve - curve.cummax()).min()),
                    "sharpe": float(group["daily_pnl"].mean() / std * np.sqrt(252)) if std > 0 else np.nan,
                    "avgGross": float(group["gross"].mean()),
                    "maxGross": float(group["gross"].max()),
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(YEARLY_OUT, index=False)
    return out


def main() -> None:
    configure_poly()
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    intraday = pd.read_pickle(INTRADAY_0935)
    intraday["date"] = pd.to_datetime(intraday["date"])

    poly.build_broad_trades(daily)
    poly.build_local_trades(daily)
    build_yday_trades_from_daily(daily)

    daily_px = poly.load_daily_prices_from_polygon(daily)
    daily_px["date"] = pd.to_datetime(daily_px["date"])
    intraday_px = intraday[["date", "ticker", "open930", "entry935", "exit1555"]].copy()
    signals = load_signals_no_intraday(daily_px, intraday_px)

    gate = pit_gate.load_pit_gate()
    gated_signals, gate_qa, gate_daily, gate_reasons = pit_gate.apply_pit_gate(signals, gate)
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
        print("PIT_FULL_ENGINE", name, summary, flush=True)
    summary_df = pd.DataFrame(summaries)
    equity_df = pd.concat(equities, ignore_index=True)
    trades_df = pd.concat(trades, ignore_index=True)
    summary_df.to_csv(SUMMARY_OUT, index=False)
    equity_df.to_csv(EQUITY_OUT, index=False)
    trades_df.to_csv(TRADES_OUT, index=False)
    write_yearly_metrics(equity_df)
    print("WROTE", SUMMARY_OUT, EQUITY_OUT, TRADES_OUT, YEARLY_OUT, flush=True)


if __name__ == "__main__":
    main()
