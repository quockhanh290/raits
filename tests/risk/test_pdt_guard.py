"""
tests/risk/test_pdt_guard.py
-----------------------------
Unit tests for raits.risk.pdt_guard.PDTGuard.

Coverage targets
----------------
- Rolling 5-business-day window construction (Mon anchor, weekend rollback)
- 3 trades allowed; 4th is blocked and NOT recorded
- Same-day multiple trades each consume one slot
- Window slides forward: oldest day drops off
- Monday proxy: business days never contain weekends
- Reset clears state
- Purge keeps list bounded (no unbounded growth)
- check_can_day_trade is read-only (no side-effect)
"""

from __future__ import annotations

import pytest
from datetime import date

from raits.risk.pdt_guard import (
    PDTGuard,
    PDTDecisionCode,
    _prior_trading_days,
    MAX_DAY_TRADES_PER_WINDOW,
    WINDOW_TRADING_DAYS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MON = date(2026, 3, 23)   # Monday
TUE = date(2026, 3, 24)
WED = date(2026, 3, 25)
THU = date(2026, 3, 26)
FRI = date(2026, 3, 27)
SAT = date(2026, 3, 28)   # weekend
SUN = date(2026, 3, 29)
MON2 = date(2026, 3, 30)  # following Monday


# ---------------------------------------------------------------------------
# _prior_trading_days helper
# ---------------------------------------------------------------------------

class TestPriorTradingDays:
    def test_monday_anchor_returns_five_weekdays(self):
        days = _prior_trading_days(MON, 5)
        assert len(days) == 5
        # Should be Mon Mar 17 through Mon Mar 23
        assert days[-1] == MON
        assert all(d.weekday() < 5 for d in days)

    def test_no_weekends_in_window(self):
        """Business-day list must never contain Saturday or Sunday."""
        for anchor in [MON, TUE, WED, THU, FRI, SAT, SUN]:
            days = _prior_trading_days(anchor, 5)
            for d in days:
                assert d.weekday() < 5, f"{d} is a weekend but appeared in window"

    def test_saturday_anchor_rolls_back_to_friday(self):
        """Saturday anchor -> window ends on Friday."""
        days = _prior_trading_days(SAT, 5)
        assert days[-1] == FRI, f"Expected Friday {FRI}, got {days[-1]}"
        assert days[0] == date(2026, 3, 23)   # Mon Mar 23

    def test_sunday_anchor_rolls_back_to_friday(self):
        days = _prior_trading_days(SUN, 5)
        assert days[-1] == FRI

    def test_ascending_order(self):
        days = _prior_trading_days(FRI, 5)
        assert days == sorted(days)

    def test_exactly_n_days_returned(self):
        for n in [1, 3, 5, 10]:
            days = _prior_trading_days(FRI, n)
            assert len(days) == n


# ---------------------------------------------------------------------------
# PDTGuard core behaviour
# ---------------------------------------------------------------------------

class TestPDTGuardBasicCounts:
    def test_fresh_guard_allows_first_trade(self):
        g = PDTGuard()
        result = g.check_can_day_trade(MON)
        assert result.passed
        assert result.data["day_trades_used"] == 0

    def test_first_three_trades_allowed(self):
        g = PDTGuard()
        for _ in range(3):
            r = g.record_day_trade(MON)
            assert r.passed

    def test_fourth_trade_blocked(self):
        g = PDTGuard()
        for _ in range(3):
            g.record_day_trade(MON)
        result = g.record_day_trade(MON)
        assert not result.passed
        assert result.code == PDTDecisionCode.BLOCK

    def test_fourth_trade_not_recorded(self):
        """Blocked trades must NOT increment the counter."""
        g = PDTGuard()
        for _ in range(3):
            g.record_day_trade(MON)
        g.record_day_trade(MON)  # blocked
        # Count must still be 3
        assert g.day_trades_in_window(MON) == 3

    def test_fifth_trade_also_blocked(self):
        g = PDTGuard()
        for _ in range(5):
            g.record_day_trade(MON)
        # Only 3 should have been recorded
        assert g.day_trades_in_window(MON) == 3

    def test_trades_spread_across_three_days(self):
        g = PDTGuard()
        g.record_day_trade(MON)
        g.record_day_trade(TUE)
        g.record_day_trade(WED)
        assert g.day_trades_in_window(WED) == 3

    def test_multiple_trades_same_day_each_consume_slot(self):
        g = PDTGuard()
        g.record_day_trade(MON)
        g.record_day_trade(MON)  # 2nd slot on Monday
        r = g.record_day_trade(MON)  # 3rd = last allowed
        assert r.passed
        r4 = g.record_day_trade(MON)  # 4th blocked
        assert not r4.passed


# ---------------------------------------------------------------------------
# Rolling window slide
# ---------------------------------------------------------------------------

class TestRollingWindowSlide:
    def test_oldest_day_drops_off_as_window_advances(self):
        """
        Record 3 trades on Mon.  By the following Monday (5 business days
        later) that Monday has dropped out of the new 5-day window —
        trading should be allowed again.
        """
        g = PDTGuard()
        g.record_day_trade(MON)
        g.record_day_trade(MON)
        g.record_day_trade(MON)
        # 4th trade on same Mon is blocked
        assert not g.record_day_trade(MON).passed

        # Next Monday: Mon is now outside the 5-day window
        assert g.day_trades_in_window(MON2) == 0
        r = g.record_day_trade(MON2)
        assert r.passed

    def test_window_on_friday_includes_monday(self):
        """Friday's 5-day window: Mon Tue Wed Thu Fri — all included."""
        g = PDTGuard()
        g.record_day_trade(MON)   # in window
        g.record_day_trade(WED)   # in window
        assert g.day_trades_in_window(FRI) == 2

    def test_trade_before_window_not_counted(self):
        """Trade on prior Friday should not appear in this-week's window."""
        prior_fri = date(2026, 3, 20)
        g = PDTGuard()
        g.record_day_trade(prior_fri)
        g.record_day_trade(prior_fri)
        g.record_day_trade(prior_fri)
        # Window as of MON2 = Mon Mar 30 only goes back to Mon Mar 24
        assert g.day_trades_in_window(MON2) == 0


# ---------------------------------------------------------------------------
# Read-only check_can_day_trade
# ---------------------------------------------------------------------------

class TestCheckCanDayTradeIsReadOnly:
    def test_check_does_not_record(self):
        g = PDTGuard()
        for _ in range(3):
            g.check_can_day_trade(MON)
        # No trades should have been recorded
        assert g.day_trades_in_window(MON) == 0

    def test_check_after_three_records_returns_block(self):
        g = PDTGuard()
        for _ in range(3):
            g.record_day_trade(MON)
        r = g.check_can_day_trade(MON)
        assert not r.passed
        assert r.code == PDTDecisionCode.BLOCK

    def test_check_does_not_change_count(self):
        g = PDTGuard()
        g.record_day_trade(MON)
        g.record_day_trade(MON)
        g.check_can_day_trade(MON)  # read-only
        assert g.day_trades_in_window(MON) == 2


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_all_records(self):
        g = PDTGuard()
        for _ in range(3):
            g.record_day_trade(MON)
        g.reset()
        assert g.day_trades_in_window(MON) == 0

    def test_reset_allows_fresh_trades(self):
        g = PDTGuard()
        for _ in range(3):
            g.record_day_trade(MON)
        g.reset()
        r = g.record_day_trade(MON)
        assert r.passed


# ---------------------------------------------------------------------------
# window_dates()
# ---------------------------------------------------------------------------

class TestWindowDates:
    def test_returns_five_dates(self):
        g = PDTGuard()
        dates = g.window_dates(FRI)
        assert len(dates) == WINDOW_TRADING_DAYS

    def test_all_weekdays(self):
        g = PDTGuard()
        for d in g.window_dates(FRI):
            assert d.weekday() < 5


# ---------------------------------------------------------------------------
# Result data payloads
# ---------------------------------------------------------------------------

class TestResultData:
    def test_pass_result_has_correct_data_keys(self):
        g = PDTGuard()
        r = g.check_can_day_trade(MON)
        assert "day_trades_used" in r.data
        assert "remaining" in r.data
        assert "window_end" in r.data

    def test_block_result_has_correct_data_keys(self):
        g = PDTGuard()
        for _ in range(3):
            g.record_day_trade(MON)
        r = g.check_can_day_trade(MON)
        assert "day_trades_used" in r.data
        assert "window_end" in r.data

    def test_pass_data_counts_are_accurate(self):
        g = PDTGuard()
        g.record_day_trade(MON)
        g.record_day_trade(TUE)
        r = g.check_can_day_trade(WED)
        assert r.data["day_trades_used"] == 2
        assert r.data["remaining"] == 1
