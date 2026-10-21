from __future__ import annotations

from pathlib import Path
import pickle

import pandas as pd

import stocks_polygon_2016warmup_2018_2024_no_ml_pipeline as warmup_pipeline
import stocks_polygon_2018_2024_no_ml_pipeline as poly
import stocks_polygon62_local_hold_vol20_fair_sizing as fair


SUMMARY_OUT = Path("STOCKS_POLYGON62_LOCAL_HOLD_VOL20_FAIR_SIZING_SUMMARY_2016WARMUP_2018_2024.csv")
YEARLY_OUT = Path("STOCKS_POLYGON62_LOCAL_HOLD_VOL20_FAIR_SIZING_YEARLY_2016WARMUP_2018_2024.csv")


def configure_warmup_poly() -> None:
    warmup_pipeline.main.__globals__["poly"] = poly
    poly.BARS = Path("raits/data/cache/window_debug_5min_POLYGON_2016WARMUP_2018_2024_62.pkl")
    poly.DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_POLYGON62_2016WARMUP_2018_2024.pkl")
    poly.INTRADAY_0935 = Path("raits/data/cache/stocks_intraday_0935_features_POLYGON62_2016WARMUP_2018_2024.pkl")
    poly.GAP_RVOL30 = Path("raits/data/cache/stocks_gap_rvol30_features_POLYGON62_2016WARMUP_2018_2024.pkl")
    poly.BROAD_TRADES = Path("STOCKS_POLYGON62_BROAD_ADV10_G2_DD85_TRADES_2016WARMUP_2018_2024.csv")
    poly.LOCAL_TRADES = Path("STOCKS_POLYGON62_LOCAL_XS_FULL_S10_TRADES_2016WARMUP_2018_2024.csv")
    poly.YDAY_TRADES = Path("STOCKS_POLYGON62_YDAY_EX6_ACTUAL_TRADES_2016WARMUP_2018_2024.csv")
    poly.INTRADAY_TRADES = Path("STOCKS_POLYGON62_INTRADAY_FOCUSED_TRADES_2016WARMUP_2018_2024.csv")
    poly.START = pd.Timestamp("2018-01-01")
    poly.END = pd.Timestamp("2024-12-31")


def spy_regimes() -> pd.DataFrame:
    with poly.BARS.open("rb") as f:
        bars = pickle.load(f)
    spy = bars["SPY"].copy().reset_index()
    spy = spy.rename(columns={spy.columns[0]: "ts"})
    spy["ts"] = pd.to_datetime(spy["ts"])
    spy["date"] = spy["ts"].dt.normalize()
    open_px = spy[spy["ts"].dt.strftime("%H:%M").eq("09:30")][["date", "open"]].rename(columns={"open": "spy_open"})
    close_px = spy[spy["ts"].dt.strftime("%H:%M").eq("15:55")][["date", "close"]].rename(columns={"close": "spy_close"})
    daily = open_px.merge(close_px, on="date", how="inner").sort_values("date").reset_index(drop=True)
    daily["spy_ret"] = daily["spy_close"].pct_change()
    daily["spy_prev_vol20"] = daily["spy_ret"].rolling(20, min_periods=20).std().shift(1)
    daily["vol20_020"] = daily["spy_prev_vol20"] >= 0.020
    return daily[["date", "vol20_020"]].copy()


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = pd.read_pickle(poly.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily_px = poly.load_daily_prices_from_polygon(daily)
    daily_px["date"] = pd.to_datetime(daily_px["date"])
    daily_px = daily_px[(daily_px["date"] >= poly.START) & (daily_px["date"] <= poly.END)].copy()
    intraday = pd.read_pickle(poly.INTRADAY_0935)
    intraday["date"] = pd.to_datetime(intraday["date"])
    intraday = intraday[["date", "ticker", "open930", "entry935", "exit1555"]]
    signals = poly.load_signals(daily_px, intraday)
    signals = signals[signals["sleeve"].isin(poly.LEAD_PORTFOLIOS["B_polygon62_no_intraday_cap40"]["weights"])].copy()
    regimes = spy_regimes()
    signals = signals.merge(regimes, on="date", how="left")
    signals["vol20_020"] = signals["vol20_020"].fillna(False).astype(bool)
    return daily_px, signals


def main() -> None:
    configure_warmup_poly()
    daily_px, base_signals = load_inputs()
    portfolios = {
        "A": poly.LEAD_PORTFOLIOS["A_polygon62_no_intraday_cap40"],
        "B": poly.LEAD_PORTFOLIOS["B_polygon62_no_intraday_cap40"],
    }
    variants = {
        "base_hold20": (None, None),
        "hold5_engine_sizing": (5, 5),
        "hold5_fixed_hold20_sizing": (5, 20),
        "hold10_engine_sizing": (10, 10),
        "hold10_fixed_hold20_sizing": (10, 20),
    }
    summary_rows = []
    yearly_frames = []
    for variant, (exit_hold, sizing_hold) in variants.items():
        signals = fair.apply_variant(daily_px, base_signals, exit_hold, sizing_hold)
        for prefix, cfg in portfolios.items():
            name = f"{prefix}_polygon62_2016warmup_{variant}"
            summary, eq, _ = poly.simulate(name, cfg, signals, daily_px)
            summary_rows.append({"variant": variant, "exitHold": exit_hold or 20, "sizingHold": sizing_hold or 20, **summary})
            yearly_frames.append(fair.yearly_metrics(eq, variant))
            print(name, f"pnl={summary['pnl']:.2f}", f"dd={summary['dd']:.2f}", f"sharpe={summary['sharpe']:.3f}", flush=True)
    pd.DataFrame(summary_rows).to_csv(SUMMARY_OUT, index=False)
    pd.concat(yearly_frames, ignore_index=True).to_csv(YEARLY_OUT, index=False)
    print("WROTE", SUMMARY_OUT, YEARLY_OUT)


if __name__ == "__main__":
    main()
