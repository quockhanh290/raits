"""
raits/risk/portfolio.py
-----------------------
Layer 2: Portfolio Controls — "Logic Controls (Strategy Supervisor)"

Blueprint reference: Section 5.2
Requirement level:  SHOULD

Three independent portfolio-level checks that run before any new position
is approved.  All three must PASS for the order to proceed.

Check 1 — Portfolio Beta Cap (max 1.5)
    Uses TOTAL account equity as the denominator (cash beta = 0.0),
    which is the correct institutional method.  Weighting against only
    invested capital overstates beta by 10-25% when cash is present.

Check 2 — Pairwise Correlation Cap (max 0.7)
    Rejects a new position if it is highly correlated (|r| > 0.7) with
    any existing position.  Prevents concentration in a de-facto single
    factor disguised as multiple positions.

Check 3 — Sector Exposure Cap (max 40%)
    Prevents more than 40% of account equity being deployed in any single
    GICS sector.  Complements the beta cap by limiting factor concentration
    within a sector rather than across the whole market.

Design decisions
----------------
* Pure functions only — no hidden I/O, no data fetching.
  Betas, correlations, and sector labels are passed in by the caller.
  This keeps the module fast, testable, and side-effect free.
* PortfolioControls orchestrates the three checks and returns the first
  failure (fail-fast), or PASS if all three clear.
* Betas and correlations must be supplied by the backtesting engine or
  data pipeline; this module does not compute them from price data.

Blueprint note: "Better to miss some high-beta trades than to build a
2x leveraged SPY portfolio disguised as alpha."
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dc_field
from enum import Enum

logger = logging.getLogger("RAITS.risk.portfolio")

# ---------------------------------------------------------------------------
# Constants (Blueprint §5.2)
# ---------------------------------------------------------------------------

MAX_PORTFOLIO_BETA: float      = 1.5    # reject if projected beta > this
MAX_PAIRWISE_CORRELATION: float = 0.70  # reject if |r| > this with any holding
MAX_SECTOR_EXPOSURE_PCT: float  = 0.40  # reject if sector would exceed 40% of equity


# ---------------------------------------------------------------------------
# Supporting types
# ---------------------------------------------------------------------------

class PortfolioCheckCode(str, Enum):
    PASS   = "PASS"
    REJECT = "REJECT"


@dataclass(frozen=True)
class PortfolioCheckResult:
    """Immutable result from a portfolio-level check."""
    code: PortfolioCheckCode
    reason: str
    check_name: str
    data: dict = dc_field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.code == PortfolioCheckCode.PASS

    def __repr__(self) -> str:
        return f"PortfolioCheckResult([{self.check_name}] {self.code.value}: {self.reason})"


@dataclass(frozen=True)
class ExistingPosition:
    """
    Minimal position descriptor for portfolio-level checks.
    Betas and sectors are pre-computed by the caller.
    """
    ticker: str
    market_value: float   # current mark-to-market value (USD)
    beta: float           # single-name beta vs SPY (1-year, 252-day lookback)
    sector: str           # GICS sector label, e.g. "Technology"


# ---------------------------------------------------------------------------
# Check 1 — Portfolio Beta
# ---------------------------------------------------------------------------

def calculate_portfolio_beta(
    positions: list[ExistingPosition],
    account_equity: float,
) -> float:
    """
    Calculate current portfolio beta using cash-diluted weighting.

    Weights each position against TOTAL account equity (not just invested
    capital).  Cash has beta = 0.0 and properly dilutes aggregate exposure.

    Parameters
    ----------
    positions      : all currently open positions with pre-computed betas
    account_equity : total account value including cash (USD)

    Returns
    -------
    Portfolio beta (float).  Returns 0.0 if no positions or zero equity.
    """
    if account_equity <= 0 or not positions:
        return 0.0

    portfolio_beta = sum(
        (p.market_value / account_equity) * p.beta
        for p in positions
    )
    return portfolio_beta


def check_portfolio_beta(
    new_position_value: float,
    new_position_beta: float,
    existing_positions: list[ExistingPosition],
    account_equity: float,
) -> PortfolioCheckResult:
    """
    Check whether adding a new position would breach the beta cap.

    Computes PROJECTED portfolio beta (existing + new) against account_equity
    as the denominator.  Cash automatically dilutes the result.

    Parameters
    ----------
    new_position_value : market value of the proposed new position (USD)
    new_position_beta  : beta of the new ticker vs SPY
    existing_positions : currently open positions
    account_equity     : total account value (USD)
    """
    name = "BetaCap"

    if account_equity <= 0:
        return PortfolioCheckResult(
            PortfolioCheckCode.PASS, "account_equity non-positive — check skipped", name,
        )

    # Current beta (cash-diluted)
    current_beta = calculate_portfolio_beta(existing_positions, account_equity)

    # Projected beta: add new position weight (cash shrinks accordingly)
    new_weight = new_position_value / account_equity
    projected_beta = current_beta + new_weight * new_position_beta

    logger.debug(
        "Beta check: current=%.3f new_weight=%.3f new_beta=%.2f projected=%.3f (limit=%.1f)",
        current_beta, new_weight, new_position_beta, projected_beta, MAX_PORTFOLIO_BETA,
    )

    if projected_beta > MAX_PORTFOLIO_BETA:
        reason = (
            f"Projected portfolio beta {projected_beta:.3f} would exceed "
            f"limit {MAX_PORTFOLIO_BETA:.1f} "
            f"(current={current_beta:.3f}, new={new_position_beta:.2f})"
        )
        logger.info("REJECT — %s", reason)
        return PortfolioCheckResult(
            PortfolioCheckCode.REJECT, reason, name,
            data={
                "current_beta": round(current_beta, 4),
                "projected_beta": round(projected_beta, 4),
                "new_position_beta": new_position_beta,
                "limit": MAX_PORTFOLIO_BETA,
            },
        )

    return PortfolioCheckResult(
        PortfolioCheckCode.PASS,
        f"Projected beta {projected_beta:.3f} within limit {MAX_PORTFOLIO_BETA:.1f}",
        name,
        data={
            "current_beta": round(current_beta, 4),
            "projected_beta": round(projected_beta, 4),
        },
    )


# ---------------------------------------------------------------------------
# Check 2 — Pairwise Correlation
# ---------------------------------------------------------------------------

def check_pairwise_correlation(
    new_ticker: str,
    correlations_with_existing: dict[str, float],
) -> PortfolioCheckResult:
    """
    Reject if the new ticker is highly correlated with any existing position.

    Parameters
    ----------
    new_ticker                  : symbol being considered
    correlations_with_existing  : {existing_ticker: correlation_coefficient}
                                  Pre-computed by the caller (e.g. 60-day rolling).
                                  Only tickers currently held need to be included.

    The absolute value of correlation is used — negative correlation above
    0.7 is also structural concentration (short/long same factor).
    """
    name = "PairwiseCorrelation"

    violations = {
        ticker: corr
        for ticker, corr in correlations_with_existing.items()
        if abs(corr) > MAX_PAIRWISE_CORRELATION
    }

    if violations:
        worst_ticker = max(violations, key=lambda t: abs(violations[t]))
        worst_corr = violations[worst_ticker]
        reason = (
            f"{new_ticker} correlation with {worst_ticker} is {worst_corr:+.3f} "
            f"(limit |r|={MAX_PAIRWISE_CORRELATION:.2f}) — "
            f"{len(violations)} violation(s) total"
        )
        logger.info("REJECT — %s", reason)
        return PortfolioCheckResult(
            PortfolioCheckCode.REJECT, reason, name,
            data={
                "new_ticker": new_ticker,
                "violations": {t: round(c, 4) for t, c in violations.items()},
                "limit": MAX_PAIRWISE_CORRELATION,
            },
        )

    logger.debug(
        "Correlation check %s: %d pair(s) checked, none exceed |%.2f|",
        new_ticker, len(correlations_with_existing), MAX_PAIRWISE_CORRELATION,
    )
    return PortfolioCheckResult(
        PortfolioCheckCode.PASS,
        f"{new_ticker}: all pairwise correlations within limit "
        f"({len(correlations_with_existing)} pair(s) checked)",
        name,
        data={"pairs_checked": len(correlations_with_existing)},
    )


# ---------------------------------------------------------------------------
# Check 3 — Sector Exposure
# ---------------------------------------------------------------------------

def check_sector_exposure(
    new_ticker: str,
    new_ticker_sector: str,
    new_position_value: float,
    existing_positions: list[ExistingPosition],
    account_equity: float,
) -> PortfolioCheckResult:
    """
    Reject if adding the new position would push any sector over 40% of equity.

    Parameters
    ----------
    new_ticker          : symbol being considered
    new_ticker_sector   : GICS sector label (must match sector labels in positions)
    new_position_value  : proposed position size (USD)
    existing_positions  : currently open positions with sector labels
    account_equity      : total account value (USD)
    """
    name = "SectorExposure"

    if account_equity <= 0:
        return PortfolioCheckResult(
            PortfolioCheckCode.PASS, "account_equity non-positive — check skipped", name,
        )

    # Current sector exposure
    current_sector_value = sum(
        p.market_value for p in existing_positions
        if p.sector == new_ticker_sector
    )
    projected_sector_value = current_sector_value + new_position_value
    projected_sector_pct = projected_sector_value / account_equity

    logger.debug(
        "Sector check %s (%s): current=%.1f%% projected=%.1f%% (limit=%.0f%%)",
        new_ticker, new_ticker_sector,
        (current_sector_value / account_equity) * 100,
        projected_sector_pct * 100,
        MAX_SECTOR_EXPOSURE_PCT * 100,
    )

    if projected_sector_pct > MAX_SECTOR_EXPOSURE_PCT:
        reason = (
            f"Sector '{new_ticker_sector}' exposure would reach "
            f"{projected_sector_pct:.1%} (limit {MAX_SECTOR_EXPOSURE_PCT:.0%}) — "
            f"current=${current_sector_value:,.0f}, new=${new_position_value:,.0f}"
        )
        logger.info("REJECT — %s", reason)
        return PortfolioCheckResult(
            PortfolioCheckCode.REJECT, reason, name,
            data={
                "sector": new_ticker_sector,
                "current_sector_pct": round(current_sector_value / account_equity, 4),
                "projected_sector_pct": round(projected_sector_pct, 4),
                "limit": MAX_SECTOR_EXPOSURE_PCT,
            },
        )

    return PortfolioCheckResult(
        PortfolioCheckCode.PASS,
        f"Sector '{new_ticker_sector}' at {projected_sector_pct:.1%} — within limit",
        name,
        data={
            "sector": new_ticker_sector,
            "projected_sector_pct": round(projected_sector_pct, 4),
        },
    )


# ---------------------------------------------------------------------------
# PortfolioControls orchestrator
# ---------------------------------------------------------------------------

class PortfolioControls:
    """
    Runs all three Layer 2 portfolio checks in order.
    Returns the first failure (fail-fast) or PASS if all three clear.

    Usage
    -----
    pc = PortfolioControls()
    result = pc.evaluate(
        new_ticker="NVDA",
        new_ticker_sector="Technology",
        new_position_value=4_000,
        new_position_beta=1.8,
        correlations_with_existing={"AAPL": 0.65, "MSFT": 0.72},
        existing_positions=open_positions,
        account_equity=25_000,
    )
    if not result.passed:
        logger.info("Position rejected: %s", result.reason)
    """

    def evaluate(
        self,
        new_ticker: str,
        new_ticker_sector: str,
        new_position_value: float,
        new_position_beta: float,
        correlations_with_existing: dict[str, float],
        existing_positions: list[ExistingPosition],
        account_equity: float,
    ) -> PortfolioCheckResult:
        """
        Run all three checks in blueprint-specified order.
        Returns immediately on first failure (fail-fast).
        """
        checks = [
            check_portfolio_beta(
                new_position_value, new_position_beta,
                existing_positions, account_equity,
            ),
            check_pairwise_correlation(new_ticker, correlations_with_existing),
            check_sector_exposure(
                new_ticker, new_ticker_sector, new_position_value,
                existing_positions, account_equity,
            ),
        ]

        for result in checks:
            logger.debug(repr(result))
            if not result.passed:
                logger.warning("Portfolio REJECT — %s", result)
                return result

        logger.debug(
            "Portfolio controls PASS for %s (%.0f%% of equity, beta=%.2f, sector=%s)",
            new_ticker,
            (new_position_value / account_equity * 100) if account_equity > 0 else 0,
            new_position_beta,
            new_ticker_sector,
        )
        return PortfolioCheckResult(
            PortfolioCheckCode.PASS,
            f"All portfolio controls passed for {new_ticker}",
            "PortfolioControls",
        )

    def evaluate_all(
        self,
        new_ticker: str,
        new_ticker_sector: str,
        new_position_value: float,
        new_position_beta: float,
        correlations_with_existing: dict[str, float],
        existing_positions: list[ExistingPosition],
        account_equity: float,
    ) -> list[PortfolioCheckResult]:
        """
        Run all checks and return every result (not fail-fast).
        Useful for diagnostics and WFO reporting.
        """
        return [
            check_portfolio_beta(
                new_position_value, new_position_beta,
                existing_positions, account_equity,
            ),
            check_pairwise_correlation(new_ticker, correlations_with_existing),
            check_sector_exposure(
                new_ticker, new_ticker_sector, new_position_value,
                existing_positions, account_equity,
            ),
        ]
