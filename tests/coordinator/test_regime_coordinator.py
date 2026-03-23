"""
tests/coordinator/test_regime_coordinator.py

Coverage targets
----------------
SystemState transitions:
  - ACTIVE → SAFETY_MODE when HMM→Stress
  - SAFETY_MODE → ACTIVE when HMM returns to Calm/Normal
  - ACTIVE → OVERRIDE_STRESS when override triggers
  - OVERRIDE_STRESS → COOLDOWN after min hold (20 min)
  - OVERRIDE_STRESS stays if min hold not elapsed
  - COOLDOWN → ACTIVE after 10-min cooldown
  - COOLDOWN → SAFETY_MODE if HMM goes Stress during cooldown
  - Any state → SHUTDOWN on circuit breaker (immediate)
  - SHUTDOWN blocks all transitions
  - reset_for_new_session re-arms

Properties:
  - trading_allowed is True only in ACTIVE
  - effective_hmm_state returns 'Stress' during OVERRIDE/COOLDOWN/SAFETY/SHUTDOWN
  - effective_hmm_state returns raw HMM in ACTIVE
"""

import pytest
from datetime import datetime, timedelta
from raits.coordinator.regime_coordinator import (
    RegimeCoordinator, SystemState,
    OVERRIDE_MIN_HOLD_MINUTES, COOLDOWN_MINUTES,
)

T0  = datetime(2026, 3, 23, 9, 35, 0)   # market open reference

def mins(n): return timedelta(minutes=n)


class TestInitialState:
    def test_starts_active(self):
        c = RegimeCoordinator()
        assert c.state == SystemState.ACTIVE

    def test_trading_allowed_initially(self):
        c = RegimeCoordinator()
        assert c.trading_allowed is True

    def test_effective_hmm_defaults_to_normal(self):
        c = RegimeCoordinator()
        assert c.effective_hmm_state == "Normal"


class TestHMMTransitions:
    def test_stress_triggers_safety_mode(self):
        c = RegimeCoordinator()
        c.notify_hmm_state("Stress", T0 + mins(31))
        assert c.state == SystemState.SAFETY_MODE

    def test_safety_mode_blocks_trading(self):
        c = RegimeCoordinator()
        c.notify_hmm_state("Stress", T0 + mins(31))
        assert c.trading_allowed is False

    def test_calm_clears_safety_mode(self):
        c = RegimeCoordinator()
        c.notify_hmm_state("Stress", T0 + mins(31))
        c.notify_hmm_state("Calm", T0 + mins(62))
        assert c.state == SystemState.ACTIVE

    def test_normal_clears_safety_mode(self):
        c = RegimeCoordinator()
        c.notify_hmm_state("Stress", T0 + mins(31))
        c.notify_hmm_state("Normal", T0 + mins(62))
        assert c.state == SystemState.ACTIVE

    def test_calm_in_active_stays_active(self):
        c = RegimeCoordinator()
        c.notify_hmm_state("Calm", T0 + mins(5))
        assert c.state == SystemState.ACTIVE

    def test_effective_hmm_stress_in_safety_mode(self):
        c = RegimeCoordinator()
        c.notify_hmm_state("Stress", T0 + mins(31))
        assert c.effective_hmm_state == "Stress"

    def test_effective_hmm_follows_raw_in_active(self):
        c = RegimeCoordinator()
        c.notify_hmm_state("Calm", T0)
        assert c.effective_hmm_state == "Calm"
        c.notify_hmm_state("Normal", T0 + mins(1))
        assert c.effective_hmm_state == "Normal"


class TestOverrideTransitions:
    def test_override_triggers_override_stress(self):
        c = RegimeCoordinator()
        c.notify_override(True, T0)
        assert c.state == SystemState.OVERRIDE_STRESS

    def test_override_beats_hmm_normal(self):
        c = RegimeCoordinator()
        c.notify_hmm_state("Normal", T0)
        c.notify_override(True, T0)
        assert c.state == SystemState.OVERRIDE_STRESS

    def test_override_expires_before_min_hold_stays(self):
        """Override cleared before 20 min — must stay OVERRIDE_STRESS."""
        c = RegimeCoordinator()
        c.notify_override(True, T0)
        c.notify_override(False, T0 + mins(OVERRIDE_MIN_HOLD_MINUTES - 1))
        assert c.state == SystemState.OVERRIDE_STRESS

    def test_override_expires_after_min_hold_enters_cooldown(self):
        c = RegimeCoordinator()
        c.notify_override(True, T0)
        c.notify_override(False, T0 + mins(OVERRIDE_MIN_HOLD_MINUTES))
        assert c.state == SystemState.COOLDOWN

    def test_cooldown_trading_blocked(self):
        c = RegimeCoordinator()
        c.notify_override(True, T0)
        c.notify_override(False, T0 + mins(OVERRIDE_MIN_HOLD_MINUTES))
        assert c.trading_allowed is False

    def test_cooldown_expires_returns_to_active(self):
        c = RegimeCoordinator()
        c.notify_override(True, T0)
        # Override expires
        c.notify_override(False, T0 + mins(OVERRIDE_MIN_HOLD_MINUTES))
        assert c.state == SystemState.COOLDOWN
        # Cooldown expires
        c.notify_override(False, T0 + mins(OVERRIDE_MIN_HOLD_MINUTES + COOLDOWN_MINUTES))
        assert c.state == SystemState.ACTIVE

    def test_cooldown_expires_to_safety_if_hmm_stress(self):
        """If HMM is Stress when cooldown ends, go to SAFETY_MODE not ACTIVE."""
        c = RegimeCoordinator()
        c.notify_override(True, T0)
        c.notify_hmm_state("Stress", T0 + mins(5))   # HMM goes Stress during override
        c.notify_override(False, T0 + mins(OVERRIDE_MIN_HOLD_MINUTES))
        c.notify_override(False, T0 + mins(OVERRIDE_MIN_HOLD_MINUTES + COOLDOWN_MINUTES))
        assert c.state == SystemState.SAFETY_MODE

    def test_hmm_stress_during_cooldown_upgrades_to_safety(self):
        c = RegimeCoordinator()
        c.notify_override(True, T0)
        c.notify_override(False, T0 + mins(OVERRIDE_MIN_HOLD_MINUTES))
        assert c.state == SystemState.COOLDOWN
        c.notify_hmm_state("Stress", T0 + mins(OVERRIDE_MIN_HOLD_MINUTES + 2))
        assert c.state == SystemState.SAFETY_MODE

    def test_effective_hmm_is_stress_during_override(self):
        c = RegimeCoordinator()
        c.notify_hmm_state("Calm", T0)
        c.notify_override(True, T0)
        assert c.effective_hmm_state == "Stress"

    def test_effective_hmm_is_stress_during_cooldown(self):
        c = RegimeCoordinator()
        c.notify_override(True, T0)
        c.notify_override(False, T0 + mins(OVERRIDE_MIN_HOLD_MINUTES))
        assert c.state == SystemState.COOLDOWN
        assert c.effective_hmm_state == "Stress"

    def test_override_hmm_cannot_preempt_override(self):
        """HMM notify during OVERRIDE_STRESS should not change state."""
        c = RegimeCoordinator()
        c.notify_override(True, T0)
        c.notify_hmm_state("Calm", T0 + mins(5))
        assert c.state == SystemState.OVERRIDE_STRESS


class TestCircuitBreaker:
    def test_circuit_breaker_triggers_shutdown(self):
        c = RegimeCoordinator()
        c.notify_circuit_breaker(T0)
        assert c.state == SystemState.SHUTDOWN

    def test_shutdown_blocks_trading(self):
        c = RegimeCoordinator()
        c.notify_circuit_breaker(T0)
        assert c.trading_allowed is False

    def test_shutdown_blocks_hmm_transitions(self):
        c = RegimeCoordinator()
        c.notify_circuit_breaker(T0)
        c.notify_hmm_state("Calm", T0 + mins(5))
        assert c.state == SystemState.SHUTDOWN

    def test_shutdown_blocks_override(self):
        c = RegimeCoordinator()
        c.notify_circuit_breaker(T0)
        c.notify_override(False, T0 + mins(30))
        assert c.state == SystemState.SHUTDOWN

    def test_shutdown_from_safety_mode(self):
        c = RegimeCoordinator()
        c.notify_hmm_state("Stress", T0 + mins(31))
        assert c.state == SystemState.SAFETY_MODE
        c.notify_circuit_breaker(T0 + mins(32))
        assert c.state == SystemState.SHUTDOWN


class TestSessionReset:
    def test_reset_clears_shutdown(self):
        c = RegimeCoordinator()
        c.notify_circuit_breaker(T0)
        c.reset_for_new_session(T0 + timedelta(days=1))
        assert c.state == SystemState.ACTIVE

    def test_reset_with_stress_hmm_restores_safety_mode(self):
        """If HMM was Stress when session ended, new session starts in SAFETY_MODE."""
        c = RegimeCoordinator()
        c.notify_hmm_state("Stress", T0 + mins(31))
        c.reset_for_new_session(T0 + timedelta(days=1))
        assert c.state == SystemState.SAFETY_MODE

    def test_reset_clears_override_tracking(self):
        c = RegimeCoordinator()
        c.notify_override(True, T0)
        c.reset_for_new_session(T0 + timedelta(days=1))
        assert c._override_active is False
        assert c._override_triggered_at is None


class TestTradingAllowed:
    def test_active_allows_trading(self):
        c = RegimeCoordinator()
        assert c.trading_allowed is True

    def test_safety_mode_blocks_trading(self):
        c = RegimeCoordinator()
        c.notify_hmm_state("Stress", T0 + mins(31))
        assert c.trading_allowed is False

    def test_override_stress_blocks_trading(self):
        c = RegimeCoordinator()
        c.notify_override(True, T0)
        assert c.trading_allowed is False

    def test_shutdown_blocks_trading(self):
        c = RegimeCoordinator()
        c.notify_circuit_breaker(T0)
        assert c.trading_allowed is False
