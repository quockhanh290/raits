"""
raits_premarket.py — Pre-market feature builder

Reads raw parquet cache (04:00–09:29 ET bars) for each ticker and builds a
MultiIndex DataFrame of pre-market summary features.

The cache key is deterministic: md5("{ticker}_{date}_{date}_5min"), so we can
compute the exact filename for each (ticker, date) pair without globbing all files.
This makes targeted reads (e.g. only Normal regime days) fast.

Usage:
    from raits.data.raits_premarket import build_premarket_df
    pm = build_premarket_df(data_5min, cache_dir=r'd:\\raits\\raits\\data\\cache',
                            dates=normal_days)
"""

import os
import hashlib
import pandas as pd
import pyarrow.parquet as pq



def _cache_path(ticker: str, date: pd.Timestamp, cache_dir: str) -> str:
    """Compute the exact parquet path for a (ticker, date) pair."""
    d = date.date()
    key = f"{ticker}_{d}_{d}_5min"
    key_hash = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(cache_dir, 'data', f'{ticker}_5min_{key_hash}.parquet')


def _pm_features(day_pm: pd.DataFrame) -> dict | None:
    """Compute pre-market summary stats from a single day's pm bars."""
    day_pm = day_pm.sort_index()
    if len(day_pm) < 2:
        return None
    pm_open  = float(day_pm['open'].iloc[0])
    pm_high  = float(day_pm['high'].max())
    pm_low   = float(day_pm['low'].min())
    pm_close = float(day_pm['close'].iloc[-1])
    pm_vol   = float(day_pm['volume'].sum())
    if pm_open <= 0:
        return None
    pm_return    = (pm_close - pm_open) / pm_open
    pm_direction = 1 if pm_return > 0 else (-1 if pm_return < 0 else 0)
    pm_range_pct = (pm_high - pm_low) / pm_open
    pm_fade      = pm_close < (pm_low + 0.5 * (pm_high - pm_low))
    return dict(
        pm_open=pm_open, pm_high=pm_high, pm_low=pm_low,
        pm_close=pm_close, pm_volume=pm_vol,
        pm_return=pm_return, pm_direction=pm_direction,
        pm_range_pct=pm_range_pct, pm_fade=pm_fade,
    )


def build_premarket_df(
    data_5min: dict,
    cache_dir: str,
    dates: list | None = None,
) -> pd.DataFrame:
    """
    Build pre-market feature DataFrame from raw parquet cache.

    Args:
        data_5min : dict  ticker -> DataFrame (regular-hours bars, used for ticker list)
        cache_dir : str   path to the raits data cache dir (contains data/ subdir)
        dates     : list of pd.Timestamp to load (e.g. normal_days).
                    If None, derives the date range from data_5min (slow — reads all files).

    Returns:
        DataFrame indexed by (ticker, date) with columns:
            pm_open, pm_high, pm_low, pm_close, pm_volume,
            pm_return, pm_direction, pm_range_pct, pm_fade
    """
    tickers = list(data_5min.keys())

    if dates is None:
        # Derive from PKL — use every date that appears in any ticker's index
        all_dates = sorted({
            d for tk in tickers
            for d in data_5min[tk].index.normalize().unique()
        })
    else:
        all_dates = sorted(pd.Timestamp(d) for d in dates)

    records = []
    for ticker in tickers:
        for date in all_dates:
            path = _cache_path(ticker, date, cache_dir)
            if not os.path.exists(path):
                continue
            try:
                df = pq.read_table(path).to_pandas()
                if not isinstance(df.index, pd.DatetimeIndex):
                    df.index = pd.to_datetime(df.index)
                pm = df.between_time('04:00', '09:29')
                if pm.empty:
                    continue
                feat = _pm_features(pm)
                if feat is None:
                    continue
                records.append({'ticker': ticker, 'date': date, **feat})
            except Exception:
                continue

    if not records:
        return pd.DataFrame()

    return (
        pd.DataFrame(records)
        .set_index(['ticker', 'date'])
        .sort_index()
    )
