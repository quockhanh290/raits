"""
global_index/test_ibkr_injection.py
=====================================
Injection tests verifying IBKRBroker satisfies three mandatory pre-live specs:

  C3: fetch_bars sorts by timestamp (out-of-order IBKR bars -> correct order)
  C5: reconcile_positions deduplicates runner.state after reconnect double-count
  C6: fetch_bars lowercases column names (IBKR uppercase OHLCV)

Run from d:\\raits:
    python global_index\\test_ibkr_injection.py

No live IBKR connection required — uses _raw_fetcher injection point.
"""
from __future__ import annotations
import sys, io
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd
import numpy as np

from global_index.ibkr_broker import IBKRBroker
from global_index.broker import Fill
from global_index.live_decision import DecisionState, OpenPos
from global_index.net_exposure_multi import MultiClusterGuard
from global_index.runner import FuturesRunner
from futures.circuit_breaker import CircuitBreaker
from global_index.signal_layer import CLUSTER_SWING

ACCOUNT = 50_000.0
PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str]] = []


def check(name: str, cond: bool, detail: str = ""):
    status = PASS if cond else FAIL
    results.append((name, status))
    mark = "  PASS" if cond else "  FAIL"
    print(f"{mark}  {name}" + (f"  [{detail}]" if detail else ""))
    return cond


# ─────────────────────────────────────────────────────────────────────────────
# C3: fetch_bars sorts by timestamp
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 60)
print("C3: fetch_bars sorts out-of-order bars")
print("=" * 60)

base_ts = pd.Timestamp("2024-03-11 09:30", tz="America/New_York")
timestamps_sorted = pd.date_range(base_ts, periods=20, freq="1min")
# Shuffle: move last 5 bars before first 5 (simulates IBKR backfill out-of-order)
shuffled_idx = list(range(15, 20)) + list(range(0, 15))
timestamps_ooo = timestamps_sorted[shuffled_idx]

raw_ooo = pd.DataFrame({
    "open":  np.random.uniform(4990, 5010, 20),
    "high":  np.random.uniform(5010, 5030, 20),
    "low":   np.random.uniform(4970, 4990, 20),
    "close": np.random.uniform(4990, 5010, 20),
    "volume": np.ones(20) * 100,
}, index=timestamps_ooo)

def raw_fetcher_ooo(inst, through):
    return raw_ooo.copy()

broker_c3 = IBKRBroker(_raw_fetcher=raw_fetcher_ooo)
result = broker_c3.fetch_bars("MES", through=timestamps_sorted[-1])

is_sorted = result.index.is_monotonic_increasing
check("C3.1 output is sorted", is_sorted,
      f"first={result.index[0].time()} last={result.index[-1].time()}")

# Verify it matches the correctly-sorted version
expected_sorted = raw_ooo.sort_index()
expected_sorted = expected_sorted[expected_sorted.index <= pd.Timestamp(timestamps_sorted[-1])]
indices_match = list(result.index) == list(expected_sorted.index)
check("C3.2 sorted order matches expected", indices_match)

# Confirm: unsorted input actually was out of order (test is non-trivial)
input_was_ooo = not raw_ooo.index.is_monotonic_increasing
check("C3.3 confirmed input was out-of-order", input_was_ooo,
      "test would be trivial if input already sorted")

print()


# ─────────────────────────────────────────────────────────────────────────────
# C6: fetch_bars lowercases column names
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 60)
print("C6: fetch_bars lowercases IBKR uppercase columns")
print("=" * 60)

ts_range = pd.date_range("2024-03-11 09:30", periods=10, freq="1min",
                          tz="America/New_York")
raw_upper = pd.DataFrame({
    "OPEN":   np.ones(10) * 5000.0,
    "HIGH":   np.ones(10) * 5010.0,
    "LOW":    np.ones(10) * 4990.0,
    "CLOSE":  np.ones(10) * 5005.0,
    "VOLUME": np.ones(10) * 200.0,
}, index=ts_range)

def raw_fetcher_upper(inst, through):
    return raw_upper.copy()

broker_c6 = IBKRBroker(_raw_fetcher=raw_fetcher_upper)
result_c6 = broker_c6.fetch_bars("MES", through=ts_range[-1])

check("C6.1 columns are all lowercase",
      all(c == c.lower() for c in result_c6.columns),
      f"columns={list(result_c6.columns)}")

check("C6.2 required columns present",
      {"open", "high", "low", "close", "volume"}.issubset(result_c6.columns))

# Confirm: upstream actually had uppercase (test is non-trivial)
check("C6.3 confirmed input had uppercase",
      any(c != c.lower() for c in raw_upper.columns),
      "test would be trivial if input already lowercase")

# Smoke: backtest_swing_tf doesn't crash with these bars (end-to-end C6)
try:
    from futures._validated_core import backtest_swing_tf, _SWING_CACHE
    from global_index._core import FuturesCost as GIFC
    from global_index.regime import RegimeLabels, load_spy_regime

    # Build a minimal multi-day df so ATR series is non-empty
    long_ts = pd.date_range("2022-01-03 09:30", periods=390 * 90, freq="1min",
                             tz="America/New_York")
    rng = np.random.default_rng(42)
    prices = 4000 + np.cumsum(rng.normal(0, 0.5, len(long_ts)))
    df_lower = pd.DataFrame({
        "open":  prices, "high": prices + 1, "low": prices - 1,
        "close": prices, "volume": np.ones(len(long_ts)) * 50,
    }, index=long_ts)
    spy = load_spy_regime("spy_daily.csv")
    labels = RegimeLabels(spy, lag_days=0)
    cost   = GIFC(5.0, 0.25, 0.62, 2.0)
    _SWING_CACHE.clear()
    trades = backtest_swing_tf(df_lower, labels, cost,
                               ema_period=20, chandelier_atr_mult=2.5, max_hold_days=5)
    check("C6.4 backtest_swing_tf runs without crash on lowercased df",
          True, f"trades={len(trades)}")
except Exception as e:
    check("C6.4 backtest_swing_tf runs without crash on lowercased df", False, str(e))

print()


# ─────────────────────────────────────────────────────────────────────────────
# C5: reconcile_positions deduplicates runner.state after reconnect
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 60)
print("C5: reconcile_positions deduplicates after reconnect double-count")
print("=" * 60)

DAY1 = pd.Timestamp("2024-03-11")
DAY2 = pd.Timestamp("2024-03-12")
PNL  = 150.0

class _MinimalBroker:
    """Tiny broker that records orders and accumulates equity for this test."""
    def __init__(self):
        self.orders = []; self._eq = ACCOUNT
    def get_equity(self): return self._eq
    def fetch_bars(self, inst, through): return pd.DataFrame()
    def send_order(self, o):
        self.orders.append(o)
        if o.action == "CLOSE":
            self._eq += o.pnl_sized
        return Fill(o.inst, o.action, o.direction, o.contracts, o.cluster, o.pnl_sized)

ibkr_broker = IBKRBroker(
    _raw_fetcher=lambda inst, through: pd.DataFrame()
)

def signal_open_then_close(day, bars, held):
    if day == DAY1:
        return [dict(inst="MES", direction="LONG", cluster=CLUSTER_SWING,
                     risk_sized=500.0, entry=5000.0, stop=4950.0, pnl_sized=PNL)], []
    pos = held[0] if held else None
    return [], ([pos] if pos else [])

guard  = MultiClusterGuard(account=ACCOUNT)
broker_proxy = _MinimalBroker()
runner = FuturesRunner(broker=broker_proxy, guard=guard,
                       contracts_by_inst={"MES": 1},
                       signal_fn=signal_open_then_close,
                       breaker=CircuitBreaker(account=ACCOUNT))

runner.run_day(DAY1)
n_after_day1 = len(runner.state.open_positions)
check("C5.1 one open position after DAY1", n_after_day1 == 1, f"n={n_after_day1}")

# Simulate reconnect double-count: inject a duplicate OpenPos
orig = runner.state.open_positions[0]
dup  = OpenPos(inst=orig.inst, direction=orig.direction, contracts=orig.contracts,
               risk_dollars=orig.risk_dollars, cluster=orig.cluster,
               entry_day=orig.entry_day, exit_day=orig.exit_day, pnl_sized=orig.pnl_sized)
runner.state.open_positions.append(dup)
n_with_dup = len(runner.state.open_positions)
check("C5.2 duplicate injected", n_with_dup == 2, f"n={n_with_dup}")

# Reconcile via IBKRBroker
n_removed = ibkr_broker.reconcile_positions(runner.state)
n_after_reconcile = len(runner.state.open_positions)
check("C5.3 reconcile removes duplicate",
      n_removed == 1 and n_after_reconcile == 1,
      f"removed={n_removed}  remaining={n_after_reconcile}")

# Verify: now DAY2 sends exactly 1 CLOSE, pnl correct (no doubling)
runner.run_day(DAY2)
close_orders = [o for o in broker_proxy.orders if o.action == "CLOSE"]
residual     = runner.state.open_positions
eq_final     = broker_proxy._eq
check("C5.4 only 1 CLOSE order after reconcile",
      len(close_orders) == 1, f"CLOSE orders={len(close_orders)}")
check("C5.5 no residual positions", len(residual) == 0, f"residual={len(residual)}")
check("C5.6 pnl not doubled",
      abs(eq_final - (ACCOUNT + PNL)) < 0.01,
      f"equity={eq_final:.2f}  expected={ACCOUNT+PNL:.2f}")

# Contrast: WITHOUT reconcile, double-count produces doubled pnl
runner2 = FuturesRunner(broker=_MinimalBroker(), guard=MultiClusterGuard(account=ACCOUNT),
                        contracts_by_inst={"MES": 1},
                        signal_fn=signal_open_then_close,
                        breaker=CircuitBreaker(account=ACCOUNT))
runner2.run_day(DAY1)
orig2 = runner2.state.open_positions[0]
dup2  = OpenPos(inst=orig2.inst, direction=orig2.direction, contracts=orig2.contracts,
                risk_dollars=orig2.risk_dollars, cluster=orig2.cluster,
                entry_day=orig2.entry_day, exit_day=orig2.exit_day, pnl_sized=orig2.pnl_sized)
runner2.state.open_positions.append(dup2)
runner2.run_day(DAY2)
eq_no_reconcile = runner2.broker._eq
check("C5.7 contrast: WITHOUT reconcile pnl IS doubled",
      abs(eq_no_reconcile - (ACCOUNT + 2 * PNL)) < 0.01,
      f"equity_no_reconcile={eq_no_reconcile:.2f}  (expected {ACCOUNT+2*PNL:.2f})")

print()

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 60)
passed = sum(1 for _, s in results if s == PASS)
failed = sum(1 for _, s in results if s == FAIL)
print(f"OVERALL: {passed}/{len(results)} passed  {'ALL PASS' if failed == 0 else f'{failed} FAIL'}")
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
