# tests/integration/test_orb_integration.py
#
# ORB integration tests — Phase 1B Week 10
#
# These tests verify the complete ORB pipeline:
#   Scanner → OR formation → Signal → Position sizing → Entry → Exit
#
# The MOST CRITICAL rule tested here:
#   "Entry occurs at NEXT BAR OPEN after signal confirmation"
#   (Blueprint Section 1, "Key Methodological Clarifications")
#
# This is NOT tested in unit tests (which crop bars at the signal candle).
# Integration tests provide the full day's bar stream so we can verify
# the replayer correctly uses the 9:47 open, not the 9:46 close.
#
# Run with: python -m unittest tests.integration.test_orb_integration -v
# Target:   8/8 passing

import unittest
from raits.backtester.orb_session import run_orb_session
from tests.fixtures.session_fixtures import (
    LONG_TRADE_HITS_TARGET,
    LONG_TRADE_HITS_STOP,
    NO_SIGNAL_STRESS_REGIME,
)
from tests.fixtures.position_fixtures import ORB_STATS, ACCOUNT_EQUITY


class TestORBSessionReplay(unittest.TestCase):
    """
    run_orb_session(bars, context) replays a full trading day bar by bar
    and returns a list of trades executed (may be empty).

    Each trade dict contains:
        ticker          : str
        direction       : 'LONG' or 'SHORT'
        entry_price     : float  — NEXT BAR OPEN after signal
        entry_time      : str    — timestamp of entry bar
        exit_price      : float
        exit_time       : str
        exit_reason     : 'TARGET_HIT' | 'STOP_HIT' | 'TIME_EXIT'
        shares          : int
        pnl             : float  — (exit - entry) × shares for LONG
        or_high         : float
        or_low          : float
    """

    def _run(self, fixture, hmm_state='Normal'):
        """Helper: run a session fixture and return trades list."""
        state = fixture.get('hmm_state_override', hmm_state)
        context = {
            'ticker':               fixture['ticker'],
            'prev_close':           fixture['prev_close'],
            'premarket_volume':     fixture['premarket_volume'],
            'avg_daily_volume':     fixture['avg_daily_volume'],
            'opening_5min_volume':  fixture['opening_5min_volume'],
            'atr':                  fixture['atr'],
            'vwap':                 fixture['vwap_at_9_46'],
            'hist_avg_vol_9_46':    fixture['hist_avg_vol_9_46'],
            'hmm_state':            state,
            'account_equity':       ACCOUNT_EQUITY,
            'strategy_stats':       ORB_STATS,
        }
        return run_orb_session(fixture['bars'], context)

    # ── Critical rule: next-bar-open entry ───────────────────────────────────

    def test_entry_is_at_next_bar_open_not_signal_close(self):
        """
        THE most important integration test.

        Signal fires on 9:46 bar (close=$104.70).
        Entry MUST be at 9:47 bar OPEN ($104.80), NOT $104.70.

        Blueprint: "All entries occur at NEXT BAR OPEN after signal confirmation"

        If this fails, the backtest is lying — it's assuming fills at prices
        that are only available if you had a time machine.
        """
        trades = self._run(LONG_TRADE_HITS_TARGET)

        self.assertEqual(len(trades), 1, "Should produce exactly one trade")
        trade = trades[0]

        # The signal bar closes at $104.70. The NEXT bar opens at $104.80.
        self.assertAlmostEqual(
            trade['entry_price'], 104.80, places=2,
            msg="Entry must be at 9:47 OPEN ($104.80), not signal close ($104.70)"
        )
        self.assertEqual(trade['entry_time'], '09:47',
                         "Entry must be timestamped to the 9:47 bar")

    # ── Target exit ───────────────────────────────────────────────────────────

    def test_trade_exits_at_target(self):
        """
        When price reaches the 2R target, the trade closes at exactly the
        target price (not the bar close, not the bar high).
        """
        f = LONG_TRADE_HITS_TARGET
        trades = self._run(f)

        self.assertEqual(len(trades), 1)
        trade = trades[0]

        self.assertAlmostEqual(trade['exit_price'], f['expected_exit_price'], places=2)
        self.assertEqual(trade['exit_reason'], 'TARGET_HIT')
        self.assertEqual(trade['exit_time'], f['expected_exit_time'])

    def test_long_pnl_is_positive_on_target_hit(self):
        """
        P&L for a long trade that hits target must be positive.
        pnl = (exit - entry) × shares = ($109.40 - $104.80) × shares
        """
        trades = self._run(LONG_TRADE_HITS_TARGET)
        self.assertEqual(len(trades), 1)
        self.assertGreater(trades[0]['pnl'], 0, "Target hit should produce positive P&L")

    # ── Stop exit ─────────────────────────────────────────────────────────────

    def test_trade_exits_at_stop(self):
        """
        When bar low touches the stop level, trade closes at exactly stop price.
        Exit price = $102.50 (the stop), not the bar low ($102.45).
        """
        f = LONG_TRADE_HITS_STOP
        trades = self._run(f)

        self.assertEqual(len(trades), 1)
        trade = trades[0]

        self.assertAlmostEqual(trade['exit_price'], f['expected_exit_price'], places=2,
                               msg="Stop exit should be at stop price, not bar low")
        self.assertEqual(trade['exit_reason'], 'STOP_HIT')

    def test_long_pnl_is_negative_on_stop_hit(self):
        """A stop-out on a long trade must produce negative P&L."""
        trades = self._run(LONG_TRADE_HITS_STOP)
        self.assertEqual(len(trades), 1)
        self.assertLess(trades[0]['pnl'], 0, "Stop hit should produce negative P&L")

    # ── Regime gate ───────────────────────────────────────────────────────────

    def test_no_trades_in_stress_regime(self):
        """
        Even a perfect setup produces zero trades when hmm_state='Stress'.
        The regime gate fires before any signal logic.
        """
        trades = self._run(NO_SIGNAL_STRESS_REGIME)
        self.assertEqual(len(trades), 0,
                         "Stress regime must produce zero ORB trades")

    # ── Trade record completeness ─────────────────────────────────────────────

    def test_trade_record_contains_all_fields(self):
        """All downstream components (cost model, analytics) expect these keys."""
        trades = self._run(LONG_TRADE_HITS_TARGET)
        self.assertEqual(len(trades), 1)
        trade = trades[0]

        required_fields = {
            'ticker', 'direction', 'entry_price', 'entry_time',
            'exit_price', 'exit_time', 'exit_reason',
            'shares', 'pnl', 'or_high', 'or_low',
        }
        for field in required_fields:
            self.assertIn(field, trade, f"Trade record missing field: '{field}'")

    def test_shares_are_positive_integer(self):
        """
        Position size must be a positive integer.
        Fractional shares don't exist in US equities.
        """
        trades = self._run(LONG_TRADE_HITS_TARGET)
        self.assertEqual(len(trades), 1)
        shares = trades[0]['shares']
        self.assertIsInstance(shares, int, "Shares must be an integer")
        self.assertGreater(shares, 0, "Shares must be positive")


if __name__ == '__main__':
    unittest.main(verbosity=2)
