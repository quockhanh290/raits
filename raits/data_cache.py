"""
raits/data_cache.py
--------------------
Shared market data cache. Reads 5-min parquet files once, saves to a single
pkl, and returns the same dict every subsequent run.

Usage (any script):
    from raits.data_cache import load_market_data

    market = load_market_data()          # uses pkl if exists
    market = load_market_data(rebuild=True)  # force re-read parquets
    spy = market["SPY"]
"""

import os
import glob
import pickle
from typing import Dict, Optional

import pandas as pd

_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "cache")
_PARQUET_DIR = os.path.join(_CACHE_DIR, "data")
PKL_PATH     = os.path.join(_CACHE_DIR, "market_data_5min.pkl")

DATASET_START = "2017-01-03"
DATASET_END   = "2022-12-31"


def _load_ticker(ticker: str) -> pd.DataFrame:
    files = glob.glob(os.path.join(_PARQUET_DIR, f"{ticker}_5min_*.parquet"))
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        try:
            frames.append(pd.read_parquet(f))
        except Exception:
            pass
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames)
    df.index = pd.DatetimeIndex(df.index)
    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df = df[(df.index >= pd.Timestamp(DATASET_START)) &
            (df.index <= pd.Timestamp(DATASET_END))]
    df = df.between_time("09:30", "16:00")
    return df


def load_market_data(
    tickers: Optional[list] = None,
    rebuild: bool = False,
    verbose: bool = True,
) -> Dict[str, pd.DataFrame]:
    """
    Load 5-min market data for all tickers.

    Returns cached pkl if it exists (fast, ~1-2s).
    Falls back to reading parquets and saves pkl (slow first run, ~3-5 min).

    Args:
        tickers:  list of tickers to load. None = load whatever is in pkl / parquets.
        rebuild:  force re-read parquets even if pkl exists.
        verbose:  print progress.
    """
    if not rebuild and os.path.exists(PKL_PATH):
        if verbose:
            print(f"[data_cache] Loading from {PKL_PATH} ...", flush=True)
        with open(PKL_PATH, "rb") as f:
            market: Dict[str, pd.DataFrame] = pickle.load(f)
        if verbose:
            print(f"[data_cache] {len(market)} tickers loaded from pkl", flush=True)
        return market

    # Build from parquets
    if tickers is None:
        # Auto-discover all tickers in the parquet dir
        all_files = glob.glob(os.path.join(_PARQUET_DIR, "*_5min_*.parquet"))
        tickers = sorted({os.path.basename(f).split("_5min_")[0] for f in all_files})

    if verbose:
        print(f"[data_cache] Building pkl from parquets ({len(tickers)} tickers)...", flush=True)

    market = {}
    for i, ticker in enumerate(tickers):
        if verbose:
            print(f"  [{i+1}/{len(tickers)}] {ticker}...", end=" ", flush=True)
        df = _load_ticker(ticker)
        if not df.empty:
            market[ticker] = df
            if verbose:
                print(f"{len(df):,} bars", flush=True)
        else:
            if verbose:
                print("no data", flush=True)

    if verbose:
        print(f"\n[data_cache] Saving {len(market)} tickers to {PKL_PATH}...", flush=True)
    with open(PKL_PATH, "wb") as f:
        pickle.dump(market, f)
    if verbose:
        print("[data_cache] Done.", flush=True)

    return market
