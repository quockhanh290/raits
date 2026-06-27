"""
tests/decision/test_decision_unit.py
Unit tests for DecisionUnit — feed synthetic bar data, assert expected decisions.
"""
import pytest
import pandas as pd
import numpy as np
from datetime import date, time as dtime, datetime
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from raits.decision.decision_unit import DecisionUnit, _REGIME_STRATEGIES
from raits.decision.types import BarContext, DecisionResult, EntryIntent, ExitIntent
from raits.backtest.data_types import BacktestConfig, Trade


# ── Factories ─────────────────────────────────────────────────────────────────

def _make_config(**kwargs) -> BacktestConfig:
    defaults = dict(
        account_equity=50_000.0,
        orb_range_minutes=15,
        vwap_bb_std=2.0,
        ema_period=30,
        max_risk_pct=0.015,
        enable_pdt_guard=False,
        enable_costs=False,
        allow_swing_hold=False,
        stress_size_fraction=0.5,
        vwap_mr_vol_threshold=0.12,
    )
    defaults.update(kwargs)
    return BacktestConfig(**defaults)


def _make_bars(
    ticker: str,
    day: str,
    times: list,
    opens, highs, lows, closes, volumes,
) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame indexed by ET naive datetimes."""
    idx = pd.to_datetime([f"{day} {t}" for t in times])
    df = pd.DataFrame({
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": volumes,
    }, index=idx)
    df.index.name = "timestamp"
    return df


def _make_spy_bar(close: float = 450.0) -> pd.Series:
    ts = pd.Timestamp("2021-06-01 09:35:00")
    s = pd.Series({"open": 449.0, "high": 451.0, "low": 448.0, "close": close, "volume": 100_000})
    s.name = ts
    return s


def _make_trade(
    ticker: str = "AAPL",
    strategy: str = "ORB",
    direction: str = "LONG",
    entry_price: float = 150.0,
    stop: float = 148.0,
    target: float = 154.0,
    hmm_state: str = "Normal",
    entry_time: str = "2021-06-01 09:50:00",
) -> Trade:
    return Trade(
        trade_id=f"{ticker}-1",
        ticker=ticker,
        strategy=strategy,
        direction=direction,
        entry_time=pd.Timestamp(entry_time),
        entry_price=entry_price,
        shares=100,
        stop=stop,
        target=target,
        hmm_state=hmm_state,
        limiting_factor="KELLY",
    )


def _make_position_sizer(shares: int = 100):
    ps = MagicMock()
    ps.account_equity = 50_000.0
    ps.calculate.return_value = {
        "shares": shares,
        "position_value": shares * 150.0,
        "risk_dollars": shares * 2.0,
        "risk_pct": 0.004,
        "kelly_shares": shares,
        "vol_target_shares": shares,
        "position_limit_shares": shares * 2,
        "limiting_factor": "KELLY",
    }
    ps.calculate_vol_target_shares.return_value = shares
    ps.calculate_position_limit_shares.return_value = shares * 2
    return ps


def _make_decision_unit(config=None, position_sizer=None) -> DecisionUnit:
    config = config or _make_config()
    ps     = position_sizer or _make_position_sizer()

    # Mock coordinator — always allows trading
    coord = MagicMock()
    coord.trading_allowed      = True
    coord.effective_hmm_state  = "Normal"

    # Mock PDT guard — always passes
    pdt = MagicMock()
    pdt.check_can_day_trade.return_value = MagicMock(passed=True)

    # Mock strategies — return no signals by default
    orb       = MagicMock()
    orb.watchlist              = []
    orb.generate_signal.return_value = None
    orb.calculate_intraday_rvol.return_value = 1.0
    orb.calculate_opening_range.return_value = (155.0, 148.0, "VALID")
    orb.confirm_or_cancel.return_value = None

    stress_orb = MagicMock()
    stress_orb.watchlist       = []
    stress_orb.generate_signal.return_value = None

    fade_orb = MagicMock()
    fade_orb.watchlist         = []
    fade_orb.generate_signal.return_value = None

    vwap_mr = MagicMock()
    vwap_mr.calculate_vwap.return_value = 450.0
    vwap_mr.generate_signal.return_value = None
    vwap_mr.run_scanner.return_value     = None

    trend = MagicMock()
    trend.watchlist            = []
    trend.watchlist_directions = {}
    trend.generate_signal.return_value = None
    trend.run_scanner.return_value     = None
    trend.calculate_ema.return_value   = 149.5

    du = DecisionUnit(
        config=config,
        orb=orb,
        stress_orb=stress_orb,
        fade_orb=fade_orb,
        vwap_mr=vwap_mr,
        trend=trend,
        coordinator=coord,
        position_sizer=ps,
        pdt_guard=pdt,
    )
    return du


def _make_bar_context(
    bar_ts_str: str = "2021-06-01 10:00:00",
    hmm_state: str = "Normal",
    open_trades=None,
    day_stocks=None,
    market_data=None,
    spy_history=None,
) -> BarContext:
    bar_ts = pd.Timestamp(bar_ts_str)
    day    = bar_ts.normalize()

    _day_stocks   = day_stocks or {}
    _market_data  = market_data or {}
    _spy_history  = spy_history or [_make_spy_bar()]
    _open_trades  = open_trades or []

    return BarContext(
        bar_ts=bar_ts,
        spy_bar=_make_spy_bar(),
        spy_history=_spy_history,
        day_stocks=_day_stocks,
        market_data=_market_data,
        open_trades=_open_trades,
        hmm_state=hmm_state,
        cur_vol=0.15,
        day=day,
        orb_vix_ok=True,
        stress_orb_vix_ok=False,
        effective_orb_universe=["AAPL"],
        effective_vwap_universe=[],
        effective_fade_universe=[],
        all_tickers=["AAPL"],
        base_universe=["AAPL"],
        stress_stocks={"SPY": pd.DataFrame()},
        spy_or_high=451.0,
        spy_or_low=448.0,
        spy_bull_trend=True,
        daily_spy_close=pd.Series([440.0, 445.0, 450.0], dtype=float),
        pe_short_calendar={},
        fade_atr_top2=set(),
        vwap_bb_std=2.0,
        ema_period=30,
        vwap_mr_vol_threshold=0.12,
        allow_swing_hold=False,
        enable_pdt_guard=False,
        stress_size_fraction=0.5,
        orb_signal_start=dtime(9, 45),
        orb_signal_end=dtime(10, 15),
    )


# ── Tests: reset_day ──────────────────────────────────────────────────────────

class TestResetDay:
    def test_clears_or_ranges(self):
        du = _make_decision_unit()
        du.or_ranges["AAPL"] = (155.0, 148.0)
        du.reset_day(pd.Timestamp("2021-06-02"), dtime(9, 45), dtime(10, 15))
        assert du.or_ranges == {}

    def test_clears_pending_orb(self):
        du = _make_decision_unit()
        du.pending_orb["AAPL"] = {"direction": "LONG"}
        du.reset_day(pd.Timestamp("2021-06-02"), dtime(9, 45), dtime(10, 15))
        assert du.pending_orb == {}

    def test_clears_intraday_flags(self):
        du = _make_decision_unit()
        du._gf_triggered = True
        du._pe_triggered = True
        du.reset_day(pd.Timestamp("2021-06-02"), dtime(9, 45), dtime(10, 15))
        assert not du._gf_triggered
        assert not du._pe_triggered

    def test_tf_cooldown_persists_across_days(self):
        """_tf_cooldown is cross-day state — reset_day must NOT clear it."""
        du = _make_decision_unit()
        du._tf_cooldown["AAPL"] = {"LONG": 148.0}
        du.reset_day(pd.Timestamp("2021-06-02"), dtime(9, 45), dtime(10, 15))
        assert du._tf_cooldown.get("AAPL") == {"LONG": 148.0}

    def test_resets_strategies(self):
        du = _make_decision_unit()
        du.reset_day(pd.Timestamp("2021-06-02"), dtime(9, 45), dtime(10, 15))
        du.orb.reset.assert_called_once()
        du.stress_orb.reset.assert_called_once()
        du.fade_orb.reset.assert_called_once()


# ── Tests: decide() with no signals ──────────────────────────────────────────

class TestDecideEmpty:
    def test_returns_empty_when_no_data(self):
        du  = _make_decision_unit()
        du.reset_day(pd.Timestamp("2021-06-01"), dtime(9, 45), dtime(10, 15))
        ctx = _make_bar_context()
        res = du.decide(ctx)
        assert isinstance(res, DecisionResult)
        assert res.entries == []
        assert res.exits   == []
        assert not res.override_active

    def test_does_not_raise_on_empty_context(self):
        du = _make_decision_unit()
        du.reset_day(pd.Timestamp("2021-06-01"), dtime(9, 45), dtime(10, 15))
        ctx = _make_bar_context(bar_ts_str="2021-06-01 14:30:00")
        # Should not raise
        du.decide(ctx)


# ── Tests: SAFETY_MODE (override active) ─────────────────────────────────────

class TestSafetyMode:
    def test_returns_exits_for_intraday_positions_when_override_active(self):
        du = _make_decision_unit()
        du.coordinator.trading_allowed = False  # triggers safety mode path

        trade = _make_trade(strategy="ORB", ticker="AAPL", direction="LONG",
                            entry_price=150.0, stop=148.0)
        day   = "2021-06-01"
        bars  = _make_bars("AAPL", day,
                           ["10:00:00"], [150.0], [152.0], [149.0], [151.0], [50000])
        bar_ts_str = "2021-06-01 10:00:00"

        du.reset_day(pd.Timestamp(day), dtime(9, 45), dtime(10, 15))
        ctx = _make_bar_context(
            bar_ts_str=bar_ts_str,
            open_trades=[trade],
            day_stocks={"AAPL": bars},
        )
        res = du.decide(ctx)

        assert res.override_active
        assert len(res.exits) == 1
        assert res.exits[0].reason == "SAFETY_MODE"
        assert res.exits[0].trade is trade

    def test_safety_mode_does_not_close_tf_positions(self):
        """TREND_FOLLOW swing positions survive SAFETY_MODE."""
        du = _make_decision_unit()
        du.coordinator.trading_allowed = False

        tf_trade = _make_trade(strategy="TREND_FOLLOW", ticker="AAPL")
        du.reset_day(pd.Timestamp("2021-06-01"), dtime(9, 45), dtime(10, 15))
        ctx = _make_bar_context(open_trades=[tf_trade])
        res = du.decide(ctx)

        # TF trade should not be in the SAFETY_MODE exits
        safety_exits = [e for e in res.exits if e.reason == "SAFETY_MODE"]
        assert all(e.trade is not tf_trade for e in safety_exits)


# ── Tests: stop / target exits ────────────────────────────────────────────────

class TestExitDetection:
    def _run_bar_with_trade(self, trade, bar_ts_str, high, low, close):
        du = _make_decision_unit()
        du.coordinator.trading_allowed = True
        ticker = trade.ticker
        day    = pd.Timestamp(bar_ts_str).date().strftime("%Y-%m-%d")
        t_str  = pd.Timestamp(bar_ts_str).time().strftime("%H:%M:%S")
        bars   = _make_bars(ticker, day, [t_str], [close], [high], [low], [close], [10_000])
        du.reset_day(pd.Timestamp(day), dtime(9, 45), dtime(10, 15))
        ctx = _make_bar_context(
            bar_ts_str=bar_ts_str,
            open_trades=[trade],
            day_stocks={ticker: bars},
        )
        return du.decide(ctx)

    def test_long_stop_hit(self):
        trade = _make_trade(direction="LONG", stop=148.0, target=155.0)
        # Bar low goes below stop
        res   = self._run_bar_with_trade(trade, "2021-06-01 10:30:00",
                                         high=150.5, low=147.5, close=149.0)
        exits = [e for e in res.exits if e.trade is trade and e.reason == "STOP_HIT"]
        assert len(exits) == 1
        assert exits[0].exit_price == 148.0

    def test_long_target_hit(self):
        trade = _make_trade(direction="LONG", stop=148.0, target=155.0)
        res   = self._run_bar_with_trade(trade, "2021-06-01 10:30:00",
                                         high=156.0, low=150.0, close=155.5)
        exits = [e for e in res.exits if e.trade is trade and e.reason == "TARGET_HIT"]
        assert len(exits) == 1

    def test_short_stop_hit(self):
        trade = _make_trade(direction="SHORT", stop=153.0, target=145.0)
        res   = self._run_bar_with_trade(trade, "2021-06-01 10:30:00",
                                         high=154.0, low=149.0, close=151.0)
        exits = [e for e in res.exits if e.trade is trade and e.reason == "STOP_HIT"]
        assert len(exits) == 1

    def test_eod_exit_at_1555(self):
        trade = _make_trade(direction="LONG", stop=148.0, target=200.0)
        res   = self._run_bar_with_trade(trade, "2021-06-01 15:55:00",
                                         high=151.0, low=149.0, close=150.5)
        exits = [e for e in res.exits if e.trade is trade and e.reason == "EOD"]
        assert len(exits) == 1

    def test_tf_stop_hit_updates_cooldown(self):
        """After a TF STOP_HIT is detected, _tf_cooldown is updated immediately."""
        du    = _make_decision_unit()
        trade = _make_trade(strategy="TREND_FOLLOW", direction="LONG", stop=148.0, target=200.0)
        ticker = trade.ticker
        day    = "2021-06-01"
        bars   = _make_bars(ticker, day, ["10:30:00"], [150.0], [150.5], [147.0], [149.0], [10_000])
        du.reset_day(pd.Timestamp(day), dtime(9, 45), dtime(10, 15))
        ctx = _make_bar_context(
            bar_ts_str="2021-06-01 10:30:00",
            open_trades=[trade],
            day_stocks={ticker: bars},
        )
        du.decide(ctx)
        # Cooldown must be recorded for LONG direction at the stop price
        assert du._tf_cooldown.get(ticker, {}).get("LONG") == 148.0


# ── Tests: on_trade_opened ────────────────────────────────────────────────────

class TestOnTradeOpened:
    def test_registers_gf_stop_dist(self):
        du     = _make_decision_unit()
        trade  = _make_trade(strategy="GAP_FILL")
        intent = EntryIntent(
            ticker="AAPL", strategy="GAP_FILL", direction="LONG",
            entry_price=150.0, shares=100, stop=148.0, target=153.0,
            is_day_trade=True, limiting_factor="KELLY", hmm_state="Normal",
            gf_stop_dist=2.0,
        )
        du.on_trade_opened(trade, intent)
        assert du._gf_stop_dists.get(id(trade)) == 2.0

    def test_registers_gf_short_stop_dist(self):
        du     = _make_decision_unit()
        trade  = _make_trade(strategy="GF_SHORT")
        intent = EntryIntent(
            ticker="AAPL", strategy="GF_SHORT", direction="SHORT",
            entry_price=150.0, shares=100, stop=152.0, target=147.0,
            is_day_trade=True, limiting_factor="KELLY", hmm_state="Normal",
            gf_stop_dist=1.5,
        )
        du.on_trade_opened(trade, intent)
        assert du._gfs_stop_dists.get(id(trade)) == 1.5

    def test_no_gf_dist_for_normal_trade(self):
        du     = _make_decision_unit()
        trade  = _make_trade(strategy="ORB")
        intent = EntryIntent(
            ticker="AAPL", strategy="ORB", direction="LONG",
            entry_price=150.0, shares=100, stop=148.0, target=154.0,
            is_day_trade=True, limiting_factor="KELLY", hmm_state="Normal",
            gf_stop_dist=None,
        )
        du.on_trade_opened(trade, intent)
        assert id(trade) not in du._gf_stop_dists
        assert id(trade) not in du._gfs_stop_dists


# ── Tests: position limits ────────────────────────────────────────────────────

class TestPositionLimits:
    def test_rejects_duplicate_ticker(self):
        du      = _make_decision_unit()
        trade   = _make_trade(ticker="AAPL")
        pending = []
        assert not du._position_ok("AAPL", "ORB", [trade], pending)

    def test_rejects_when_max_total_reached(self):
        du      = _make_decision_unit()
        # MAX_TOTAL = 8
        trades  = [_make_trade(ticker=f"T{i}") for i in range(8)]
        pending = []
        assert not du._position_ok("NEW", "ORB", trades, pending)

    def test_rejects_when_strategy_cap_reached(self):
        du      = _make_decision_unit()
        # MAX_ORB = 2
        trades  = [_make_trade(ticker=f"O{i}", strategy="ORB") for i in range(2)]
        pending = []
        assert not du._position_ok("NEW", "ORB", trades, pending)

    def test_counts_pending_entries(self):
        du      = _make_decision_unit()
        trades  = []
        # Two ORB pending entries already hits the MAX_ORB=2 cap
        pending = [
            EntryIntent("O0", "ORB", "LONG", 150, 100, 148, 154, True, "KELLY", "Normal"),
            EntryIntent("O1", "ORB", "LONG", 150, 100, 148, 154, True, "KELLY", "Normal"),
        ]
        assert not du._position_ok("NEW", "ORB", trades, pending)

    def test_allows_when_within_limits(self):
        du      = _make_decision_unit()
        trade   = _make_trade(ticker="AAPL", strategy="ORB")
        pending = []
        assert du._position_ok("MSFT", "ORB", [trade], pending)
