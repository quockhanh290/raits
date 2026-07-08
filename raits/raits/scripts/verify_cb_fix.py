"""
verify_cb_fix.py
----------------
Verify the corrected CB semantics in BOTH engines (ORIG + REFAC) and
measure the new baseline.

Changes verified:
  - daily-drawdown-CB exits NOW count toward consecutive-loss streak (both engines)
  - SAFETY_MODE exits NO LONGER count toward streak in REFAC (was wrong)
  - EOD exits unchanged (never counted, still don't)

Expected result:
  - ORIG == REFAC to the cent (both now identical CB semantics)
  - New trade count may differ from old 604 (daily-CB counting is new for both)

Usage:
    cd d:\\raits\\raits
    python raits/scripts/verify_cb_fix.py

Output:
  - ORIG vs REFAC comparison (must be IDENTICAL)
  - Daily-CB event list (days where CB fired and how many positions closed)
  - Comparison vs old baseline (results_20260624_200216.pkl)
  - Saves new baseline: data/cache/verify_cb_fixed_baseline.pkl (if ORIG==REFAC)
"""

import sys, os, pickle, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import warnings
warnings.filterwarnings("ignore")

import pandas as pd

from raits.backtest.engine import BacktestEngine
from raits.backtest.engine_refactored import RefactoredBacktestEngine
from raits.backtest.data_types import BacktestConfig
from raits.strategies.universe_scanner import CANDIDATE_POOL

# ── Config (must match locked IS baseline) ───────────────────────────────────
UNIVERSE     = ["TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL"]
PHASE1       = ["INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
                "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX",
                "CSCO","GS","CRM","JPM"]
PHASE2       = ["MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM"]
PE_EXPANSION = ["PFE","MRK","LLY","ABBV","JNJ","BMY","BAC","WFC","C",
                "WMT","TGT","HD","LOW","MCD","NKE","PG","KO","PEP",
                "CAT","DE","BA","GE","PYPL","PANW","NOW"]
SECTOR_ETFS  = ["XLF","XLE","XLV","XLU","XLI","XLK","XLP","XLB","XLY","GLD"]
TICKERS      = ["SPY","QQQ","IWM"] + SECTOR_ETFS + UNIVERSE + PHASE1 + PHASE2 + PE_EXPANSION

IS_START = "2017-01-03"
IS_END   = "2022-12-30"

_BASE = os.path.join(os.path.dirname(__file__), "..", "..")
PICKLE_5MIN  = os.path.join(_BASE, "data", "cache", "window_debug_5min.pkl")
PICKLE_DAILY = os.path.join(_BASE, "data", "cache", "window_debug_daily.pkl")
OLD_BASELINE = os.path.join(_BASE, "data", "cache", "results_20260624_200216.pkl")
NEW_BASELINE = os.path.join(_BASE, "data", "cache", "verify_cb_fixed_baseline.pkl")

import yaml as _yaml
_PARAMS_PATH = os.path.join(_BASE, "configs", "final_params.yaml")
with open(_PARAMS_PATH) as _f:
    _params = _yaml.safe_load(_f)

COMPARED_FIELDS = [
    "ticker", "strategy", "direction",
    "entry_time", "entry_price", "shares",
    "exit_time", "exit_price", "exit_reason",
    "stop", "target", "hmm_state",
    "gross_pnl", "net_pnl",
]


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


# ── Instrumented ORIG: intercepts _close_all to capture daily-CB events ──────

class InstrumentedOrig(BacktestEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.daily_cb_events = []   # list of (date, n_trades_closed, sum_pnl)

    def _close_all(self, timestamp, day_stocks, reason,
                   skip_swing=False, skip_tf=False,
                   circuit_breakers=None, update_cb=False):
        if reason == "CIRCUIT_BREAKER":
            open_before = len(list(self.trade_log.open_trades))
            super()._close_all(timestamp, day_stocks, reason,
                                skip_swing=skip_swing, skip_tf=skip_tf,
                                circuit_breakers=circuit_breakers, update_cb=update_cb)
            self.daily_cb_events.append({
                "date": str(pd.Timestamp(timestamp).date()),
                "n_closed": open_before,
            })
        else:
            super()._close_all(timestamp, day_stocks, reason,
                                skip_swing=skip_swing, skip_tf=skip_tf,
                                circuit_breakers=circuit_breakers, update_cb=update_cb)


def compare_trade_logs(orig_trades, refac_trades):
    mismatches = []
    if len(orig_trades) != len(refac_trades):
        mismatches.append({"type": "COUNT", "orig": len(orig_trades), "refac": len(refac_trades)})
        orig_keys  = {(str(t.entry_time), t.ticker, t.strategy): t for t in orig_trades}
        refac_keys = {(str(t.entry_time), t.ticker, t.strategy): t for t in refac_trades}
        only_orig  = sorted(set(orig_keys) - set(refac_keys))
        only_refac = sorted(set(refac_keys) - set(orig_keys))
        if only_orig:
            mismatches.append({"type": "ONLY_IN_ORIG",  "trades": only_orig})
        if only_refac:
            mismatches.append({"type": "ONLY_IN_REFAC", "trades": only_refac})
        return mismatches
    for i, (a, b) in enumerate(zip(orig_trades, refac_trades)):
        for field in COMPARED_FIELDS:
            va, vb = getattr(a, field, None), getattr(b, field, None)
            match = (abs(va - vb) < 0.01) if isinstance(va, float) and isinstance(vb, float) else (va == vb)
            if not match:
                mismatches.append({
                    "type": "FIELD", "idx": i,
                    "ticker": a.ticker, "strategy": a.strategy, "entry_time": str(a.entry_time),
                    "field": field, "orig": va, "refac": vb,
                })
    return mismatches


def main():
    print("=" * 65)
    print("RAITS CB-Fix Verification — IS 2017-2022 (window_debug data)")
    print("=" * 65)

    # Load data
    print("\nLoading 5-min data...")
    with open(PICKLE_5MIN, "rb") as f:
        all_data = pickle.load(f)
    market_data = {t: df for t, df in all_data.items() if t in TICKERS}
    for t in list(market_data):
        df = market_data[t]
        market_data[t] = df[(df.index >= pd.Timestamp(IS_START)) &
                            (df.index <= pd.Timestamp(IS_END))]
    print(f"  {len(market_data)} tickers loaded")

    print("Loading daily data...")
    with open(PICKLE_DAILY, "rb") as f:
        daily_data = pickle.load(f)

    config = make_config()

    # Run ORIG (instrumented)
    print("\nRunning BacktestEngine (ORIG, corrected CB)...")
    t0 = time.time()
    orig_engine = InstrumentedOrig(config)
    orig_result = orig_engine.run(market_data, daily_data)
    orig_trades = orig_result.trade_log
    orig_pnl    = sum(t.net_pnl or 0.0 for t in orig_trades)
    print(f"  ORIG: {len(orig_trades)} trades | P&L ${orig_pnl:,.2f} | {time.time()-t0:.1f}s")

    # Run REFAC
    print("\nRunning RefactoredBacktestEngine (REFAC, corrected CB)...")
    t0 = time.time()
    refac_engine  = RefactoredBacktestEngine(config)
    refac_result  = refac_engine.run(market_data, daily_data)
    refac_trades  = refac_result.trade_log
    refac_pnl     = sum(t.net_pnl or 0.0 for t in refac_trades)
    print(f"  REFAC: {len(refac_trades)} trades | P&L ${refac_pnl:,.2f} | {time.time()-t0:.1f}s")

    # ── Daily-CB events ──────────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("DAILY-CB EVENTS (>4% daily loss → positions closed + now count toward streak)")
    if orig_engine.daily_cb_events:
        for ev in orig_engine.daily_cb_events:
            print(f"  {ev['date']}  {ev['n_closed']} positions closed")
        print(f"  Total: {len(orig_engine.daily_cb_events)} daily-CB days, "
              f"{sum(e['n_closed'] for e in orig_engine.daily_cb_events)} positions closed")
    else:
        print("  (none — daily-CB never fired in IS 2017-2022)")

    # ── ORIG vs REFAC comparison ─────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("ORIG vs REFAC COMPARISON")
    mismatches = compare_trade_logs(orig_trades, refac_trades)
    if not mismatches:
        print(f"  OK IDENTICAL: {len(orig_trades)} trades matched 100% | P&L diff ${abs(orig_pnl - refac_pnl):.4f}")
    else:
        print(f"  FAIL MISMATCH ({len(mismatches)} issues):")
        for m in mismatches[:20]:
            if m["type"] == "COUNT":
                print(f"    COUNT: ORIG={m['orig']} REFAC={m['refac']}")
            elif m["type"] in ("ONLY_IN_ORIG", "ONLY_IN_REFAC"):
                print(f"    {m['type']}:")
                for k in m["trades"][:5]:
                    print(f"      {k}")
            elif m["type"] == "FIELD":
                print(f"    trade[{m['idx']}] {m['ticker']}/{m['strategy']} @ {m['entry_time']}"
                      f"  {m['field']}: {m['orig']!r} → {m['refac']!r}")

    # ── Comparison vs old baseline ───────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("COMPARISON vs OLD BASELINE (results_20260624_200216.pkl, 604 trades)")
    if os.path.exists(OLD_BASELINE):
        with open(OLD_BASELINE, "rb") as f:
            old_obj = pickle.load(f)
        if hasattr(old_obj, "trade_log"):
            old_trades = old_obj.trade_log
        elif isinstance(old_obj, list):
            old_trades = old_obj
        else:
            old_trades = []
        old_pnl = sum(t.net_pnl or 0.0 for t in old_trades)
        print(f"  Old baseline: {len(old_trades)} trades | P&L ${old_pnl:,.2f}")
        print(f"  New ORIG:     {len(orig_trades)} trades | P&L ${orig_pnl:,.2f}")
        delta_n   = len(orig_trades) - len(old_trades)
        delta_pnl = orig_pnl - old_pnl
        print(f"  Delta: {delta_n:+d} trades, ${delta_pnl:+,.2f} P&L")
        if delta_n != 0:
            # Show which trades are different
            old_keys  = {(str(t.entry_time), t.ticker, t.strategy) for t in old_trades}
            new_keys  = {(str(t.entry_time), t.ticker, t.strategy) for t in orig_trades}
            only_old  = sorted(old_keys - new_keys)
            only_new  = sorted(new_keys - old_keys)
            if only_old:
                print(f"  Blocked by corrected CB (in old, not in new):")
                for k in only_old:
                    pnl_v = next((t.net_pnl for t in old_trades
                                  if str(t.entry_time)==k[0] and t.ticker==k[1] and t.strategy==k[2]), None)
                    print(f"    {k[0]}  {k[1]}  {k[2]}  pnl={pnl_v}")
            if only_new:
                print(f"  Unblocked by corrected CB (in new, not in old):")
                for k in only_new:
                    pnl_v = next((t.net_pnl for t in orig_trades
                                  if str(t.entry_time)==k[0] and t.ticker==k[1] and t.strategy==k[2]), None)
                    print(f"    {k[0]}  {k[1]}  {k[2]}  pnl={pnl_v}")
    else:
        print(f"  Old baseline not found at {OLD_BASELINE}")

    # ── Save new baseline ────────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    if not mismatches:
        with open(NEW_BASELINE, "wb") as f:
            pickle.dump(orig_result, f)
        print(f"NEW BASELINE SAVED: {NEW_BASELINE}")
        print(f"  {len(orig_trades)} trades | P&L ${orig_pnl:,.2f}")
        print(f"  CB semantics: STOP/TARGET/TIME_STOP/daily-CB count; SAFETY_MODE/EOD do NOT count")
        print(f"  Commit this file + note in TASK.md")
    else:
        print("BASELINE NOT SAVED (ORIG != REFAC — fix the divergence first)")


if __name__ == "__main__":
    main()
