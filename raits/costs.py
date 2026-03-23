"""
RAITS Transaction Cost Model
============================
Phase 1A — Weeks 6-8 deliverable

Implements all SHALL (mandatory) and SHOULD (standard config) cost components
as specified in Blueprint v1.2, Section 2.

SHALL components (Tier 1 — required for Vault validation):
  - Bid-ask spread modeling
  - Commission calculation (IB Tiered)
  - SEC Section 31 fees
  - FINRA TAF fees
  - Basic slippage (minimum 0.01% per trade)

SHOULD components (Tier 2 — standard configuration):
  - Market impact model (square-root law, regime-dependent gamma)
  - Entry gap analysis (bar-to-bar execution gaps, percentile-based)
  - Regime-aware slippage multipliers (Calm 0.67×, Normal 1.0×, Stress 2.0×)

Order fill assumptions (Section 2.2 — Microstructure Friction):
  - Orders NEVER fill at the Close of a minute bar
  - Buys  → executed at the Ask
  - Sells → executed at the Bid

Usage:
    from raits.costs import TransactionCostModel, TradeSpec, HMMState

    model = TransactionCostModel()
    trade = TradeSpec(
        ticker="AAPL", shares=100, price=150.00,
        direction="BUY", market_cap=2.5e12,
        adv=50_000_000, volatility=0.015,
        hmm_state=HMMState.NORMAL,
    )
    breakdown = model.calculate(trade)
    print(breakdown.total)   # e.g. $3.05
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & Constants
# ---------------------------------------------------------------------------

class HMMState(str, Enum):
    """Three HMM regime states used throughout RAITS."""
    CALM   = "calm"
    NORMAL = "normal"
    STRESS = "stress"


class Direction(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


class MarketCapTier(str, Enum):
    LARGE = "large_cap"   # > $10B
    MID   = "mid_cap"     # $2B – $10B
    SMALL = "small_cap"   # < $2B


# ---------------------------------------------------------------------------
# Blueprint constants (Section 2.4 & 2.5)
# ---------------------------------------------------------------------------

# IB Tiered pricing
IB_RATE_PER_SHARE = 0.0035
IB_MIN_PER_ORDER  = 0.35
IB_MAX_PER_ORDER  = 1.00

# Regulatory fees (sell-side only)
SEC_RATE_PER_DOLLAR = 27.50 / 1_000_000   # $27.50 per $1M
FINRA_TAF_PER_SHARE = 0.000195
FINRA_TAF_CAP       = 9.79                 # 2026 cap

# Bid-ask spread typical ranges (% of price) — Section 2.3
SPREAD_PCT: Dict[MarketCapTier, float] = {
    MarketCapTier.LARGE: 0.0002,   # 0.02% — midpoint of 0.01–0.02%
    MarketCapTier.MID:   0.0003,   # 0.03% — midpoint of 0.02–0.05%
    MarketCapTier.SMALL: 0.0010,   # 0.10% — midpoint of 0.05–0.15%
}

# Market impact gamma — regime × liquidity tier (Section 2.5)
MARKET_IMPACT_GAMMA: Dict[MarketCapTier, Dict[HMMState, float]] = {
    MarketCapTier.LARGE: {
        HMMState.CALM:   0.05,
        HMMState.NORMAL: 0.10,
        HMMState.STRESS: 0.25,
    },
    MarketCapTier.MID: {
        HMMState.CALM:   0.15,
        HMMState.NORMAL: 0.30,
        HMMState.STRESS: 0.60,
    },
    MarketCapTier.SMALL: {
        HMMState.CALM:   0.30,
        HMMState.NORMAL: 0.60,
        HMMState.STRESS: 1.20,
    },
}

# Regime-aware slippage multipliers (SHOULD — Section 2.3)
SLIPPAGE_REGIME_MULTIPLIER: Dict[HMMState, float] = {
    HMMState.CALM:   0.67,
    HMMState.NORMAL: 1.00,
    HMMState.STRESS: 2.00,
}

# Base slippage as a fraction of price (minimum 0.01% per Blueprint SHALL)
BASE_SLIPPAGE_PCT = 0.00015   # 0.015% — typical for liquid intraday stocks

# Market impact progressive scaling thresholds (fraction of ADV)
IMPACT_ZERO_THRESHOLD = 0.0025   # <0.25% ADV → no impact, slippage only
IMPACT_FULL_THRESHOLD = 0.0100   # >1.0%  ADV → full impact

# Short borrow rate defaults (Section 2.4)
BORROW_RATE_DEFAULTS: Dict[MarketCapTier, float] = {
    MarketCapTier.LARGE: 0.005,   # 0.5% annualized
    MarketCapTier.MID:   0.020,   # 2.0% annualized
    MarketCapTier.SMALL: 0.050,   # 5.0% annualized
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TradeSpec:
    """
    Complete specification of a single trade, required for cost calculation.

    Parameters
    ----------
    ticker      : str        — Stock symbol
    shares      : int        — Number of shares traded (positive integer)
    price       : float      — Execution price (Ask for buys, Bid for sells)
    direction   : Direction  — BUY or SELL
    market_cap  : float      — Current market cap in dollars (used for tier)
    adv         : float      — 20-day avg daily volume in shares
    volatility  : float      — 20-day realized volatility (e.g. 0.02 = 2%)
    hmm_state   : HMMState   — Current regime from HMM model
    days_held   : int        — Holding period (for short borrow fee, default 1)
    borrow_rate : float|None — Annualized borrow rate; None → use tier default
    gap_pcts    : dict|None  — Historical gap percentiles {p50, p75, p90} for
                               this ticker. None → fallback to base slippage.
    """
    ticker:      str
    shares:      int
    price:       float
    direction:   Direction
    market_cap:  float
    adv:         float
    volatility:  float
    hmm_state:   HMMState
    days_held:   int = 1
    borrow_rate: Optional[float] = None
    gap_pcts:    Optional[Dict[str, float]] = None

    def __post_init__(self):
        # Coerce string direction / state if callers pass plain strings
        if isinstance(self.direction, str):
            self.direction = Direction(self.direction.upper())
        if isinstance(self.hmm_state, str):
            self.hmm_state = HMMState(self.hmm_state.lower())
        assert self.shares > 0,  "shares must be positive"
        assert self.price  > 0,  "price must be positive"
        assert self.adv    > 0,  "adv must be positive"

    @property
    def notional(self) -> float:
        return self.shares * self.price

    @property
    def cap_tier(self) -> MarketCapTier:
        if self.market_cap > 10e9:
            return MarketCapTier.LARGE
        elif self.market_cap > 2e9:
            return MarketCapTier.MID
        else:
            return MarketCapTier.SMALL

    @property
    def order_fraction(self) -> float:
        """Fraction of average daily volume being traded."""
        return self.shares / self.adv


@dataclass
class CostBreakdown:
    """
    Per-trade cost breakdown with all components itemised.
    All values are in dollars (positive = cost to trader).
    """
    commission:    float = 0.0
    spread:        float = 0.0
    slippage:      float = 0.0
    market_impact: float = 0.0
    sec_fee:       float = 0.0
    taf_fee:       float = 0.0
    borrow_fee:    float = 0.0

    # Metadata (not included in total)
    ticker:        str   = ""
    shares:        int   = 0
    price:         float = 0.0
    direction:     str   = ""
    hmm_state:     str   = ""
    cap_tier:      str   = ""
    order_fraction:float = 0.0

    @property
    def total(self) -> float:
        return (self.commission + self.spread + self.slippage +
                self.market_impact + self.sec_fee + self.taf_fee +
                self.borrow_fee)

    @property
    def total_pct(self) -> float:
        """Total cost as a fraction of notional value."""
        notional = self.shares * self.price
        return self.total / notional if notional > 0 else 0.0

    def as_dict(self) -> dict:
        return {
            "ticker":         self.ticker,
            "shares":         self.shares,
            "price":          self.price,
            "direction":      self.direction,
            "hmm_state":      self.hmm_state,
            "cap_tier":       self.cap_tier,
            "order_fraction": round(self.order_fraction, 6),
            "commission":     round(self.commission, 4),
            "spread":         round(self.spread, 4),
            "slippage":       round(self.slippage, 4),
            "market_impact":  round(self.market_impact, 4),
            "sec_fee":        round(self.sec_fee, 4),
            "taf_fee":        round(self.taf_fee, 4),
            "borrow_fee":     round(self.borrow_fee, 4),
            "total":          round(self.total, 4),
            "total_pct_bps":  round(self.total_pct * 10_000, 2),
        }


# ---------------------------------------------------------------------------
# TransactionCostModel
# ---------------------------------------------------------------------------

class TransactionCostModel:
    """
    Institutional-grade transaction cost calculator for RAITS.

    All cost formulas are sourced directly from Blueprint v1.2, Section 2.
    Every method has a reference comment indicating the Blueprint section.

    Design principle: each component is a standalone method so callers
    can unit-test individual pieces without constructing full TradeSpec objects.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(self, trade: TradeSpec) -> CostBreakdown:
        """
        Calculate the full cost breakdown for a single trade.

        This is the primary entry point. Calls each cost component in order
        and returns an itemised CostBreakdown.

        Blueprint reference: Section 2 — Data Engineering & Transaction Cost Model
        """
        bd = CostBreakdown(
            ticker         = trade.ticker,
            shares         = trade.shares,
            price          = trade.price,
            direction      = trade.direction.value,
            hmm_state      = trade.hmm_state.value,
            cap_tier       = trade.cap_tier.value,
            order_fraction = trade.order_fraction,
        )

        bd.commission    = self.commission(trade)
        bd.spread        = self.spread(trade)
        bd.slippage      = self.slippage(trade)
        bd.market_impact = self.market_impact(trade)

        # Regulatory fees: sell-side only
        if trade.direction == Direction.SELL:
            bd.sec_fee = self.sec_fee(trade)
            bd.taf_fee = self.taf_fee(trade)

        # Short borrow fee: short positions only
        if trade.direction == Direction.SELL:  # simplified — extend for SHORT
            bd.borrow_fee = 0.0  # shorts handled separately in position manager

        self._log(trade, bd)
        return bd

    # ------------------------------------------------------------------
    # SHALL components — Mandatory (Tier 1)
    # ------------------------------------------------------------------

    def commission(self, trade: TradeSpec) -> float:
        """
        IB Tiered commission: $0.0035/share, min $0.35, max $1.00 per order.

        Blueprint reference: Section 2.4 — Broker Commissions
        Formula: min(max(shares × $0.0035, $0.35), $1.00)
        """
        raw = trade.shares * IB_RATE_PER_SHARE
        return min(max(raw, IB_MIN_PER_ORDER), IB_MAX_PER_ORDER)

    def spread(self, trade: TradeSpec) -> float:
        """
        Bid-ask spread cost: percentage of notional, tier-dependent.

        Buys pay the ask (above mid); sells receive the bid (below mid).
        Cost is therefore spread_pct × notional for each side.

        Blueprint reference: Section 2.2 — Microstructure Friction
        Typical ranges: Large-cap 0.01–0.02%, Mid-cap 0.02–0.05%, Small-cap 0.05–0.15%
        """
        pct = SPREAD_PCT[trade.cap_tier]
        return pct * trade.notional

    def slippage(self, trade: TradeSpec) -> float:
        """
        Two-component regime-aware slippage (SHOULD enhances the SHALL minimum).

        Component 1: Bid-ask spread — already captured in spread()
        Component 2: Bar-to-bar execution gap

        If historical gap percentiles are provided (gap_pcts), use them with
        regime-appropriate percentile selection. Otherwise fall back to the
        base rate × regime multiplier (guaranteed ≥ 0.01% per Blueprint SHALL).

        Blueprint reference: Section 2.3 — Regime-Aware Slippage & Execution Gaps
        Regime multipliers: Calm 0.67×, Normal 1.0×, Stress 2.0×
        """
        multiplier = SLIPPAGE_REGIME_MULTIPLIER[trade.hmm_state]

        if trade.gap_pcts:
            # SHOULD path: percentile-based from historical analysis
            percentile_map = {
                HMMState.CALM:   "p50",
                HMMState.NORMAL: "p75",
                HMMState.STRESS: "p90",
            }
            key = percentile_map[trade.hmm_state]
            gap_pct = trade.gap_pcts.get(key, BASE_SLIPPAGE_PCT)
        else:
            # SHALL fallback: base rate × regime multiplier
            gap_pct = BASE_SLIPPAGE_PCT * multiplier

        # Enforce Blueprint minimum: no less than 0.01% per trade
        gap_pct = max(gap_pct, 0.0001)

        return gap_pct * trade.notional

    def sec_fee(self, trade: TradeSpec) -> float:
        """
        SEC Section 31 transaction fee.
        Applied to SELL orders only at $27.50 per $1M of sell-side value.

        Blueprint reference: Section 2.4 — SEC Section 31 Transaction Fees
        Formula: sell_value × (27.50 / 1_000_000)
        """
        if trade.direction != Direction.SELL:
            return 0.0
        return trade.notional * SEC_RATE_PER_DOLLAR

    def taf_fee(self, trade: TradeSpec) -> float:
        """
        FINRA Trading Activity Fee (TAF).
        Applied to SELL orders only. $0.000195/share, capped at $9.79 (2026 rate).

        Blueprint reference: Section 2.4 — FINRA Trading Activity Fee
        Formula: min(shares × $0.000195, $9.79)
        """
        if trade.direction != Direction.SELL:
            return 0.0
        return min(trade.shares * FINRA_TAF_PER_SHARE, FINRA_TAF_CAP)

    # ------------------------------------------------------------------
    # SHOULD component — Standard Configuration
    # ------------------------------------------------------------------

    def market_impact(self, trade: TradeSpec) -> float:
        """
        Square-root law market impact model with regime-dependent gamma.

        Formula: ΔP = Y × σ × √(Q / V)
        Where:
          Y = gamma (regime + liquidity tier dependent)
          σ = 20-day realized volatility
          Q = shares in this order
          V = average daily volume (20-day)

        Progressive scaling prevents discontinuities at ADV thresholds:
          < 0.25% ADV → no impact (slippage only)
          0.25%–1.0% ADV → linearly scaled from 0 to full impact
          > 1.0%  ADV → full impact; warn if > 2% ADV

        Blueprint reference: Section 2.5 — Market Impact (Square-Root Law)
        """
        frac = trade.order_fraction

        if frac < IMPACT_ZERO_THRESHOLD:
            return 0.0

        Y = MARKET_IMPACT_GAMMA[trade.cap_tier][trade.hmm_state]
        base_impact_per_share = Y * trade.volatility * math.sqrt(frac)
        base_impact_total     = base_impact_per_share * trade.shares * trade.price

        if frac <= IMPACT_FULL_THRESHOLD:
            # Linear ramp between zero-threshold and full-threshold
            scale = (frac - IMPACT_ZERO_THRESHOLD) / (IMPACT_FULL_THRESHOLD - IMPACT_ZERO_THRESHOLD)
            impact = scale * base_impact_total
        else:
            impact = base_impact_total
            if frac > 0.02:
                logger.warning(
                    "LARGE ORDER WARNING: %s — %.2f%% of ADV. "
                    "Consider rejecting orders >2%% ADV.",
                    trade.ticker, frac * 100,
                )

        return impact

    def borrow_fee(
        self,
        trade: TradeSpec,
        days_held: Optional[int] = None,
        annualized_rate: Optional[float] = None,
    ) -> float:
        """
        Short borrow fee for short positions.

        Defaults to tier-based rate if no specific rate supplied.
        Formula: position_value × (annualized_rate / 252) × days_held

        Blueprint reference: Section 2.4 — Short Borrow Fees (Hard-to-Borrow)
        Default ranges: Large-cap 0.5%, Mid-cap 2.0%, Small-cap 5.0% annualized
        """
        days = days_held if days_held is not None else trade.days_held
        rate = annualized_rate if annualized_rate is not None else (
            trade.borrow_rate if trade.borrow_rate is not None
            else BORROW_RATE_DEFAULTS[trade.cap_tier]
        )
        daily_rate = rate / 252
        return trade.notional * daily_rate * days

    # ------------------------------------------------------------------
    # Batch helper
    # ------------------------------------------------------------------

    def calculate_batch(self, trades: list[TradeSpec]) -> list[CostBreakdown]:
        """Calculate costs for a list of trades. Returns breakdowns in same order."""
        return [self.calculate(t) for t in trades]

    def round_trip_cost(
        self,
        ticker: str,
        shares: int,
        entry_price: float,
        exit_price: float,
        market_cap: float,
        adv: float,
        volatility: float,
        hmm_state: HMMState,
        days_held: int = 1,
    ) -> Dict[str, float]:
        """
        Calculate the full round-trip cost for a position (entry + exit).

        Returns a dict with entry_cost, exit_cost, total_cost, cost_pct.
        This is the number that matters for strategy profitability analysis.
        """
        entry_trade = TradeSpec(
            ticker=ticker, shares=shares, price=entry_price,
            direction=Direction.BUY, market_cap=market_cap,
            adv=adv, volatility=volatility, hmm_state=hmm_state,
        )
        exit_trade = TradeSpec(
            ticker=ticker, shares=shares, price=exit_price,
            direction=Direction.SELL, market_cap=market_cap,
            adv=adv, volatility=volatility, hmm_state=hmm_state,
            days_held=days_held,
        )
        entry_bd = self.calculate(entry_trade)
        exit_bd  = self.calculate(exit_trade)

        total = entry_bd.total + exit_bd.total
        avg_price = (entry_price + exit_price) / 2
        notional = shares * avg_price
        return {
            "entry_cost":  round(entry_bd.total, 4),
            "exit_cost":   round(exit_bd.total, 4),
            "total_cost":  round(total, 4),
            "cost_pct":    round(total / notional, 6),
            "cost_bps":    round(total / notional * 10_000, 2),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _log(self, trade: TradeSpec, bd: CostBreakdown) -> None:
        logger.debug(
            "Cost calc | %s %s %d@%.2f | total=$%.4f (%.2f bps) | "
            "comm=%.2f spread=%.2f slip=%.2f impact=%.2f sec=%.4f taf=%.4f",
            trade.direction.value, trade.ticker, trade.shares, trade.price,
            bd.total, bd.total_pct * 10_000,
            bd.commission, bd.spread, bd.slippage,
            bd.market_impact, bd.sec_fee, bd.taf_fee,
        )


# ---------------------------------------------------------------------------
# Module-level convenience function (matches test harness in Blueprint 12.3)
# ---------------------------------------------------------------------------

_default_model = TransactionCostModel()


def calculate_total_costs(trade_dict: dict) -> dict:
    """
    Convenience wrapper for the test harness shown in Blueprint Section 12.3.

    Accepts a plain dict (matching the test fixture format) and returns a
    flat dict with individual cost components plus a 'total' key.

    Example:
        costs = calculate_total_costs({
            'ticker': 'AAPL', 'shares': 100, 'price': 150.00,
            'direction': 'BUY', 'market_cap': 2.5e12,
            'adv': 50_000_000, 'volatility': 0.015, 'hmm_state': 'Normal'
        })
    """
    trade = TradeSpec(
        ticker     = trade_dict["ticker"],
        shares     = trade_dict["shares"],
        price      = trade_dict["price"],
        direction  = Direction(trade_dict["direction"].upper()),
        market_cap = trade_dict["market_cap"],
        adv        = trade_dict["adv"],
        volatility = trade_dict["volatility"],
        hmm_state  = HMMState(trade_dict["hmm_state"].lower()),
        days_held  = trade_dict.get("days_held", 1),
        borrow_rate= trade_dict.get("borrow_rate", None),
        gap_pcts   = trade_dict.get("gap_pcts", None),
    )
    bd = _default_model.calculate(trade)
    return {
        "commission":    bd.commission,
        "spread":        bd.spread,
        "slippage":      bd.slippage,
        "impact":        bd.market_impact,
        "sec_fee":       bd.sec_fee,
        "taf_fee":       bd.taf_fee,
        "borrow_fee":    bd.borrow_fee,
        "total":         bd.total,
        "total_pct":     bd.total_pct,
        "total_bps":     bd.total_pct * 10_000,
    }
