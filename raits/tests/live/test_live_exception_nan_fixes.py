"""
tests/live/test_live_exception_nan_fixes.py

Tests for FIX 4 (exception safety) and FIX 5 (NaN/inf guard):

  FIX 4 — Exception on a bar must NOT crash the whole loop:
    (a) decide() raises → bar skipped (bars_errored++), loop continues,
        subsequent bars still process exits on open positions, notify fired
    (b) _process_exit raises → one exit crash doesn't block other exits
        on the same bar; loop continues; notify fired
    (c) _process_entry raises → entry skipped, loop continues

  FIX 5 — NaN/inf must fail loud at the first boundary:
    (d) NaN entry price → order not submitted, entries_nan_rejected++, notify fired
    (e) inf entry price → same
    (f) zero shares → rejected
    (g) NaN pnl in process_exit → position closed, pnl_nan_guarded++, equity unchanged,
        CB not fed, notify fired
"""
import math
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


def _open_trade(ticker="AAPL", entry_price=150.0) -> Trade:
    return Trade(
        trade_id=str(uuid.uuid4()),
        ticker=ticker, strategy="ORB", direction="LONG",
        entry_time=pd.Timestamp("2022-01-03 09:35:00"),
        entry_price=entry_price, shares=10, stop=145.0, target=160.0,
        limiting_factor="KELLY", hmm_state="Normal",
    )


def _make_trader(tmp_path, broker=None, reconcile_on_startup=False):
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


# ── FIX 4a: decide() raises → bar skipped, loop continues ────────────────────

def test_decide_exception_skips_bar_loop_continues(tmp_path):
    """decide() raising on bar 1 increments bars_errored and bar 2 is processed."""
    trader, du = _make_trader(tmp_path)

    bar1 = _dummy_ctx("2022-01-03 09:35:00")
    bar2 = _dummy_ctx("2022-01-03 09:40:00")

    du.decide.side_effect = [RuntimeError("simulated decide crash"), DecisionResult(entries=[], exits=[])]

    with patch("raits.live.runner.notify") as mock_notify:
        result = trader.run(MockContextFeed([bar1, bar2]))

    assert result.bars_errored == 1
    assert result.bars_processed == 1   # only bar 2 counted (bar 1 errored)
    mock_notify.assert_called_once()
    assert "BAR EXCEPTION" in mock_notify.call_args[0][0]


def test_decide_exception_exits_still_process_on_next_bar(tmp_path):
    """Open position survives a crashed bar; the exit still processes on the next bar."""
    broker = MockBroker(initial_equity=50_000.0, seed=0)
    trader, du = _make_trader(tmp_path, broker=broker)

    # Plant an open position manually
    trade = _open_trade()
    trader._open_positions[trade.trade_id] = trade

    bar1 = _dummy_ctx("2022-01-03 09:35:00")
    bar2 = _dummy_ctx("2022-01-03 09:40:00")

    exit_intent = ExitIntent(trade=trade, exit_price=155.0, reason="TIME_STOP")

    # Bar 1: decide crashes (exit missed for this bar)
    # Bar 2: decide returns the exit intent
    du.decide.side_effect = [
        RuntimeError("crash"),
        DecisionResult(entries=[], exits=[exit_intent]),
    ]

    with patch("raits.live.runner.notify"):
        result = trader.run(MockContextFeed([bar1, bar2]))

    # Position must be closed on bar 2
    assert trade.trade_id not in trader._open_positions
    assert result.bars_errored == 1
    assert result.exits_signalled == 1


def test_decide_exception_notifies(tmp_path):
    """BAR EXCEPTION notify message contains bar timestamp."""
    trader, du = _make_trader(tmp_path)
    du.decide.side_effect = ValueError("broken")

    with patch("raits.live.runner.notify") as mock_notify:
        trader.run(MockContextFeed([_dummy_ctx("2022-01-03 09:35:00")]))

    msg = mock_notify.call_args[0][0]
    assert "BAR EXCEPTION" in msg
    assert "2022-01-03 09:35:00" in msg


# ── FIX 4b: _process_exit raises → other exits still fire ────────────────────

def test_exit_exception_does_not_block_other_exits(tmp_path):
    """If one exit crashes, the other exits on the same bar still process."""
    broker = MockBroker(initial_equity=50_000.0, seed=0)
    trader, du = _make_trader(tmp_path, broker=broker)

    trade_a = _open_trade("AAPL")
    trade_b = _open_trade("MSFT")
    trader._open_positions[trade_a.trade_id] = trade_a
    trader._open_positions[trade_b.trade_id] = trade_b

    exit_a = ExitIntent(trade=trade_a, exit_price=155.0, reason="STOP_HIT")
    exit_b = ExitIntent(trade=trade_b, exit_price=250.0, reason="TIME_STOP")

    du.decide.return_value = DecisionResult(entries=[], exits=[exit_a, exit_b])

    # Make _process_exit crash for trade_a but succeed for trade_b
    original_process_exit = trader._process_exit
    call_count = [0]

    def _flaky_exit(intent, bar_ts, result):
        call_count[0] += 1
        if intent.trade.ticker == "AAPL":
            raise RuntimeError("AAPL exit exploded")
        return original_process_exit(intent, bar_ts, result)

    trader._process_exit = _flaky_exit

    with patch("raits.live.runner.notify") as mock_notify:
        result = trader.run(MockContextFeed([_dummy_ctx()]))

    # MSFT exit succeeded during bar processing → exit_reason set by the exit intent
    assert trade_b.exit_reason == "TIME_STOP"
    # AAPL exit crashed; EOD cleanup correctly closes it after the bar loop
    # (that is CORRECT behavior — the loop didn't crash, and EOD is the safety net)
    assert trade_a.exit_reason == "EOD"
    # Loop didn't crash — result was returned and bar was counted
    assert result.bars_processed == 1
    # notify called for the exception on AAPL
    assert any("EXIT EXCEPTION" in str(c) for c in mock_notify.call_args_list)


# ── FIX 5d-f: NaN/inf/zero entry guard ───────────────────────────────────────

def test_nan_entry_price_rejected(tmp_path):
    """NaN entry price → order not submitted, entries_nan_rejected++, notify fired."""
    trader, du = _make_trader(tmp_path)

    intent = _entry_intent(price=float("nan"))
    result = RunResult()

    with patch("raits.live.runner.notify") as mock_notify:
        returned = trader._process_entry(intent, pd.Timestamp("2022-01-03 09:35:00"), result)

    assert returned is None
    assert result.entries_nan_rejected == 1
    assert result.orders_submitted == 0
    mock_notify.assert_called_once()
    assert "NaN/INF ENTRY REJECTED" in mock_notify.call_args[0][0]


def test_inf_entry_price_rejected(tmp_path):
    """Inf entry price → rejected."""
    trader, du = _make_trader(tmp_path)
    intent = _entry_intent(price=float("inf"))
    result = RunResult()

    with patch("raits.live.runner.notify"):
        returned = trader._process_entry(intent, pd.Timestamp("2022-01-03 09:35:00"), result)

    assert returned is None
    assert result.entries_nan_rejected == 1


def test_zero_shares_rejected(tmp_path):
    """Zero shares → rejected (position size zero is nonsensical)."""
    trader, du = _make_trader(tmp_path)
    intent = _entry_intent(shares=0)
    result = RunResult()

    with patch("raits.live.runner.notify"):
        returned = trader._process_entry(intent, pd.Timestamp("2022-01-03 09:35:00"), result)

    assert returned is None
    assert result.entries_nan_rejected == 1


def test_valid_entry_not_rejected(tmp_path):
    """Valid price and shares must NOT trigger the NaN guard."""
    broker = MockBroker(initial_equity=50_000.0, seed=0)
    trader, du = _make_trader(tmp_path, broker=broker)
    intent = _entry_intent(price=150.0, shares=10)
    result = RunResult()

    with patch("raits.live.runner.notify") as mock_notify:
        returned = trader._process_entry(intent, pd.Timestamp("2022-01-03 09:35:00"), result)

    assert returned is not None
    assert result.entries_nan_rejected == 0
    mock_notify.assert_not_called()


# ── FIX 5g: NaN pnl in process_exit ─────────────────────────────────────────

class _NaNFillBroker(BrokerInterface):
    """Broker that fills at a NaN price, producing NaN gross_pnl."""

    def submit_order(self, order: Order) -> Order:
        order.fill_status = FillStatus.FILLED
        order.filled_qty = order.qty
        order.fill_price = float("nan")   # NaN fill → NaN gross_pnl
        order.fill_ts = time.time()
        return order

    def cancel_order(self, order_id: str) -> bool:
        return False

    def account_equity(self) -> float:
        return 50_000.0

    def get_open_positions(self):
        return {}


def test_nan_pnl_in_process_exit_closes_position_without_equity_corruption(tmp_path):
    """NaN fill price → pnl_nan_guarded++, position closed, equity unchanged, CB not fed."""
    broker = _NaNFillBroker()
    trader, du = _make_trader(tmp_path, broker=broker)

    trade = _open_trade(entry_price=150.0)
    trader._open_positions[trade.trade_id] = trade
    initial_equity = trader._running_equity

    exit_intent = ExitIntent(trade=trade, exit_price=155.0, reason="TIME_STOP")
    result = RunResult()

    with patch("raits.live.runner.notify") as mock_notify:
        trader._process_exit(exit_intent, pd.Timestamp("2022-01-03 15:55:00"), result)

    # Position is closed
    assert trade.trade_id not in trader._open_positions
    assert trade in trader._closed_trades
    # pnl fields set to None (not corrupted)
    assert trade.gross_pnl is None
    assert trade.net_pnl is None
    # equity NOT updated
    assert trader._running_equity == pytest.approx(initial_equity)
    # counter incremented
    assert result.pnl_nan_guarded == 1
    # notify fired
    mock_notify.assert_called_once()
    assert "NaN/INF P&L" in mock_notify.call_args[0][0]


def test_nan_pnl_does_not_trip_circuit_breaker(tmp_path):
    """NaN pnl must not be fed to the CB — CB consecutive-loss counter stays clean."""
    broker = _NaNFillBroker()
    trader, du = _make_trader(tmp_path, broker=broker)

    trade = _open_trade(entry_price=150.0)
    trader._open_positions[trade.trade_id] = trade

    exit_intent = ExitIntent(trade=trade, exit_price=155.0, reason="TIME_STOP")
    result = RunResult()

    with patch("raits.live.runner.notify"):
        trader._process_exit(exit_intent, pd.Timestamp("2022-01-03 15:55:00"), result)

    # CB should NOT have been tripped by the NaN pnl
    assert not trader._cb_active
