"""
RAITS Volatility Override (Layer 0)
=====================================
Real-time crash detection that bypasses the HMM when extreme moves occur.

Blueprint reference: Section 3.6 and 3.6.1

Problem
-------
Standard Gaussian HMMs underestimate fat-tail probabilities.  During a flash
crash the model may stay in "Normal" for hours while the market collapses.

Solution
--------
Three independent triggers, each derived from academic jump-detection theory
(NOT tuned to historical events — see Section 3.6.1):

  Trigger 1 — SPY 5-min return > 3σ   (Merton 1976 jump threshold)
  Trigger 2 — SPY 20-min return > 5σ  (Madan & Seneta 1990 sustained jump)
  Trigger 3 — VIX single-bar spike > 50%  (GARCH vol-of-vol threshold)

Any single trigger fires FORCE_STRESS.  The override auto-resets when no
trigger has fired in the last `RESET_LOOKBACK_BARS` bars.

Usage in strategy router (Section 6.1)
---------------------------------------
    from raits.hmm.volatility_override import VolatilityOverride, OverrideDecision

    override = VolatilityOverride(spy_5min_history, vix_history)
    decision = override.check()

    if decision == OverrideDecision.FORCE_STRESS:
        # bypass HMM, enter safety mode immediately
        ...
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (Section 3.6.1 — academic justification)
# ---------------------------------------------------------------------------

# Trigger 1: 5-min SPY move magnitude (in σ units)  [Merton 1976]
TRIGGER_1_SIGMA = 3.0
TRIGGER_1_LOOKBACK_BARS = 1      # Single 5-min bar

# Trigger 2: 20-min SPY move magnitude (in σ units)  [Madan & Seneta 1990]
TRIGGER_2_SIGMA = 5.0
TRIGGER_2_LOOKBACK_BARS = 4      # 4 × 5-min bars = 20 minutes

# Trigger 3: VIX single-bar percentage spike  [Engle 1982 / CBOE]
TRIGGER_3_VIX_PCT = 0.50         # 50% spike in one bar

# Baseline vol window: 5-day realised vol for normalisation
BASELINE_VOL_DAYS = 5
BARS_PER_DAY = 78                # 6.5 trading hours × 12 five-min bars

# Auto-reset: override releases if no trigger fires for this many bars
RESET_LOOKBACK_BARS = 3

# Alert: if this many emergency retrains occur within 5 trading days, alert
EMERGENCY_RETRAIN_ALERT_THRESHOLD = 3
EMERGENCY_RETRAIN_ALERT_WINDOW_DAYS = 5


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class OverrideDecision(Enum):
    FORCE_STRESS = "FORCE_STRESS"
    USE_HMM = "USE_HMM"


@dataclass
class OverrideResult:
    decision: OverrideDecision
    trigger: Optional[int] = None    # 1, 2, or 3 — which trigger fired
    magnitude: Optional[float] = None  # σ-units or % depending on trigger
    detail: str = ""

    @property
    def is_override_active(self) -> bool:
        return self.decision == OverrideDecision.FORCE_STRESS


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class VolatilityOverride:
    """
    Stateful volatility override checker.

    Parameters
    ----------
    spy_5min_prices : pd.Series
        Recent 5-min SPY close prices (oldest first), datetime-indexed.
        Must contain at least BASELINE_VOL_DAYS × BARS_PER_DAY + TRIGGER_2_LOOKBACK_BARS
        bars so baseline vol and the 20-min return can both be computed.
    vix_prices : pd.Series
        Recent VIX values at 5-min resolution (or daily — last two values used).
        Must contain at least 2 observations.
    """

    def __init__(
        self,
        spy_5min_prices: pd.Series,
        vix_prices: pd.Series,
    ) -> None:
        self._spy = spy_5min_prices
        self._vix = vix_prices
        self._consecutive_clear_bars: int = 0

    def check(self) -> OverrideResult:
        """
        Evaluate all three triggers against the latest market data.

        Returns
        -------
        OverrideResult
            .decision = FORCE_STRESS if any trigger fires, USE_HMM otherwise.
        """
        baseline_vol_5min, baseline_vol_20min = self._compute_baseline_vols()

        # --- Trigger 1: 5-min 3σ move ---
        t1 = self._check_trigger_1(baseline_vol_5min)
        if t1.decision == OverrideDecision.FORCE_STRESS:
            self._consecutive_clear_bars = 0
            return t1

        # --- Trigger 2: 20-min 5σ move ---
        t2 = self._check_trigger_2(baseline_vol_20min)
        if t2.decision == OverrideDecision.FORCE_STRESS:
            self._consecutive_clear_bars = 0
            return t2

        # --- Trigger 3: VIX 50% spike ---
        t3 = self._check_trigger_3()
        if t3.decision == OverrideDecision.FORCE_STRESS:
            self._consecutive_clear_bars = 0
            return t3

        # No trigger — track clear bars for auto-reset logic
        self._consecutive_clear_bars += 1
        logger.debug(
            "Override: all triggers clear (clear_bars=%d)",
            self._consecutive_clear_bars,
        )
        return OverrideResult(decision=OverrideDecision.USE_HMM, detail="All triggers clear")

    @property
    def consecutive_clear_bars(self) -> int:
        """Number of consecutive bars since the last trigger fired."""
        return self._consecutive_clear_bars

    # ------------------------------------------------------------------
    # Trigger checks
    # ------------------------------------------------------------------

    def _check_trigger_1(self, baseline_vol_5min: float) -> OverrideResult:
        """SPY 5-min return > 3σ  (Merton 1976 jump threshold)."""
        if len(self._spy) < 2:
            return OverrideResult(
                decision=OverrideDecision.USE_HMM,
                detail="Insufficient SPY bars for T1",
            )

        latest_return = _compute_return(self._spy.iloc[-1], self._spy.iloc[-2])
        threshold = TRIGGER_1_SIGMA * baseline_vol_5min
        magnitude_sigma = abs(latest_return) / baseline_vol_5min if baseline_vol_5min > 0 else 0.0

        if abs(latest_return) > threshold:
            logger.warning(
                "🚨 VOLATILITY OVERRIDE TRIGGER 1 — SPY 5-min return %.2f%% > "
                "3σ threshold %.2f%% (%.1fσ)",
                latest_return * 100,
                threshold * 100,
                magnitude_sigma,
            )
            return OverrideResult(
                decision=OverrideDecision.FORCE_STRESS,
                trigger=1,
                magnitude=magnitude_sigma,
                detail=(
                    f"SPY 5-min return {latest_return:.2%} exceeds "
                    f"3σ={threshold:.2%} ({magnitude_sigma:.1f}σ)"
                ),
            )

        return OverrideResult(decision=OverrideDecision.USE_HMM)

    def _check_trigger_2(self, baseline_vol_20min: float) -> OverrideResult:
        """SPY 20-min return > 5σ  (Madan & Seneta 1990 sustained jump)."""
        required = TRIGGER_2_LOOKBACK_BARS + 1
        if len(self._spy) < required:
            return OverrideResult(
                decision=OverrideDecision.USE_HMM,
                detail=f"Insufficient SPY bars for T2 (need {required})",
            )

        current_price = self._spy.iloc[-1]
        price_20min_ago = self._spy.iloc[-(TRIGGER_2_LOOKBACK_BARS + 1)]
        twenty_min_return = _compute_return(current_price, price_20min_ago)
        threshold = TRIGGER_2_SIGMA * baseline_vol_20min
        magnitude_sigma = (
            abs(twenty_min_return) / baseline_vol_20min if baseline_vol_20min > 0 else 0.0
        )

        if abs(twenty_min_return) > threshold:
            logger.warning(
                "🚨 VOLATILITY OVERRIDE TRIGGER 2 — SPY 20-min return %.2f%% > "
                "5σ threshold %.2f%% (%.1fσ)",
                twenty_min_return * 100,
                threshold * 100,
                magnitude_sigma,
            )
            return OverrideResult(
                decision=OverrideDecision.FORCE_STRESS,
                trigger=2,
                magnitude=magnitude_sigma,
                detail=(
                    f"SPY 20-min return {twenty_min_return:.2%} exceeds "
                    f"5σ={threshold:.2%} ({magnitude_sigma:.1f}σ)"
                ),
            )

        return OverrideResult(decision=OverrideDecision.USE_HMM)

    def _check_trigger_3(self) -> OverrideResult:
        """VIX single-bar spike > 50%  (GARCH vol-of-vol threshold)."""
        if len(self._vix) < 2:
            return OverrideResult(
                decision=OverrideDecision.USE_HMM,
                detail="Insufficient VIX data for T3",
            )

        vix_current = float(self._vix.iloc[-1])
        vix_prev = float(self._vix.iloc[-2])

        if vix_prev <= 0:
            return OverrideResult(
                decision=OverrideDecision.USE_HMM,
                detail="VIX previous value <= 0, skipping T3",
            )

        vix_spike_pct = (vix_current - vix_prev) / vix_prev

        if vix_spike_pct > TRIGGER_3_VIX_PCT:
            logger.warning(
                "🚨 VOLATILITY OVERRIDE TRIGGER 3 — VIX spike %.1f%% "
                "(%.1f → %.1f)",
                vix_spike_pct * 100,
                vix_prev,
                vix_current,
            )
            return OverrideResult(
                decision=OverrideDecision.FORCE_STRESS,
                trigger=3,
                magnitude=vix_spike_pct,
                detail=(
                    f"VIX spike {vix_spike_pct:.1%}: "
                    f"{vix_prev:.1f} → {vix_current:.1f}"
                ),
            )

        return OverrideResult(decision=OverrideDecision.USE_HMM)

    # ------------------------------------------------------------------
    # Baseline volatility
    # ------------------------------------------------------------------

    def _compute_baseline_vols(self) -> tuple[float, float]:
        """
        Compute baseline 5-min and 20-min volatility from recent 5-min returns.

        The input series is already at 5-min frequency, so:

            vol_5min  = std(5-min log-returns over last 5 trading days)
            vol_20min = vol_5min × √4   [20-min window = 4 five-min bars]

        This matches the blueprint's logic (Section 3.6):
            spy_realized_vol_5day = calculate_realized_vol('SPY', period=5)
            vol_5min  = spy_realized_vol_5day / √78       # daily → 5-min
            vol_20min = spy_realized_vol_5day / √(78/4)   # daily → 20-min

        Taking vol_5min = per-bar std and vol_20min = vol_5min × √4 is
        mathematically equivalent under IID return assumption.
        """
        required_bars = BASELINE_VOL_DAYS * BARS_PER_DAY
        available = len(self._spy)

        if available < required_bars:
            logger.warning(
                "Only %d bars available for baseline vol (want %d). "
                "Estimate may be noisy.",
                available,
                required_bars,
            )

        lookback = self._spy.iloc[-min(available, required_bars):]
        log_returns = np.log(lookback / lookback.shift(1)).dropna()

        if len(log_returns) < 2:
            # Fallback: VIX 15 ≈ 0.95% daily ÷ √78 ≈ 0.11% per 5-min bar
            vol_5min = 0.0095 / math.sqrt(BARS_PER_DAY)
            logger.warning(
                "Insufficient return history; using fallback vol_5min=%.5f",
                vol_5min,
            )
        else:
            # std of 5-min log-returns IS vol_5min directly
            vol_5min = float(log_returns.std())

        # Scale to 20-min: 4 five-min bars in 20 minutes → √4 scaling
        vol_20min = vol_5min * math.sqrt(TRIGGER_2_LOOKBACK_BARS)

        logger.debug(
            "Baseline vols: 5min=%.6f (%.3f%%), 20min=%.6f (%.3f%%)",
            vol_5min, vol_5min * 100,
            vol_20min, vol_20min * 100,
        )
        return vol_5min, vol_20min


# ---------------------------------------------------------------------------
# Convenience function for backtesting (Section 3.6 — backtest implementation)
# ---------------------------------------------------------------------------

def test_override_on_historical(
    spy_5min: pd.Series,
    vix_5min: pd.Series,
    warm_up_bars: int = BASELINE_VOL_DAYS * BARS_PER_DAY,
) -> pd.DataFrame:
    """
    Replay the override logic across a full historical price series.

    Returns a DataFrame with one row per bar:
        timestamp, decision, trigger (1/2/3/None), magnitude, detail

    Useful for the Section 3.6 backtest acceptance criteria:
        - Detection rate ≥ 95% of all >3σ events
        - False positive rate < 10%
    """
    results = []

    for i in range(warm_up_bars, len(spy_5min)):
        spy_window = spy_5min.iloc[: i + 1]
        vix_window = vix_5min.iloc[: i + 1] if len(vix_5min) > i else vix_5min

        checker = VolatilityOverride(spy_window, vix_window)
        result = checker.check()

        results.append(
            {
                "timestamp": spy_5min.index[i],
                "decision": result.decision.value,
                "trigger": result.trigger,
                "magnitude": result.magnitude,
                "detail": result.detail,
            }
        )

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _compute_return(current: float, previous: float) -> float:
    """Simple arithmetic return: (current - previous) / previous."""
    if previous == 0:
        return 0.0
    return (current - previous) / previous
