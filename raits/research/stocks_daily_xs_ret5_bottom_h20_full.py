from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


OUT = Path("STOCKS_DAILY_XS_RET5_BOTTOM_H20_FULL_TRADES_REGEN_2026-09-09.csv")
ORIGINAL = Path("STOCKS_DAILY_XS_RET5_BOTTOM_H20_FULL_TRADES_2026-09-08.csv")
CAPITAL_PER_SLOT = 200.0
COST = 0.0004
HOLD = 20
SLOTS = 10


def build() -> pd.DataFrame:
    daily = pd.read_pickle("raits/data/cache/stocks_clean_daily_features_CAUSEQA_2026-09-10.pkl")
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values(["ticker", "date"]).copy()
    g = daily.groupby("ticker", sort=False)
    prev_close = g["close_1555"].shift(1)
    daily["ret5_pre_clean"] = prev_close / g["close_1555"].shift(6) - 1.0
    daily["exit_close"] = g["close_1555"].shift(-(HOLD - 1))
    daily["ret"] = daily["exit_close"] / daily["open_0930"] - 1.0
    data = daily.dropna(subset=["ret5_pre_clean", "ret", "open_0930", "exit_close"]).copy()
    data = data[(data["date"] >= pd.Timestamp("2020-01-01")) & (data["date"] <= pd.Timestamp("2024-12-31"))].copy()
    data = data[(data["open_0930"] > 0.0) & (data["exit_close"] > 0.0)]
    data = data.sort_values(["date", "ret5_pre_clean", "ticker"]).copy()
    data["rank"] = data.groupby("date")["ret5_pre_clean"].rank(method="first", ascending=True)
    picks = data[data["rank"] <= SLOTS].copy()
    picks["pnl"] = CAPITAL_PER_SLOT * (picks["ret"] - COST)
    return picks[["date", "ticker", "ret5_pre_clean", "rank", "ret", "pnl"]].reset_index(drop=True)


def main() -> None:
    out = build()
    out.to_csv(OUT, index=False)
    print("WROTE", OUT, "rows", len(out))
    if ORIGINAL.exists():
        orig = pd.read_csv(ORIGINAL, parse_dates=["date"])
        reg = pd.read_csv(OUT, parse_dates=["date"])
        print("original rows", len(orig), "regen rows", len(reg))
        print("same columns", list(orig.columns) == list(reg.columns))
        key = ["date", "ticker"]
        orig = orig.sort_values(key).reset_index(drop=True)
        reg = reg.sort_values(key).reset_index(drop=True)
        print("same keys", orig[key].astype(str).equals(reg[key].astype(str)))
        for col in ["ret5_pre_clean", "rank", "ret", "pnl"]:
            diff = float((orig[col].astype(float) - reg[col].astype(float)).abs().max())
            print(col, "max_abs_diff", diff)


if __name__ == "__main__":
    main()
