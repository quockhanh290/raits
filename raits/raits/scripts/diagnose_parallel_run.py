"""
scripts/diagnose_parallel_run.py
---------------------------------
Run orig + refactored engines on 6 year windows in parallel.
Wall time ~30 min (vs ~3h sequential).

Each worker: filter data to one year, run BacktestEngine then
RefactoredBacktestEngine, return both trade logs.

Cross-year TF-cooldown / equity state resets at year boundary — acceptable
for diagnostic purposes (structural bug shows up within each year).

Usage:
    cd d:\\raits\\raits
    python raits/scripts/diagnose_parallel_run.py
"""

import sys, os, pickle, time, argparse
import multiprocessing as mp

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import warnings
warnings.filterwarnings("ignore")

import yaml as _yaml
import pandas as pd
from collections import Counter

from raits.strategies.universe_scanner import CANDIDATE_POOL

# ── Universe ──────────────────────────────────────────────────────────────────
UNIVERSE    = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL"]
PHASE1      = ["INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
               "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX",
               "CSCO","GS","CRM","JPM"]
PHASE2      = ["MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM"]
PE_EXPANSION= ["PFE","MRK","LLY","ABBV","JNJ","BMY",
               "BAC","WFC","C","WMT","TGT","HD","LOW","MCD","NKE",
               "PG","KO","PEP","CAT","DE","BA","GE","PYPL","PANW","NOW"]
SECTOR_ETFS = ["XLF","XLE","XLV","XLU","XLI","XLK","XLP","XLB","XLY","GLD"]
TICKERS     = ["SPY","QQQ","IWM"] + SECTOR_ETFS + UNIVERSE + PHASE1 + PHASE2 + PE_EXPANSION

YEARS = [2017, 2018, 2019, 2020, 2021, 2022]

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PICKLE_5MIN  = os.path.join(_SCRIPTS_DIR, "..", "..", "data", "cache", "window_debug_5min.pkl")
PICKLE_DAILY = os.path.join(_SCRIPTS_DIR, "..", "..", "data", "cache", "window_debug_daily.pkl")
CACHE_DIR    = os.path.join(_SCRIPTS_DIR, "..", "..", "data", "cache")
_PARAMS_PATH = os.path.join(_SCRIPTS_DIR, "..", "..", "configs", "final_params.yaml")


def _load_params():
    with open(_PARAMS_PATH) as f:
        return _yaml.safe_load(f)


def _make_config(year, params):
    from raits.backtest.data_types import BacktestConfig
    return BacktestConfig(
        account_equity=50_000.0,
        start_date=f"{year}-01-01",
        end_date=f"{year}-12-31",
        universe=UNIVERSE + PHASE1 + PHASE2,
        orb_universe=list(CANDIDATE_POOL),
        vwap_universe=["SPY", "QQQ", "IWM"],
        orb_range_minutes=params["orb_range_minutes"],
        vwap_bb_std=params["vwap_bb_std"],
        ema_period=params["ema_period"],
        max_risk_pct=0.015,
        max_position_pct=0.40,
        kelly_fraction=0.75,
        enable_costs=True,
        enable_pdt_guard=True,
        hmm_retrain_weekly=True,
        allow_swing_hold=True,
        max_hold_days=5,
        stress_size_fraction=0.5,
        log_level="WARNING",
    )


def _run_year(args):
    """Worker: run both engines on one calendar year. Returns (year, orig_trades, refac_trades)."""
    year, market_data_year, daily_data = args

    import warnings
    warnings.filterwarnings("ignore")

    sys.path.insert(0, os.path.abspath(os.path.join(_SCRIPTS_DIR, '..', '..', '..')))

    from raits.backtest.engine import BacktestEngine
    from raits.backtest.engine_refactored import RefactoredBacktestEngine

    params = _load_params()
    config = _make_config(year, params)

    t0 = time.time()
    orig_engine = BacktestEngine(config)
    orig_result = orig_engine.run(market_data_year, daily_data)
    orig_trades = orig_result.trade_log

    refac_engine = RefactoredBacktestEngine(config)
    refac_result = refac_engine.run(market_data_year, daily_data)
    refac_trades = refac_result.trade_log

    elapsed = time.time() - t0
    print(f"  [{year}] orig={len(orig_trades)} refac={len(refac_trades)} "
          f"delta={len(refac_trades)-len(orig_trades):+d}  ({elapsed/60:.1f} min)", flush=True)

    return (year, orig_trades, refac_trades)


def find_extras(orig_trades, refac_trades):
    def key(t):
        return (t.ticker, t.strategy, str(t.entry_time))

    orig_counts = Counter(key(t) for t in orig_trades)
    extra, consumed = [], Counter()
    for t in refac_trades:
        k = key(t)
        if consumed[k] < orig_counts[k]:
            consumed[k] += 1
        else:
            extra.append(t)
    return extra


def find_missing(orig_trades, refac_trades):
    def key(t):
        return (t.ticker, t.strategy, str(t.entry_time))

    refac_counts = Counter(key(t) for t in refac_trades)
    missing, consumed = [], Counter()
    for t in orig_trades:
        k = key(t)
        if consumed[k] < refac_counts[k]:
            consumed[k] += 1
        else:
            missing.append(t)
    return missing


def print_breakdown(label, trades):
    if not trades:
        print(f"  {label}: (none)")
        return
    print(f"\n{'─'*60}")
    print(f"  {label}: {len(trades)} trades")

    print("\n  By strategy:")
    for s, n in Counter(t.strategy for t in trades).most_common():
        print(f"    {s:<22} {n:>4}")

    print("\n  By regime (hmm_state):")
    for r, n in Counter(t.hmm_state for t in trades).most_common():
        print(f"    {r:<22} {n:>4}")

    print("\n  By exit_reason:")
    for r, n in Counter(t.exit_reason for t in trades).most_common():
        print(f"    {r:<22} {n:>4}")

    print("\n  By year:")
    by_year = Counter(pd.Timestamp(t.entry_time).year for t in trades)
    for y in sorted(by_year):
        print(f"    {y}  {by_year[y]:>4}")


def check_tf_cooldown_suspect(extra_trades, orig_trades):
    tf_stop_dates = set()
    for t in orig_trades:
        if t.strategy == "TREND_FOLLOW" and t.exit_reason == "STOP_HIT":
            tf_stop_dates.add(pd.Timestamp(t.exit_time).date())

    extra_tf = [t for t in extra_trades if t.strategy == "TREND_FOLLOW"]
    suspect = [t for t in extra_tf
               if any(s <= pd.Timestamp(t.entry_time).date() for s in tf_stop_dates)]

    print(f"\n  TF cooldown suspect:")
    print(f"    Extra TF trades total:          {len(extra_tf)}")
    print(f"    ... on/after a TF stop-hit day: {len(suspect)}")
    if suspect:
        print("    Sample (ticker, entry_time, direction):")
        for t in sorted(suspect, key=lambda x: x.entry_time)[:5]:
            print(f"      {t.ticker:<8} {t.entry_time}  {t.direction}")


def check_position_limit_suspect(extra_trades, orig_trades):
    MAX_TOTAL = 5
    suspect = 0
    for t in extra_trades:
        entry_ts = pd.Timestamp(t.entry_time)
        open_count = sum(
            1 for o in orig_trades
            if pd.Timestamp(o.entry_time) <= entry_ts
            and (o.exit_time is None or pd.Timestamp(o.exit_time) > entry_ts)
        )
        if open_count >= MAX_TOTAL:
            suspect += 1
    print(f"\n  Position-limit suspect: {suspect} extra trades when orig already had ≥{MAX_TOTAL} open")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    cache_path = os.path.join(CACHE_DIR, "diag_parallel_results.pkl")

    if args.no_cache and os.path.exists(cache_path):
        os.remove(cache_path)
        print(f"Removed cache: {cache_path}")

    print("=" * 60)
    print("RAITS Parallel-Run Diagnostic  (6 years × 2 engines)")
    print("=" * 60)

    # ── Load from cache if available ─────────────────────────────────────────
    if os.path.exists(cache_path):
        print(f"Loading results from cache: {cache_path}")
        with open(cache_path, "rb") as f:
            year_results = pickle.load(f)
    else:
        # ── Load market data once in main process ─────────────────────────────
        print("Loading 5-min data...", end=" ", flush=True)
        with open(PICKLE_5MIN, "rb") as f:
            all_data = pickle.load(f)
        market_data_full = {t: df for t, df in all_data.items() if t in TICKERS}
        print(f"{len(market_data_full)} tickers")

        daily_data = None
        if os.path.exists(PICKLE_DAILY):
            with open(PICKLE_DAILY, "rb") as f:
                daily_data = pickle.load(f)

        # ── Pre-filter data per year to reduce IPC payload ────────────────────
        print(f"\nPre-filtering data by year...", flush=True)
        worker_args = []
        for year in YEARS:
            start = pd.Timestamp(f"{year}-01-01")
            end   = pd.Timestamp(f"{year}-12-31 23:59:59")
            md_year = {
                ticker: df[(df.index >= start) & (df.index <= end)]
                for ticker, df in market_data_full.items()
            }
            worker_args.append((year, md_year, daily_data))

        # ── Run in parallel ───────────────────────────────────────────────────
        n_workers = min(args.workers, len(YEARS))
        print(f"\nRunning {len(YEARS)} years × 2 engines ({n_workers} parallel workers)...")
        print("Each year takes ~25-35 min. Progress below:\n")

        with mp.Pool(processes=n_workers) as pool:
            year_results = pool.map(_run_year, worker_args)

        year_results.sort(key=lambda x: x[0])

        with open(cache_path, "wb") as f:
            pickle.dump(year_results, f)
        print(f"\nCached to: {cache_path}")

    # ── Merge all years ───────────────────────────────────────────────────────
    all_orig  = []
    all_refac = []
    print(f"\n{'─'*60}")
    print(f"  {'Year':<6} {'Orig':>6} {'Refac':>6} {'Delta':>6}")
    print(f"  {'─'*4:<6} {'─'*6:>6} {'─'*6:>6} {'─'*6:>6}")
    for year, orig, refac in year_results:
        delta = len(refac) - len(orig)
        flag  = "  ← MISMATCH" if delta != 0 else ""
        print(f"  {year:<6} {len(orig):>6} {len(refac):>6} {delta:>+6}{flag}")
        all_orig.extend(orig)
        all_refac.extend(refac)

    print(f"  {'─'*4:<6} {'─'*6:>6} {'─'*6:>6} {'─'*6:>6}")
    total_delta = len(all_refac) - len(all_orig)
    print(f"  {'TOTAL':<6} {len(all_orig):>6} {len(all_refac):>6} {total_delta:>+6}")

    # ── Find extras & missing ─────────────────────────────────────────────────
    extra   = find_extras(all_orig, all_refac)
    missing = find_missing(all_orig, all_refac)

    print_breakdown("EXTRA in refactored (not in original)", extra)
    print_breakdown("MISSING from refactored (in original only)", missing)

    # ── Suspect analysis ──────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SUSPECT ANALYSIS")
    check_tf_cooldown_suspect(extra, all_orig)
    check_position_limit_suspect(extra, all_orig)

    # ── First 10 extra trades in detail ──────────────────────────────────────
    if extra:
        print(f"\n{'─'*60}")
        print("First 10 extra trades (sorted by entry_time):")
        for t in sorted(extra, key=lambda t: t.entry_time)[:10]:
            print(f"  {t.entry_time}  {t.strategy:<14} {t.ticker:<8} "
                  f"{t.direction:<6} exit={t.exit_reason}  regime={t.hmm_state}")


if __name__ == "__main__":
    main()
