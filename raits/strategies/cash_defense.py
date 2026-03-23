# raits/strategies/cash_defense.py
#
# Cash/Defense Mode — "Safety Mode"
#
# Blueprint ref: Section 4.5
# Trigger:      HMM detects Stress regime (any time during market hours)
# Active period: Any time — overrides all other strategies immediately
# Max positions: 0 — liquidate everything, block all new entries
#
# ──────────────────────────────────────────────────────────────────────────────
# WHY THIS IS ARCHITECTURALLY DIFFERENT FROM THE OTHER THREE STRATEGIES
# ──────────────────────────────────────────────────────────────────────────────
#
# ORB, VWAP MR, and Trend Follow are SIGNAL GENERATORS:
#   Input:  price bars + regime
#   Output: signal dict or None
#   State:  mostly stateless per call
#
# Cash/Defense is a SYSTEM STATE CONTROLLER:
#   Input:  HMM regime + list of open positions
#   Output: activation status + liquidation orders
#   State:  binary active/inactive, PERSISTS between calls
#
# This statefulness is essential. The mode is called every bar while Stress
# is active. On the first call it produces liquidation orders. On subsequent
# calls (when already active and positions are gone) it must NOT produce
# duplicate orders. The `_active` flag enables this idempotent behaviour.
#
# ──────────────────────────────────────────────────────────────────────────────
# THE SINGLE METHOD: evaluate()
# ──────────────────────────────────────────────────────────────────────────────
#
# The Master Strategy Router (Phase 1C) calls this BEFORE checking any other
# strategy. If evaluate() returns active=True, the router skips ORB, VWAP MR,
# and Trend Follow entirely and processes the liquidation orders instead.
#
# This is the "Safety Mode overrides everything" rule from Section 4.6:
#
#   def resolve_signal_conflicts(stock, signals):
#       if 'SAFETY_MODE' in signals:
#           return signals['SAFETY_MODE'], 'Safety mode activated'
#       ...

import logging
from typing import Optional

logger = logging.getLogger('RAITS.CashDefense')

# The only regime that triggers Cash/Defense mode
STRESS_REGIME = 'Stress'

# Regimes that allow return to normal trading
NORMAL_REGIMES = {'Calm', 'Normal'}


class CashDefenseMode:
    """
    Cash/Defense safety mode controller.

    Usage (Master Strategy Router):
        defense = CashDefenseMode()

        # Called every bar, before all other strategy checks
        result = defense.evaluate(hmm_state, open_positions)

        if result['active']:
            # Process liquidation orders, skip all other strategies
            for order in result['liquidation_orders']:
                backtester.execute_market_order(order)
            return  # nothing else to do this bar
        else:
            # Normal routing — check ORB, VWAP MR, Trend Follow
            ...
    """

    def __init__(self):
        # The single piece of state: are we currently in Safety Mode?
        self._active: bool = False

    def is_active(self) -> bool:
        """Return current Safety Mode state."""
        return self._active

    def evaluate(self, hmm_state: str, open_positions: list) -> dict:
        """
        Evaluate the current HMM regime and return an action result.

        This is the single entry point. The router calls it every bar.

        DECISION LOGIC:
          If Stress and NOT currently active:
            → Activate: set _active=True, generate liquidation orders
          If Stress and ALREADY active:
            → Stay active: no new liquidation orders (idempotent)
          If Calm or Normal and active:
            → Deactivate: set _active=False, no orders
          If Calm or Normal and not active:
            → Stay inactive: no-op

        Parameters
        ----------
        hmm_state      : str   — 'Calm', 'Normal', or 'Stress'
        open_positions : list  — current open position dicts
                                 (from session replayer, each has:
                                  ticker, direction, shares, entry_price, strategy)

        Returns
        -------
        dict:
            active             : bool       — is Safety Mode currently active?
            liquidation_orders : list[dict] — orders to execute (may be empty)
            reason             : str|None   — why the state changed (or None)
        """

        # ── Case 1: Stress detected ───────────────────────────────────────────
        if hmm_state == STRESS_REGIME:

            if not self._active:
                # First time we're seeing Stress — ACTIVATE
                self._active = True
                orders = self._build_liquidation_orders(open_positions)

                logger.critical(
                    f"🚨 CASH/DEFENSE ACTIVATED | "
                    f"regime={hmm_state} | "
                    f"positions_to_close={len(open_positions)} | "
                    f"orders_generated={len(orders)}"
                )

                return {
                    'active':             True,
                    'liquidation_orders': orders,
                    'reason':             'HMM_STRESS',
                }

            else:
                # Already active — idempotent: no new orders
                # (positions were already closed on first activation)
                logger.debug("Cash/Defense: already active in Stress regime — no new orders")
                return {
                    'active':             True,
                    'liquidation_orders': [],
                    'reason':             None,
                }

        # ── Case 2: Regime normalised (Calm or Normal) ────────────────────────
        elif hmm_state in NORMAL_REGIMES:

            if self._active:
                # Transitioning OUT of Safety Mode
                self._active = False

                logger.info(
                    f"✅ CASH/DEFENSE DEACTIVATED | "
                    f"regime={hmm_state} — returning to normal trading"
                )

                return {
                    'active':             False,
                    'liquidation_orders': [],  # positions were closed on activation
                    'reason':             'REGIME_NORMALIZED',
                }

            else:
                # Already inactive — no-op
                return {
                    'active':             False,
                    'liquidation_orders': [],
                    'reason':             None,
                }

        # ── Case 3: Unknown regime (defensive guard) ──────────────────────────
        else:
            logger.warning(f"Cash/Defense: unknown hmm_state='{hmm_state}' — "
                           f"treating as safe (not activating)")
            return {
                'active':             self._active,
                'liquidation_orders': [],
                'reason':             None,
            }

    # ──────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPER
    # ──────────────────────────────────────────────────────────────────────────

    def _build_liquidation_orders(self, open_positions: list) -> list:
        """
        Build one MARKET liquidation order for each open position.

        Closing direction:
            LONG  position → SELL  (sell shares to close)
            SHORT position → BUY   (buy shares to cover)

        Blueprint: "order_type=MARKET — accept slippage for execution speed"
        During a crash we cannot wait for limit fills. Getting flat immediately
        is worth the slippage cost.

        Parameters
        ----------
        open_positions : list[dict]
            Each position dict must have: ticker, direction, shares

        Returns
        -------
        list[dict] — one order per position
        """
        orders = []

        for pos in open_positions:
            # Closing direction is the opposite of position direction
            if pos['direction'] == 'LONG':
                close_direction = 'SELL'
            else:  # SHORT
                close_direction = 'BUY'

            order = {
                'ticker':     pos['ticker'],
                'direction':  close_direction,
                'shares':     pos['shares'],
                'order_type': 'MARKET',
                'reason':     'Emergency liquidation — Stress regime detected',
            }

            logger.info(
                f"Liquidation order: {close_direction} {pos['shares']} "
                f"{pos['ticker']} @ MARKET "
                f"(was {pos['direction']} from {pos['strategy']})"
            )

            orders.append(order)

        return orders
