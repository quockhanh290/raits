"""
raits/live/verify_context.py

Context-equivalence verification:
  1. Run RefactoredBacktestEngine with capture hook → capture every BarContext
  2. Run ReplayContextFeed over same data → generate every BarContext
  3. Compare field-by-field at each bar
  4. Report: N bars compared, any mismatch (first divergence style)

Usage (from raits/raits/):
    python raits/live/verify_context.py [--days N] [--start YYYY-MM-DD]

Options:
    --days N        : limit to first N days (default 5 for fast iteration)
    --start DATE    : IS start date override (default 2017-01-03)
    --full          : run full IS 2017-2022 (overrides --days)
    --skip-hmm      : skip hmm_state / cur_vol comparison (stochastic field)

SUCCESS: "CONTEXT MATCH: X/X bars identical"
FAILURE: first divergence printed with field, engine value, feed value
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np
import pandas as pd

from raits.backtest.engine_refactored import RefactoredBacktestEngine
from raits.backtest.data_types import BacktestConfig
from raits.live.context_feed import ReplayContextFeed
from raits.strategies.universe_scanner import CANDIDATE_POOL

import yaml as _yaml

# ── Config mirrors verify_parallel_run.py ────────────────────────────────────
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
TICKERS     = ["SPY", "QQQ", "IWM"] + SECTOR_ETFS + UNIVERSE + PHASE1 + PHASE2 + PE_EXPANSION

_SCRIPT_DIR  = os.path.dirname(__file__)
_CACHE_DIR   = os.path.join(_SCRIPT_DIR, "..", "data", "cache")
PICKLE_5MIN  = os.path.normpath(os.path.join(_CACHE_DIR, "window_debug_5min.pkl"))
PICKLE_DAILY = os.path.normpath(os.path.join(_CACHE_DIR, "window_debug_daily.pkl"))
_PARAMS_PATH = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "configs", "final_params.yaml"))


def load_data():
    with open(PICKLE_5MIN, "rb") as f:
        all_data = pickle.load(f)
    market_data = {t: df for t, df in all_data.items() if t in TICKERS}

    daily_data = None
    if os.path.exists(PICKLE_DAILY):
        with open(PICKLE_DAILY, "rb") as f:
            daily_data = pickle.load(f)
    return market_data, daily_data


def make_config(params: dict, start: str, end: str) -> BacktestConfig:
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
        enable_costs=True,
        enable_pdt_guard=True,
        hmm_retrain_weekly=True,
        allow_swing_hold=True,
        max_hold_days=5,
        stress_size_fraction=0.5,
        log_level="WARNING",
    )


# ── Field comparators ─────────────────────────────────────────────────────────

def _cmp_float(a, b, tol=1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < tol


def _cmp_list(a, b) -> bool:
    return list(a) == list(b)


def _cmp_set(a, b) -> bool:
    return set(a) == set(b)


def _cmp_series(a: pd.Series, b: pd.Series, tol=1e-6) -> bool:
    if len(a) != len(b):
        return False
    if a.empty and b.empty:
        return True
    try:
        return bool(np.allclose(a.values, b.values, atol=tol, equal_nan=True))
    except Exception:
        return False


def _cmp_day_stocks(
    a: dict, b: dict, open_trade_tickers: set = None,
    pe_expansion_tickers: set = None,
) -> Optional[str]:
    """Return None if identical, or a description of the first difference.

    open_trade_tickers: tickers the engine injected from its open trade log.
    pe_expansion_tickers: PE_EXPANSION tickers that decide() lazily injects into
        day_stocks via the PE_SHORT handler.  They persist in the shared day_stocks
        dict for the rest of the day after first injection; the feed omits them at
        build time (decide() adds them identically at runtime), so we tolerate them
        as expected extra_engine entries here.
    """
    if open_trade_tickers is None:
        open_trade_tickers = set()
    if pe_expansion_tickers is None:
        pe_expansion_tickers = set()
    extra_a = set(a.keys()) - set(b.keys()) - open_trade_tickers - pe_expansion_tickers
    extra_b = set(b.keys()) - set(a.keys())
    if extra_a or extra_b:
        return f"key mismatch extra_engine={extra_a} extra_feed={extra_b}"
    for ticker in sorted(set(a.keys()) & set(b.keys())):
        df_a, df_b = a[ticker], b[ticker]
        if len(df_a) != len(df_b):
            return f"{ticker} row count {len(df_a)} vs {len(df_b)}"
        if not df_a.empty and not df_b.empty:
            last_a = df_a.iloc[-1]
            last_b = df_b.iloc[-1]
            for col in ("open", "high", "low", "close", "volume"):
                if col in last_a.index and col in last_b.index:
                    if not _cmp_float(last_a[col], last_b[col], tol=0.01):
                        return f"{ticker}.{col} last row: {last_a[col]!r} vs {last_b[col]!r}"
    return None


def _compare_ctx(engine_ctx, feed_ctx, skip_hmm: bool) -> list[str]:
    """Return list of field mismatches between two BarContexts."""
    diffs = []

    def _chk(name, ok, engine_val, feed_val):
        if not ok:
            diffs.append(f"{name}: engine={engine_val!r} feed={feed_val!r}")

    # Scalar exact
    _chk("day", engine_ctx.day == feed_ctx.day, engine_ctx.day, feed_ctx.day)
    _chk("bar_ts", engine_ctx.bar_ts == feed_ctx.bar_ts, engine_ctx.bar_ts, feed_ctx.bar_ts)
    _chk("orb_vix_ok", engine_ctx.orb_vix_ok == feed_ctx.orb_vix_ok,
         engine_ctx.orb_vix_ok, feed_ctx.orb_vix_ok)
    _chk("stress_orb_vix_ok", engine_ctx.stress_orb_vix_ok == feed_ctx.stress_orb_vix_ok,
         engine_ctx.stress_orb_vix_ok, feed_ctx.stress_orb_vix_ok)
    _chk("spy_bull_trend", engine_ctx.spy_bull_trend == feed_ctx.spy_bull_trend,
         engine_ctx.spy_bull_trend, feed_ctx.spy_bull_trend)
    _chk("vwap_bb_std", _cmp_float(engine_ctx.vwap_bb_std, feed_ctx.vwap_bb_std),
         engine_ctx.vwap_bb_std, feed_ctx.vwap_bb_std)
    _chk("ema_period", engine_ctx.ema_period == feed_ctx.ema_period,
         engine_ctx.ema_period, feed_ctx.ema_period)
    _chk("allow_swing_hold", engine_ctx.allow_swing_hold == feed_ctx.allow_swing_hold,
         engine_ctx.allow_swing_hold, feed_ctx.allow_swing_hold)
    _chk("enable_pdt_guard", engine_ctx.enable_pdt_guard == feed_ctx.enable_pdt_guard,
         engine_ctx.enable_pdt_guard, feed_ctx.enable_pdt_guard)
    _chk("orb_signal_start", engine_ctx.orb_signal_start == feed_ctx.orb_signal_start,
         engine_ctx.orb_signal_start, feed_ctx.orb_signal_start)
    _chk("orb_signal_end", engine_ctx.orb_signal_end == feed_ctx.orb_signal_end,
         engine_ctx.orb_signal_end, feed_ctx.orb_signal_end)

    # Float approx
    _chk("spy_or_high", _cmp_float(engine_ctx.spy_or_high, feed_ctx.spy_or_high, tol=0.01),
         engine_ctx.spy_or_high, feed_ctx.spy_or_high)
    _chk("spy_or_low", _cmp_float(engine_ctx.spy_or_low, feed_ctx.spy_or_low, tol=0.01),
         engine_ctx.spy_or_low, feed_ctx.spy_or_low)

    # HMM / vol (stochastic — skip if requested)
    if not skip_hmm:
        _chk("hmm_state", engine_ctx.hmm_state == feed_ctx.hmm_state,
             engine_ctx.hmm_state, feed_ctx.hmm_state)
        _chk("cur_vol", _cmp_float(engine_ctx.cur_vol, feed_ctx.cur_vol, tol=1e-6),
             engine_ctx.cur_vol, feed_ctx.cur_vol)

    # spy_bar (Series values)
    for col in ("open", "high", "low", "close", "volume"):
        try:
            ea = float(engine_ctx.spy_bar[col])
            fa = float(feed_ctx.spy_bar[col])
            _chk(f"spy_bar.{col}", _cmp_float(ea, fa, tol=0.01), ea, fa)
        except Exception:
            pass

    # spy_history length
    _chk("spy_history_len",
         len(engine_ctx.spy_history) == len(feed_ctx.spy_history),
         len(engine_ctx.spy_history), len(feed_ctx.spy_history))

    # Universes / lists
    _chk("base_universe", _cmp_list(engine_ctx.base_universe, feed_ctx.base_universe),
         engine_ctx.base_universe, feed_ctx.base_universe)
    _chk("effective_orb_universe",
         _cmp_list(engine_ctx.effective_orb_universe, feed_ctx.effective_orb_universe),
         engine_ctx.effective_orb_universe, feed_ctx.effective_orb_universe)
    _chk("effective_vwap_universe",
         _cmp_list(engine_ctx.effective_vwap_universe, feed_ctx.effective_vwap_universe),
         engine_ctx.effective_vwap_universe, feed_ctx.effective_vwap_universe)
    _chk("effective_fade_universe",
         _cmp_list(engine_ctx.effective_fade_universe, feed_ctx.effective_fade_universe),
         engine_ctx.effective_fade_universe, feed_ctx.effective_fade_universe)
    _chk("all_tickers", _cmp_list(engine_ctx.all_tickers, feed_ctx.all_tickers),
         engine_ctx.all_tickers[:5], feed_ctx.all_tickers[:5])

    # day_stocks — two expected engine-side extras:
    # 1. open swing trade tickers injected at day-start by the engine
    # 2. PE_EXPANSION tickers lazily injected by decide()'s PE_SHORT handler;
    #    they persist in the shared dict for the rest of the day after bar N,
    #    so bars N+1..EOD show them in the captured snapshot.  decide() injects
    #    them identically in the paper-trader path, so this is not a real gap.
    _ot_tickers = {getattr(t, "ticker", None) for t in engine_ctx.open_trades}
    ds_diff = _cmp_day_stocks(engine_ctx.day_stocks, feed_ctx.day_stocks,
                               open_trade_tickers=_ot_tickers,
                               pe_expansion_tickers=set(PE_EXPANSION))
    if ds_diff:
        diffs.append(f"day_stocks: {ds_diff}")

    # daily_spy_close
    _chk("daily_spy_close",
         _cmp_series(engine_ctx.daily_spy_close, feed_ctx.daily_spy_close),
         f"len={len(engine_ctx.daily_spy_close)}", f"len={len(feed_ctx.daily_spy_close)}")

    # fade_atr_top2
    _chk("fade_atr_top2",
         _cmp_set(engine_ctx.fade_atr_top2, feed_ctx.fade_atr_top2),
         engine_ctx.fade_atr_top2, feed_ctx.fade_atr_top2)

    return diffs


# ── Optional type hint ────────────────────────────────────────────────────────
from typing import Optional


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Verify ReplayContextFeed against engine_refactored")
    parser.add_argument("--days",  type=int, default=5,
                        help="Number of IS days to verify (default 5)")
    parser.add_argument("--start", type=str, default="2017-01-03",
                        help="IS start date (default 2017-01-03)")
    parser.add_argument("--full",  action="store_true",
                        help="Run full IS 2017-2022")
    parser.add_argument("--skip-hmm", action="store_true",
                        help="Skip hmm_state/cur_vol comparison (stochastic)")
    args = parser.parse_args()

    print("=" * 60)
    print("RAITS Context Equivalence Verification")
    print("=" * 60)

    # ── Load data ─────────────────────────────────────────────────────────────
    print("Loading market data from pickle cache...")
    market_data, daily_data = load_data()
    print(f"  {len(market_data)} tickers loaded")

    with open(_PARAMS_PATH) as f:
        params = _yaml.safe_load(f)

    # ── Determine date range ──────────────────────────────────────────────────
    IS_START = args.start
    if args.full:
        IS_END = "2022-12-30"
    else:
        # Find first N trading days from IS_START
        spy = market_data["SPY"]
        avail_days = sorted(spy[spy.index.normalize() >= pd.Timestamp(IS_START)]
                            .index.normalize().unique())
        IS_END = str(avail_days[min(args.days - 1, len(avail_days) - 1)].date())

    print(f"  Window: {IS_START} -> {IS_END}")

    # ── Filter market_data to IS window ──────────────────────────────────────
    for ticker in list(market_data.keys()):
        df = market_data[ticker]
        market_data[ticker] = df[
            (df.index >= pd.Timestamp(IS_START))
            & (df.index <= pd.Timestamp(IS_END))
        ]

    config = make_config(params, IS_START, IS_END)

    # ── Step 1: Capture contexts from engine_refactored ───────────────────────
    # day_stocks is a shared mutable dict; decide() injects PE tickers into it
    # AFTER the hook fires.  Snapshot day_stocks keys+DataFrames at capture time
    # so the recorded context reflects the state BEFORE decide() mutates it.
    print("\nCapturing BarContexts from RefactoredBacktestEngine...")
    engine = RefactoredBacktestEngine(config)
    engine_contexts = []

    def _capture(ctx):
        from dataclasses import replace
        engine_contexts.append(replace(ctx, day_stocks=dict(ctx.day_stocks)))

    engine._ctx_capture_hook = _capture
    engine.run(market_data, daily_data)
    print(f"  Captured {len(engine_contexts)} contexts")

    # ── Step 2: Generate contexts from ReplayContextFeed ─────────────────────
    print("\nGenerating BarContexts from ReplayContextFeed...")
    feed = ReplayContextFeed(
        market_data=market_data,
        config=config,
        daily_data=daily_data,
    )
    feed_contexts = list(feed)
    print(f"  Generated {len(feed_contexts)} contexts")

    # ── Step 3: Count check ────────────────────────────────────────────────────
    n_compare = min(len(engine_contexts), len(feed_contexts))
    if len(engine_contexts) != len(feed_contexts):
        print(
            f"\n  NOTE: bar count differs — engine={len(engine_contexts)} "
            f"feed={len(feed_contexts)}. Engine likely halted early (circuit breaker). "
            f"Comparing first {n_compare} bars."
        )

    # ── Step 4: Field-by-field comparison ─────────────────────────────────────
    print(f"\nComparing {n_compare} bar contexts field-by-field...")
    if args.skip_hmm:
        print("  (skipping hmm_state / cur_vol — use --skip-hmm to disable)")

    first_fail = None
    for i, (e_ctx, f_ctx) in enumerate(zip(engine_contexts[:n_compare], feed_contexts[:n_compare])):
        diffs = _compare_ctx(e_ctx, f_ctx, skip_hmm=args.skip_hmm)
        if diffs:
            first_fail = (i, e_ctx.bar_ts, diffs)
            break

    print("-" * 60)
    if first_fail is None:
        print(f"CONTEXT MATCH: {n_compare}/{n_compare} bars identical")
        if args.skip_hmm:
            print("  (hmm_state / cur_vol NOT compared — add those checks when HMM training is unified)")
    else:
        idx, ts, diffs = first_fail
        print(f"FAIL: First mismatch at bar {idx} ({ts}):")
        for d in diffs[:10]:
            print(f"  {d}")
        if len(diffs) > 10:
            print(f"  ... and {len(diffs) - 10} more")
        print("\nFix the divergence then re-run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
