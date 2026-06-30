"""
tests/live/test_live_broker.py

Unit tests for MockBroker fill/slippage/partial/reject logic.
"""
import pytest
import time

from raits.live.broker import (
    BrokerInterface,
    FillStatus,
    IBKRBroker,
    MockBroker,
    Order,
)


def _order(**kwargs) -> Order:
    defaults = dict(
        order_id="test-001",
        ticker="AAPL",
        side="BUY",
        qty=10,
        limit_price=150.0,
        strategy="ORB",
        hmm_state="Normal",
        signal_ts=time.time(),
    )
    defaults.update(kwargs)
    return Order(**defaults)


# ── Fill ──────────────────────────────────────────────────────────────────────

def test_mock_broker_full_fill_zero_slippage():
    broker = MockBroker(slippage_pct=0.0, seed=42)
    order = broker.submit_order(_order(side="BUY", qty=10, limit_price=100.0))
    assert order.fill_status == FillStatus.FILLED
    assert order.filled_qty == 10
    assert order.fill_price == pytest.approx(100.0)


def test_mock_broker_slippage_buy():
    broker = MockBroker(slippage_pct=0.001, seed=42)
    order = broker.submit_order(_order(side="BUY", limit_price=100.0))
    # Buy: fill_price = limit_price * (1 + slippage_pct)
    assert order.fill_price == pytest.approx(100.1)
    assert order.fill_status == FillStatus.FILLED


def test_mock_broker_slippage_sell():
    broker = MockBroker(slippage_pct=0.001, seed=42)
    order = broker.submit_order(_order(side="SELL", limit_price=100.0))
    # Sell: fill_price = limit_price * (1 - slippage_pct)
    assert order.fill_price == pytest.approx(99.9)
    assert order.fill_status == FillStatus.FILLED


def test_mock_broker_partial_fill():
    # Force partial by setting partial_fill_rate=1.0
    broker = MockBroker(partial_fill_rate=1.0, partial_fill_fraction=0.5, seed=0)
    order = broker.submit_order(_order(qty=10))
    assert order.fill_status == FillStatus.PARTIAL
    assert order.filled_qty == 5


def test_mock_broker_partial_fill_at_least_one_share():
    # Even with tiny fraction, filled_qty >= 1
    broker = MockBroker(partial_fill_rate=1.0, partial_fill_fraction=0.001, seed=0)
    order = broker.submit_order(_order(qty=10))
    assert order.filled_qty >= 1


def test_mock_broker_reject():
    broker = MockBroker(reject_rate=1.0, seed=42)
    order = broker.submit_order(_order())
    assert order.fill_status == FillStatus.REJECTED
    assert order.filled_qty == 0
    assert order.reject_reason != ""


def test_mock_broker_cancel_pending_not_possible():
    # Orders are synchronously filled — cancel always returns False
    broker = MockBroker(seed=42)
    order = broker.submit_order(_order())
    assert order.fill_status == FillStatus.FILLED
    # Already filled; cancel returns False
    cancelled = broker.cancel_order(order.order_id)
    assert cancelled is False


def test_mock_broker_cancel_unknown_order():
    broker = MockBroker(seed=42)
    assert broker.cancel_order("nonexistent") is False


def test_mock_broker_account_equity():
    broker = MockBroker(initial_equity=50_000.0)
    assert broker.account_equity() == pytest.approx(50_000.0)
    broker.set_equity(49_000.0)
    assert broker.account_equity() == pytest.approx(49_000.0)


def test_mock_broker_fill_latency_logged():
    sig_ts = time.time()
    broker = MockBroker(fill_latency_s=0.5, seed=42)
    order = _order(signal_ts=sig_ts)
    filled = broker.submit_order(order)
    assert filled.fill_ts >= sig_ts + 0.4  # at least 0.5s after signal


def test_mock_broker_is_broker_interface():
    broker = MockBroker()
    assert isinstance(broker, BrokerInterface)


# ── IBKRBroker stub ───────────────────────────────────────────────────────────

def test_ibkr_broker_submit_raises():
    broker = IBKRBroker()
    with pytest.raises(NotImplementedError):
        broker.submit_order(_order())


def test_ibkr_broker_cancel_raises():
    broker = IBKRBroker()
    with pytest.raises(NotImplementedError):
        broker.cancel_order("x")


def test_ibkr_broker_equity_raises():
    broker = IBKRBroker()
    with pytest.raises(NotImplementedError):
        broker.account_equity()


def test_ibkr_broker_is_broker_interface():
    assert isinstance(IBKRBroker(), BrokerInterface)
