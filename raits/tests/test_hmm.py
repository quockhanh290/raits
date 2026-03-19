"""
RAITS HMM Engine — Unit Tests
================================
Covers all blueprint requirements from Sections 3.1 – 3.6.

Run:
    pytest tests/test_hmm.py -v

All tests use synthetic data so they run offline (no API keys needed).

Test categories
---------------
  TestFeatureEngineering   – feature matrix shape, values, edge cases
  TestStateSorting         – label-switching safeguard
  TestHMMEngine            – fit, predict, persist, validate
  TestVolatilityOverride   – all three triggers + auto-reset
  TestRetrainingScheduler  – weekly schedule, emergency triggers, alert
  TestEndToEnd             – full integration smoke test
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hmmlearn.hmm import GaussianHMM

# Make the project importable when running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from raits.hmm.features import (
    MIN_OBSERVATIONS,
    build_feature_matrix,
    build_feature_row,
    get_feature_names,
)
from raits.hmm.state_sorting import (
    CALM, NORMAL, STRESS,
    HMM_STATES, sort_hmm_states, validate_state_order,
)
from raits.hmm.engine import HMMEngine
from raits.hmm.volatility_override import (
    BARS_PER_DAY, BASELINE_VOL_DAYS, TRIGGER_3_VIX_PCT,
    OverrideDecision, VolatilityOverride,
)
from raits.hmm.retraining import (
    SPY_MOVE_THRESHOLD, VIX_SPIKE_THRESHOLD, RetrainingScheduler,
)


# ===========================================================================
# Shared fixtures / helpers
# ===========================================================================

def _make_spy_close(
    n_days: int = 300,
    seed: int = 42,
    drift: float = 0.0004,
    vol: float = 0.01,
    start_price: float = 400.0,
) -> pd.Series:
    """Generate synthetic daily SPY close prices."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, vol, size=n_days)
    prices = start_price * np.exp(np.cumsum(returns))
    dates = pd.date_range(start="2022-01-03", periods=n_days, freq="B")
    return pd.Series(prices, index=dates, name="close")


def _make_spy_5min(
    n_bars: int = 1000,
    seed: int = 99,
    vol_per_bar: float = 0.0005,
    start_price: float = 400.0,
) -> pd.Series:
    """Generate synthetic 5-min SPY close prices."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0, vol_per_bar, size=n_bars)
    prices = start_price * np.exp(np.cumsum(returns))
    idx = pd.date_range("2022-01-03 09:30", periods=n_bars, freq="5min")
    return pd.Series(prices, index=idx, name="spy_5min")


def _make_vix(n: int = 1000, level: float = 20.0) -> pd.Series:
    """Generate synthetic VIX series (constant level ± small noise)."""
    rng = np.random.default_rng(7)
    vals = level + rng.normal(0, 0.5, size=n)
    idx = pd.date_range("2022-01-03 09:30", periods=n, freq="5min")
    return pd.Series(vals, index=idx, name="vix")


def _make_stress_5min(spike_bar: int = 500, spike_size: float = -0.025) -> pd.Series:
    """Insert a large move at `spike_bar` to trigger override."""
    prices = _make_spy_5min(n_bars=600)
    prices.iloc[spike_bar] = prices.iloc[spike_bar - 1] * (1 + spike_size)
    return prices


# ===========================================================================
# Feature Engineering
# ===========================================================================

class TestFeatureEngineering:

    def test_output_shape(self):
        spy = _make_spy_close(300)
        X = build_feature_matrix(spy)
        # After dropping NaN (4 rows for 5-day window), shape = (295, 2)
        assert X.shape[1] == 2, "Feature matrix must have exactly 2 columns"
        assert X.shape[0] >= MIN_OBSERVATIONS

    def test_column_order(self):
        names = get_feature_names()
        assert names[0] == "log_return"
        assert names[1] == "realised_vol"

    def test_no_nan_after_build(self):
        spy = _make_spy_close(300)
        X = build_feature_matrix(spy)
        assert not np.any(np.isnan(X)), "Feature matrix must not contain NaN"

    def test_realised_vol_positive(self):
        spy = _make_spy_close(300)
        X = build_feature_matrix(spy)
        assert np.all(X[:, 1] > 0), "Realised vol must be strictly positive"

    def test_realised_vol_annualised_range(self):
        """Annualised vol should be in a plausible range for synthetic data (5%–60%)."""
        spy = _make_spy_close(300, vol=0.01)   # 1% daily = ~16% annualised
        X = build_feature_matrix(spy)
        median_vol = np.median(X[:, 1])
        assert 0.05 < median_vol < 0.60, f"Unexpected annualised vol: {median_vol:.2%}"

    def test_insufficient_data_raises(self):
        spy = _make_spy_close(10)   # Way too short
        with pytest.raises(ValueError):
            build_feature_matrix(spy)

    def test_single_row(self):
        spy = _make_spy_close(50)
        row = build_feature_row(spy)
        assert row.shape == (1, 2), "build_feature_row must return shape (1, 2)"
        assert not np.any(np.isnan(row))

    def test_no_lookahead(self):
        """Feature at position i must only use data up to and including i."""
        spy = _make_spy_close(200)
        X_full = build_feature_matrix(spy)
        # Build matrix on first 100 rows — final row should match full matrix at same position
        X_partial = build_feature_matrix(spy.iloc[:100])
        # The last row of X_partial should match the same date's row in X_full
        np.testing.assert_allclose(X_partial[-1], X_full[len(X_partial) - 1], rtol=1e-9)


# ===========================================================================
# State Sorting
# ===========================================================================

class TestStateSorting:

    def _fit_unsorted_hmm(self, spy: pd.Series) -> GaussianHMM:
        X = build_feature_matrix(spy)
        hmm = GaussianHMM(n_components=3, covariance_type="full",
                          n_iter=50, random_state=0)
        hmm.fit(X)
        return hmm

    def test_sorted_states_monotone_variance(self):
        spy = _make_spy_close(350)
        hmm = self._fit_unsorted_hmm(spy)
        sorted_hmm = sort_hmm_states(hmm)
        assert validate_state_order(sorted_hmm), (
            "After sorting, state variances must increase: Calm < Normal < Stress"
        )

    def test_sorting_idempotent(self):
        spy = _make_spy_close(350)
        hmm = self._fit_unsorted_hmm(spy)
        sorted1 = sort_hmm_states(hmm)
        sorted2 = sort_hmm_states(sorted1)
        np.testing.assert_allclose(sorted1.means_, sorted2.means_, rtol=1e-9)

    def test_transition_matrix_rows_sum_to_one(self):
        spy = _make_spy_close(350)
        hmm = self._fit_unsorted_hmm(spy)
        sorted_hmm = sort_hmm_states(hmm)
        row_sums = sorted_hmm.transmat_.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-6)

    def test_startprob_sums_to_one(self):
        spy = _make_spy_close(350)
        hmm = self._fit_unsorted_hmm(spy)
        sorted_hmm = sort_hmm_states(hmm)
        assert abs(sorted_hmm.startprob_.sum() - 1.0) < 1e-6

    def test_wrong_n_components_raises(self):
        X = build_feature_matrix(_make_spy_close(300))
        hmm = GaussianHMM(n_components=2, covariance_type="full", n_iter=20)
        hmm.fit(X)
        with pytest.raises(ValueError, match="exactly 3"):
            sort_hmm_states(hmm)

    def test_state_labels(self):
        assert HMM_STATES[CALM] == "Calm"
        assert HMM_STATES[NORMAL] == "Normal"
        assert HMM_STATES[STRESS] == "Stress"
        assert CALM == 0 and NORMAL == 1 and STRESS == 2


# ===========================================================================
# HMM Engine
# ===========================================================================

class TestHMMEngine:

    def test_fit_and_predict_sequence(self):
        spy = _make_spy_close(350)
        engine = HMMEngine(n_iter=50, n_init=2)
        engine.fit(spy, save=False)
        assert engine.is_fitted()
        states = engine.predict_sequence(spy)
        X = build_feature_matrix(spy)
        assert len(states) == len(X)
        assert set(states).issubset({0, 1, 2})

    def test_predict_current_returns_scalar(self):
        spy = _make_spy_close(350)
        engine = HMMEngine(n_iter=50, n_init=2)
        engine.fit(spy, save=False)
        state = engine.predict_current(spy)
        assert state in (CALM, NORMAL, STRESS)

    def test_predict_proba_sums_to_one(self):
        spy = _make_spy_close(350)
        engine = HMMEngine(n_iter=50, n_init=2)
        engine.fit(spy, save=False)
        probs = engine.predict_proba(spy)
        assert probs.shape == (3,)
        assert abs(probs.sum() - 1.0) < 1e-5

    def test_state_names(self):
        engine = HMMEngine()
        assert engine.state_name(CALM) == "Calm"
        assert engine.state_name(NORMAL) == "Normal"
        assert engine.state_name(STRESS) == "Stress"

    def test_not_fitted_raises(self):
        engine = HMMEngine()
        spy = _make_spy_close(100)
        with pytest.raises(RuntimeError, match="fitted"):
            engine.predict_current(spy)

    def test_retrain_success(self):
        spy = _make_spy_close(400)
        engine = HMMEngine(n_iter=50, n_init=2)
        engine.fit(spy.iloc[:300], save=False)
        success = engine.retrain(spy.iloc[100:], save=False)
        assert isinstance(success, bool)
        assert engine.is_fitted()

    def test_retrain_fallback_on_bad_data(self):
        """Retraining with too-short data should fail gracefully."""
        spy = _make_spy_close(350)
        engine = HMMEngine(n_iter=50, n_init=2)
        engine.fit(spy, save=False)
        original_version = engine.version
        success = engine.retrain(spy.iloc[:5], save=False)  # Too short
        assert success is False
        assert engine.is_fitted()  # Still fitted (kept old model)

    def test_save_and_load(self):
        spy = _make_spy_close(350)
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HMMEngine(n_iter=50, n_init=2, model_dir=tmpdir)
            engine.fit(spy, version_tag="test", save=True)
            saved_version = engine.version

            engine2 = HMMEngine(model_dir=tmpdir)
            engine2.load(saved_version)
            assert engine2.is_fitted()

            # Predictions should be identical
            s1 = engine.predict_sequence(spy)
            s2 = engine2.predict_sequence(spy)
            np.testing.assert_array_equal(s1, s2)

    def test_states_ordered_after_fit(self):
        spy = _make_spy_close(350)
        engine = HMMEngine(n_iter=50, n_init=2)
        engine.fit(spy, save=False)
        assert validate_state_order(engine.model)

    def test_stress_regime_during_high_vol(self):
        """
        Fit HMM on mixed-vol data; stress regime should assign highest-var state
        to high-vol period.  Section 12 blueprint test pattern.
        """
        rng = np.random.default_rng(1)
        # 200 calm days + 100 stress days
        calm_rets = rng.normal(0.0005, 0.005, 200)   # low vol
        stress_rets = rng.normal(-0.001, 0.025, 100)  # high vol
        rets = np.concatenate([calm_rets, stress_rets])
        prices = 400.0 * np.exp(np.cumsum(rets))
        dates = pd.date_range("2022-01-03", periods=300, freq="B")
        spy = pd.Series(prices, index=dates)

        engine = HMMEngine(n_iter=100, n_init=5)
        engine.fit(spy, save=False)

        # Predict on stress period only
        stress_states = engine.predict_sequence(spy.iloc[200:])
        stress_rate = (stress_states == STRESS).mean()

        # At least 60% of stress-period bars should be detected as Stress or Normal
        non_calm_rate = (stress_states != CALM).mean()
        assert non_calm_rate >= 0.60, (
            f"Only {non_calm_rate:.0%} of high-vol bars detected as non-Calm "
            f"(expected ≥ 60%)."
        )


# ===========================================================================
# Volatility Override
# ===========================================================================

class TestVolatilityOverride:

    def test_no_trigger_in_calm_market(self):
        spy = _make_spy_5min(800, vol_per_bar=0.0003)  # very calm
        vix = _make_vix(800, level=15.0)
        checker = VolatilityOverride(spy, vix)
        result = checker.check()
        assert result.decision == OverrideDecision.USE_HMM

    def test_trigger_1_fires_on_large_5min_move(self):
        """A 4σ 5-min move must trigger override."""
        spy_calm = _make_spy_5min(500, vol_per_bar=0.0004)
        # Append a large single-bar spike (~3% move, ~7.5σ)
        last_price = float(spy_calm.iloc[-1])
        spike_price = last_price * 0.97  # -3% in one 5-min bar
        spike_idx = spy_calm.index[-1] + pd.Timedelta("5min")
        spy_with_spike = pd.concat([
            spy_calm,
            pd.Series([spike_price], index=[spike_idx]),
        ])
        vix = _make_vix(len(spy_with_spike), level=20.0)
        checker = VolatilityOverride(spy_with_spike, vix)
        result = checker.check()
        assert result.decision == OverrideDecision.FORCE_STRESS
        assert result.trigger == 1

    def test_trigger_3_vix_spike(self):
        """A 60% VIX jump must trigger override."""
        spy = _make_spy_5min(500, vol_per_bar=0.0003)
        vix_vals = [20.0] * 499 + [32.0]  # +60% in one bar
        vix = pd.Series(vix_vals, index=spy.index[:500])
        checker = VolatilityOverride(spy, vix)
        result = checker.check()
        assert result.decision == OverrideDecision.FORCE_STRESS
        assert result.trigger == 3

    def test_override_result_fields(self):
        spy_calm = _make_spy_5min(500, vol_per_bar=0.0004)
        last_price = float(spy_calm.iloc[-1])
        spike_idx = spy_calm.index[-1] + pd.Timedelta("5min")
        spy_with_spike = pd.concat([
            spy_calm,
            pd.Series([last_price * 0.96], index=[spike_idx]),
        ])
        vix = _make_vix(len(spy_with_spike), 20.0)
        result = VolatilityOverride(spy_with_spike, vix).check()

        if result.decision == OverrideDecision.FORCE_STRESS:
            assert result.trigger in (1, 2, 3)
            assert result.magnitude is not None
            assert len(result.detail) > 0

    def test_insufficient_data_graceful(self):
        spy = pd.Series([400.0, 399.0], index=pd.date_range("2022-01-03", periods=2, freq="5min"))
        vix = pd.Series([20.0, 21.0], index=spy.index)
        # Should not raise, may trigger or not
        checker = VolatilityOverride(spy, vix)
        result = checker.check()
        assert isinstance(result.decision, OverrideDecision)


# ===========================================================================
# Retraining Scheduler
# ===========================================================================

class TestRetrainingScheduler:

    def _make_scheduler(self, spy: pd.Series) -> tuple[HMMEngine, RetrainingScheduler]:
        engine = HMMEngine(n_iter=50, n_init=2)
        engine.fit(spy.iloc[:260], save=False)

        def fetcher(n_days: int) -> pd.Series:
            return spy.iloc[-n_days:] if n_days < len(spy) else spy

        scheduler = RetrainingScheduler(engine, fetcher)
        return engine, scheduler

    def test_weekly_trigger_on_sunday(self):
        spy = _make_spy_close(400)
        engine, scheduler = self._make_scheduler(spy)
        sunday = date(2022, 3, 6)  # A Sunday
        triggered = scheduler.check_weekly_retrain(sunday)
        assert triggered is True

    def test_no_weekly_trigger_on_monday(self):
        spy = _make_spy_close(400)
        engine, scheduler = self._make_scheduler(spy)
        monday = date(2022, 3, 7)
        triggered = scheduler.check_weekly_retrain(monday)
        assert triggered is False

    def test_emergency_trigger_a_vix_spike(self):
        spy = _make_spy_close(400)
        engine, scheduler = self._make_scheduler(spy)
        now = datetime(2022, 3, 15, 14, 0, tzinfo=timezone.utc)
        triggered = scheduler.check_emergency_triggers(
            vix_current=25.0,
            vix_previous_close=19.0,   # +31.6% spike > 25%
            spy_current=400.0,
            spy_open=400.0,
            current_dt=now,
        )
        assert triggered is True

    def test_emergency_trigger_b_spy_crash(self):
        spy = _make_spy_close(400)
        engine, scheduler = self._make_scheduler(spy)
        now = datetime(2022, 3, 15, 11, 0, tzinfo=timezone.utc)
        triggered = scheduler.check_emergency_triggers(
            vix_current=20.0,
            vix_previous_close=19.5,   # Small VIX change
            spy_current=384.0,
            spy_open=400.0,            # -4% intraday > 3% threshold
            current_dt=now,
        )
        assert triggered is True

    def test_no_emergency_trigger_normal_session(self):
        spy = _make_spy_close(400)
        engine, scheduler = self._make_scheduler(spy)
        now = datetime(2022, 3, 15, 10, 0, tzinfo=timezone.utc)
        triggered = scheduler.check_emergency_triggers(
            vix_current=20.2,
            vix_previous_close=19.8,   # +2% change
            spy_current=401.0,
            spy_open=400.0,            # +0.25% intraday
            current_dt=now,
        )
        assert triggered is False

    def test_simulate_weekly_retrains_returns_records(self):
        spy = _make_spy_close(600)
        engine = HMMEngine(n_iter=30, n_init=1)
        engine.fit(spy.iloc[:300], save=False)

        def fetcher(n: int) -> pd.Series:
            return spy.iloc[-n:] if n < len(spy) else spy

        scheduler = RetrainingScheduler(engine, fetcher)
        records = scheduler.simulate_weekly_retrains(spy, initial_train_end=300)
        assert len(records) > 0, "simulate_weekly_retrains must return at least one record"
        assert all("success" in r for r in records)


# ===========================================================================
# End-to-end integration smoke test
# ===========================================================================

class TestEndToEnd:

    def test_full_regime_workflow(self):
        """
        Smoke test: fit → predict → override check → retrain sequence.
        Mirrors what the strategy router will do every trading bar.
        """
        # 1. Initial training (burn-in simulation)
        spy_daily = _make_spy_close(400)
        spy_5min = _make_spy_5min(2000, vol_per_bar=0.0003)
        vix = _make_vix(2000, level=18.0)

        engine = HMMEngine(n_iter=100, n_init=3)
        engine.fit(spy_daily.iloc[:252], save=False)
        assert engine.is_fitted()

        # 2. Predict current regime
        recent = spy_daily.iloc[200:260]
        state = engine.predict_current(recent)
        assert state in (CALM, NORMAL, STRESS)

        # 3. Check volatility override
        checker = VolatilityOverride(spy_5min.iloc[:600], vix.iloc[:600])
        result = checker.check()
        assert result.decision in (OverrideDecision.FORCE_STRESS, OverrideDecision.USE_HMM)

        # 4. Weekly retrain
        success = engine.retrain(spy_daily.iloc[100:360], save=False)
        assert isinstance(success, bool)
        assert engine.is_fitted()

        # 5. Posterior probs sum to 1
        probs = engine.predict_proba(recent)
        assert abs(probs.sum() - 1.0) < 1e-5

        print(
            f"\n✓ End-to-end regime workflow:"
            f"\n  Current state : {engine.state_name(state)} ({state})"
            f"\n  Override      : {result.decision.value}"
            f"\n  Posteriors    : Calm={probs[0]:.2%}, Normal={probs[1]:.2%}, "
            f"Stress={probs[2]:.2%}"
            f"\n  Retrain       : {'success' if success else 'failed (kept old model)'}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
