"""
scripts/fetch_spy_historical.py
--------------------------------
Download SPY daily bars from 2007-01-01 to 2024-12-31 via yfinance.
Polygon API tier only provides data from mid-2016; yfinance has full history
back to SPY inception (1993) at no cost.

Used to give the HMM 2008 GFC + 2020 COVID examples for proper Crisis state
calibration during initial fit.  This only needs to be run once.

Output:
    data/cache/daily/SPY_daily_2007_2024.parquet   (columns: open,high,low,close,volume)

Usage:
    cd d:\\raits\\raits
    python raits/scripts/fetch_spy_historical.py
"""

import sys
import os
import warnings
warnings.filterwarnings("ignore")

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

import pandas as pd

HIST_START = "2007-01-01"
HIST_END   = "2024-12-31"
CACHE_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "..", "data", "cache", "daily")
CACHE_FILE = os.path.join(CACHE_DIR, "SPY_daily_2007_2024.parquet")

os.makedirs(CACHE_DIR, exist_ok=True)


def fetch_spy_historical() -> pd.Series:
    if os.path.exists(CACHE_FILE):
        df = pd.read_parquet(CACHE_FILE)
        # Validate that file actually covers 2008 GFC
        first_date = df.index[0]
        if hasattr(first_date, 'year') and first_date.year <= 2008:
            print(f"[CACHE] {CACHE_FILE}")
            print(f"  {len(df)} trading days ({df.index[0].date()} → {df.index[-1].date()})")
            return df["close"]
        else:
            print(f"[STALE] Cache starts {first_date.date()} — missing 2008 GFC, re-fetching.")
            os.remove(CACHE_FILE)

    try:
        import yfinance as yf
    except ImportError:
        print("[FAIL] yfinance not installed. Run: pip install yfinance")
        sys.exit(1)

    print(f"Fetching SPY daily via yfinance: {HIST_START} → {HIST_END}")
    raw = yf.download("SPY", start=HIST_START, end=HIST_END, auto_adjust=True, progress=False)

    if raw.empty:
        print("[FAIL] yfinance returned no data")
        sys.exit(1)

    # Flatten MultiIndex columns if present (yfinance ≥0.2 returns MultiIndex for single ticker)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["open", "high", "low", "close", "volume"]
    df.index = pd.DatetimeIndex(df.index)
    df.index.name = "date"
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]

    df.to_parquet(CACHE_FILE)
    print(f"[OK] {len(df)} trading days saved → {CACHE_FILE}")
    print(f"     {df.index[0].date()} → {df.index[-1].date()}")
    return df["close"]


if __name__ == "__main__":
    spy_close = fetch_spy_historical()

    print(f"\nSanity check:")
    print(f"  Total days : {len(spy_close)}")
    print(f"  2008 GFC   : {len(spy_close['2008-09':'2009-03'])} days (expect ~130)")
    print(f"  2020 COVID : {len(spy_close['2020-02':'2020-04'])} days (expect ~60)")
    print(f"  Min close  : {spy_close.min():.2f}  Max close: {spy_close.max():.2f}")
