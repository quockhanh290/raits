"""
raits/live/verify_live_path.py

Part 3 verification: PaperTrader(ReplayContextFeed + MockBroker zero-slippage)
produces the same trade log as engine_refactored field-by-field.

Scope tested
------------
- ticker, strategy, direction
- entry_time, entry_price, shares
- exit_time, exit_price, exit_reason
- stop, target, hmm_state, gross_pnl
- net_pnl (identical to gross_pnl because enable_costs=False in both runs)

Known structural difference
---------------------------
Same-bar entry+exit: engine calls decision_unit._check_exits() immediately
after opening an intraday trade (Bug B fix), closing it on the entry bar if
the bar already breached stop/target.  PaperTrader does not replicate this
post-entry intraday check — the exit appears one bar later.  Any mismatch
labelled "SAME_BAR_EXIT" in the report is this known modeling difference,
not a pipeline bug.

Usage (from d:\\raits\\raits):
    python live/verify_live_path.py [--days N] [--start YYYY-MM-DD] [--full]
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
import warnings
from typing import Callable, Dict, List, Optional

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pandas as pd
import yaml as _yaml

from raits.backtest.engine_refactored import RefactoredBacktestEngine
from raits.backtest.data_types import BacktestConfig, Trade
from raits.costs import calculate_total_costs
from raits.decision.decision_unit import DecisionUnit
from raits.live.broker import MockBroker
from raits.live.context_feed import ReplayContextFeed
from raits.live.reconciliation import ReconciliationLog
from raits.live.runner import PaperTrader
from raits.strategies.universe_scanner import CANDIDATE_POOL

# ── Universe (must match engine_refactored run config) ────────────────────────
UNIVERSE  = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL"]
PHASE1    = [
    "INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
    "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
    "CSCO", "GS", "CRM", "JPM",
]
PHASE2    = ["MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM"]
PE_EXPANSION = [
    "PFE", "MRK", "LLY", "ABBV", "JNJ", "BMY",
    "BAC", "WFC", "C", "WMT", "TGT", "HD", "LOW", "MCD", "NKE",
    "PG", "KO", "PEP", "CAT", "DE", "BA", "GE", "PYPL", "PANW", "NOW",
]
SECTOR_ETFS = ["XLF", "XLE", "XLV", "XLU", "XLI", "XLK", "XLP", "XLB", "XLY", "GLD"]
TICKERS = (
    ["SPY", "QQQ", "IWM"] + SECTOR_ETFS + UNIVERSE + PHASE1 + PHASE2 + PE_EXPANSION
)

_SCRIPT_DIR  = os.path.dirname(__file__)
_CACHE_DIR   = os.path.join(_SCRIPT_DIR, "..", "data", "cache")
PICKLE_5MIN  = os.path.normpath(os.path.join(_CACHE_DIR, "window_debug_5min.pkl"))
PICKLE_DAILY = os.path.normpath(os.path.join(_CACHE_DIR, "window_debug_daily.pkl"))
_PARAMS_PATH = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "configs", "final_params.yaml"))

COMPARED_FIELDS = [
    "ticker", "strategy", "direction",
    "entry_time", "entry_price", "shares",
    "exit_time", "exit_price", "exit_reason",
    "stop", "target", "hmm_state",
    "gross_pnl", "net_pnl",
]


# ── Data + config ─────────────────────────────────────────────────────────────

def load_data():
    with open(PICKLE_5MIN, "rb") as f:
        all_data = pickle.load(f)
    market_data = {t: df for t, df in all_data.items() if t in TICKERS}
    daily_data = None
    if os.path.exists(PICKLE_DAILY):
        with open(PICKLE_DAILY, "rb") as f:
            daily_data = pickle.load(f)
    return market_data, daily_data


def make_config(params: dict, start: str, end: str, enable_costs: bool = False) -> BacktestConfig:
    return BacktestConfig(
        account_equity=50_000.0,
        start_date=start,
        end_date=end,
        universe=UNIVERSE + PHASE1 + PHASE2,
        orb_universe=list(CANDIDATE_POOL),
        vwap_universe=["SPY", "QQQ", "IWM"],
        orb_range_minutes=params["orb_range_minutes"],
        vwap_bb_std=params["vwap_bb_std"],
        ema_period=params["ema_period"],
        max_risk_pct=0.015,
        max_position_pct=0.40,
        kelly_fraction=0.75,
        enable_costs=enable_costs,
        enable_pdt_guard=True,
        hmm_retrain_weekly=True,
        allow_swing_hold=True,
        max_hold_days=5,
        stress_size_fraction=0.5,
        log_level="WARNING",
    )


def engine_cost_fn(trade: Trade, exit_price: float) -> float:
    """Mirrors engine_refactored._compute_costs() exactly — same dict shape and constants."""
    try:
        result = calculate_total_costs({
            "ticker":     trade.ticker,
            "shares":     trade.shares,
            "price":      exit_price,
            "direction":  "BUY" if trade.direction == "LONG" else "SELL",
            "hmm_state":  trade.hmm_state,
            "market_cap": 2.5e12,
            "adv":        1_000_000,
            "volatility": 0.02,
        })
        if isinstance(result, dict):
            return float(result.get("total", 0.0))
        return float(getattr(result, "total", 0.0))
    except Exception:
        return 0.0


# ── DecisionUnit factory ──────────────────────────────────────────────────────

def build_decision_unit(config: BacktestConfig) -> DecisionUnit:
    """
    Instantiate a fresh DecisionUnit using the same strategy configs as
    engine_refactored.run().  Mirrors lines 156-223 of engine_refactored.py
    exactly; any change there must be reflected here.
    """
    tmp = RefactoredBacktestEngine(config)
    mods = tmp._mods  # populated in __init__ via _load_modules(); no run() needed

    pdt_guard = mods["PDTGuard"]()
    position_sizer = mods["PositionSizer"](
        account_equity=config.account_equity,
        max_risk_pct=config.max_risk_pct,
        max_position_pct=config.max_position_pct,
        kelly_fraction=config.kelly_fraction,
    )
    coordinator = mods["RegimeCoordinator"]()

    orb = mods["ORBStrategy"](config={
        "opening_vol_multiplier": 1.2,
        "min_price": 1.0,
        "max_price": 1e9,
        "min_gap_pct": 0.01,
    })
    stress_orb = mods["ORBStrategy"](config={
        "allowed_regimes":        ["Stress"],
        "min_gap_pct":            0.0,
        "rvol_threshold":         0.0,
        "min_price":              1.0,
        "max_price":              1e9,
        "min_range_atr_multiple": 0.2,
    })
    fade_orb = mods["ORBStrategy"](config={
        "opening_vol_multiplier": 1.2,
        "min_price":              1.0,
        "max_price":              1e9,
        "min_gap_pct":            0.0,
        "rvol_threshold":         0.0,
        "fade_require_midpoint":  False,
        "fade_long_enabled":      True,
    })
    vwap_mr = mods["VWAPMRStrategy"](config={"bb_std_dev": config.vwap_bb_std})
    trend   = mods["TrendStrategy"](config={"ema_period": config.ema_period})

    return DecisionUnit(
        config=config,
        orb=orb,
        stress_orb=stress_orb,
        fade_orb=fade_orb,
        vwap_mr=vwap_mr,
        trend=trend,
        coordinator=coordinator,
        position_sizer=position_sizer,
        pdt_guard=pdt_guard,
    )


# ── Trade log comparator (key-based matching) ────────────────────────────────

def _trade_key(t: Trade) -> tuple:
    """Unique trade identifier: (ticker, strategy, direction, entry_time)."""
    return (t.ticker, t.strategy, t.direction, str(t.entry_time))


def compare_trade_logs(
    engine_trades: List[Trade], paper_trades: List[Trade]
) -> List[dict]:
    """
    Key-based comparison: match by (ticker, strategy, direction, entry_time)
    before comparing fields.  This rules out ordering differences before
    flagging pipeline bugs.
    """
    mismatches = []

    # Index by key; warn on duplicates (shouldn't happen with position caps)
    engine_map: Dict[tuple, Trade] = {}
    for t in engine_trades:
        k = _trade_key(t)
        if k in engine_map:
            mismatches.append({"type": "DUPLICATE_KEY_ENGINE", "key": k})
        engine_map[k] = t

    paper_map: Dict[tuple, Trade] = {}
    for t in paper_trades:
        k = _trade_key(t)
        if k in paper_map:
            mismatches.append({"type": "DUPLICATE_KEY_PAPER", "key": k})
        paper_map[k] = t

    engine_keys = set(engine_map)
    paper_keys  = set(paper_map)

    for k in sorted(engine_keys - paper_keys, key=str):
        t = engine_map[k]
        mismatches.append({
            "type":   "MISSING_IN_PAPER",
            "ticker": t.ticker, "strategy": t.strategy,
            "entry_time": str(t.entry_time),
        })
    for k in sorted(paper_keys - engine_keys, key=str):
        t = paper_map[k]
        mismatches.append({
            "type":   "EXTRA_IN_PAPER",
            "ticker": t.ticker, "strategy": t.strategy,
            "entry_time": str(t.entry_time),
        })

    # Field-by-field on matched trades
    for k in sorted(engine_keys & paper_keys, key=str):
        a, b = engine_map[k], paper_map[k]
        for fld in COMPARED_FIELDS:
            va = getattr(a, fld, None)
            vb = getattr(b, fld, None)
            if isinstance(va, float) and isinstance(vb, float):
                ok = abs(va - vb) < 0.01
            else:
                ok = va == vb
            if not ok:
                mismatches.append({
                    "type":       "FIELD_MISMATCH",
                    "key":        k,
                    "ticker":     a.ticker,
                    "strategy":   a.strategy,
                    "entry_time": str(a.entry_time),
                    "field":      fld,
                    "engine":     va,
                    "paper":      vb,
                })

    return mismatches


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Verify PaperTrader trade log matches engine_refactored"
    )
    parser.add_argument("--days",  type=int, default=5,
                        help="First N IS trading days (default 5)")
    parser.add_argument("--start", type=str, default="2017-01-03")
    parser.add_argument("--end",   type=str, default=None,
                        help="Explicit IS end date (overrides --days)")
    parser.add_argument("--full",  action="store_true",
                        help="Full IS 2017-2022")
    parser.add_argument("--costs", action="store_true",
                        help="Enable cost model (verify net_pnl to the cent)")
    args = parser.parse_args()

    print("=" * 60)
    print("RAITS Live-Path Verification (Part 3)")
    print("=" * 60)

    market_data, daily_data = load_data()
    print(f"  {len(market_data)} tickers loaded")

    with open(_PARAMS_PATH) as f:
        params = _yaml.safe_load(f)

    IS_START = args.start
    if args.full:
        IS_END = "2022-12-30"
    elif args.end:
        IS_END = args.end
    else:
        spy = market_data["SPY"]
        avail = sorted(
            spy[spy.index.normalize() >= pd.Timestamp(IS_START)]
            .index.normalize().unique()
        )
        IS_END = str(avail[min(args.days - 1, len(avail) - 1)].date())

    costs_label = "costs ON" if args.costs else "costs OFF (net_pnl == gross_pnl)"
    print(f"  Window: {IS_START} -> {IS_END}  |  {costs_label}")

    for ticker in list(market_data.keys()):
        df = market_data[ticker]
        market_data[ticker] = df[
            (df.index >= pd.Timestamp(IS_START))
            & (df.index <= pd.Timestamp(IS_END))
        ]

    config = make_config(params, IS_START, IS_END, enable_costs=args.costs)

    # ── Step 1: engine_refactored (ground truth) ──────────────────────────────
    print("\nStep 1: Running engine_refactored (ground truth)...")
    engine = RefactoredBacktestEngine(config)
    engine_result = engine.run(market_data, daily_data)
    engine_trades = engine_result.trade_log
    engine_closed = [t for t in engine_trades if not t.is_open]
    engine_pnl    = sum(t.net_pnl or 0.0 for t in engine_closed)
    print(f"  engine: {len(engine_closed)} closed trades | net P&L ${engine_pnl:,.2f}")

    # ── Step 2: PaperTrader with ReplayContextFeed ────────────────────────────
    print("\nStep 2: Running PaperTrader (ReplayContextFeed + MockBroker zero-slippage)...")

    du     = build_decision_unit(config)
    broker = MockBroker(slippage_pct=0.0, partial_fill_rate=0.0, reject_rate=0.0)
    recon  = ReconciliationLog(out_dir=os.path.join(_SCRIPT_DIR, "..", "data", "recon_verify"))
    trader = PaperTrader(
        decision_unit=du,
        broker=broker,
        recon=recon,
        account_equity=config.account_equity,
        live_mode=False,
        kill_switch_pct=1.0,    # disable kill-switch; engine handles its own CB
        cost_fn=engine_cost_fn if args.costs else None,
        allow_swing_hold=config.allow_swing_hold,
        max_hold_days=config.max_hold_days,
    )
    feed = ReplayContextFeed(
        market_data=market_data,
        config=config,
        daily_data=daily_data,
    )
    trader.run(feed)
    paper_trades = trader.closed_trades
    paper_pnl    = sum(t.net_pnl or 0.0 for t in paper_trades)
    print(f"  paper:  {len(paper_trades)} closed trades | net P&L ${paper_pnl:,.2f}")

    # ── Step 3: Compare ───────────────────────────────────────────────────────
    print("\nComparing trade logs field-by-field...")
    mismatches = compare_trade_logs(engine_closed, paper_trades)

    print("-" * 60)
    if not mismatches:
        print(f"TRADE LOG MATCH: {len(engine_closed)}/{len(engine_closed)} trades identical")
        if not args.costs:
            print("  (costs disabled: net_pnl == gross_pnl; re-run with --costs to verify cost model)")
        else:
            print("  (costs enabled: net_pnl verified to the cent)")
    else:
        from collections import defaultdict

        missing  = [m for m in mismatches if m["type"] == "MISSING_IN_PAPER"]
        extra    = [m for m in mismatches if m["type"] == "EXTRA_IN_PAPER"]
        field_mm = [m for m in mismatches if m["type"] == "FIELD_MISMATCH"]

        n_engine = len(engine_closed)
        n_paper  = len(paper_trades)
        if n_engine != n_paper:
            print(f"  Count: engine={n_engine}  paper={n_paper}")

        if missing:
            print(f"\n  MISSING in paper ({len(missing)} trades — in engine but not paper):")
            for m in missing[:10]:
                print(f"    {m['ticker']:6s} {m['strategy']:12s} entry={m['entry_time']}")
            if len(missing) > 10:
                print(f"    ... and {len(missing)-10} more")

        if extra:
            print(f"\n  EXTRA in paper ({len(extra)} trades — in paper but not engine):")
            for m in extra[:10]:
                print(f"    {m['ticker']:6s} {m['strategy']:12s} entry={m['entry_time']}")
            if len(extra) > 10:
                print(f"    ... and {len(extra)-10} more")

        if field_mm:
            by_trade: Dict[tuple, List[dict]] = defaultdict(list)
            for m in field_mm:
                by_trade[m["key"]].append(m)
            print(f"\n  {len(by_trade)} matched trade(s) with field diffs "
                  f"({len(field_mm)} total):")
            for key in sorted(by_trade)[:10]:
                mm_list = by_trade[key]
                first = mm_list[0]
                print(f"\n    {first['ticker']} {first['strategy']} entry={first['entry_time']}")
                for m in mm_list:
                    print(f"      {m['field']:20s}  engine={m['engine']!r:30}  paper={m['paper']!r}")
            if len(by_trade) > 10:
                print(f"\n    ... and {len(by_trade)-10} more")

        print("\nFix pipeline differences then re-run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
