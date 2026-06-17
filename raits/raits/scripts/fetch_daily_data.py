"""
scripts/fetch_daily_data.py
---------------------------
One-time download of daily OHLCV bars for the full scanner candidate pool.
Required for DailyUniverseScanner to run T-1 scans in backtest and production.

Daily bars are much lighter than 5-min bars:
  41 tickers x 8 years x 1 bar/day = ~82,000 bars total
  At 100 calls/min → ~7 minutes first run, <30 seconds subsequent runs.

Usage:
    cd d:\\raits\\raits
    python raits/scripts/fetch_daily_data.py

Output:
    data/cache/daily/<TICKER>_daily_<START>_<END>.parquet
"""

import sys
import os
import warnings
warnings.filterwarnings("ignore")

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

import pandas as pd
from datetime import datetime

# ── API key ────────────────────────────────────────────────────────────────────
_api_key = None
for _cfg_path in [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config_private.py'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config_private.py'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'config_private.py'),
    'config_private.py',
]:
    _cfg_path = os.path.abspath(_cfg_path)
    if os.path.exists(_cfg_path):
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location("config_private", _cfg_path)
        _mod  = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _api_key = getattr(_mod, 'POLYGON_API_KEY', None)
        print(f"[OK] Config: {_cfg_path}")
        break

if not _api_key:
    print("[FAIL] config_private.py not found.")
    sys.exit(1)

from raits.data.raits_polygon_fetcher import PolygonDataFetcher
from raits.strategies.universe_scanner import CANDIDATE_POOL

# ── Parameters ────────────────────────────────────────────────────────────────
DATASET_START = "2017-01-03"
DATASET_END   = "2024-12-31"
TICKERS       = ["SPY"] + CANDIDATE_POOL

CACHE_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "..", "data", "cache", "daily")
os.makedirs(CACHE_DIR, exist_ok=True)


def load_from_cache(ticker: str) -> pd.DataFrame:
    """Load all parquet files for this ticker from daily cache."""
    import glob
    files = glob.glob(os.path.join(CACHE_DIR, f"{ticker}_daily_*.parquet"))
    if not files:
        return pd.DataFrame()
    frames = [pd.read_parquet(f) for f in files]
    df = pd.concat(frames)
    df.index = pd.DatetimeIndex(df.index)
    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df


def save_to_cache(ticker: str, df: pd.DataFrame) -> None:
    fname = f"{ticker}_daily_{DATASET_START}_{DATASET_END}.parquet"
    fpath = os.path.join(CACHE_DIR, fname)
    df.to_parquet(fpath)


def fetch_all_daily(tickers: list) -> dict:
    fetcher = PolygonDataFetcher(
        api_key=_api_key,
        use_cache=False,          # we manage our own daily cache
        cache_dir=None,
        rate_limit_calls_per_minute=100,
    )

    start_dt = datetime.strptime(DATASET_START, "%Y-%m-%d")
    end_dt   = datetime.strptime(DATASET_END,   "%Y-%m-%d")

    print(f"\n{'='*55}")
    print(f"Fetching daily bars: {DATASET_START} → {DATASET_END}")
    print(f"Tickers: {len(tickers)}")
    print(f"Cache:   {CACHE_DIR}")
    print(f"{'='*55}\n")

    daily_data = {}
    ok = fail = cached = 0

    for ticker in tickers:
        # Fast path: already cached
        cached_df = load_from_cache(ticker)
        if not cached_df.empty:
            days = len(cached_df)
            print(f"  {ticker:<6} [CACHE] {days} days")
            daily_data[ticker] = cached_df
            cached += 1
            continue

        # Fetch from Polygon
        print(f"  {ticker:<6} fetching...", end=" ", flush=True)
        try:
            hist = fetcher.fetch_daily_bars(
                ticker=ticker,
                start_date=start_dt,
                end_date=end_dt,
                use_cache=False,
            )
            df = hist.to_dataframe().reset_index()
            df.rename(columns={"timestamp": "date"}, inplace=True)
            df.set_index("date", inplace=True)
            df.index = pd.DatetimeIndex(df.index)
            df.columns = [c.lower() for c in df.columns]
            df = df.sort_index()
            df = df[~df.index.duplicated(keep="first")]

            if df.empty:
                print("EMPTY")
                fail += 1
                continue

            save_to_cache(ticker, df)
            daily_data[ticker] = df
            print(f"[OK] {len(df)} days")
            ok += 1

        except Exception as e:
            print(f"[FAIL] {e}")
            fail += 1

    print(f"\n{'='*55}")
    print(f"Done: {ok} fetched, {cached} cached, {fail} failed")
    print(f"Total loaded: {len(daily_data)} tickers")
    print(f"{'='*55}\n")
    return daily_data


if __name__ == "__main__":
    daily_data = fetch_all_daily(TICKERS)

    # Quick sanity check
    spy_days = len(daily_data.get("SPY", pd.DataFrame()))
    stocks_ok = sum(1 for t in CANDIDATE_POOL if t in daily_data and not daily_data[t].empty)
    print(f"SPY: {spy_days} days")
    print(f"Pool coverage: {stocks_ok}/{len(CANDIDATE_POOL)} stocks")

    if spy_days < 252 * 3:
        print("[WARN] Less than 3 years of SPY data — check API key or date range")
    else:
        print("[OK] Daily data ready for DailyUniverseScanner")
