from __future__ import annotations

from pathlib import Path

import pandas as pd

import stocks_databento_daily_xs_mtm as broad


TRADES_OUT = Path("STOCKS_DATABENTO_DAILY_XS_MTM_DD_OVERLAY_BEST_TRADES_REGEN_2026-09-09.csv")
EQUITY_OUT = Path("STOCKS_DATABENTO_DAILY_XS_MTM_DD_OVERLAY_BEST_EQUITY_REGEN_2026-09-09.csv")
ORIGINAL_TRADES = Path("STOCKS_DATABENTO_DAILY_XS_MTM_DD_OVERLAY_BEST_TRADES_2026-09-08.csv")
ORIGINAL_EQUITY = Path("STOCKS_DATABENTO_DAILY_XS_MTM_DD_OVERLAY_BEST_EQUITY_2026-09-08.csv")


def config() -> broad.Config:
    return broad.Config(
        adv=10_000_000.0,
        slots=20,
        hold=20,
        gross_cap=2.0,
        layer_gross=0.1,
        min_ret5=-0.5,
        max_ticker_gross=0.10,
        active_ticker_cap=3,
        overlay="dd",
        dd_trigger=0.08,
        throttle_mult=0.85,
    )


def main() -> None:
    panel = broad.load_panel()
    summary, trades, equity = broad.simulate(panel, config())
    trades.to_csv(TRADES_OUT, index=False)
    equity.to_csv(EQUITY_OUT, index=False)
    print("summary", summary)
    print("WROTE", TRADES_OUT, EQUITY_OUT)

    if ORIGINAL_TRADES.exists():
        orig = pd.read_csv(ORIGINAL_TRADES, parse_dates=["entry_date", "planned_exit_date"])
        reg = pd.read_csv(TRADES_OUT, parse_dates=["entry_date", "planned_exit_date"])
        print("trades rows", len(orig), len(reg), "same columns", list(orig.columns) == list(reg.columns))
        key = ["entry_date", "symbol", "planned_exit_date", "ret5"]
        orig = orig.sort_values(key).reset_index(drop=True)
        reg = reg.sort_values(key).reset_index(drop=True)
        print("trades same keys", orig[["entry_date", "symbol", "planned_exit_date"]].astype(str).equals(reg[["entry_date", "symbol", "planned_exit_date"]].astype(str)))
        for col in ["entry_price", "shares", "entry_notional", "entry_cost", "ret5", "adv20"]:
            diff = float((orig[col].astype(float) - reg[col].astype(float)).abs().max())
            print("trades", col, "max_abs_diff", diff)

    if ORIGINAL_EQUITY.exists():
        orig_eq = pd.read_csv(ORIGINAL_EQUITY, parse_dates=["date"])
        reg_eq = pd.read_csv(EQUITY_OUT, parse_dates=["date"])
        print("equity rows", len(orig_eq), len(reg_eq), "same columns", list(orig_eq.columns) == list(reg_eq.columns))
        orig_eq = orig_eq.sort_values("date").reset_index(drop=True)
        reg_eq = reg_eq.sort_values("date").reset_index(drop=True)
        for col in ["equity", "daily_pnl", "gross", "active_positions"]:
            diff = float((orig_eq[col].astype(float) - reg_eq[col].astype(float)).abs().max())
            print("equity", col, "max_abs_diff", diff)


if __name__ == "__main__":
    main()
