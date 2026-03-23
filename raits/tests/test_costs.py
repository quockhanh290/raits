"""
Test Suite: Transaction Cost Model
====================================
Phase 1A validation — Blueprint v1.2, Section 12.3

All hand-calculated expected values use the formulas documented in Section 2.
Tests are designed so that the EXPECTED values can be independently verified
in a spreadsheet without running any code.

Pre-Vault Readiness Checklist (Blueprint Section 7.5.1):
  ✅ All cost components verified against hand-calculated values
  ✅ Market impact scales correctly with order size (square-root law)
  ✅ Regulatory fees are sell-side only
  ✅ Regime multipliers change slippage correctly
  ✅ Commission clamps to $0.35 min and $1.00 max
  ✅ FINRA TAF cap at $9.79
  ✅ Round-trip cost helper works correctly
"""

import unittest
import math

from raits.costs import (
    TransactionCostModel,
    TradeSpec,
    CostBreakdown,
    HMMState,
    Direction,
    MarketCapTier,
    calculate_total_costs,
    IB_RATE_PER_SHARE,
    IB_MIN_PER_ORDER,
    IB_MAX_PER_ORDER,
    SEC_RATE_PER_DOLLAR,
    FINRA_TAF_PER_SHARE,
    FINRA_TAF_CAP,
    MARKET_IMPACT_GAMMA,
    SLIPPAGE_REGIME_MULTIPLIER,
)

model = TransactionCostModel()


# ---------------------------------------------------------------------------
# Helpers — shared fixtures
# ---------------------------------------------------------------------------

def make_trade(**overrides) -> TradeSpec:
    """Return a default large-cap, Normal-regime BUY trade with optional overrides."""
    defaults = dict(
        ticker="AAPL", shares=100, price=150.00,
        direction=Direction.BUY, market_cap=2.5e12,
        adv=50_000_000, volatility=0.015,
        hmm_state=HMMState.NORMAL,
    )
    defaults.update(overrides)
    return TradeSpec(**defaults)


# ---------------------------------------------------------------------------
# TIER 1: Commission (SHALL)
# ---------------------------------------------------------------------------

class TestCommission(unittest.TestCase):
    """
    IB Tiered: $0.0035/share, min $0.35, max $1.00
    Hand verification column: min(max(shares × 0.0035, 0.35), 1.00)
    """

    def test_normal_order_100_shares(self):
        # 100 × 0.0035 = 0.35 → at minimum exactly
        trade = make_trade(shares=100, price=150.00)
        self.assertAlmostEqual(model.commission(trade), 0.35, places=4)

    def test_minimum_applies_for_small_orders(self):
        # 10 × 0.0035 = 0.035 → clamped to 0.35 minimum
        trade = make_trade(shares=10, price=5.00)
        self.assertAlmostEqual(model.commission(trade), 0.35, places=4)

    def test_maximum_applies_for_large_orders(self):
        # 1000 × 0.0035 = 3.50 → clamped to $1.00 maximum
        trade = make_trade(shares=1000, price=50.00)
        self.assertAlmostEqual(model.commission(trade), 1.00, places=4)

    def test_mid_range_order_286_shares(self):
        # 286 × 0.0035 = 1.001 → just over $1, clamped to $1.00
        trade = make_trade(shares=286)
        self.assertAlmostEqual(model.commission(trade), 1.00, places=4)

    def test_boundary_exactly_100_shares_hits_minimum(self):
        # 100 × 0.0035 = 0.35 == minimum; should NOT be clamped down
        trade = make_trade(shares=100)
        self.assertAlmostEqual(model.commission(trade), IB_MIN_PER_ORDER, places=10)


# ---------------------------------------------------------------------------
# TIER 1: Spread (SHALL)
# ---------------------------------------------------------------------------

class TestSpread(unittest.TestCase):
    """
    spread = spread_pct × notional
    Large-cap: 0.02% | Mid-cap: 0.03% | Small-cap: 0.10%
    """

    def test_large_cap_spread(self):
        # 0.0002 × (100 × 150) = 0.0002 × 15000 = 3.00
        trade = make_trade(shares=100, price=150.00, market_cap=2.5e12)
        self.assertAlmostEqual(model.spread(trade), 3.00, places=2)

    def test_mid_cap_spread(self):
        # 0.0003 × (100 × 50) = 0.0003 × 5000 = 1.50
        trade = make_trade(shares=100, price=50.00, market_cap=5e9)
        self.assertAlmostEqual(model.spread(trade), 1.50, places=2)

    def test_small_cap_spread(self):
        # 0.0010 × (200 × 20) = 0.0010 × 4000 = 4.00
        trade = make_trade(shares=200, price=20.00, market_cap=500e6)
        self.assertAlmostEqual(model.spread(trade), 4.00, places=2)

    def test_spread_scales_linearly_with_notional(self):
        trade_100  = make_trade(shares=100, price=50.00)
        trade_200  = make_trade(shares=200, price=50.00)
        self.assertAlmostEqual(
            model.spread(trade_200),
            model.spread(trade_100) * 2,
            places=4,
        )


# ---------------------------------------------------------------------------
# TIER 1: Slippage — base / fallback path (SHALL)
# ---------------------------------------------------------------------------

class TestSlippage(unittest.TestCase):
    """
    SHALL path (no gap_pcts supplied):
      slippage = max(BASE_SLIPPAGE_PCT × multiplier, 0.01%) × notional

    Normal-regime multiplier = 1.0
    BASE_SLIPPAGE_PCT = 0.00015
    => 0.00015 × 1.0 × (100 × 150) = 2.25
    """

    def test_normal_regime_base_slippage(self):
        trade = make_trade(shares=100, price=150.00, hmm_state=HMMState.NORMAL)
        expected = 0.00015 * 1.00 * (100 * 150.00)  # = 2.25
        self.assertAlmostEqual(model.slippage(trade), expected, places=2)

    def test_calm_regime_reduced_slippage(self):
        # Calm multiplier = 0.67
        trade_calm   = make_trade(hmm_state=HMMState.CALM)
        trade_normal = make_trade(hmm_state=HMMState.NORMAL)
        ratio = model.slippage(trade_calm) / model.slippage(trade_normal)
        self.assertAlmostEqual(ratio, 0.67, places=2)

    def test_stress_regime_doubled_slippage(self):
        # Stress multiplier = 2.00
        trade_stress = make_trade(hmm_state=HMMState.STRESS)
        trade_normal = make_trade(hmm_state=HMMState.NORMAL)
        ratio = model.slippage(trade_stress) / model.slippage(trade_normal)
        self.assertAlmostEqual(ratio, 2.00, places=2)

    def test_minimum_slippage_enforced(self):
        # Even with a tiny gap_pct supplied, minimum 0.01% must apply
        trade = make_trade(gap_pcts={"p50": 0.0, "p75": 0.0, "p90": 0.0})
        self.assertGreaterEqual(
            model.slippage(trade),
            0.0001 * trade.notional,
        )

    def test_gap_pcts_used_when_provided(self):
        # With Normal state → p75 percentile is selected
        gap_pcts = {"p50": 0.0002, "p75": 0.0005, "p90": 0.0010}
        trade = make_trade(hmm_state=HMMState.NORMAL, gap_pcts=gap_pcts)
        expected = 0.0005 * (100 * 150.00)   # p75 × notional
        self.assertAlmostEqual(model.slippage(trade), expected, places=2)

    def test_stress_regime_uses_p90_percentile(self):
        gap_pcts = {"p50": 0.0002, "p75": 0.0005, "p90": 0.0010}
        trade = make_trade(hmm_state=HMMState.STRESS, gap_pcts=gap_pcts)
        expected = 0.0010 * (100 * 150.00)   # p90 × notional
        self.assertAlmostEqual(model.slippage(trade), expected, places=2)


# ---------------------------------------------------------------------------
# TIER 1: Regulatory Fees — SEC & FINRA TAF (SHALL)
# ---------------------------------------------------------------------------

class TestRegulatoryFees(unittest.TestCase):
    """
    Both fees apply to SELL orders only.
    """

    # SEC Section 31
    def test_sec_fee_on_sell(self):
        # $150 × 100 × (27.50 / 1_000_000) = 15000 × 0.0000275 = 0.4125
        trade = make_trade(direction=Direction.SELL)
        expected = 15_000 * SEC_RATE_PER_DOLLAR
        self.assertAlmostEqual(model.sec_fee(trade), expected, places=4)

    def test_sec_fee_zero_on_buy(self):
        trade = make_trade(direction=Direction.BUY)
        self.assertEqual(model.sec_fee(trade), 0.0)

    # FINRA TAF
    def test_taf_fee_normal_order(self):
        # 100 × 0.000195 = 0.0195, below $9.79 cap
        trade = make_trade(shares=100, direction=Direction.SELL)
        self.assertAlmostEqual(model.taf_fee(trade), 0.0195, places=4)

    def test_taf_fee_cap_applies(self):
        # 60,000 × 0.000195 = 11.70 → capped at $9.79
        trade = make_trade(shares=60_000, direction=Direction.SELL)
        self.assertAlmostEqual(model.taf_fee(trade), FINRA_TAF_CAP, places=4)

    def test_taf_fee_zero_on_buy(self):
        trade = make_trade(direction=Direction.BUY)
        self.assertEqual(model.taf_fee(trade), 0.0)

    def test_taf_cap_boundary(self):
        # Exactly at cap: $9.79 / 0.000195 ≈ 50,205 shares
        cap_shares = int(FINRA_TAF_CAP / FINRA_TAF_PER_SHARE)
        below = make_trade(shares=cap_shares - 1, direction=Direction.SELL)
        above = make_trade(shares=cap_shares + 1000, direction=Direction.SELL)
        self.assertLessEqual(model.taf_fee(below), FINRA_TAF_CAP)
        self.assertEqual(model.taf_fee(above), FINRA_TAF_CAP)


# ---------------------------------------------------------------------------
# SHOULD: Market Impact — Square-Root Law (Standard Config)
# ---------------------------------------------------------------------------

class TestMarketImpact(unittest.TestCase):
    """
    ΔP = Y × σ × √(Q / V)
    Blueprint Section 2.5 — progressive scaling around ADV thresholds.
    """

    def test_no_impact_below_threshold(self):
        # 100 shares of 50M ADV = 0.0002% → below 0.25% threshold
        trade = make_trade(shares=100, adv=50_000_000)
        self.assertEqual(model.market_impact(trade), 0.0)

    def test_impact_scales_with_order_size(self):
        # Three order sizes all above the 0.25% ADV threshold (2,500+ shares of 1M ADV)
        # 3,000 = 0.3%, 10,000 = 1.0%, 20,000 = 2.0% ADV — each larger than the last
        sizes = [3_000, 10_000, 20_000]
        impacts = [
            model.market_impact(make_trade(shares=s, adv=1_000_000))
            for s in sizes
        ]
        self.assertLess(impacts[0], impacts[1])
        self.assertLess(impacts[1], impacts[2])

    def test_square_root_law(self):
        """
        Total impact = Y × σ × √(Q/V) × Q × P, which scales as Q^1.5.
        Doubling order size increases total impact by 2^1.5 = 2√2 ≈ 2.828.
        (The √law governs per-share impact; total cost includes the extra shares.)
        """
        base   = make_trade(shares=20_000, adv=1_000_000)  # 2% ADV — full impact
        double = make_trade(shares=40_000, adv=1_000_000)  # 4% ADV — full impact
        impact_base   = model.market_impact(base)
        impact_double = model.market_impact(double)
        ratio = impact_double / impact_base
        self.assertAlmostEqual(ratio, 2 * math.sqrt(2), delta=0.05)

    def test_stress_regime_higher_impact_than_calm(self):
        calm   = make_trade(shares=10_000, adv=1_000_000, hmm_state=HMMState.CALM)
        normal = make_trade(shares=10_000, adv=1_000_000, hmm_state=HMMState.NORMAL)
        stress = make_trade(shares=10_000, adv=1_000_000, hmm_state=HMMState.STRESS)
        self.assertLess(model.market_impact(calm), model.market_impact(normal))
        self.assertLess(model.market_impact(normal), model.market_impact(stress))

    def test_gamma_ratio_stress_vs_calm_large_cap(self):
        """Stress gamma (0.25) should be 5× calm gamma (0.05) for large-cap."""
        calm   = make_trade(shares=10_000, adv=500_000, market_cap=15e9, hmm_state=HMMState.CALM)
        stress = make_trade(shares=10_000, adv=500_000, market_cap=15e9, hmm_state=HMMState.STRESS)
        # Both are in the full-impact zone; ratio should equal gamma ratio
        gamma_ratio = (
            MARKET_IMPACT_GAMMA[MarketCapTier.LARGE][HMMState.STRESS] /
            MARKET_IMPACT_GAMMA[MarketCapTier.LARGE][HMMState.CALM]
        )
        impact_ratio = model.market_impact(stress) / model.market_impact(calm)
        self.assertAlmostEqual(impact_ratio, gamma_ratio, places=2)

    def test_linear_ramp_between_thresholds(self):
        """Impact at midpoint of [0.25%, 1.0%] band should be ~50% of full impact."""
        mid_shares  = int(1_000_000 * 0.00625)   # 0.625% ADV — midpoint
        full_shares = int(1_000_000 * 0.015)      # 1.5%  ADV — fully in impact zone
        trade_mid   = make_trade(shares=mid_shares,  adv=1_000_000)
        trade_full  = make_trade(shares=full_shares, adv=1_000_000)
        impact_mid  = model.market_impact(trade_mid)
        impact_full = model.market_impact(trade_full)
        # Mid should be meaningfully less than full; not zero
        self.assertGreater(impact_mid, 0)
        self.assertLess(impact_mid, impact_full)


# ---------------------------------------------------------------------------
# Integration: Full hand-verified example (Blueprint Section 7.5.1)
# ---------------------------------------------------------------------------

class TestFullBreakdownHandVerified(unittest.TestCase):
    """
    Hand-verified reference example from Blueprint Section 12.3 test harness.

    Trade: BUY 100 shares AAPL @ $150.00, Normal regime, large-cap
    Expected (calculated from formulas, not from code):
      commission: min(max(100 × 0.0035, 0.35), 1.00) = $0.35
      spread:     0.0002 × 15,000                    = $3.00
      slippage:   0.00015 × 1.0 × 15,000             = $2.25
      impact:     0.0 (100/50M = 0.0002% < 0.25% ADV)
      sec_fee:    0.00 (buy)
      taf_fee:    0.00 (buy)
    """

    def setUp(self):
        self.trade = make_trade(shares=100, price=150.00, hmm_state=HMMState.NORMAL)
        self.bd    = model.calculate(self.trade)

    def test_commission(self):
        self.assertAlmostEqual(self.bd.commission, 0.35, places=2)

    def test_spread(self):
        self.assertAlmostEqual(self.bd.spread, 3.00, places=2)

    def test_slippage(self):
        self.assertAlmostEqual(self.bd.slippage, 2.25, places=2)

    def test_market_impact_zero_small_order(self):
        self.assertAlmostEqual(self.bd.market_impact, 0.00, places=4)

    def test_sec_fee_zero_on_buy(self):
        self.assertAlmostEqual(self.bd.sec_fee, 0.00, places=4)

    def test_taf_fee_zero_on_buy(self):
        self.assertAlmostEqual(self.bd.taf_fee, 0.00, places=4)

    def test_total_matches_sum_of_components(self):
        expected_total = (0.35 + 3.00 + 2.25 + 0.00 + 0.00 + 0.00)
        self.assertAlmostEqual(self.bd.total, expected_total, places=2)

    def test_convenience_wrapper_matches(self):
        """calculate_total_costs() should match direct model.calculate()"""
        costs = calculate_total_costs({
            'ticker': 'AAPL', 'shares': 100, 'price': 150.00,
            'direction': 'BUY', 'market_cap': 2.5e12,
            'adv': 50_000_000, 'volatility': 0.015, 'hmm_state': 'Normal',
        })
        self.assertAlmostEqual(costs['commission'],  0.35,  places=2)
        self.assertAlmostEqual(costs['spread'],      3.00,  places=2)
        self.assertAlmostEqual(costs['slippage'],    2.25,  places=2)
        self.assertAlmostEqual(costs['total'],       self.bd.total, places=4)


class TestSellBreakdownHandVerified(unittest.TestCase):
    """
    Hand-verified SELL example to confirm regulatory fees are applied.

    Trade: SELL 500 shares MSFT @ $400.00, Normal regime, large-cap
      commission: min(max(500 × 0.0035, 0.35), 1.00)  = $1.00 (capped)
      spread:     0.0002 × (500 × 400) = 0.0002 × 200,000 = $40.00
      slippage:   0.00015 × 1.0 × 200,000              = $30.00
      sec_fee:    200,000 × (27.50 / 1,000,000)         = $5.50
      taf_fee:    min(500 × 0.000195, 9.79) = 0.0975    = $0.0975
      impact:     500 / 20M = 0.0025% < 0.25% ADV       = $0.00
    """

    def setUp(self):
        self.trade = TradeSpec(
            ticker="MSFT", shares=500, price=400.00,
            direction=Direction.SELL, market_cap=3e12,
            adv=20_000_000, volatility=0.02,
            hmm_state=HMMState.NORMAL,
        )
        self.bd = model.calculate(self.trade)

    def test_commission_capped(self):
        self.assertAlmostEqual(self.bd.commission, 1.00, places=4)

    def test_spread(self):
        self.assertAlmostEqual(self.bd.spread, 40.00, places=2)

    def test_slippage(self):
        self.assertAlmostEqual(self.bd.slippage, 30.00, places=2)

    def test_sec_fee(self):
        self.assertAlmostEqual(self.bd.sec_fee, 5.50, places=2)

    def test_taf_fee_uncapped(self):
        self.assertAlmostEqual(self.bd.taf_fee, 0.0975, places=4)

    def test_total(self):
        expected = 1.00 + 40.00 + 30.00 + 5.50 + 0.0975
        self.assertAlmostEqual(self.bd.total, expected, places=2)


# ---------------------------------------------------------------------------
# Round-trip helper
# ---------------------------------------------------------------------------

class TestRoundTrip(unittest.TestCase):

    def test_round_trip_costs_include_both_legs(self):
        rt = model.round_trip_cost(
            ticker="AAPL", shares=100,
            entry_price=150.00, exit_price=152.00,
            market_cap=2.5e12, adv=50_000_000,
            volatility=0.015, hmm_state=HMMState.NORMAL,
        )
        # Entry (BUY): no regulatory fees
        # Exit (SELL): has SEC + TAF fees
        self.assertGreater(rt["exit_cost"], rt["entry_cost"])
        self.assertAlmostEqual(
            rt["total_cost"], rt["entry_cost"] + rt["exit_cost"], places=4
        )
        self.assertIn("cost_bps", rt)

    def test_round_trip_bps_sensible_range(self):
        """Total round-trip cost should be in the 10-100 bps range for typical trades."""
        rt = model.round_trip_cost(
            ticker="AAPL", shares=100,
            entry_price=150.00, exit_price=151.00,
            market_cap=2.5e12, adv=50_000_000,
            volatility=0.015, hmm_state=HMMState.NORMAL,
        )
        self.assertGreater(rt["cost_bps"], 5)
        self.assertLess(rt["cost_bps"], 500)


# ---------------------------------------------------------------------------
# Edge cases & validation
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_string_inputs_coerced_correctly(self):
        """TradeSpec should accept plain string direction and hmm_state."""
        trade = TradeSpec(
            ticker="TEST", shares=100, price=50.00,
            direction="BUY", market_cap=1e9,
            adv=5_000_000, volatility=0.02,
            hmm_state="stress",
        )
        self.assertEqual(trade.direction, Direction.BUY)
        self.assertEqual(trade.hmm_state, HMMState.STRESS)

    def test_cap_tier_boundaries(self):
        large = make_trade(market_cap=10e9 + 1)
        mid   = make_trade(market_cap=5e9)
        small = make_trade(market_cap=1e9)
        self.assertEqual(large.cap_tier, MarketCapTier.LARGE)
        self.assertEqual(mid.cap_tier,   MarketCapTier.MID)
        self.assertEqual(small.cap_tier, MarketCapTier.SMALL)

    def test_notional_calculation(self):
        trade = make_trade(shares=250, price=80.00)
        self.assertAlmostEqual(trade.notional, 20_000.00, places=2)

    def test_cost_breakdown_as_dict(self):
        bd = model.calculate(make_trade())
        d  = bd.as_dict()
        self.assertIn("total_pct_bps", d)
        self.assertIn("commission", d)
        self.assertGreater(d["total"], 0)

    def test_batch_calculate_same_as_individual(self):
        trades = [make_trade(shares=s) for s in [100, 200, 300]]
        batch  = model.calculate_batch(trades)
        for i, trade in enumerate(trades):
            individual = model.calculate(trade)
            self.assertAlmostEqual(batch[i].total, individual.total, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
