"""
raits/coordinator/regime_coordinator.py
----------------------------------------
Regime state machine with precedence hierarchy and cooldown logic.

Blueprint reference: Section 6.3 (Regime State Coordination Protocol)
Requirement level:  SHALL

Precedence hierarchy (highest to lowest):
    1. Volatility Override  — real-time crash detection, min 20-min hold
    2. HMM State            — weekly-retrained model output
    3. Manual Override      — testing/emergency only (not implemented here)

System states
-------------
ACTIVE          Normal trading — HMM is Calm or Normal, no override active.
OVERRIDE_STRESS Volatility override triggered — all scanners disabled.
                Minimum hold: 20 minutes from trigger time.
COOLDOWN        Override just expired — 10-minute buffer before resuming.
                Prevents whipsaw re-entry on brief volatility recovery.
SAFETY_MODE     HMM detected Stress — close all positions, halt new entries.
                Clears only when HMM returns to Calm/Normal.
SHUTDOWN        Circuit breaker fired (daily -4% or 5 consecutive losses).
                Clears only on next session reset.

State transition rules (Blueprint §6.3):
    - Any state has a minimum 30-minute hold (except SHUTDOWN, which is permanent
      until reset, and circuit-breaker escalations, which are immediate).
    - Override always beats HMM when both are active.
    - Cooldown prevents immediate re-entry after override expires.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger("RAITS.coordinator.regime")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OVERRIDE_MIN_HOLD_MINUTES: int  = 20   # override stays active at least this long
COOLDOWN_MINUTES: int           = 10   # buffer after override expires
STATE_MIN_HOLD_MINUTES: int     = 30   # no state lasts fewer than 30 minutes
                                        # (except SHUTDOWN — permanent until reset)


# ---------------------------------------------------------------------------
# SystemState
# ---------------------------------------------------------------------------

class SystemState(str, Enum):
    ACTIVE          = "ACTIVE"
    OVERRIDE_STRESS = "OVERRIDE_STRESS"
    COOLDOWN        = "COOLDOWN"
    SAFETY_MODE     = "SAFETY_MODE"
    SHUTDOWN        = "SHUTDOWN"


# ---------------------------------------------------------------------------
# RegimeCoordinator
# ---------------------------------------------------------------------------

@dataclass
class _StateRecord:
    """Internal record of a state entry."""
    state: SystemState
    entered_at: datetime
    reason: str


class RegimeCoordinator:
    """
    Stateful regime state machine.  One instance per backtest run or live session.

    The coordinator owns the authoritative answer to two questions:
        1. What is the current system state?
        2. Is new trading permitted right now?

    It does NOT execute trades or close positions — that is the router's job.
    It simply tracks state and exposes it for the router to act on.

    Usage
    -----
    coord = RegimeCoordinator()

    # Each bar, notify coordinator of current inputs:
    coord.notify_hmm_state(hmm_state, current_time)     # from HMMEngine
    coord.notify_override(active, current_time)          # from VolatilityOverride
    coord.notify_circuit_breaker(current_time)           # when breaker fires

    # Then query:
    state   = coord.state          # current SystemState
    allowed = coord.trading_allowed  # bool
    hmm     = coord.effective_hmm_state  # 'Calm'/'Normal'/'Stress' (override-aware)
    """

    def __init__(self) -> None:
        self._current: _StateRecord = _StateRecord(
            state=SystemState.ACTIVE,
            entered_at=datetime.min,
            reason="initialised",
        )
        self._hmm_state: str = "Normal"          # last known HMM output
        self._override_active: bool = False
        self._override_triggered_at: datetime | None = None
        self._cooldown_started_at: datetime | None = None
        logger.debug("RegimeCoordinator initialised — state=ACTIVE")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> SystemState:
        return self._current.state

    @property
    def trading_allowed(self) -> bool:
        """True only when state is ACTIVE — new positions may be considered."""
        return self._current.state == SystemState.ACTIVE

    @property
    def effective_hmm_state(self) -> str:
        """
        HMM state as seen by strategies.

        During OVERRIDE_STRESS or COOLDOWN the override forces 'Stress'
        regardless of what the HMM model says.  In all other states the
        actual HMM output is returned.
        """
        if self._current.state in (SystemState.OVERRIDE_STRESS, SystemState.COOLDOWN,
                                    SystemState.SAFETY_MODE, SystemState.SHUTDOWN):
            return "Stress"
        return self._hmm_state

    @property
    def hmm_state(self) -> str:
        """Raw HMM model output (unmodified by override)."""
        return self._hmm_state

    # ------------------------------------------------------------------
    # Notification API
    # ------------------------------------------------------------------

    def notify_hmm_state(self, hmm_state: str, current_time: datetime = None) -> SystemState:
        """
        Called each bar with the latest HMM output.

        HMM Stress does NOT block trading — SAFETY_MODE is reserved for Layer 0 only.
        However if we enter a session stuck in SAFETY_MODE (reset_for_new_session saw
        yesterday's Stress) and HMM has already returned to Normal/Calm, unblock trading
        so we don't lose an entire Normal day at the start of a recovery.
        """
        self._hmm_state = hmm_state
        if (hmm_state not in ("Stress", "Crisis")
                and self._current.state == SystemState.SAFETY_MODE
                and self._current.state not in (SystemState.OVERRIDE_STRESS, SystemState.COOLDOWN)):
            self._transition(SystemState.ACTIVE, current_time or datetime.utcnow(),
                             f"HMM returned to {hmm_state} — exit SAFETY_MODE")
        return self._current.state

    def notify_override(self, override_active: bool, current_time: datetime) -> SystemState:
        """
        Called each bar with the current volatility-override status.

        override_active=True  → force OVERRIDE_STRESS (beats HMM).
        override_active=False → if we were in OVERRIDE_STRESS and the minimum
                                hold has elapsed, start the COOLDOWN period.
                                After cooldown, return to HMM-based state.
        """
        if self._current.state == SystemState.SHUTDOWN:
            return self._current.state

        self._override_active = override_active

        if override_active:
            if self._current.state != SystemState.OVERRIDE_STRESS:
                self._override_triggered_at = current_time
                self._transition(SystemState.OVERRIDE_STRESS, current_time,
                                 "Volatility override triggered")

        else:
            # Override just cleared — check minimum hold
            if self._current.state == SystemState.OVERRIDE_STRESS:
                elapsed = (current_time - self._override_triggered_at).total_seconds() / 60
                if elapsed >= OVERRIDE_MIN_HOLD_MINUTES:
                    self._cooldown_started_at = current_time
                    self._transition(SystemState.COOLDOWN, current_time,
                                     f"Override expired after {elapsed:.0f} min — entering cooldown")
                else:
                    logger.debug(
                        "Override cleared but minimum hold not met (%.0f / %d min) — staying OVERRIDE_STRESS",
                        elapsed, OVERRIDE_MIN_HOLD_MINUTES,
                    )

            # Check if cooldown period has elapsed
            elif self._current.state == SystemState.COOLDOWN:
                elapsed = (current_time - self._cooldown_started_at).total_seconds() / 60
                if elapsed >= COOLDOWN_MINUTES:
                    # Transition back to HMM-driven state
                    target = SystemState.SAFETY_MODE if self._hmm_state in ("Stress", "Crisis") else SystemState.ACTIVE
                    self._transition(target, current_time,
                                     f"Cooldown complete ({elapsed:.0f} min) — resuming {target.value}")

        return self._current.state

    def notify_circuit_breaker(self, current_time: datetime) -> SystemState:
        """
        Circuit breaker fired (daily -4% or 5 consecutive losses).
        Transitions immediately to SHUTDOWN — no minimum hold applies.
        Recovery only via reset_for_new_session().
        """
        if self._current.state != SystemState.SHUTDOWN:
            self._transition(SystemState.SHUTDOWN, current_time,
                             "Circuit breaker activated — trading halted for session",
                             bypass_min_hold=True)
        return self._current.state

    def reset_for_new_session(self, session_start: datetime) -> None:
        """
        Re-arm the coordinator for a new trading session.
        Clears SHUTDOWN and SAFETY_MODE; resets override tracking.
        """
        prev = self._current.state.value
        # Always reset to ACTIVE — HMM Stress no longer implies SAFETY_MODE.
        # SAFETY_MODE is reserved for real-time Layer 0 events (notify_override).
        self._current = _StateRecord(state=SystemState.ACTIVE, entered_at=session_start,
                                     reason=f"session reset (was {prev})")
        self._override_active = False
        self._override_triggered_at = None
        self._cooldown_started_at = None
        logger.info("RegimeCoordinator reset for new session — state=ACTIVE")

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _transition(
        self,
        new_state: SystemState,
        current_time: datetime,
        reason: str,
        bypass_min_hold: bool = False,
    ) -> None:
        """Execute a state transition, respecting minimum hold time unless bypassed."""
        if not bypass_min_hold:
            elapsed = (current_time - self._current.entered_at).total_seconds() / 60
            min_hold = STATE_MIN_HOLD_MINUTES
            if elapsed < min_hold and self._current.state not in (
                SystemState.OVERRIDE_STRESS,   # override expiry uses its own timer
                SystemState.COOLDOWN,          # cooldown uses its own timer
            ):
                logger.debug(
                    "State transition %s→%s suppressed: only %.0f/%d min elapsed",
                    self._current.state.value, new_state.value, elapsed, min_hold,
                )
                return

        old = self._current.state.value
        self._current = _StateRecord(state=new_state, entered_at=current_time, reason=reason)
        logger.info("Regime: %s → %s | %s", old, new_state.value, reason)
