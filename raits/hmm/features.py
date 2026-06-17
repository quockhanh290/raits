"""
RAITS HMM Feature Engineering
==============================
Builds the observation matrix fed into the 4-state Gaussian HMM.

Features (2-dimensional, daily frequency):
  [0] SPY log-return        – direction / drift signal
  [1] Realized volatility   – 5-day rolling std of log-returns (annualised)

Design notes
------------
- Only SPY (market proxy) is used so the HMM captures *regime*, not stock alpha.
- Realized vol is annualised (× √252) so Calm/Normal/Stress/Crisis covariance
  values map naturally to VIX-like numbers the state-sorting algorithm can compare.
- All computations are strictly backward-looking (no look-ahead bias).
- Vol alone is sufficient to separate 4 states when trained on 2007-2024 data
  (2008 GFC and 2020 COVID provide clear Crisis examples at vol 60-80%+).
- Crisis override at vol>50% in the backtest engine acts as an additional backstop.

Section references: 3.1, 3.2 (burn-in), 3.5 (state-sorting uses mean/var).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANNUALISATION_FACTOR = np.sqrt(252)      # Daily → annual vol
DEFAULT_VOL_WINDOW = 5                   # Rolling realised vol lookback (days)
MIN_OBSERVATIONS = 30                    # Minimum rows to build a valid matrix

# Number of initial rows that will be NaN due to rolling windows — must be
# dropped before feeding the HMM.
_WARM_UP_ROWS = DEFAULT_VOL_WINDOW - 1  # 4 rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_feature_matrix(
    spy_close: pd.Series,
    vol_window: int = DEFAULT_VOL_WINDOW,
    drop_nan: bool = True,
) -> np.ndarray:
    """
    Construct the (T × 2) observation matrix for hmmlearn.

    Parameters
    ----------
    spy_close : pd.Series
        Daily close prices for SPY, indexed by date (oldest first).
    vol_window : int
        Rolling window for realised volatility calculation (default 5 days).
    drop_nan : bool
        Drop leading NaN rows produced by rolling window (default True).
        Set False only if you need to preserve alignment with raw price index.

    Returns
    -------
    np.ndarray, shape (T, 2)
        Column 0 – daily log-return
        Column 1 – annualised realised volatility (5-day rolling)

    Raises
    ------
    ValueError
        If the resulting matrix has fewer than MIN_OBSERVATIONS rows.
    """
    min_required = vol_window + MIN_OBSERVATIONS
    if len(spy_close) < min_required:
        raise ValueError(
            f"Need at least {min_required} price observations; "
            f"got {len(spy_close)}."
        )

    log_returns  = _compute_log_returns(spy_close)
    realised_vol = _compute_realised_vol(log_returns, vol_window)

    features = pd.DataFrame(
        {
            "log_return":   log_returns,
            "realised_vol": realised_vol,
        },
        index=spy_close.index,
    )

    if drop_nan:
        features = features.dropna()

    if len(features) < MIN_OBSERVATIONS:
        raise ValueError(
            f"After dropping NaN rows only {len(features)} observations remain "
            f"(minimum required: {MIN_OBSERVATIONS})."
        )

    matrix = features[["log_return", "realised_vol"]].values.astype(np.float64)
    logger.debug(
        "Feature matrix built: shape=%s, log_return μ=%.4f, vol μ=%.4f",
        matrix.shape,
        matrix[:, 0].mean(),
        matrix[:, 1].mean(),
    )
    return matrix


def build_feature_row(
    spy_close_recent: pd.Series,
    vol_window: int = DEFAULT_VOL_WINDOW,
) -> np.ndarray:
    """
    Build a single-row (1 × 2) observation for real-time regime inference.

    Parameters
    ----------
    spy_close_recent : pd.Series
        Recent SPY closes (minimum vol_window + 1 values), oldest first.

    Returns
    -------
    np.ndarray, shape (1, 2)
    """
    required = vol_window + 1
    if len(spy_close_recent) < required:
        raise ValueError(
            f"Need at least {required} recent closes for a single feature row; "
            f"got {len(spy_close_recent)}."
        )

    tail_vol     = spy_close_recent.iloc[-(vol_window + 1):]
    log_ret      = _compute_log_returns(tail_vol)
    realised_vol = _compute_realised_vol(log_ret, vol_window).dropna()

    latest_log_ret = float(log_ret.iloc[-1])
    latest_vol     = float(realised_vol.iloc[-1])

    row = np.array([[latest_log_ret, latest_vol]], dtype=np.float64)
    logger.debug(
        "Single feature row: log_return=%.4f, realised_vol=%.4f",
        latest_log_ret,
        latest_vol,
    )
    return row


def get_feature_names() -> list[str]:
    """Return ordered list of feature column names (for logging / debugging)."""
    return ["log_return", "realised_vol"]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _compute_log_returns(prices: pd.Series) -> pd.Series:
    """Compute daily log-returns: ln(P_t / P_{t-1})."""
    return np.log(prices / prices.shift(1))


def _compute_realised_vol(
    log_returns: pd.Series,
    window: int,
) -> pd.Series:
    """
    Rolling realised volatility, annualised.

    RV_t = std(log_returns_{t-window+1 : t}) × √252
    """
    return log_returns.rolling(window).std() * ANNUALISATION_FACTOR
