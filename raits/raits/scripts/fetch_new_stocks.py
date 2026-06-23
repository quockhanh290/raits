"""
scripts/fetch_new_stocks.py
---------------------------
Download 5-min bars for the 29 new stocks identified by scanner_audit.py.
These stocks were never in the original 8-stock universe but are selected
by DailyUniverseScanner ≥52 times in the 2019-2022 audit period.

Date range: 2019-01-02 → 2022-12-30
  - 2019 provides 252-day warmup for the 2020 OOS test window
  - No need to go back to 2017 for 5-min (daily bars cover SMA200 warmup)
  - 2023+ data can be added later if extending OOS windows

Phase 1 (≥248 days selected) — download now:
  INTU COST VRTX AMAT REGN AVGO ADBE MS SBUX TXN
  XOM AMGN ORCL EBAY QCOM CVX CSCO GS CRM JPM

Phase 2 (run if Phase 1 results are good):
  MU HON MA NFLX INTC V GILD BIIB MMM

Usage:
    cd d:\\raits\\raits
    python raits/scripts/fetch_new_stocks.py          # Phase 1 (default)
    python raits/scripts/fetch_new_stocks.py --phase2 # Phase 2
    python raits/scripts/fetch_new_stocks.py --all    # Both phases

Estimated runtime:
    Phase 1: ~20 stocks × 1,008 days × 0.6s/call ≈ 3–4 hours
    Phase 2: ~9 stocks  × 1,008 days × 0.6s/call ≈ 1.5 hours
"""

import sys
import os
import argparse
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

import pandas as pd

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

# ── Parameters ─────────────────────────────────────────────────────────────────
DATE_START    = "2017-01-03"   # matches original 8-stock universe start
DATE_END      = "2024-12-31"   # covers all OOS windows including 2023-2024

CACHE_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "..", "data", "cache")
CACHE_DATA    = os.path.join(CACHE_DIR, "data")

INTERVAL_MINS = 5

# Phase 1: ≥248 scanner-audit days (20 stocks)
PHASE1 = [
    "INTU",   # 425 days
    "COST",   # 420 days
    "VRTX",   # 401 days
    "AMAT",   # 391 days
    "REGN",   # 363 days
    "AVGO",   # 360 days
    "ADBE",   # 353 days
    "MS",     # 327 days
    "SBUX",   # 314 days
    "TXN",    # 310 days
    "XOM",    # 301 days
    "AMGN",   # 288 days
    "ORCL",   # 285 days
    "EBAY",   # 282 days
    "QCOM",   # 268 days
    "CVX",    # 265 days
    "CSCO",   # 264 days
    "GS",     # 261 days
    "CRM",    # 249 days
    "JPM",    # 248 days
]

# Phase 2: 9 stocks with lower selection frequency
PHASE2 = [
    "MU",     # 227 days
    "HON",    # 226 days
    "MA",     # 218 days
    "NFLX",   # 213 days
    "INTC",   # 189 days
    "V",      # 180 days
    "GILD",   # 139 days
    "BIIB",   # 120 days
    "MMM",    #  52 days
]

ALREADY_CACHED = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AMD"]

# Sector ETFs for VWAP_MR universe expansion
ETF_PHASE = [
    "XLF",   # Financial Select Sector SPDR
    "XLE",   # Energy Select Sector SPDR
    "XLV",   # Health Care Select Sector SPDR
    "XLU",   # Utilities Select Sector SPDR
    "XLI",   # Industrial Select Sector SPDR
]

# Additional ETFs for expanded VWAP_MR universe
ETF_PHASE2 = [
    "XLK",   # Technology Select Sector SPDR
    "XLP",   # Consumer Staples Select Sector SPDR
    "XLB",   # Materials Select Sector SPDR
    "XLY",   # Consumer Discretionary Select Sector SPDR
    "GLD",   # SPDR Gold Shares
]

# PE_SHORT expansion universe — 25 stocks not yet in 5-min cache
PE_EXPANSION = [
    # Pharma (frequent >5% earnings reactions)
    "PFE", "MRK", "LLY", "ABBV", "JNJ", "BMY",
    # Financials
    "BAC", "WFC", "C",
    # Consumer / Retail
    "WMT", "TGT", "HD", "LOW", "MCD", "NKE",
    # Consumer Staples
    "PG", "KO", "PEP",
    # Industrials
    "CAT", "DE", "BA", "GE",
    # Tech / Fintech
    "PYPL", "PANW", "NOW",
]


def get_cached_dates(ticker: str) -> set:
    """
    Return set of date strings (YYYY-MM-DD) already in the 5-min cache
    for this ticker within the download date range.
    Reads all parquet files once so we can skip already-fetched days.
    """
    import glob
    files = glob.glob(os.path.join(CACHE_DATA, f"{ticker}_5min_*.parquet"))
    if not files:
        return set()

    start_ts = pd.Timestamp(DATE_START)
    end_ts   = pd.Timestamp(DATE_END) + pd.Timedelta("1D")
    dates: set = set()

    for f in files:
        try:
            df = pd.read_parquet(f)
            if df.empty:
                continue
            idx = pd.DatetimeIndex(df.index)
            in_range = idx[(idx >= start_ts) & (idx < end_ts)]
            for d in in_range.normalize().unique():
                dates.add(d.strftime("%Y-%m-%d"))
        except Exception:
            pass

    return dates


def fetch_ticker(fetcher: PolygonDataFetcher, ticker: str, trading_days: pd.DatetimeIndex) -> int:
    """
    Fetch 5-min bars for each day in trading_days, skipping any day
    that is already in the local cache. Resumes exactly where it left off
    if the previous run was interrupted.

    Returns number of newly fetched days.
    """
    # Build set of already-cached dates in one pass — O(N) disk reads upfront.
    cached_dates = get_cached_dates(ticker)
    missing_days = [d for d in trading_days
                    if d.strftime("%Y-%m-%d") not in cached_dates]

    if not missing_days:
        return 0  # fully cached — caller will print the skip message

    print(f"    {ticker}: {len(cached_dates)} cached, "
          f"{len(missing_days)} to fetch", flush=True)

    ok = skip = err = 0

    for i, day in enumerate(missing_days):
        if (i + 1) % 50 == 0:
            pct = (i + 1) / len(missing_days) * 100
            print(f"    {ticker}: {i+1}/{len(missing_days)} new days ({pct:.0f}%)",
                  flush=True)

        try:
            hist = fetcher.fetch_intraday_bars(
                ticker=ticker,
                date=day.to_pydatetime(),
                interval_minutes=INTERVAL_MINS,
                use_cache=True,
            )
            df = hist.to_dataframe()
            if df is not None and not df.empty:
                ok += 1
            else:
                skip += 1  # holiday or early close with no data
        except Exception as e:
            msg = str(e).lower()
            if "no intraday data" in msg or "no data" in msg:
                skip += 1  # market holiday — bdate_range doesn't know about these
            else:
                err += 1
                if err <= 5:
                    print(f"    [ERR] {ticker} {day.date()}: {e}", flush=True)

    return ok


def run_fetch(tickers: list) -> None:
    start_dt    = datetime.strptime(DATE_START, "%Y-%m-%d")
    end_dt      = datetime.strptime(DATE_END,   "%Y-%m-%d")
    trading_days = pd.bdate_range(start=start_dt, end=end_dt)
    total_days   = len(trading_days)

    print(f"\n{'='*60}")
    print(f"5-min data download: {DATE_START} → {DATE_END}")
    print(f"Trading days per ticker: {total_days}")
    print(f"Tickers: {len(tickers)}")
    print(f"Estimated API calls: {len(tickers) * total_days:,}")
    print(f"Estimated time at 100 calls/min: "
          f"~{len(tickers) * total_days / 100 / 60:.1f} hours")
    print(f"{'='*60}\n")

    fetcher = PolygonDataFetcher(
        api_key=_api_key,
        use_cache=True,
        cache_dir=CACHE_DIR,
        rate_limit_calls_per_minute=100,
    )

    import time
    session_start = time.time()
    done = 0

    for ticker in tickers:
        if ticker in ALREADY_CACHED:
            print(f"  {ticker:<6} [SKIP] already in original universe")
            continue

        ticker_start = time.time()
        days_fetched = fetch_ticker(fetcher, ticker, trading_days)

        if days_fetched == 0:
            print(f"  {ticker:<6} [DONE] fully cached — skip")
            continue
        elapsed = time.time() - ticker_start

        done += 1
        total_elapsed = time.time() - session_start
        remaining = len(tickers) - done
        eta_mins  = (total_elapsed / done * remaining) / 60 if done > 0 else 0

        print(f"  {ticker:<6} [OK] {days_fetched} days  ({elapsed/60:.1f} min)  "
              f"— {done}/{len(tickers)} done, ETA {eta_mins:.0f} min", flush=True)

    total_time = (time.time() - session_start) / 60
    print(f"\n{'='*60}")
    print(f"Download complete in {total_time:.1f} minutes")
    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download 5-min bars for new scanner stocks")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--phase2",   action="store_true", help="Download Phase 2 only (9 low-freq stocks)")
    grp.add_argument("--all",      action="store_true", help="Download all 29 stocks (Phase 1 + Phase 2)")
    grp.add_argument("--etf",      action="store_true", help="Download sector ETFs for VWAP_MR (XLF, XLE, XLV, XLU, XLI)")
    grp.add_argument("--etf2",     action="store_true", help="Download expanded ETFs (XLK, XLP, XLB, XLY, GLD)")
    grp.add_argument("--pe",       action="store_true", help="Download PE_SHORT expansion (25 stocks, 2019-2022)")
    args = parser.parse_args()

    if args.pe:
        # Narrow date range — only need 2019+ for ATR warmup + 2020-2022 backtest
        global DATE_START, DATE_END
        DATE_START = "2019-01-02"
        DATE_END   = "2022-12-30"
        tickers = PE_EXPANSION
        print(f"Mode: PE_SHORT expansion (25 stocks, {DATE_START} → {DATE_END})")
        run_fetch(tickers)
        return

    if args.all:
        tickers = PHASE1 + PHASE2
        print("Mode: ALL (Phase 1 + Phase 2, 29 stocks)")
    elif args.phase2:
        tickers = PHASE2
        print("Mode: Phase 2 only (9 low-frequency stocks)")
    elif args.etf:
        tickers = ETF_PHASE
        print("Mode: Sector ETFs for VWAP_MR (XLF, XLE, XLV, XLU, XLI)")
    elif args.etf2:
        tickers = ETF_PHASE2
        print("Mode: Expanded ETFs for VWAP_MR (XLK, XLP, XLB, XLY, GLD)")
    else:
        tickers = PHASE1
        print("Mode: Phase 1 (20 high-frequency stocks, ≥248 days selected)")
        print(f"Skipping Phase 2: {PHASE2}")

    run_fetch(tickers)

    if not args.phase2 and not args.all:
        print("\nPhase 2 stocks (run with --phase2 when ready):")
        for t in PHASE2:
            freq_map = {"MU":227,"HON":226,"MA":218,"NFLX":213,
                        "INTC":189,"V":180,"GILD":139,"BIIB":120,"MMM":52}
            print(f"  {t:<6} ({freq_map.get(t, '?')} days selected)")


if __name__ == "__main__":
    main()
