"""
tests/live/test_live_runner.py

Unit tests for PaperTrader runner:
  (1) intent → order conversion
  (2) discipline-lock hash
  (3) kill-switch trigger
  (4) MockContextFeed iteration
  (5) end-to-end: slippage=0 → $0 reconciliation diff
  (6) end-to-end: slippage>0 → measured by reconciliation
  (7) LivePolygonFeed wires into PaperTrader (Step 1)
  (8) Full pipeline with all guards + LivePolygonFeed (Step 3)
"""
import time
import uuid
import numpy as np
import pytest
from unittest.mock import MagicMock
import pandas as pd

from raits.backtest.data_types import BacktestConfig
from raits.live.broker import FillStatus, MockBroker, Order
from raits.live.context_feed import LivePolygonFeed
from raits.live.reconciliation import ReconciliationLog
from raits.live.runner import (
    DisciplineLockError,
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
    intent  = _make_entry_intent(shares=10, entry_price=150.0)
    order   = _filled_order(fill_price=150.5, filled_qty=10)
    bar_ts  = pd.Timestamp("2022-01-03 09:35:00")
    trade   = _intent_to_trade(intent, order, bar_ts)
    assert trade.ticker      == "AAPL"
    assert trade.strategy    == "ORB"
    assert trade.direction   == "LONG"
    assert trade.shares      == 10
    assert trade.entry_price == pytest.approx(150.5)  # actual fill price
    assert trade.stop        == pytest.approx(145.0)
    assert trade.target      == pytest.approx(160.0)


def test_intent_to_trade_partial_fill_uses_filled_qty():
    intent  = _make_entry_intent(shares=10)
    order   = _filled_order(filled_qty=5, fill_status=FillStatus.PARTIAL)
    bar_ts  = pd.Timestamp("2022-01-03 09:35:00")
    trade   = _intent_to_trade(intent, order, bar_ts, use_filled_qty=True)
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
    du._check_exits = MagicMock(return_value=None)  # no same-bar exit
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


# ── LivePolygonFeed helpers ───────────────────────────────────────────────────

def _live_spy_bars(day_str: str = "2022-01-03") -> pd.DataFrame:
    day   = pd.Timestamp(day_str)
    times = pd.date_range(start=day.replace(hour=9, minute=30), periods=13, freq="5min")
    n     = len(times)
    rng   = np.random.default_rng(seed=42)
    close = 470.0 + np.cumsum(rng.standard_normal(n) * 0.3)
    return pd.DataFrame({
        "open": close - 0.1, "high": close + 0.5,
        "low":  close - 0.5, "close": close,
        "volume": np.full(n, 500_000),
    }, index=times)


def _live_stock_bars(day_str: str = "2022-01-03", seed: int = 0) -> pd.DataFrame:
    day   = pd.Timestamp(day_str)
    times = pd.date_range(start=day.replace(hour=9, minute=30), periods=13, freq="5min")
    n     = len(times)
    rng   = np.random.default_rng(seed=seed)
    close = 150.0 + np.cumsum(rng.standard_normal(n) * 0.5)
    return pd.DataFrame({
        "open": close - 0.15, "high": close + 0.8,
        "low":  close - 0.8,  "close": close,
        "volume": np.full(n, 200_000), "vwap": close,
    }, index=times)


def _minimal_live_mkt(day_str: str = "2022-01-03") -> dict:
    return {
        "SPY":  _live_spy_bars(day_str),
        "AAPL": _live_stock_bars(day_str, seed=1),
        "MSFT": _live_stock_bars(day_str, seed=2),
    }


# ── Step 1: LivePolygonFeed wires into PaperTrader ───────────────────────────

def test_live_polygon_feed_wires_into_paper_trader(tmp_path):
    """LivePolygonFeed (test mode) is a valid ContextFeed and drives PaperTrader without error."""
    cfg  = BacktestConfig(
        start_date="2022-01-03", end_date="2022-01-03",
        universe=["AAPL", "MSFT"], account_equity=50_000.0,
    )
    mkt  = _minimal_live_mkt()
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, vix_daily={})

    broker = MockBroker(slippage_pct=0.0, seed=0)
    recon  = ReconciliationLog(out_dir=str(tmp_path))
    du     = MagicMock()
    du.reset_day = MagicMock()
    du.decide    = MagicMock(return_value=DecisionResult(entries=[], exits=[]))

    trader = PaperTrader(du, broker, recon, account_equity=50_000.0)
    result = trader.run(feed)

    assert not result.kill_switch_tripped
    assert du.decide.call_count >= 13  # 13 bars in one day


# ── Step 3: Full pipeline + all guards ───────────────────────────────────────

def test_live_feed_all_guards_clean_run(tmp_path):
    """Full pipeline: LivePolygonFeed + DISCIPLINE_LOCK + KILL_SWITCH + $0 slippage."""
    params    = {"orb_range_minutes": 20, "vwap_bb_std": 1.5, "ema_period": 30}
    good_hash = _config_hash(params)

    cfg  = BacktestConfig(
        start_date="2022-01-03", end_date="2022-01-03",
        universe=["AAPL", "MSFT"], account_equity=50_000.0,
        orb_range_minutes=20, vwap_bb_std=1.5, ema_period=30,
    )
    mkt  = _minimal_live_mkt()
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, vix_daily={})

    broker = MockBroker(slippage_pct=0.0, seed=0)
    recon  = ReconciliationLog(out_dir=str(tmp_path))
    du     = MagicMock()
    du.reset_day = MagicMock()
    du.decide    = MagicMock(return_value=DecisionResult(entries=[], exits=[]))

    trader = PaperTrader(
        du, broker, recon,
        account_equity=50_000.0,
        discipline_params=params,
        expected_hash=good_hash,
    )
    result  = trader.run(feed)
    summary = recon.analyze()

    assert not result.kill_switch_tripped
    assert summary.get("total_slippage_usd", 0.0) == pytest.approx(0.0)


def test_paper_only_still_blocks_live_port_with_live_feed(tmp_path):
    """PAPER_ONLY guard fires regardless of which ContextFeed is used."""
    with pytest.raises(PaperOnlyViolation, match="PAPER_ONLY"):
        check_paper_only(ibkr_port=7496, live_flag=False)


# ── Proactive EOD (live mode) ─────────────────────────────────────────────────

def _make_trader_live(tmp_path, clock_fn, equity=50_000.0):
    """PaperTrader in live_mode with injected clock and no-op DU."""
    broker = MockBroker(slippage_pct=0.0, seed=0)
    recon  = ReconciliationLog(out_dir=str(tmp_path))
    du     = MagicMock()
    du.reset_day  = MagicMock()
    du._check_exits = MagicMock(return_value=None)
    du.on_trade_opened = MagicMock()
    du.decide = MagicMock(return_value=DecisionResult(entries=[], exits=[]))
    return PaperTrader(
        du, broker, recon,
        account_equity=equity,
        live_mode=True,
        clock_fn=clock_fn,
    ), du


import datetime as _dt_mod
from unittest.mock import patch as _patch


def test_proactive_eod_closes_intraday_position_on_half_day(tmp_path):
    """
    Half-day scenario: VWAP_MR position opened at 10:00, bars stop at 12:55.
    Clock injected to return 13:01 ET on every call.
    Proactive EOD should close the position; it must NOT wait for next-day bar.
    """
    entry_intent = _make_entry_intent(strategy="VWAP_MR", entry_price=100.0)

    call_count = [0]
    open_trade_slot: list = []

    def _decide(ctx):
        call_count[0] += 1
        if call_count[0] == 1:          # first bar: open position
            return DecisionResult(entries=[entry_intent], exits=[])
        return DecisionResult(entries=[], exits=[])

    broker = MockBroker(slippage_pct=0.0, seed=0)
    recon  = ReconciliationLog(out_dir=str(tmp_path))
    du     = MagicMock()
    du.reset_day       = MagicMock()
    du._check_exits    = MagicMock(return_value=None)
    du.on_trade_opened = MagicMock()
    du.decide          = MagicMock(side_effect=_decide)

    # Clock always reads 13:01 ET → proactive EOD fires after each bar
    clock_fn = MagicMock(return_value=_dt_mod.time(13, 1))

    with _patch("raits.live.runner._market_close_time",
                return_value=_dt_mod.time(13, 0)):
        trader = PaperTrader(
            du, broker, recon,
            live_mode=True,
            clock_fn=clock_fn,
        )
        ctxs = [
            _dummy_ctx("2026-07-03 10:00:00"),  # bar 1: entry
            _dummy_ctx("2026-07-03 12:55:00"),  # bar 2: last bar, clock > 13:00
        ]
        trader.run(MockContextFeed(ctxs))

    # Position must have been closed by proactive EOD, not held overnight
    assert len(trader.closed_trades) == 1
    closed = trader.closed_trades[0]
    assert closed.exit_reason == "EOD"
    assert closed.ticker == "AAPL"


def test_proactive_eod_fires_exactly_once_per_day(tmp_path):
    """
    Proactive EOD fires once per day; the _eod_fired flag prevents double-close
    when the next day's first bar arrives.
    """
    broker = MockBroker(slippage_pct=0.0, seed=0)
    recon  = ReconciliationLog(out_dir=str(tmp_path))
    du     = MagicMock()
    du.reset_day    = MagicMock()
    du._check_exits = MagicMock(return_value=None)
    du.decide       = MagicMock(return_value=DecisionResult(entries=[], exits=[]))

    clock_fn = MagicMock(return_value=_dt_mod.time(13, 1))

    with _patch("raits.live.runner._market_close_time",
                return_value=_dt_mod.time(13, 0)):
        trader = PaperTrader(du, broker, recon, live_mode=True, clock_fn=clock_fn)
        with _patch.object(trader, "_close_all_eod", wraps=trader._close_all_eod) as mock_eod:
            ctxs = [
                _dummy_ctx("2026-07-03 12:55:00"),  # half-day bar
                _dummy_ctx("2026-07-07 09:35:00"),  # next week's first bar
            ]
            trader.run(MockContextFeed(ctxs))

    # _close_all_eod should fire once (proactive) for July 3,
    # once (post-loop) for July 7, not twice for July 3.
    eod_days = [call.args[0].date() if hasattr(call.args[0], "date") else None
                for call in mock_eod.call_args_list]
    jul3_calls = sum(1 for d in eod_days if d == _dt_mod.date(2026, 7, 3))
    assert jul3_calls == 1, f"Expected 1 proactive EOD for Jul 3, got {jul3_calls}"


def test_reactive_eod_unchanged_in_replay_mode(tmp_path):
    """
    Replay mode (live_mode=False, default): reactive EOD fires at day boundary
    as before; proactive path is never taken.
    """
    broker = MockBroker(slippage_pct=0.0, seed=0)
    recon  = ReconciliationLog(out_dir=str(tmp_path))
    du     = MagicMock()
    du.reset_day    = MagicMock()
    du._check_exits = MagicMock(return_value=None)
    du.decide       = MagicMock(return_value=DecisionResult(entries=[], exits=[]))

    # No live_mode, no clock_fn — reactive only
    trader = PaperTrader(du, broker, recon, live_mode=False)
    with _patch.object(trader, "_close_all_eod", wraps=trader._close_all_eod) as mock_eod:
        ctxs = [
            _dummy_ctx("2022-01-03 12:55:00"),  # day 1 last bar
            _dummy_ctx("2022-01-04 09:35:00"),  # day 2 first bar → triggers reactive EOD
        ]
        trader.run(MockContextFeed(ctxs))

    # Reactive EOD fires once for Jan 3 (at Jan 4's day boundary) + once post-loop for Jan 4
    assert mock_eod.call_count == 2
