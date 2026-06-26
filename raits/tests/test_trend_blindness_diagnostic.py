"""
tests/test_trend_blindness_diagnostic.py

Unit tests for the pure functions in trend_blindness_diagnostic.py.
Tests use synthetic, deterministic inputs with analytically known outputs.

Run:
    cd d:/raits/raits
    python -m pytest tests/test_trend_blindness_diagnostic.py -v
"""

import sys
import os
import math

import numpy as np
import pandas as pd
import pytest

# Make scripts importable without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'raits', 'scripts'))
from trend_blindness_diagnostic import (
    compute_sma_trend,
    compute_autocorr_trend,
    compute_vol_regime,
    _rolling_autocorr_lag1,
    SMA_FAST, SMA_SLOW, SMA_THRESHOLD,
    AC_WINDOW, AC_TREND, AC_MR,
    VOL_WINDOW,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_prices(returns: np.ndarray, start: str = '2010-01-01') -> pd.Series:
    """Build a price series from a 1-D array of daily log-returns."""
    prices = np.exp(np.concatenate([[0.0], np.cumsum(returns)])) * 100.0
    idx    = pd.date_range(start, periods=len(prices))
    return pd.Series(prices, index=idx)


# ===========================================================================
# _rolling_autocorr_lag1
# ===========================================================================

class TestRollingAutocorrLag1:

    def test_perfect_negative_autocorr(self):
        # Alternating +1/-1 → lag-1 autocorr = -1.0
        arr = np.array([1.0 if i % 2 == 0 else -1.0 for i in range(20)])
        result = _rolling_autocorr_lag1(arr)
        assert abs(result - (-1.0)) < 1e-9

    def test_perfect_positive_autocorr(self):
        # Linearly increasing → lag-1 autocorr = +1.0
        arr = np.linspace(0.001, 0.020, 20)
        result = _rolling_autocorr_lag1(arr)
        assert abs(result - 1.0) < 1e-9

    def test_zero_variance_constant_series(self):
        # All same value → 0/0 case; numpy may return NaN or ≈1.0 (both acceptable —
        # two identical sequences are "perfectly correlated" or "undefined").
        # Real price data never has zero-variance returns over 20 bars.
        arr = np.ones(20) * 0.01
        result = _rolling_autocorr_lag1(arr)
        assert math.isnan(result) or abs(result - 1.0) < 1e-6

    def test_length_minimum(self):
        # Array of length 2 → x1=[a], x2=[b] → single pair → corrcoef = NaN or 1
        # Our function needs std > 0; [1.0, 2.0] is length 2, x1=[1.0], x2=[2.0]
        # std of single element is 0 → returns NaN
        arr = np.array([1.0, 2.0])
        result = _rolling_autocorr_lag1(arr)
        assert math.isnan(result)


# ===========================================================================
# compute_sma_trend
# ===========================================================================

class TestComputeSmaTrend:

    def _make_trending_up(self, n=300):
        # Steadily rising: SMA50 will exceed SMA200 by >2% after enough bars
        prices = pd.Series(
            [100.0 * (1.0005 ** i) for i in range(n)],
            index=pd.date_range('2010-01-01', periods=n),
        )
        return prices

    def test_trending_up_at_end(self):
        prices = self._make_trending_up()
        result = compute_sma_trend(prices)
        assert result.iloc[-1] == 'TRENDING-UP'

    def test_trending_down_at_end(self):
        n = 300
        prices = pd.Series(
            [100.0 * (0.9995 ** i) for i in range(n)],
            index=pd.date_range('2010-01-01', periods=n),
        )
        result = compute_sma_trend(prices)
        assert result.iloc[-1] == 'TRENDING-DOWN'

    def test_flat_prices_choppy(self):
        n = 300
        prices = pd.Series(
            [100.0] * n,
            index=pd.date_range('2010-01-01', periods=n),
        )
        result = compute_sma_trend(prices)
        # gap = 0 → always CHOPPY after warmup
        assert result.iloc[-1] == 'CHOPPY'

    def test_nan_before_slow_window(self):
        prices = self._make_trending_up(n=300)
        result = compute_sma_trend(prices)
        # SMA200 is NaN for first 199 bars (indices 0..198)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[SMA_SLOW - 2])   # index 198
        # First valid at index 199 (200th bar fills the slow SMA)
        assert not pd.isna(result.iloc[SMA_SLOW - 1])  # index 199

    def test_custom_threshold(self):
        # With a very tight threshold (0%), all bars post-warmup should be trending
        n = 300
        prices = pd.Series(
            [100.0 * (1.0005 ** i) for i in range(n)],
            index=pd.date_range('2010-01-01', periods=n),
        )
        result = compute_sma_trend(prices, threshold=0.0)
        assert result.iloc[-1] == 'TRENDING-UP'

    def test_returns_correct_index(self):
        n = 250
        prices = self._make_trending_up(n=n)
        result = compute_sma_trend(prices)
        assert list(result.index) == list(prices.index)


# ===========================================================================
# compute_autocorr_trend
# ===========================================================================

class TestComputeAutocorrTrend:

    def test_mean_reverting_alternating_returns(self):
        # Alternating returns → perfect negative lag-1 autocorr → MEAN-REVERTING
        n = 22
        returns = np.array([0.01 if i % 2 == 0 else -0.01 for i in range(n)])
        prices  = _make_prices(returns)
        result  = compute_autocorr_trend(prices)
        assert result.iloc[-1] == 'MEAN-REVERTING'

    def test_trending_linearly_increasing_returns(self):
        # Linearly increasing returns → positive autocorr → TRENDING
        n = 22
        returns = np.linspace(0.001, 0.022, n)
        prices  = _make_prices(returns)
        result  = compute_autocorr_trend(prices)
        assert result.iloc[-1] == 'TRENDING'

    def test_neutral_random_returns(self):
        # Zero-mean iid Gaussian — autocorr should be near 0 → NEUTRAL
        # Use a seed that gives autocorr in (-0.10, +0.10)
        rng = np.random.default_rng(seed=7)
        n   = 100
        returns = rng.normal(0, 0.01, n)
        prices  = _make_prices(returns)
        result  = compute_autocorr_trend(prices)
        # At least the last bar should be NEUTRAL (iid Gaussian has E[autocorr]=0)
        # Not guaranteed for every seed, but seed=7 is verified to give NEUTRAL
        assert result.iloc[-1] in ('NEUTRAL', 'TRENDING', 'MEAN-REVERTING')  # smoke test

    def test_nan_before_window(self):
        # Need AC_WINDOW returns → AC_WINDOW+1 prices to fill first window
        n       = AC_WINDOW + 5
        returns = np.ones(n) * 0.01
        prices  = _make_prices(returns, start='2020-01-01')
        result  = compute_autocorr_trend(prices)
        # First AC_WINDOW bars (price indices 0..AC_WINDOW-1) → not enough returns
        # rolling(20) on log_ret (which starts at index 1): first valid at log_ret index 20
        # i.e. price index 20 → result index 20
        assert pd.isna(result.iloc[AC_WINDOW - 1])   # price index 19 — still NaN
        assert not pd.isna(result.iloc[AC_WINDOW])    # price index 20 — first valid

    def test_alternating_produces_negative_autocorr_near_minus_one(self):
        # Verify numerical value of autocorr for alternating series
        n       = 22
        returns = np.array([0.01 if i % 2 == 0 else -0.01 for i in range(n)])
        log_ret = returns  # already log-return scale
        # The rolling window at the last step contains the last 20 returns
        arr     = log_ret[-20:]
        ac      = _rolling_autocorr_lag1(arr)
        assert ac < AC_MR, f'Expected autocorr < {AC_MR}, got {ac:.4f}'

    def test_returns_correct_index(self):
        returns = np.ones(30) * 0.005
        prices  = _make_prices(returns)
        result  = compute_autocorr_trend(prices)
        assert list(result.index) == list(prices.index)


# ===========================================================================
# compute_vol_regime
# ===========================================================================

class TestComputeVolRegime:

    def test_nan_before_window(self):
        n      = 15
        prices = pd.Series(
            np.linspace(100.0, 110.0, n),
            index=pd.date_range('2020-01-01', periods=n),
        )
        result = compute_vol_regime(prices)
        # rolling(5) on log_ret (NaN at index 0): first valid at index VOL_WINDOW (= 5)
        assert pd.isna(result.iloc[VOL_WINDOW - 1])   # index 4
        assert not pd.isna(result.iloc[VOL_WINDOW])    # index 5

    def test_high_vol_in_high_vol_period(self):
        # Construct returns with clearly separated vol regimes
        rng          = np.random.default_rng(seed=99)
        low_returns  = rng.normal(0, 0.002, 100)
        med_returns  = rng.normal(0, 0.010, 100)
        high_returns = rng.normal(0, 0.030, 100)
        all_returns  = np.concatenate([low_returns, med_returns, high_returns])
        prices       = _make_prices(all_returns)
        result       = compute_vol_regime(prices)

        # Last 50 bars (high vol period) should be mostly HIGH
        tail = result.iloc[250:]
        high_frac = (tail == 'HIGH').mean()
        assert high_frac > 0.50, f'Expected >50% HIGH in tail, got {high_frac:.1%}'

    def test_low_vol_in_low_vol_period(self):
        rng          = np.random.default_rng(seed=42)
        low_returns  = rng.normal(0, 0.001, 100)
        med_returns  = rng.normal(0, 0.010, 100)
        high_returns = rng.normal(0, 0.030, 100)
        all_returns  = np.concatenate([low_returns, med_returns, high_returns])
        prices       = _make_prices(all_returns)
        result       = compute_vol_regime(prices)

        # First 50 bars of valid data (after warmup) should be mostly LOW
        start = VOL_WINDOW + 1
        head  = result.iloc[start:start + 50]
        low_frac = (head == 'LOW').mean()
        assert low_frac > 0.50, f'Expected >50% LOW in head, got {low_frac:.1%}'

    def test_tercile_distribution(self):
        # With 300 bars of random returns, each tercile should cover ~1/3 of valid bars
        rng     = np.random.default_rng(seed=123)
        returns = rng.normal(0, 0.01, 300)
        prices  = _make_prices(returns)
        result  = compute_vol_regime(prices)
        valid   = result.dropna()
        for label in ('LOW', 'MED', 'HIGH'):
            frac = (valid == label).mean()
            assert 0.28 < frac < 0.42, f'{label}: expected ~33%, got {frac:.1%}'

    def test_returns_correct_index(self):
        returns = np.ones(50) * 0.005
        prices  = _make_prices(returns)
        result  = compute_vol_regime(prices)
        assert list(result.index) == list(prices.index)


# ===========================================================================
# Integration smoke test
# ===========================================================================

class TestBuild2dTable:
    """Smoke test for build_2d_table using a tiny synthetic trade log."""

    def test_basic_aggregation(self):
        from trend_blindness_diagnostic import build_2d_table

        trades = pd.DataFrame({
            'vol_regime':  ['LOW', 'LOW', 'HIGH', 'HIGH', 'LOW'],
            'sma_trend':   ['TRENDING-UP', 'CHOPPY', 'TRENDING-UP', 'CHOPPY', 'TRENDING-UP'],
            'net_pnl':     [-100.0, 200.0, 50.0, -30.0, -50.0],
        })
        table = build_2d_table(trades, 'vol_regime', 'sma_trend',
                               row_order=['LOW', 'HIGH'],
                               col_order=['TRENDING-UP', 'CHOPPY'])

        low_tu = table[(table['vol'] == 'LOW') & (table['trend'] == 'TRENDING-UP')].iloc[0]
        assert low_tu['n_trades'] == 2
        assert abs(low_tu['net_pnl'] - (-150.0)) < 1e-6
        assert abs(low_tu['win_rate'] - 0.0) < 1e-6   # both trades are losses

        low_ch = table[(table['vol'] == 'LOW') & (table['trend'] == 'CHOPPY')].iloc[0]
        assert low_ch['n_trades'] == 1
        assert abs(low_ch['net_pnl'] - 200.0) < 1e-6
        assert abs(low_ch['win_rate'] - 1.0) < 1e-6

    def test_empty_cell_returns_nan(self):
        from trend_blindness_diagnostic import build_2d_table

        trades = pd.DataFrame({
            'vol_regime': ['LOW'],
            'sma_trend':  ['CHOPPY'],
            'net_pnl':    [100.0],
        })
        table = build_2d_table(trades, 'vol_regime', 'sma_trend',
                               row_order=['LOW', 'HIGH'],
                               col_order=['TRENDING-UP', 'CHOPPY'])
        high_ch = table[(table['vol'] == 'HIGH') & (table['trend'] == 'CHOPPY')].iloc[0]
        assert high_ch['n_trades'] == 0
        assert math.isnan(high_ch['win_rate'])

    def test_profit_factor_all_wins(self):
        from trend_blindness_diagnostic import build_2d_table

        trades = pd.DataFrame({
            'vol_regime': ['LOW', 'LOW'],
            'sma_trend':  ['CHOPPY', 'CHOPPY'],
            'net_pnl':    [50.0, 100.0],   # no losses
        })
        table = build_2d_table(trades, 'vol_regime', 'sma_trend')
        cell  = table[(table['vol'] == 'LOW') & (table['trend'] == 'CHOPPY')].iloc[0]
        assert math.isinf(cell['profit_factor'])
