# tests/test_cash_defense.py
#
# Cash/Defense mode test suite — Phase 1B Week 15
#
# Blueprint ref: Section 4.5 "Strategy 4: Cash/Defense - Safety Mode"
#
# Run with: python -m unittest tests.test_cash_defense -v
# Target:   18/18 passing
#
# Test class structure:
#   TestActivation         (5 tests)  — when/why the mode activates
#   TestDeactivation       (4 tests)  — when/why the mode deactivates
#   TestLiquidationOrders  (5 tests)  — structure and content of liquidation orders
#   TestStateMachine       (4 tests)  — idempotency and transition edge cases

import unittest

from raits.strategies.cash_defense import CashDefenseMode
from tests.fixtures.cash_defense_fixtures import (
    ACTIVATE_WITH_POSITIONS,
    ACTIVATE_NO_POSITIONS,
    NO_ACTIVATE_CALM,
    NO_ACTIVATE_NORMAL,
    DEACTIVATE_CALM_RETURNS,
    DEACTIVATE_NORMAL_RETURNS,
    REMAIN_ACTIVE_STRESS_CONTINUES,
    LIQUIDATION_ORDER_STRUCTURE,
    LIQUIDATION_SHORT_POSITION,
    IDEMPOTENT_ACTIVATION,
    DEACTIVATE_WHEN_NOT_ACTIVE,
    POSITION_TSLA,
    POSITION_AAPL,
    TWO_POSITIONS,
    THREE_POSITIONS,
    NO_POSITIONS,
)


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 1: Activation
# Blueprint ref: Section 4.5 "Emergency Actions"
# ─────────────────────────────────────────────────────────────────────────────

class TestActivation(unittest.TestCase):
    """
    evaluate(hmm_state, open_positions) is the main entry point.
    It checks the regime and activates if Stress.

    Returns a result dict:
        active             : bool
        liquidation_orders : list[dict]  — one per open position (may be empty)
        reason             : str or None
    """

    def setUp(self):
        self.mode = CashDefenseMode()

    def test_activates_on_stress_with_positions(self):
        """
        Blueprint: "Trigger: HMM detects Stress regime"
        Stress + open positions → activate and return liquidation orders.
        """
        f = ACTIVATE_WITH_POSITIONS
        result = self.mode.evaluate(f['hmm_state'], f['open_positions'])
        self.assertTrue(result['active'],
                        "Stress regime should activate Cash/Defense mode")

    def test_liquidation_count_matches_position_count(self):
        """
        Blueprint: "Close all existing positions IMMEDIATELY"
        One liquidation order per open position — no more, no less.
        """
        f = ACTIVATE_WITH_POSITIONS
        result = self.mode.evaluate(f['hmm_state'], f['open_positions'])
        self.assertEqual(len(result['liquidation_orders']),
                         f['expected_liquidations'],
                         "Should produce one liquidation order per open position")

    def test_activates_stress_with_no_positions(self):
        """
        Stress regime with no open positions → still activates (blocks new entries),
        but liquidation_orders is empty (nothing to close).
        """
        f = ACTIVATE_NO_POSITIONS
        result = self.mode.evaluate(f['hmm_state'], f['open_positions'])
        self.assertTrue(result['active'])
        self.assertEqual(len(result['liquidation_orders']), 0)

    def test_does_not_activate_on_calm(self):
        """
        Blueprint: Cash/Defense only triggers on Stress.
        Calm regime = normal conditions, all strategies can run.
        """
        f = NO_ACTIVATE_CALM
        result = self.mode.evaluate(f['hmm_state'], f['open_positions'])
        self.assertFalse(result['active'],
                         "Calm regime should NOT activate Cash/Defense")

    def test_does_not_activate_on_normal(self):
        """
        Normal regime = some trend, but not a crash. Strategies still run.
        Only Stress triggers the emergency mode.
        """
        f = NO_ACTIVATE_NORMAL
        result = self.mode.evaluate(f['hmm_state'], f['open_positions'])
        self.assertFalse(result['active'],
                         "Normal regime should NOT activate Cash/Defense")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 2: Deactivation
# Blueprint ref: Section 4.5 "Exit Condition"
# ─────────────────────────────────────────────────────────────────────────────

class TestDeactivation(unittest.TestCase):
    """
    Once active, the mode deactivates when HMM returns to Calm or Normal.

    Note: deactivation does NOT produce new orders — the system simply
    resumes normal strategy routing. There are no positions to close
    (they were all liquidated on activation).
    """

    def setUp(self):
        self.mode = CashDefenseMode()
        # Pre-activate: put the mode in Stress state
        self.mode.evaluate('Stress', TWO_POSITIONS)

    def test_deactivates_when_calm_returns(self):
        """
        Blueprint: "Returns to normal trading when HMM state returns to Calm"
        """
        result = self.mode.evaluate('Calm', NO_POSITIONS)
        self.assertFalse(result['active'],
                         "Calm regime should deactivate Cash/Defense mode")

    def test_deactivates_when_normal_returns(self):
        """
        Blueprint: "Returns to normal trading when HMM state returns to Normal"
        """
        result = self.mode.evaluate('Normal', NO_POSITIONS)
        self.assertFalse(result['active'],
                         "Normal regime should deactivate Cash/Defense mode")

    def test_remains_active_while_stress_continues(self):
        """
        If Stress regime continues, mode stays active.
        No new liquidation orders (positions already closed).
        """
        result = self.mode.evaluate('Stress', NO_POSITIONS)
        self.assertTrue(result['active'],
                        "Should remain active while Stress regime continues")

    def test_deactivation_produces_no_new_liquidation_orders(self):
        """
        When deactivating, we don't need to close positions — they were
        already closed when we activated. The result should have no orders.
        """
        result = self.mode.evaluate('Calm', NO_POSITIONS)
        self.assertEqual(len(result['liquidation_orders']), 0,
                         "Deactivation should not produce liquidation orders")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 3: Liquidation order structure
# Blueprint ref: Section 4.5 "Close all existing positions IMMEDIATELY"
# ─────────────────────────────────────────────────────────────────────────────

class TestLiquidationOrders(unittest.TestCase):
    """
    Each liquidation order must be a complete, actionable instruction
    for the backtester (and eventually the broker in Phase 2/3).
    """

    def setUp(self):
        self.mode = CashDefenseMode()

    def test_liquidation_order_contains_required_fields(self):
        """
        The backtester downstream needs these keys to process the order.
        Missing any = KeyError.
        """
        f = LIQUIDATION_ORDER_STRUCTURE
        result = self.mode.evaluate(f['hmm_state'], f['open_positions'])
        self.assertEqual(len(result['liquidation_orders']), 1)
        order = result['liquidation_orders'][0]
        for key in f['required_keys']:
            self.assertIn(key, order,
                          f"Liquidation order missing required field: '{key}'")

    def test_liquidation_uses_market_orders(self):
        """
        Blueprint: "order_type='MARKET' — accept slippage for execution speed"
        During a crash, getting OUT is more important than price.
        Limit orders might not fill. Market orders always fill.
        """
        f = LIQUIDATION_ORDER_STRUCTURE
        result = self.mode.evaluate(f['hmm_state'], f['open_positions'])
        order = result['liquidation_orders'][0]
        self.assertEqual(order['order_type'], 'MARKET',
                         "Liquidation must use MARKET orders (not LIMIT)")

    def test_long_position_generates_sell_order(self):
        """
        To close a LONG position, we must SELL.
        TSLA is LONG → close direction = SELL.
        """
        result = self.mode.evaluate('Stress', [POSITION_TSLA])
        order = result['liquidation_orders'][0]
        self.assertEqual(order['direction'], 'SELL',
                         "LONG position should produce SELL liquidation order")

    def test_short_position_generates_buy_order(self):
        """
        To close a SHORT position, we must BUY to cover.
        AAPL is SHORT → close direction = BUY.
        """
        result = self.mode.evaluate('Stress', [POSITION_AAPL])
        order = result['liquidation_orders'][0]
        self.assertEqual(order['direction'], 'BUY',
                         "SHORT position should produce BUY liquidation order")

    def test_liquidation_preserves_share_count(self):
        """
        Liquidation order must close the EXACT number of shares held.
        Not partial, not rounded — every share must be accounted for.
        """
        result = self.mode.evaluate('Stress', [POSITION_TSLA])
        order = result['liquidation_orders'][0]
        self.assertEqual(order['shares'], POSITION_TSLA['shares'],
                         "Liquidation must close exact share count")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 4: State machine
# Blueprint ref: Section 4.5 + Section 6.3 "Regime Coordination Protocol"
# ─────────────────────────────────────────────────────────────────────────────

class TestStateMachine(unittest.TestCase):
    """
    CashDefenseMode is stateful. The same input can produce different outputs
    depending on whether the mode is currently active.

    Key properties:
      - is_active()   : bool — current state
      - Activation is idempotent (calling twice does not double-liquidate)
      - Deactivation when already inactive is a no-op
    """

    def setUp(self):
        self.mode = CashDefenseMode()

    def test_initially_not_active(self):
        """Mode starts inactive — no Stress at system startup."""
        self.assertFalse(self.mode.is_active(),
                         "Mode should start in inactive state")

    def test_is_active_after_stress(self):
        """After evaluating Stress, is_active() returns True."""
        self.mode.evaluate('Stress', NO_POSITIONS)
        self.assertTrue(self.mode.is_active())

    def test_activation_is_idempotent(self):
        """
        Calling evaluate('Stress', positions) twice must not produce
        double liquidations on the second call.

        First call: positions exist → liquidate them
        Second call: no new positions → no new liquidations

        This guards against the replayer calling evaluate() every bar
        while already in Safety Mode.
        """
        # First activation — positions exist
        result1 = self.mode.evaluate('Stress', TWO_POSITIONS)
        self.assertEqual(len(result1['liquidation_orders']), 2)

        # Second activation — already active, no new positions
        result2 = self.mode.evaluate('Stress', NO_POSITIONS)
        self.assertEqual(len(result2['liquidation_orders']), 0,
                         "Second Stress evaluation should not re-liquidate")

    def test_deactivate_when_not_active_is_noop(self):
        """
        Calling evaluate('Calm') when not active should not raise
        an error and should return active=False cleanly.
        """
        result = self.mode.evaluate('Calm', NO_POSITIONS)
        self.assertFalse(result['active'])
        self.assertEqual(len(result['liquidation_orders']), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
