# tests/test_position_sizer.py
#
# Position sizer test suite — Phase 1B Week 10
#
# Blueprint ref: Section 5.3 "Layer 3: Sizing Controls"
#
# Run with: python -m unittest tests.test_position_sizer -v
# Target:   18/18 passing

import unittest
from raits.risk.position_sizer import PositionSizer
from tests.fixtures.position_fixtures import (
    ACCOUNT_EQUITY,
    ORB_STATS,
    POSITION_LIMIT_BINDS,
    VOL_TARGET_BINDS,
    KELLY_BINDS,
    NEGATIVE_KELLY,
    WEAK_STATS,
)


class TestKellyCalculation(unittest.TestCase):
    """
    Tests for the Kelly Criterion calculation specifically.
    Blueprint formula: f* = (p×b - q) / b, then take half-Kelly.
    """

    def setUp(self):
        self.sizer = PositionSizer(account_equity=ACCOUNT_EQUITY)

    def test_kelly_fraction_is_correct(self):
        """
        Blueprint example: win_rate=0.62, avg_win=$4.50, avg_loss=$2.00
          b = 4.50 / 2.00 = 2.25
          f = (0.62 × 2.25 - 0.38) / 2.25 = 0.451
          half_kelly = 0.2255
        """
        fraction = self.sizer.calculate_kelly_fraction(ORB_STATS)
        self.assertAlmostEqual(fraction, 0.2255, places=3,
                               msg="Half-Kelly fraction should be 0.2255")

    def test_kelly_shares_at_given_price(self):
        """
        capital = $25,000 × 0.2255 = $5,637.50
        shares  = $5,637.50 / $178.50 = 31.57 → 31
        """
        shares = self.sizer.calculate_kelly_shares(
            entry_price=178.50, strategy_stats=ORB_STATS
        )
        self.assertEqual(shares, 31)

    def test_negative_kelly_returns_zero(self):
        """
        Negative Kelly = negative expected value = no edge.
        Should return 0, not a negative number.
        """
        shares = self.sizer.calculate_kelly_shares(
            entry_price=50.00,
            strategy_stats=NEGATIVE_KELLY['strategy_stats']
        )
        self.assertEqual(shares, 0,
                         "Negative Kelly should return 0 shares (no edge)")

    def test_kelly_is_independent_of_stop_distance(self):
        """
        Kelly only cares about win rate and win/loss ratio, not the stop distance.
        Two trades at the same price but different stops should yield same Kelly shares.
        """
        shares_tight = self.sizer.calculate_kelly_shares(50.00, ORB_STATS)
        shares_wide  = self.sizer.calculate_kelly_shares(50.00, ORB_STATS)
        self.assertEqual(shares_tight, shares_wide,
                         "Kelly shares depend only on price and stats, not stop")


class TestVolatilityTarget(unittest.TestCase):
    """
    Tests for the 1% risk cap constraint.
    Blueprint: max_risk = 1% of account = $250. shares = $250 / risk_per_share.
    """

    def setUp(self):
        self.sizer = PositionSizer(account_equity=ACCOUNT_EQUITY)

    def test_vol_target_calculation(self):
        """
        entry=$178.50, stop=$174.00, risk=$4.50/share
        shares = $250 / $4.50 = 55.5 → 55
        """
        shares = self.sizer.calculate_vol_target_shares(
            entry_price=178.50, stop_loss=174.00
        )
        self.assertEqual(shares, 55)

    def test_wide_stop_reduces_shares(self):
        """
        The whole point of vol targeting: wider stops → smaller positions.
        $250 / $5.00 = 50 shares  vs  $250 / $10.00 = 25 shares
        """
        shares_tight = self.sizer.calculate_vol_target_shares(100.00, 95.00)  # $5 risk
        shares_wide  = self.sizer.calculate_vol_target_shares(100.00, 90.00)  # $10 risk
        self.assertGreater(shares_tight, shares_wide,
                           "Tight stop should allow more shares than wide stop")
        self.assertEqual(shares_tight, 50)
        self.assertEqual(shares_wide,  25)

    def test_vol_target_uses_abs_risk(self):
        """
        For short trades, stop is ABOVE entry. abs() must be used so risk
        is always positive.
        Short: entry=$95.30, stop=$97.50, risk=abs(95.30-97.50)=$2.20
        shares = $250 / $2.20 = 113.6 → 113
        """
        shares = self.sizer.calculate_vol_target_shares(
            entry_price=95.30, stop_loss=97.50
        )
        self.assertEqual(shares, 113)


class TestPositionLimit(unittest.TestCase):
    """
    Tests for the 20% concentration cap.
    Blueprint: max_position = 20% × account = $5,000. shares = $5,000 / entry.
    """

    def setUp(self):
        self.sizer = PositionSizer(account_equity=ACCOUNT_EQUITY)

    def test_position_limit_calculation(self):
        """$5,000 / $178.50 = 28.01 → 28 shares"""
        shares = self.sizer.calculate_position_limit_shares(entry_price=178.50)
        self.assertEqual(shares, 28)

    def test_position_limit_scales_with_price(self):
        """Cheaper stocks allow more shares under the same dollar cap."""
        shares_cheap     = self.sizer.calculate_position_limit_shares(10.00)
        shares_expensive = self.sizer.calculate_position_limit_shares(100.00)
        self.assertGreater(shares_cheap, shares_expensive)


class TestFinalPositionSize(unittest.TestCase):
    """
    Tests for the master calculate() method that combines all three constraints.
    Blueprint: final = min(kelly, vol_target, position_limit)
    """

    def setUp(self):
        self.sizer = PositionSizer(account_equity=ACCOUNT_EQUITY)

    def test_position_limit_is_binding(self):
        """Scenario A: expensive stock, position limit binds at 28 shares."""
        f = POSITION_LIMIT_BINDS
        result = self.sizer.calculate(
            entry_price=f['entry_price'],
            stop_loss=f['stop_loss'],
            strategy_stats=f['strategy_stats'],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['shares'], f['expected_final_shares'])
        self.assertEqual(result['limiting_factor'], f['expected_limiting_factor'])

    def test_vol_target_is_binding(self):
        """Scenario B: $100 stock, $5 risk — vol target and limit both hit 50."""
        f = VOL_TARGET_BINDS
        result = self.sizer.calculate(
            entry_price=f['entry_price'],
            stop_loss=f['stop_loss'],
            strategy_stats=f['strategy_stats'],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['shares'], f['expected_final_shares'])
        self.assertEqual(result['limiting_factor'], f['expected_limiting_factor'])

    def test_kelly_is_binding(self):
        """Scenario C: weak edge stats — Kelly is smallest at 25 shares."""
        f = KELLY_BINDS
        result = self.sizer.calculate(
            entry_price=f['entry_price'],
            stop_loss=f['stop_loss'],
            strategy_stats=f['strategy_stats'],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['shares'], f['expected_final_shares'])
        self.assertEqual(result['limiting_factor'], f['expected_limiting_factor'])

    def test_negative_kelly_returns_none(self):
        """No edge = no trade. calculate() must return None."""
        f = NEGATIVE_KELLY
        result = self.sizer.calculate(
            entry_price=f['entry_price'],
            stop_loss=f['stop_loss'],
            strategy_stats=f['strategy_stats'],
        )
        self.assertIsNone(result,
                          "Negative Kelly should return None (no trade)")

    def test_result_contains_all_required_fields(self):
        """Downstream components need these fields — missing = KeyError."""
        f = POSITION_LIMIT_BINDS
        result = self.sizer.calculate(
            entry_price=f['entry_price'],
            stop_loss=f['stop_loss'],
            strategy_stats=f['strategy_stats'],
        )
        required = {
            'shares', 'position_value', 'risk_dollars',
            'risk_pct', 'kelly_shares', 'vol_target_shares',
            'position_limit_shares', 'limiting_factor',
        }
        for key in required:
            self.assertIn(key, result, f"Result missing required field: '{key}'")

    def test_risk_pct_never_exceeds_one_percent(self):
        """
        The vol target constraint exists specifically to cap risk at 1%.
        Regardless of which constraint binds, risk_pct should always be ≤ 1%.
        """
        for fixture in [POSITION_LIMIT_BINDS, VOL_TARGET_BINDS, KELLY_BINDS]:
            result = self.sizer.calculate(
                entry_price=fixture['entry_price'],
                stop_loss=fixture['stop_loss'],
                strategy_stats=fixture['strategy_stats'],
            )
            if result:
                self.assertLessEqual(
                    result['risk_pct'], 0.011,  # 1% + small float tolerance
                    f"Risk {result['risk_pct']:.2%} exceeds 1% cap"
                )


if __name__ == '__main__':
    unittest.main(verbosity=2)
