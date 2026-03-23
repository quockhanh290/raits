# tests/test_trend_strategy.py
#
# Trend Following strategy test suite — Phase 1B Weeks 13-14
#
# Blueprint ref: Section 4.4 "Strategy 3: Trend Following / MOC - The Runners"
#
# Run with: python -m unittest tests.test_trend_strategy -v
# Target:   22/22 passing
#
# Test class structure:
#   TestTrendScanner           (4 tests)  — run_scanner()
#   TestEMACalculation         (3 tests)  — calculate_ema()
#   TestChandelierStop         (4 tests)  — calculate_chandelier_stop()
#   TestVolumePattern          (3 tests)  — check_volume_pattern()
#   TestSignalGeneration       (8 tests)  — generate_signal()

import unittest
import pandas as pd
import numpy as np

from raits.strategies.trend_follow import TrendFollowStrategy
from tests.fixtures.trend_fixtures import (
    CLEAN_LONG_PULLBACK,
    CLEAN_SHORT_PULLBACK,
    CALM_REGIME_VALID_SETUP,
    PULLBACK_HIGH_VOLUME,
    RESUME_LOW_VOLUME,
    SCANNER_VALID_NEAR_HOD,
    SCANNER_NOT_NEAR_HOD_OR_LOD,
    ATR_VALUE,
    EMA_20_VALUE,
    HOD_VALUE,
    AVG_VOLUME_10,
)


def get_pullback_bar(fixture: dict) -> pd.Series:
    """bar[-2] — the low-volume pullback bar."""
    return fixture['bars'].iloc[-2]

def get_resume_bar(fixture: dict) -> pd.Series:
    """bar[-1] — the high-volume resume bar (entry at its close)."""
    return fixture['bars'].iloc[-1]

def get_history_bars(fixture: dict) -> pd.DataFrame:
    """All bars except the last two (for EMA calculation)."""
    return fixture['bars'].iloc[:-2]


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 1: Scanner gate
# Blueprint ref: Section 4.4 "Scanner Criteria"
# ─────────────────────────────────────────────────────────────────────────────

class TestTrendScanner(unittest.TestCase):
    """
    run_scanner() filters for late-day momentum setups.

    Filters:
      1. Near HOD (long) or LOD (short):
         Method A: within 3% of HOD/LOD
         Method B: within 2× ATR of HOD/LOD
         Either method passing = accept (more permissive)
      2. Volume > 1.5× average intraday volume
      3. Sector strength > 0 (positive sector momentum)
    """

    def setUp(self):
        self.strategy = TrendFollowStrategy()

    def test_accepts_valid_near_hod_candidate(self):
        """Price near HOD, good volume, positive sector → accepted."""
        c = SCANNER_VALID_NEAR_HOD
        result = self.strategy.run_scanner([{
            'ticker':              c['ticker'],
            'current_price':       c['current_price'],
            'hod':                 c['hod'],
            'lod':                 c['lod'],
            'atr':                 c['atr'],
            'avg_intraday_volume': c['avg_intraday_volume'],
            'current_volume':      c['current_volume'],
            'sector_strength':     c['sector_strength'],
        }])
        self.assertIn(c['ticker'], result,
                      "Valid near-HOD candidate should pass scanner")

    def test_rejects_price_not_near_hod_or_lod(self):
        """
        Price in the middle of the day's range — no trend setup.
        Blueprint: "if not (near_hod or near_lod): return False"
        """
        c = SCANNER_NOT_NEAR_HOD_OR_LOD
        result = self.strategy.run_scanner([{
            'ticker':              c['ticker'],
            'current_price':       c['current_price'],
            'hod':                 c['hod'],
            'lod':                 c['lod'],
            'atr':                 c['atr'],
            'avg_intraday_volume': c['avg_intraday_volume'],
            'current_volume':      80_000,
            'sector_strength':     0.5,
        }])
        self.assertNotIn(c['ticker'], result,
                         "Price not near HOD/LOD should be rejected")

    def test_rejects_low_volume(self):
        """
        Blueprint: "Volume confirmation > 1.5× average"
        Low volume = weak momentum, not worth chasing.
        """
        c = SCANNER_VALID_NEAR_HOD
        result = self.strategy.run_scanner([{
            'ticker':              c['ticker'],
            'current_price':       c['current_price'],
            'hod':                 c['hod'],
            'lod':                 c['lod'],
            'atr':                 c['atr'],
            'avg_intraday_volume': c['avg_intraday_volume'],
            'current_volume':      40_000,  # 0.8× avg — below 1.5× threshold
            'sector_strength':     0.5,
        }])
        self.assertNotIn(c['ticker'], result,
                         "Volume 0.8× avg should be rejected (< 1.5× threshold)")

    def test_rejects_negative_sector_strength(self):
        """
        Blueprint: "Sector strength > 0"
        Don't buy a stock near HOD if its whole sector is selling off.
        """
        c = SCANNER_VALID_NEAR_HOD
        result = self.strategy.run_scanner([{
            'ticker':              c['ticker'],
            'current_price':       c['current_price'],
            'hod':                 c['hod'],
            'lod':                 c['lod'],
            'atr':                 c['atr'],
            'avg_intraday_volume': c['avg_intraday_volume'],
            'current_volume':      c['current_volume'],
            'sector_strength':    -0.5,   # negative sector
        }])
        self.assertNotIn(c['ticker'], result,
                         "Negative sector strength should be rejected")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 2: EMA calculation
# Blueprint ref: Section 7.1 (EMA period is the WFO parameter)
# ─────────────────────────────────────────────────────────────────────────────

class TestEMACalculation(unittest.TestCase):
    """
    calculate_ema(bars, period=20) returns the current EMA value.

    EMA uses exponential weighting — recent bars matter more.
    The WFO-optimizable parameter is the period: grid 20, 30, 50.
    """

    def setUp(self):
        self.strategy = TrendFollowStrategy()

    def test_ema_on_flat_series_equals_mean(self):
        """
        If all prices are identical, EMA = that price (no directional bias).
        20 bars of $100.00 → EMA = $100.00
        """
        bars = pd.DataFrame({
            'open':   [100.0]*20, 'high':  [100.0]*20,
            'low':    [100.0]*20, 'close': [100.0]*20,
            'volume': [50_000]*20,
        }, index=pd.date_range('2024-01-15 10:00', periods=20, freq='5min'))
        ema = self.strategy.calculate_ema(bars, period=20)
        self.assertAlmostEqual(ema, 100.0, places=4)

    def test_ema_on_uptrend_lags_price(self):
        """
        On an uptrending series, EMA < current price (it lags).
        This is what creates the pullback-to-EMA setup.
        """
        history = get_history_bars(CLEAN_LONG_PULLBACK)
        ema = self.strategy.calculate_ema(history, period=20)
        last_price = float(history['close'].iloc[-1])
        self.assertLess(ema, last_price,
                        "EMA should lag behind price on an uptrend")

    def test_longer_period_lags_more(self):
        """
        A 50-period EMA lags further behind price than a 20-period EMA.
        This is the core WFO trade-off: faster EMA = more signals but noisier.
        """
        history = get_history_bars(CLEAN_LONG_PULLBACK)
        ema_20 = self.strategy.calculate_ema(history, period=20)
        ema_50 = self.strategy.calculate_ema(history, period=min(50, len(history)))
        # On an uptrend, both lag behind price, but 50-period lags more
        self.assertLess(ema_50, ema_20,
                        "50-period EMA should be below 20-period EMA on uptrend")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 3: Chandelier Stop calculation
# Blueprint ref: Section 4.4 "Exit Logic — Chandelier Exit"
# ─────────────────────────────────────────────────────────────────────────────

class TestChandelierStop(unittest.TestCase):
    """
    calculate_chandelier_stop(bars_since_entry, atr, direction) returns
    the current trailing stop level.

    LONG:  stop = highest_high_since_entry - 3.0 × ATR
    SHORT: stop = lowest_low_since_entry  + 3.0 × ATR

    The stop can only MOVE IN THE DIRECTION OF THE TRADE:
    - For LONG: stop can only rise (never fall)
    - For SHORT: stop can only fall (never rise)
    This "locks in" profit as price moves in our favour.
    """

    def setUp(self):
        self.strategy = TrendFollowStrategy()

    def test_long_chandelier_is_highest_high_minus_3atr(self):
        """
        LONG: stop = highest_high - 3×ATR
        2 bars with highs $107.00 and $109.00 → highest_high=$109.00
        stop = $109.00 - 3×$1.00 = $106.00
        """
        bars_since_entry = pd.DataFrame({
            'open':   [106.00, 107.50],
            'high':   [107.00, 109.00],  # highest = $109.00
            'low':    [105.50, 107.00],
            'close':  [106.50, 108.50],
            'volume': [60_000, 65_000],
        }, index=pd.date_range('2024-01-15 14:00', periods=2, freq='5min'))

        stop = self.strategy.calculate_chandelier_stop(
            bars_since_entry, ATR_VALUE, direction='LONG'
        )
        self.assertAlmostEqual(stop, 106.00, places=2,
                               msg="LONG Chandelier = highest_high - 3×ATR")

    def test_short_chandelier_is_lowest_low_plus_3atr(self):
        """
        SHORT: stop = lowest_low + 3×ATR
        2 bars with lows $97.00 and $95.00 → lowest_low=$95.00
        stop = $95.00 + 3×$1.00 = $98.00
        """
        bars_since_entry = pd.DataFrame({
            'open':   [104.00, 103.00],
            'high':   [104.50, 103.50],
            'low':    [ 97.00,  95.00],  # lowest = $95.00
            'close':  [103.50, 102.50],
            'volume': [60_000, 65_000],
        }, index=pd.date_range('2024-01-15 14:00', periods=2, freq='5min'))

        stop = self.strategy.calculate_chandelier_stop(
            bars_since_entry, ATR_VALUE, direction='SHORT'
        )
        self.assertAlmostEqual(stop, 98.00, places=2,
                               msg="SHORT Chandelier = lowest_low + 3×ATR")

    def test_chandelier_stop_rises_as_price_makes_new_highs(self):
        """
        As a LONG trade makes new highs, the Chandelier stop rises.
        This is how the trailing stop 'locks in' profit.
        Bar 1 high: $107 → stop = $104
        Bar 2 high: $110 → stop = $107  (rose by $3)
        """
        bars_one = pd.DataFrame({
            'high': [107.0], 'low': [105.0],
            'open': [106.0], 'close': [106.5], 'volume': [50_000]
        }, index=pd.date_range('2024-01-15 14:00', periods=1, freq='5min'))

        bars_two = pd.DataFrame({
            'high': [107.0, 110.0], 'low': [105.0, 108.0],
            'open': [106.0, 108.5], 'close': [106.5, 109.5], 'volume': [50_000, 55_000]
        }, index=pd.date_range('2024-01-15 14:00', periods=2, freq='5min'))

        stop_bar1 = self.strategy.calculate_chandelier_stop(bars_one, ATR_VALUE, 'LONG')
        stop_bar2 = self.strategy.calculate_chandelier_stop(bars_two, ATR_VALUE, 'LONG')

        self.assertAlmostEqual(stop_bar1, 104.0, places=2)  # 107 - 3
        self.assertAlmostEqual(stop_bar2, 107.0, places=2)  # 110 - 3
        self.assertGreater(stop_bar2, stop_bar1,
                           "Chandelier stop should rise as price makes new highs")

    def test_single_bar_initial_stop(self):
        """
        On the very first bar after entry, stop is based on that single bar's
        high (LONG) or low (SHORT). This is the initial stop level.
        Entry bar high=$106.20 → initial LONG stop = $106.20 - $3.00 = $103.20
        """
        entry_bar = pd.DataFrame({
            'open': [106.00], 'high': [106.20],
            'low':  [105.00], 'close': [106.00], 'volume': [70_000]
        }, index=pd.date_range('2024-01-15 14:05', periods=1, freq='5min'))

        stop = self.strategy.calculate_chandelier_stop(entry_bar, ATR_VALUE, 'LONG')
        self.assertAlmostEqual(stop, 103.20, places=2,
                               msg="Initial Chandelier stop = entry bar high - 3×ATR")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 4: Volume pattern
# Blueprint ref: Section 4.4 "Entry Logic — Pullback entry"
# ─────────────────────────────────────────────────────────────────────────────

class TestVolumePattern(unittest.TestCase):
    """
    check_volume_pattern(pullback_bar, resume_bar, avg_volume) returns True
    if the volume pattern confirms a healthy pullback + resume.

    Requirements:
      - pullback_bar.volume < avg_volume        (volume declined on pullback)
      - resume_bar.volume   > avg_volume × 1.3  (volume surged on resume)
    """

    def setUp(self):
        self.strategy = TrendFollowStrategy()

    def test_valid_volume_pattern(self):
        """Pullback low-vol + resume high-vol = valid pattern."""
        pullback = pd.Series({'volume': 30_000})
        resume   = pd.Series({'volume': 70_000})
        result   = self.strategy.check_volume_pattern(pullback, resume, AVG_VOLUME_10)
        self.assertTrue(result, "30k pullback, 70k resume should be valid pattern")

    def test_high_volume_pullback_rejected(self):
        """
        Aggressive selling on the pullback = not a healthy pause.
        Blueprint: volume must DECLINE on pullback.
        """
        pullback = pd.Series({'volume': 70_000})  # high vol ✗
        resume   = pd.Series({'volume': 70_000})
        result   = self.strategy.check_volume_pattern(pullback, resume, AVG_VOLUME_10)
        self.assertFalse(result, "High pullback volume should be rejected")

    def test_low_volume_resume_rejected(self):
        """
        Insufficient volume on the resume bar = weak conviction.
        Threshold: avg × 1.3 = 50,000 × 1.3 = 65,000.
        55,000 < 65,000 → rejected.
        """
        pullback = pd.Series({'volume': 30_000})
        resume   = pd.Series({'volume': 55_000})  # below 65k threshold ✗
        result   = self.strategy.check_volume_pattern(pullback, resume, AVG_VOLUME_10)
        self.assertFalse(result, "Insufficient resume volume should be rejected")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 5: Signal generation
# Blueprint ref: Section 4.4 "Entry Logic" + Section 6.1 Regime Mapping
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalGeneration(unittest.TestCase):
    """
    generate_signal(pullback_bar, resume_bar, ema_20, atr, hmm_state,
                    avg_volume_10) returns a signal dict or None.

    DECISION SEQUENCE:
      1. Regime gate      → None if Calm
      2. EMA proximity    → resume_bar.close within 0.2% of ema_20?
                           Wait — pullback_bar.close within 0.2% of ema_20
      3. Volume pattern   → declined on pullback, surged on resume?
      4. Compute levels   → entry=resume_bar.close,
                            initial_stop=Chandelier(resume_bar high/low, atr)
      5. Return signal

    Signal dict keys:
        direction     : 'LONG' or 'SHORT'
        entry_price   : resume_bar['close']
        initial_stop  : Chandelier stop at entry
        atr           : passed through (for stop updates in session replayer)
    """

    def setUp(self):
        self.strategy = TrendFollowStrategy()

    # ── Happy path ────────────────────────────────────────────────────────────

    def test_generates_long_signal_on_valid_pullback(self):
        """Scenario 1: uptrend + EMA touch + volume pattern → LONG."""
        f = CLEAN_LONG_PULLBACK
        signal = self.strategy.generate_signal(
            pullback_bar=get_pullback_bar(f),
            resume_bar=get_resume_bar(f),
            ema_20=f['ema_20'], atr=f['atr'],
            hmm_state='Normal',
            avg_volume_10=f['avg_volume_10'],
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal['direction'], 'LONG')

    def test_generates_short_signal_on_valid_pullback(self):
        """Scenario 2: downtrend + EMA touch + volume pattern → SHORT."""
        f = CLEAN_SHORT_PULLBACK
        signal = self.strategy.generate_signal(
            pullback_bar=get_pullback_bar(f),
            resume_bar=get_resume_bar(f),
            ema_20=f['ema_20'], atr=f['atr'],
            hmm_state='Normal',
            avg_volume_10=f['avg_volume_10'],
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal['direction'], 'SHORT')

    def test_generates_signal_in_stress_regime(self):
        """
        Blueprint: "Trend Following allowed in Normal AND Stress."
        Stress regime means strong trending — exactly the right conditions.
        """
        f = CLEAN_LONG_PULLBACK
        signal = self.strategy.generate_signal(
            pullback_bar=get_pullback_bar(f),
            resume_bar=get_resume_bar(f),
            ema_20=f['ema_20'], atr=f['atr'],
            hmm_state='Stress',
            avg_volume_10=f['avg_volume_10'],
        )
        self.assertIsNotNone(signal, "Stress regime should be allowed for Trend Follow")

    # ── Regime gate ───────────────────────────────────────────────────────────

    def test_rejects_calm_regime(self):
        """
        Blueprint: "Best HMM Regimes: Normal, Stress — skip during Calm"
        Calm = range-bound market = no trend to follow.
        """
        f = CLEAN_LONG_PULLBACK
        signal = self.strategy.generate_signal(
            pullback_bar=get_pullback_bar(f),
            resume_bar=get_resume_bar(f),
            ema_20=f['ema_20'], atr=f['atr'],
            hmm_state='Calm',
            avg_volume_10=f['avg_volume_10'],
        )
        self.assertIsNone(signal, "Calm regime must block Trend Follow")

    # ── Volume gate ───────────────────────────────────────────────────────────

    def test_rejects_high_volume_pullback(self):
        """Pullback on high volume = aggressive selling, not a pause."""
        f = PULLBACK_HIGH_VOLUME
        signal = self.strategy.generate_signal(
            pullback_bar=get_pullback_bar(f),
            resume_bar=get_resume_bar(f),
            ema_20=f['ema_20'], atr=f['atr'],
            hmm_state='Normal',
            avg_volume_10=f['avg_volume_10'],
        )
        self.assertIsNone(signal, "High-volume pullback should be rejected")

    def test_rejects_low_volume_resume(self):
        """Resume bar without volume surge = no conviction behind the move."""
        f = RESUME_LOW_VOLUME
        signal = self.strategy.generate_signal(
            pullback_bar=get_pullback_bar(f),
            resume_bar=get_resume_bar(f),
            ema_20=f['ema_20'], atr=f['atr'],
            hmm_state='Normal',
            avg_volume_10=f['avg_volume_10'],
        )
        self.assertIsNone(signal, "Low resume volume should be rejected")

    # ── Signal structure ──────────────────────────────────────────────────────

    def test_entry_is_resume_bar_close(self):
        """
        Entry is the CLOSE of the resume bar — the bar that confirmed
        the move resumed. (On 5-min bars, we use close, not next-bar-open,
        because the 5-min bar is already 5 minutes of price action.)
        """
        f = CLEAN_LONG_PULLBACK
        signal = self.strategy.generate_signal(
            pullback_bar=get_pullback_bar(f),
            resume_bar=get_resume_bar(f),
            ema_20=f['ema_20'], atr=f['atr'],
            hmm_state='Normal',
            avg_volume_10=f['avg_volume_10'],
        )
        self.assertAlmostEqual(signal['entry_price'], f['expected_entry'], places=2,
                               msg="Entry must be resume bar close")

    def test_initial_stop_is_chandelier(self):
        """
        Initial stop = resume bar high - 3×ATR (LONG)
        resume bar high = $106.20, ATR=$1.00 → stop = $103.20
        """
        f = CLEAN_LONG_PULLBACK
        signal = self.strategy.generate_signal(
            pullback_bar=get_pullback_bar(f),
            resume_bar=get_resume_bar(f),
            ema_20=f['ema_20'], atr=f['atr'],
            hmm_state='Normal',
            avg_volume_10=f['avg_volume_10'],
        )
        self.assertAlmostEqual(signal['initial_stop'], f['expected_initial_stop'],
                               places=2, msg="Initial stop = Chandelier on entry bar")

    def test_signal_contains_all_required_fields(self):
        """Downstream session replayer needs these keys."""
        f = CLEAN_LONG_PULLBACK
        signal = self.strategy.generate_signal(
            pullback_bar=get_pullback_bar(f),
            resume_bar=get_resume_bar(f),
            ema_20=f['ema_20'], atr=f['atr'],
            hmm_state='Normal',
            avg_volume_10=f['avg_volume_10'],
        )
        self.assertIsNotNone(signal)
        for key in {'direction', 'entry_price', 'initial_stop', 'atr'}:
            self.assertIn(key, signal, f"Signal missing required field: '{key}'")


if __name__ == '__main__':
    unittest.main(verbosity=2)
