"""
RAITS HMM Retraining Scheduler
================================
Manages both scheduled (weekly) and event-driven (emergency) retraining.

Blueprint references: Section 3.3 (weekly), Section 3.4 (emergency)

Design
------
Two independent retraining pathways:

1. Weekly (Section 3.3)
   - Every Sunday at 00:00 UTC
   - Rolling 252-day lookback
   - New parameters apply from Monday market open

2. Emergency (Section 3.4)
   - Trigger A: VIX daily change > 25%
   - Trigger B: SPY intraday return |>| 3%
   - Queued for 16:05 ET if triggered during market hours
   - Executes immediately if triggered after hours
   - Fallback to last-good model if new model fails validation

Alert: if ≥ 3 emergency retrains fire in 5 trading days → operator alert.

For backtesting, use RetrainingScheduler.simulate_weekly_retrains() which
replays the weekly schedule on a historical price series.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

import pandas as pd

from raits.hmm.engine import HMMEngine, TRAINING_LOOKBACK_DAYS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Emergency trigger thresholds (Section 3.4)
VIX_SPIKE_THRESHOLD = 0.25        # 25% daily VIX change
SPY_MOVE_THRESHOLD = 0.03         # ±3% intraday SPY move

# Alert parameters (Section 3.4)
EMERGENCY_ALERT_COUNT = 3
EMERGENCY_ALERT_WINDOW_DAYS = 5

# Emergency retrain execution window
EMERGENCY_RETRAIN_HOUR_ET = 16    # 4:00 PM ET (after market close)
EMERGENCY_RETRAIN_MINUTE_ET = 5   # 16:05 ET


# ---------------------------------------------------------------------------
# Retraining scheduler
# ---------------------------------------------------------------------------

class RetrainingScheduler:
    """
    Coordinates weekly and emergency HMM retrains.

    Parameters
    ----------
    engine : HMMEngine
        The active HMM engine to retrain.
    data_fetcher : callable
        Function that returns a pd.Series of SPY daily closes given
        a lookback of `n` trading days.  Signature:
            fetch_spy_closes(n_days: int) -> pd.Series
    alert_callback : callable, optional
        Called when the emergency alert threshold is exceeded.
        Signature:  alert(message: str) -> None
    """

    def __init__(
        self,
        engine: HMMEngine,
        data_fetcher: Callable[[int], pd.Series],
        alert_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._engine = engine
        self._fetch = data_fetcher
        self._alert = alert_callback or _default_alert

        # Ring buffer tracking emergency retrain timestamps (last 5 days)
        self._emergency_history: deque[datetime] = deque()
        self._pending_emergency: bool = False

    # ------------------------------------------------------------------
    # Weekly retrain (Section 3.3)
    # ------------------------------------------------------------------

    def check_weekly_retrain(self, today: date) -> bool:
        """
        Trigger a weekly retrain if today is Sunday.

        Returns True if a retrain was attempted (not necessarily successful).
        """
        if today.weekday() != 6:   # 6 = Sunday
            return False

        logger.info("Weekly HMM retrain triggered (Sunday %s)", today.isoformat())
        spy_closes = self._fetch(TRAINING_LOOKBACK_DAYS)
        version_tag = f"weekly_{today.strftime('%Y%m%d')}"
        success = self._engine.retrain(spy_closes, version_tag=version_tag)

        if success:
            logger.info("Weekly HMM retrain completed (v%s)", version_tag)
        else:
            logger.warning("Weekly retrain failed — current model retained")

        return True

    # ------------------------------------------------------------------
    # Emergency retrain (Section 3.4)
    # ------------------------------------------------------------------

    def check_emergency_triggers(
        self,
        vix_current: float,
        vix_previous_close: float,
        spy_current: float,
        spy_open: float,
        current_dt: datetime,
    ) -> bool:
        """
        Evaluate Trigger A (VIX) and Trigger B (SPY) and schedule a retrain
        if either fires.

        Parameters
        ----------
        vix_current : float
            Current VIX level.
        vix_previous_close : float
            Previous session's VIX close.
        spy_current : float
            Current SPY price.
        spy_open : float
            SPY opening price for today.
        current_dt : datetime
            Current datetime (timezone-aware, ET preferred).

        Returns
        -------
        bool
            True if an emergency retrain was scheduled/executed.
        """
        triggered = False

        # --- Trigger A: VIX spike ---
        if vix_previous_close > 0:
            vix_change = (vix_current - vix_previous_close) / vix_previous_close
            if vix_change > VIX_SPIKE_THRESHOLD:
                logger.warning(
                    "EMERGENCY RETRAIN TRIGGERED (A): VIX spike %.1f%% "
                    "(%.1f → %.1f)",
                    vix_change * 100,
                    vix_previous_close,
                    vix_current,
                )
                triggered = True

        # --- Trigger B: SPY intraday move ---
        if not triggered and spy_open > 0:
            spy_intraday_return = (spy_current - spy_open) / spy_open
            if abs(spy_intraday_return) > SPY_MOVE_THRESHOLD:
                logger.warning(
                    "EMERGENCY RETRAIN TRIGGERED (B): SPY intraday return %.2f%%",
                    spy_intraday_return * 100,
                )
                triggered = True

        if triggered and not self._pending_emergency:
            self._schedule_emergency_retrain(current_dt)
            return True

        return False

    def execute_pending_emergency_retrain(self, current_dt: datetime) -> bool:
        """
        Execute a previously-queued emergency retrain if the time window has
        arrived (16:05 ET or later, or after hours).

        Call this method periodically (e.g. every 5 minutes) from the main loop.
        """
        if not self._pending_emergency:
            return False

        if _is_market_hours(current_dt) and not _is_after_retrain_window(current_dt):
            logger.debug(
                "Emergency retrain pending — waiting for 16:05 ET "
                "(current: %s)", current_dt.strftime("%H:%M")
            )
            return False

        logger.info("Executing queued emergency HMM retrain...")
        self._pending_emergency = False
        spy_closes = self._fetch(TRAINING_LOOKBACK_DAYS)
        tag = f"emergency_{current_dt.strftime('%Y%m%d_%H%M')}"
        success = self._engine.retrain(spy_closes, version_tag=tag)

        # Record in alert history
        self._emergency_history.append(current_dt)
        self._prune_alert_history(current_dt)
        self._check_alert_threshold(current_dt)

        if success:
            logger.info("Emergency retrain completed (v%s)", tag)
        else:
            logger.warning("Emergency retrain failed — model unchanged")

        return True

    # ------------------------------------------------------------------
    # Backtesting helper
    # ------------------------------------------------------------------

    def simulate_weekly_retrains(
        self,
        spy_daily_close: pd.Series,
        initial_train_end: int = TRAINING_LOOKBACK_DAYS,
    ) -> list[dict]:
        """
        Replay weekly retraining schedule on a historical price series.

        Designed for the WFO loop (Section 7.2): each Sunday triggers a
        retrain using the prior 252 trading days.

        Parameters
        ----------
        spy_daily_close : pd.Series
            Full historical SPY daily closes (datetime-indexed).
        initial_train_end : int
            Index of last day used for initial training (burn-in boundary).

        Returns
        -------
        list of dict
            Each entry: {date, version, success, log_likelihood}
        """
        records = []
        dates = spy_daily_close.index

        for i in range(initial_train_end, len(dates)):
            current_date = pd.Timestamp(dates[i]).date()

            # Business-day series (Mon–Fri) never contain Sundays.
            # Trigger on Monday — first trading day after the weekend retrain.
            if current_date.weekday() != 0:  # Not Monday
                continue

            # Rolling 252-day window, strictly before current date
            window_end = i
            window_start = max(0, window_end - TRAINING_LOOKBACK_DAYS)
            window = spy_daily_close.iloc[window_start:window_end]

            tag = f"sim_weekly_{current_date.strftime('%Y%m%d')}"
            success = self._engine.retrain(window, version_tag=tag, save=False)

            log_ll = None
            if success and self._engine.is_fitted():
                from raits.hmm.features import build_feature_matrix
                try:
                    X = build_feature_matrix(window)
                    log_ll = float(self._engine.model.score(X))
                except Exception:
                    pass

            records.append({
                "date": current_date,
                "version": tag,
                "success": success,
                "log_likelihood": log_ll,
                "window_start": window.index[0] if len(window) > 0 else None,
                "window_end": window.index[-1] if len(window) > 0 else None,
            })
            logger.info(
                "Simulated weekly retrain %s: success=%s, log-L=%.2f",
                current_date,
                success,
                log_ll or float("nan"),
            )

        return records

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _schedule_emergency_retrain(self, current_dt: datetime) -> None:
        """Queue an emergency retrain for 16:05 ET (or immediately if after hours)."""
        self._pending_emergency = True
        if _is_market_hours(current_dt):
            logger.info(
                "Emergency retrain queued for 16:05 ET "
                "(triggered at %s)", current_dt.strftime("%H:%M")
            )
        else:
            logger.info("Emergency retrain queued for immediate execution (after hours)")

    def _prune_alert_history(self, current_dt: datetime) -> None:
        """Remove retrain records older than EMERGENCY_ALERT_WINDOW_DAYS."""
        cutoff = current_dt - timedelta(days=EMERGENCY_ALERT_WINDOW_DAYS)
        while self._emergency_history and self._emergency_history[0] < cutoff:
            self._emergency_history.popleft()

    def _check_alert_threshold(self, current_dt: datetime) -> None:
        """Fire alert if ≥ EMERGENCY_ALERT_COUNT retrains in the alert window."""
        count = len(self._emergency_history)
        if count >= EMERGENCY_ALERT_COUNT:
            msg = (
                f"CRITICAL: {count} emergency HMM retrains in the last "
                f"{EMERGENCY_ALERT_WINDOW_DAYS} days (latest: {current_dt}). "
                "Market may be in unprecedented volatility regime. "
                "Manual intervention recommended."
            )
            logger.critical(msg)
            self._alert(msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_market_hours(dt: datetime) -> bool:
    """
    Naive check: market is open if time is between 09:30 and 16:00.
    For production, replace with a proper trading calendar (e.g. pandas_market_calendars).
    """
    hour, minute = dt.hour, dt.minute
    if 9 < hour < 16:
        return True
    if hour == 9 and minute >= 30:
        return True
    return False


def _is_after_retrain_window(dt: datetime) -> bool:
    """Return True if current time >= 16:05 ET (emergency retrain window open)."""
    return dt.hour > EMERGENCY_RETRAIN_HOUR_ET or (
        dt.hour == EMERGENCY_RETRAIN_HOUR_ET
        and dt.minute >= EMERGENCY_RETRAIN_MINUTE_ET
    )


def _default_alert(message: str) -> None:
    """Default alert handler — logs at CRITICAL level."""
    logger.critical("ALERT: %s", message)
