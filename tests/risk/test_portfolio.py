"""
tests/risk/test_portfolio.py
-----------------------------
Unit tests for raits.risk.portfolio.

Coverage targets
----------------
calculate_portfolio_beta:
  - Empty portfolio returns 0.0
  - Cash dilution: weights against total equity, not invested capital
  - Fully invested: weights sum to 1.0
  - 50% cash: portfolio beta halved vs fully invested

check_portfolio_beta:
  - PASS when projected beta is below limit
  - REJECT when projected beta exceeds 1.5
  - Boundary: exactly 1.5 passes (> not >=)
  - Zero equity handled gracefully

check_pairwise_correlation:
  - PASS when all correlations within limit
  - REJECT when any |r| > 0.7
  - Negative correlation above 0.7 also triggers
  - Exactly 0.7 passes (> not >=)
  - Empty dict (no existing positions) passes

check_sector_exposure:
  - PASS when projected sector below 40%
  - REJECT when projected sector exceeds 40%
  - Boundary: exactly 40% passes (> not >=)
  - Only same-sector positions counted
  - Zero equity handled gracefully

PortfolioControls.evaluate:
  - Fail-fast on first failure
  - All three must pass for overall PASS
  - evaluate_all returns all results regardless
"""

from __future__ import annotations

import pytest
from raits.risk.portfolio import (
    PortfolioControls,
    PortfolioCheckCode,
    ExistingPosition,
    calculate_portfolio_beta,
    check_portfolio_beta,
    check_pairwise_correlation,
    check_sector_exposure,
    MAX_PORTFOLIO_BETA,
    MAX_PAIRWISE_CORRELATION,
    MAX_SECTOR_EXPOSURE_PCT,
)

EQUITY = 25_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pos(ticker: str, value: float, beta: float, sector: str = "Technology") -> ExistingPosition:
    return ExistingPosition(ticker=ticker, market_value=value, beta=beta, sector=sector)


# ---------------------------------------------------------------------------
# calculate_portfolio_beta
# ---------------------------------------------------------------------------

class TestCalculatePortfolioBeta:
    def test_empty_portfolio_returns_zero(self):
        assert calculate_portfolio_beta([], EQUITY) == 0.0

    def test_zero_equity_returns_zero(self):
        positions = [pos("AAPL", 10_000, 1.2)]
        assert calculate_portfolio_beta(positions, 0) == 0.0

    def test_fully_invested_single_position(self):
        # 100% in one stock with beta 1.4 -> portfolio beta = 1.4
        positions = [pos("AAPL", 25_000, 1.4)]
        beta = calculate_portfolio_beta(positions, 25_000)
        assert abs(beta - 1.4) < 1e-6

    def test_cash_dilution_50pct_invested(self):
        """
        Blueprint example: $12,500 invested, $12,500 cash.
        Portfolio beta = 0.5 * 1.4 = 0.70 (cash dilutes by half).
        """
        positions = [pos("AAPL", 12_500, 1.4)]
        beta = calculate_portfolio_beta(positions, 25_000)
        assert abs(beta - 0.70) < 1e-6

    def test_cash_dilution_blueprint_example(self):
        """
        Blueprint Section 5.2 exact example:
        AAPL $10k beta 1.5, MSFT $10k beta 1.3, cash $5k.
        Expected: 0.4*1.5 + 0.4*1.3 + 0.2*0.0 = 1.12
        """
        positions = [
            pos("AAPL", 10_000, 1.5),
            pos("MSFT", 10_000, 1.3),
        ]
        beta = calculate_portfolio_beta(positions, 25_000)
        assert abs(beta - 1.12) < 1e-6

    def test_two_positions_fully_invested(self):
        """50%/50% split, fully invested: weighted average."""
        positions = [
            pos("AAPL", 12_500, 1.4),
            pos("MSFT", 12_500, 1.2),
        ]
        beta = calculate_portfolio_beta(positions, 25_000)
        # 0.5*1.4 + 0.5*1.2 = 1.30
        assert abs(beta - 1.30) < 1e-6

    def test_high_beta_position(self):
        positions = [pos("NVDA", 5_000, 2.1)]
        beta = calculate_portfolio_beta(positions, 25_000)
        # 0.2 * 2.1 = 0.42
        assert abs(beta - 0.42) < 1e-6


# ---------------------------------------------------------------------------
# check_portfolio_beta
# ---------------------------------------------------------------------------

class TestCheckPortfolioBeta:
    def test_no_existing_positions_low_beta_passes(self):
        r = check_portfolio_beta(5_000, 1.2, [], EQUITY)
        assert r.passed

    def test_exactly_at_limit_passes(self):
        """Projected beta == 1.5 must PASS (limit is >, not >=)."""
        # 100% in one stock, what beta produces exactly 1.5?
        # new_weight = 5000/25000 = 0.20, need 0.20 * beta = 1.5 -> beta = 7.5
        # Easier: use 25000/25000 = 1.0 weight, beta = 1.5
        r = check_portfolio_beta(25_000, 1.5, [], EQUITY)
        assert r.passed

    def test_above_limit_rejects(self):
        """Projected beta > 1.5 must REJECT."""
        r = check_portfolio_beta(25_000, 1.501, [], EQUITY)
        assert not r.passed
        assert r.code == PortfolioCheckCode.REJECT

    def test_existing_positions_push_over_limit(self):
        """Two positions together exceed beta limit."""
        existing = [pos("AAPL", 10_000, 1.4)]
        # current beta = 10000/25000 * 1.4 = 0.56
        # new: 10000/25000 * 1.8 = 0.72 -> projected = 1.28 (passes)
        r = check_portfolio_beta(10_000, 1.8, existing, EQUITY)
        assert r.passed

    def test_three_positions_exceeds_limit(self):
        existing = [
            pos("AAPL", 10_000, 1.6),
            pos("MSFT", 10_000, 1.5),
        ]
        # current = (10k/25k)*1.6 + (10k/25k)*1.5 = 0.64+0.60 = 1.24
        # new: (5k/25k)*1.8 = 0.36 -> projected = 1.60 > 1.5
        r = check_portfolio_beta(5_000, 1.8, existing, EQUITY)
        assert not r.passed

    def test_zero_equity_skips_gracefully(self):
        r = check_portfolio_beta(5_000, 1.8, [], 0)
        assert r.passed

    def test_projected_beta_in_result_data(self):
        r = check_portfolio_beta(5_000, 1.2, [], EQUITY)
        assert "projected_beta" in r.data
        assert "current_beta" in r.data


# ---------------------------------------------------------------------------
# check_pairwise_correlation
# ---------------------------------------------------------------------------

class TestCheckPairwiseCorrelation:
    def test_empty_dict_passes(self):
        r = check_pairwise_correlation("NVDA", {})
        assert r.passed

    def test_low_correlations_pass(self):
        r = check_pairwise_correlation("NVDA", {"AAPL": 0.50, "MSFT": 0.45})
        assert r.passed

    def test_exactly_at_limit_passes(self):
        """Exactly 0.70 must PASS (limit is >, not >=)."""
        r = check_pairwise_correlation("NVDA", {"AAPL": 0.70})
        assert r.passed

    def test_above_limit_rejects(self):
        r = check_pairwise_correlation("NVDA", {"AAPL": 0.71})
        assert not r.passed
        assert r.code == PortfolioCheckCode.REJECT

    def test_negative_correlation_above_limit_rejects(self):
        """High negative correlation is also a structural concentration."""
        r = check_pairwise_correlation("SH", {"SPY": -0.95})
        assert not r.passed

    def test_negative_exactly_at_limit_passes(self):
        r = check_pairwise_correlation("SH", {"SPY": -0.70})
        assert r.passed

    def test_one_violation_among_many_rejects(self):
        r = check_pairwise_correlation("NVDA", {
            "AAPL": 0.50,
            "MSFT": 0.45,
            "AMD": 0.75,    # violation
            "GOOG": 0.30,
        })
        assert not r.passed

    def test_violation_ticker_in_data(self):
        r = check_pairwise_correlation("NVDA", {"AMD": 0.80})
        assert "AMD" in r.data.get("violations", {})

    def test_pairs_checked_count_in_pass_data(self):
        r = check_pairwise_correlation("NVDA", {"AAPL": 0.3, "MSFT": 0.4})
        assert r.data.get("pairs_checked") == 2

    def test_high_positive_correlation_rejects(self):
        r = check_pairwise_correlation("NVDA", {"AMD": 0.92})
        assert not r.passed


# ---------------------------------------------------------------------------
# check_sector_exposure
# ---------------------------------------------------------------------------

class TestCheckSectorExposure:
    def test_no_existing_same_sector_passes(self):
        existing = [pos("JPM", 8_000, 1.1, sector="Financials")]
        r = check_sector_exposure("AAPL", "Technology", 5_000, existing, EQUITY)
        assert r.passed

    def test_exactly_at_limit_passes(self):
        """Sector at exactly 40% must PASS (> not >=)."""
        # 40% of 25000 = 10000; no existing in sector; new = 10000
        r = check_sector_exposure("AAPL", "Technology", 10_000, [], EQUITY)
        assert r.passed

    def test_above_limit_rejects(self):
        """One dollar above 40% must REJECT."""
        r = check_sector_exposure("AAPL", "Technology", 10_001, [], EQUITY)
        assert not r.passed
        assert r.code == PortfolioCheckCode.REJECT

    def test_existing_same_sector_accumulates(self):
        existing = [pos("MSFT", 8_000, 1.2, sector="Technology")]
        # 8000 existing + 4000 new = 12000 / 25000 = 48% > 40%
        r = check_sector_exposure("AAPL", "Technology", 4_000, existing, EQUITY)
        assert not r.passed

    def test_existing_same_sector_within_limit_passes(self):
        existing = [pos("MSFT", 5_000, 1.2, sector="Technology")]
        # 5000 + 4000 = 9000 / 25000 = 36% < 40%
        r = check_sector_exposure("AAPL", "Technology", 4_000, existing, EQUITY)
        assert r.passed

    def test_different_sector_positions_not_counted(self):
        """Financials positions should not count toward Technology limit."""
        existing = [
            pos("JPM", 8_000, 1.1, sector="Financials"),
            pos("GS",  6_000, 1.3, sector="Financials"),
        ]
        r = check_sector_exposure("AAPL", "Technology", 9_000, existing, EQUITY)
        assert r.passed  # 9000/25000 = 36% < 40%

    def test_sector_pct_in_result_data(self):
        r = check_sector_exposure("AAPL", "Technology", 5_000, [], EQUITY)
        assert "projected_sector_pct" in r.data

    def test_zero_equity_skips_gracefully(self):
        r = check_sector_exposure("AAPL", "Technology", 5_000, [], 0)
        assert r.passed


# ---------------------------------------------------------------------------
# PortfolioControls orchestrator
# ---------------------------------------------------------------------------

class TestPortfolioControls:
    def setup_method(self):
        self.pc = PortfolioControls()

    def _all_pass_kwargs(self, **overrides):
        kwargs = dict(
            new_ticker="NVDA",
            new_ticker_sector="Technology",
            new_position_value=4_000,
            new_position_beta=1.2,
            correlations_with_existing={},
            existing_positions=[],
            account_equity=25_000,
        )
        kwargs.update(overrides)
        return kwargs

    def test_all_pass(self):
        r = self.pc.evaluate(**self._all_pass_kwargs())
        assert r.passed

    def test_beta_violation_fails_fast(self):
        """Beta over limit -> fails on first check."""
        r = self.pc.evaluate(**self._all_pass_kwargs(
            new_position_value=25_000,
            new_position_beta=1.6,  # 100% * 1.6 = 1.6 > 1.5
        ))
        assert not r.passed
        assert r.check_name == "BetaCap"

    def test_correlation_violation_fails(self):
        r = self.pc.evaluate(**self._all_pass_kwargs(
            correlations_with_existing={"AMD": 0.85},
        ))
        assert not r.passed
        assert r.check_name == "PairwiseCorrelation"

    def test_sector_violation_fails(self):
        r = self.pc.evaluate(**self._all_pass_kwargs(
            new_position_value=11_000,   # 44% > 40%
            new_position_beta=1.0,
        ))
        assert not r.passed
        assert r.check_name == "SectorExposure"

    def test_evaluate_all_returns_all_results(self):
        results = self.pc.evaluate_all(**self._all_pass_kwargs())
        assert len(results) == 3

    def test_evaluate_all_includes_failures(self):
        """evaluate_all must not short-circuit — returns all 3 results even when beta fails."""
        results = self.pc.evaluate_all(**self._all_pass_kwargs(
            new_position_value=25_000,
            new_position_beta=1.6,   # triggers beta failure
        ))
        assert len(results) == 3  # all three returned, not just the first failure

    def test_check_name_in_results(self):
        r = self.pc.evaluate(**self._all_pass_kwargs())
        assert r.check_name == "PortfolioControls"
