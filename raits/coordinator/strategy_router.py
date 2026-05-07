"""
raits/coordinator/strategy_router.py
--------------------------------------
Time-based and regime-based strategy activation.

Blueprint reference: Section 6.2 (Master Strategy Router), Section 4.1
Requirement level:  SHALL

Time windows (all times US/Eastern, market hours only):
    PRE_OPEN       before 9:35              — no trading
    ORB_SCAN       9:35                     — build ORB watchlist (one-shot)
    ORB_MONITOR    9:35 – 10:15             — ORB breakout monitoring
    VWAP_MR        10:15 – 14:00            — VWAP mean reversion
    TREND_FOLLOW   14:00 – 15:55            — trend / momentum
    CLOSE_ALL      15:55 – 16:00            — forced EOD exit, no new entries
    CLOSED         after 16:00              — market closed

Regime filter (Blueprint §6.1):
    ORB:          Calm, Normal   (blocked during Stress)
    VWAP_MR:      Calm only
    TREND_FOLLOW: Normal, Stress (trends persist during volatility)
    CASH:         Stress         (no new entries, held by RegimeCoordinator)

Execution note
--------------
StrategyRouter does NOT call strategy engines or HMMEngine directly.
It returns a RoutingDecision that tells the backtester/executor:
    - which strategy to invoke (if any)
    - whether a forced close-all is needed
The backtester loop calls the appropriate strategy engine and passes
back any resulting signal to ConflictResolver for position-limit gating.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum

from raits.coordinator.regime_coordinator import RegimeCoordinator, SystemState

logger = logging.getLogger("RAITS.coordinator.router")

# ---------------------------------------------------------------------------
# Time-window boundaries (ET, inclusive-start exclusive-end)
# ---------------------------------------------------------------------------

_ORB_SCAN_START     = time(9, 35)
_ORB_MONITOR_END    = time(10, 15)
_VWAP_MR_END        = time(14, 0)
_TREND_FOLLOW_END   = time(15, 55)
_MARKET_CLOSE       = time(16, 0)


# ---------------------------------------------------------------------------
# Regime filters
# ---------------------------------------------------------------------------

STRATEGY_ALLOWED_REGIMES: dict[str, list[str]] = {
    "ORB":          ["Calm", "Normal"],
    "VWAP_MR":      ["Calm"],
    "TREND_FOLLOW": ["Normal", "Stress"],
}


# ---------------------------------------------------------------------------
# RoutingDecision
# ---------------------------------------------------------------------------

class TimeWindow(str, Enum):
    PRE_OPEN        = "PRE_OPEN"
    ORB_SCAN        = "ORB_SCAN"       # 9:35 one-shot scanner run
    ORB_MONITOR     = "ORB_MONITOR"    # 9:35–10:15 breakout watch
    VWAP_MR         = "VWAP_MR"
    TREND_FOLLOW    = "TREND_FOLLOW"
    CLOSE_ALL       = "CLOSE_ALL"      # 15:55–16:00 forced EOD exit
    CLOSED          = "CLOSED"         # after 16:00


@dataclass(frozen=True)
class RoutingDecision:
    """
    The output of StrategyRouter.route() for a single bar.

    Fields
    ------
    window          : which time window this bar falls in
    active_strategy : strategy to invoke, or None if no trading permitted
    close_all       : True = executor must close all open positions this bar
    blocked_reason  : why active_strategy is None (for logging)
    system_state    : RegimeCoordinator state at decision time
    hmm_state       : effective HMM state seen by strategies
    """
    window: TimeWindow
    active_strategy: str | None
    close_all: bool
    blocked_reason: str
    system_state: SystemState
    hmm_state: str

    @property
    def has_signal_opportunity(self) -> bool:
        return self.active_strategy is not None and not self.close_all


# ---------------------------------------------------------------------------
# StrategyRouter
# ---------------------------------------------------------------------------

class StrategyRouter:
    """
    Translates (current_time, regime_state) → RoutingDecision.

    Designed to be called once per bar per ticker in the backtesting loop,
    or once per bar in live trading (ticker-agnostic routing).

    The router does not maintain its own state beyond what it delegates
    to RegimeCoordinator — it is effectively a pure function of its inputs.

    Parameters
    ----------
    coordinator : RegimeCoordinator
        The shared state machine.  Must be notified externally before
        route() is called (notify_hmm_state, notify_override, etc.).
    """

    def __init__(self, coordinator: RegimeCoordinator) -> None:
        self._coord = coordinator

    def route(self, current_time: datetime) -> RoutingDecision:
        """
        Determine which strategy (if any) should run for this bar.

        Parameters
        ----------
        current_time : datetime
            The timestamp of the current bar (market hours, ET assumed).

        Returns
        -------
        RoutingDecision
        """
        t = current_time.time()
        state = self._coord.state
        hmm   = self._coord.effective_hmm_state

        # ── Determine time window ────────────────────────────────────────────
        window = self._classify_window(t)

        # ── Force-close window: no new entries, close everything ─────────────
        if window == TimeWindow.CLOSE_ALL:
            logger.debug("CLOSE_ALL window at %s", current_time.strftime("%H:%M"))
            return RoutingDecision(
                window=window, active_strategy=None,
                close_all=True, blocked_reason="EOD force-close window",
                system_state=state, hmm_state=hmm,
            )

        # ── Outside market hours ─────────────────────────────────────────────
        if window in (TimeWindow.PRE_OPEN, TimeWindow.CLOSED):
            return RoutingDecision(
                window=window, active_strategy=None,
                close_all=False, blocked_reason="Outside market hours",
                system_state=state, hmm_state=hmm,
            )

        # ── System not in ACTIVE state ───────────────────────────────────────
        if state != SystemState.ACTIVE:
            close_all = state in (SystemState.SAFETY_MODE, SystemState.OVERRIDE_STRESS)
            reason = f"System state={state.value} — trading halted"
            logger.debug(reason)
            return RoutingDecision(
                window=window, active_strategy=None,
                close_all=close_all, blocked_reason=reason,
                system_state=state, hmm_state=hmm,
            )

        # ── Map time window to strategy and check regime filter ──────────────
        candidate = self._window_to_strategy(window)

        if candidate is None:
            return RoutingDecision(
                window=window, active_strategy=None,
                close_all=False, blocked_reason="No strategy mapped to this window",
                system_state=state, hmm_state=hmm,
            )

        allowed_regimes = STRATEGY_ALLOWED_REGIMES.get(candidate, [])
        if hmm not in allowed_regimes:
            reason = (
                f"{candidate} blocked: regime={hmm} not in "
                f"allowed={allowed_regimes}"
            )
            logger.debug(reason)
            return RoutingDecision(
                window=window, active_strategy=None,
                close_all=False, blocked_reason=reason,
                system_state=state, hmm_state=hmm,
            )

        logger.debug(
            "Route: window=%s strategy=%s regime=%s",
            window.value, candidate, hmm,
        )
        return RoutingDecision(
            window=window, active_strategy=candidate,
            close_all=False, blocked_reason="",
            system_state=state, hmm_state=hmm,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_window(t: time) -> TimeWindow:
        """Map a wall-clock time (ET) to a TimeWindow."""
        if t < _ORB_SCAN_START:
            return TimeWindow.PRE_OPEN
        if t < _ORB_MONITOR_END:
            # 9:35 is both SCAN and the start of MONITOR — treat as ORB_MONITOR.
            # The backtester should call orb.run_scanner() once at exactly 9:35
            # and then orb.generate_signal() for subsequent bars through 10:15.
            if t == _ORB_SCAN_START:
                return TimeWindow.ORB_SCAN
            return TimeWindow.ORB_MONITOR
        if t < _VWAP_MR_END:
            return TimeWindow.VWAP_MR
        if t < _TREND_FOLLOW_END:
            return TimeWindow.TREND_FOLLOW
        if t < _MARKET_CLOSE:
            return TimeWindow.CLOSE_ALL
        return TimeWindow.CLOSED

    @staticmethod
    def _window_to_strategy(window: TimeWindow) -> str | None:
        """Return the strategy name for a given active time window."""
        mapping = {
    TimeWindow.ORB_SCAN:     "ORB",
    TimeWindow.ORB_MONITOR:  "ORB",
    # VWAP_MR disabled -- structural fit failure on trending universe
    # TimeWindow.VWAP_MR:   "VWAP_MR",
    TimeWindow.TREND_FOLLOW: "TREND_FOLLOW",
}
        return mapping.get(window)
