"""
tests/live/test_live_runner.py

Unit tests for PaperTrader runner:
  (1) intent → order conversion
  (2) discipline-lock hash
  (3) kill-switch trigger
  (4) MockContextFeed iteration
  (5) end-to-end: slippage=0 → $0 reconciliation diff
  (6) end-to-end: slippage>0 → measured by reconciliation
"""
import time
import uuid
import pytest
from unittest.mock import MagicMock, patch
import pandas as pd

from raits.live.broker import FillStatus, MockBroker, Order
from raits.live.reconciliation import ReconciliationLog
from raits.live.runner import (
    DisciplineLockError,
    KillSwitchTripped,
    MockContextFeed,
    LiveContextFeed,
    PaperOnlyViolation,
    PaperTrader,
    RunResult,
    _config_hash,
    check_discipline_lock,
    check_paper_only,
    _intent_to_trade,
)
from raits.decision.types import BarContext, DecisionResult, EntryIntent, ExitIntent
from raits.backtest.data_types import Trade


# ── Discipline lock ───────────────────────────────────────────────────────────

def test_config_hash_is_deterministic():
    params = {"orb_range_minutes": 20, "vwap_bb_std": 1.5, "ema_period": 30}
    h1 = _config_hash(params)
    h2 = _config_hash(params)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_config_hash_differs_on_change():
    params1 = {"orb_range_minutes": 20, "vwap_bb_std": 1.5, "ema_period": 30}
    params2 = {"orb_range_minutes": 15, "vwap_bb_std": 1.5, "ema_period": 30}
    assert _config_hash(params1) != _config_hash(params2)


def test_discipline_lock_passes():
    params = {"orb_range_minutes": 20, "vwap_bb_std": 1.5, "ema_period": 30}
    h = _config_hash(params)
    check_discipline_lock(params, h)  # must not raise


def test_discipline_lock_fails():
    params = {"orb_range_minutes": 20, "vwap_bb_std": 1.5, "ema_period": 30}
    with pytest.raises(DisciplineLockError, match="config hash mismatch"):
        check_discipline_lock(params, "wronghash")


# ── PAPER_ONLY guard ──────────────────────────────────────────────────────────

def test_paper_only_paper_port_ok():
    check_paper_only(ibkr_port=7497, live_flag=False)  # must not raise


def test_paper_only_live_port_without_flag_raises():
    with pytest.raises(PaperOnlyViolation, match="PAPER_ONLY"):
        check_paper_only(ibkr_port=7496, live_flag=False)


def test_paper_only_live_port_with_flag_ok():
    check_paper_only(ibkr_port=7496, live_flag=True)  # must not raise


# ── _intent_to_trade helper ───────────────────────────────────────────────────

def _make_entry_intent(**kwargs) -> EntryIntent:
    defaults = dict(
        ticker="AAPL",
        strategy="ORB",
        direction="LONG",
        entry_price=150.0,
        shares=10,
        stop=145.0,
        target=160.0,
        is_day_trade=True,
        limiting_factor="KELLY",
        hmm_state="Normal",
    )
    defaults.update(kwargs)
    return EntryIntent(**defaults)


def _filled_order(
    ticker="AAPL", side="BUY", qty=10, limit_price=150.0, fill_price=150.0,
    fill_status=FillStatus.FILLED, filled_qty=10, strategy="ORB", hmm_state="Normal",
) -> Order:
    o = Order(
        order_id=str(uuid.uuid4()),
        ticker=ticker, side=side, qty=qty, limit_price=limit_price,
        strategy=strategy, hmm_state=hmm_state, signal_ts=time.time(),
    )
    o.fill_status = fill_status
    o.filled_qty  = filled_qty
    o.fill_price  = fill_price
    o.fill_ts     = time.time() + 0.01
    return o


def test_intent_to_trade_full_fill():
    intent = _make_entry_intent(shares=10, entry_price=150.0)
    order  = _filled_order(fill_price=150.5, filled_qty=10)
    trade  = _intent_to_trade(intent, order)
    assert trade.ticker     == "AAPL"
    assert trade.strategy   == "ORB"
    assert trade.direction  == "LONG"
    assert trade.shares     == 10
    assert trade.entry_price == pytest.approx(150.5)  # actual fill price
    assert trade.stop       == pytest.approx(145.0)
    assert trade.target     == pytest.approx(160.0)


def test_intent_to_trade_partial_fill_uses_filled_qty():
    intent = _make_entry_intent(shares=10)
    order  = _filled_order(filled_qty=5, fill_status=FillStatus.PARTIAL)
    trade  = _intent_to_trade(intent, order, use_filled_qty=True)
    assert trade.shares == 5


# ── MockContextFeed ───────────────────────────────────────────────────────────

def _dummy_ctx(ts_str: str = "2022-01-03 09:35:00") -> BarContext:
    ts = pd.Timestamp(ts_str)
    spy_bar = pd.Series({"open": 450.0, "high": 451.0, "low": 449.0, "close": 450.5, "volume": 1000})
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
        orb_signal_start=pd.Timestamp(ts_str).time(),
        orb_signal_end=pd.Timestamp(ts_str).time(),
    )


def test_mock_context_feed_iteration():
    ctxs = [_dummy_ctx("2022-01-03 09:35:00"), _dummy_ctx("2022-01-03 09:40:00")]
    feed = MockContextFeed(ctxs)
    collected = list(feed)
    assert len(collected) == 2
    assert collected[0].bar_ts == pd.Timestamp("2022-01-03 09:35:00")


def test_mock_context_feed_empty():
    feed = MockContextFeed([])
    assert list(feed) == []


def test_live_context_feed_raises():
    with pytest.raises(NotImplementedError):
        LiveContextFeed()


# ── Kill-switch ───────────────────────────────────────────────────────────────

def _make_trader(tmp_path, slippage=0.0, kill_pct=0.04, equity=50_000.0):
    broker = MockBroker(initial_equity=equity, slippage_pct=slippage, seed=0)
    recon  = ReconciliationLog(out_dir=str(tmp_path))
    du     = MagicMock()
    du.reset_day = MagicMock()
    du.decide    = MagicMock(return_value=DecisionResult(entries=[], exits=[]))
    return PaperTrader(du, broker, recon, account_equity=equity, kill_switch_pct=kill_pct), du


def test_kill_switch_not_tripped_no_loss(tmp_path):
    trader, du = _make_trader(tmp_path, kill_pct=0.04, equity=50_000.0)
    feed = MockContextFeed([_dummy_ctx()])
    result = trader.run(feed)
    assert not result.kill_switch_tripped


def test_kill_switch_tripped_when_daily_loss_exceeds_cap(tmp_path):
    """Test _kill_switch_triggered directly — bypasses day-reset in run()."""
    trader, _ = _make_trader(tmp_path, kill_pct=0.02, equity=10_000.0)
    result = RunResult()
    trader._daily_pnl = -250.0  # 2.5% of $10k → exceeds 2% cap
    bar_ts = pd.Timestamp("2022-01-03 10:00:00")
    tripped = trader._kill_switch_triggered(bar_ts, result)
    assert tripped is True
    assert result.kill_switch_tripped
    assert result.kill_switch_bar == bar_ts


def test_kill_switch_not_tripped_below_cap(tmp_path):
    """Loss below cap should not trip the kill switch."""
    trader, _ = _make_trader(tmp_path, kill_pct=0.04, equity=10_000.0)
    result = RunResult()
    trader._daily_pnl = -100.0  # 1% of $10k → below 4% cap
    bar_ts = pd.Timestamp("2022-01-03 10:00:00")
    tripped = trader._kill_switch_triggered(bar_ts, result)
    assert tripped is False
    assert not result.kill_switch_tripped


# ── End-to-end: slippage=0 → $0 reconciliation ───────────────────────────────

def _make_trade(trade_id: str = "t1", ticker: str = "AAPL") -> Trade:
    return Trade(
        trade_id=trade_id, ticker=ticker, strategy="ORB", direction="LONG",
        entry_time=time.time(), entry_price=150.0, shares=10,
        stop=145.0, target=160.0, hmm_state="Normal", limiting_factor="KELLY",
    )


def test_end_to_end_zero_slippage(tmp_path):
    broker = MockBroker(slippage_pct=0.0, seed=0)
    recon  = ReconciliationLog(out_dir=str(tmp_path))

    entry = EntryIntent(
        ticker="AAPL", strategy="ORB", direction="LONG",
        entry_price=150.0, shares=10, stop=145.0, target=160.0,
        is_day_trade=True, limiting_factor="KELLY", hmm_state="Normal",
    )

    du = MagicMock()
    du.reset_day = MagicMock()
    # First bar: emit entry; second bar: emit exit
    ctx1 = _dummy_ctx("2022-01-03 09:35:00")
    ctx2 = _dummy_ctx("2022-01-03 09:40:00")

    open_trade_ref = []

    def decide_side_effect(ctx):
        if ctx.bar_ts == pd.Timestamp("2022-01-03 09:35:00"):
            return DecisionResult(entries=[entry], exits=[])
        else:
            if open_trade_ref:
                ex = ExitIntent(trade=open_trade_ref[0], exit_price=155.0, reason="TARGET_HIT")
                return DecisionResult(entries=[], exits=[ex])
            return DecisionResult(entries=[], exits=[])

    du.decide = MagicMock(side_effect=decide_side_effect)

    trader = PaperTrader(du, broker, recon, account_equity=50_000.0)

    # After entry bar: capture the open trade
    original_process_entry = trader._process_entry

    def patched_entry(intent, bar_ts, result):
        original_process_entry(intent, bar_ts, result)
        open_trade_ref.extend(trader._open_positions.values())

    trader._process_entry = patched_entry

    feed = MockContextFeed([ctx1, ctx2])
    result = trader.run(feed)

    summary = recon.analyze()
    assert summary["total_slippage_usd"] == pytest.approx(0.0), \
        f"Expected $0 slippage with slippage_pct=0, got {summary['total_slippage_usd']}"
    assert summary["total_orders"] >= 1


def test_end_to_end_slippage_measured(tmp_path):
    broker = MockBroker(slippage_pct=0.005, seed=0)  # 0.5% slippage
    recon  = ReconciliationLog(out_dir=str(tmp_path))

    entry = EntryIntent(
        ticker="AAPL", strategy="ORB", direction="LONG",
        entry_price=100.0, shares=10, stop=95.0, target=110.0,
        is_day_trade=True, limiting_factor="KELLY", hmm_state="Normal",
    )

    du = MagicMock()
    du.reset_day = MagicMock()
    du.decide = MagicMock(return_value=DecisionResult(entries=[entry], exits=[]))

    trader = PaperTrader(du, broker, recon, account_equity=50_000.0)
    feed   = MockContextFeed([_dummy_ctx()])
    trader.run(feed)

    summary = recon.analyze()
    # BUY 10 shares at 100 with 0.5% slippage → fill at 100.5 → $5 slippage
    assert summary["total_slippage_usd"] == pytest.approx(5.0, abs=0.01), \
        f"Expected $5 slippage, got {summary['total_slippage_usd']}"
    assert summary["total_orders"] == 1


# ── PaperTrader discipline guard at init ──────────────────────────────────────

def test_paper_trader_discipline_lock_at_init(tmp_path):
    broker = MockBroker()
    recon  = ReconciliationLog(out_dir=str(tmp_path))
    du     = MagicMock()
    du.reset_day = MagicMock()
    params = {"orb_range_minutes": 20, "vwap_bb_std": 1.5, "ema_period": 30}
    good_hash = _config_hash(params)
    # Should not raise
    PaperTrader(du, broker, recon, discipline_params=params, expected_hash=good_hash)


def test_paper_trader_discipline_lock_wrong_hash_raises(tmp_path):
    broker = MockBroker()
    recon  = ReconciliationLog(out_dir=str(tmp_path))
    du     = MagicMock()
    params = {"orb_range_minutes": 20, "vwap_bb_std": 1.5, "ema_period": 30}
    with pytest.raises(DisciplineLockError):
        PaperTrader(du, broker, recon, discipline_params=params, expected_hash="badhash")
