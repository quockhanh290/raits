"""
tests/test_hmm_state_diagnostic.py

Unit tests for the pure functions in hmm_state_diagnostic.py.
Uses synthetic, deterministic inputs with analytically known outputs.

Run:
    cd d:/raits/raits
    python -m pytest tests/test_hmm_state_diagnostic.py -v
"""

import sys
import os
import math

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "raits", "scripts"))
from hmm_state_diagnostic import (
    count_state_days,
    is_bull_day,
    apply_crisis_override,
    compute_20d_returns,
    compute_sma,
    VOL_OVERRIDE_THRESHOLD,
    SMA_BULL_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dates(n, start="2020-01-01"):
    return pd.date_range(start, periods=n, freq="B")


# ===========================================================================
# count_state_days
# ===========================================================================

class TestCountStateDays:

    def test_basic_counts(self):
        s = pd.Series([0, 1, 1, 2, 0, 1], index=_dates(6))
        result = count_state_days(s)
        assert result == {0: 2, 1: 3, 2: 1}

    def test_single_state(self):
        s = pd.Series([1, 1, 1], index=_dates(3))
        result = count_state_days(s)
        assert result == {1: 3}

    def test_all_four_states(self):
        s = pd.Series([0, 1, 2, 3, 0, 3], index=_dates(6))
        result = count_state_days(s)
        assert result == {0: 2, 1: 1, 2: 1, 3: 2}

    def test_sorted_by_state(self):
        s = pd.Series([2, 0, 1], index=_dates(3))
        result = count_state_days(s)
        assert list(result.keys()) == [0, 1, 2]

    def test_empty_series(self):
        s = pd.Series([], dtype=int, index=pd.DatetimeIndex([]))
        result = count_state_days(s)
        assert result == {}

    def test_nan_dropped(self):
        s = pd.Series([0, np.nan, 1, 1], index=_dates(4))
        result = count_state_days(s)
        assert result == {0: 1, 1: 2}

    def test_total_matches_length_minus_nan(self):
        s = pd.Series([0, 1, 2, 0, np.nan], index=_dates(5))
        result = count_state_days(s)
        assert sum(result.values()) == 4

    def test_large_series(self):
        # Reproducible: 1000 states uniformly distributed over 0-3
        rng = np.random.default_rng(seed=42)
        vals = rng.integers(0, 4, size=1000)
        s = pd.Series(vals, index=_dates(1000))
        result = count_state_days(s)
        assert set(result.keys()) == {0, 1, 2, 3}
        assert sum(result.values()) == 1000


# ===========================================================================
# is_bull_day
# ===========================================================================

class TestIsBullDay:

    def test_basic_bull(self):
        # gap = (110-100)/100 = 0.10 > 0.02 -> True
        fast = pd.Series([110.0], index=_dates(1))
        slow = pd.Series([100.0], index=_dates(1))
        result = is_bull_day(fast, slow)
        assert bool(result.iloc[0]) is True

    def test_basic_not_bull_flat(self):
        fast = pd.Series([100.0], index=_dates(1))
        slow = pd.Series([100.0], index=_dates(1))
        result = is_bull_day(fast, slow)
        assert bool(result.iloc[0]) is False

    def test_basic_bear(self):
        # gap = (90-100)/100 = -0.10 < 0.02 -> False
        fast = pd.Series([90.0], index=_dates(1))
        slow = pd.Series([100.0], index=_dates(1))
        result = is_bull_day(fast, slow)
        assert bool(result.iloc[0]) is False

    def test_exactly_at_threshold_not_bull(self):
        # gap = exactly 2% -- boundary: NOT bull (strict >)
        fast = pd.Series([102.0], index=_dates(1))
        slow = pd.Series([100.0], index=_dates(1))
        result = is_bull_day(fast, slow)
        assert bool(result.iloc[0]) is False

    def test_just_above_threshold_is_bull(self):
        # gap = 2.01% -> True
        fast = pd.Series([102.01], index=_dates(1))
        slow = pd.Series([100.0], index=_dates(1))
        result = is_bull_day(fast, slow)
        assert bool(result.iloc[0]) is True

    def test_mixed_series(self):
        fast = pd.Series([110.0, 100.0, 90.0, 103.0], index=_dates(4))
        slow = pd.Series([100.0, 100.0, 100.0, 100.0], index=_dates(4))
        result = is_bull_day(fast, slow)
        assert list(result) == [True, False, False, True]

    def test_custom_threshold(self):
        # With threshold=0.05, gap=0.03 should NOT be bull
        fast = pd.Series([103.0], index=_dates(1))
        slow = pd.Series([100.0], index=_dates(1))
        result = is_bull_day(fast, slow, threshold=0.05)
        assert bool(result.iloc[0]) is False

    def test_custom_threshold_above(self):
        # With threshold=0.05, gap=0.06 should be bull
        fast = pd.Series([106.0], index=_dates(1))
        slow = pd.Series([100.0], index=_dates(1))
        result = is_bull_day(fast, slow, threshold=0.05)
        assert bool(result.iloc[0]) is True

    def test_preserves_index(self):
        idx  = pd.date_range("2020-03-01", periods=3)
        fast = pd.Series([110.0, 105.0, 95.0], index=idx)
        slow = pd.Series([100.0, 100.0, 100.0], index=idx)
        result = is_bull_day(fast, slow)
        assert list(result.index) == list(idx)


# ===========================================================================
# apply_crisis_override
# ===========================================================================

class TestApplyCrisisOverride:

    def _make_low_vol_prices(self, n=30, daily_ret=0.001):
        """Prices with low daily return -> low rvol."""
        prices = pd.Series(
            [100.0 * (1 + daily_ret) ** i for i in range(n)],
            index=_dates(n),
        )
        return prices

    def _make_high_vol_prices(self, n=30):
        """Prices with alternating +5%/-5% returns -> high rvol."""
        rets  = np.array([0.05 if i % 2 == 0 else -0.05 for i in range(n)])
        close = np.cumprod(1 + rets) * 100.0
        return pd.Series(close, index=_dates(n))

    def test_no_override_low_vol(self):
        prices = self._make_low_vol_prices(n=30)
        states = pd.Series([1] * 25, index=prices.index[5:])  # 25 Normal days
        result = apply_crisis_override(states, prices)
        # Low vol -> no override -> all still Normal (1)
        assert (result == 1).all(), f"Expected all Normal, got: {result.value_counts().to_dict()}"

    def test_override_fires_high_vol(self):
        """Alternating +-5% returns produce rvol >> 50% -> Crisis override."""
        prices = self._make_high_vol_prices(n=30)
        idx    = prices.index[5:]   # after warmup
        states = pd.Series([1] * len(idx), index=idx)  # start as Normal
        result = apply_crisis_override(states, prices, threshold=0.50)
        # At least some days should become Crisis (3)
        assert (result == 3).any(), "Expected at least some Crisis days with high vol"

    def test_override_uses_correct_threshold(self):
        """Vol just below threshold -> no override; just above -> override fires."""
        prices = self._make_high_vol_prices(n=30)
        idx    = prices.index[5:]
        states = pd.Series([2] * len(idx), index=idx)  # Stress

        # With an impossibly high threshold (200%), nothing triggers
        result_no = apply_crisis_override(states, prices, threshold=2.00)
        assert (result_no == 2).all()

        # With a very low threshold (1%), everything triggers
        result_all = apply_crisis_override(states, prices, threshold=0.01)
        assert (result_all == 3).all()

    def test_crisis_label_is_3(self):
        """Override must use integer 3 for Crisis."""
        prices = self._make_high_vol_prices(n=30)
        idx    = prices.index[5:]
        states = pd.Series([0] * len(idx), index=idx)
        result = apply_crisis_override(states, prices, threshold=0.01)
        unique = set(result.unique())
        assert 3 in unique, "Crisis override must produce state 3"

    def test_non_override_days_unchanged(self):
        """States on non-crisis days must remain unchanged."""
        n      = 40
        prices = self._make_low_vol_prices(n)
        idx    = prices.index[5:]
        states = pd.Series(range(len(idx)), index=idx)  # unique values per day
        result = apply_crisis_override(states, prices, threshold=0.99)
        # No day should be overridden (vol is tiny)
        pd.testing.assert_series_equal(result, states)


# ===========================================================================
# compute_20d_returns
# ===========================================================================

class TestCompute20dReturns:

    def test_known_return(self):
        # Price doubles in 20 days -> log(2) ~ 0.693
        prices = pd.Series(
            [100.0] * 20 + [200.0],
            index=_dates(21),
        )
        result = compute_20d_returns(prices)
        expected = math.log(200.0 / 100.0)
        assert abs(float(result.iloc[-1]) - expected) < 1e-9

    def test_nan_before_20_bars(self):
        prices = pd.Series([100.0 * (1.01 ** i) for i in range(25)], index=_dates(25))
        result = compute_20d_returns(prices)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[19])
        assert not pd.isna(result.iloc[20])

    def test_flat_price_zero_return(self):
        prices = pd.Series([100.0] * 25, index=_dates(25))
        result = compute_20d_returns(prices)
        assert abs(float(result.iloc[-1])) < 1e-12


# ===========================================================================
# compute_sma
# ===========================================================================

class TestComputeSma:

    def test_sma_known_value(self):
        prices = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=_dates(5))
        result = compute_sma(prices, window=3)
        # Third bar: mean(1,2,3) = 2.0
        assert abs(float(result.iloc[2]) - 2.0) < 1e-9
        # Fourth bar: mean(2,3,4) = 3.0
        assert abs(float(result.iloc[3]) - 3.0) < 1e-9

    def test_sma_nan_before_window(self):
        prices = pd.Series([1.0] * 10, index=_dates(10))
        result = compute_sma(prices, window=5)
        assert pd.isna(result.iloc[3])    # before 5 bars
        assert not pd.isna(result.iloc[4])  # at 5th bar

    def test_sma_flat_price(self):
        prices = pd.Series([42.0] * 20, index=_dates(20))
        result = compute_sma(prices, window=10)
        valid = result.dropna()
        assert (abs(valid - 42.0) < 1e-9).all()

    def test_sma_preserves_index(self):
        idx    = pd.date_range("2020-06-01", periods=10)
        prices = pd.Series(range(10, 20), index=idx, dtype=float)
        result = compute_sma(prices, window=3)
        assert list(result.index) == list(idx)


# ===========================================================================
# Integration: count_state_days + is_bull_day together
# ===========================================================================

class TestBullDayStateIntegration:

    def test_bull_days_counted_correctly(self):
        """
        Synthetic: 10 days all bull (fast >> slow) -> all True.
        Manually assign states and verify bull counts per state.
        """
        idx  = _dates(10)
        fast = pd.Series([120.0] * 10, index=idx)
        slow = pd.Series([100.0] * 10, index=idx)
        bull = is_bull_day(fast, slow)
        assert bull.all()

    def test_non_bull_days_all_false(self):
        idx  = _dates(5)
        fast = pd.Series([100.0] * 5, index=idx)
        slow = pd.Series([105.0] * 5, index=idx)
        bull = is_bull_day(fast, slow)
        assert not bull.any()

    def test_mixed_bull_and_non_bull(self):
        idx  = _dates(4)
        fast = pd.Series([110.0, 100.0, 115.0, 99.0], index=idx)
        slow = pd.Series([100.0, 100.0, 100.0, 100.0], index=idx)
        bull = is_bull_day(fast, slow)
        # gaps: +10%, 0%, +15%, -1%
        assert list(bull) == [True, False, True, False]

    def test_bull_days_per_state(self):
        """Simulate assigning states and counting bull days per state."""
        idx    = _dates(6)
        states = pd.Series([0, 1, 2, 0, 1, 1], index=idx)
        fast   = pd.Series([110, 100, 115, 108, 99, 120], index=idx, dtype=float)
        slow   = pd.Series([100] * 6, index=idx, dtype=float)
        bull   = is_bull_day(fast, slow)
        # Bull: [T, F, T, T, F, T] (gaps: 10%, 0%, 15%, 8%, -1%, 20%)
        # State 0 days: idx 0,3 -> bull=[T,T] -> 2 bull
        # State 1 days: idx 1,4,5 -> bull=[F,F,T] -> 1 bull
        # State 2 days: idx 2 -> bull=[T] -> 1 bull
        state_counts = count_state_days(states)
        bull_per_state = {}
        for s in [0, 1, 2]:
            bull_per_state[s] = int(bull[states == s].sum())
        assert bull_per_state[0] == 2
        assert bull_per_state[1] == 1
        assert bull_per_state[2] == 1
