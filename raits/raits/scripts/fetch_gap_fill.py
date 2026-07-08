"""
fetch_gap_fill.py
=================
Fetch missing 5-min bars for LOW, SBUX, and META (FB pre-2022).
Reads existing cache, finds gaps vs SPY reference, fetches only missing days.

META strategy:
  - 2022-06-09 onwards: fetch as "META"
  - pre 2022-06-09: fetch as "FB", save into cache under "META" key

Run from d:\\raits\\raits:
    python raits/scripts/fetch_gap_fill.py
"""
from __future__ import annotations
import glob
import hashlib
import os
import sys
import time
import warnings
warnings.filterwarnings("ignore")

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
import requests
from datetime import datetime, date as date_t

# ── API key ────────────────────────────────────────────────────────────────────
_api_key = None
for _p in [
    os.path.join(os.path.dirname(__file__), '..', 'config_private.py'),
    os.path.join(os.path.dirname(__file__), '..', '..', 'config_private.py'),
    os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config_private.py'),
]:
    _p = os.path.abspath(_p)
    if os.path.exists(_p):
        import importlib.util as _ilu
        _s = _ilu.spec_from_file_location("config_private", _p)
        _m = _ilu.module_from_spec(_s); _s.loader.exec_module(_m)
        _api_key = getattr(_m, 'POLYGON_API_KEY', None)
        print("[OK] Config:", _p)
        break

if not _api_key:
    print("[FAIL] config_private.py not found"); sys.exit(1)

# ── Paths ──────────────────────────────────────────────────────────────────────
CACHE_5MIN = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "data"))
META_RENAME_CUTOFF = pd.Timestamp("2022-06-09")  # FB -> META
INTERVAL = 5

# ── Cache key matches raits_data_cache.py ─────────────────────────────────────
def _cache_key(ticker: str, day: pd.Timestamp) -> str:
    start = datetime.combine(day.date(), datetime.min.time())
    end   = datetime.combine(day.date(), datetime.max.time())
    key_string = f"{ticker}_{start.isoformat()}_{end.isoformat()}_5min"
    key_hash   = hashlib.md5(key_string.encode()).hexdigest()
    return f"{ticker}_5min_{key_hash}.parquet"

def cache_path(ticker: str, day: pd.Timestamp) -> str:
    return os.path.join(CACHE_5MIN, _cache_key(ticker, day))

def already_cached(ticker: str, day: pd.Timestamp) -> bool:
    return os.path.exists(cache_path(ticker, day))

# ── Get SPY reference trading days ────────────────────────────────────────────
def spy_trading_days() -> list[pd.Timestamp]:
    files = sorted(glob.glob(os.path.join(CACHE_5MIN, "SPY_5min_*.parquet")))
    if not files:
        print("[FAIL] No SPY cache — run wfo_real_run.py first"); sys.exit(1)
    days = set()
    for f in files:
        df = pd.read_parquet(f, columns=["close"])
        days.update(df.index.normalize().unique().tolist())
    return sorted(days)

# ── Fetch one day from Polygon ─────────────────────────────────────────────────
def fetch_day(api_ticker: str, day: pd.Timestamp, retries: int = 3) -> pd.DataFrame | None:
    date_str = day.strftime("%Y-%m-%d")
    url = (f"https://api.polygon.io/v2/aggs/ticker/{api_ticker}/range/"
           f"{INTERVAL}/minute/{date_str}/{date_str}")
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": _api_key}
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            if data.get("status") != "OK" or not data.get("results"):
                return None
            df = pd.DataFrame(data["results"])
            df.rename(columns={"o":"open","h":"high","l":"low","c":"close","v":"volume","t":"timestamp"}, inplace=True)
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df["timestamp"] = df["timestamp"].dt.tz_convert("US/Eastern").dt.tz_localize(None)
            df = df.set_index("timestamp")[["open","high","low","close","volume"]]
            df = df.between_time("09:30", "16:00")
            return df if not df.empty else None
        except requests.exceptions.ConnectionError:
            if attempt < retries:
                print(f"      connection error, retry {attempt}/{retries}...")
                time.sleep(10)
            else:
                return None
        except Exception as e:
            print(f"      error: {e}")
            return None
    return None

# ── Save to cache (same format as raits_data_cache.py) ────────────────────────
def save_to_cache(cache_ticker: str, day: pd.Timestamp, df: pd.DataFrame) -> None:
    path = cache_path(cache_ticker, day)
    df.to_parquet(path, compression="snappy")

# ── Find missing days for a ticker ────────────────────────────────────────────
def missing_days(cache_ticker: str, all_days: list[pd.Timestamp]) -> list[pd.Timestamp]:
    return [d for d in all_days if not already_cached(cache_ticker, d)]

# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    print("\nLoading SPY reference trading days...")
    all_days = spy_trading_days()
    print(f"  {len(all_days)} trading days  {all_days[0].date()} to {all_days[-1].date()}")

    # Tickers: (cache_ticker, api_ticker_fn, label)
    # api_ticker_fn takes a pd.Timestamp and returns the ticker to query
    tasks = [
        ("LOW",  lambda d: "LOW",  "LOW (network gap 2022-03)"),
        ("SBUX", lambda d: "SBUX", "SBUX (network gap 2022-11)"),
        # META: use FB for pre-rename, META for post-rename
        ("META", lambda d: "META" if d >= META_RENAME_CUTOFF else "FB",
         "META/FB (ticker rename 2022-06-09)"),
    ]

    for cache_ticker, api_fn, label in tasks:
        gaps = missing_days(cache_ticker, all_days)
        print(f"\n{'='*60}")
        print(f"{label}")
        print(f"  Missing days: {len(gaps)}")
        if not gaps:
            print("  Nothing to fetch.")
            continue

        ok = skip = fail = 0
        for i, day in enumerate(gaps, 1):
            api_ticker = api_fn(day)
            df = fetch_day(api_ticker, day)
            if df is not None and not df.empty:
                save_to_cache(cache_ticker, day, df)
                ok += 1
                if i % 50 == 0 or i == len(gaps):
                    print(f"  [{i}/{len(gaps)}] fetched {ok} saved, {skip} empty, {fail} errors")
            else:
                skip += 1  # market holiday or genuine no-data day
            time.sleep(0.12)  # ~8 req/s — stay under rate limit

        print(f"  Done: {ok} saved, {skip} empty/holiday, {fail} errors")

    print("\nGap fill complete. Re-run wfo_real_run.py to rebuild the pickle.")

if __name__ == "__main__":
    main()