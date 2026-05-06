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
from datetime import datetime, timedelta
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
DATASET_END   = "2024-12-31"   # Keep 2025 as fresh validation data

UNIVERSE     = ["TSLA", "NFLX", "AMD", "BABA", "ROKU", "SQ"]
ORB_UNIVERSE = ["TSLA", "AMD", "NVDA", "META", "NFLX", "BABA"]   # volatile gappers — ORB only
TICKERS      = ["SPY"] + UNIVERSE + [t for t in ORB_UNIVERSE if t not in UNIVERSE]

CACHE_DIR     = "./raits/data/cache"
INTERVAL_MINS = 5


def fetch_market_data(
    tickers: list,
    start: str,
    end: str,
    interval_minutes: int = 5,
) -> Dict[str, pd.DataFrame]:
    """
    Pull multi-year 5-minute bars for all tickers using PolygonDataFetcher.
    Results are cached in Parquet — subsequent runs are fast.

    Returns dict: ticker → DataFrame with DatetimeIndex, lowercase OHLCV columns.
    """
    fetcher = PolygonDataFetcher(
        api_key=POLYGON_API_KEY,
        use_cache=True,
        cache_dir=CACHE_DIR,
        rate_limit_calls_per_minute=100,  # Developer plan
    )

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt   = datetime.strptime(end,   "%Y-%m-%d")

    trading_days = pd.bdate_range(start=start_dt, end=end_dt)
    total_calls  = len(trading_days) * len(tickers)

    print(f"\n{'='*60}")
    print(f"Fetching {interval_minutes}-min data: {start} -> {end}")
    print(f"Tickers:      {tickers}")
    print(f"Trading days: {len(trading_days)}")
    print(f"API calls:    ~{total_calls:,} (cached after first run)")
    print(f"Cache dir:    {CACHE_DIR}")
    print(f"{'='*60}\n")

    market_data: Dict[str, pd.DataFrame] = {}

    for ticker in tickers:
        print(f"  {ticker} ...", end=" ", flush=True)
        frames = []
        errors = 0

        for day in trading_days:
            try:
                hist = fetcher.fetch_intraday_bars(
                    ticker=ticker,
                    date=day.to_pydatetime(),
                    interval_minutes=interval_minutes,
                    use_cache=True,
                )
                df = hist.to_dataframe().reset_index()
                df.rename(columns={"timestamp": "datetime"}, inplace=True)
                df.set_index("datetime", inplace=True)
                df.index = pd.DatetimeIndex(df.index)
                # Lowercase columns
                df.columns = [c.lower() for c in df.columns]
                # Keep market hours only
                df = df.between_time("09:30", "16:00")
                if not df.empty:
                    frames.append(df)
            except Exception as e:
                errors += 1
                logger.debug(f"{ticker} {day.date()}: {e}")

        if frames:
            combined = pd.concat(frames).sort_index()
            # Drop duplicate timestamps
            combined = combined[~combined.index.duplicated(keep="first")]
            market_data[ticker] = combined
            days_loaded = len(combined.index.normalize().unique())
            print(f"[OK] {days_loaded} days, {len(combined):,} bars"
                  + (f" ({errors} errors)" if errors else ""))
        else:
            print(f"[FAIL] No data returned ({errors} errors)")

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

    print(f"\n[OK] Data validated: {spy_days} SPY days, {stocks}/{len(UNIVERSE)} stocks")
    return True


def run_real_wfo(market_data: dict) -> None:
    """Execute the full WFO per blueprint Section 7.2."""
    cfg = WFOConfig(
        full_dataset_start=DATASET_START,
        full_dataset_end=DATASET_END,
        vault_fraction=0.25,          # 25% held out — ~2 years (2023-2024), allows 3+ OOS windows
        train_years=3,                # Blueprint: 3-year training windows
        test_years=1,                 # Blueprint: 1-year OOS test
        universe=UNIVERSE,
        orb_universe=ORB_UNIVERSE,
        account_equity=50_000.0,
        enable_costs=True,
        enable_pdt_guard=False,       # False — above $25k PDT threshold
        log_level="WARNING",
        aggregation_method="MEAN",    # Blueprint: arithmetic mean
    )

    print(f"\n{'='*60}")
    print("REAL WFO RUN -- blueprint Section 7.2")
    print(f"  Train window:  {cfg.train_years} years")
    print(f"  Test window:   {cfg.test_years} year")
    print(f"  Grid:          27 combinations per window")
    print(f"  Vault holdout: {cfg.vault_fraction:.0%} of data")
    print(f"  Note: Expect 2-4 hours on first run (81 backtests × real data)")
    print(f"{'='*60}\n")

    engine = WFOEngine(cfg)
    report = engine.run(market_data)

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
    print("\n" + "="*60)
    print("RAITS — Real Walk-Forward Optimization")
    print("Blueprint Section 7.2 compliant")
    print("="*60)

    # Step 1: Fetch data
    market_data = fetch_market_data(
        tickers=TICKERS,
        start=DATASET_START,
        end=DATASET_END,
        interval_minutes=INTERVAL_MINS,
    )

    # Step 2: Validate
    if not validate_market_data(market_data):
        sys.exit(1)

    # Step 3: Run WFO
    run_real_wfo(market_data)
