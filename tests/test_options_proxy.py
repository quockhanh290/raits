"""
tests/test_options_proxy.py
----------------------------
TDD test suite for options_proxy_analysis.py

Run:  python -m pytest tests/test_options_proxy.py -v
      (from d:\\raits)

Test classes:
  TestBlackScholes    (7 tests) — bs_call / bs_put / put-call parity / expiry boundaries
  TestReconcileGross  (3 tests) — STEP 0 gate
  TestAnalyzeTrade    (3 tests) — per-trade option analysis integration
"""
import math
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

# Add the script directory so the standalone script is importable
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "raits" / "raits" / "scripts"))

from options_proxy_analysis import (
    analyze_trade_option,
    bs_call,
    bs_put,
    reconcile_gross,
)


# ── Black-Scholes ─────────────────────────────────────────────────────────────

class TestBlackScholes(unittest.TestCase):

    def test_bs_call_atm_1yr(self):
        """ATM call T=1yr r=5% σ=20% — textbook value ≈ $10.45."""
        result = bs_call(100.0, 100.0, 1.0, 0.05, 0.20)
        self.assertAlmostEqual(result, 10.4506, delta=0.01)

    def test_bs_put_atm_1yr(self):
        """ATM put T=1yr r=5% σ=20% — textbook value ≈ $5.57."""
        result = bs_put(100.0, 100.0, 1.0, 0.05, 0.20)
        self.assertAlmostEqual(result, 5.5724, delta=0.01)

    def test_put_call_parity(self):
        """C - P = S - K·exp(-rT) for arbitrary inputs."""
        S, K, T, r, sigma = 95.0, 100.0, 0.5, 0.04, 0.25
        C = bs_call(S, K, T, r, sigma)
        P = bs_put(S, K, T, r, sigma)
        parity = S - K * math.exp(-r * T)
        self.assertAlmostEqual(C - P, parity, places=6)

    def test_bs_call_expiry_itm(self):
        """Call at T=0: intrinsic value max(S-K, 0) for ITM."""
        self.assertAlmostEqual(bs_call(110.0, 100.0, 0.0, 0.05, 0.20), 10.0, delta=1e-9)

    def test_bs_call_expiry_otm(self):
        """Call at T=0: 0 for OTM."""
        self.assertEqual(bs_call(90.0, 100.0, 0.0, 0.05, 0.20), 0.0)

    def test_bs_put_expiry_itm(self):
        """Put at T=0: intrinsic value max(K-S, 0) for ITM."""
        self.assertAlmostEqual(bs_put(90.0, 100.0, 0.0, 0.05, 0.20), 10.0, delta=1e-9)

    def test_bs_put_expiry_otm(self):
        """Put at T=0: 0 for OTM."""
        self.assertEqual(bs_put(110.0, 100.0, 0.0, 0.05, 0.20), 0.0)


# ── Reconciliation gate ───────────────────────────────────────────────────────

class TestReconcileGross(unittest.TestCase):

    def test_all_match(self):
        df = pd.DataFrame({
            "direction":   ["LONG",  "SHORT"],
            "shares":      [100,     50],
            "entry_price": [50.0,    55.0],
            "exit_price":  [55.0,    50.0],
            "gross_pnl":   [500.0,   250.0],   # correct
        })
        n_match, n_mismatch, total = reconcile_gross(df)
        self.assertEqual(n_match, 2)
        self.assertEqual(n_mismatch, 0)
        self.assertEqual(total, 2)

    def test_detects_mismatch(self):
        df = pd.DataFrame({
            "direction":   ["LONG"],
            "shares":      [100],
            "entry_price": [50.0],
            "exit_price":  [55.0],
            "gross_pnl":   [999.0],   # wrong — should be 500
        })
        n_match, n_mismatch, _ = reconcile_gross(df)
        self.assertEqual(n_mismatch, 1)
        self.assertEqual(n_match, 0)

    def test_short_direction_sign(self):
        """SHORT: gross = shares × (entry - exit) > 0 when price falls."""
        df = pd.DataFrame({
            "direction":   ["SHORT"],
            "shares":      [200],
            "entry_price": [100.0],
            "exit_price":  [95.0],
            "gross_pnl":   [1000.0],   # 200 × (100 - 95) = 1000
        })
        n_match, n_mismatch, _ = reconcile_gross(df)
        self.assertEqual(n_match, 1)
        self.assertEqual(n_mismatch, 0)


# ── Per-trade option analysis ─────────────────────────────────────────────────

class TestAnalyzeTrade(unittest.TestCase):

    def _make_row(self, direction="LONG", entry=100.0, exit_price=105.0,
                  shares=20, hold_days=5, net_pnl=48.0,
                  entry_ts="2021-01-04 09:35"):
        entry_time = pd.Timestamp(entry_ts)
        return {
            "ticker":      "AAPL",
            "direction":   direction,
            "entry_price": entry,
            "exit_price":  exit_price,
            "entry_time":  entry_time,
            "exit_time":   entry_time + pd.Timedelta(days=hold_days),
            "shares":      shares,
            "net_pnl":     net_pnl,
        }

    def test_long_profitable_move(self):
        """LONG, underlying +10% in 2 days: option should be profitable."""
        row = self._make_row(direction="LONG", entry=100.0, exit_price=110.0,
                             shares=20, hold_days=2, net_pnl=48.0)
        res = analyze_trade_option(
            row, dte=21, skew=1.0, iv_fallback=0.35,
            rate=0.04, spread=0.05, price_cache={}
        )

        self.assertEqual(res["iv_source"], "fallback")
        self.assertAlmostEqual(res["iv"], 0.35)
        self.assertEqual(res["holding_calendar_days"], 2)
        self.assertGreater(res["entry_premium"], 0)
        # ITM call should be worth more than ATM call at entry
        self.assertGreater(res["exit_premium"], res["entry_premium"])
        self.assertGreater(res["contracts"], 0)
        self.assertGreater(res["option_gross"], 0)
        self.assertFalse(res["theta_dominated"])
        self.assertFalse(res["zero_contracts"])

    def test_short_profitable_move(self):
        """SHORT, underlying -10% in 2 days: put should be profitable."""
        row = self._make_row(direction="SHORT", entry=100.0, exit_price=90.0,
                             shares=20, hold_days=2, net_pnl=48.0)
        res = analyze_trade_option(
            row, dte=21, skew=1.0, iv_fallback=0.35,
            rate=0.04, spread=0.05, price_cache={}
        )
        # Deeper ITM put should be worth more than ATM put at entry
        self.assertGreater(res["exit_premium"], res["entry_premium"])
        self.assertGreater(res["option_gross"], 0)

    def test_theta_dominated(self):
        """Stock ekes out a small win over 15 days while theta decimates the option."""
        row = {
            "ticker":      "AAPL",
            "direction":   "LONG",
            "entry_price": 100.0,
            "exit_price":  100.50,   # tiny bullish move
            "entry_time":  pd.Timestamp("2021-01-04 09:35"),
            "exit_time":   pd.Timestamp("2021-01-19 09:35"),  # 15 calendar days
            "shares":      100,
            "net_pnl":     3.0,       # stock wins by $3
        }
        # DTE=21, hold=15 → T_exit = 6/365 ≈ 0.0164; ATM call decays heavily
        res = analyze_trade_option(
            row, dte=21, skew=1.0, iv_fallback=0.30,
            rate=0.04, spread=0.05, price_cache={}
        )
        self.assertEqual(res["holding_calendar_days"], 15)
        self.assertTrue(
            res["theta_dominated"],
            f"Expected theta_dominated but option_net={res['option_net']:.2f}, "
            f"stock net_pnl=3.0",
        )
        self.assertLess(res["option_net"], 0)


if __name__ == "__main__":
    unittest.main()
