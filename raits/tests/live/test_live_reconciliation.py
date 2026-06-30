"""
tests/live/test_live_reconciliation.py

Unit tests for ReconciliationLog — slippage math, latency, P&L impact, CSV/JSONL.
"""
import json
import os
import time
import pytest

from raits.live.broker import FillStatus, MockBroker, Order
from raits.live.reconciliation import ReconciliationLog, _make_record


def _order(
    ticker="AAPL",
    side="BUY",
    qty=10,
    limit_price=100.0,
    fill_price=100.0,
    filled_qty=10,
    fill_status=FillStatus.FILLED,
    strategy="ORB",
    hmm_state="Normal",
    fill_latency=0.05,
) -> Order:
    sig_ts = time.time()
    o = Order(
        order_id="t001",
        ticker=ticker,
        side=side,
        qty=qty,
        limit_price=limit_price,
        strategy=strategy,
        hmm_state=hmm_state,
        signal_ts=sig_ts,
    )
    o.fill_status  = fill_status
    o.filled_qty   = filled_qty
    o.fill_price   = fill_price
    o.fill_ts      = sig_ts + fill_latency
    return o


# ── _make_record slippage math ────────────────────────────────────────────────

def test_make_record_zero_slippage():
    o = _order(limit_price=100.0, fill_price=100.0)
    r = _make_record(o)
    assert r.slippage_usd  == pytest.approx(0.0)
    assert r.slippage_pct  == pytest.approx(0.0)


def test_make_record_slippage_buy():
    # BUY filled at 101 vs expected 100 → $10 extra cost (bad, positive)
    o = _order(side="BUY", limit_price=100.0, fill_price=101.0, qty=10, filled_qty=10)
    r = _make_record(o)
    assert r.slippage_usd == pytest.approx(10.0)
    assert r.slippage_pct == pytest.approx(0.01)


def test_make_record_slippage_sell():
    # SELL filled at 99 vs expected 100 → $10 worse outcome (positive cost)
    o = _order(side="SELL", limit_price=100.0, fill_price=99.0, qty=10, filled_qty=10)
    r = _make_record(o)
    assert r.slippage_usd == pytest.approx(10.0)
    assert r.slippage_pct == pytest.approx(0.01)


def test_make_record_partial_fill():
    o = _order(
        side="BUY", qty=10, filled_qty=5,
        limit_price=100.0, fill_price=100.5,
        fill_status=FillStatus.PARTIAL,
    )
    r = _make_record(o)
    # slippage on the 5 filled shares only
    assert r.slippage_usd == pytest.approx(2.5)
    assert r.fill_status == "PARTIAL"
    assert r.filled_qty == 5
    assert r.intended_qty == 10


def test_make_record_rejected():
    o = _order(fill_status=FillStatus.REJECTED, filled_qty=0, fill_price=0.0)
    r = _make_record(o)
    assert r.slippage_usd == pytest.approx(0.0)
    assert r.fill_status == "REJECTED"


def test_make_record_latency():
    sig = time.time()
    o = _order(fill_latency=0.1)
    r = _make_record(o)
    assert r.fill_latency_s == pytest.approx(0.1, abs=0.01)


# ── ReconciliationLog ─────────────────────────────────────────────────────────

@pytest.fixture
def log(tmp_path):
    return ReconciliationLog(out_dir=str(tmp_path))


def test_recon_log_creates_csv_header(tmp_path):
    ReconciliationLog(out_dir=str(tmp_path))
    csv_path = tmp_path / "orders.csv"
    assert csv_path.exists()
    first_line = csv_path.read_text().splitlines()[0]
    assert "slippage_usd" in first_line
    assert "ticker" in first_line


def test_recon_log_record_appends(log, tmp_path):
    log.record(_order())
    log.record(_order(ticker="NVDA"))
    lines = (tmp_path / "orders.csv").read_text().splitlines()
    assert len(lines) == 3  # header + 2 rows


def test_recon_log_jsonl(log, tmp_path):
    log.record(_order())
    lines = (tmp_path / "orders.jsonl").read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["ticker"] == "AAPL"


def test_recon_analyze_empty(log):
    result = log.analyze()
    assert result["total_orders"] == 0


def test_recon_analyze_zero_slippage(log):
    log.record(_order(limit_price=100.0, fill_price=100.0))
    log.record(_order(ticker="NVDA", limit_price=200.0, fill_price=200.0))
    summary = log.analyze()
    assert summary["total_orders"] == 2
    assert summary["filled"] == 2
    assert summary["total_slippage_usd"] == pytest.approx(0.0)
    assert summary["slippage_usd"]["mean"] == pytest.approx(0.0)


def test_recon_analyze_with_slippage(log):
    # 2 orders, $5 each slippage
    log.record(_order(side="BUY", limit_price=100.0, fill_price=100.5, qty=10, filled_qty=10))
    log.record(_order(side="BUY", limit_price=100.0, fill_price=100.5, qty=10, filled_qty=10))
    summary = log.analyze()
    assert summary["total_slippage_usd"] == pytest.approx(10.0)
    assert summary["slippage_usd"]["mean"] == pytest.approx(5.0)


def test_recon_analyze_reject_rate(log):
    log.record(_order())  # filled
    log.record(_order(fill_status=FillStatus.REJECTED, filled_qty=0, fill_price=0.0))
    summary = log.analyze()
    assert summary["reject_rate"] == pytest.approx(0.5)
    assert summary["fill_rate"] == pytest.approx(0.5)


def test_recon_analyze_per_strategy(log):
    log.record(_order(strategy="ORB",   side="BUY", limit_price=100.0, fill_price=101.0, qty=10, filled_qty=10))
    log.record(_order(strategy="TREND_FOLLOW", side="BUY", limit_price=200.0, fill_price=200.0, qty=5, filled_qty=5))
    summary = log.analyze()
    assert "ORB" in summary["per_strategy"]
    assert "TREND_FOLLOW" in summary["per_strategy"]
    assert summary["per_strategy"]["ORB"]["total_slip_usd"] == pytest.approx(10.0)
    assert summary["per_strategy"]["TREND_FOLLOW"]["total_slip_usd"] == pytest.approx(0.0)


def test_recon_analyze_p90_latency(log):
    for lat in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
        sig = time.time() - lat
        o = _order()
        o.signal_ts = sig
        o.fill_ts   = sig + lat
        log.record(o)
    summary = log.analyze()
    # p90 index = int(10 * 0.9) = 9 → sorted[9] = 1.0
    assert summary["latency_s"]["p90"] == pytest.approx(1.0, abs=0.05)
