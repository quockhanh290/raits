"""
fetch_lowbeta_5min.py — Fetch 5-min data cho low-beta universe.

Low-beta tickers: Consumer Staples, Utilities, Healthcare stable, Large-cap Financials.
These are mean-reversion friendly stocks vs the high-beta tech universe we already have.

Saves Parquet to data/cache/data/ — same format window_debug reads.

Usage:
    cd D:\raits\raits
    python raits\scripts\fetch_lowbeta_5min.py
"""
import sys, os, time, requests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd

# ── API key ──────────────────────────────────────────────────────────
_api_key = None
for _p in [
    os.path.join(os.path.dirname(__file__), '..', 'config_private.py'),
    os.path.join(os.path.dirname(__file__), '..', '..', 'config_private.py'),
    os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config_private.py'),
    os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'config_private.py'),
    'config_private.py',
]:
    _p = os.path.abspath(_p)
    if os.path.exists(_p):
        import importlib.util as _ilu
        _s = _ilu.spec_from_file_location("cfg", _p)
        _m = _ilu.module_from_spec(_s); _s.loader.exec_module(_m)
        _api_key = getattr(_m, 'POLYGON_API_KEY', None)
        print(f"[OK] API key from {_p}")
        break

if not _api_key:
    print("[FAIL] config_private.py not found"); sys.exit(1)

# ── Low-beta universe ─────────────────────────────────────────────────
LOW_BETA = [
    # Consumer Staples (beta ~0.3-0.6)
    "PG", "KO", "PEP", "WMT", "MO", "CL", "KMB", "GIS", "MDLZ",
    # Utilities (beta ~0.2-0.4)
    "NEE", "DUK", "SO", "D", "AEP",
    # Healthcare stable (beta ~0.4-0.7)
    "JNJ", "ABT", "MRK", "PFE", "BMY",
    # Large-cap Financials stable
    "BRK.B", "WFC", "USB",
]

CACHE_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'cache', 'data'))
os.makedirs(CACHE_DIR, exist_ok=True)

YEARS = [("2020-01-01", "2020-12-31"),
         ("2021-01-01", "2021-12-31"),
         ("2022-01-01", "2022-12-31")]

BASE_URL = "https://api.polygon.io"
MIN_INTERVAL_SECS = 60 / 100   # 100 calls/min

def fetch_5min_range(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Fetch 5-min bars for ticker over a date range. Handles Polygon pagination."""
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/5/minute/{start}/{end}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": _api_key}
    all_bars = []
    while url:
        time.sleep(MIN_INTERVAL_SECS)
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        d = r.json()
        if d.get("status") not in ("OK", "DELAYED"):
            raise ValueError(f"API status={d.get('status')}: {d.get('error','')}")
        bars = d.get("results", [])
        all_bars.extend(bars)
        next_url = d.get("next_url")
        url = next_url
        params = {"apiKey": _api_key} if next_url else {}
    if not all_bars:
        return pd.DataFrame()
    df = pd.DataFrame(all_bars)
    # Convert UTC ms → ET naive datetime
    import pytz
    et = pytz.timezone("US/Eastern")
    df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert(et).dt.tz_localize(None)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].set_index("timestamp")
    df = df.sort_index().between_time("09:30", "16:00")
    return df

print(f"\nFetching 5-min data for {len(LOW_BETA)} low-beta tickers, 2020-2022")
print(f"Cache dir: {CACHE_DIR}\n")

ok = skip = fail = 0
for ticker in LOW_BETA:
    frames = []
    ticker_fail = False
    for (start, end) in YEARS:
        fname = os.path.join(CACHE_DIR, f"{ticker}_5min_{start}_{end}.parquet")
        if os.path.exists(fname):
            print(f"  {ticker} {start[:4]} [cached]")
            frames.append(pd.read_parquet(fname))
            skip += 1
            continue
        print(f"  {ticker} {start[:4]} fetching...", end=" ", flush=True)
        try:
            df = fetch_5min_range(ticker, start, end)
            if df.empty:
                print("EMPTY"); ticker_fail = True; continue
            df.to_parquet(fname)
            frames.append(df)
            print(f"[OK] {len(df):,} bars")
            ok += 1
        except Exception as e:
            print(f"[FAIL] {e}"); ticker_fail = True; fail += 1

    if frames and not ticker_fail:
        total = sum(len(f) for f in frames)
        print(f"  {ticker}: total {total:,} bars across 3 years")

print(f"\nDone: {ok} fetched, {skip} cached, {fail} failed")
print(f"\nNext: run orb_retest_sim.py with --lowbeta flag")
