"""
tests/test_dip_buy_sim.py

Unit tests for dip_buy_sim.py pure functions.
Synthetic, deterministic inputs with analytically known outcomes.

Run:
    cd d:/raits/raits
    python -m pytest tests/test_dip_buy_sim.py -v
"""

from __future__ import annotations
import sys
import os

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "raits", "scripts"))
from dip_buy_sim import (
    compute_indicators,
    simulate_stock,
    bootstrap_pvalue,
    TRADE_SIZE_USD,
    COMM_USD,
    SLIPPAGE_PCT,
    DIP_LOOKBACK,
    TIME_STOP_DAYS,
    SMA_FAST,
    SMA_SLOW,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bdays(n: int, start: str = "2017-01-03") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="B")


def _series(values, start="2017-01-03", name=None):
    idx = _bdays(len(values), start)
    return pd.Series(values, index=idx, name=name)


def _const_indicators(close: pd.Series, sma50_val: float, sma200_val: float):
    """Return constant sma50, sma200 (uptrend guaranteed) and rolling roll_high."""
    sma50    = pd.Series(sma50_val,  index=close.index, dtype=float)
    sma200   = pd.Series(sma200_val, index=close.index, dtype=float)
    roll_high = close.rolling(DIP_LOOKBACK, min_periods=DIP_LOOKBACK).max()
    return sma50, sma200, roll_high


def _run(ticker, close_vals, open_vals, high_vals, sma50_val, sma200_val,
         variant="A", trade_size=TRADE_SIZE_USD, comm=COMM_USD, slippage=SLIPPAGE_PCT):
    """Build Series, compute const indicators, run simulate_stock."""
    close  = _series(close_vals, name="close")
    open_  = _series(open_vals,  name="open")
    high   = _series(high_vals,  name="high")
    sma50, sma200, roll_high = _const_indicators(close, sma50_val, sma200_val)
    return simulate_stock(
        ticker, close, open_, high, sma50, sma200, roll_high,
        variant, trade_size, comm, slippage,
    )


# ---------------------------------------------------------------------------
# 1. compute_indicators
# ---------------------------------------------------------------------------

class TestComputeIndicators:

    def test_sma_fast_nan_before_window(self):
        close = _series([100.0] * 60)
        sma50, sma200, rh = compute_indicators(close)
        assert pd.isna(sma50.iloc[SMA_FAST - 2])
        assert not pd.isna(sma50.iloc[SMA_FAST - 1])

    def test_sma_slow_nan_before_window(self):
        close = _series([100.0] * 210)
        sma50, sma200, rh = compute_indicators(close)
        assert pd.isna(sma200.iloc[SMA_SLOW - 2])
        assert not pd.isna(sma200.iloc[SMA_SLOW - 1])

    def test_roll_high_nan_before_lookback(self):
        close = _series([100.0] * 25)
        _, _, rh = compute_indicators(close)
        assert pd.isna(rh.iloc[DIP_LOOKBACK - 2])
        assert not pd.isna(rh.iloc[DIP_LOOKBACK - 1])

    def test_roll_high_correct_value(self):
        vals  = list(range(1, 22))    # 1..21; max of last 20 = max(2..21) = 21 on bar 20
        close = _series(vals, name="close")
        _, _, rh = compute_indicators(close)
        # Bar 20 (index 20, value=21): roll(20) over indices 1-20 = max(2..21) = 21
        assert float(rh.iloc[20]) == 21.0

    def test_sma_values_correct(self):
        # Constant series: sma = constant
        close = _series([50.0] * 210)
        sma50, sma200, _ = compute_indicators(close)
        assert abs(float(sma50.iloc[-1]) - 50.0) < 1e-9
        assert abs(float(sma200.iloc[-1]) - 50.0) < 1e-9


# ---------------------------------------------------------------------------
# 2. Dip detection — no signal without a dip
# ---------------------------------------------------------------------------

class TestDipDetection:

    def test_no_trade_when_no_dip(self):
        # Price flat at 100, roll_high = 100 after warmup -> dip = 100 < 95 -> False
        n = 25
        close = [100.0] * n
        open_ = [100.0] * n
        high  = [100.0] * n
        trades = _run("T", close, open_, high, sma50_val=90.0, sma200_val=80.0)
        assert trades == [], "No trades expected when price never dips"

    def test_no_trade_in_downtrend(self):
        # close < sma50 on all bars -> uptrend always False
        n = 30
        # sma50 = 110, close = 100 -> not uptrend
        close = [100.0] * n
        open_ = [100.0] * n
        high  = [100.0] * n
        sma50, sma200, rh = _const_indicators(
            _series(close), sma50_val=110.0, sma200_val=90.0
        )
        c   = _series(close)
        o   = _series(open_)
        h   = _series(high)
        trades = simulate_stock("T", c, o, h, sma50, sma200, rh, "A")
        assert trades == [], "No trades expected in downtrend"

    def test_no_trade_when_dip_breaks_sma50(self):
        # Dip condition requires close > sma50.
        # Close = 80, sma50 = 90 -> dip condition False (close NOT > sma50)
        n = 30
        close = [80.0] * n
        # roll_high will be 80 after 20 bars, dip = 80 < 80*0.95=76 -> False anyway
        # But sma50=90 blocks uptrend check too
        trades = _run("T", close, [80.0]*n, [80.0]*n, sma50_val=90.0, sma200_val=70.0)
        assert trades == []


# ---------------------------------------------------------------------------
# 3. Entry timing — signal on green day, fill on next open
# ---------------------------------------------------------------------------

class TestEntryTiming:
    """
    Setup:
      Days 0-19 (20 bars): close = 120 (peak, roll_high builds to 120)
      Day 20: close = 110 (drop of 8.3%; 110 < 120*0.95=114 -> dip)
      Day 21: close = 111 (green: 111 > 110; signal fires; peak_target = 120)
      Day 22 (fill): open = 112 (entry price)
      Days 22-41: close stays < 120 so no target, no stop
      Day 41: hold_day 20 -> TIME_STOP
    """

    def _build_case(self, variant="B"):
        # 42 bars total
        n = 44
        close_vals = [120.0] * 20 + [110.0, 111.0] + [115.0] * 22
        open_vals  = [120.0] * 20 + [110.0, 111.0, 112.0] + [115.0] * 21
        high_vals  = [120.0] * 20 + [110.0, 111.0] + [118.0] * 22  # high < 120 -> no target A
        trades = _run("TEST", close_vals, open_vals, high_vals,
                      sma50_val=90.0, sma200_val=70.0, variant=variant)
        return trades

    def test_entry_fires_after_dip_and_green(self):
        trades = self._build_case(variant="B")
        assert len(trades) >= 1, "Expected at least one trade"

    def test_entry_date_is_day_after_green(self):
        trades = self._build_case(variant="B")
        assert len(trades) >= 1
        t = trades[0]
        # Signal on day index 21 -> fill on day index 22
        close = _series([120.0] * 20 + [110.0, 111.0] + [115.0] * 22)
        fill_date = close.index[22]
        assert pd.Timestamp(t["entry_date"]) == fill_date

    def test_entry_price_is_next_open(self):
        trades = self._build_case(variant="B")
        assert len(trades) >= 1
        assert abs(trades[0]["entry_px"] - 112.0) < 1e-6

    def test_time_stop_fires_at_session_20(self):
        trades = self._build_case(variant="B")
        assert len(trades) >= 1
        t = trades[0]
        assert t["hold_days"] == TIME_STOP_DAYS
        assert t["exit_reason"] == "TIME_STOP"


# ---------------------------------------------------------------------------
# 4. Exit Variant A — TARGET
# ---------------------------------------------------------------------------

class TestExitVariantA:
    """
    Days 0-19: close = 120 (peak)
    Day 20: close = 110 (dip)
    Day 21: close = 111 (green; signal; peak_target = 120)
    Day 22: open = 112 (entry)
    Days 22-25: close = 118, high = 118 (below target)
    Day 26: close = 121, high = 122 -> high >= 120 -> TARGET, exit at 120
    """

    def _build(self):
        close_vals = [120.0]*20 + [110.0, 111.0] + [118.0]*4 + [121.0]
        open_vals  = [120.0]*20 + [110.0, 111.0, 112.0] + [118.0]*4 + [121.0]
        high_vals  = [120.0]*20 + [110.0, 111.0] + [118.0]*4 + [122.0]
        return _run("T", close_vals, open_vals, high_vals,
                    sma50_val=90.0, sma200_val=70.0, variant="A")

    def test_target_exit_fires(self):
        trades = self._build()
        assert len(trades) == 1
        assert trades[0]["exit_reason"] == "TARGET"

    def test_exit_price_is_peak_target(self):
        trades = self._build()
        assert abs(trades[0]["exit_px"] - 120.0) < 1e-6

    def test_hold_days_correct(self):
        trades = self._build()
        # fill on day 22, exit on day 26 -> hold_days = 5 (days 22,23,24,25,26)
        assert trades[0]["hold_days"] == 5

    def test_bah_exit_is_close_not_peak(self):
        trades = self._build()
        # On target day close = 121 (above 120), bah exits at 121
        assert abs(trades[0]["bah_exit_px"] - 121.0) < 1e-6

    def test_edge_negative_when_close_above_target(self):
        # close > peak_target on target day -> bah got higher price -> edge < 0
        trades = self._build()
        assert trades[0]["edge"] < 0, (
            f"Expected edge < 0 (BAH exits at higher close), got {trades[0]['edge']:.2f}"
        )

    def test_edge_positive_when_close_below_target(self):
        # high >= target but close < target -> dip-buy got better price than BAH
        close_vals = [120.0]*20 + [110.0, 111.0] + [118.0]*4 + [119.0]
        open_vals  = [120.0]*20 + [110.0, 111.0, 112.0] + [118.0]*4 + [119.0]
        high_vals  = [120.0]*20 + [110.0, 111.0] + [118.0]*4 + [122.0]
        trades = _run("T", close_vals, open_vals, high_vals,
                      sma50_val=90.0, sma200_val=70.0, variant="A")
        assert len(trades) == 1
        assert trades[0]["exit_reason"] == "TARGET"
        # exit_px = 120 (target), bah_exit_px = 119 (close) -> edge > 0
        assert trades[0]["edge"] > 0, (
            f"Expected edge > 0 (dip-buy exits higher than BAH), got {trades[0]['edge']:.2f}"
        )

    def test_gross_pnl_correct(self):
        trades = self._build()
        t = trades[0]
        entry = t["entry_px"]          # 112
        shares = t["shares"]
        expected_gross = (120.0 - entry) * shares
        assert abs(t["gross_pnl"] - expected_gross) < 1e-6

    def test_net_pnl_less_than_gross(self):
        trades = self._build()
        assert trades[0]["net_pnl"] < trades[0]["gross_pnl"]


# ---------------------------------------------------------------------------
# 5. Stop loss — 8% loss from entry
# ---------------------------------------------------------------------------

class TestStopLoss8Pct:
    """
    Entry at 100. Loss >= 8% when close <= 92.
    sma50 = 75 (always below close, so SMA stop won't fire early).
    """

    def _build(self, close_on_stop: float = 91.0):
        # 20 bars warmup at 110, then dip to 100, green to 101, fill at 100, then drop
        close_vals = [110.0]*20 + [100.0, 101.0, 101.0, close_on_stop]
        open_vals  = close_vals[:]
        high_vals  = close_vals[:]
        return _run("T", close_vals, open_vals, high_vals,
                    sma50_val=75.0, sma200_val=60.0, variant="A")

    def test_stop_fires_at_8pct_loss(self):
        # entry at 101 (open[22]), close[25] = 91 -> loss = (91-101)/101 = -9.9% -> stop
        trades = self._build(close_on_stop=91.0)
        assert len(trades) == 1
        assert trades[0]["exit_reason"] == "STOP_LOSS"

    def test_exit_at_close_on_stop_day(self):
        trades = self._build(close_on_stop=91.0)
        assert abs(trades[0]["exit_px"] - 91.0) < 1e-6

    def test_no_stop_above_threshold(self):
        # close = 94 -> loss = (94-101)/101 = -6.9% -> no stop (need >= 8%)
        # Also: high < 120 -> no target A; hold_days < 20 -> no time stop
        # So we need more bars to see what happens... instead verify hold_days < 20
        # and exit_reason is not STOP_LOSS on day 4 (hold_day=2 when close=94)
        close_vals = [110.0]*20 + [100.0, 101.0, 101.0, 94.0] + [94.0]*18
        open_vals  = close_vals[:]
        high_vals  = close_vals[:]
        trades = _run("T", close_vals, open_vals, high_vals,
                      sma50_val=75.0, sma200_val=60.0, variant="B")
        # No stop on day 4 (6.9% loss). Eventually time stop at 20.
        assert len(trades) == 1
        assert trades[0]["exit_reason"] == "TIME_STOP"
        assert trades[0]["hold_days"] == TIME_STOP_DAYS


# ---------------------------------------------------------------------------
# 6. SMA stop
# ---------------------------------------------------------------------------

class TestSmaStop:
    """
    Entry at open=100. Then close drops below sma50.
    sma50 is constant at 95. Close = 94 on exit day -> SMA stop.
    """

    def _build(self):
        # 20 bars at 110, dip to 100, green to 101, fill at 100, then drop to 94
        close_vals = [110.0]*20 + [100.0, 101.0, 101.0, 94.0]
        open_vals  = close_vals[:]
        high_vals  = close_vals[:]
        # sma50 = 95 -> close=94 < sma50=95 -> SMA stop
        # sma200 = 70 (below sma50)
        close = _series(close_vals)
        open_ = _series(open_vals)
        high  = _series(high_vals)
        sma50 = pd.Series(95.0, index=close.index, dtype=float)
        sma200 = pd.Series(70.0, index=close.index, dtype=float)
        roll_high = close.rolling(DIP_LOOKBACK, min_periods=DIP_LOOKBACK).max()
        return simulate_stock("T", close, open_, high, sma50, sma200, roll_high, "A")

    def test_sma_stop_fires(self):
        trades = self._build()
        assert len(trades) == 1
        assert trades[0]["exit_reason"] == "STOP_LOSS"

    def test_sma_stop_exit_price_is_close(self):
        trades = self._build()
        assert abs(trades[0]["exit_px"] - 94.0) < 1e-6

    def test_bah_equals_dip_buy_on_sma_stop(self):
        # Both exit at same close price -> edge = 0
        trades = self._build()
        assert abs(trades[0]["edge"]) < 1e-4, (
            f"Expected edge ~= 0 for SMA stop (same exit price), got {trades[0]['edge']:.4f}"
        )


# ---------------------------------------------------------------------------
# 7. Time stop (20 sessions)
# ---------------------------------------------------------------------------

class TestTimeStop:
    """
    Entry, hold 20 days without hitting target or stop.
    Exit at close on day 20, exit_reason = TIME_STOP.
    """

    def _build(self, variant="A"):
        # 22-bar setup, then 20 bars of holding
        # close stays at 115 (no target=120, no SMA stop=sma50=90, no 8% loss)
        setup   = [120.0]*20 + [110.0, 111.0]   # 22 bars (warmup + dip + green)
        holding = [115.0] * (TIME_STOP_DAYS + 1) # 21 bars (entry open + 20 hold days)
        close_vals = setup + holding
        open_vals  = setup + [112.0] + [115.0] * TIME_STOP_DAYS
        high_vals  = setup + [115.0] * (TIME_STOP_DAYS + 1)
        trades = _run("T", close_vals, open_vals, high_vals,
                      sma50_val=90.0, sma200_val=70.0, variant=variant)
        return trades

    def test_time_stop_fires_at_day_20_variant_a(self):
        trades = self._build(variant="A")
        assert len(trades) == 1
        assert trades[0]["exit_reason"] == "TIME_STOP"
        assert trades[0]["hold_days"] == TIME_STOP_DAYS

    def test_time_stop_fires_at_day_20_variant_b(self):
        trades = self._build(variant="B")
        assert len(trades) == 1
        assert trades[0]["exit_reason"] == "TIME_STOP"
        assert trades[0]["hold_days"] == TIME_STOP_DAYS

    def test_time_stop_exit_at_close(self):
        trades = self._build(variant="A")
        assert abs(trades[0]["exit_px"] - 115.0) < 1e-6

    def test_time_stop_bah_edge_zero(self):
        trades = self._build(variant="A")
        assert abs(trades[0]["edge"]) < 1e-4


# ---------------------------------------------------------------------------
# 8. Variant B never hits target (trailing stop only)
# ---------------------------------------------------------------------------

class TestVariantBNoTarget:
    """Variant B should NEVER exit via TARGET regardless of price hitting peak."""

    def test_variant_b_ignores_target(self):
        # High = 125 > peak_target = 120 on day 5 of holding
        # Variant B should NOT exit via TARGET
        setup   = [120.0]*20 + [110.0, 111.0]
        holding = [115.0]*4 + [130.0]  # close = 130 on day 5 of holding
        close_vals = setup + [115.0] + holding  # first holding bar = fill bar
        open_vals  = setup + [112.0] + [115.0]*4 + [130.0]
        high_vals  = setup + [115.0] + [115.0]*4 + [135.0]
        close = _series(close_vals)
        open_ = _series(open_vals)
        high  = _series(high_vals)
        sma50, sma200, rh = _const_indicators(close, 90.0, 70.0)
        trades = simulate_stock("T", close, open_, high, sma50, sma200, rh, "B")
        for t in trades:
            assert t["exit_reason"] != "TARGET", (
                f"Variant B should not exit via TARGET, got {t['exit_reason']}"
            )


# ---------------------------------------------------------------------------
# 9. No re-entry while in trade
# ---------------------------------------------------------------------------

class TestNoReentry:

    def test_one_trade_not_two_overlapping(self):
        # Two dip-buy cycles.  After the first trade time-stops (20 bars at 115),
        # the 20-session rolling high is 115.  Second dip must be >= 5% below 115:
        # use 108 (< 115 * 0.95 = 109.25 -> dip condition True).
        setup   = [120.0] * 20
        dip1    = [110.0, 111.0]          # dip + green; peak_target = 120
        hold1   = [115.0] * 20            # 20 days -> TIME_STOP; roll_high -> 115
        dip2    = [108.0, 109.0]          # 108 < 115*0.95=109.25 -> dip; 109 = green
        hold2   = [112.0] * 21            # 20 days -> TIME_STOP
        close_vals = setup + dip1 + hold1 + dip2 + hold2
        open_vals  = (setup + dip1
                      + [112.0] + [115.0]*19      # hold1 fill + 19 remaining
                      + dip2 + [109.0] + [112.0]*20)  # hold2 fill + 20 remaining
        high_vals  = close_vals[:]
        trades = _run("T", close_vals, open_vals, high_vals,
                      sma50_val=90.0, sma200_val=70.0, variant="B")
        assert len(trades) == 2, f"Expected 2 trades, got {len(trades)}"
        assert pd.Timestamp(trades[0]["exit_date"]) < pd.Timestamp(trades[1]["entry_date"])


# ---------------------------------------------------------------------------
# 10. Cost model
# ---------------------------------------------------------------------------

class TestCostModel:

    def test_costs_positive(self):
        # Any completed trade should have total_cost > 0
        close_vals = [120.0]*20 + [110.0, 111.0] + [118.0]*4 + [121.0]
        open_vals  = [120.0]*20 + [110.0, 111.0, 112.0] + [118.0]*4 + [121.0]
        high_vals  = [120.0]*20 + [110.0, 111.0] + [118.0]*4 + [122.0]
        trades = _run("T", close_vals, open_vals, high_vals,
                      sma50_val=90.0, sma200_val=70.0, variant="A")
        assert len(trades) == 1
        assert trades[0]["costs"] > 0

    def test_costs_include_commission_and_slippage(self):
        close_vals = [120.0]*20 + [110.0, 111.0] + [118.0]*4 + [121.0]
        open_vals  = [120.0]*20 + [110.0, 111.0, 112.0] + [118.0]*4 + [121.0]
        high_vals  = [120.0]*20 + [110.0, 111.0] + [118.0]*4 + [122.0]
        trades = _run("T", close_vals, open_vals, high_vals,
                      sma50_val=90.0, sma200_val=70.0, variant="A",
                      comm=5.0, slippage=0.0005)
        t = trades[0]
        shares = t["shares"]
        entry  = t["entry_px"]   # 112
        exit_  = t["exit_px"]    # 120 (peak_target)
        expected_cost = (
            COMM_USD + SLIPPAGE_PCT * entry * shares +
            COMM_USD + SLIPPAGE_PCT * exit_ * shares
        )
        assert abs(t["costs"] - expected_cost) < 1e-4

    def test_shares_is_floor_of_trade_size_over_open(self):
        # entry open = 112, trade_size = 10000 -> shares = int(10000/112) = 89
        close_vals = [120.0]*20 + [110.0, 111.0] + [115.0]*20 + [121.0]
        open_vals  = [120.0]*20 + [110.0, 111.0, 112.0] + [115.0]*19 + [121.0]
        high_vals  = [120.0]*20 + [110.0, 111.0] + [115.0]*20 + [122.0]
        trades = _run("T", close_vals, open_vals, high_vals,
                      sma50_val=90.0, sma200_val=70.0, variant="A")
        if trades:
            assert trades[0]["shares"] == int(TRADE_SIZE_USD / 112.0)


# ---------------------------------------------------------------------------
# 11. Bootstrap p-value
# ---------------------------------------------------------------------------

class TestBootstrapPvalue:

    def test_all_positive_edges_pval_near_zero(self):
        # All edges > 0 -> mean always positive -> p = 0
        edges = np.ones(100) * 50.0
        p = bootstrap_pvalue(edges, n_boot=500, seed=0)
        assert p == 0.0, f"Expected p=0 for all-positive edges, got {p}"

    def test_all_negative_edges_pval_near_one(self):
        edges = np.ones(100) * -50.0
        p = bootstrap_pvalue(edges, n_boot=500, seed=0)
        assert p == 1.0, f"Expected p=1 for all-negative edges, got {p}"

    def test_all_zero_edges_pval_is_one(self):
        # All edges = 0 -> every resample mean = 0 -> mean <= 0 always True -> p = 1
        edges = np.zeros(50)
        p = bootstrap_pvalue(edges, n_boot=500, seed=0)
        assert p == 1.0, f"Expected p=1 for all-zero edges, got {p}"

    def test_mixed_edges_pval_in_0_1(self):
        rng   = np.random.default_rng(42)
        edges = rng.normal(loc=10.0, scale=50.0, size=200)
        p = bootstrap_pvalue(edges, n_boot=500, seed=42)
        assert 0.0 <= p <= 1.0

    def test_empty_edges_returns_one(self):
        p = bootstrap_pvalue(np.array([]))
        assert p == 1.0

    def test_deterministic_with_seed(self):
        rng   = np.random.default_rng(7)
        edges = rng.normal(loc=5.0, scale=20.0, size=100)
        p1 = bootstrap_pvalue(edges, n_boot=200, seed=99)
        p2 = bootstrap_pvalue(edges, n_boot=200, seed=99)
        assert p1 == p2


# ---------------------------------------------------------------------------
# 12. Buy-and-hold edge logic
# ---------------------------------------------------------------------------

class TestBahEdge:
    """Edge = dip_buy_net_pnl - bah_net_pnl. Non-zero only for Target exits."""

    def test_time_stop_edge_is_zero(self):
        # Both exit at same close -> edge = 0
        setup   = [120.0]*20 + [110.0, 111.0]
        holding = [115.0] * (TIME_STOP_DAYS + 1)
        close_vals = setup + holding
        open_vals  = setup + [112.0] + [115.0] * TIME_STOP_DAYS
        high_vals  = setup + [115.0] * (TIME_STOP_DAYS + 1)
        trades = _run("T", close_vals, open_vals, high_vals,
                      sma50_val=90.0, sma200_val=70.0, variant="A")
        assert len(trades) == 1
        assert abs(trades[0]["edge"]) < 1e-4

    def test_stop_loss_edge_is_zero(self):
        # Both exit at same close -> edge = 0
        close_vals = [110.0]*20 + [100.0, 101.0, 101.0, 91.0]
        open_vals  = close_vals[:]
        high_vals  = close_vals[:]
        trades = _run("T", close_vals, open_vals, high_vals,
                      sma50_val=75.0, sma200_val=60.0, variant="A")
        assert len(trades) == 1
        assert trades[0]["exit_reason"] == "STOP_LOSS"
        assert abs(trades[0]["edge"]) < 1e-4

    def test_target_edge_equals_shares_times_px_diff(self):
        # peak_target=120, close on target day=121 -> edge = (120-121)*shares
        close_vals = [120.0]*20 + [110.0, 111.0] + [118.0]*4 + [121.0]
        open_vals  = [120.0]*20 + [110.0, 111.0, 112.0] + [118.0]*4 + [121.0]
        high_vals  = [120.0]*20 + [110.0, 111.0] + [118.0]*4 + [122.0]
        trades = _run("T", close_vals, open_vals, high_vals,
                      sma50_val=90.0, sma200_val=70.0, variant="A",
                      comm=0.0, slippage=0.0)  # zero costs for clean math
        t = trades[0]
        expected_edge = (120.0 - 121.0) * t["shares"]
        assert abs(t["edge"] - expected_edge) < 1e-4, (
            f"Expected edge {expected_edge:.2f}, got {t['edge']:.2f}"
        )
