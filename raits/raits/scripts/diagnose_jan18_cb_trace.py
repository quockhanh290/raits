"""
Diagnostic: WHY does the circuit breaker fire on 2019-01-18 before 14:00 in REFAC?

Compares:
  1. Open positions at START of Jan 18 (after reset) in ORIG vs REFAC
  2. All trades that CLOSED on Jan 18 before 14:00 in both engines
  3. Cumulative consecutive-loss streak at each closed trade on Jan 18

Usage:
    cd d:\\raits\\raits
    python raits/scripts/diagnose_jan18_cb_trace.py
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

JAN18_START = pd.Timestamp("2019-01-18 09:30:00")
JAN18_CUTOFF = pd.Timestamp("2019-01-18 14:00:00")
SHORT_END = "2019-01-25"


def make_config() -> BacktestConfig:
    return BacktestConfig(
        account_equity=50_000.0,
        start_date="2017-01-03",
        end_date=SHORT_END,
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


def open_at_start_of_day(trades, day: pd.Timestamp):
    """Trades still open at the START of day (entry < day 09:30, exit >= 09:30 or still open)."""
    result = []
    day_open = day.normalize() + pd.Timedelta(hours=9, minutes=30)
    for t in trades:
        entry = pd.Timestamp(t.entry_time)
        exit_ = pd.Timestamp(t.exit_time) if t.exit_time else None
        if entry < day_open and (exit_ is None or exit_ >= day_open):
            result.append(t)
    return sorted(result, key=lambda x: x.entry_time)


def closed_on_day_before(trades, day: pd.Timestamp, cutoff: pd.Timestamp):
    """Trades that CLOSED on `day` strictly before `cutoff`."""
    day_open = day.normalize() + pd.Timedelta(hours=9, minutes=30)
    result = []
    for t in trades:
        if not t.exit_time:
            continue
        exit_ = pd.Timestamp(t.exit_time)
        if day_open <= exit_ < cutoff:
            result.append(t)
    return sorted(result, key=lambda x: x.exit_time)


def simulate_cb_streak(closed_trades):
    """
    Simulate the consecutive-loss counter for a list of closed trades in order.
    Returns list of (trade, streak_after_this_trade, cb_fired).
    CB fires when streak reaches 5.
    """
    streak = 0
    rows = []
    cb_fired = False
    for t in closed_trades:
        pnl = t.net_pnl or 0.0
        if pnl < 0:
            streak += 1
        else:
            streak = 0
        fires = not cb_fired and streak >= 5
        if fires:
            cb_fired = True
        rows.append((t, streak, fires))
    return rows


def print_trades(label, trades):
    for t in trades:
        pnl_str = f"pnl={t.net_pnl:+.2f}" if t.net_pnl is not None else "pnl=?"
        print(f"  {t.ticker:6s} {t.strategy:12s} {t.direction:5s} "
              f"entry={t.entry_time}  exit={t.exit_time}  "
              f"reason={t.exit_reason}  {pnl_str}")
    print(f"  -> {label} count: {len(trades)}")


def main():
    print("=" * 70)
    print("RAITS CB Trace - Why does circuit breaker fire before Jan 18 14:00?")
    print("=" * 70)

    # Load data
    print("\nLoading 5-min data...")
    with open(PICKLE_5MIN, "rb") as f:
        all_data = pickle.load(f)
    market_data_full = {t: df for t, df in all_data.items() if t in TICKERS}

    print("Loading daily data...")
    with open(PICKLE_DAILY, "rb") as f:
        daily_data = pickle.load(f)

    # ORIG: load cached trade log
    print("\n[ORIG] Loading cached full-IS trade log...")
    with open(ORIG_CACHE, "rb") as f:
        orig_trades = pickle.load(f)
    print(f"  Total: {len(orig_trades)} trades")

    # REFAC: run short engine
    print(f"\n[REFAC] Running engine_refactored 2017-01-03 to {SHORT_END}...")
    market_data_short = {
        t: df[
            (df.index >= pd.Timestamp("2017-01-03"))
            & (df.index <= pd.Timestamp(SHORT_END))
        ]
        for t, df in market_data_full.items()
    }
    config = make_config()
    t0 = time.time()
    engine = RefactoredBacktestEngine(config)
    result = engine.run(market_data_short, daily_data)
    elapsed = time.time() - t0
    refac_trades = result.trade_log
    print(f"  Done in {elapsed:.1f}s - {len(refac_trades)} trades total")
    _refac_cache = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "verify_refac_jan25_trades.pkl")
    with open(_refac_cache, "wb") as f:
        pickle.dump(refac_trades, f)
    print(f"  REFAC trades saved to {_refac_cache}")

    # Section 1: Open positions at start of Jan 18
    print("\n" + "=" * 70)
    print("SECTION 1: Open positions at START of Jan 18 (carried from prev days)")
    print("=" * 70)

    orig_open = open_at_start_of_day(orig_trades, JAN18_START)
    refac_open = open_at_start_of_day(refac_trades, JAN18_START)

    print(f"\n[ORIG] Positions open at start of Jan 18 ({len(orig_open)}):")
    print_trades("ORIG open", orig_open)

    print(f"\n[REFAC] Positions open at start of Jan 18 ({len(refac_open)}):")
    print_trades("REFAC open", refac_open)

    # Highlight differences
    orig_keys = {(t.ticker, t.strategy, str(t.entry_time)) for t in orig_open}
    refac_keys = {(t.ticker, t.strategy, str(t.entry_time)) for t in refac_open}
    only_orig = orig_keys - refac_keys
    only_refac = refac_keys - orig_keys
    if only_orig:
        print(f"\n  ONLY in ORIG open at Jan 18 start:")
        for k in sorted(only_orig):
            print(f"    {k}")
    if only_refac:
        print(f"\n  ONLY in REFAC open at Jan 18 start:")
        for k in sorted(only_refac):
            print(f"    {k}")
    if not only_orig and not only_refac:
        print("\n  IDENTICAL open positions at start of Jan 18")

    # Section 2: Trades closed on Jan 18 before 14:00
    print("\n" + "=" * 70)
    print("SECTION 2: Trades CLOSED on Jan 18 before 14:00")
    print("=" * 70)

    orig_closed = closed_on_day_before(orig_trades, JAN18_START, JAN18_CUTOFF)
    refac_closed = closed_on_day_before(refac_trades, JAN18_START, JAN18_CUTOFF)

    print(f"\n[ORIG] Trades closed on Jan 18 before 14:00 ({len(orig_closed)}):")
    print_trades("ORIG closed", orig_closed)

    print(f"\n[REFAC] Trades closed on Jan 18 before 14:00 ({len(refac_closed)}):")
    print_trades("REFAC closed", refac_closed)

    # Section 3: Consecutive loss streak simulation
    print("\n" + "=" * 70)
    print("SECTION 3: Consecutive loss streak on Jan 18 (reset at day start)")
    print("=" * 70)

    print("\n[ORIG] CB streak simulation:")
    orig_rows = simulate_cb_streak(orig_closed)
    if orig_rows:
        for trade, streak, fires in orig_rows:
            pnl = trade.net_pnl or 0.0
            flag = " *** CB FIRES ***" if fires else ""
            print(f"  {trade.exit_time}  {trade.ticker:6s} {trade.strategy:12s} "
                  f"pnl={pnl:+.2f}  streak={streak}{flag}")
        if not any(fires for _, _, fires in orig_rows):
            print("  -> CB does NOT fire in ORIG on Jan 18 before 14:00")
    else:
        print("  (No trades closed before 14:00)")

    print("\n[REFAC] CB streak simulation:")
    refac_rows = simulate_cb_streak(refac_closed)
    if refac_rows:
        for trade, streak, fires in refac_rows:
            pnl = trade.net_pnl or 0.0
            flag = " *** CB FIRES ***" if fires else ""
            print(f"  {trade.exit_time}  {trade.ticker:6s} {trade.strategy:12s} "
                  f"pnl={pnl:+.2f}  streak={streak}{flag}")
        if not any(fires for _, _, fires in refac_rows):
            print("  -> CB does NOT fire in REFAC on Jan 18 before 14:00")
    else:
        print("  (No trades closed before 14:00)")

    # Section 4: Diff of closed trades
    print("\n" + "=" * 70)
    print("SECTION 4: Diff of closed trades on Jan 18 before 14:00")
    print("=" * 70)
    orig_c_keys = {(t.ticker, t.strategy, str(t.exit_time)) for t in orig_closed}
    refac_c_keys = {(t.ticker, t.strategy, str(t.exit_time)) for t in refac_closed}
    only_orig_c = orig_c_keys - refac_c_keys
    only_refac_c = refac_c_keys - orig_c_keys
    if only_orig_c:
        print(f"\n  ONLY in ORIG closed on Jan 18 before 14:00:")
        for k in sorted(only_orig_c): print(f"    {k}")
    if only_refac_c:
        print(f"\n  ONLY in REFAC closed on Jan 18 before 14:00:")
        for k in sorted(only_refac_c): print(f"    {k}")
    if not only_orig_c and not only_refac_c:
        print("\n  SAME set of closed trades in both engines (same CB exposure)")

    print()


if __name__ == "__main__":
    main()