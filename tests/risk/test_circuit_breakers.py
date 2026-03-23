"""
tests/risk/test_circuit_breakers.py
-------------------------------------
Unit tests for raits.risk.circuit_breakers.CircuitBreakerManager.

Coverage targets
----------------
Kill Switch 1 — Daily Drawdown:
  - Triggers at exactly -4.0% (boundary)
  - Does NOT trigger at -3.99%
  - Non-positive session_start_equity is handled gracefully

Kill Switch 2 — Consecutive Losses:
  - Triggers on exactly 5th consecutive loss
  - Does NOT trigger on 4th
  - Win resets streak to zero
  - Break-even (pnl=0) counts as a loss
  - Streak survives session reset

Kill Switch 3 — MOC Imbalance (position-level):
  - Triggers when sell imbalance > 50% of ADV
  - Does NOT arm account-level kill switch
  - Invalid ADV handled gracefully

Cross-cutting:
  - Once HALTED, all subsequent checks return HALTED without re-evaluation
  - reset_for_new_session re-arms account-level state
  - assert_trading_active blocks when halted
  - BreakerResult.passed and .kill_switch are consistent
"""

from __future__ import annotations

import pytest
from datetime import date

from raits.risk.circuit_breakers import (
    CircuitBreakerManager,
    BreakerState,
    BreakerResult,
    TriggerReason,
    DAILY_DRAWDOWN_LIMIT,
    CONSECUTIVE_LOSS_LIMIT,
    MOC_IMBALANCE_FRACTION,
)

SESSION = date(2026, 3, 23)
SESSION2 = date(2026, 3, 24)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cb() -> CircuitBreakerManager:
    mgr = CircuitBreakerManager()
    mgr.reset_for_new_session(SESSION)
    return mgr


# ---------------------------------------------------------------------------
# Kill Switch 1 — Daily Drawdown
# ---------------------------------------------------------------------------

class TestDailyDrawdown:
    def test_no_loss_passes(self, cb):
        r = cb.check_daily_drawdown(25_000, 25_000)
        assert r.passed
        assert not r.kill_switch
        assert cb.state == BreakerState.ACTIVE

    def test_small_loss_passes(self, cb):
        r = cb.check_daily_drawdown(24_010, 25_000)  # -3.96%
        assert r.passed
        assert cb.state == BreakerState.ACTIVE

    def test_exactly_minus_3_99_pct_passes(self, cb):
        """Just inside the limit must NOT trigger."""
        start = 25_000.0
        equity = start * (1 + DAILY_DRAWDOWN_LIMIT + 0.0001)  # -3.99%
        r = cb.check_daily_drawdown(equity, start)
        assert r.passed

    def test_exactly_minus_4_pct_triggers(self, cb):
        """Exactly at the limit must trigger the kill switch."""
        start = 25_000.0
        equity = start * (1 + DAILY_DRAWDOWN_LIMIT)            # exactly -4%
        r = cb.check_daily_drawdown(equity, start)
        assert not r.passed
        assert r.kill_switch
        assert cb.state == BreakerState.HALTED
        assert cb.trigger_reason == TriggerReason.DAILY_DRAWDOWN

    def test_beyond_minus_4_pct_triggers(self, cb):
        """Loss beyond the limit also triggers."""
        r = cb.check_daily_drawdown(23_000, 25_000)  # -8%
        assert r.kill_switch

    def test_profit_passes(self, cb):
        r = cb.check_daily_drawdown(26_000, 25_000)
        assert r.passed

    def test_nonpositive_start_equity_skips_gracefully(self, cb):
        r = cb.check_daily_drawdown(25_000, 0)
        assert r.passed  # skipped, not crashed

    def test_dd_pct_in_result_data(self, cb):
        start = 25_000.0
        equity = start * 0.97
        r = cb.check_daily_drawdown(equity, start)
        assert "daily_dd_pct" in r.data
        assert abs(r.data["daily_dd_pct"] - (-0.03)) < 1e-6

    def test_halted_state_blocks_subsequent_dd_check(self, cb):
        start = 25_000.0
        cb.check_daily_drawdown(start * 0.95, start)  # trigger
        r = cb.check_daily_drawdown(start * 0.95, start)
        assert not r.passed
        assert r.kill_switch


# ---------------------------------------------------------------------------
# Kill Switch 2 — Consecutive Losses
# ---------------------------------------------------------------------------

class TestConsecutiveLosses:
    def test_single_loss_passes(self, cb):
        r = cb.record_trade_result(-100)
        assert r.passed
        assert cb.consecutive_losses == 1

    def test_four_losses_pass(self, cb):
        for _ in range(CONSECUTIVE_LOSS_LIMIT - 1):
            r = cb.record_trade_result(-50)
            assert r.passed
        assert cb.consecutive_losses == CONSECUTIVE_LOSS_LIMIT - 1

    def test_fifth_loss_triggers(self, cb):
        for _ in range(CONSECUTIVE_LOSS_LIMIT - 1):
            cb.record_trade_result(-50)
        r = cb.record_trade_result(-50)   # 5th
        assert not r.passed
        assert r.kill_switch
        assert cb.state == BreakerState.HALTED
        assert cb.trigger_reason == TriggerReason.CONSECUTIVE_LOSSES

    def test_win_resets_streak(self, cb):
        cb.record_trade_result(-100)
        cb.record_trade_result(-100)
        cb.record_trade_result(-100)
        r = cb.record_trade_result(50)    # win
        assert r.passed
        assert cb.consecutive_losses == 0

    def test_win_then_four_losses_passes(self, cb):
        """After a win, must accumulate 5 new losses to trigger."""
        cb.record_trade_result(-50)
        cb.record_trade_result(-50)
        cb.record_trade_result(-50)
        cb.record_trade_result(100)   # win — reset
        for i in range(CONSECUTIVE_LOSS_LIMIT - 1):
            r = cb.record_trade_result(-50)
            assert r.passed, f"Should not trigger on loss {i+1} after reset"

    def test_breakeven_counts_as_loss(self, cb):
        """pnl == 0 must NOT reset the streak."""
        for _ in range(CONSECUTIVE_LOSS_LIMIT - 1):
            cb.record_trade_result(-10)
        r = cb.record_trade_result(0.0)   # break-even → 5th "loss"
        assert not r.passed
        assert r.kill_switch

    def test_consecutive_losses_survive_session_reset(self, cb):
        """A losing streak must carry forward across the session boundary."""
        cb.record_trade_result(-100)
        cb.record_trade_result(-100)
        cb.record_trade_result(-100)
        # New session — account re-armed but streak persists
        cb.reset_for_new_session(SESSION2)
        assert cb.consecutive_losses == 3
        assert cb.state == BreakerState.ACTIVE

    def test_remaining_count_in_data(self, cb):
        cb.record_trade_result(-50)
        r = cb.record_trade_result(-50)
        assert r.data["remaining_until_halt"] == CONSECUTIVE_LOSS_LIMIT - 2


# ---------------------------------------------------------------------------
# Kill Switch 3 — MOC Imbalance
# ---------------------------------------------------------------------------

class TestMOCImbalance:
    def test_small_imbalance_passes(self, cb):
        r = cb.check_moc_imbalance("TSLA", 100_000, 1_000_000)  # 10%
        assert r.passed
        assert not r.kill_switch

    def test_exactly_50pct_passes(self, cb):
        """Exactly at boundary should NOT trigger (> not >=)."""
        r = cb.check_moc_imbalance("AAPL", 500_000, 1_000_000)  # exactly 50%
        assert r.passed

    def test_above_50pct_triggers(self, cb):
        r = cb.check_moc_imbalance("AAPL", 500_001, 1_000_000)  # 50.0001%
        assert not r.passed
        assert r.kill_switch

    def test_moc_does_not_arm_account_level_switch(self, cb):
        """MOC is position-level: account must remain ACTIVE after trigger."""
        cb.check_moc_imbalance("AAPL", 600_000, 1_000_000)  # trigger
        assert cb.state == BreakerState.ACTIVE   # account still active
        assert cb.trigger_reason is None

    def test_large_imbalance_triggers(self, cb):
        r = cb.check_moc_imbalance("GME", 900_000, 1_000_000)  # 90%
        assert r.kill_switch
        assert "GME" in r.reason

    def test_invalid_adv_skips_gracefully(self, cb):
        r = cb.check_moc_imbalance("XYZ", 100_000, 0)
        assert r.passed   # skip, not crash

    def test_ticker_in_result_data(self, cb):
        r = cb.check_moc_imbalance("SPY", 600_000, 1_000_000)
        assert r.data.get("ticker") == "SPY"


# ---------------------------------------------------------------------------
# Cross-cutting: HALTED state blocks everything
# ---------------------------------------------------------------------------

class TestHaltedStateBlocksAll:
    def test_assert_trading_active_blocks_when_halted(self, cb):
        # Arm with drawdown
        cb.check_daily_drawdown(24_000, 25_000)  # triggers
        r = cb.assert_trading_active()
        assert not r.passed
        assert r.kill_switch

    def test_dd_check_blocked_when_already_halted(self, cb):
        cb.check_daily_drawdown(24_000, 25_000)  # arm
        r = cb.check_daily_drawdown(23_000, 25_000)  # should short-circuit
        assert not r.passed

    def test_trade_result_blocked_when_halted(self, cb):
        cb.check_daily_drawdown(24_000, 25_000)  # arm
        r = cb.record_trade_result(-100)
        assert not r.passed

    def test_assert_trading_active_passes_when_active(self, cb):
        r = cb.assert_trading_active()
        assert r.passed
        assert not r.kill_switch


# ---------------------------------------------------------------------------
# Session reset
# ---------------------------------------------------------------------------

class TestSessionReset:
    def test_reset_re_arms_halted_account(self, cb):
        cb.check_daily_drawdown(24_000, 25_000)  # arm
        assert cb.state == BreakerState.HALTED
        cb.reset_for_new_session(SESSION2)
        assert cb.state == BreakerState.ACTIVE

    def test_reset_clears_trigger_reason(self, cb):
        cb.check_daily_drawdown(24_000, 25_000)
        cb.reset_for_new_session(SESSION2)
        assert cb.trigger_reason is None

    def test_reset_updates_session_date(self, cb):
        cb.reset_for_new_session(SESSION2)
        assert cb.session_date == SESSION2

    def test_trading_permitted_after_reset(self, cb):
        cb.check_daily_drawdown(24_000, 25_000)  # arm
        cb.reset_for_new_session(SESSION2)
        r = cb.assert_trading_active()
        assert r.passed


# ---------------------------------------------------------------------------
# BreakerResult invariants
# ---------------------------------------------------------------------------

class TestBreakerResultInvariants:
    def test_pass_result_is_not_kill_switch(self, cb):
        r = cb.check_daily_drawdown(25_000, 25_000)
        assert r.passed and not r.kill_switch

    def test_kill_switch_result_is_not_passed(self, cb):
        cb.check_daily_drawdown(24_000, 25_000)  # arm
        r = cb.assert_trading_active()
        assert not r.passed and r.kill_switch

    def test_repr_contains_state_tag(self, cb):
        r = cb.assert_trading_active()
        assert "PASS" in repr(r)
