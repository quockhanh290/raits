# tests/test_vwap_mr_strategy.py
#
# VWAP Mean Reversion strategy test suite — Phase 1B Weeks 11-12
#
# Blueprint ref: Section 4.3 "Strategy 2: VWAP Mean Reversion - The Grinders"
#
# Run with: python -m unittest tests.test_vwap_mr_strategy -v
# Target:   21/21 passing
#
# Test class structure:
#   TestVWAPMRScanner        (5 tests)  — run_scanner() gate
#   TestBollingerBands       (4 tests)  — calculate_bollinger_bands()
#   TestVWAPCalculation      (3 tests)  — calculate_vwap()
#   TestSignalGeneration     (9 tests)  — generate_signal() end-to-end

import unittest
import pandas as pd
import numpy as np

from raits.strategies.vwap_mr import VWAPMRStrategy
from tests.fixtures.vwap_mr_fixtures import (
    CLEAN_SHORT_FADE,
    CLEAN_LONG_FADE,
    NORMAL_REGIME_VALID_SETUP,
    STRESS_REGIME_VALID_SETUP,
    NO_CONFIRMATION_CLOSES_OUTSIDE,
    SCANNER_ADX_TOO_HIGH,
    SCANNER_SMA_TOO_FAR,
    SCANNER_VOLUME_SPIKE,
    SCANNER_VALID_CANDIDATE,
    BB_UPPER, BB_LOWER, BB_MIDDLE,
    VWAP_VALUE, ATR_VALUE,
)


def get_prev_bar(fixture: dict) -> pd.Series:
    """bar[-2] — the confirmation bar that touched the BB."""
    return fixture['bars'].iloc[-2]

def get_entry_bar(fixture: dict) -> pd.Series:
    """bar[-1] — the bar whose open is the fill price."""
    return fixture['bars'].iloc[-1]

def get_history_bars(fixture: dict) -> pd.DataFrame:
    """All bars EXCEPT the last two (used for BB/VWAP calculation)."""
    return fixture['bars'].iloc[:-2]


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 1: Scanner gate
# Blueprint ref: Section 4.3 "Scanner Criteria (Real-Time Filter)"
# ─────────────────────────────────────────────────────────────────────────────

class TestVWAPMRScanner(unittest.TestCase):
    """
    run_scanner() takes a list of candidate dicts and returns tickers that
    pass all five filters:
      1. ADX < 25           (not trending)
      2. price within ±3%   of 20-period SMA  (ADX lag protection)
      3. volume < 3×        avg daily volume  (ADX lag protection)
      4. ATR decreasing     (volatility compressing, not expanding)
      5. no earnings today  or yesterday AH
    """

    def setUp(self):
        self.strategy = VWAPMRStrategy()

    def test_accepts_valid_candidate(self):
        """All five filters pass → ticker appears in result."""
        c = SCANNER_VALID_CANDIDATE
        result = self.strategy.run_scanner([{
            'ticker':           c['ticker'],
            'adx':              c['adx'],
            'sma_20':           c['sma_20'],
            'current_price':    c['current_price'],
            'current_volume':   c['current_volume'],
            'avg_daily_volume': c['avg_daily_volume'],
            'atr_current':      c['atr_current'],
            'atr_5bars_ago':    c['atr_5bars_ago'],
            'has_earnings':     c['has_earnings'],
        }])
        self.assertIn(c['ticker'], result,
                      "Valid candidate should pass all scanner filters")

    def test_rejects_high_adx(self):
        """
        Blueprint: "Trendless filter — ADX < 25. If ADX >= 25: return False"
        ADX=28 means the stock is trending — mean reversion trades will lose.
        """
        c = SCANNER_ADX_TOO_HIGH
        result = self.strategy.run_scanner([{
            'ticker': c['ticker'], 'adx': c['adx'],
            'sma_20': c['sma_20'], 'current_price': c['current_price'],
            'current_volume': c['current_volume'],
            'avg_daily_volume': c['avg_daily_volume'],
            'atr_current': c['atr_current'], 'atr_5bars_ago': c['atr_5bars_ago'],
            'has_earnings': c['has_earnings'],
        }])
        self.assertNotIn(c['ticker'], result,
                         "ADX=28 should be rejected (>= 25 threshold)")

    def test_rejects_price_too_far_from_sma(self):
        """
        Blueprint ADX Lag Protection Filter #1:
        "Price > 3% from 20-period SMA → reject"
        Price $75 vs SMA $100 = 25% deviation.
        """
        c = SCANNER_SMA_TOO_FAR
        result = self.strategy.run_scanner([{
            'ticker': c['ticker'], 'adx': c['adx'],
            'sma_20': c['sma_20'], 'current_price': c['current_price'],
            'current_volume': c['current_volume'],
            'avg_daily_volume': c['avg_daily_volume'],
            'atr_current': c['atr_current'], 'atr_5bars_ago': c['atr_5bars_ago'],
            'has_earnings': c['has_earnings'],
        }])
        self.assertNotIn(c['ticker'], result,
                         "Price 25% from SMA should be rejected")

    def test_rejects_volume_spike(self):
        """
        Blueprint ADX Lag Protection Filter #2:
        "Volume > 3× avg daily volume → reject"
        4× volume = something unusual happening (news, earnings, halt).
        """
        c = SCANNER_VOLUME_SPIKE
        result = self.strategy.run_scanner([{
            'ticker': c['ticker'], 'adx': c['adx'],
            'sma_20': c['sma_20'], 'current_price': c['current_price'],
            'current_volume': c['current_volume'],
            'avg_daily_volume': c['avg_daily_volume'],
            'atr_current': c['atr_current'], 'atr_5bars_ago': c['atr_5bars_ago'],
            'has_earnings': c['has_earnings'],
        }])
        self.assertNotIn(c['ticker'], result,
                         "Volume 4× avg should be rejected (> 3× threshold)")

    def test_rejects_earnings(self):
        """
        Blueprint: "Earnings calendar check — if earnings today or yesterday AH: reject"
        Earnings = unpredictable volatility = mean reversion will fail.
        """
        c = dict(SCANNER_VALID_CANDIDATE)
        c['has_earnings'] = True    # only change from valid candidate
        result = self.strategy.run_scanner([{
            'ticker': c['ticker'], 'adx': c['adx'],
            'sma_20': c['sma_20'], 'current_price': c['current_price'],
            'current_volume': c['current_volume'],
            'avg_daily_volume': c['avg_daily_volume'],
            'atr_current': c['atr_current'], 'atr_5bars_ago': c['atr_5bars_ago'],
            'has_earnings': c['has_earnings'],
        }])
        self.assertNotIn(c['ticker'], result,
                         "Earnings day should be rejected")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 2: Bollinger Band calculation
# Blueprint ref: Section 4.3 "Entry Logic — Fade"
# ─────────────────────────────────────────────────────────────────────────────

class TestBollingerBands(unittest.TestCase):
    """
    calculate_bollinger_bands(bars, period=20, std_dev=2.0) returns
    (bb_upper, bb_middle, bb_lower) computed from the close prices of bars.

    Formula:
        bb_middle = rolling mean of close (20-period)
        bb_std    = rolling std of close  (20-period)
        bb_upper  = bb_middle + std_dev × bb_std
        bb_lower  = bb_middle - std_dev × bb_std
    """

    def setUp(self):
        self.strategy = VWAPMRStrategy()
        # Use the 20 history bars from the clean short fade fixture
        self.history_bars = get_history_bars(CLEAN_SHORT_FADE)

    def test_bb_middle_is_sma_of_close(self):
        """
        BB middle band = 20-period SMA of close prices.
        With alternating $99.90/$100.10, SMA = $100.00.
        """
        upper, middle, lower = self.strategy.calculate_bollinger_bands(
            self.history_bars, period=20, std_dev=2.0
        )
        self.assertAlmostEqual(middle, BB_MIDDLE, places=4,
                               msg="BB middle should be SMA of close = $100.00")

    def test_bb_upper_and_lower_are_symmetric(self):
        """
        Upper and lower bands must be equidistant from middle.
        BB_upper - BB_middle == BB_middle - BB_lower
        """
        upper, middle, lower = self.strategy.calculate_bollinger_bands(
            self.history_bars, period=20, std_dev=2.0
        )
        upper_distance = upper - middle
        lower_distance = middle - lower
        self.assertAlmostEqual(upper_distance, lower_distance, places=6,
                               msg="BB bands should be symmetric around middle")

    def test_bb_upper_matches_expected_value(self):
        """
        With std=$0.10 and std_dev=2.0:
        BB_upper = $100.00 + 2.0 × $0.10 = $100.20
        """
        upper, middle, lower = self.strategy.calculate_bollinger_bands(
            self.history_bars, period=20, std_dev=2.0
        )
        # places=1 because pandas rolling().std() uses sample std (ddof=1,
        # divides by N-1=19), not population std (N=20). The two differ by
        # ~0.5% for small N — implementation is correct, fixture is approximate.
        self.assertAlmostEqual(upper, BB_UPPER, places=1,
                               msg=f"BB upper should be ~${BB_UPPER}")

    def test_bb_wider_with_higher_std_dev(self):
        """
        Setting std_dev=2.5 should produce wider bands than std_dev=2.0.
        This is the WFO-optimizable parameter (Section 7.1).
        """
        upper_2, _, lower_2 = self.strategy.calculate_bollinger_bands(
            self.history_bars, period=20, std_dev=2.0
        )
        upper_25, _, lower_25 = self.strategy.calculate_bollinger_bands(
            self.history_bars, period=20, std_dev=2.5
        )
        self.assertGreater(upper_25, upper_2,
                           "std_dev=2.5 should produce higher upper band")
        self.assertLess(lower_25, lower_2,
                        "std_dev=2.5 should produce lower lower band")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 3: VWAP calculation
# Blueprint ref: Section 4.3 "Exit Logic — Target: VWAP Line"
# ─────────────────────────────────────────────────────────────────────────────

class TestVWAPCalculation(unittest.TestCase):
    """
    calculate_vwap(bars) returns the Volume Weighted Average Price
    from the session open through the provided bars.

    Formula:
        VWAP = Σ(typical_price × volume) / Σ(volume)
        typical_price = (high + low + close) / 3
    """

    def setUp(self):
        self.strategy = VWAPMRStrategy()

    def test_vwap_with_equal_volume_bars(self):
        """
        When all bars have equal volume, VWAP = average of typical prices.
        3 bars: all with typical_price=$100.00, volume=1000 each.
        VWAP = (100+100+100)/3 = $100.00
        """
        bars = pd.DataFrame({
            'open':   [100.0, 100.0, 100.0],
            'high':   [100.2, 100.2, 100.2],
            'low':    [ 99.8,  99.8,  99.8],
            'close':  [100.0, 100.0, 100.0],
            'volume': [1000,  1000,  1000],
        }, index=pd.to_datetime(['2024-01-15 10:15',
                                  '2024-01-15 10:16',
                                  '2024-01-15 10:17']))
        vwap = self.strategy.calculate_vwap(bars)
        self.assertAlmostEqual(vwap, 100.0, places=4)

    def test_vwap_weighted_toward_high_volume_bar(self):
        """
        If one bar has much higher volume, VWAP should be pulled toward
        that bar's typical price.

        Bar 1: typical=$99.00, volume=100
        Bar 2: typical=$101.00, volume=900
        Expected VWAP = (99×100 + 101×900) / 1000 = 100.80
        """
        bars = pd.DataFrame({
            'open':   [99.0,  101.0],
            'high':   [99.2,  101.2],
            'low':    [98.8,  100.8],
            'close':  [99.0,  101.0],   # typical = (high+low+close)/3 ≈ 99.0 / 101.0
            'volume': [100,   900],
        }, index=pd.to_datetime(['2024-01-15 10:15',
                                  '2024-01-15 10:16']))
        vwap = self.strategy.calculate_vwap(bars)
        # typical_1 = (99.2+98.8+99.0)/3 = 99.0
        # typical_2 = (101.2+100.8+101.0)/3 = 101.0
        # vwap = (99.0×100 + 101.0×900) / 1000 = (9900 + 90900) / 1000 = 100.80
        self.assertAlmostEqual(vwap, 100.80, places=2)

    def test_vwap_matches_precomputed_fixture_value(self):
        """
        The history bars in CLEAN_SHORT_FADE are designed so that VWAP
        converges to $100.00 (all bars centered around $100, equal volume weighting).
        """
        history = get_history_bars(CLEAN_SHORT_FADE)
        vwap = self.strategy.calculate_vwap(history)
        self.assertAlmostEqual(vwap, VWAP_VALUE, delta=0.05,
                               msg="VWAP should converge to $100.00 on balanced bars")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 4: Signal generation (end-to-end)
# Blueprint ref: Section 4.3 "Entry Logic — Fade" + Section 6.1 Regime Mapping
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalGeneration(unittest.TestCase):
    """
    generate_signal(prev_bar, entry_bar, bb_upper, bb_lower, vwap, atr, hmm_state)

    DECISION SEQUENCE:
      1. HMM regime gate     → None if not Calm
      2. Confirmation check  → does prev_bar touch AND close back inside band?
      3. Direction           → SHORT (upper fade) or LONG (lower fade)
      4. Compute levels      → entry=entry_bar.open, stop=entry±1.5×ATR, target=vwap
      5. Return signal dict

    Signal dict keys:
      direction    : 'LONG' or 'SHORT'
      entry_price  : entry_bar['open']
      stop_loss    : entry ± 1.5×ATR
      target       : vwap
    """

    def setUp(self):
        self.strategy = VWAPMRStrategy()

    # ── Happy path ────────────────────────────────────────────────────────────

    def test_generates_short_signal_on_upper_fade(self):
        """
        Scenario 1: upper BB touch with confirmation → SHORT signal.
        """
        f = CLEAN_SHORT_FADE
        signal = self.strategy.generate_signal(
            prev_bar=get_prev_bar(f),
            entry_bar=get_entry_bar(f),
            bb_upper=f['bb_upper'], bb_lower=f['bb_lower'],
            vwap=f['vwap'], atr=f['atr'],
            hmm_state='Calm',
        )
        self.assertIsNotNone(signal, "Upper band fade should produce a signal")
        self.assertEqual(signal['direction'], 'SHORT')

    def test_generates_long_signal_on_lower_fade(self):
        """
        Scenario 2: lower BB touch with confirmation → LONG signal.
        """
        f = CLEAN_LONG_FADE
        signal = self.strategy.generate_signal(
            prev_bar=get_prev_bar(f),
            entry_bar=get_entry_bar(f),
            bb_upper=f['bb_upper'], bb_lower=f['bb_lower'],
            vwap=f['vwap'], atr=f['atr'],
            hmm_state='Calm',
        )
        self.assertIsNotNone(signal, "Lower band fade should produce a signal")
        self.assertEqual(signal['direction'], 'LONG')

    # ── Regime gate (most restrictive of all four strategies) ─────────────────

    def test_rejects_normal_regime(self):
        """
        Blueprint: "Best HMM Regime: Calm ONLY — skip during Normal/Stress"
        VWAP MR needs quiet, range-bound conditions. Normal has too much trend.
        """
        f = CLEAN_SHORT_FADE
        signal = self.strategy.generate_signal(
            prev_bar=get_prev_bar(f),
            entry_bar=get_entry_bar(f),
            bb_upper=f['bb_upper'], bb_lower=f['bb_lower'],
            vwap=f['vwap'], atr=f['atr'],
            hmm_state='Normal',
        )
        self.assertIsNone(signal, "Normal regime must block VWAP MR")

    def test_rejects_stress_regime(self):
        """Stress regime also blocked — even more so than Normal."""
        f = CLEAN_SHORT_FADE
        signal = self.strategy.generate_signal(
            prev_bar=get_prev_bar(f),
            entry_bar=get_entry_bar(f),
            bb_upper=f['bb_upper'], bb_lower=f['bb_lower'],
            vwap=f['vwap'], atr=f['atr'],
            hmm_state='Stress',
        )
        self.assertIsNone(signal, "Stress regime must block VWAP MR")

    # ── Confirmation gate ─────────────────────────────────────────────────────

    def test_rejects_no_confirmation_closes_outside(self):
        """
        Blueprint: "prev_bar.high >= bb_upper AND prev_bar.close < bb_upper"
        If bar closes ABOVE the band, momentum is strong — do not fade.
        """
        f = NO_CONFIRMATION_CLOSES_OUTSIDE
        signal = self.strategy.generate_signal(
            prev_bar=get_prev_bar(f),
            entry_bar=get_entry_bar(f),
            bb_upper=f['bb_upper'], bb_lower=f['bb_lower'],
            vwap=f['vwap'], atr=f['atr'],
            hmm_state='Calm',
        )
        self.assertIsNone(signal,
                          "Bar closing outside band = no confirmation = no signal")

    # ── Signal structure ──────────────────────────────────────────────────────

    def test_entry_is_entry_bar_open(self):
        """
        Blueprint: "Entry occurs at NEXT BAR OPEN after confirmation"
        For VWAP MR, the confirmation is at bar[-2] completion,
        so entry is bar[-1] open — NOT bar[-2] close.
        """
        f = CLEAN_SHORT_FADE
        signal = self.strategy.generate_signal(
            prev_bar=get_prev_bar(f),
            entry_bar=get_entry_bar(f),
            bb_upper=f['bb_upper'], bb_lower=f['bb_lower'],
            vwap=f['vwap'], atr=f['atr'],
            hmm_state='Calm',
        )
        self.assertAlmostEqual(
            signal['entry_price'], f['expected_entry'], places=2,
            msg="Entry must be entry_bar open, not prev_bar close"
        )

    def test_short_stop_is_entry_plus_atr(self):
        """
        Blueprint: "stop = entry_price + 1.5 × ATR" for SHORT trades.
        entry=$100.12, ATR=$0.30 → stop = $100.12 + $0.45 = $100.57
        """
        f = CLEAN_SHORT_FADE
        signal = self.strategy.generate_signal(
            prev_bar=get_prev_bar(f),
            entry_bar=get_entry_bar(f),
            bb_upper=f['bb_upper'], bb_lower=f['bb_lower'],
            vwap=f['vwap'], atr=f['atr'],
            hmm_state='Calm',
        )
        self.assertAlmostEqual(signal['stop_loss'], f['expected_stop'], places=2,
                               msg="SHORT stop = entry + 1.5×ATR")

    def test_long_stop_is_entry_minus_atr(self):
        """
        Blueprint: "stop = entry_price - 1.5 × ATR" for LONG trades.
        entry=$99.88, ATR=$0.30 → stop = $99.88 - $0.45 = $99.43
        """
        f = CLEAN_LONG_FADE
        signal = self.strategy.generate_signal(
            prev_bar=get_prev_bar(f),
            entry_bar=get_entry_bar(f),
            bb_upper=f['bb_upper'], bb_lower=f['bb_lower'],
            vwap=f['vwap'], atr=f['atr'],
            hmm_state='Calm',
        )
        self.assertAlmostEqual(signal['stop_loss'], f['expected_stop'], places=2,
                               msg="LONG stop = entry - 1.5×ATR")

    def test_target_is_vwap(self):
        """
        Blueprint: "Target: VWAP Line (fair value)"
        Unlike ORB (2R), VWAP MR targets mean reversion to VWAP.
        """
        f = CLEAN_SHORT_FADE
        signal = self.strategy.generate_signal(
            prev_bar=get_prev_bar(f),
            entry_bar=get_entry_bar(f),
            bb_upper=f['bb_upper'], bb_lower=f['bb_lower'],
            vwap=f['vwap'], atr=f['atr'],
            hmm_state='Calm',
        )
        self.assertAlmostEqual(signal['target'], VWAP_VALUE, places=2,
                               msg="Target must be VWAP, not a fixed R multiple")

    def test_signal_contains_all_required_fields(self):
        """All downstream consumers (backtester, cost model) need these keys."""
        f = CLEAN_SHORT_FADE
        signal = self.strategy.generate_signal(
            prev_bar=get_prev_bar(f),
            entry_bar=get_entry_bar(f),
            bb_upper=f['bb_upper'], bb_lower=f['bb_lower'],
            vwap=f['vwap'], atr=f['atr'],
            hmm_state='Calm',
        )
        self.assertIsNotNone(signal)
        for key in {'direction', 'entry_price', 'stop_loss', 'target'}:
            self.assertIn(key, signal,
                          f"Signal missing required field: '{key}'")


if __name__ == '__main__':
    unittest.main(verbosity=2)
