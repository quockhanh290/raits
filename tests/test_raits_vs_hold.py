"""
TDD tests for raits_vs_hold.py
Run: pytest tests/test_raits_vs_hold.py -v
"""
import sys
import os
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "raits", "raits", "scripts"))
from raits_vs_hold import (
    _classify_single_day,
    classify_regimes,
    build_raits_equity_curve,
    build_hold_equity_curve,
    build_overlay_equity_curve,
    sortino,
    verify_bull_day_return_equality,
    # Two-convention curve builders
    build_fixed_raits_curve,
    build_fixed_spy_curve,
    build_fixed_overlay_curve,
    build_compound_raits_curve,
    build_compound_spy_curve,
    build_compound_overlay_curve,
)


# ---------------------------------------------------------------------------
# _classify_single_day — tests the scalar classification rule
# ---------------------------------------------------------------------------

class TestClassifySingleDay:
    def test_bull_trending(self):
        # SMA50 > SMA200 and close > SMA50 → BULL
        assert _classify_single_day(close=110.0, sma50=105.0, sma200=100.0) == "BULL"

    def test_bull_boundary_exact_sma50_equals_sma200(self):
        # SMA50 == SMA200: not strictly greater → NOT BULL, close>sma50 doesn't matter
        # SMA50 not < SMA200 either → CHOPPY
        assert _classify_single_day(close=106.0, sma50=100.0, sma200=100.0) == "CHOPPY"

    def test_bear_sma50_below_sma200(self):
        # SMA50 < SMA200 → BEAR regardless of close position
        assert _classify_single_day(close=95.0, sma50=100.0, sma200=105.0) == "BEAR"

    def test_bear_close_above_sma50_still_bear(self):
        # SMA50 < SMA200 even if close > SMA50 → still BEAR
        assert _classify_single_day(close=103.0, sma50=100.0, sma200=105.0) == "BEAR"

    def test_choppy_sma50_above_sma200_close_below_sma50(self):
        # SMA50 > SMA200 but close <= SMA50 → CHOPPY
        assert _classify_single_day(close=98.0, sma50=100.0, sma200=98.0) == "CHOPPY"

    def test_choppy_close_equals_sma50(self):
        # close == sma50 (not strictly above) → CHOPPY
        assert _classify_single_day(close=100.0, sma50=100.0, sma200=98.0) == "CHOPPY"


# ---------------------------------------------------------------------------
# classify_regimes — integration test over a constructed price series
# ---------------------------------------------------------------------------

class TestClassifyRegimes:
    def _make_spy(self, closes):
        """Build a minimal SPY DataFrame with given close prices."""
        dates = pd.bdate_range("2020-01-02", periods=len(closes))
        return pd.DataFrame({"close": closes}, index=dates)

    def test_all_nan_sma_returns_choppy_for_early_rows(self):
        # First 199 rows have no SMA200 — should be classified CHOPPY (NaN → neutral)
        spy = self._make_spy([100.0] * 220)
        regimes = classify_regimes(spy)
        assert regimes.iloc[0] == "CHOPPY"
        assert regimes.iloc[198] == "CHOPPY"

    def test_rising_series_eventually_bull(self):
        # Steadily rising prices: after enough bars, SMA50 > SMA200 and close > SMA50 → BULL
        closes = list(range(100, 350))  # 250 days, price 100→349 (always rising)
        spy = self._make_spy(closes)
        regimes = classify_regimes(spy)
        assert regimes.iloc[-1] == "BULL"

    def test_falling_series_eventually_bear(self):
        # Steadily falling prices: SMA50 < SMA200 eventually → BEAR
        closes = list(range(350, 100, -1))  # 250 days, price 350→101 (always falling)
        spy = self._make_spy(closes)
        regimes = classify_regimes(spy)
        assert regimes.iloc[-1] == "BEAR"

    def test_returns_series_with_same_index(self):
        spy = self._make_spy([100.0] * 220)
        regimes = classify_regimes(spy)
        assert isinstance(regimes, pd.Series)
        assert len(regimes) == len(spy)
        assert regimes.index.equals(spy.index)

    def test_values_only_from_valid_set(self):
        closes = list(range(100, 350))
        spy = self._make_spy(closes)
        regimes = classify_regimes(spy)
        assert set(regimes.unique()).issubset({"BULL", "BEAR", "CHOPPY"})


# ---------------------------------------------------------------------------
# build_raits_equity_curve
# ---------------------------------------------------------------------------

class TestBuildRaitsEquityCurve:
    def _dates(self, start="2020-01-02", end="2020-01-31"):
        return pd.bdate_range(start, end)

    def test_no_trades_flat_at_start_capital(self):
        dates = self._dates()
        trades = pd.DataFrame(columns=["exit_time", "net_pnl"])
        curve = build_raits_equity_curve(trades, start_capital=50_000, date_range=dates)
        assert len(curve) == len(dates)
        assert (curve == 50_000).all()

    def test_single_trade_adds_pnl_on_exit_date(self):
        dates = self._dates("2020-01-02", "2020-01-10")
        trades = pd.DataFrame({
            "exit_time": [pd.Timestamp("2020-01-07")],
            "net_pnl": [1_000.0],
        })
        curve = build_raits_equity_curve(trades, start_capital=50_000, date_range=dates)
        # Days before exit: unchanged
        pre = curve[curve.index < pd.Timestamp("2020-01-07")]
        assert (pre == 50_000).all()
        # Exit day onward: +1000
        post = curve[curve.index >= pd.Timestamp("2020-01-07")]
        assert (post == 51_000).all()

    def test_two_trades_accumulate(self):
        dates = self._dates("2020-01-02", "2020-01-15")
        trades = pd.DataFrame({
            "exit_time": [pd.Timestamp("2020-01-06"), pd.Timestamp("2020-01-10")],
            "net_pnl": [500.0, -200.0],
        })
        curve = build_raits_equity_curve(trades, start_capital=50_000, date_range=dates)
        assert curve[pd.Timestamp("2020-01-06")] == 50_500.0
        assert curve[pd.Timestamp("2020-01-10")] == 50_300.0
        assert curve[pd.Timestamp("2020-01-15")] == 50_300.0

    def test_same_day_multiple_trades(self):
        dates = self._dates("2020-01-02", "2020-01-10")
        trades = pd.DataFrame({
            "exit_time": [pd.Timestamp("2020-01-07"), pd.Timestamp("2020-01-07")],
            "net_pnl": [300.0, 200.0],
        })
        curve = build_raits_equity_curve(trades, start_capital=50_000, date_range=dates)
        assert curve[pd.Timestamp("2020-01-07")] == 50_500.0

    def test_returns_series_indexed_by_date_range(self):
        dates = self._dates()
        trades = pd.DataFrame(columns=["exit_time", "net_pnl"])
        curve = build_raits_equity_curve(trades, start_capital=50_000, date_range=dates)
        assert isinstance(curve, pd.Series)
        assert curve.index.equals(dates)


# ---------------------------------------------------------------------------
# build_hold_equity_curve
# ---------------------------------------------------------------------------

class TestBuildHoldEquityCurve:
    def _make_prices(self, closes, start="2020-01-02"):
        dates = pd.bdate_range(start, periods=len(closes))
        return pd.DataFrame({"close": closes}, index=dates)

    def test_flat_prices_flat_equity(self):
        prices = self._make_prices([100.0] * 20)
        curve = build_hold_equity_curve(prices, start_capital=50_000)
        assert abs(curve.iloc[0] - 50_000) < 1e-6
        assert abs(curve.iloc[-1] - 50_000) < 1e-6

    def test_price_doubles_equity_doubles(self):
        n = 20
        closes = np.linspace(100.0, 200.0, n)
        prices = self._make_prices(closes)
        curve = build_hold_equity_curve(prices, start_capital=50_000)
        assert abs(curve.iloc[0] - 50_000) < 1e-6
        assert abs(curve.iloc[-1] - 100_000) < 1e-6

    def test_price_halves_equity_halves(self):
        n = 20
        closes = np.linspace(200.0, 100.0, n)
        prices = self._make_prices(closes)
        curve = build_hold_equity_curve(prices, start_capital=50_000)
        assert abs(curve.iloc[0] - 50_000) < 1e-6
        assert abs(curve.iloc[-1] - 25_000) < 1e-6

    def test_returns_series_same_index(self):
        prices = self._make_prices([100.0] * 10)
        curve = build_hold_equity_curve(prices, start_capital=50_000)
        assert isinstance(curve, pd.Series)
        assert curve.index.equals(prices.index)


# ---------------------------------------------------------------------------
# build_overlay_equity_curve
# ---------------------------------------------------------------------------

class TestBuildOverlayEquityCurve:
    def _dates(self, start="2020-01-02", periods=10):
        return pd.bdate_range(start, periods=periods)

    def _flat_spy(self, n=10, price=100.0, start="2020-01-02"):
        dates = pd.bdate_range(start, periods=n)
        return pd.DataFrame({"close": [price] * n}, index=dates)

    def test_all_choppy_matches_raits_curve(self):
        # When no day is BULL, overlay == RAITS (SPY return doesn't matter)
        dates = self._dates(periods=10)
        regimes = pd.Series("CHOPPY", index=dates)
        spy = self._flat_spy(n=10)
        trades = pd.DataFrame({
            "exit_time": [dates[4]],
            "net_pnl": [1_000.0],
        })
        overlay = build_overlay_equity_curve(trades, spy, regimes, 50_000, dates)
        raits = build_raits_equity_curve(trades, 50_000, dates)
        pd.testing.assert_series_equal(overlay, raits)

    def test_all_bull_flat_spy_equity_unchanged(self):
        # All BULL, flat SPY (0% return) → equity stays at start_capital (no RAITS trades applied)
        dates = self._dates(periods=10)
        regimes = pd.Series("BULL", index=dates)
        spy = self._flat_spy(n=10, price=100.0)
        trades = pd.DataFrame({
            "exit_time": [dates[5]],
            "net_pnl": [2_000.0],  # should be ignored: BULL day
        })
        overlay = build_overlay_equity_curve(trades, spy, regimes, 50_000, dates)
        # Flat SPY: every day equity stays at 50_000
        assert (overlay == 50_000).all()

    def test_all_bull_rising_spy_equity_tracks_spy(self):
        # All BULL, SPY rises 10% → equity rises 10%
        dates = self._dates(periods=10)
        regimes = pd.Series("BULL", index=dates)
        n = 10
        closes = np.linspace(100.0, 110.0, n)
        spy = pd.DataFrame({"close": closes}, index=dates)
        trades = pd.DataFrame(columns=["exit_time", "net_pnl"])
        overlay = build_overlay_equity_curve(trades, spy, regimes, 50_000, dates)
        expected_last = 50_000 * (110.0 / 100.0)
        assert abs(overlay.iloc[-1] - expected_last) < 1e-6

    def test_bull_then_bear_transition(self):
        # First 5 days BULL (flat SPY), then 5 days BEAR (one trade +1000)
        dates = self._dates(periods=10)
        regimes = pd.Series(
            ["BULL"] * 5 + ["BEAR"] * 5, index=dates
        )
        spy = self._flat_spy(n=10, price=100.0)
        trade_date = dates[7]  # day 8, in BEAR segment
        trades = pd.DataFrame({
            "exit_time": [trade_date],
            "net_pnl": [1_000.0],
        })
        overlay = build_overlay_equity_curve(trades, spy, regimes, 50_000, dates)
        # Days 1-5 (BULL, flat SPY): still 50_000
        assert (overlay.iloc[:5] == 50_000).all()
        # Days 6-7 (BEAR, no trade yet): still 50_000
        assert overlay.iloc[5] == 50_000
        assert overlay.iloc[6] == 50_000
        # Day 8 onward: +1000
        assert overlay.iloc[7] == 51_000
        assert overlay.iloc[9] == 51_000


# ---------------------------------------------------------------------------
# TestSortino — new metric
# ---------------------------------------------------------------------------

class TestSortino:
    def test_positive_for_rising_curve_with_some_down_days(self):
        # Net positive curve with a few down days: Sortino > 0
        dates = pd.bdate_range("2020-01-02", periods=10)
        values = [50_000, 50_500, 50_300, 50_800, 50_600, 51_000,
                  50_900, 51_400, 51_200, 51_800]
        curve = pd.Series(values, index=dates, dtype=float)
        result = sortino(curve)
        assert result > 0.0

    def test_negative_for_declining_curve(self):
        # Steadily falling curve: Sortino < 0
        dates = pd.bdate_range("2020-01-02", periods=10)
        values = [50_000 - i * 200 for i in range(10)]
        curve = pd.Series(values, index=dates, dtype=float)
        result = sortino(curve)
        assert result < 0.0

    def test_flat_curve_returns_zero_or_nan(self):
        # Flat curve: no return at all; Sortino = 0 or NaN
        dates = pd.bdate_range("2020-01-02", periods=20)
        curve = pd.Series(50_000.0, index=dates)
        result = sortino(curve)
        assert result == 0.0 or np.isnan(result)

    def test_only_up_days_returns_inf_or_large(self):
        # Every day is positive — no downside — Sortino undefined (inf or nan)
        dates = pd.bdate_range("2020-01-02", periods=10)
        values = [50_000 + i * 200 for i in range(10)]
        curve = pd.Series(values, index=dates, dtype=float)
        result = sortino(curve)
        assert np.isinf(result) or np.isnan(result)

    def test_higher_than_sharpe_when_only_downside_is_small(self):
        # Sortino ignores upside volatility, so for a curve with large up moves
        # and small down moves, Sortino > Sharpe (from same module)
        from raits_vs_hold import _sharpe
        dates = pd.bdate_range("2020-01-02", periods=50)
        np.random.seed(42)
        # Skewed returns: mostly small gains, rare large gains, tiny losses
        returns = np.where(np.arange(50) % 10 == 0, 0.05, 0.005)
        returns[3] = -0.003
        returns[17] = -0.002
        base = 50_000.0
        values = [base]
        for r in returns[1:]:
            values.append(values[-1] * (1 + r))
        curve = pd.Series(values, index=dates)
        s = sortino(curve)
        sh = _sharpe(curve)
        assert s > sh  # Sortino rewards asymmetric upside


# ---------------------------------------------------------------------------
# TestVerifyBullDayReturnEquality — new consistency check
# ---------------------------------------------------------------------------

class TestVerifyBullDayReturnEquality:
    def _rising_spy(self, n=10, start_price=100.0):
        dates = pd.bdate_range("2020-01-02", periods=n)
        closes = np.linspace(start_price, start_price * 1.10, n)
        return pd.DataFrame({"close": closes}, index=dates), dates

    def test_returns_true_for_correctly_built_overlay(self):
        # curve_c built by build_overlay_equity_curve on all-BULL regime must
        # have same daily returns as curve_b on every BULL day
        spy, dates = self._rising_spy()
        regimes = pd.Series("BULL", index=dates)
        trades = pd.DataFrame(columns=["exit_time", "net_pnl"])
        curve_b = build_hold_equity_curve(spy, 50_000)
        curve_c = build_overlay_equity_curve(trades, spy, regimes, 50_000, dates)
        assert verify_bull_day_return_equality(curve_c, curve_b, regimes)

    def test_returns_true_for_mixed_regime_on_bull_days(self):
        # Mixed regime: first 5 BULL, next 5 BEAR. On BULL days C == B.
        spy, dates = self._rising_spy()
        regimes = pd.Series(["BULL"] * 5 + ["BEAR"] * 5, index=dates)
        trades = pd.DataFrame({
            "exit_time": [dates[7]],
            "net_pnl": [1_000.0],
        })
        curve_b = build_hold_equity_curve(spy, 50_000)
        curve_c = build_overlay_equity_curve(trades, spy, regimes, 50_000, dates)
        assert verify_bull_day_return_equality(curve_c, curve_b, regimes)

    def test_returns_false_when_curve_c_deviates_on_bull_day(self):
        # Manually construct a fake curve_c that adds $500 every day (wrong for BULL)
        # vs curve_b that uses SPY % return — they will differ on BULL days
        spy, dates = self._rising_spy()
        regimes = pd.Series("BULL", index=dates)
        # curve_b: price-ratio hold
        curve_b = build_hold_equity_curve(spy, 50_000)
        # fake curve_c: linear $500/day growth (not SPY %)
        curve_c = pd.Series([50_000 + i * 500 for i in range(len(dates))],
                             index=dates, dtype=float)
        assert not verify_bull_day_return_equality(curve_c, curve_b, regimes)

    def test_empty_bull_days_returns_true(self):
        # No BULL days at all: vacuously true
        spy, dates = self._rising_spy()
        regimes = pd.Series("BEAR", index=dates)
        curve_b = build_hold_equity_curve(spy, 50_000)
        curve_c = build_hold_equity_curve(spy, 50_000)
        assert verify_bull_day_return_equality(curve_c, curve_b, regimes)


# ---------------------------------------------------------------------------
# TestCompoundingEquivalence — documents the mathematical identity
# ---------------------------------------------------------------------------

class TestCompoundingEquivalence:
    def test_raits_compounding_equals_simple_sum(self):
        # Key mathematical identity: equity[t-1] * (1 + pnl/equity[t-1]) = equity[t-1] + pnl
        # So Curve A compounded == Curve A simple-sum. Verify with known numbers.
        dates = pd.bdate_range("2020-01-02", periods=5)
        pnl_seq = [100.0, -50.0, 200.0, 0.0, 150.0]
        trades = pd.DataFrame({
            "exit_time": list(dates),
            "net_pnl": pnl_seq,
        })
        curve = build_raits_equity_curve(trades, 50_000, dates)
        simple_sum_final = 50_000 + sum(pnl_seq)  # = 50_400
        assert abs(curve.iloc[-1] - simple_sum_final) < 1e-6, (
            f"Compounded {curve.iloc[-1]} != simple-sum {simple_sum_final}"
        )

    def test_raits_daily_return_formula_consistent_with_equity_increment(self):
        # For a single-trade day: daily_return = pnl / equity[t-1],
        # then equity[t] = equity[t-1] * (1 + pnl/equity[t-1]) = equity[t-1] + pnl
        # Verify the specific arithmetic for equity = 75000, pnl = 750 (1%)
        equity_prev = 75_000.0
        pnl = 750.0
        return_rate = pnl / equity_prev            # = 0.01 exactly
        equity_compounded = equity_prev * (1 + return_rate)
        equity_additive = equity_prev + pnl
        assert abs(equity_compounded - equity_additive) < 1e-9


# ===========================================================================
# Tests for the two genuinely-distinct conventions (the real fix)
# ===========================================================================

# ---------------------------------------------------------------------------
# TestFixedMode — fixed-dollar, no compounding for any curve
# ---------------------------------------------------------------------------

class TestFixedMode:
    """
    Fixed mode: SPY P&L = spy_ret * start_capital (non-compounding).
    RAITS P&L = raw net_pnl. All curves are sums of fixed-dollar amounts.
    """

    def _make_spy(self, closes, start="2020-01-02"):
        dates = pd.bdate_range(start, periods=len(closes))
        return pd.DataFrame({"close": closes}, index=dates), dates

    def test_fixed_spy_up_then_down_returns_to_start(self):
        # +10% then -10%: fixed sum = 0 net. Compound would give -1%.
        spy, dates = self._make_spy([100.0, 110.0, 99.0])
        start = 50_000.0
        curve = build_fixed_spy_curve(spy, start, dates)
        # day 0: no prior price -> P&L = 0 -> equity = 50000
        assert abs(curve.iloc[0] - 50_000) < 1e-6
        # day 1: +10% * $50k = +$5000 -> equity = 55000
        assert abs(curve.iloc[1] - 55_000) < 1e-6
        # day 2: -10% * $50k = -$5000 -> equity = 50000
        assert abs(curve.iloc[2] - 50_000) < 1e-6

    def test_fixed_spy_differs_from_compound_spy_for_volatile_prices(self):
        # +10% / -10% path: fixed ends at $50k, compound ends at $49,500
        spy, dates = self._make_spy([100.0, 110.0, 99.0])
        start = 50_000.0
        fixed = build_fixed_spy_curve(spy, start, dates)
        compound = build_compound_spy_curve(spy, start, dates)
        assert abs(fixed.iloc[-1] - 50_000) < 1e-6
        assert abs(compound.iloc[-1] - 49_500) < 1e-6
        assert abs(fixed.iloc[-1] - compound.iloc[-1]) > 400  # genuinely different

    def test_fixed_raits_equals_simple_cumsum(self):
        # Fixed RAITS is just cumsum — same as the existing build_raits_equity_curve
        dates = pd.bdate_range("2020-01-02", periods=5)
        pnl_seq = [500.0, -200.0, 300.0, 0.0, 100.0]
        trades = pd.DataFrame({"exit_time": list(dates), "net_pnl": pnl_seq})
        curve = build_fixed_raits_curve(trades, 50_000, dates)
        expected_final = 50_000 + sum(pnl_seq)
        assert abs(curve.iloc[-1] - expected_final) < 1e-6

    def test_fixed_overlay_all_bull_equals_fixed_spy(self):
        # All BULL, no RAITS trades: overlay must exactly equal fixed SPY curve
        spy, dates = self._make_spy([100.0, 105.0, 110.0, 108.0, 112.0])
        regimes = pd.Series("BULL", index=dates)
        trades = pd.DataFrame(columns=["exit_time", "net_pnl"])
        start = 50_000.0
        overlay = build_fixed_overlay_curve(trades, spy, regimes, start, dates)
        fixed_spy = build_fixed_spy_curve(spy, start, dates)
        for i in range(len(dates)):
            assert abs(overlay.iloc[i] - fixed_spy.iloc[i]) < 1e-6

    def test_fixed_overlay_all_choppy_equals_fixed_raits(self):
        # No BULL days: overlay must equal fixed RAITS curve
        spy, dates = self._make_spy([100.0] * 5)
        regimes = pd.Series("CHOPPY", index=dates)
        pnl_seq = [300.0, -100.0, 500.0, 0.0, 200.0]
        trades = pd.DataFrame({"exit_time": list(dates), "net_pnl": pnl_seq})
        start = 50_000.0
        overlay = build_fixed_overlay_curve(trades, spy, regimes, start, dates)
        fixed_raits = build_fixed_raits_curve(trades, start, dates)
        for i in range(len(dates)):
            assert abs(overlay.iloc[i] - fixed_raits.iloc[i]) < 1e-6

    def test_fixed_overlay_bull_day_contribution_matches_fixed_spy_daily_pnl(self):
        # On each BULL day, the equity increment in overlay == spy_ret * start_capital
        spy, dates = self._make_spy([100.0, 110.0, 121.0, 115.0, 120.0])
        # Days 0-2 BULL, days 3-4 BEAR
        regimes = pd.Series(["BULL", "BULL", "BULL", "BEAR", "BEAR"], index=dates)
        trades = pd.DataFrame({"exit_time": [dates[3]], "net_pnl": [1_000.0]})
        start = 50_000.0
        overlay = build_fixed_overlay_curve(trades, spy, regimes, start, dates)
        # Day 0 (BULL): no prior price -> +0 -> equity = 50000
        assert abs(overlay.iloc[0] - 50_000) < 1e-6
        # Day 1 (BULL): +10% * $50k = +$5000 -> equity = 55000
        assert abs(overlay.iloc[1] - 55_000) < 1e-6
        # Day 2 (BULL): +10% * $50k = +$5000 -> equity = 60000
        assert abs(overlay.iloc[2] - 60_000) < 1e-6
        # Day 3 (BEAR): RAITS P&L +$1000 -> equity = 61000
        assert abs(overlay.iloc[3] - 61_000) < 1e-6
        # Day 4 (BEAR): no trade -> equity = 61000
        assert abs(overlay.iloc[4] - 61_000) < 1e-6


# ---------------------------------------------------------------------------
# TestCompoundMode — everything compounds on one running balance
# ---------------------------------------------------------------------------

class TestCompoundMode:
    """
    Compound mode: RAITS daily_return = pnl / start_capital (proportional re-sizing).
    SPY daily_return = spy_ret. All curves: equity *= (1 + daily_return).
    KEY PROPERTY: compound RAITS != simple-sum when returns are non-zero.
    """

    def _make_spy(self, closes, start="2020-01-02"):
        dates = pd.bdate_range(start, periods=len(closes))
        return pd.DataFrame({"close": closes}, index=dates), dates

    def test_compound_raits_with_constant_pct_gain_matches_formula(self):
        # 5% gain every day for 10 days: equity should match start * 1.05^10
        dates = pd.bdate_range("2020-01-02", periods=10)
        start = 50_000.0
        pnl_per_day = start * 0.05  # $2,500 = exactly 5% of start
        trades = pd.DataFrame({
            "exit_time": list(dates),
            "net_pnl": [pnl_per_day] * 10,
        })
        curve = build_compound_raits_curve(trades, start, dates)
        expected = start * (1.05 ** 10)  # ≈ $81,444.73
        assert abs(curve.iloc[-1] - expected) < 1e-6

    def test_compound_raits_differs_from_simple_sum_when_account_grows(self):
        # Same setup: compound final != simple-sum final (THIS PROVES THE FIX IS REAL)
        dates = pd.bdate_range("2020-01-02", periods=10)
        start = 50_000.0
        pnl_per_day = start * 0.05  # 5% each day
        trades = pd.DataFrame({
            "exit_time": list(dates),
            "net_pnl": [pnl_per_day] * 10,
        })
        curve = build_compound_raits_curve(trades, start, dates)
        simple_sum_final = start + 10 * pnl_per_day  # $75,000
        compound_final = start * (1.05 ** 10)         # ≈ $81,444.73
        # Must match compound formula
        assert abs(curve.iloc[-1] - compound_final) < 1e-6
        # MUST differ from simple-sum by a large, detectable margin
        assert abs(curve.iloc[-1] - simple_sum_final) > 500, (
            f"Compound ({curve.iloc[-1]:.2f}) should differ from "
            f"simple-sum ({simple_sum_final:.2f}) by >$500"
        )
        assert curve.iloc[-1] > simple_sum_final  # compound > simple for pure gains

    def test_compound_raits_no_trades_stays_flat(self):
        dates = pd.bdate_range("2020-01-02", periods=5)
        trades = pd.DataFrame(columns=["exit_time", "net_pnl"])
        curve = build_compound_raits_curve(trades, 50_000, dates)
        assert (curve == 50_000).all()

    def test_compound_spy_matches_price_ratio(self):
        # SPY doubles: equity should double
        spy, dates = self._make_spy([100.0, 110.0, 120.0, 150.0, 200.0])
        curve = build_compound_spy_curve(spy, 50_000, dates)
        assert abs(curve.iloc[0] - 50_000) < 1e-6
        assert abs(curve.iloc[-1] - 100_000) < 1e-6  # 100->200 = 2x

    def test_compound_overlay_all_bull_equals_compound_spy(self):
        # All BULL, no RAITS trades: overlay == compound SPY exactly
        spy, dates = self._make_spy([100.0, 110.0, 121.0, 115.0, 120.0])
        regimes = pd.Series("BULL", index=dates)
        trades = pd.DataFrame(columns=["exit_time", "net_pnl"])
        start = 50_000.0
        overlay = build_compound_overlay_curve(trades, spy, regimes, start, dates)
        spy_curve = build_compound_spy_curve(spy, start, dates)
        for i in range(len(dates)):
            assert abs(overlay.iloc[i] - spy_curve.iloc[i]) < 1e-9

    def test_compound_overlay_non_bull_uses_pnl_over_start_capital(self):
        # CHOPPY days: equity *= (1 + pnl/start_capital), NOT equity += pnl
        # 10%/day gain for 5 days: compound gives start * 1.1^5 = $80,525.5
        spy, dates = self._make_spy([100.0] * 5)
        regimes = pd.Series("CHOPPY", index=dates)
        start = 50_000.0
        pnl = start * 0.10  # $5,000 = 10% each day
        trades = pd.DataFrame({"exit_time": list(dates), "net_pnl": [pnl] * 5})
        overlay = build_compound_overlay_curve(trades, spy, regimes, start, dates)
        expected_compound = start * (1.10 ** 5)  # ≈ $80,525.5
        expected_simple   = start + 5 * pnl      # = $75,000
        assert abs(overlay.iloc[-1] - expected_compound) < 1e-6
        assert abs(overlay.iloc[-1] - expected_simple) > 500  # genuinely different

    def test_compound_overlay_mixed_regime_bull_days_match_compound_spy_return(self):
        # On BULL days, compound overlay's daily % return must equal SPY's daily % return
        spy, dates = self._make_spy([100.0, 110.0, 121.0, 121.0, 130.0])
        # Days 0, 1, 2 BULL; days 3, 4 CHOPPY
        regimes = pd.Series(["BULL", "BULL", "BULL", "CHOPPY", "CHOPPY"], index=dates)
        start = 50_000.0
        trades = pd.DataFrame({"exit_time": [dates[3]], "net_pnl": [1_000.0]})
        overlay = build_compound_overlay_curve(trades, spy, regimes, start, dates)
        spy_curve = build_compound_spy_curve(spy, start, dates)
        # On BULL days (0-2), both curves must have same daily return
        for i in range(1, 3):  # skip i=0 (no prior day to compute return)
            ret_overlay = overlay.iloc[i] / overlay.iloc[i - 1] - 1
            ret_spy = spy_curve.iloc[i] / spy_curve.iloc[i - 1] - 1
            assert abs(ret_overlay - ret_spy) < 1e-9, (
                f"BULL day {i}: overlay return {ret_overlay:.6f} != spy return {ret_spy:.6f}"
            )


# ---------------------------------------------------------------------------
# TestCrossConventionAssertion1 — compound A != simple-sum (proves fix is real)
# ---------------------------------------------------------------------------

class TestCrossConventionAssertion1:
    """Assert that compound_raits_final != simple_sum_final when account grows.
    This is the core proof that compound mode genuinely differs from fixed mode.
    """

    def test_assertion1_fails_for_flat_account(self):
        # If all P&L = 0, compound == simple-sum (both = start_capital). Edge case.
        dates = pd.bdate_range("2020-01-02", periods=5)
        trades = pd.DataFrame({
            "exit_time": list(dates),
            "net_pnl": [0.0] * 5,
        })
        curve = build_compound_raits_curve(trades, 50_000, dates)
        assert (curve == 50_000).all()  # no growth -> equal

    def test_assertion1_passes_for_growing_account(self):
        # Large steady gain: compound > simple-sum by a significant, detectable margin.
        # 2% daily gain for 20 days: compound = start*1.02^20 = $74,297; simple = $70,000
        dates = pd.bdate_range("2020-01-02", periods=20)
        start = 50_000.0
        pnl = start * 0.02  # $1,000 = 2% of start each day
        trades = pd.DataFrame({
            "exit_time": list(dates),
            "net_pnl": [pnl] * 20,
        })
        curve = build_compound_raits_curve(trades, start, dates)
        simple_sum = start + 20 * pnl          # $70,000
        compound_expected = start * (1.02 ** 20)  # ≈ $74,297
        assert abs(curve.iloc[-1] - compound_expected) < 1e-6
        assert abs(curve.iloc[-1] - simple_sum) > 1_000  # large, detectable difference
        assert curve.iloc[-1] > simple_sum
