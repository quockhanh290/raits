"""
RAITS HMM State Sorting
========================
Prevents label-switching across retrains by sorting states consistently.

Blueprint reference: Section 3.5

Design
------
After every fit/retrain, hmmlearn may assign arbitrary integer labels to the
three regimes.  Left unsorted, "State 0" might be Stress on one retrain and
Calm on the next — breaking all downstream strategy logic.

Sorting key (composite score):
    score_i = variance_i × 1.0  +  mean_return_i × 0.1

The 10:1 weighting ensures states are ordered primarily by volatility (the
regime signal we care about), with return acting only as a tiebreaker.

After sorting:
    State 0 → Calm   (lowest variance, stable)
    State 1 → Normal (medium variance)
    State 2 → Stress (highest variance, volatile)

Downstream code can rely on numeric indices OR the HMM_STATES mapping.
"""

from __future__ import annotations

import logging
from copy import deepcopy

import numpy as np
from hmmlearn.hmm import GaussianHMM

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public constants — use these throughout the codebase for clarity
# ---------------------------------------------------------------------------

HMM_STATES: dict[int, str] = {
    0: "Calm",    # Low variance, stable returns
    1: "Normal",  # Medium variance, moderate volatility
    2: "Stress",  # High variance, extreme volatility
}

STATE_LABELS: dict[str, int] = {v: k for k, v in HMM_STATES.items()}

CALM = 0
NORMAL = 1
STRESS = 2

# Weights for composite sorting score
_VARIANCE_WEIGHT = 1.0
_RETURN_WEIGHT = 0.1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sort_hmm_states(hmm: GaussianHMM) -> GaussianHMM:
    """
    Return a *copy* of `hmm` with states reordered so that:
        State 0 = Calm, State 1 = Normal, State 2 = Stress.

    Parameters
    ----------
    hmm : GaussianHMM (fitted)
        A trained hmmlearn Gaussian HMM with n_components = 3.

    Returns
    -------
    GaussianHMM
        Deep copy with re-ordered means_, covars_, startprob_, transmat_.

    Raises
    ------
    ValueError
        If hmm.n_components != 3.
    """
    if hmm.n_components != 3:
        raise ValueError(
            f"RAITS requires exactly 3 HMM states; got {hmm.n_components}."
        )

    scores = _compute_sort_scores(hmm)
    old_to_new = _build_mapping(scores)

    sorted_hmm = _apply_mapping(hmm, old_to_new)

    _log_sort_result(hmm, sorted_hmm, old_to_new)
    return sorted_hmm


def state_name(state_idx: int) -> str:
    """Convert numeric state index to label string ("Calm" / "Normal" / "Stress")."""
    return HMM_STATES[state_idx]


def state_index(label: str) -> int:
    """Convert label string to numeric state index."""
    return STATE_LABELS[label]


def validate_state_order(hmm: GaussianHMM) -> bool:
    """
    Return True if state variance increases monotonically (0 < 1 < 2).

    Useful as a quick sanity-check after fitting or loading a model.
    """
    variances = _extract_variances(hmm)
    return bool(variances[0] < variances[1] < variances[2])


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _compute_sort_scores(hmm: GaussianHMM) -> list[tuple[int, float]]:
    """
    Compute (original_index, composite_score) for each state.

    For multi-variate HMMs, we use the *trace* of the covariance matrix
    (sum of variances along the diagonal) as the scalar variance proxy.
    For univariate models the covariance is a scalar.
    """
    scores: list[tuple[int, float]] = []
    for i in range(hmm.n_components):
        mu = hmm.means_[i]                   # shape (n_features,) or scalar
        cov = hmm.covars_[i]                 # shape varies by covariance_type

        # Scalar variance proxy: trace of diag (works for all covariance types)
        if np.ndim(cov) == 0:
            variance_proxy = float(cov)
        elif np.ndim(cov) == 1:
            # "diag" covariance type — cov is shape (n_features,)
            variance_proxy = float(np.sum(cov))
        else:
            # "full" or "tied" — cov is (n_features, n_features)
            variance_proxy = float(np.trace(cov))

        # Mean return proxy — use first feature (log-return) if multi-variate
        mean_return = float(mu[0]) if np.ndim(mu) > 0 else float(mu)

        score = variance_proxy * _VARIANCE_WEIGHT + mean_return * _RETURN_WEIGHT
        scores.append((i, score))

    return scores


def _build_mapping(scores: list[tuple[int, float]]) -> dict[int, int]:
    """
    Sort states by composite score (ascending) and return
    old_index → new_index mapping.
    """
    sorted_scores = sorted(scores, key=lambda x: x[1])
    return {old_idx: new_idx for new_idx, (old_idx, _) in enumerate(sorted_scores)}


def _apply_mapping(hmm: GaussianHMM, mapping: dict[int, int]) -> GaussianHMM:
    """
    Deep-copy the HMM and reorder its parameter arrays according to `mapping`.
    """
    sorted_hmm = deepcopy(hmm)
    n = hmm.n_components

    # Build permutation array: perm[new_idx] = old_idx
    perm = [None] * n
    for old_idx, new_idx in mapping.items():
        perm[new_idx] = old_idx

    # Reorder state-level parameters
    sorted_hmm.means_ = hmm.means_[perm]
    sorted_hmm._covars_ = hmm._covars_[perm]  # raw internal array — covars_ getter expands diag to 2D in newer hmmlearn
    sorted_hmm.startprob_ = hmm.startprob_[perm]

    # Reorder transition matrix rows *and* columns
    transmat = hmm.transmat_[np.ix_(perm, perm)]
    sorted_hmm.transmat_ = transmat

    return sorted_hmm


def _extract_variances(hmm: GaussianHMM) -> list[float]:
    """Extract scalar variance proxy per state (for validation)."""
    variances = []
    for i in range(hmm.n_components):
        cov = hmm.covars_[i]
        if np.ndim(cov) == 0:
            variances.append(float(cov))
        elif np.ndim(cov) == 1:
            variances.append(float(np.sum(cov)))
        else:
            variances.append(float(np.trace(cov)))
    return variances


def _log_sort_result(
    original: GaussianHMM,
    sorted_hmm: GaussianHMM,
    mapping: dict[int, int],
) -> None:
    orig_vars = _extract_variances(original)
    new_vars = _extract_variances(sorted_hmm)

    logger.info("HMM state sort applied:")
    for old_idx, new_idx in sorted(mapping.items(), key=lambda x: x[1]):
        logger.info(
            "  %s (old %d) → %s (new %d)  var: %.6f → %.6f",
            HMM_STATES.get(old_idx, "?"),
            old_idx,
            HMM_STATES[new_idx],
            new_idx,
            orig_vars[old_idx],
            new_vars[new_idx],
        )
