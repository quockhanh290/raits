"""
scripts/wfo_real_run.py
------------------------
Real WFO run using Polygon.io 10-year historical data.

Pulls 10 years of 5-minute bars for SPY + universe via the existing
PolygonDataFetcher (with 24-hour Parquet cache to avoid re-downloading).
Converts to the DataFrame format WFOEngine.run() expects, then executes
the full 3-year/1-year rolling WFO per blueprint Section 7.2.

Estimated download time (first run, no cache):
    ~10 years × 252 days × 5 tickers × 1 API call/day = ~12,600 calls
    At 100 calls/min Developer rate limit ≈ 2-3 hours first run
    Subsequent runs: <5 minutes (all cached in Parquet)

Usage:
    cd C:\\Users\\quock\\RAITS\\raits
    python scripts/wfo_real_run.py

Outputs:
    configs/final_params.yaml   ← production params for Vault test
    configs/wfo_report.json     ← full WFO report (audit trail)
"""

import sys
import os
import logging
import warnings
from datetime import datetime
from typing import Dict

warnings.filterwarnings("ignore")

# Add project root to sys.path
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)


import pandas as pd

# -- Config / API key ----------------------------------------------------------
# Try multiple locations for config_private.py
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
        print(f"[OK] Config loaded from: {_cfg_path}")
        break

if not _api_key:
    print("[FAIL] FATAL: config_private.py not found or POLYGON_API_KEY missing.")
    print("  Searched in script dir, parent dir, and current dir.")
    sys.exit(1)

POLYGON_API_KEY = _api_key

from raits.data.raits_polygon_fetcher import PolygonDataFetcher
from raits.backtest.wfo import WFOEngine, WFOConfig

# -- Logging -------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("wfo_real_run")

# -- Parameters ----------------------------------------------------------------
# Blueprint Section 7.2: minimum 7 years, Developer plan gives 10
DATASET_START = "2017-01-03"   # earliest date Polygon Developer plan supports
DATASET_END   = "2022-12-31"   # 2023-2024 sealed as true OOS — never loaded

UNIVERSE      = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL"]
PHASE1        = [
    "INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
    "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
    "CSCO", "GS", "CRM", "JPM",
]
PHASE2        = ["MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM"]
CANDIDATE_POOL = UNIVERSE + PHASE1 + PHASE2   # full 37-stock ORB/TF pool
SECTOR_ETFS   = ["XLF", "XLE", "XLV", "XLU", "XLI", "XLK", "XLP", "XLB", "XLY", "GLD"]
MR_UNIVERSE   = ["XLF", "XLE", "XLV", "XLU", "XLI", "XLK", "XLP", "XLB", "XLY", "GLD", "QQQ", "IWM"]
ORB_UNIVERSE  = []
VWAP_UNIVERSE = MR_UNIVERSE
PE_EXPANSION  = [
    "PFE", "MRK", "LLY", "ABBV", "JNJ", "BMY",
    "BAC", "WFC", "C",
    "WMT", "TGT", "HD", "LOW", "MCD", "NKE",
    "PG", "KO", "PEP",
    "CAT", "DE", "BA", "GE",
    "PYPL", "PANW", "NOW",
]
TICKERS       = ["SPY", "QQQ", "IWM"] + SECTOR_ETFS + CANDIDATE_POOL + PE_EXPANSION

CACHE_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "cache")
INTERVAL_MINS = 5


def _load_ticker_from_cache(
    ticker: str,
    start: str,
    end: str,
    interval_minutes: int,
    cache_data_dir: str,
) -> pd.DataFrame:
    """
    Bulk-load all cached Parquet files for a ticker directly — no per-day fetcher loop.
    Reads all matching files in one pass and filters to the requested date range.
    ~100x faster than day-by-day fetcher calls for cached data.
    """
    import glob as _glob
    prefix = os.path.join(cache_data_dir, f"{ticker}_{interval_minutes}min_")
    files  = _glob.glob(prefix + "*.parquet")

    if not files:
        return pd.DataFrame()

    frames = []
    for fpath in files:
        try:
            df = pd.read_parquet(fpath)
            frames.append(df)
        except Exception:
            pass

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames)
    combined.index = pd.DatetimeIndex(combined.index)
    combined.columns = [c.lower() for c in combined.columns]
    combined = combined.sort_index()
    combined = combined[~combined.index.duplicated(keep="first")]

    # Filter to requested date range + market hours
    start_ts = pd.Timestamp(start)
    end_ts   = pd.Timestamp(end) + pd.Timedelta("1D")
    combined = combined[(combined.index >= start_ts) & (combined.index < end_ts)]
    combined = combined.between_time("09:30", "16:00")

    return combined


def fetch_market_data(
    tickers: list,
    start: str,
    end: str,
    interval_minutes: int = 5,
) -> Dict[str, pd.DataFrame]:
    """
    Load multi-year 5-minute bars for all tickers.

    Fast path: reads all cached Parquet files for each ticker in one bulk pass.
    Falls back to Polygon API (day-by-day) for any ticker with no cached data.

    Returns dict: ticker → DataFrame with DatetimeIndex, lowercase OHLCV columns.
    """
    cache_data_dir = os.path.join(CACHE_DIR, "data")

    print(f"\n{'='*60}")
    print(f"Loading {interval_minutes}-min data: {start} -> {end}")
    print(f"Tickers:   {tickers}")
    print(f"Cache dir: {cache_data_dir}")
    print(f"{'='*60}\n")

    market_data: Dict[str, pd.DataFrame] = {}

    for ticker in tickers:
        print(f"  {ticker} ...", end=" ", flush=True)

        # Fast path: bulk read from cache
        df = _load_ticker_from_cache(ticker, start, end, interval_minutes, cache_data_dir)

        if not df.empty:
            days_loaded = len(df.index.normalize().unique())
            print(f"[OK] {days_loaded} days, {len(df):,} bars (cache)")
            market_data[ticker] = df
            continue

        # Slow path: fetch from Polygon API day-by-day (first run / cache miss)
        print(f"cache empty — fetching from API...", end=" ", flush=True)
        fetcher = PolygonDataFetcher(
            api_key=POLYGON_API_KEY,
            use_cache=True,
            cache_dir=CACHE_DIR,
            rate_limit_calls_per_minute=100,
        )
        start_dt     = datetime.strptime(start, "%Y-%m-%d")
        end_dt       = datetime.strptime(end,   "%Y-%m-%d")
        trading_days = pd.bdate_range(start=start_dt, end=end_dt)
        frames       = []
        errors       = 0

        for day in trading_days:
            try:
                hist = fetcher.fetch_intraday_bars(
                    ticker=ticker,
                    date=day.to_pydatetime(),
                    interval_minutes=interval_minutes,
                    use_cache=True,
                )
                _df = hist.to_dataframe().reset_index()
                _df.rename(columns={"timestamp": "datetime"}, inplace=True)
                _df.set_index("datetime", inplace=True)
                _df.index = pd.DatetimeIndex(_df.index)
                _df.columns = [c.lower() for c in _df.columns]
                _df = _df.between_time("09:30", "16:00")
                if not _df.empty:
                    frames.append(_df)
            except Exception as e:
                errors += 1
                logger.debug(f"{ticker} {day.date()}: {e}")

        if frames:
            combined = pd.concat(frames).sort_index()
            combined = combined[~combined.index.duplicated(keep="first")]
            market_data[ticker] = combined
            days_loaded = len(combined.index.normalize().unique())
            print(f"[OK] {days_loaded} days, {len(combined):,} bars"
                  + (f" ({errors} errors)" if errors else ""))
        else:
            print(f"[FAIL] No data ({errors} errors)")

    return market_data


def validate_market_data(market_data: dict) -> bool:
    """Basic sanity checks before running WFO."""
    if "SPY" not in market_data or market_data["SPY"].empty:
        print("\n[FAIL] FATAL: SPY data missing")
        return False

    spy_days = len(market_data["SPY"].index.normalize().unique())
    print(f"\nData summary:")
    for ticker, df in market_data.items():
        days = len(df.index.normalize().unique())
        print(f"  {ticker}: {days} days, {len(df):,} bars")

    if spy_days < 252 * 3:   # Need at least 3 years for first train window
        print(f"\n[FAIL] FATAL: Need >={252*3} SPY days, got {spy_days}")
        return False

    stocks = sum(1 for t in UNIVERSE if t in market_data and not market_data[t].empty)
    if stocks == 0:
        print("\n[FAIL] FATAL: No stock data available")
        return False

    etfs = sum(1 for t in VWAP_UNIVERSE if t in market_data and not market_data[t].empty)
    print(f"\n[OK] Data validated: {spy_days} SPY days, {stocks}/{len(UNIVERSE)} stocks, {etfs}/{len(VWAP_UNIVERSE)} ETFs")
    return True


def run_real_wfo(market_data: dict, daily_data: dict, fixed_params: bool = False) -> None:
    """Execute the full WFO per blueprint Section 7.2."""
    cfg = WFOConfig(
        full_dataset_start=DATASET_START,
        full_dataset_end=DATASET_END,
        vault_fraction=0.0,           # 2023-2024 not loaded at all — sealed true OOS
        train_years=3,                # Blueprint: 3-year training windows
        test_years=1,                 # Blueprint: 1-year OOS test
        universe=CANDIDATE_POOL,
        orb_universe=ORB_UNIVERSE,
        vwap_universe=VWAP_UNIVERSE,
        account_equity=50_000.0,
        enable_costs=True,
        enable_pdt_guard=False,       # False — above $25k PDT threshold
        log_level="WARNING",
        aggregation_method="MEAN",    # Blueprint: arithmetic mean
        allow_swing_hold=True,        # TREND_FOLLOW carries overnight, Chandelier stop
        max_hold_days=5,              # force-close after 5 calendar days
        stress_size_fraction=0.5,     # half-size when HMM=Stress
        use_scanner=True,
        scanner_top_n=15,
        use_mr_scanner=True,
        mr_scanner_top_n=8,
        use_orb_scanner=True,
        orb_scanner_top_n=10,
        vwap_mr_vol_threshold=0.12,
        max_risk_pct=0.015,
        max_position_pct=0.40,
        kelly_fraction=0.75,
        pe_universe=PE_EXPANSION,
        cache_data_dir=os.path.join(CACHE_DIR, "data"),
        interval_mins=INTERVAL_MINS,
        fixed_orb_range=15 if fixed_params else None,
        fixed_bb_std=2.0  if fixed_params else None,
        fixed_ema_period=30 if fixed_params else None,
    )

    print(f"\n{'='*60}")
    print("REAL WFO RUN -- blueprint Section 7.2")
    print(f"  Train window:  {cfg.train_years} years")
    print(f"  Test window:   {cfg.test_years} year")
    if fixed_params:
        print(f"  Mode:          FIXED-PARAMS (skip grid search)")
        print(f"  Params:        ORB=15  BB=2.0  EMA=30")
    else:
        print(f"  Grid:          48 combinations per window")
    print(f"  Vault holdout: {cfg.vault_fraction:.0%} of data")
    if not fixed_params:
        print(f"  Note: Grid search runs without scanner (subprocess limitation).")
        print(f"        OOS tests run with full scanner + daily data.")
    print(f"{'='*60}\n")

    engine = WFOEngine(cfg)
    report = engine.run(market_data, daily_data=daily_data)

    print("\n" + report.summary())

    # Save outputs
    os.makedirs("configs", exist_ok=True)
    report.save("configs")

    # Final verdict
    print(f"\n{'='*60}")
    if report.proceed_to_vault:
        print("[OK] WFO PASSED \u2014 ready for cooling-off period (7 days)")
        print("  Production params saved to configs/final_params.yaml")
        print("  DO NOT modify any code during the cooling-off period.")
        print("  After 7 days: run pre-Vault checklist → execute Vault test.")
    else:
        m = report.stitched_metrics
        print("[FAIL] WFO DID NOT PASS TARGETS")
        print(f"  Calmar: {m.get('calmar_ratio',0):.2f} (need >2.0)")
        print(f"  Sharpe: {m.get('sharpe_ratio',0):.2f} (need >1.5)")
        print(f"  Max DD: {m.get('max_drawdown',0):.1%} (need <15%)")
        print()
        print("  DO NOT run the Vault test.")
        print("  Review strategy logic before proceeding.")
        print("  Common causes:")
        print("    - HMM regime detection needs re-tuning")
        print("    - Transaction costs too high for trade frequency")
        print("    - Strategy parameters too restrictive for this universe")
    print(f"{'='*60}")


if __name__ == "__main__":
    import argparse
    _parser = argparse.ArgumentParser()
    _parser.add_argument(
        "--fixed-params", action="store_true",
        help="Skip grid search, run OOS only with ORB=15 BB=2.0 EMA=30"
    )
    _args = _parser.parse_args()

    print("\n" + "="*60)
    print("RAITS — Real Walk-Forward Optimization")
    print("Blueprint Section 7.2 compliant")
    print("="*60)

    # Step 1: Fetch 5-min data
    market_data = fetch_market_data(
        tickers=TICKERS,
        start=DATASET_START,
        end=DATASET_END,
        interval_minutes=INTERVAL_MINS,
    )

    # Step 2: Validate
    if not validate_market_data(market_data):
        sys.exit(1)

    # Step 3: Load daily data for scanner (same logic as window_debug)
    import glob as _glob
    from raits.strategies.universe_scanner import CANDIDATE_POOL
    cache_daily = os.path.join(CACHE_DIR, "daily")
    daily_data: Dict[str, pd.DataFrame] = {}
    for ticker in ["SPY"] + CANDIDATE_POOL:
        files = _glob.glob(os.path.join(cache_daily, f"{ticker}_daily_*.parquet"))
        if not files:
            continue
        frames = [pd.read_parquet(f) for f in files]
        df = pd.concat(frames)
        df.index = pd.DatetimeIndex(df.index)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]
        daily_data[ticker] = df
    print(f"\n[OK] Daily data loaded: {len(daily_data)} tickers")

    # Step 4: Run WFO
    run_real_wfo(market_data, daily_data, fixed_params=_args.fixed_params)
