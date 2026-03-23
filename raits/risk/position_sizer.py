# raits/risk/position_sizer.py
#
# Three-constraint position sizing — "Layer 3: Sizing Controls"
# Blueprint ref: Section 5.3
#
# CONCEPT
# -------
# Every trade gets sized by three independent calculations. We take the
# MINIMUM — the most conservative answer. This means:
#
#   Kelly     answers: "How much should I bet given my mathematical edge?"
#   VolTarget answers: "How many shares keep my max loss under 1% of account?"
#   Limit     answers: "How many shares keep me under 20% concentration?"
#
# Each constraint catches a different failure mode:
#   - Kelly without VolTarget: could bet big on high-edge but wide-stop trade
#   - VolTarget without Limit: cheap stocks could be 100% of account
#   - Limit without Kelly:     ignores whether the edge even justifies trading
#
# By requiring ALL THREE to agree, each trade is safe from multiple angles.
#
# BOOTSTRAP VALUES
# ----------------
# Kelly requires historical win rate and win/loss ratio. In Week 10 we don't
# have real backtested trades yet, so callers pass in bootstrap values from
# the blueprint's worked example (ORB: 62% win rate, 2.25 W/L ratio).
# After Phase 1D WFO, these will be replaced with empirically derived stats.

import logging
from typing import Optional

logger = logging.getLogger('RAITS.PositionSizer')


class PositionSizer:
    """
    Computes position size using the three-constraint minimum system.

    Usage:
        sizer  = PositionSizer(account_equity=25_000)
        result = sizer.calculate(
            entry_price=178.50,
            stop_loss=174.00,
            strategy_stats={'win_rate': 0.62, 'avg_win': 4.50, 'avg_loss': 2.00}
        )
        if result:
            shares = result['shares']
    """

    def __init__(self, account_equity: float,
                 max_risk_pct: float = 0.01,
                 max_position_pct: float = 0.20,
                 kelly_fraction: float = 0.5):
        """
        Parameters
        ----------
        account_equity    : float — current account value ($25,000 default)
        max_risk_pct      : float — max loss per trade as % of account (default 1%)
        max_position_pct  : float — max position as % of account (default 20%)
        kelly_fraction    : float — Kelly multiplier (0.5 = half-Kelly, industry standard)
        """
        self.account_equity   = account_equity
        self.max_risk_pct     = max_risk_pct
        self.max_position_pct = max_position_pct
        self.kelly_fraction   = kelly_fraction

    # ──────────────────────────────────────────────────────────────────────────
    # CONSTRAINT 1: Kelly Criterion
    # ──────────────────────────────────────────────────────────────────────────

    def calculate_kelly_fraction(self, strategy_stats: dict) -> float:
        """
        Compute the Half-Kelly fraction from strategy win/loss statistics.

        Blueprint formula:
            b = avg_win / avg_loss          (win-to-loss ratio)
            f = (p×b - q) / b               (full Kelly fraction)
            half_kelly = f × 0.5            (apply Kelly multiplier)

        Where p = win_rate, q = 1 - win_rate.

        Returns 0.0 if Kelly is negative (strategy has no edge).
        Returns the half-Kelly fraction (a number between 0 and ~0.5).
        """
        p = strategy_stats['win_rate']
        q = 1.0 - p
        b = strategy_stats['avg_win'] / strategy_stats['avg_loss']

        full_kelly = (p * b - q) / b

        if full_kelly <= 0:
            # Negative Kelly means expected value is negative.
            # The math is telling us not to trade.
            logger.debug(f"Kelly is negative ({full_kelly:.4f}) — no edge detected")
            return 0.0

        half_kelly = full_kelly * self.kelly_fraction
        logger.debug(f"Kelly: p={p:.2f}, b={b:.2f}, full={full_kelly:.4f}, half={half_kelly:.4f}")
        return half_kelly

    def calculate_kelly_shares(self, entry_price: float,
                                strategy_stats: dict) -> int:
        """
        Convert Kelly fraction to a whole number of shares.

        capital = account_equity × half_kelly_fraction
        shares  = int(capital / entry_price)
        """
        fraction = self.calculate_kelly_fraction(strategy_stats)
        if fraction <= 0:
            return 0

        capital = self.account_equity * fraction
        shares  = int(capital / entry_price)
        logger.debug(f"Kelly shares: capital=${capital:.2f}, price=${entry_price:.2f}, "
                     f"shares={shares}")
        return shares

    # ──────────────────────────────────────────────────────────────────────────
    # CONSTRAINT 2: Volatility Targeting
    # ──────────────────────────────────────────────────────────────────────────

    def calculate_vol_target_shares(self, entry_price: float,
                                     stop_loss: float) -> int:
        """
        Cap maximum loss per trade at max_risk_pct of account.

        max_risk_dollars = account_equity × max_risk_pct  (default: $250)
        risk_per_share   = abs(entry_price - stop_loss)
        shares           = int(max_risk_dollars / risk_per_share)

        abs() is critical: for SHORT trades, stop_loss > entry_price.
        Without abs(), risk_per_share would be negative.
        """
        max_risk_dollars = self.account_equity * self.max_risk_pct
        risk_per_share   = abs(entry_price - stop_loss)

        if risk_per_share <= 0:
            logger.warning("Risk per share is zero — entry equals stop. Returning 0.")
            return 0

        shares = int(max_risk_dollars / risk_per_share)
        logger.debug(f"VolTarget shares: max_risk=${max_risk_dollars:.2f}, "
                     f"risk/share=${risk_per_share:.2f}, shares={shares}")
        return shares

    # ──────────────────────────────────────────────────────────────────────────
    # CONSTRAINT 3: Position Size Limit
    # ──────────────────────────────────────────────────────────────────────────

    def calculate_position_limit_shares(self, entry_price: float) -> int:
        """
        Cap maximum position value at max_position_pct of account.

        max_position_value = account_equity × max_position_pct  (default: $5,000)
        shares             = int(max_position_value / entry_price)
        """
        max_value = self.account_equity * self.max_position_pct
        shares    = int(max_value / entry_price)
        logger.debug(f"Limit shares: max_value=${max_value:.2f}, "
                     f"price=${entry_price:.2f}, shares={shares}")
        return shares

    # ──────────────────────────────────────────────────────────────────────────
    # MASTER METHOD: three-way minimum
    # ──────────────────────────────────────────────────────────────────────────

    def calculate(self, entry_price: float, stop_loss: float,
                  strategy_stats: dict) -> Optional[dict]:
        """
        Compute final position size as the minimum of all three constraints.

        Returns None if:
          - Kelly is zero/negative (no edge — don't trade)
          - Final shares < 1 (position too small to execute)

        Returns a dict with full breakdown for logging and diagnostics:
            shares              : int   — final position size
            position_value      : float — shares × entry_price
            risk_dollars        : float — shares × risk_per_share
            risk_pct            : float — risk_dollars / account_equity
            kelly_shares        : int
            vol_target_shares   : int
            position_limit_shares : int
            limiting_factor     : str  — which constraint was smallest
        """
        kelly_shares  = self.calculate_kelly_shares(entry_price, strategy_stats)
        vol_shares    = self.calculate_vol_target_shares(entry_price, stop_loss)
        limit_shares  = self.calculate_position_limit_shares(entry_price)

        # Negative Kelly = no edge = no trade
        if kelly_shares == 0:
            logger.info("Position sizing: REJECTED — Kelly=0 (no edge detected)")
            return None

        # Three-way minimum
        final_shares = min(kelly_shares, vol_shares, limit_shares)

        if final_shares < 1:
            logger.info(f"Position sizing: REJECTED — final_shares={final_shares} < 1")
            return None

        # Determine which constraint was the binding factor.
        # Tie-break order: VolTarget > Limit > Kelly (most operationally meaningful).
        min_val = min(kelly_shares, vol_shares, limit_shares)
        if vol_shares == min_val:
            limiting_factor = 'VOLATILITY_TARGET'
        elif limit_shares == min_val:
            limiting_factor = 'POSITION_LIMIT'
        else:
            limiting_factor = 'KELLY_CRITERION'

        risk_per_share  = abs(entry_price - stop_loss)
        position_value  = final_shares * entry_price
        risk_dollars    = final_shares * risk_per_share
        risk_pct        = risk_dollars / self.account_equity

        result = {
            'shares':                 final_shares,
            'position_value':         round(position_value, 2),
            'risk_dollars':           round(risk_dollars, 2),
            'risk_pct':               round(risk_pct, 6),
            'kelly_shares':           kelly_shares,
            'vol_target_shares':      vol_shares,
            'position_limit_shares':  limit_shares,
            'limiting_factor':        limiting_factor,
        }

        logger.info(
            f"Position size: {final_shares} shares | "
            f"value=${position_value:.2f} | risk=${risk_dollars:.2f} ({risk_pct:.2%}) | "
            f"binding={limiting_factor} | "
            f"[Kelly={kelly_shares}, Vol={vol_shares}, Limit={limit_shares}]"
        )

        return result
