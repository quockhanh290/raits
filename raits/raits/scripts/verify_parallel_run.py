"""
scripts/verify_parallel_run.py
-------------------------------
Parallel-run verification: run BacktestEngine (original) and
RefactoredBacktestEngine on the same IS 2017-2022 data and assert
100% identical trade logs.

Usage:
    cd d:\\raits\\raits
    python raits/scripts/verify_parallel_run.py

SUCCESS: "✓ IDENTICAL: N trades matched 100%"
FAILURE: diff printed with every mismatched field
"""

import sys, os, pickle, time, argparse
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import warnings
warnings.filterwarnings("ignore")

import glob as _glob
import pandas as pd

from raits.backtest.engine import BacktestEngine
from raits.backtest.engine_refactored import RefactoredBacktestEngine
from raits.backtest.data_types import BacktestConfig
from raits.strategies.universe_scanner import CANDIDATE_POOL

# ── Config ───────────────────────────────────────────────────────────────────
# Must match the locked IS baseline (window_debug.py settings)
UNIVERSE      = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL"]
PHASE1        = [
    "INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
    "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
    "CSCO", "GS", "CRM", "JPM",
]
PHASE2        = ["MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM"]
PE_EXPANSION  = [
    "PFE", "MRK", "LLY", "ABBV", "JNJ", "BMY",
    "BAC", "WFC", "C", "WMT", "TGT", "HD", "LOW", "MCD", "NKE",
    "PG", "KO", "PEP", "CAT", "DE", "BA", "GE", "PYPL", "PANW", "NOW",
]
SECTOR_ETFS   = ["XLF", "XLE", "XLV", "XLU", "XLI", "XLK", "XLP", "XLB", "XLY", "GLD"]
TICKERS       = ["SPY", "QQQ", "IWM"] + SECTOR_ETFS + UNIVERSE + PHASE1 + PHASE2 + PE_EXPANSION

# IS period only — vault (2023+) stays sealed
IS_START = "2017-01-03"
IS_END   = "2022-12-30"

CACHE_5MIN  = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "data")
CACHE_DAILY = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "daily")
PICKLE_5MIN  = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")
PICKLE_DAILY = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_daily.pkl")
# engine.py never changes — cache its IS trade log so we skip the ~25-min run every iteration
ORIG_CACHE   = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "verify_orig_trades_IS.pkl")

import yaml as _yaml
_PARAMS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "configs", "final_params.yaml")
with open(_PARAMS_PATH) as _f:
    _params = _yaml.safe_load(_f)

COMPARED_FIELDS = [
    "ticker", "strategy", "direction",
    "entry_time", "entry_price", "shares",
    "exit_time", "exit_price", "exit_reason",
    "stop", "target", "hmm_state",
    "gross_pnl", "net_pnl",
]


def load_market_data():
    print("Loading 5-min data from pickle cache...")
    if not os.path.exists(PICKLE_5MIN):
        raise FileNotFoundError(
            f"5-min pickle not found: {PICKLE_5MIN}\n"
            "Run window_debug.py once first to build the cache."
        )
    with open(PICKLE_5MIN, "rb") as f:
        all_data = pickle.load(f)
    market_data = {t: df for t, df in all_data.items() if t in TICKERS}
    print(f"  Loaded {len(market_data)} tickers")
    return market_data


def load_daily_data():
    print("Loading daily data from pickle cache...")
    if not os.path.exists(PICKLE_DAILY):
        print("  Daily pickle not found — daily scanners disabled")
        return None
    with open(PICKLE_DAILY, "rb") as f:
        return pickle.load(f)


def make_config() -> BacktestConfig:
    return BacktestConfig(
        account_equity=50_000.0,
        start_date=IS_START,
        end_date=IS_END,
        universe=UNIVERSE + PHASE1 + PHASE2,
        orb_universe=list(CANDIDATE_POOL),
        vwap_universe=["SPY", "QQQ", "IWM"],
        orb_range_minutes=_params["orb_range_minutes"],
        vwap_bb_std=_params["vwap_bb_std"],
        ema_period=_params["ema_period"],
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


def _trade_key(t):
    return (str(getattr(t, "entry_time", "?")), getattr(t, "ticker", "?"), getattr(t, "strategy", "?"))


def compare_trade_logs(orig_trades, refac_trades):
    mismatches = []
    if len(orig_trades) != len(refac_trades):
        mismatches.append({
            "type": "TRADE_COUNT",
            "diff": f"count {len(orig_trades)} vs {len(refac_trades)}",
        })
        # Show which specific trades differ (set-based on entry_time+ticker+strategy)
        orig_keys = {}
        for t in orig_trades:
            k = _trade_key(t)
            orig_keys[k] = orig_keys.get(k, 0) + 1
        refac_keys = {}
        for t in refac_trades:
            k = _trade_key(t)
            refac_keys[k] = refac_keys.get(k, 0) + 1
        only_in_orig = []
        only_in_refac = []
        all_keys = set(list(orig_keys.keys()) + list(refac_keys.keys()))
        for k in sorted(all_keys):
            oc = orig_keys.get(k, 0)
            rc = refac_keys.get(k, 0)
            if oc > rc:
                for _ in range(oc - rc):
                    only_in_orig.append(k)
            elif rc > oc:
                for _ in range(rc - oc):
                    only_in_refac.append(k)
        if only_in_orig:
            mismatches.append({"type": "ONLY_IN_ORIG", "trades": only_in_orig})
        if only_in_refac:
            mismatches.append({"type": "ONLY_IN_REFAC", "trades": only_in_refac})
        return mismatches

    for i, (a, b) in enumerate(zip(orig_trades, refac_trades)):
        for field in COMPARED_FIELDS:
            va = getattr(a, field, None)
            vb = getattr(b, field, None)
            if isinstance(va, float) and isinstance(vb, float):
                match = abs(va - vb) < 0.01
            else:
                match = (va == vb)
            if not match:
                mismatches.append({
                    "type": "FIELD_MISMATCH",
                    "trade_index": i,
                    "ticker": getattr(a, "ticker", "?"),
                    "strategy": getattr(a, "strategy", "?"),
                    "entry_time": str(getattr(a, "entry_time", "?")),
                    "field": field,
                    "original": va,
                    "refactored": vb,
                })
    return mismatches


def run_engine(engine_cls, market_data, daily_data, config, label):
    print(f"\nRunning {label}...")
    t0 = time.time()
    engine = engine_cls(config)
    result = engine.run(market_data, daily_data)
    elapsed = time.time() - t0
    trades  = result.trade_log
    total_pnl = sum(t.net_pnl or 0.0 for t in trades)
    print(f"  {label}: {len(trades)} trades | P&L ${total_pnl:,.2f} | {elapsed:.1f}s")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset-orig-cache", action="store_true",
                        help="Delete cached original trade log and re-run engine.py")
    args = parser.parse_args()

    if args.reset_orig_cache and os.path.exists(ORIG_CACHE):
        os.remove(ORIG_CACHE)
        print(f"Deleted orig cache: {ORIG_CACHE}")

    print("=" * 60)
    print("RAITS Parallel-Run Verification (IS 2017-2022)")
    print("=" * 60)

    market_data = load_market_data()
    daily_data  = load_daily_data()
    config      = make_config()

    # Filter to IS period
    for ticker in list(market_data.keys()):
        df = market_data[ticker]
        market_data[ticker] = df[
            (df.index >= pd.Timestamp(IS_START))
            & (df.index <= pd.Timestamp(IS_END))
        ]

    # engine.py is read-only — cache its trade log; only re-run with --reset-orig-cache
    if os.path.exists(ORIG_CACHE):
        print(f"\nLoading original trade log from cache (use --reset-orig-cache to force re-run)...")
        with open(ORIG_CACHE, "rb") as f:
            orig_trades = pickle.load(f)
        print(f"  BacktestEngine (cached): {len(orig_trades)} trades")
    else:
        orig_result = run_engine(BacktestEngine, market_data, daily_data, config, "BacktestEngine (original)")
        orig_trades = orig_result.trade_log
        with open(ORIG_CACHE, "wb") as f:
            pickle.dump(orig_trades, f)
        print(f"  Cached to: {ORIG_CACHE}")

    refac_result  = run_engine(RefactoredBacktestEngine, market_data, daily_data, config, "RefactoredBacktestEngine")

    refac_trades = refac_result.trade_log

    print(f"\n{'-'*60}")
    print("COMPARISON")
    print(f"  Original trades:   {len(orig_trades)}")
    print(f"  Refactored trades: {len(refac_trades)}")

    mismatches = compare_trade_logs(orig_trades, refac_trades)

    if not mismatches:
        print(f"\nOK IDENTICAL: {len(orig_trades)} trades matched 100%")
        pnl_o = sum(t.net_pnl or 0.0 for t in orig_trades)
        pnl_r = sum(t.net_pnl or 0.0 for t in refac_trades)
        print(f"\nAggregate metrics:")
        print(f"  Original:   {len(orig_trades)} trades, P&L ${pnl_o:,.2f}")
        print(f"  Refactored: {len(refac_trades)} trades, P&L ${pnl_r:,.2f}")
        diff_pnl = abs(pnl_o - pnl_r)
        if diff_pnl < 1.0:
            print(f"  P&L diff: ${diff_pnl:.4f} OK (< $1)")
        else:
            print(f"  FAIL P&L diff: ${diff_pnl:.4f} (unexpected)")
    else:
        count_mm   = [m for m in mismatches if m["type"] == "TRADE_COUNT"]
        field_mm   = [m for m in mismatches if m["type"] == "FIELD_MISMATCH"]
        orig_only  = [m for m in mismatches if m["type"] == "ONLY_IN_ORIG"]
        refac_only = [m for m in mismatches if m["type"] == "ONLY_IN_REFAC"]
        print(f"\nFAIL MISMATCH DETECTED")
        if count_mm:
            print(f"  Count: {count_mm[0]['diff']}")
        if orig_only:
            print(f"  In ORIGINAL only (BacktestEngine has but Refactored lacks):")
            for k in orig_only[0]["trades"]:
                print(f"    entry_time={k[0]}  ticker={k[1]}  strategy={k[2]}")
        if refac_only:
            print(f"  In REFACTORED only (Refactored has but BacktestEngine lacks):")
            for k in refac_only[0]["trades"]:
                print(f"    entry_time={k[0]}  ticker={k[1]}  strategy={k[2]}")
        if field_mm:
            print(f"  Field mismatches: {len(field_mm)}")
            for m in field_mm[:20]:
                print(
                    f"    trade[{m['trade_index']}] {m['ticker']}/{m['strategy']} "
                    f"@ {m['entry_time']}  "
                    f"{m['field']}: {m['original']!r} -> {m['refactored']!r}"
                )
            if len(field_mm) > 20:
                print(f"    ... and {len(field_mm) - 20} more")
        print("\n  -> Extraction is WRONG. Fix DecisionUnit before declaring success.")
        sys.exit(1)


if __name__ == "__main__":
    main()
