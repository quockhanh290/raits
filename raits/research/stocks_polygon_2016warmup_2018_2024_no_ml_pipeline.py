from __future__ import annotations

from pathlib import Path

import pandas as pd

import stocks_polygon_2018_2024_no_ml_pipeline as poly


YEARLY_OUT = Path("STOCKS_POLYGON62_ONE_ENGINE_NO_ML_YEARLY_2016WARMUP_2018_2024.csv")
ORIGINAL_LOAD_DAILY_PRICES = poly.load_daily_prices_from_polygon


def load_daily_prices_scoring_window(daily: pd.DataFrame) -> pd.DataFrame:
    px = ORIGINAL_LOAD_DAILY_PRICES(daily)
    px["date"] = pd.to_datetime(px["date"])
    return px[(px["date"] >= poly.START) & (px["date"] <= poly.END)].copy()


def write_yearly_metrics(equity_path: Path) -> None:
    eq = pd.read_csv(equity_path, parse_dates=["date"])
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
                    "sharpe": float(group["daily_pnl"].mean() / group["daily_pnl"].std() * (252**0.5))
                    if group["daily_pnl"].std() > 0
                    else None,
                    "avgGross": float(group["gross"].mean()),
                    "maxGross": float(group["gross"].max()),
                }
            )
    pd.DataFrame(rows).to_csv(YEARLY_OUT, index=False)
    print("WROTE", YEARLY_OUT)


def main() -> None:
    poly.BARS = Path("raits/data/cache/window_debug_5min_POLYGON_2016WARMUP_2018_2024_62.pkl")
    poly.DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_POLYGON62_2016WARMUP_2018_2024.pkl")
    poly.INTRADAY_0935 = Path("raits/data/cache/stocks_intraday_0935_features_POLYGON62_2016WARMUP_2018_2024.pkl")
    poly.GAP_RVOL30 = Path("raits/data/cache/stocks_gap_rvol30_features_POLYGON62_2016WARMUP_2018_2024.pkl")

    poly.BROAD_TRADES = Path("STOCKS_POLYGON62_BROAD_ADV10_G2_DD85_TRADES_2016WARMUP_2018_2024.csv")
    poly.LOCAL_TRADES = Path("STOCKS_POLYGON62_LOCAL_XS_FULL_S10_TRADES_2016WARMUP_2018_2024.csv")
    poly.YDAY_TRADES = Path("STOCKS_POLYGON62_YDAY_EX6_ACTUAL_TRADES_2016WARMUP_2018_2024.csv")
    poly.INTRADAY_TRADES = Path("STOCKS_POLYGON62_INTRADAY_FOCUSED_TRADES_2016WARMUP_2018_2024.csv")

    poly.SUMMARY_OUT = Path("STOCKS_POLYGON62_ONE_ENGINE_NO_ML_SUMMARY_2016WARMUP_2018_2024.csv")
    poly.EQUITY_OUT = Path("STOCKS_POLYGON62_ONE_ENGINE_NO_ML_EQUITY_2016WARMUP_2018_2024.csv")
    poly.TRADES_OUT = Path("STOCKS_POLYGON62_ONE_ENGINE_NO_ML_TRADES_2016WARMUP_2018_2024.csv")
    poly.SPLIT_OUT = Path("STOCKS_POLYGON62_ONE_ENGINE_NO_ML_SPLITS_2016WARMUP_2018_2024.csv")

    poly.START = pd.Timestamp("2018-01-01")
    poly.END = pd.Timestamp("2024-12-31")
    poly.load_daily_prices_from_polygon = load_daily_prices_scoring_window
    poly.main()
    write_yearly_metrics(poly.EQUITY_OUT)


if __name__ == "__main__":
    main()
