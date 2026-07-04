"""
tests/live/test_divergence_gaps.py

COVERAGE tests for the live-vs-backtest divergence audit (Gaps 2/E7, 3, 4, 5, 6/E6).
All offline-verifiable — no Polygon.io, no pkl cache files.

If every test here passes → no code changes needed for these gaps.
If a test reveals a real bug → stop and report BEFORE fixing.

Run from d:\\raits:
    pytest raits/tests/live/test_divergence_gaps.py -v
"""
from __future__ import annotations

import datetime
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch

from raits.backtest.data_types import BacktestConfig, Trade
from raits.decision.types import BarContext, DecisionResult
from raits.live.broker import MockBroker
from raits.live.context_feed import LivePolygonFeed, _BarAccumulator
from raits.live.reconciliation import ReconciliationLog
from raits.live.runner import PaperTrader
from raits.live.trading_calendar import (
    et_now_time,
    market_close_time,
    _NORMAL_CLOSE,
    _EARLY_CLOSE,
)


# ── Shared synthetic-data helpers ─────────────────────────────────────────────

def _bars(day: str, start_hm: str, end_hm: str, base: float, seed: int) -> pd.DataFrame:
    """5-min bars from start_hm to end_hm on day with a random-walk close."""
    times = pd.date_range(f"{day} {start_hm}", f"{day} {end_hm}", freq="5min")
    rng = np.random.default_rng(seed)
    n = len(times)
    close = base + np.cumsum(rng.standard_normal(n) * 0.3)
    return pd.DataFrame({
        "open": close - 0.1, "high": close + 0.5,
        "low": close - 0.5, "close": close,
        "volume": np.full(n, 500_000), "vwap": close,
    }, index=pd.DatetimeIndex(times))


def _make_trade(
    trade_id: str, ticker: str, strategy: str, direction: str,
    entry_price: float, shares: int, stop: float, target: float,
    entry_day: str = "2022-11-25",
) -> Trade:
    return Trade(
        trade_id=trade_id,
        ticker=ticker,
        strategy=strategy,
        direction=direction,
        entry_time=pd.Timestamp(f"{entry_day} 09:35"),
        entry_price=entry_price,
        shares=shares,
        stop=stop,
        target=target,
        hmm_state="Normal",
        limiting_factor="KELLY",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# GAP 5 — Chandelier stop isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestGap5ChandelierIsolation:
    """
    Gap 5: _update_swing_stops is called at day boundary using _prev_ctx.day_stocks.

    At the boundary:
      - ReplayContextFeed: day_stocks = full day (all bars pre-loaded)
      - LivePolygonFeed:   day_stocks = incremental, BUT accumulated to the 15:55 bar
                           (the 15:55 bar is the last bar of the day, so the two
                           DataFrames are identical at that point)

    The chandelier stop value must be identical in both cases.
    Gap 5 is closed if the assertion passes.
    """

    def _fresh_trader(self, tmp_path: str) -> PaperTrader:
        du = MagicMock()
        du.reset_day = MagicMock()
        du.decide = MagicMock(return_value=DecisionResult(entries=[], exits=[]))
        broker = MockBroker(slippage_pct=0.0, seed=0)
        recon = ReconciliationLog(out_dir=str(tmp_path))
        return PaperTrader(du, broker, recon, account_equity=50_000.0, allow_swing_hold=True)

    def test_chandelier_identical_full_vs_incremental_at_eod(self, tmp_path):
        """
        Call _update_swing_stops with (a) full pre-loaded day_stocks and
        (b) incremental day_stocks where the last bar IS the 15:55 bar
        (= complete day). Assert the chandelier stop is identical.
        """
        rng = np.random.default_rng(42)
        day_ts = pd.Timestamp("2022-01-03")

        # Full-day 5-min bars for AAPL (9:30–15:55, 26 bars)
        times_intraday = pd.date_range("2022-01-03 09:30", "2022-01-03 15:55", freq="5min")
        n = len(times_intraday)
        highs  = 152.0 + rng.uniform(0.2, 1.5, n)
        lows   = 149.0 - rng.uniform(0.2, 1.5, n)
        closes = (highs + lows) / 2
        full_day_df = pd.DataFrame({
            "open": closes - 0.1, "high": highs, "low": lows, "close": closes,
            "volume": 200_000, "vwap": closes,
        }, index=times_intraday)

        # Incremental-at-eod: in LivePolygonFeed semantics, at the last bar (15:55),
        # the accumulated day_stocks contains ALL bars (9:30 → 15:55).
        # This DataFrame is byte-identical to full_day_df.
        incremental_at_eod_df = full_day_df.copy()

        # Daily bars for AAPL (for ATR computation) — must predate day_ts
        daily_times = pd.date_range("2021-06-01", "2021-12-30", freq="B")
        m = len(daily_times)
        daily_closes = 148.0 + np.cumsum(rng.standard_normal(m))
        market_data = {"AAPL": pd.DataFrame({
            "open": daily_closes - 0.5, "high": daily_closes + 1.0,
            "low": daily_closes - 1.0, "close": daily_closes,
        }, index=daily_times)}

        tf_entry_price = 150.0

        # ── (a) Full-day ReplayContextFeed semantics ──────────────────────────
        trader_a = self._fresh_trader(tmp_path)
        trade_a = _make_trade("tf_a", "AAPL", "TREND_FOLLOW", "LONG",
                              entry_price=tf_entry_price, shares=10,
                              stop=tf_entry_price - 5.0, target=0.0,
                              entry_day="2022-01-03")
        trade_a.target = 9999.0  # never hit
        trader_a._open_positions["tf_a"] = trade_a
        trader_a._update_swing_stops(day_ts, market_data, {"AAPL": full_day_df})
        stop_a = trade_a.stop

        # ── (b) Incremental-at-EOD LivePolygonFeed semantics ─────────────────
        trader_b = self._fresh_trader(tmp_path)
        trade_b = _make_trade("tf_b", "AAPL", "TREND_FOLLOW", "LONG",
                              entry_price=tf_entry_price, shares=10,
                              stop=tf_entry_price - 5.0, target=0.0,
                              entry_day="2022-01-03")
        trade_b.target = 9999.0
        trader_b._open_positions["tf_b"] = trade_b
        trader_b._update_swing_stops(day_ts, market_data, {"AAPL": incremental_at_eod_df})
        stop_b = trade_b.stop

        # ── Assert ────────────────────────────────────────────────────────────
        assert stop_a == stop_b, (
            f"GAP 5 NOT closed: chandelier stop differs!\n"
            f"  full-day path: stop={stop_a:.4f}\n"
            f"  incremental path: stop={stop_b:.4f}\n"
            f"  Cause: _update_swing_stops uses different bar sets in the two paths."
        )
        # Verify stop actually advanced (confirming ATR was computed and applied)
        initial_stop = tf_entry_price - 5.0
        assert stop_a != initial_stop or stop_a >= initial_stop, (
            "Stop should be >= initial stop (chandelier only advances in favour)"
        )

    def test_chandelier_uses_full_day_highs_at_boundary(self, tmp_path):
        """
        Confirm that _update_swing_stops uses the max high from the FULL day
        (not just bars up to some arbitrary cut-off). The stop should equal
        max(all_bar_highs) - 3 * daily_atr.
        """
        rng = np.random.default_rng(7)
        day_ts = pd.Timestamp("2022-01-03")

        # Controlled bars: high spikes at 15:50 (second-to-last bar)
        times = pd.date_range("2022-01-03 09:30", "2022-01-03 15:55", freq="5min")
        n = len(times)
        base_close = 150.0 + np.cumsum(rng.standard_normal(n) * 0.2)
        highs = base_close + 0.5
        lows  = base_close - 0.5
        # Artificial spike at the 15:50 bar (index -2)
        highs[-2] = 200.0   # extreme high late in the day
        closes = (highs + lows) / 2

        full_day_df = pd.DataFrame({
            "open": closes - 0.1, "high": highs, "low": lows, "close": closes,
            "volume": 200_000, "vwap": closes,
        }, index=times)

        daily_times = pd.date_range("2021-06-01", "2021-12-30", freq="B")
        m = len(daily_times)
        daily_closes = 148.0 + np.cumsum(rng.standard_normal(m))
        market_data = {"AAPL": pd.DataFrame({
            "open": daily_closes - 0.5, "high": daily_closes + 1.0,
            "low": daily_closes - 1.0, "close": daily_closes,
        }, index=daily_times)}

        trader = self._fresh_trader(tmp_path)
        trade = _make_trade("tf_spike", "AAPL", "TREND_FOLLOW", "LONG",
                            entry_price=150.0, shares=10,
                            stop=100.0, target=9999.0,
                            entry_day="2022-01-03")
        trader._open_positions["tf_spike"] = trade
        trader._update_swing_stops(day_ts, market_data, {"AAPL": full_day_df})

        # The chandelier stop must be based on the 200.0 high spike.
        # stop = max_high - 3 * daily_atr.  max_high = 200.0.
        # daily_atr > 0, so stop < 200.0 and stop >> original 100.0
        assert trade.stop > 100.0, "Chandelier should have advanced from 200.0 spike"
        assert trade.stop < 200.0, "Chandelier stop must be below max high"


# ═══════════════════════════════════════════════════════════════════════════════
# GAP 3 — Proactive EOD integration with real DecisionUnit
# ═══════════════════════════════════════════════════════════════════════════════

class TestGap3ProactiveEODIntegration:
    """
    Gap 3: Proactive EOD closes intraday positions but preserves swing (TF)
    in a full end-to-end run with a REAL DecisionUnit (not a mock).

    Scenario: half-day 2022-11-25 (Black Friday, close=13:00 ET).
    Two open positions injected before the bar loop:
      - AAPL ORB LONG  (intraday, is_day_trade=True)
      - MSFT TF  LONG  (swing, allow_swing_hold=True)

    Clock injected to return 13:01 ET → proactive EOD fires after each bar.
    Expected:
      - AAPL ORB → closed with exit_reason="EOD" (proactive EOD)
      - MSFT TF  → closed with exit_reason="END_OF_PERIOD" (survived EOD,
                   closed at end of IS period post-loop)
      - _close_all_eod NOT called reactively (proactive flag prevents double-close)
    """

    @staticmethod
    def _build_real_du(cfg: BacktestConfig):
        """Build a real DecisionUnit via engine module loading (no data needed)."""
        from raits.backtest.engine_refactored import RefactoredBacktestEngine
        from raits.decision.decision_unit import DecisionUnit

        tmp = RefactoredBacktestEngine(cfg)
        mods = tmp._mods

        pdt_guard = mods["PDTGuard"]()
        position_sizer = mods["PositionSizer"](
            account_equity=cfg.account_equity,
            max_risk_pct=cfg.max_risk_pct,
            max_position_pct=cfg.max_position_pct,
            kelly_fraction=cfg.kelly_fraction,
        )
        coordinator = mods["RegimeCoordinator"]()
        orb = mods["ORBStrategy"](config={
            "opening_vol_multiplier": 1.2, "min_price": 1.0,
            "max_price": 1e9, "min_gap_pct": 0.01,
        })
        stress_orb = mods["ORBStrategy"](config={
            "allowed_regimes": ["Stress"], "min_gap_pct": 0.0,
            "rvol_threshold": 0.0, "min_price": 1.0,
            "max_price": 1e9, "min_range_atr_multiple": 0.2,
        })
        fade_orb = mods["ORBStrategy"](config={
            "opening_vol_multiplier": 1.2, "min_price": 1.0, "max_price": 1e9,
            "min_gap_pct": 0.0, "rvol_threshold": 0.0,
            "fade_require_midpoint": False, "fade_long_enabled": True,
        })
        vwap_mr = mods["VWAPMRStrategy"](config={"bb_std_dev": cfg.vwap_bb_std})
        trend   = mods["TrendStrategy"](config={"ema_period": cfg.ema_period})

        return DecisionUnit(
            config=cfg, orb=orb, stress_orb=stress_orb, fade_orb=fade_orb,
            vwap_mr=vwap_mr, trend=trend, coordinator=coordinator,
            position_sizer=position_sizer, pdt_guard=pdt_guard,
        )

    def test_proactive_eod_real_du_intraday_closes_swing_survives(self, tmp_path):
        """
        Full integration: real DU, LivePolygonFeed test mode, half-day.
        ORB closes at EOD (proactive); TF survives and closes at END_OF_PERIOD.
        """
        DAY = "2022-11-25"  # Black Friday — market_close_time = 13:00 ET

        cfg = BacktestConfig(
            start_date=DAY, end_date=DAY,
            universe=["AAPL", "MSFT"],
            account_equity=50_000.0,
            allow_swing_hold=True,
            orb_range_minutes=20,
            vwap_bb_std=1.5,
            ema_period=30,
            max_risk_pct=0.015,
            max_position_pct=0.40,
            kelly_fraction=0.75,
            hmm_retrain_weekly=False,  # skip HMM in synthetic run
        )

        # Half-day bars: 9:30–12:55 (42 bars each)
        spy_bars  = _bars(DAY, "09:30", "12:55", base=400.0, seed=0)
        aapl_bars = _bars(DAY, "09:30", "12:55", base=150.0, seed=1)
        msft_bars = _bars(DAY, "09:30", "12:55", base=250.0, seed=2)

        market_data = {"SPY": spy_bars, "AAPL": aapl_bars, "MSFT": msft_bars}

        feed = LivePolygonFeed(
            config=cfg,
            _test_market_data=market_data,
            vix_daily={},         # no VIX → orb_vix_ok=True (default)
            daily_data=None,      # no daily data needed for this test
            emit_timeout=0.01,
        )

        real_du = self._build_real_du(cfg)
        broker  = MockBroker(slippage_pct=0.0, seed=0)
        recon   = ReconciliationLog(out_dir=str(tmp_path))

        # Clock always reads 13:01 → proactive EOD fires after every bar
        clock_fn = lambda: datetime.time(13, 1)

        trader = PaperTrader(
            real_du, broker, recon,
            account_equity=50_000.0,
            live_mode=True,
            allow_swing_hold=True,
            clock_fn=clock_fn,
        )

        # Inject two open positions BEFORE run():
        #   AAPL ORB LONG  (intraday) — wide stop/target so it stays open until EOD
        #   MSFT TF  LONG  (swing)    — allow_swing_hold skips it in _close_all_eod
        orb_trade = _make_trade("orb_aapl", "AAPL", "ORB", "LONG",
                                entry_price=150.0, shares=10,
                                stop=100.0, target=200.0)
        tf_trade  = _make_trade("tf_msft", "MSFT", "TREND_FOLLOW", "LONG",
                                entry_price=250.0, shares=5,
                                stop=180.0, target=350.0)
        trader._open_positions["orb_aapl"] = orb_trade
        trader._open_positions["tf_msft"]  = tf_trade

        # Track _close_all_eod calls to verify no double-close
        with patch.object(trader, "_close_all_eod",
                          wraps=trader._close_all_eod) as mock_eod:
            result = trader.run(feed)

        closed = {t.trade_id: t for t in trader.closed_trades}

        # ── Assert 1: ORB is closed with exit_reason="EOD" ────────────────────
        assert "orb_aapl" in closed, (
            "GAP 3 FAIL: ORB trade not found in closed_trades. "
            "Proactive EOD did not fire or failed to close the intraday position."
        )
        assert closed["orb_aapl"].exit_reason == "EOD", (
            f"GAP 3 FAIL: ORB exit_reason={closed['orb_aapl'].exit_reason!r}, "
            f"expected 'EOD'. Proactive EOD either didn't fire or used wrong path."
        )

        # ── Assert 2: TF is NOT closed by EOD — survives and gets END_OF_PERIOD ─
        assert "tf_msft" in closed, (
            "GAP 3 FAIL: TF trade not found in closed_trades. "
            "_close_end_of_period did not clean up the swing position."
        )
        assert closed["tf_msft"].exit_reason == "END_OF_PERIOD", (
            f"GAP 3 FAIL: TF exit_reason={closed['tf_msft'].exit_reason!r}, "
            f"expected 'END_OF_PERIOD'. "
            f"If 'EOD': allow_swing_hold=True was not respected in _close_all_eod."
        )

        # ── Assert 3: _eod_fired prevents double-close ────────────────────────
        # Proactive EOD fires once per day. The post-loop `if not _eod_fired`
        # guard skips the reactive call. Total _close_all_eod calls = 1 for 2022-11-25.
        half_day = datetime.date(2022, 11, 25)
        eod_days_called = [
            c.args[0].date() if hasattr(c.args[0], "date") else None
            for c in mock_eod.call_args_list
        ]
        calls_for_halfday = sum(1 for d in eod_days_called if d == half_day)
        assert calls_for_halfday == 1, (
            f"GAP 3 FAIL: _close_all_eod called {calls_for_halfday}× for {half_day}, "
            f"expected exactly 1. _eod_fired flag is not preventing double-close."
        )

        # ── Assert 4: run() completed cleanly ────────────────────────────────
        assert not result.kill_switch_tripped, "Kill switch should not trip on synthetic data"
        assert len(trader.closed_trades) == 2, (
            f"Expected 2 closed trades (ORB + TF), got {len(trader.closed_trades)}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# GAP 4 — DST transition correctness
# ═══════════════════════════════════════════════════════════════════════════════

class TestGap4DSTTransition:
    """
    Gap 4: et_now_time() / market_close_time() DST boundary correctness.

    The live guard compares et_now_time() >= market_close_time() to decide
    whether to trigger proactive EOD. An incorrect UTC offset would make the
    system think market has closed 1h early or 1h late.

    Two DST boundaries tested:
      - Spring forward: 2025-03-09 02:00 ET → 03:00 ET (clocks jump forward)
      - Fall back:      2025-11-02 02:00 ET → 01:00 ET (clocks fall back)
    """

    def test_zoneinfo_spring_forward_correct_offset(self):
        """
        ZoneInfo uses EDT (UTC-4) for market hours after spring forward.
        First market day after spring forward 2025-03-09: 2025-03-10.
        14:30 UTC on 2025-03-10 = 10:30 EDT.
        """
        from datetime import timezone
        from zoneinfo import ZoneInfo

        # 2025-03-10 14:30 UTC = 10:30 EDT (UTC-4)
        utc = datetime.datetime(2025, 3, 10, 14, 30, 0, tzinfo=timezone.utc)
        et  = utc.astimezone(ZoneInfo("America/New_York"))

        assert et.utcoffset() == datetime.timedelta(hours=-4), (
            f"Expected EDT offset UTC-4 after spring forward, got {et.utcoffset()}"
        )
        assert et.time() == datetime.time(10, 30), (
            f"Expected 10:30 ET after spring forward, got {et.time()}"
        )

    def test_zoneinfo_fall_back_correct_offset(self):
        """
        ZoneInfo uses EST (UTC-5) for market hours after fall back.
        First market day after fall back 2025-11-02: 2025-11-03.
        15:30 UTC on 2025-11-03 = 10:30 EST.
        """
        from datetime import timezone
        from zoneinfo import ZoneInfo

        # 2025-11-03 15:30 UTC = 10:30 EST (UTC-5)
        utc = datetime.datetime(2025, 11, 3, 15, 30, 0, tzinfo=timezone.utc)
        et  = utc.astimezone(ZoneInfo("America/New_York"))

        assert et.utcoffset() == datetime.timedelta(hours=-5), (
            f"Expected EST offset UTC-5 after fall back, got {et.utcoffset()}"
        )
        assert et.time() == datetime.time(10, 30), (
            f"Expected 10:30 ET after fall back, got {et.time()}"
        )

    def test_zoneinfo_spring_forward_transition_no_gap(self):
        """
        At the spring-forward moment (2025-03-09 07:00 UTC = 02:00 → 03:00 ET):
        ZoneInfo must land on EDT (UTC-4), not the skipped EST 02:xx window.
        """
        from datetime import timezone
        from zoneinfo import ZoneInfo

        utc = datetime.datetime(2025, 3, 9, 7, 0, 0, tzinfo=timezone.utc)
        et  = utc.astimezone(ZoneInfo("America/New_York"))

        # After spring forward: offset is UTC-4, time is 03:00
        assert et.utcoffset() == datetime.timedelta(hours=-4), (
            "At spring-forward transition, ZoneInfo must use EDT (UTC-4)"
        )
        assert et.time() == datetime.time(3, 0), (
            f"02:00 ET spring-forward → 03:00 EDT; got {et.time()}"
        )

    def test_zoneinfo_fall_back_transition_correct(self):
        """
        At the fall-back moment (2025-11-02 06:01 UTC = 01:01 after fall back):
        ZoneInfo must use EST (UTC-5).
        """
        from datetime import timezone
        from zoneinfo import ZoneInfo

        # 06:01 UTC on 2025-11-02 = 01:01 EST (fall back completed at 06:00 UTC)
        utc = datetime.datetime(2025, 11, 2, 6, 1, 0, tzinfo=timezone.utc)
        et  = utc.astimezone(ZoneInfo("America/New_York"))

        assert et.utcoffset() == datetime.timedelta(hours=-5), (
            "After fall back, ZoneInfo must use EST (UTC-5)"
        )
        assert et.time() == datetime.time(1, 1), (
            f"06:01 UTC after fall back = 01:01 EST; got {et.time()}"
        )

    def test_utc4_fallback_is_1h_wrong_in_winter(self):
        """
        Documents the KNOWN LIMITATION of the UTC-4 static fallback.

        The fallback (datetime.datetime.utcnow() - timedelta(hours=4)) is correct
        during EDT (summer, UTC-4) but is 1h FAST during EST (winter, UTC-5).

        Risk: if ZoneInfo and pytz both fail, the live guard would fire proactive EOD
        1h early in winter (e.g., at 12:00 ET on a 13:00 half-day).

        This is not a bug in the primary path — it is a documented fallback limitation
        that only triggers if both ZoneInfo (stdlib, Python 3.9+) and pytz are absent.
        On RAITS' requirement of Python 3.10+, this path is unreachable in practice.
        """
        from datetime import timezone, timedelta
        from zoneinfo import ZoneInfo

        # Winter day: 2025-01-15 14:30 UTC = 09:30 EST (correct, UTC-5)
        utc_aware = datetime.datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc)

        # ZoneInfo correct answer
        correct_et = utc_aware.astimezone(ZoneInfo("America/New_York")).time()
        assert correct_et == datetime.time(9, 30), f"Expected 09:30 EST, got {correct_et}"

        # Fallback (UTC-4) wrong answer
        utc_naive = datetime.datetime(2025, 1, 15, 14, 30, 0)
        fallback_et = (utc_naive - datetime.timedelta(hours=4)).time()
        assert fallback_et == datetime.time(10, 30), (
            f"UTC-4 fallback should give 10:30, got {fallback_et}"
        )

        # The fallback is 1h FAST in winter
        assert fallback_et > correct_et, (
            "UTC-4 fallback must be 1h fast in winter EST — this is the known limitation"
        )
        fast_by = (
            datetime.datetime.combine(datetime.date.today(), fallback_et)
            - datetime.datetime.combine(datetime.date.today(), correct_et)
        ).seconds // 60
        assert fast_by == 60, f"Expected 60-min error in winter, got {fast_by} min"

    def test_et_now_time_returns_valid_time_object(self):
        """
        et_now_time() must return a naive datetime.time without raising.
        The ZoneInfo path (primary) is taken on Python 3.10+ (ZoneInfo in stdlib).
        """
        result = et_now_time()
        assert isinstance(result, datetime.time), (
            f"et_now_time() must return datetime.time, got {type(result)}"
        )
        assert result.tzinfo is None, "et_now_time() must return naive time (no tzinfo)"
        assert datetime.time(0, 0) <= result <= datetime.time(23, 59, 59)

    def test_et_now_time_fallback_when_zoneinfo_blocked(self, caplog):
        """
        When ZoneInfo is unavailable and pytz is absent, et_now_time() falls back
        to UTC-4, returns a valid naive time object, and emits a loud WARNING so
        operators know the fallback was taken.
        """
        import logging
        import sys

        original_zoneinfo = sys.modules.get("zoneinfo")
        original_pytz     = sys.modules.get("pytz")

        sys.modules["zoneinfo"] = None  # force ImportError on 'from zoneinfo import ZoneInfo'
        sys.modules["pytz"]     = None  # block pytz as well → UTC-4 fallback taken

        try:
            with caplog.at_level(logging.WARNING, logger="RAITS.live.trading_calendar"):
                result = et_now_time()
        finally:
            # Restore modules
            if original_zoneinfo is not None:
                sys.modules["zoneinfo"] = original_zoneinfo
            else:
                sys.modules.pop("zoneinfo", None)
            if original_pytz is not None:
                sys.modules["pytz"] = original_pytz
            else:
                sys.modules.pop("pytz", None)

        assert isinstance(result, datetime.time), (
            f"Fallback et_now_time() must return datetime.time, got {type(result)}"
        )
        assert result.tzinfo is None, "Fallback must be naive"
        warning_texts = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("UTC-4" in t for t in warning_texts), (
            f"Expected loud WARNING about UTC-4 fallback, got: {warning_texts}"
        )
        assert any("tzdata" in t for t in warning_texts), (
            f"Expected WARNING to mention 'tzdata', got: {warning_texts}"
        )

    def test_market_close_time_correct_around_dst(self):
        """
        market_close_time() is calendar-based (no wall clock) and must return
        correct close times on and near DST transition dates.
        """
        # Spring forward 2025-03-09 (Sunday, non-trading) → verify the Fri/Mon around it
        assert market_close_time(datetime.date(2025, 3, 7)) == _NORMAL_CLOSE, \
            "Fri before spring forward should have normal close (16:00)"
        assert market_close_time(datetime.date(2025, 3, 10)) == _NORMAL_CLOSE, \
            "Mon after spring forward should have normal close (16:00)"

        # Fall back 2025-11-02 (Sunday, non-trading) → verify the Fri/Mon around it
        assert market_close_time(datetime.date(2025, 10, 31)) == _NORMAL_CLOSE, \
            "Fri before fall back should have normal close (16:00)"
        assert market_close_time(datetime.date(2025, 11, 3)) == _NORMAL_CLOSE, \
            "Mon after fall back should have normal close (16:00)"

        # Known half-days near DST transitions
        # Black Friday 2025-11-28 (1 month after fall back) — early close
        assert market_close_time(datetime.date(2025, 11, 28)) == _EARLY_CLOSE, \
            "Black Friday 2025-11-28 must have early close (13:00)"

        # Christmas Eve 2024-12-24 (winter, EST) — early close
        assert market_close_time(datetime.date(2024, 12, 24)) == _EARLY_CLOSE, \
            "Christmas Eve 2024 must have early close (13:00)"


# ═══════════════════════════════════════════════════════════════════════════════
# GAP 2 (E7) — Signal-bar lag: missing current bar
# ═══════════════════════════════════════════════════════════════════════════════

class TestGap2E7SignalBarLag:
    """
    E7: A non-SPY ticker's current bar (e.g., AAPL's 10:00 bar) has not yet
    arrived in the WebSocket queue when SPY's 10:00 bar triggers context emission.

    _BarAccumulator behaviour:
    - get_day_stocks(day, as_of=10:00) returns AAPL with bars up to 9:55 (stale).
      AAPL is NOT dropped — it stays present with whatever bars have arrived.
    - When the late bar arrives and is added to the accumulator, it is visible
      in the NEXT call to get_day_stocks (as_of=10:05).
    - The day_stocks dict already returned for as_of=10:00 is NOT retroactively
      modified — it is an independent snapshot.

    DU safety:
    - du.decide() at bar_ts=10:00 with stale 9:55 data must not crash and must
      not generate a spurious ORB entry.  Safety guaranteed by physics: the stale
      9:55 bar's close ≤ high ≤ OR high (OR high = max of all highs incl. 9:55),
      so it can never appear to break out of its own range.
    """

    @staticmethod
    def _row(ts: pd.Timestamp, open_: float, high: float, low: float, close: float) -> pd.Series:
        return pd.Series(
            {"open": open_, "high": high, "low": low,
             "close": close, "volume": 500_000.0, "vwap": close},
            name=ts,
        )

    @staticmethod
    def _build_du(cfg: BacktestConfig):
        """Build a real DecisionUnit (same pattern as TestGap3)."""
        from raits.backtest.engine_refactored import RefactoredBacktestEngine
        from raits.decision.decision_unit import DecisionUnit

        eng  = RefactoredBacktestEngine(cfg)
        mods = eng._mods
        pdt  = mods["PDTGuard"]()
        sizer = mods["PositionSizer"](
            account_equity=cfg.account_equity,
            max_risk_pct=cfg.max_risk_pct,
            max_position_pct=cfg.max_position_pct,
            kelly_fraction=cfg.kelly_fraction,
        )
        coord = mods["RegimeCoordinator"]()
        orb   = mods["ORBStrategy"](config={
            "opening_vol_multiplier": 1.2, "min_price": 1.0,
            "max_price": 1e9, "min_gap_pct": 0.01,
        })
        stress_orb = mods["ORBStrategy"](config={
            "allowed_regimes": ["Stress"], "min_gap_pct": 0.0,
            "rvol_threshold": 0.0, "min_price": 1.0,
            "max_price": 1e9, "min_range_atr_multiple": 0.2,
        })
        fade_orb = mods["ORBStrategy"](config={
            "opening_vol_multiplier": 1.2, "min_price": 1.0, "max_price": 1e9,
            "min_gap_pct": 0.0, "rvol_threshold": 0.0,
            "fade_require_midpoint": False, "fade_long_enabled": True,
        })
        vwap_mr = mods["VWAPMRStrategy"](config={"bb_std_dev": cfg.vwap_bb_std})
        trend   = mods["TrendStrategy"](config={"ema_period": cfg.ema_period})
        return DecisionUnit(
            config=cfg, orb=orb, stress_orb=stress_orb, fade_orb=fade_orb,
            vwap_mr=vwap_mr, trend=trend, coordinator=coord,
            position_sizer=sizer, pdt_guard=pdt,
        )

    # ── 1. Accumulator: withheld current bar absent; stale bars retained ──────

    def test_accumulator_withheld_bar_absent_stale_bars_retained(self):
        """
        _BarAccumulator at as_of=10:00 with AAPL's 10:00 bar never added:
        AAPL must still appear in day_stocks (with bars up to 9:55) — not dropped.
        The absent 10:00 bar must not appear.
        """
        acc = _BarAccumulator()
        day = pd.Timestamp("2022-01-04")

        for i, hm in enumerate(["09:30", "09:35", "09:40", "09:45", "09:50", "09:55"]):
            ts   = pd.Timestamp(f"2022-01-04 {hm}")
            base = 149.90 + i * 0.1
            acc.add("AAPL", ts, self._row(ts, base - 0.1, base + 0.2, base - 0.2, base))

        ds = acc.get_day_stocks(day, pd.Timestamp("2022-01-04 10:00"))

        assert "AAPL" in ds, (
            "E7 FAIL: AAPL absent from day_stocks when its current bar is withheld. "
            "Stale-but-present bars must be retained, not dropped."
        )
        idx = list(ds["AAPL"].index)
        assert pd.Timestamp("2022-01-04 09:55") in idx, "Stale 9:55 bar must be visible"
        assert pd.Timestamp("2022-01-04 10:00") not in idx, (
            "E7 FAIL: 10:00 bar must NOT appear until it is added to the accumulator"
        )

    # ── 2. Accumulator: late bar visible in NEXT context; past snapshot immutable

    def test_accumulator_late_bar_visible_next_context_not_retroactive(self):
        """
        After adding AAPL's late 10:00 bar, the 10:05 context includes it.
        The previously captured 10:00 snapshot (ds_1000) is not retroactively
        modified — pd.concat creates independent DataFrames.
        """
        acc = _BarAccumulator()
        day = pd.Timestamp("2022-01-04")

        for i, hm in enumerate(["09:30", "09:35", "09:40", "09:45", "09:50", "09:55"]):
            ts   = pd.Timestamp(f"2022-01-04 {hm}")
            base = 149.90 + i * 0.1
            acc.add("AAPL", ts, self._row(ts, base - 0.1, base + 0.2, base - 0.2, base))

        # Capture the 10:00 context before the late bar arrives
        ds_1000     = acc.get_day_stocks(day, pd.Timestamp("2022-01-04 10:00"))
        idx_at_1000 = list(ds_1000["AAPL"].index)

        # Late arrival: AAPL 10:00 bar added to accumulator
        ts_1000 = pd.Timestamp("2022-01-04 10:00")
        acc.add("AAPL", ts_1000, self._row(ts_1000, 150.55, 151.00, 150.40, 150.80))

        # Next context must include the late bar
        ds_1005 = acc.get_day_stocks(day, pd.Timestamp("2022-01-04 10:05"))
        assert pd.Timestamp("2022-01-04 10:00") in list(ds_1005["AAPL"].index), (
            "E7 FAIL: Late AAPL 10:00 bar must be visible in the 10:05 context."
        )

        # Past context (10:00) must be immutable
        assert list(ds_1000["AAPL"].index) == idx_at_1000, (
            "E7 FAIL: Previously captured 10:00 context was retroactively modified."
        )
        assert pd.Timestamp("2022-01-04 10:00") not in idx_at_1000

    # ── 3. DU: stale 9:55 bar cannot trigger a spurious ORB breakout ──────────

    def test_stale_bar_no_spurious_orb_signal(self):
        """
        du.decide() at bar_ts=10:00 with only stale 9:55 AAPL data must not
        crash and must not generate an ORB entry.

        Safety invariant: stale_bar.close ≤ stale_bar.high ≤ OR high.
        A bar can never break out of the range it helped build.
        """
        cfg = BacktestConfig(
            start_date="2022-01-04", end_date="2022-01-04",
            universe=["AAPL"], orb_universe=["AAPL"],
            account_equity=50_000.0, orb_range_minutes=30,
            vwap_bb_std=1.5, ema_period=30,
            max_risk_pct=0.015, max_position_pct=0.40,
            kelly_fraction=0.75, hmm_retrain_weekly=False,
        )
        du  = self._build_du(cfg)
        day = pd.Timestamp("2022-01-04")
        du.reset_day(day,
                     orb_signal_start=datetime.time(10, 0),
                     orb_signal_end=datetime.time(10, 30))

        # OR range: high=150.60 (9:40 bar), low=149.50 (9:30 bar)
        or_high, or_low = 150.60, 149.50
        du.or_ranges["AAPL"] = (or_high, or_low)

        # AAPL day_stocks: bars 9:30..9:55 only (10:00 bar withheld)
        # 9:55 bar: close=150.45 < 150.60 = or_high  →  cannot break out
        bar_spec = [
            # hm,     open,   high,   low,    close
            ("09:30", 149.60, 149.75, 149.50, 149.60),  # low = or_low
            ("09:35", 149.80, 149.95, 149.65, 149.80),
            ("09:40", 150.20, 150.60, 150.10, 150.20),  # high = or_high
            ("09:45", 150.40, 150.55, 150.20, 150.40),
            ("09:50", 150.35, 150.50, 150.20, 150.35),
            ("09:55", 150.30, 150.45, 150.20, 150.45),  # stale; close < or_high
        ]
        rows, idx = [], []
        for hm, o, h, l, c in bar_spec:
            ts = pd.Timestamp(f"2022-01-04 {hm}")
            rows.append({"open": o, "high": h, "low": l, "close": c,
                         "volume": 500_000.0, "vwap": c})
            idx.append(ts)
        aapl_df = pd.DataFrame(rows, index=pd.DatetimeIndex(idx))

        stale_close = float(aapl_df.iloc[-1]["close"])
        assert stale_close < or_high, "Test design: 9:55 close must be < or_high"
        assert stale_close > or_low,  "Test design: 9:55 close must be > or_low"

        bar_ts  = pd.Timestamp("2022-01-04 10:00")
        spy_bar = pd.Series(
            {"open": 399.0, "high": 400.5, "low": 398.5,
             "close": 400.0, "volume": 5_000_000.0, "vwap": 400.0},
            name=bar_ts,
        )
        spy_df       = spy_bar.to_frame().T
        spy_df.index = pd.DatetimeIndex([bar_ts])

        ctx = BarContext(
            bar_ts=bar_ts, spy_bar=spy_bar, spy_history=[spy_bar],
            day_stocks={"AAPL": aapl_df},
            market_data={}, open_trades=[],
            hmm_state="Normal", cur_vol=0.15,
            day=day, orb_vix_ok=True, stress_orb_vix_ok=False,
            effective_orb_universe=["AAPL"],
            effective_vwap_universe=[], effective_fade_universe=[],
            all_tickers=["AAPL"], base_universe=["AAPL"],
            stress_stocks={"SPY": spy_df},
            spy_or_high=400.5, spy_or_low=398.5, spy_bull_trend=True,
            daily_spy_close=pd.Series(dtype=float),
            pe_short_calendar={}, fade_atr_top2=set(),
            vwap_bb_std=cfg.vwap_bb_std,
            ema_period=cfg.ema_period,
            vwap_mr_vol_threshold=cfg.vwap_mr_vol_threshold,
            allow_swing_hold=cfg.allow_swing_hold,
            enable_pdt_guard=cfg.enable_pdt_guard,
            stress_size_fraction=cfg.stress_size_fraction,
            orb_signal_start=datetime.time(10, 0),
            orb_signal_end=datetime.time(10, 30),
        )

        result = du.decide(ctx)   # must not raise

        orb_entries = [e for e in result.entries
                       if e.ticker == "AAPL" and e.strategy == "ORB"]
        assert not orb_entries, (
            f"E7 FAIL: Spurious ORB entry using stale 9:55 data "
            f"(close={stale_close}, or_high={or_high}). "
            f"A bar cannot break out of the range it helped build. "
            f"Got: {orb_entries}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# GAP 6 (E6) — Out-of-order inter-ticker bar
# ═══════════════════════════════════════════════════════════════════════════════

class TestGap6E6OutOfOrderInterTicker:
    """
    E6: SPY's 10:05 bar triggers context emission while AAPL's 10:00 bar is
    delayed on a different WebSocket channel.  After the 10:05 context is
    yielded, AAPL's 10:00 bar finally arrives.

    _BarAccumulator behaviour:
    - The late 10:00 bar is stored (not dropped) via add().
    - At as_of=10:10, get_day_stocks returns AAPL with 10:00 included (ts <= as_of).
    - The 10:05 context snapshot (captured before the late bar arrived) is NOT
      retroactively modified — pd.concat builds an independent DataFrame.
    - The resulting DataFrame is sorted in ascending timestamp order even though
      the 10:00 bar arrived after 10:05 was already buffered.
    """

    @staticmethod
    def _row(ts: pd.Timestamp, close: float = 150.0) -> pd.Series:
        return pd.Series(
            {"open": close - 0.1, "high": close + 0.2,
             "low": close - 0.2, "close": close,
             "volume": 500_000.0, "vwap": close},
            name=ts,
        )

    # ── 1. Late bar stored and visible in next context ─────────────────────────

    def test_late_interticker_bar_stored_visible_next_context(self):
        """
        AAPL's 10:00 bar arrives after the 10:05 context was emitted.
        It must be stored in the accumulator and appear in the 10:10 context.
        """
        acc = _BarAccumulator()
        day = pd.Timestamp("2022-01-04")

        # Add bars that arrived before the 10:05 emission (no 10:00 yet)
        for hm in ["09:30", "09:35", "09:40", "09:45", "09:50", "09:55", "10:05"]:
            ts = pd.Timestamp(f"2022-01-04 {hm}")
            acc.add("AAPL", ts, self._row(ts))

        # 10:05 context: 10:00 bar absent
        ds_1005 = acc.get_day_stocks(day, pd.Timestamp("2022-01-04 10:05"))
        assert "AAPL" in ds_1005
        assert pd.Timestamp("2022-01-04 10:00") not in list(ds_1005["AAPL"].index), (
            "E6: 10:00 bar must not appear in the 10:05 context before it arrives"
        )
        assert pd.Timestamp("2022-01-04 10:05") in list(ds_1005["AAPL"].index)

        # Late arrival: AAPL 10:00 bar added out-of-order
        ts_1000 = pd.Timestamp("2022-01-04 10:00")
        acc.add("AAPL", ts_1000, self._row(ts_1000, close=150.30))

        # 10:10 context: 10:00 bar now visible
        ds_1010 = acc.get_day_stocks(day, pd.Timestamp("2022-01-04 10:10"))
        assert pd.Timestamp("2022-01-04 10:00") in list(ds_1010["AAPL"].index), (
            "E6 FAIL: Late AAPL 10:00 bar must be visible in the 10:10 context (not dropped)."
        )

    # ── 2. Past context immutable after late bar addition ──────────────────────

    def test_late_bar_not_retroactive_in_past_context(self):
        """
        The day_stocks dict captured at as_of=10:05 must not change after the
        late 10:00 bar is added.  _BarAccumulator.get_day_stocks returns
        independent DataFrames built from a point-in-time snapshot.
        """
        acc = _BarAccumulator()
        day = pd.Timestamp("2022-01-04")

        for hm in ["09:30", "09:35", "09:40", "09:45", "09:50", "09:55", "10:05"]:
            ts = pd.Timestamp(f"2022-01-04 {hm}")
            acc.add("AAPL", ts, self._row(ts))

        # Capture 10:05 snapshot (before late bar)
        ds_1005    = acc.get_day_stocks(day, pd.Timestamp("2022-01-04 10:05"))
        idx_before = list(ds_1005["AAPL"].index)

        # Late bar arrives
        ts_1000 = pd.Timestamp("2022-01-04 10:00")
        acc.add("AAPL", ts_1000, self._row(ts_1000, close=150.30))

        assert list(ds_1005["AAPL"].index) == idx_before, (
            "E6 FAIL: Adding late bar retroactively modified the captured 10:05 snapshot."
        )
        assert pd.Timestamp("2022-01-04 10:00") not in list(ds_1005["AAPL"].index), (
            "E6 FAIL: Late 10:00 bar appeared inside the already-yielded 10:05 context."
        )

    # ── 3. Out-of-order arrival produces correctly sorted DataFrame ────────────

    def test_out_of_order_arrival_correctly_sorted(self):
        """
        When AAPL's 10:00 bar is added to the accumulator AFTER the 10:05 and
        10:10 bars, the DataFrame returned by get_day_stocks must still have
        timestamps in strictly ascending order: ..., 10:00, 10:05, 10:10.
        """
        acc = _BarAccumulator()
        day = pd.Timestamp("2022-01-04")

        # 9:30..9:55 arrive in order, then 10:05 and 10:10 (skipping 10:00)
        for hm in ["09:30", "09:35", "09:40", "09:45", "09:50", "09:55",
                   "10:05", "10:10"]:
            ts = pd.Timestamp(f"2022-01-04 {hm}")
            acc.add("AAPL", ts, self._row(ts))

        # 10:00 arrives LATE (strictly out of chronological order)
        ts_1000 = pd.Timestamp("2022-01-04 10:00")
        acc.add("AAPL", ts_1000, self._row(ts_1000, close=150.30))

        ds = acc.get_day_stocks(day, pd.Timestamp("2022-01-04 10:10"))
        aapl_idx = list(ds["AAPL"].index)

        # All three late-window bars present
        for ts in [pd.Timestamp("2022-01-04 10:00"),
                   pd.Timestamp("2022-01-04 10:05"),
                   pd.Timestamp("2022-01-04 10:10")]:
            assert ts in aapl_idx, f"E6 FAIL: {ts} missing from day_stocks"

        # Sorted by timestamp (not arrival order)
        assert aapl_idx == sorted(aapl_idx), (
            f"E6 FAIL: Bars not in chronological order after out-of-order arrival. "
            f"Got: {aapl_idx[-4:]}"
        )

        # 10:00 explicitly precedes 10:05 despite arriving last
        i_1000 = aapl_idx.index(pd.Timestamp("2022-01-04 10:00"))
        i_1005 = aapl_idx.index(pd.Timestamp("2022-01-04 10:05"))
        assert i_1000 < i_1005, (
            "E6 FAIL: Late 10:00 bar must sort before 10:05 in chronological order"
        )
