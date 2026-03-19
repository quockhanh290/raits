"""
raits.hmm — 3-state Gaussian HMM regime detection engine.

Public API
----------
    from raits.hmm import HMMEngine, VolatilityOverride, RetrainingScheduler
    from raits.hmm import HMM_STATES, CALM, NORMAL, STRESS
    from raits.hmm import build_feature_matrix
"""

from raits.hmm.engine import HMMEngine
from raits.hmm.features import build_feature_matrix, build_feature_row
from raits.hmm.retraining import RetrainingScheduler
from raits.hmm.state_sorting import CALM, HMM_STATES, NORMAL, STATE_LABELS, STRESS
from raits.hmm.volatility_override import (
    OverrideDecision,
    OverrideResult,
    VolatilityOverride,
    test_override_on_historical,
)

__all__ = [
    # Core engine
    "HMMEngine",
    # Feature engineering
    "build_feature_matrix",
    "build_feature_row",
    # Retraining
    "RetrainingScheduler",
    # State constants
    "HMM_STATES",
    "STATE_LABELS",
    "CALM",
    "NORMAL",
    "STRESS",
    # Volatility override
    "VolatilityOverride",
    "OverrideDecision",
    "OverrideResult",
    "test_override_on_historical",
]
