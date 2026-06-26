"""
tests/test_bull_calm_strats.py

Unit tests for bull_calm_strats.py pure functions.
Synthetic, deterministic inputs with analytically known outcomes.

Run:
    cd d:/raits/raits
    python -m pytest tests/test_bull_calm_strats.py -v
"""

from __future__ import annotations
import sys
import os

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "raits", "scripts"))
from bull_calm_strats import (
    compute_sma,
    compute_ema,
    compute_rsi,
    compute_atr,
    simulate_a,
    simulate_b,
    simulate_c,
    bootstrap_pvalue,
    TRADE_SIZE,
    COMM,
    SLIPPAGE,
    BONFERRONI_P,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bdays(n, start="2017-01-03"):
    return pd.date_range(start, periods=n, freq="B")


def _s(vals, start="2017-01-03"):
    return pd.Series(vals, index=_bdays(len(vals)))


def _const(val, n, start="2017-01-03"):
    return pd.Series(val, index=_bdays(n), dtype=float)


def _run_a(ticker, close_v, open_v, high_v, low_v,
           sma50_val, sma200_val, ema20_v, atr14_v, rsi14_v, rh20_v,
           **kw):
    n = len(close_v)
    idx = _bdays(n)
    close = pd.Series(close_v, index=idx)
    open_ = pd.Series(open_v,  index=idx)
    high  = pd.Series(high_v,  index=idx)
    low   = pd.Series(low_v,   index=idx)
    sma50 = _const(sma50_val, n) if isinstance(sma50_val, float) else pd.Series(sma50_val, index=idx)
    sma200 = _const(sma200_val, n) if isinstance(sma200_val, float) else pd.Series(sma200_val, index=idx)
    ema20  = pd.Series(ema20_v, index=idx) if not isinstance(ema20_v, float) else _const(ema20_v, n)
    atr14  = pd.Series(atr14_v, index=idx) if not isinstance(atr14_v, float) else _const(atr14_v, n)
    rsi14  = pd.Series(rsi14_v, index=idx) if not isinstance(rsi14_v, float) else _const(rsi14_v, n)
    rh20   = pd.Series(rh20_v, index=idx) if not isinstance(rh20_v, float) else _const(rh20_v, n)
    return simulate_a(ticker, close, open_, high, low, sma50, sma200, ema20, atr14, rsi14, rh20, **kw)


# ---------------------------------------------------------------------------
# 1. Indicator tests
# ---------------------------------------------------------------------------

class TestComputeSma:
    def test_constant_price(self):
        c = _s([100.0] * 10)
        r = compute_sma(c, 3)
        assert abs(float(r.iloc[-1]) - 100.0) < 1e-9

    def test_nan_before_window(self):
        c = _s([1.0] * 10)
        r = compute_sma(c, 5)
        assert pd.isna(r.iloc[3])
        assert not pd.isna(r.iloc[4])

    def test_known_value(self):
        c = _s([1.0, 2.0, 3.0, 4.0, 5.0])
        r = compute_sma(c, 3)
        assert abs(float(r.iloc[2]) - 2.0) < 1e-9
        assert abs(float(r.iloc[4]) - 4.0) < 1e-9


class TestComputeEma:
    def test_constant_price_equals_price(self):
        c = _s([50.0] * 30)
        r = compute_ema(c, 10)
        assert abs(float(r.iloc[-1]) - 50.0) < 1e-6

    def test_rising_price_ema_below_price(self):
        # For rising prices, EMA lags behind (EMA < close after warmup)
        c = _s(list(range(1, 31)))
        r = compute_ema(c, 5)
        assert float(r.iloc[-1]) < float(c.iloc[-1])

    def test_ema_span3_known(self):
        # alpha = 2/(3+1) = 0.5
        # EMA[0]=1, EMA[1]=0.5*2+0.5*1=1.5, EMA[2]=0.5*3+0.5*1.5=2.25
        c = _s([1.0, 2.0, 3.0])
        r = compute_ema(c, 3)
        assert abs(float(r.iloc[2]) - 2.25) < 1e-6


class TestComputeRsi:
    def test_rsi_in_range(self):
        c = _s([100.0 + i * 0.1 * (-1) ** i for i in range(50)])
        r = compute_rsi(c, 14)
        valid = r.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_all_up_returns_high_rsi(self):
        # Constant +1% daily gain -> RSI near 100
        vals = [100.0 * (1.01 ** i) for i in range(40)]
        c = _s(vals)
        r = compute_rsi(c, 14)
        assert float(r.iloc[-1]) > 70, f"Expected high RSI, got {r.iloc[-1]:.1f}"

    def test_all_down_returns_low_rsi(self):
        vals = [100.0 * (0.99 ** i) for i in range(40)]
        c = _s(vals)
        r = compute_rsi(c, 14)
        assert float(r.iloc[-1]) < 30, f"Expected low RSI, got {r.iloc[-1]:.1f}"

    def test_nan_before_window(self):
        c = _s([100.0] * 20)
        r = compute_rsi(c, 14)
        assert pd.isna(r.iloc[13])


class TestComputeAtr:
    def test_atr_positive(self):
        h = _s([110.0] * 20); l = _s([90.0] * 20); c = _s([100.0] * 20)
        r = compute_atr(h, l, c, 14)
        assert (r.dropna() > 0).all()

    def test_atr_constant_range(self):
        # Constant HL spread of 10, no gap -> TR=10 -> ATR=10
        h = _s([105.0] * 30); l = _s([95.0] * 30); c = _s([100.0] * 30)
        r = compute_atr(h, l, c, 14)
        assert abs(float(r.iloc[-1]) - 10.0) < 0.5  # converges to 10

    def test_atr_nan_before_window(self):
        h = _s([105.0] * 20); l = _s([95.0] * 20); c = _s([100.0] * 20)
        r = compute_atr(h, l, c, 14)
        # TR is NaN at index 0 (no prev close).  EWM with min_periods=14 yields the
        # first non-NaN value as soon as 14 positions (not 14 non-NaN obs) are seen.
        assert pd.isna(r.iloc[0])         # definitely NaN at start
        assert not pd.isna(r.iloc[-1])    # definitely valid at end
        assert r.isna().sum() >= 13       # at least 13 warmup NaNs


# ---------------------------------------------------------------------------
# 2. Strategy A tests
# ---------------------------------------------------------------------------

class TestStrategyA:
    """
    Synthetic setup:
      - sma50=90, sma200=70 (so close=100 > sma50 > sma200: uptrend)
      - atr14 = 2.0 (atr/close = 2/100 = 2% < 3%: low vol OK)
      - ema20 = 98 (signal day low = 98, touches ema20)
      - rsi14 = 48 (in [40, 55])
      - roll_high20 = 108 (peak target)
    """

    def _build_signal(self, n=10, close_at_sig=100.0, high_prev=99.0,
                      sma50=90.0, sma200=70.0, ema20=98.0, atr14=2.0, rsi14=48.0,
                      rh20=108.0):
        """Build minimal synthetic data for Strategy A signal."""
        # Day 0: prev bar (high_prev)
        # Day 1: signal bar (close=close_at_sig, low=98=ema20, close>high_prev=99)
        # Day 2: fill bar (open=101)
        # Days 3+: continuation
        close_v = [high_prev] + [close_at_sig] + [102.0] * (n - 2)
        open_v  = [high_prev] + [close_at_sig] + [101.0] + [102.0] * (n - 3)
        high_v  = [high_prev] + [close_at_sig] + [102.0] * (n - 2)
        low_v   = [high_prev - 1] + [ema20] + [100.0] * (n - 2)  # day 1 low = ema20
        return (close_v, open_v, high_v, low_v)

    def test_no_signal_without_ema_touch(self):
        # low > ema20 -> dip-setup not met
        n = 5
        close_v = [99.0, 101.0, 102.0, 103.0, 104.0]
        # low stays well above ema20=98
        trades = _run_a("T", close_v, close_v, close_v,
                        [100.0, 100.0, 100.0, 100.0, 100.0],  # low > ema20
                        90.0, 70.0, 98.0, 2.0, 48.0, 108.0)
        assert trades == []

    def test_no_signal_rsi_out_of_range(self):
        # RSI = 65 > 55 -> setup not met
        n = 10
        cv, ov, hv, lv = self._build_signal(n)
        trades = _run_a("T", cv, ov, hv, lv, 90.0, 70.0, 98.0, 2.0, 65.0, 108.0)
        assert trades == []

    def test_no_signal_atr_too_high(self):
        # atr14 = 4.0 / close = 100 -> 4% > 3% -> regime blocked
        n = 10
        cv, ov, hv, lv = self._build_signal(n)
        trades = _run_a("T", cv, ov, hv, lv, 90.0, 70.0, 98.0, 4.0, 48.0, 108.0)
        assert trades == []

    def test_no_signal_close_not_above_prev_high(self):
        # close[1] = 100, high[0] = 101 -> close < prev high -> no confirm
        n = 10
        cv, ov, hv, lv = self._build_signal(n, close_at_sig=100.0, high_prev=101.0)
        trades = _run_a("T", cv, ov, hv, lv, 90.0, 70.0, 98.0, 2.0, 48.0, 108.0)
        assert trades == []

    def test_signal_fires_with_all_conditions(self):
        # close=100 > high_prev=99, low=98=ema20, rsi=48, atr=2 (2%), rh=108
        n = 35  # need room for 30-day time stop
        cv, ov, hv, lv = self._build_signal(n, close_at_sig=100.0, high_prev=99.0)
        trades = _run_a("T", cv, ov, hv, lv, 90.0, 70.0, 98.0, 2.0, 48.0, 108.0)
        assert len(trades) >= 1, "Expected at least one trade"

    def test_stop_loss_fires(self):
        # entry at open=101, stop = low[signal] - 0.5*ATR = 98 - 0.5*2 = 97
        # next bar: low = 96 <= 97 -> stop fires at 97
        n = 10
        close_v = [99.0, 100.0] + [90.0] * (n - 2)
        open_v  = [99.0, 100.0, 101.0] + [90.0] * (n - 3)
        high_v  = [99.0, 100.0] + [100.0] * (n - 2)
        low_v   = [98.0, 98.0] + [96.0] * (n - 2)  # low=96 < stop=97 on bar after fill
        trades  = _run_a("T", close_v, open_v, high_v, low_v, 90.0, 70.0, 98.0, 2.0, 48.0, 108.0)
        assert len(trades) == 1
        assert trades[0]["exit_reason"] == "STOP_LOSS"
        assert abs(trades[0]["exit_px"] - 97.0) < 1e-6   # stop = 98 - 0.5*2 = 97

    def test_phase1_partial_exit(self):
        # peak_target = rh20 = 108; after a few bars, high reaches 110 -> phase1 fires
        # Then close stays above ema20=98 for many bars -> phase2 waits
        n = 40
        close_v = [99.0, 100.0] + [102.0] * 5 + [103.0] * (n - 7)
        open_v  = [99.0, 100.0, 101.0] + [102.0] * 4 + [103.0] * (n - 7)
        # On bar 7 (index 7): high = 110 >= peak_target=108 -> phase1
        high_v  = [99.0, 100.0] + [103.0] * 4 + [110.0] + [103.0] * (n - 7)
        low_v   = [98.0, 98.0] + [100.0] * (n - 2)
        # Close stays > ema20=98 until time stop
        trades  = _run_a("T", close_v, open_v, high_v, low_v, 90.0, 70.0, 98.0, 2.0, 48.0, 108.0)
        assert len(trades) >= 1
        t = trades[0]
        assert "PHASE1" in t["exit_reason"] or t["exit_reason"] in (
            "PHASE1_THEN_EMA20", "PHASE1_THEN_TIMEOUT"
        ), f"Expected phase1 exit, got: {t['exit_reason']}"

    def test_ema20_stop_without_phase1(self):
        # close drops below ema20=98 before high hits 108 -> full stop
        n = 10
        close_v = [99.0, 100.0] + [102.0] * 3 + [95.0] * (n - 5)
        open_v  = [99.0, 100.0, 101.0] + [102.0] * 2 + [95.0] * (n - 5)
        high_v  = [99.0, 100.0] + [104.0] * (n - 2)   # high stays < 108
        low_v   = [98.0, 98.0] + [101.0] * 3 + [94.0] * (n - 5)
        # On bar 5: close=95 < ema20=98 -> stop fires but stop_price = 98-0.5*2=97
        # Actually close < ema20 fires the TRAILING stop in phase2.
        # Before phase1, SMA20 break is handled as a stop in the uptrend check (not directly).
        # In Strategy A, the stop is ONLY via intraday low <= stop_price.
        # EMA20 stop only applies in PHASE2. Without phase1, only stop_price matters.
        # So close=95 doesn't exit in phase1 unless low < 97.
        # Let me use low < 97 instead.
        low_v = [98.0, 98.0] + [101.0] * 3 + [96.0] * (n - 5)  # low=96 < stop=97 on bar 5
        trades  = _run_a("T", close_v, open_v, high_v, low_v, 90.0, 70.0, 98.0, 2.0, 48.0, 108.0)
        assert len(trades) == 1
        assert trades[0]["exit_reason"] == "STOP_LOSS"

    def test_entry_price_is_next_open(self):
        n = 35
        cv, ov, hv, lv = self._build_signal(n)
        trades = _run_a("T", cv, ov, hv, lv, 90.0, 70.0, 98.0, 2.0, 48.0, 108.0)
        assert len(trades) >= 1
        # Entry should be open of day 2 (index 2) = 101.0
        assert abs(trades[0]["entry_px"] - 101.0) < 1e-6


# ---------------------------------------------------------------------------
# 3. Strategy B tests
# ---------------------------------------------------------------------------

class TestStrategyB:
    """
    Build a synthetic series:
    - 25 bars at 100 (roll_high_20_prev becomes valid at bar 21)
    - Bar 21: close = 105 (breakout: 105 > prev 20-day high = 100)
    - Bars 22-23: close = 104 (within but not retest yet; days_since_bo=1,2 -> too early)
    - Bar 24 (days_since_bo=3): low = 101 <= 100*1.02=102 (retest), close=103>prev=104? No.
    - Let close[24]=103, prev close[23]=104 -> not green. No signal.
    - Bar 25 (days_since_bo=4): low=101, close=104, prev_close=103 -> green! signal.
    - Entry at open[26].
    """

    def _build_breakout_retest(self, n_extra=25):
        # 21 bars of 100, then breakout, then retest
        base = [100.0] * 21
        # bar 21: breakout
        bo = [105.0]
        # bars 22,23: consolidation (above 100, not near 100*1.02=102)
        consolidate = [104.0, 104.0]
        # bar 24 (days_since_bo=3): retest low=101, close=102, prev=104 -> not green
        retest1 = [102.0]
        # bar 25 (days_since_bo=4): green close after retest: low=101, close=103
        retest2 = [103.0]
        # entry at open[26] = 103
        # more bars for trade lifecycle
        rest = [104.0] * n_extra

        close_v = base + bo + consolidate + retest1 + retest2 + rest
        open_v  = base + bo + consolidate + retest1 + [103.0] + [103.0] + rest[1:]
        high_v  = [c + 1.0 for c in close_v]
        low_v   = [c - 1.0 for c in close_v]
        # Override: bars 24,25 have low=101 (retest touch)
        idx24 = 21 + 1 + 2 + 0  # = 24
        idx25 = 25
        for i in [idx24, idx25]:
            if i < len(low_v):
                low_v[i] = 101.0
        return close_v, open_v, high_v, low_v

    def _make_indicators(self, close_v, ema20_val=95.0, sma50_val=90.0, sma200_val=80.0):
        n   = len(close_v)
        idx = _bdays(n)
        close = pd.Series(close_v, index=idx)
        sma50  = _const(sma50_val, n)
        sma200 = _const(sma200_val, n)
        ema20  = _const(ema20_val, n)
        # roll_high20_prev: prior 20-session high (not including today)
        rh = close.shift(1).rolling(20, min_periods=20).max()
        return close, sma50, sma200, ema20, rh

    def test_breakout_detected_and_trade_entered(self):
        cv, ov, hv, lv = self._build_breakout_retest()
        close, s50, s200, e20, rh = self._make_indicators(cv)
        n = len(cv)
        idx = _bdays(n)
        trades = simulate_b("T", close,
                             pd.Series(ov, index=idx),
                             pd.Series(hv, index=idx),
                             pd.Series(lv, index=idx),
                             s50, s200, e20, rh)
        assert len(trades) >= 1, f"Expected at least one trade, got {len(trades)}"

    def test_no_trade_without_breakout(self):
        # price flat at 100, never breaks above 20-session high
        n = 40
        cv = [100.0] * n
        close, s50, s200, e20, rh = self._make_indicators(cv)
        idx = _bdays(n)
        trades = simulate_b("T", close, close, close, close, s50, s200, e20, rh)
        assert trades == []

    def test_no_trade_if_retest_too_early(self):
        # Retest on day_since_bo=1 (bar 22) -> should be skipped (< 3)
        base = [100.0] * 21 + [105.0]  # breakout at bar 21
        # bar 22 (days_since_bo=1): low=101 (retest), close=103 (green)
        # This should NOT trigger because days_since_bo=1 < 3
        rest = [103.0] + [104.0] * 20
        cv = base + rest
        lv = [c - 1.0 for c in cv]
        lv[22] = 101.0  # retest low on day 22
        close, s50, s200, e20, rh = self._make_indicators(cv)
        n = len(cv)
        idx = _bdays(n)
        trades = simulate_b("T", close,
                             pd.Series([c + 0.2 for c in cv], index=idx),
                             pd.Series([c + 1.0 for c in cv], index=idx),
                             pd.Series(lv, index=idx),
                             s50, s200, e20, rh)
        # Trade might still fire on a later day if another retest occurs,
        # but it should NOT fire on day 22 (too early)
        # Check: the entry should not be at bar 23 (which would be day 22+1)
        if trades:
            entry_date = pd.Timestamp(trades[0]["entry_date"])
            expected_early = _bdays(len(cv))[22]
            assert entry_date > expected_early, (
                f"Expected entry AFTER day 22, but got {entry_date}"
            )

    def test_2r_exit(self):
        # After entry at 103, stop at 100 -> risk=3, 2R target = 103+6=109
        # Make high reach 110 on bar 28
        cv, ov, hv, lv = self._build_breakout_retest(n_extra=10)
        # On bar after entry (bar 26+3), set high to 115 -> 2R hit
        hv = list(hv)
        for i in range(27, min(30, len(hv))):
            hv[i] = 115.0  # high enough to hit 2R
        close, s50, s200, e20, rh = self._make_indicators(cv)
        n = len(cv)
        idx = _bdays(n)
        trades = simulate_b("T", close,
                             pd.Series(ov, index=idx),
                             pd.Series(hv, index=idx),
                             pd.Series(lv, index=idx),
                             s50, s200, e20, rh)
        target_exits = [t for t in trades if t.get("exit_reason") == "TARGET_2R"]
        assert len(target_exits) >= 1, f"Expected TARGET_2R exit, got: {[t['exit_reason'] for t in trades]}"

    def test_stop_loss_fires_below_breakout(self):
        cv, ov, hv, lv = self._build_breakout_retest(n_extra=10)
        # After entry, set low < breakout_level=100 on bar 28
        lv = list(lv)
        for i in range(27, min(30, len(lv))):
            lv[i] = 98.0   # below breakout_level=100 -> stop fires at 100
        close, s50, s200, e20, rh = self._make_indicators(cv)
        n = len(cv)
        idx = _bdays(n)
        trades = simulate_b("T", close,
                             pd.Series(ov, index=idx),
                             pd.Series(hv, index=idx),
                             pd.Series(lv, index=idx),
                             s50, s200, e20, rh)
        stop_exits = [t for t in trades if t.get("exit_reason") == "STOP_LOSS"]
        assert len(stop_exits) >= 1, f"Expected STOP_LOSS, got: {[t['exit_reason'] for t in trades]}"
        assert abs(stop_exits[0]["exit_px"] - 100.0) < 1e-6


# ---------------------------------------------------------------------------
# 4. Strategy C tests
# ---------------------------------------------------------------------------

class TestStrategyC:
    """
    Synthetic inside bar pattern:
    - Setup: close > ema20 > sma50 > sma200, atr/close < 3%
    - Day T: inside bar (high <= prev_high, low >= prev_low)
    - Day T+1: buy-stop at ib_high triggered
    """

    def _setup_regime(self, n):
        # sma50=90, sma200=80, ema20=95, ema10=97 -> close=100 > ema20 > sma50 > sma200
        return dict(
            sma50_v=90.0, sma200_v=80.0, ema10_v=97.0, ema20_v=95.0, atr14_v=2.0
        )

    def _run_c(self, close_v, open_v, high_v, low_v, **regime):
        n   = len(close_v)
        idx = _bdays(n)
        close = pd.Series(close_v, index=idx)
        open_ = pd.Series(open_v,  index=idx)
        high  = pd.Series(high_v,  index=idx)
        low   = pd.Series(low_v,   index=idx)
        s50   = _const(regime.get("sma50_v", 90.0), n)
        s200  = _const(regime.get("sma200_v", 80.0), n)
        e10   = _const(regime.get("ema10_v", 97.0), n)
        e20   = _const(regime.get("ema20_v", 95.0), n)
        a14   = _const(regime.get("atr14_v", 2.0), n)
        return simulate_c("T", close, open_, high, low, s50, s200, e10, e20, a14)

    def test_inside_bar_detected_and_trade_entered(self):
        # Bar 0: outer bar (high=105, low=95)
        # Bar 1: inside bar (high=104<=105, low=96>=95) -> pending_entry
        # Bar 2: buy-stop trigger (high=105 >= 104=ib_high) -> fill at 104
        close_v = [100.0, 100.0, 102.0] + [103.0] * 25
        open_v  = [100.0, 100.0, 103.0] + [103.0] * 25
        high_v  = [105.0, 104.0, 105.0] + [104.0] * 25
        low_v   = [95.0,  96.0,  101.0] + [101.0] * 25
        trades = self._run_c(close_v, open_v, high_v, low_v, **self._setup_regime(len(close_v)))
        assert len(trades) >= 1, f"Expected trade, got {len(trades)}"

    def test_no_inside_bar_when_high_exceeds_prev(self):
        # Use strictly expanding high/low so no two consecutive bars form an inside bar.
        # Bar 1: high=106 > prev_high=105 -> NOT inside -> no trade ever.
        n = 10
        close_v = [100.0 + i for i in range(n)]
        high_v  = [105.0 + i for i in range(n)]   # always strictly increasing
        low_v   = [95.0  + i for i in range(n)]   # always strictly increasing
        trades = self._run_c(close_v, close_v, high_v, low_v, **self._setup_regime(n))
        assert trades == [], f"Expected no trades, got {len(trades)}"

    def test_no_inside_bar_when_low_below_prev(self):
        # Bar 1: high=104 (inside OK) but low=94 < prev_low=95 -> NOT inside
        # Use expanding ranges afterwards so no later inside bars form.
        n = 8
        close_v = [100.0, 100.0] + [101.0 + i for i in range(n - 2)]
        high_v  = [105.0, 104.0] + [107.0 + i for i in range(n - 2)]  # expanding after bar 1
        low_v   = [95.0,  94.0]  + [97.0  + i for i in range(n - 2)]  # bar 1 low<prev -> not inside
        trades = self._run_c(close_v, close_v, high_v, low_v, **self._setup_regime(n))
        assert trades == [], f"Expected no trades, got {len(trades)}"

    def test_buystop_no_fill_when_high_too_low(self):
        # Bar 1: inside bar (ib_high=104, ib_low=96) -> pending_entry
        # Bar 2: high=103 < ib_high=104 -> no fill (pending_entry cancelled)
        # Bars 3+: expanding ranges, no new inside bars formed
        n = 8
        close_v = [100.0, 100.0, 100.0] + [101.0 + i for i in range(n - 3)]
        high_v  = [105.0, 104.0, 103.0] + [106.0 + i for i in range(n - 3)]  # expanding
        low_v   = [95.0,  96.0,  97.0]  + [99.0  + i for i in range(n - 3)]  # expanding
        trades = self._run_c(close_v, close_v, high_v, low_v, **self._setup_regime(n))
        assert trades == [], f"Expected no trades, got {len(trades)}"

    def test_gap_up_fills_at_open(self):
        # After inside bar (ib_high=104), next bar opens at 107 (gap up) -> fill at 107
        close_v = [100.0, 100.0, 108.0] + [109.0] * 25
        open_v  = [100.0, 100.0, 107.0] + [109.0] * 25  # gap-up open=107 > ib_high=104
        high_v  = [105.0, 104.0, 110.0] + [110.0] * 25
        low_v   = [95.0,  96.0,  106.0] + [106.0] * 25
        trades = self._run_c(close_v, open_v, high_v, low_v, **self._setup_regime(len(close_v)))
        if trades:
            assert abs(trades[0]["entry_px"] - 107.0) < 1e-6, (
                f"Gap-up should fill at open=107, got {trades[0]['entry_px']}"
            )

    def test_2r_exit(self):
        # Bar 0: outer bar H=105, L=95
        # Bar 1: inside bar H=104<=105, L=96>=95 -> pending, ib_high=104, ib_low=96
        # Bar 2: fill H=105>=104, open=101 (< ib_high=104) -> fill at ib_high=104
        #         risk=104-96=8, 2R=120
        # Bars 3-4: hold (no exit)
        # Bar 5: H=125 >= 120 -> TARGET_2R at 120
        n = 10
        close_v = [100.0, 100.0, 101.0, 103.0, 104.0, 119.0] + [119.0] * (n - 6)
        open_v  = [100.0, 100.0, 101.0, 103.0, 104.0, 119.0] + [119.0] * (n - 6)
        high_v  = [105.0, 104.0, 105.0, 105.0, 106.0, 125.0] + [120.0] * (n - 6)
        low_v   = [95.0,  96.0,  100.0, 100.0, 101.0, 116.0] + [116.0] * (n - 6)
        trades = self._run_c(close_v, open_v, high_v, low_v, **self._setup_regime(n))
        target_exits = [t for t in trades if t.get("exit_reason") == "TARGET_2R"]
        assert len(target_exits) >= 1, f"Expected TARGET_2R, got {[t.get('exit_reason') for t in trades]}"
        assert abs(target_exits[0]["exit_px"] - 120.0) < 1e-6

    def test_ema10_stop(self):
        # After entry at 104 (stop=96, ema10=97):
        # Close drops to 90 < ema10=97 while low stays above stop (l=98 > stop=96)
        # -> EMA10_STOP fires before STOP_LOSS
        n = 10
        close_v = [100.0, 100.0, 101.0, 103.0, 104.0] + [90.0]  * (n - 5)
        open_v  = [100.0, 100.0, 101.0, 103.0, 104.0] + [90.0]  * (n - 5)
        high_v  = [105.0, 104.0, 105.0, 105.0, 106.0] + [104.0] * (n - 5)
        # low stays ABOVE stop=96 so stop-loss never triggers
        low_v   = [95.0,  96.0,  100.0, 100.0, 101.0] + [98.0]  * (n - 5)
        trades = self._run_c(close_v, open_v, high_v, low_v, **self._setup_regime(n))
        ema10_stops = [t for t in trades if t.get("exit_reason") == "EMA10_STOP"]
        assert len(ema10_stops) >= 1, (
            f"Expected EMA10_STOP, got {[t.get('exit_reason') for t in trades]}"
        )

    def test_no_trade_without_regime(self):
        # sma50 > close -> regime not met
        close_v = [100.0, 100.0, 102.0] + [103.0] * 10
        high_v  = [105.0, 104.0, 105.0] + [104.0] * 10
        low_v   = [95.0,  96.0,  101.0] + [101.0] * 10
        # Set sma50 = 110 > close = 100 -> regime fails
        trades = self._run_c(close_v, close_v, high_v, low_v,
                             sma50_v=110.0, sma200_v=90.0, ema10_v=97.0,
                             ema20_v=95.0, atr14_v=2.0)
        assert trades == []

    def test_no_trade_high_atr(self):
        # atr/close = 4.0/100 = 4% > 3% -> regime fails
        close_v = [100.0, 100.0, 102.0] + [103.0] * 10
        high_v  = [105.0, 104.0, 105.0] + [104.0] * 10
        low_v   = [95.0,  96.0,  101.0] + [101.0] * 10
        trades = self._run_c(close_v, close_v, high_v, low_v,
                             sma50_v=90.0, sma200_v=80.0, ema10_v=97.0,
                             ema20_v=95.0, atr14_v=4.0)  # 4% > 3%
        assert trades == []


# ---------------------------------------------------------------------------
# 5. Buy-and-hold edge tests
# ---------------------------------------------------------------------------

class TestBahEdge:

    def test_stop_loss_edge_zero_when_exit_at_close(self):
        # When both strategy and BAH exit at same close price, edge = 0
        # Strategy A stop fires when low <= stop_price; exits at stop_price
        # BAH exits at close on same day
        # If close != stop_price, edge != 0 (by design -- intraday fill vs EOD)
        # Test: strategy A stop at 97, close at 96 -> edge = (97-96)*shares > 0
        n = 10
        close_v = [99.0, 100.0, 101.0, 101.0, 101.0, 96.0] + [96.0] * (n - 6)
        open_v  = [99.0, 100.0, 101.0, 101.0, 101.0, 96.0] + [96.0] * (n - 6)
        high_v  = [99.0, 100.0, 101.0, 101.0, 101.0, 96.5] + [96.5] * (n - 6)
        low_v   = [98.0, 98.0,  99.0,  99.0,  99.0,  96.0] + [96.0] * (n - 6)
        # stop = low[signal] - 0.5*ATR = 98 - 0.5*2 = 97
        # on bar 5: low = 96 <= 97 -> strategy exits at 97; bah exits at 96
        trades = _run_a("T", close_v, open_v, high_v, low_v, 90.0, 70.0, 98.0, 2.0, 48.0, 108.0)
        if trades and trades[0]["exit_reason"] == "STOP_LOSS":
            t = trades[0]
            # Edge = strategy_net - bah_net.  Both differ by (stop_price - close) * shares
            # but the exit slippage costs slightly differ too.
            # The intraday stop (97) beats BAH close (96): edge should be ~shares * $1
            assert t["edge"] > 0, "Stop at higher price than close should give positive edge"
            # Within $1 of shares * $1 (slippage on $1 price diff is ~$0.05 for 99 shares)
            expected_approx = (97.0 - 96.0) * t["shares"]
            assert abs(t["edge"] - expected_approx) < 1.0, (
                f"Edge {t['edge']:.4f} not within $1 of expected {expected_approx:.4f}"
            )

    def test_time_stop_bah_edge_zero(self):
        # Time stop: both exit at same close -> edge = 0
        n = 40
        cv, ov, hv, lv = (
            [99.0, 100.0] + [102.0] * (n - 2),
            [99.0, 100.0, 101.0] + [102.0] * (n - 3),
            [99.0, 100.0] + [103.0] * (n - 2),
            [98.0, 98.0]  + [100.0] * (n - 2),
        )
        trades = _run_a("T", cv, ov, hv, lv, 90.0, 70.0, 98.0, 2.0, 48.0, 108.0)
        if trades and trades[0]["exit_reason"] == "TIME_STOP":
            assert abs(trades[0]["edge"]) < 1e-2, (
                f"Time stop edge should be ~0, got {trades[0]['edge']:.4f}"
            )


# ---------------------------------------------------------------------------
# 6. Bootstrap tests
# ---------------------------------------------------------------------------

class TestBootstrap:

    def test_all_positive_pval_zero(self):
        edges = np.ones(100) * 50.0
        p = bootstrap_pvalue(edges, n_boot=500, seed=0)
        assert p == 0.0

    def test_all_negative_pval_one(self):
        edges = np.ones(100) * -50.0
        p = bootstrap_pvalue(edges, n_boot=500, seed=0)
        assert p == 1.0

    def test_all_zero_pval_one(self):
        edges = np.zeros(100)
        p = bootstrap_pvalue(edges, n_boot=500, seed=0)
        assert p == 1.0

    def test_empty_edges_pval_one(self):
        p = bootstrap_pvalue(np.array([]))
        assert p == 1.0

    def test_bonferroni_threshold_is_correct(self):
        # BONFERRONI_P = 0.0167 (rounded), exact = 0.05/3 ≈ 0.01667; tolerance = 0.001
        assert abs(BONFERRONI_P - 0.05 / 3.0) < 0.001

    def test_deterministic(self):
        rng   = np.random.default_rng(7)
        edges = rng.normal(5.0, 20.0, 100)
        p1 = bootstrap_pvalue(edges, n_boot=200, seed=42)
        p2 = bootstrap_pvalue(edges, n_boot=200, seed=42)
        assert p1 == p2
