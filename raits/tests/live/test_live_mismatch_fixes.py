"""
tests/live/test_live_mismatch_fixes.py

Tests for FIX 1/2/3 in the live/broker path:

  FIX 1 — Fill timeout (PENDING) is not treated as rejected.
           Ticker is blocked; subsequent entries on it are skipped.
           orders_pending counter is incremented.

  FIX 2 — Exit order rejected: retry once.
           If retry succeeds, position is closed normally.
           If retry also fails, notify() is called, position stays open,
           exits_failed counter is incremented.

  FIX 3 — Startup reconcile-or-halt:
           MockBroker returns {} → no halt.
           Broker returns non-empty positions → StartupMismatchError raised.
           reconcile_on_startup=False → no call to get_open_positions.
"""
import time
import uuid
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

from raits.live.broker import BrokerInterface, FillStatus, MockBroker, Order
from raits.live.reconciliation import ReconciliationLog
from raits.live.runner import (
    MockContextFeed,
    PaperTrader,
    RunResult,
    StartupMismatchError,
)
from raits.decision.types import BarContext, DecisionResult, EntryIntent, ExitIntent
from raits.backtest.data_types import Trade


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dummy_ctx(ts_str: str = "2022-01-03 09:35:00") -> BarContext:
    ts = pd.Timestamp(ts_str)
    spy_bar = pd.Series({
        "open": 450.0, "high": 451.0, "low": 449.0, "close": 450.5, "volume": 1000
    })
    return BarContext(
        bar_ts=ts, spy_bar=spy_bar, spy_history=[spy_bar],
        day_stocks={}, market_data={}, open_trades=[],
        hmm_state="Normal", cur_vol=0.15,
        day=ts.normalize(), orb_vix_ok=True, stress_orb_vix_ok=True,
        effective_orb_universe=[], effective_vwap_universe=[],
        effective_fade_universe=[], all_tickers=[], base_universe=[],
        stress_stocks={}, spy_or_high=452.0, spy_or_low=448.0,
        spy_bull_trend=True, daily_spy_close=pd.Series(dtype=float),
        pe_short_calendar={}, fade_atr_top2=set(),
        vwap_bb_std=2.0, ema_period=30, vwap_mr_vol_threshold=0.12,
        allow_swing_hold=False, enable_pdt_guard=False,
        stress_size_fraction=0.5,
        orb_signal_start=ts.time(),
        orb_signal_end=ts.time(),
    )


def _entry_intent(ticker="AAPL", price=150.0, shares=10) -> EntryIntent:
    return EntryIntent(
        ticker=ticker, strategy="ORB", direction="LONG",
        entry_price=price, shares=shares, stop=145.0, target=160.0,
        is_day_trade=True, limiting_factor="KELLY", hmm_state="Normal",
    )


def _make_trader(tmp_path, broker=None, reconcile_on_startup=False):
    """Build a PaperTrader with a MagicMock DecisionUnit."""
    if broker is None:
        broker = MockBroker(initial_equity=50_000.0, seed=0)
    recon = ReconciliationLog(out_dir=str(tmp_path))
    du = MagicMock()
    du.reset_day = MagicMock()
    du.decide = MagicMock(return_value=DecisionResult(entries=[], exits=[]))
    du.on_trade_opened = MagicMock()
    du._check_exits = MagicMock(return_value=None)
    return PaperTrader(
        du, broker, recon,
        account_equity=50_000.0,
        reconcile_on_startup=reconcile_on_startup,
    ), du


class _BrokerWithFillSequence(BrokerInterface):
    """Broker that returns a preset sequence of FillStatus values per submit_order call."""

    def __init__(self, fill_statuses):
        self._statuses = list(fill_statuses)
        self._idx = 0
        self._positions = {}

    def submit_order(self, order: Order) -> Order:
        status = self._statuses[self._idx % len(self._statuses)]
        self._idx += 1
        order.fill_status = status
        if status in (FillStatus.FILLED, FillStatus.PARTIAL):
            order.filled_qty = order.qty
            order.fill_price = order.limit_price
            order.fill_ts = time.time()
        elif status == FillStatus.PENDING:
            order.reject_reason = "Fill timeout after 30s"
        elif status == FillStatus.REJECTED:
            order.reject_reason = "MockSequence: reject"
        return order

    def cancel_order(self, order_id: str) -> bool:
        return False

    def account_equity(self) -> float:
        return 50_000.0

    def get_open_positions(self):
        return self._positions


# ── FIX 1: PENDING status handling ────────────────────────────────────────────

def test_pending_not_counted_as_rejected(tmp_path):
    """PENDING fill must NOT increment orders_rejected; must increment orders_pending."""
    broker = _BrokerWithFillSequence([FillStatus.PENDING])
    trader, du = _make_trader(tmp_path, broker=broker)

    intent = _entry_intent()
    result = RunResult()
    with patch("raits.live.runner.notify"):
        returned_trade = trader._process_entry(intent, pd.Timestamp("2022-01-03 09:35:00"), result)

    assert returned_trade is None
    assert result.orders_pending == 1
    assert result.orders_rejected == 0


def test_pending_blocks_subsequent_entry(tmp_path):
    """After a PENDING order, the same ticker must be blocked on the next entry attempt."""
    broker = _BrokerWithFillSequence([FillStatus.PENDING])
    trader, du = _make_trader(tmp_path, broker=broker)

    bar_ts = pd.Timestamp("2022-01-03 09:35:00")
    result = RunResult()
    with patch("raits.live.runner.notify"):
        trader._process_entry(_entry_intent("AAPL"), bar_ts, result)

    # Ticker is now in _pending_tickers — second entry must not submit to broker
    result2 = RunResult()
    # broker._idx would advance if submit_order were called again
    idx_before = broker._idx
    returned = trader._process_entry(_entry_intent("AAPL"), bar_ts, result2)

    assert returned is None
    assert broker._idx == idx_before          # no second submit
    assert result2.orders_submitted == 0      # blocked before submission
    assert "AAPL" in trader._pending_tickers


# ── FIX 2: Exit retry and notify ─────────────────────────────────────────────

def _open_trade(ticker="AAPL") -> Trade:
    t = Trade(
        trade_id=str(uuid.uuid4()),
        ticker=ticker,
        strategy="ORB",
        direction="LONG",
        entry_time=pd.Timestamp("2022-01-03 09:35:00"),
        entry_price=150.0,
        shares=10,
        stop=145.0,
        target=160.0,
        limiting_factor="KELLY",
        hmm_state="Normal",
    )
    return t


def test_exit_retry_succeeds_on_second_attempt(tmp_path):
    """First exit attempt REJECTED, retry FILLED → position closes, no notify."""
    broker = _BrokerWithFillSequence([FillStatus.REJECTED, FillStatus.FILLED])
    trader, du = _make_trader(tmp_path, broker=broker)

    trade = _open_trade()
    trader._open_positions[trade.trade_id] = trade
    exit_intent = ExitIntent(trade=trade, exit_price=155.0, reason="TIME_STOP")
    result = RunResult()

    with patch("raits.live.runner.notify") as mock_notify:
        trader._process_exit(exit_intent, pd.Timestamp("2022-01-03 15:55:00"), result)

    assert trade.trade_id not in trader._open_positions  # closed
    assert result.exits_failed == 0
    mock_notify.assert_not_called()


def test_exit_both_attempts_fail_keeps_position_and_notifies(tmp_path):
    """Both exit attempts REJECTED → position stays open, notify fired, exits_failed=1."""
    broker = _BrokerWithFillSequence([FillStatus.REJECTED, FillStatus.REJECTED])
    trader, du = _make_trader(tmp_path, broker=broker)

    trade = _open_trade()
    trader._open_positions[trade.trade_id] = trade
    exit_intent = ExitIntent(trade=trade, exit_price=155.0, reason="TIME_STOP")
    result = RunResult()

    with patch("raits.live.runner.notify") as mock_notify:
        trader._process_exit(exit_intent, pd.Timestamp("2022-01-03 15:55:00"), result)

    assert trade.trade_id in trader._open_positions   # still open
    assert result.exits_failed == 1
    assert result.orders_rejected == 1
    mock_notify.assert_called_once()
    assert "EXIT FAILED" in mock_notify.call_args[0][0]


# ── FIX 3: Startup reconcile-or-halt ─────────────────────────────────────────

def test_startup_no_positions_proceeds(tmp_path):
    """MockBroker returns {} → no StartupMismatchError, run completes normally."""
    broker = MockBroker(initial_equity=50_000.0, seed=0)
    trader, du = _make_trader(tmp_path, broker=broker, reconcile_on_startup=True)

    feed = MockContextFeed([_dummy_ctx()])
    result = trader.run(feed)  # must not raise
    assert result.bars_processed == 1


def test_startup_mismatch_halts(tmp_path):
    """Broker reports open positions at startup → StartupMismatchError raised."""
    broker = _BrokerWithFillSequence([FillStatus.FILLED])
    broker._positions = {"TSLA": 50.0}   # simulate IBKR holding a position

    recon = ReconciliationLog(out_dir=str(tmp_path))
    du = MagicMock()
    du.reset_day = MagicMock()
    du.decide = MagicMock(return_value=DecisionResult(entries=[], exits=[]))

    trader = PaperTrader(du, broker, recon, account_equity=50_000.0,
                         reconcile_on_startup=True)

    with patch("raits.live.runner.notify"):
        with pytest.raises(StartupMismatchError, match="TSLA"):
            trader.run(MockContextFeed([_dummy_ctx()]))


def test_startup_reconcile_skipped_when_disabled(tmp_path):
    """reconcile_on_startup=False → get_open_positions never called."""
    broker = MagicMock(spec=BrokerInterface)
    broker.get_open_positions.return_value = {"MSFT": 100.0}
    broker.submit_order.return_value = Order(
        order_id="x", ticker="MSFT", side="BUY", qty=1,
        limit_price=100.0, strategy="ORB", hmm_state="Normal",
        signal_ts=time.time(),
    )
    broker.account_equity.return_value = 50_000.0

    recon = ReconciliationLog(out_dir=str(tmp_path))
    du = MagicMock()
    du.reset_day = MagicMock()
    du.decide = MagicMock(return_value=DecisionResult(entries=[], exits=[]))

    trader = PaperTrader(du, broker, recon, account_equity=50_000.0,
                         reconcile_on_startup=False)

    result = trader.run(MockContextFeed([_dummy_ctx()]))

    broker.get_open_positions.assert_not_called()
    assert result.bars_processed == 1
