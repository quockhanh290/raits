"""
tests/test_pf_analysis.py
Unit tests for pf_analysis.py — profit_factor and cost stress recompute.

Run:
    cd d:/raits/raits
    python -m pytest tests/test_pf_analysis.py -v
"""

import sys
import os
import math

import pandas as pd
import pytest

# Make scripts importable without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "raits", "scripts"))
from pf_analysis import profit_factor, stressed_pf


# ── profit_factor ─────────────────────────────────────────────────────────────

class TestProfitFactor:
    def test_known_wins_losses(self):
        # wins: 100+200=300, losses: 50+50=100 → PF = 3.0
        pnls = pd.Series([100.0, 200.0, -50.0, -50.0])
        assert abs(profit_factor(pnls) - 3.0) < 1e-9

    def test_single_win_single_loss(self):
        pnls = pd.Series([60.0, -40.0])
        # 60 / 40 = 1.5
        assert abs(profit_factor(pnls) - 1.5) < 1e-9

    def test_breakeven_trade_counts_as_loss(self):
        # net_pnl == 0 should be treated as loss (not a win), so denominator > 0
        pnls = pd.Series([50.0, 0.0])
        # wins=50, losses=0 → but 0.0 is <= 0, so loss sum = 0 → inf? No:
        # 0.0 <= 0 is True, so it IS in losses. losses.sum() = 0.0. abs(0) = 0.
        # → this hits the losses==0 branch → inf
        # Actually 0.0 IS in the <= 0 bucket, sum=0.0, |0|=0 → inf
        assert profit_factor(pnls) == float("inf")

    def test_all_wins_returns_inf(self):
        pnls = pd.Series([10.0, 20.0, 30.0])
        assert profit_factor(pnls) == float("inf")

    def test_all_losses_returns_zero(self):
        pnls = pd.Series([-10.0, -20.0])
        # wins=0, losses=30 → 0/30 = 0.0
        assert profit_factor(pnls) == 0.0

    def test_empty_series(self):
        # No wins and no losses: both branches → losses==0, wins==0 → 0.0
        pnls = pd.Series([], dtype=float)
        assert profit_factor(pnls) == 0.0

    def test_pf_1_37_range(self):
        # Simulate a realistic ~50% WR system around PF 1.37
        # 50 wins of $200, 50 losses of $146 → PF ≈ 200/146 = 1.370
        wins   = pd.Series([200.0] * 50)
        losses = pd.Series([-146.0] * 50)
        pnls   = pd.concat([wins, losses], ignore_index=True)
        pf = profit_factor(pnls)
        expected = (50 * 200) / (50 * 146)
        assert abs(pf - expected) < 1e-6

    def test_pf_below_1_losing_system(self):
        # wins sum < losses sum → PF < 1
        pnls = pd.Series([10.0, 10.0, -25.0])
        pf = profit_factor(pnls)
        assert pf < 1.0
        assert abs(pf - 20.0 / 25.0) < 1e-9

    def test_single_trade_win(self):
        pnls = pd.Series([42.0])
        assert profit_factor(pnls) == float("inf")

    def test_single_trade_loss(self):
        pnls = pd.Series([-42.0])
        assert profit_factor(pnls) == 0.0


# ── stressed_pf ───────────────────────────────────────────────────────────────

class TestStressedPf:
    def _make_df(self, gross, costs):
        return (
            pd.Series(gross, dtype=float),
            pd.Series(costs, dtype=float),
        )

    def test_1x_matches_net(self):
        # stressed_pf at 1x should equal profit_factor(gross - costs)
        gross  = pd.Series([200.0, 150.0, -80.0, -60.0])
        costs  = pd.Series([10.0,   8.0,   5.0,   4.0])
        net    = gross - costs  # [190, 142, -85, -64]
        expected = profit_factor(net)
        assert abs(stressed_pf(gross, costs, 1.0) - expected) < 1e-9

    def test_2x_costs_reduces_pf(self):
        gross = pd.Series([200.0, -80.0])
        costs = pd.Series([20.0,   5.0])
        # 1x: net=[180, -85] → PF = 180/85 ≈ 2.118
        # 2x: net=[160, -90] → PF = 160/90 ≈ 1.778
        pf_1x = stressed_pf(gross, costs, 1.0)
        pf_2x = stressed_pf(gross, costs, 2.0)
        assert pf_2x < pf_1x

    def test_high_multiplier_breaks_system(self):
        # With very high costs, even winning trades become losses
        gross = pd.Series([100.0, -50.0])
        costs = pd.Series([60.0,   5.0])
        # 3x: stressed_net = [100-180, -50-15] = [-80, -65] → all losses → PF=0
        pf_3x = stressed_pf(gross, costs, 3.0)
        assert pf_3x == 0.0

    def test_cost_scaling_monotone(self):
        gross = pd.Series([150.0, 120.0, -80.0, -70.0])
        costs = pd.Series([10.0,   8.0,   4.0,   3.0])
        pfs = [stressed_pf(gross, costs, m) for m in [1.0, 1.5, 2.0, 3.0]]
        # PF should be non-increasing as costs rise
        for i in range(len(pfs) - 1):
            assert pfs[i] >= pfs[i + 1] - 1e-9, (
                f"PF not monotone: pfs[{i}]={pfs[i]:.4f} > pfs[{i+1}]={pfs[i+1]:.4f}"
            )

    def test_zero_costs_unchanged(self):
        gross = pd.Series([100.0, -60.0])
        costs = pd.Series([0.0,    0.0])
        pf_2x = stressed_pf(gross, costs, 2.0)
        # stressed_net = gross - 0*2 = gross → same PF at any mult
        assert abs(pf_2x - profit_factor(gross)) < 1e-9
