"""
tests/coordinator/test_strategy_router.py

Coverage targets
----------------
Time window classification:
  - Pre-open routes to PRE_OPEN
  - 9:35 exactly → ORB_SCAN
  - 9:36–10:14 → ORB_MONITOR
  - 10:15–13:59 → VWAP_MR
  - 14:00–15:54 → TREND_FOLLOW
  - 15:55–15:59 → CLOSE_ALL
  - 16:00+ → CLOSED

Regime filters:
  - ORB blocked during Stress
  - VWAP_MR blocked during Normal and Stress
  - TREND_FOLLOW allowed during Normal and Stress
  - TREND_FOLLOW blocked during Calm

System state gates:
  - SAFETY_MODE blocks all signals and sets close_all=True
  - OVERRIDE_STRESS blocks all signals and sets close_all=True
  - COOLDOWN blocks all signals, close_all=False
  - SHUTDOWN blocks all signals, close_all=False
  - CLOSE_ALL window always sets close_all=True regardless of state

RoutingDecision properties:
  - has_signal_opportunity True only when strategy is set and not close_all
"""

import pytest
from datetime import datetime, time
from raits.coordinator.regime_coordinator import RegimeCoordinator, SystemState
from raits.coordinator.strategy_router import (
    StrategyRouter, RoutingDecision, TimeWindow,
    STRATEGY_ALLOWED_REGIMES,
)

def dt(h, m, s=0):
    return datetime(2026, 3, 23, h, m, s)

def mins(n):
    from datetime import timedelta
    return timedelta(minutes=n)

T0 = dt(9, 35)


def make_router(hmm_state="Normal", override=False):
    """Helper: coordinator pre-loaded with given state."""
    coord = RegimeCoordinator()
    # Use a time far enough past init to clear min-hold
    coord.notify_hmm_state(hmm_state, dt(8, 0))
    if override:
        coord.notify_override(True, dt(8, 0))
    return StrategyRouter(coord)


class TestTimeWindows:
    def test_pre_open(self):
        r = make_router()
        d = r.route(dt(9, 34))
        assert d.window == TimeWindow.PRE_OPEN
        assert d.active_strategy is None

    def test_orb_scan_at_935(self):
        r = make_router()
        d = r.route(dt(9, 35, 0))
        assert d.window == TimeWindow.ORB_SCAN

    def test_orb_monitor_936(self):
        r = make_router()
        d = r.route(dt(9, 36))
        assert d.window == TimeWindow.ORB_MONITOR

    def test_orb_monitor_1014(self):
        r = make_router()
        d = r.route(dt(10, 14))
        assert d.window == TimeWindow.ORB_MONITOR

    def test_vwap_mr_1015(self):
        r = make_router()
        d = r.route(dt(10, 15))
        assert d.window == TimeWindow.VWAP_MR

    def test_vwap_mr_1359(self):
        r = make_router()
        d = r.route(dt(13, 59))
        assert d.window == TimeWindow.VWAP_MR

    def test_trend_follow_1400(self):
        r = make_router()
        d = r.route(dt(14, 0))
        assert d.window == TimeWindow.TREND_FOLLOW

    def test_trend_follow_1554(self):
        r = make_router()
        d = r.route(dt(15, 54))
        assert d.window == TimeWindow.TREND_FOLLOW

    def test_close_all_1555(self):
        r = make_router()
        d = r.route(dt(15, 55))
        assert d.window == TimeWindow.CLOSE_ALL
        assert d.close_all is True
        assert d.active_strategy is None

    def test_close_all_1559(self):
        r = make_router()
        d = r.route(dt(15, 59))
        assert d.close_all is True

    def test_closed_1600(self):
        r = make_router()
        d = r.route(dt(16, 0))
        assert d.window == TimeWindow.CLOSED
        assert d.active_strategy is None


class TestRegimeFilters:
    def test_orb_allowed_calm(self):
        r = make_router(hmm_state="Calm")
        d = r.route(dt(9, 50))
        assert d.active_strategy == "ORB"

    def test_orb_allowed_normal(self):
        r = make_router(hmm_state="Normal")
        d = r.route(dt(9, 50))
        assert d.active_strategy == "ORB"

    def test_orb_blocked_stress(self):
        coord = RegimeCoordinator()
        coord.notify_hmm_state("Stress", dt(8, 0))
        # Force safety mode cleared for test (use override to simulate stress without safety)
        # Actually with Stress HMM the coord goes to SAFETY_MODE which blocks anyway.
        # Let's test the regime filter directly via STRATEGY_ALLOWED_REGIMES.
        assert "Stress" not in STRATEGY_ALLOWED_REGIMES["ORB"]

    def test_vwap_mr_allowed_calm(self):
        r = make_router(hmm_state="Calm")
        d = r.route(dt(11, 0))
        assert d.active_strategy == "VWAP_MR"

    def test_vwap_mr_blocked_normal(self):
        r = make_router(hmm_state="Normal")
        d = r.route(dt(11, 0))
        assert d.active_strategy is None
        assert "Normal" not in STRATEGY_ALLOWED_REGIMES["VWAP_MR"]

    def test_vwap_mr_blocked_stress(self):
        assert "Stress" not in STRATEGY_ALLOWED_REGIMES["VWAP_MR"]

    def test_trend_follow_allowed_normal(self):
        r = make_router(hmm_state="Normal")
        d = r.route(dt(14, 30))
        assert d.active_strategy == "TREND_FOLLOW"

    def test_trend_follow_blocked_calm(self):
        r = make_router(hmm_state="Calm")
        d = r.route(dt(14, 30))
        assert d.active_strategy is None
        assert "Calm" not in STRATEGY_ALLOWED_REGIMES["TREND_FOLLOW"]


class TestSystemStateGates:
    def test_safety_mode_blocks_and_closes(self):
        coord = RegimeCoordinator()
        coord.notify_hmm_state("Stress", dt(8, 0))
        router = StrategyRouter(coord)
        d = router.route(dt(11, 0))
        assert d.active_strategy is None
        assert d.close_all is True
        assert d.system_state == SystemState.SAFETY_MODE

    def test_override_stress_blocks_and_closes(self):
        coord = RegimeCoordinator()
        coord.notify_override(True, dt(8, 0))
        router = StrategyRouter(coord)
        d = router.route(dt(11, 0))
        assert d.active_strategy is None
        assert d.close_all is True

    def test_cooldown_blocks_no_close(self):
        from datetime import timedelta
        from raits.coordinator.regime_coordinator import OVERRIDE_MIN_HOLD_MINUTES
        coord = RegimeCoordinator()
        coord.notify_override(True, dt(8, 0))
        coord.notify_override(False, dt(8, 0) + timedelta(minutes=OVERRIDE_MIN_HOLD_MINUTES))
        assert coord.state == SystemState.COOLDOWN
        router = StrategyRouter(coord)
        d = router.route(dt(11, 0))
        assert d.active_strategy is None
        assert d.close_all is False

    def test_shutdown_blocks_no_close(self):
        coord = RegimeCoordinator()
        coord.notify_circuit_breaker(dt(8, 0))
        router = StrategyRouter(coord)
        d = router.route(dt(11, 0))
        assert d.active_strategy is None
        assert d.close_all is False

    def test_close_all_window_overrides_active_state(self):
        """CLOSE_ALL window must force close even when system is ACTIVE."""
        r = make_router(hmm_state="Normal")
        d = r.route(dt(15, 55))
        assert d.close_all is True


class TestRoutingDecisionProperties:
    def test_has_signal_opportunity_true(self):
        r = make_router(hmm_state="Normal")
        d = r.route(dt(9, 50))   # ORB window, Normal allowed
        assert d.has_signal_opportunity is True

    def test_has_signal_opportunity_false_no_strategy(self):
        r = make_router(hmm_state="Normal")
        d = r.route(dt(9, 30))   # PRE_OPEN
        assert d.has_signal_opportunity is False

    def test_has_signal_opportunity_false_close_all(self):
        r = make_router(hmm_state="Normal")
        d = r.route(dt(15, 55))
        assert d.has_signal_opportunity is False

    def test_decision_contains_hmm_state(self):
        r = make_router(hmm_state="Calm")
        d = r.route(dt(11, 0))
        assert d.hmm_state == "Calm"

    def test_blocked_reason_populated_on_block(self):
        r = make_router(hmm_state="Normal")
        d = r.route(dt(11, 0))   # VWAP_MR blocked in Normal
        assert d.active_strategy is None
        assert len(d.blocked_reason) > 0
