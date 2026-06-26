# Decision Unit — Task 5: Parallel Verification

> **For agentic workers:** Use superpowers:subagent-driven-development to execute.
> Depends on Tasks 3 and 4.

**Goal:** Prove the extraction is correct: run both engines on IS 2017-2022 data with the same config, assert 100% identical trade logs field-by-field. Also test that the comparator CATCHES mismatches (deliberate-mismatch test).

**Files:**
- Create: `raits/raits/tests/decision/test_parallel_run.py`  — pytest tests (fast, uses mock data for mismatch detector)
- Create: `raits/raits/scripts/verify_parallel_run.py`       — real-data verification script

**SUCCESS CRITERION:** 100% field match. Any mismatch = extraction is wrong, fix it before reporting done.

---

## Part A: Comparator + mismatch detector (pytest, fast)

- [ ] **Step 1: Write `raits/raits/tests/decision/test_parallel_run.py`**

```python
"""
tests/decision/test_parallel_run.py
Tests for the trade-log comparator and a fast parallel-run on synthetic data.
"""
import pytest
import pandas as pd
from datetime import datetime
from dataclasses import asdict

from raits.backtest.data_types import Trade, BacktestConfig


# ── Comparator (the actual comparison logic, extracted for reuse in the script) ──

COMPARED_FIELDS = [
    "ticker", "strategy", "direction",
    "entry_time", "entry_price", "shares",
    "exit_time", "exit_price", "exit_reason",
    "stop", "target", "hmm_state",
    "gross_pnl", "net_pnl",
]


def compare_trade_logs(orig_trades, refac_trades):
    """
    Compare two lists of Trade objects field-by-field.
    Returns (mismatches: list[dict], summary: str).
    """
    mismatches = []

    if len(orig_trades) != len(refac_trades):
        mismatches.append({
            "type": "TRADE_COUNT",
            "original": len(orig_trades),
            "refactored": len(refac_trades),
            "diff": f"count differs: {len(orig_trades)} vs {len(refac_trades)}",
        })
        return mismatches, _summary(mismatches, orig_trades, refac_trades)

    for i, (a, b) in enumerate(zip(orig_trades, refac_trades)):
        for field in COMPARED_FIELDS:
            va = getattr(a, field, None)
            vb = getattr(b, field, None)
            if isinstance(va, float) and isinstance(vb, float):
                match = abs(va - vb) < 0.01  # cent tolerance
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

    return mismatches, _summary(mismatches, orig_trades, refac_trades)


def _summary(mismatches, orig, refac):
    if not mismatches:
        return f"✓ IDENTICAL: {len(orig)} trades matched 100%"
    count_mm = [m for m in mismatches if m["type"] == "TRADE_COUNT"]
    field_mm = [m for m in mismatches if m["type"] == "FIELD_MISMATCH"]
    lines = [f"✗ MISMATCH: {len(orig)} original vs {len(refac)} refactored trades"]
    if count_mm:
        lines.append(f"  Count mismatch: {count_mm[0]['diff']}")
    if field_mm:
        lines.append(f"  Field mismatches: {len(field_mm)}")
        for m in field_mm[:10]:  # show first 10
            lines.append(
                f"    trade[{m['trade_index']}] {m['ticker']}/{m['strategy']} "
                f"@ {m['entry_time']}  field={m['field']}: "
                f"{m['original']!r} → {m['refactored']!r}"
            )
    return "\n".join(lines)


# ── Helper: build a synthetic Trade ──────────────────────────────────────────

def _make_trade(i=0, **kwargs) -> Trade:
    defaults = dict(
        trade_id=f"T{i}",
        ticker="AAPL",
        strategy="ORB",
        direction="LONG",
        entry_time=pd.Timestamp(f"2021-06-0{i+1} 09:50:00"),
        entry_price=150.0 + i,
        shares=100,
        stop=148.0 + i,
        target=154.0 + i,
        hmm_state="Normal",
        limiting_factor="KELLY",
        exit_time=pd.Timestamp(f"2021-06-0{i+1} 14:00:00"),
        exit_price=153.0 + i,
        exit_reason="TARGET_HIT",
        gross_pnl=300.0,
        total_costs=2.0,
        net_pnl=298.0,
    )
    defaults.update(kwargs)
    return Trade(**defaults)


# ── Tests: comparator ─────────────────────────────────────────────────────────

class TestComparator:
    def test_identical_logs_returns_no_mismatches(self):
        trades = [_make_trade(i) for i in range(3)]
        mm, summary = compare_trade_logs(trades, trades)
        assert mm == [], summary

    def test_detects_count_mismatch(self):
        orig   = [_make_trade(0), _make_trade(1)]
        refac  = [_make_trade(0)]
        mm, summary = compare_trade_logs(orig, refac)
        assert any(m["type"] == "TRADE_COUNT" for m in mm)
        assert "count differs" in summary

    def test_detects_ticker_mismatch(self):
        orig  = [_make_trade(0, ticker="AAPL")]
        refac = [_make_trade(0, ticker="MSFT")]
        mm, _ = compare_trade_logs(orig, refac)
        assert any(m.get("field") == "ticker" for m in mm)

    def test_detects_entry_price_mismatch(self):
        orig  = [_make_trade(0, entry_price=150.00)]
        refac = [_make_trade(0, entry_price=150.05)]   # >$0.01 diff
        mm, _ = compare_trade_logs(orig, refac)
        assert any(m.get("field") == "entry_price" for m in mm)

    def test_ignores_cent_rounding(self):
        """Floating-point differences < $0.01 are acceptable."""
        orig  = [_make_trade(0, net_pnl=298.001)]
        refac = [_make_trade(0, net_pnl=298.000)]
        mm, _ = compare_trade_logs(orig, refac)
        assert mm == []

    def test_detects_shares_mismatch(self):
        orig  = [_make_trade(0, shares=100)]
        refac = [_make_trade(0, shares=99)]
        mm, _ = compare_trade_logs(orig, refac)
        assert any(m.get("field") == "shares" for m in mm)

    def test_detects_exit_reason_mismatch(self):
        orig  = [_make_trade(0, exit_reason="TARGET_HIT")]
        refac = [_make_trade(0, exit_reason="STOP_HIT")]
        mm, _ = compare_trade_logs(orig, refac)
        assert any(m.get("field") == "exit_reason" for m in mm)

    def test_summary_shows_field_diffs(self):
        orig  = [_make_trade(0, exit_reason="TARGET_HIT", net_pnl=298.0)]
        refac = [_make_trade(0, exit_reason="STOP_HIT",   net_pnl=-52.0)]
        mm, summary = compare_trade_logs(orig, refac)
        assert "MISMATCH" in summary
        assert "exit_reason" in summary or "net_pnl" in summary
```

- [ ] **Step 2: Run pytest tests**
```
cd d:\raits\raits
pytest tests/decision/test_parallel_run.py -v
```
Expected: all PASS.

---

## Part B: Real-data parallel verification script

- [ ] **Step 3: Write `raits/raits/scripts/verify_parallel_run.py`**

```python
"""
scripts/verify_parallel_run.py
-------------------------------
Parallel-run verification: run BacktestEngine (original) and
RefactoredBacktestEngine on the same IS 2017-2022 data and assert
100% identical trade logs.

Usage:
    cd d:\raits\raits
    python raits/scripts/verify_parallel_run.py

SUCCESS: "✓ IDENTICAL: N trades matched 100%"
FAILURE: diff printed with every mismatched field
"""

import sys, os, pickle, time
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
        orb_range_minutes=15,
        vwap_bb_std=2.0,
        ema_period=30,
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


def compare_trade_logs(orig_trades, refac_trades):
    mismatches = []
    if len(orig_trades) != len(refac_trades):
        mismatches.append({
            "type": "TRADE_COUNT",
            "diff": f"count {len(orig_trades)} vs {len(refac_trades)}",
        })
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

    orig_result   = run_engine(BacktestEngine,            market_data, daily_data, config, "BacktestEngine (original)")
    refac_result  = run_engine(RefactoredBacktestEngine,  market_data, daily_data, config, "RefactoredBacktestEngine")

    orig_trades  = orig_result.trade_log
    refac_trades = refac_result.trade_log

    print(f"\n{'─'*60}")
    print("COMPARISON")
    print(f"  Original trades:   {len(orig_trades)}")
    print(f"  Refactored trades: {len(refac_trades)}")

    mismatches = compare_trade_logs(orig_trades, refac_trades)

    if not mismatches:
        print(f"\n✓ IDENTICAL: {len(orig_trades)} trades matched 100%")
        # Aggregate metrics
        def metrics(result):
            trades = result.trade_log
            pnl   = sum(t.net_pnl or 0.0 for t in trades)
            return len(trades), pnl
        n_o, p_o = metrics(orig_result)
        n_r, p_r = metrics(refac_result)
        print(f"\nAggregate metrics:")
        print(f"  Original:   {n_o} trades, P&L ${p_o:,.2f}")
        print(f"  Refactored: {n_r} trades, P&L ${p_r:,.2f}")
        diff_pnl = abs(p_o - p_r)
        if diff_pnl < 1.0:
            print(f"  P&L diff: ${diff_pnl:.4f} ✓ (< $1)")
        else:
            print(f"  ✗ P&L diff: ${diff_pnl:.4f} (unexpected)")
    else:
        count_mm = [m for m in mismatches if m["type"] == "TRADE_COUNT"]
        field_mm = [m for m in mismatches if m["type"] == "FIELD_MISMATCH"]
        print(f"\n✗ MISMATCH DETECTED")
        if count_mm:
            print(f"  Count: {count_mm[0]['diff']}")
        if field_mm:
            print(f"  Field mismatches: {len(field_mm)}")
            for m in field_mm[:20]:
                print(
                    f"    trade[{m['trade_index']}] {m['ticker']}/{m['strategy']} "
                    f"@ {m['entry_time']}  "
                    f"{m['field']}: {m['original']!r} → {m['refactored']!r}"
                )
            if len(field_mm) > 20:
                print(f"    ... and {len(field_mm) - 20} more")
        print("\n  → Extraction is WRONG. Fix DecisionUnit before declaring success.")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run verification — must exit 0**
```
cd d:\raits\raits
python raits/scripts/verify_parallel_run.py
```

Expected output:
```
✓ IDENTICAL: NNNN trades matched 100%
Aggregate metrics:
  Original:   NNNN trades, P&L $XX,XXX.XX
  Refactored: NNNN trades, P&L $XX,XXX.XX
  P&L diff: $0.0000 ✓ (< $1)
```

If any mismatch is reported, investigate the diff and fix `decision_unit.py` or `engine_refactored.py`. Do NOT declare success until all fields match 100%.

- [ ] **Step 5: Verify engine.py is unchanged**
```
cd d:\raits
git diff HEAD raits/raits/backtest/engine.py
```
Expected: no output (no changes).

- [ ] **Step 6: Commit**
```
git add raits/tests/decision/test_parallel_run.py raits/scripts/verify_parallel_run.py
git commit -m "feat: parallel-run verification proves DecisionUnit is behaviorally identical to BacktestEngine"
```

---

## Post-verification checklist

After `verify_parallel_run.py` exits 0:

1. Paste into this chat: trade count, P&L diff, and "✓ IDENTICAL" line
2. Confirm `git diff HEAD raits/raits/backtest/engine.py` shows no changes
3. Run full test suite: `pytest raits/tests/ -v`
4. Update TASK.md with the new `raits/decision/` module and verification result
