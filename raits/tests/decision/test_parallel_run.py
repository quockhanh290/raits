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
