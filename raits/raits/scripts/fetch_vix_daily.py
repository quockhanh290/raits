"""
fetch_vix_daily.py — Download VIX daily closes via yfinance

Fetches ^VIX (CBOE Volatility Index) daily closes 2018-01-01 → today and saves
to data/cache/daily/vix_daily.parquet for use by the engine VIX gate.

Note: Polygon does not support CBOE indices (I:VIX) on the current plan.
yfinance is used here as ^VIX is a public CBOE index, not tradeable market data.

Usage:
    cd d:\\raits\\raits
    py -3.11 raits\\scripts\\fetch_vix_daily.py
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import yfinance as yf

OUTPUT     = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "cache", "daily", "vix_daily.parquet"
))
START_DATE = "2017-01-01"

print(f"Fetching ^VIX {START_DATE} → today via yfinance ...")
raw = yf.download("^VIX", start=START_DATE, auto_adjust=True, progress=False)

close = raw["Close"]
if isinstance(close, pd.DataFrame):
    close = close.iloc[:, 0]

vix = close.rename("vix").dropna()
vix.index = pd.DatetimeIndex(vix.index).normalize()

print(f"Fetched {len(vix)} days  |  VIX range: {vix.min():.1f} – {vix.max():.1f}")
print(f"Latest: {vix.index[-1].date()}  VIX={vix.iloc[-1]:.2f}")

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
vix.to_frame().to_parquet(OUTPUT)
print(f"Saved → {OUTPUT}")
