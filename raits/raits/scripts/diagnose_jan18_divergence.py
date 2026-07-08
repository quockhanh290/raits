"""
Diagnostic: Why does CVX TF enter on 2019-01-18 14:00 in engine.py but not engine_refactored?

Dumps which TF trades are OPEN at 2019-01-18 14:00 in each engine, and the
CVX TF stop-hit history before Jan 18 (to check whether cooldown is the cause).

Usage:
    cd d:\\raits\\raits
    python raits/scripts/diagnose_jan18_divergence.py
"""
import sys, os, pickle, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import yaml

from raits.backtest.data_types import BacktestConfig
from raits.backtest.engine_refactored import RefactoredBacktestEngine
from raits.strategies.universe_scanner import CANDIDATE_POOL

UNIVERSE = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL"]
PHASE1 = [
    "INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
    "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
    "CSCO", "GS", "CRM", "JPM",
]
PHASE2 = ["MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM"]
PE_EXPANSION = [
    "PFE", "MRK", "LLY", "ABBV", "JNJ", "BMY",
    "BAC", "WFC", "C", "WMT", "TGT", "HD", "LOW", "MCD", "NKE",
    "PG", "KO", "PEP", "CAT", "DE", "BA", "GE", "PYPL", "PANW", "NOW",
]
SECTOR_ETFS = ["XLF", "XLE", "XLV", "XLU", "XLI", "XLK", "XLP", "XLB", "XLY", "GLD"]
TICKERS = (
    ["SPY", "QQQ", "IWM"] + SECTOR_ETFS + UNIVERSE + PHASE1 + PHASE2 + PE_EXPANSION
)

PICKLE_5MIN  = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")
PICKLE_DAILY = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_daily.pkl")
ORIG_CACHE   = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "verify_orig_trades_IS.pkl")
_PARAMS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "configs", "final_params.yaml")

with open(_PARAMS_PATH) as _f:
    _params = yaml.safe_load(_f)

TARGET_DT = pd.Timestamp("2019-01-18 14:00:00")
SHORT_END  = "2019-01-25"


def make_config(end_date: str) -> BacktestConfig:
    return BacktestConfig(
        account_equity=50_000.0,
        start_date="2017-01-03",
        end_date=end_date,
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


def open_at(trades, target_dt: pd.Timestamp, strategy=None):
    """All trades open at target_dt (entry <= target_dt < exit), optionally filtered by strategy."""
    result = []
    for t in trades:
        if strategy and t.strategy != strategy:
            continue
        entry = pd.Timestamp(t.entry_time)
        exit_ = pd.Timestamp(t.exit_time) if t.exit_time else None
        if entry <= target_dt and (exit_ is None or exit_ > target_dt):
            result.append(t)
    return result


def cvx_tf_history_before(trades, cutoff: pd.Timestamp):
    """CVX TF trades that exited before cutoff, sorted by exit time."""
    result = []
    for t in trades:
        if t.ticker != "CVX" or t.strategy != "TREND_FOLLOW":
            continue
        if t.exit_time and pd.Timestamp(t.exit_time) < cutoff:
            result.append(t)
    return sorted(result, key=lambda x: x.exit_time)


def prev_close_for(ticker: str, market_data: dict, bar_ts: pd.Timestamp):
    """Last 5-min close strictly before bar_ts — mirrors cooldown recovery check."""
    if ticker not in market_data:
        return None
    idx = market_data[ticker].index
    before = idx[idx < bar_ts]
    if len(before) == 0:
        return None
    return float(market_data[ticker].loc[before[-1], "close"])


def print_trades(label: str, trades):
    for t in sorted(trades, key=lambda x: x.entry_time):
        print(f"  {t.ticker:6s}  entry={t.entry_time}  exit={t.exit_time}  "
              f"stop={t.stop:.2f}  exit_reason={t.exit_reason}  dir={t.direction}")
    print(f"  → {label} count = {len(trades)}")


def main():
    print("=" * 65)
    print("RAITS Divergence Diagnostic — CVX TF 2019-01-18 14:00")
    print("=" * 65)

    # ── Load data ──────────────────────────────────────────────────
    print("\nLoading 5-min data...")
    with open(PICKLE_5MIN, "rb") as f:
        all_data = pickle.load(f)
    market_data_full = {t: df for t, df in all_data.items() if t in TICKERS}

    print("Loading daily data...")
    with open(PICKLE_DAILY, "rb") as f:
        daily_data = pickle.load(f)

    # ── ORIG: load cached full-IS trades ──────────────────────────
    print("\n[ORIG] Loading engine.py cached trade log...")
    if not os.path.exists(ORIG_CACHE):
        print(f"  ERROR: {ORIG_CACHE} not found — run verify_parallel_run.py first to build cache")
        sys.exit(1)
    with open(ORIG_CACHE, "rb") as f:
        orig_trades = pickle.load(f)
    print(f"  Total: {len(orig_trades)} trades")

    orig_open_tf = open_at(orig_trades, TARGET_DT, strategy="TREND_FOLLOW")
    orig_open_all = open_at(orig_trades, TARGET_DT)
    print(f"\n[ORIG] ALL trades OPEN at {TARGET_DT}:")
    print_trades("ORIG open all", orig_open_all)
    print(f"\n[ORIG] TF trades OPEN at {TARGET_DT}:")
    print_trades("ORIG open TF", orig_open_tf)

    print("\n[ORIG] CVX TF history BEFORE 2019-01-18:")
    cvx_hist_orig = cvx_tf_history_before(orig_trades, TARGET_DT)
    if cvx_hist_orig:
        for t in cvx_hist_orig:
            print(f"  entry={t.entry_time}  exit={t.exit_time}  "
                  f"stop_at_exit={t.stop:.2f}  reason={t.exit_reason}")
            if t.exit_reason == "STOP_HIT":
                pc = prev_close_for("CVX", market_data_full, TARGET_DT)
                print(f"    → cooldown block_stop={t.stop:.2f}  "
                      f"CVX prev_close@Jan18-14:00={pc}")
                if pc is not None:
                    print(f"    → recovered? {pc:.2f} > {t.stop:.2f} = {pc > t.stop}")
    else:
        print("  None — CVX never had a TF entry before Jan 18 in ORIG")

    # ── REFAC: short run ──────────────────────────────────────────
    print(f"\n[REFAC] Running engine_refactored 2017-01-03 → {SHORT_END}...")
    market_data_short = {
        t: df[
            (df.index >= pd.Timestamp("2017-01-03"))
            & (df.index <= pd.Timestamp(SHORT_END))
        ]
        for t, df in market_data_full.items()
    }

    config = make_config(SHORT_END)
    t0 = time.time()
    engine = RefactoredBacktestEngine(config)
    result = engine.run(market_data_short, daily_data)
    elapsed = time.time() - t0
    refac_trades = result.trade_log
    print(f"  Done in {elapsed:.1f}s — {len(refac_trades)} trades total (to {SHORT_END})")

    refac_open_tf  = open_at(refac_trades, TARGET_DT, strategy="TREND_FOLLOW")
    refac_open_all = open_at(refac_trades, TARGET_DT)
    print(f"\n[REFAC] ALL trades OPEN at {TARGET_DT}:")
    print_trades("REFAC open all", refac_open_all)
    print(f"\n[REFAC] TF trades OPEN at {TARGET_DT}:")
    print_trades("REFAC open TF", refac_open_tf)

    print("\n[REFAC] CVX TF history BEFORE 2019-01-18:")
    cvx_hist_refac = cvx_tf_history_before(refac_trades, TARGET_DT)
    if cvx_hist_refac:
        for t in cvx_hist_refac:
            print(f"  entry={t.entry_time}  exit={t.exit_time}  "
                  f"stop_at_exit={t.stop:.2f}  reason={t.exit_reason}")
            if t.exit_reason == "STOP_HIT":
                pc = prev_close_for("CVX", market_data_full, TARGET_DT)
                print(f"    → cooldown block_stop={t.stop:.2f}  "
                      f"CVX prev_close@Jan18-14:00={pc}")
                if pc is not None:
                    print(f"    → recovered? {pc:.2f} > {t.stop:.2f} = {pc > t.stop}")
    else:
        print("  None — CVX never had a TF entry before Jan 18 in REFAC")

    # ── Comparison ────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("COMPARISON")
    print("=" * 65)
    orig_set  = {(t.ticker, str(t.entry_time)) for t in orig_open_all}
    refac_set = {(t.ticker, str(t.entry_time)) for t in refac_open_all}
    orig_set_tf  = {(t.ticker, str(t.entry_time)) for t in orig_open_tf}
    refac_set_tf = {(t.ticker, str(t.entry_time)) for t in refac_open_tf}
    only_refac_all = refac_set - orig_set
    only_orig_all  = orig_set  - refac_set
    only_refac_tf  = refac_set_tf - orig_set_tf
    only_orig_tf   = orig_set_tf  - refac_set_tf

    print(f"\n  ORIG  open (all strat) count: {len(orig_open_all)}")
    print(f"  REFAC open (all strat) count: {len(refac_open_all)}")
    if only_orig_all:
        print(f"\n  Extra in ORIG (all strat):")
        for k in sorted(only_orig_all):
            print(f"    {k}")
    if only_refac_all:
        print(f"\n  Extra in REFAC (all strat):")
        for k in sorted(only_refac_all):
            print(f"    {k}")

    print(f"\n  ORIG  open TF count: {len(orig_open_tf)}")
    print(f"  REFAC open TF count: {len(refac_open_tf)}")

    if only_refac_tf:
        print(f"\n  EXTRA TF in REFAC (occupies 3rd slot, blocks CVX):")
        for k in sorted(only_refac_tf):
            print(f"    ticker={k[0]}  entry={k[1]}")
        print("\n  ROOT CAUSE: extra TF in REFAC prevents CVX from entering")
    elif only_orig_tf:
        cvx_entries = [k for k in only_orig_tf if k[0] == "CVX"]
        non_cvx = [k for k in only_orig_tf if k[0] != "CVX"]
        if cvx_entries and not non_cvx:
            print(f"\n  Only extra in ORIG-TF is CVX itself (the entry we're investigating)")
            print(f"  → Both engines started with SAME pre-existing TF trades")
            print(f"  → CVX was blocked in REFAC by something OTHER than TF position count")
            if only_refac_all:
                print(f"  → REFAC has extra non-TF open trade(s) — this is the CVX ticker blocker:")
                for k in sorted(only_refac_all):
                    print(f"    {k}")
            elif only_orig_all:
                print(f"  → ORIG has extra non-TF open trade(s):")
                for k in sorted(only_orig_all):
                    print(f"    {k}")
            else:
                print(f"  → All-strategy open sets are IDENTICAL")
                print(f"  → CVX not blocked by open position; must be watchlist or generate_signal")
                print(f"  → Rerun with log_level='INFO' to see TF watchlist contents on Jan 18")
    else:
        print("\n  SAME open TF set in both engines at 14:00 Jan 18")
        print("  → CVX blocked by something else (cooldown, watchlist, or generate_signal)")

    print()


if __name__ == "__main__":
    main()