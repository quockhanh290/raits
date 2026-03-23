# tests/test_orb_strategy.py
#
# ORB Strategy test suite — Phase 1B, Weeks 9-10
#
# TDD DISCIPLINE: This file was written BEFORE raits/strategies/orb.py existed.
# Every assertion describes what the system SHOULD do per the blueprint spec.
# It does NOT describe what the code currently does (nothing exists yet).
#
# Run with:  pytest tests/test_orb_strategy.py -v
#
# Target: 29/29 tests passing before Week 10 is complete.
#
# Test class structure:
#   TestORBScanner           (7 tests)  — run_scanner() gate
#   TestOpeningRangeCalc     (4 tests)  — calculate_opening_range()
#   TestFakeoutDetection     (5 tests)  — check_fakeout()
#   TestIntradayRVol         (3 tests)  — calculate_intraday_rvol()
#   TestSignalGeneration    (10 tests)  — generate_signal() end-to-end

import unittest
import pandas as pd

# ── This import will FAIL until Step 5 (orb.py) is created. ──────────────────
# That is expected and correct. The tests define the contract; the
# implementation must satisfy it.
from raits.strategies.orb import ORBStrategy

# Fixtures: pre-built synthetic OHLCV scenarios
from tests.fixtures.orb_fixtures import (
    CLEAN_GAP_UP_BREAKOUT,
    FAKEOUT_BREAKOUT,
    STRESS_REGIME_VALID_SETUP,
    CLEAN_GAP_DOWN_BREAKDOWN,
    INSUFFICIENT_GAP,
    NARROW_OPENING_RANGE,
    ATR_VALUE,
    HIST_AVG_VOL_9_46,
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_breakout_candle(fixture: dict) -> pd.Series:
    """Return the last bar (9:46) from a fixture's bar DataFrame."""
    return fixture['bars'].iloc[-1]

def get_or_bars(fixture: dict) -> pd.DataFrame:
    """Return only the opening range bars (all bars except the last)."""
    return fixture['bars'].iloc[:-1]


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 1: Scanner gate
# Blueprint ref: Section 4.2 "Scanner Criteria (Executed at 9:35 AM ET)"
# ─────────────────────────────────────────────────────────────────────────────

class TestORBScanner(unittest.TestCase):
    """
    run_scanner() takes a list of candidate dicts and returns a list of the
    tickers that pass all scanner filters.

    Filters (all must pass):
      1. gap_pct = abs(open - prev_close) / prev_close >= 0.02  (2%)
      2. 10 <= price <= 200
      3. premarket_volume > 50,000  OR  opening_5min_volume > 2× (avg_daily_volume / 78)
    """

    def setUp(self):
        self.strategy = ORBStrategy()

    # ── Filter 1: Gap percentage ──────────────────────────────────────────────

    def test_scanner_accepts_valid_gap_up(self):
        """
        Blueprint: "Gap filter (REQUIRED) — minimum ±2% gap"
        A 3% gap-up with sufficient volume should pass.
        """
        f = CLEAN_GAP_UP_BREAKOUT
        candidates = [{'ticker': 'TSLA', 'prev_close': f['prev_close'],
                        'open_price': f['open_price'],
                        'premarket_volume': f['premarket_volume'],
                        'avg_daily_volume': f['avg_daily_volume'],
                        'opening_5min_volume': f['opening_5min_volume']}]

        result = self.strategy.run_scanner(candidates)
        self.assertIn('TSLA', result, "3% gap-up with volume should pass scanner")

    def test_scanner_accepts_valid_gap_down(self):
        """
        Blueprint: "minimum ±2% gap" — abs() means shorts qualify too.
        A -3.5% gap-down should pass.
        """
        f = CLEAN_GAP_DOWN_BREAKDOWN
        candidates = [{'ticker': 'AAPL', 'prev_close': f['prev_close'],
                        'open_price': f['open_price'],
                        'premarket_volume': f['premarket_volume'],
                        'avg_daily_volume': f['avg_daily_volume'],
                        'opening_5min_volume': f['opening_5min_volume']}]

        result = self.strategy.run_scanner(candidates)
        self.assertIn('AAPL', result, "3.5% gap-down with volume should pass scanner")

    def test_scanner_rejects_insufficient_gap(self):
        """
        Blueprint: gap_pct < 0.02 → return False
        A 0.5% gap is noise, not a catalyst. Must be rejected.
        """
        f = INSUFFICIENT_GAP
        candidates = [{'ticker': 'MSFT', 'prev_close': f['prev_close'],
                        'open_price': f['open_price'],
                        'premarket_volume': f['premarket_volume'],
                        'avg_daily_volume': f['avg_daily_volume'],
                        'opening_5min_volume': f['opening_5min_volume']}]

        result = self.strategy.run_scanner(candidates)
        self.assertNotIn('MSFT', result, "0.5% gap should be rejected (< 2% minimum)")

    # ── Filter 2: Price range ────────────────────────────────────────────────

    def test_scanner_rejects_price_below_minimum(self):
        """
        Blueprint: "Price range filter — $10–$200"
        Stocks below $10 are penny stocks with wide spreads and thin books.
        """
        candidates = [{'ticker': 'PENNY', 'prev_close': 8.00,
                        'open_price': 8.50,      # 6.25% gap — would pass gap filter
                        'premarket_volume': 75_000,
                        'avg_daily_volume': 1_200_000,
                        'opening_5min_volume': 200_000}]

        result = self.strategy.run_scanner(candidates)
        self.assertNotIn('PENNY', result, "Price $8.50 should be rejected (< $10 minimum)")

    def test_scanner_rejects_price_above_maximum(self):
        """
        Blueprint: "Price range filter — $10–$200"
        Stocks above $200 require very large dollar amounts per share,
        which conflicts with PDT position sizing constraints.
        """
        candidates = [{'ticker': 'EXPEN', 'prev_close': 240.00,
                        'open_price': 246.00,    # 2.5% gap — would pass gap filter
                        'premarket_volume': 75_000,
                        'avg_daily_volume': 1_200_000,
                        'opening_5min_volume': 200_000}]

        result = self.strategy.run_scanner(candidates)
        self.assertNotIn('EXPEN', result, "Price $246 should be rejected (> $200 maximum)")

    # ── Filter 3: Volume (two-path logic) ────────────────────────────────────

    def test_scanner_accepts_with_opening_volume_fallback(self):
        """
        Blueprint: Option B fallback — if premarket_volume == 0,
        accept when opening_5min_volume > 2× (avg_daily_volume / 78).

        avg_daily_volume = 1,200,000
        avg_5min = 1,200,000 / 78 = 15,385
        threshold = 2.0 × 15,385 = 30,769
        opening_5min_volume = 200,000 > 30,769 ✓
        """
        candidates = [{'ticker': 'NVDA', 'prev_close': 100.00,
                        'open_price': 103.00,     # 3% gap
                        'premarket_volume': 0,     # no premarket data
                        'avg_daily_volume': 1_200_000,
                        'opening_5min_volume': 200_000}]

        result = self.strategy.run_scanner(candidates)
        self.assertIn('NVDA', result,
                      "Opening 5-min volume fallback should accept when premarket data absent")

    def test_scanner_rejects_no_volume(self):
        """
        Blueprint: Both Option A and Option B fail → return False
        Neither pre-market nor opening volume confirm sufficient interest.
        """
        candidates = [{'ticker': 'THIN', 'prev_close': 100.00,
                        'open_price': 103.00,     # 3% gap ✓
                        'premarket_volume': 10_000,  # too low (< 50,000)
                        'avg_daily_volume': 1_200_000,
                        'opening_5min_volume': 5_000}]   # too low (< 30,769)

        result = self.strategy.run_scanner(candidates)
        self.assertNotIn('THIN', result, "Insufficient volume should be rejected")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 2: Opening Range calculation
# Blueprint ref: Section 4.2 "Opening Range Definition"
# ─────────────────────────────────────────────────────────────────────────────

class TestOpeningRangeCalc(unittest.TestCase):
    """
    calculate_opening_range(bars, atr) extracts OR high and OR low from the
    9:31–9:45 bars, then validates the range is neither too narrow nor too wide.

    Returns: (or_high, or_low, status)
      status == 'VALID'            → usable range
      status == 'RANGE_TOO_NARROW' → or_range < 0.5 × ATR
      status == 'RANGE_TOO_WIDE'   → or_range > 5.0 × ATR
    """

    def setUp(self):
        self.strategy = ORBStrategy()

    def test_or_returns_correct_high_and_low(self):
        """
        OR high and OR low must be the exact max/min of all bars in the window.
        Fixture has OR high = 104.00 (bar at 9:40) and OR low = 102.50 (bar at 9:32).
        """
        bars = get_or_bars(CLEAN_GAP_UP_BREAKOUT)
        or_high, or_low, status = self.strategy.calculate_opening_range(bars, ATR_VALUE)

        self.assertEqual(status, 'VALID')
        self.assertAlmostEqual(or_high, 104.00, places=2,
                               msg="OR high should be $104.00")
        self.assertAlmostEqual(or_low, 102.50, places=2,
                               msg="OR low should be $102.50")

    def test_or_rejects_narrow_range(self):
        """
        Blueprint: "if or_range < max(0.5 * atr, 0.20): return RANGE_TOO_NARROW"
        Fixture range = $0.15, which is less than 0.5 × $2.00 = $1.00.
        """
        bars = NARROW_OPENING_RANGE['bars']   # already OR-only bars
        atr  = NARROW_OPENING_RANGE['atr']

        or_high, or_low, status = self.strategy.calculate_opening_range(bars, atr)

        self.assertEqual(status, 'RANGE_TOO_NARROW',
                         "OR range $0.15 should be rejected (< 0.5× ATR = $1.00)")
        self.assertIsNone(or_high, "or_high should be None on rejection")
        self.assertIsNone(or_low,  "or_low should be None on rejection")

    def test_or_rejects_wide_range(self):
        """
        Blueprint: "if or_range > 5.0 * atr: return RANGE_TOO_WIDE"
        A $15 range when ATR=$2 suggests a data error or extreme event.
        We build this synthetically rather than using a fixture.
        """
        # Construct a bars DataFrame with or_high=115.00, or_low=100.00
        # Range = $15 = 7.5× ATR — exceeds 5.0× ceiling
        bars = pd.DataFrame({
            'open':  [100.00, 115.00],
            'high':  [100.50, 115.00],
            'low':   [100.00, 100.00],
            'close': [100.25, 107.50],
            'volume':[80_000,  70_000],
        }, index=pd.to_datetime(['2024-01-15 09:31', '2024-01-15 09:32']))

        or_high, or_low, status = self.strategy.calculate_opening_range(bars, ATR_VALUE)

        self.assertEqual(status, 'RANGE_TOO_WIDE',
                         "OR range $15 should be rejected (7.5× ATR > 5.0× ceiling)")

    def test_or_valid_status_string(self):
        """
        When the range is acceptable, status must be the string 'VALID'
        (not True, not 1, not 'valid' — exact string match).
        The router downstream does: if status == 'VALID'
        """
        bars = get_or_bars(CLEAN_GAP_UP_BREAKOUT)
        _, _, status = self.strategy.calculate_opening_range(bars, ATR_VALUE)
        self.assertEqual(status, 'VALID')


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 3: Fakeout detection
# Blueprint ref: Section 4.2 "Failure Condition — The Fakeout"
# ─────────────────────────────────────────────────────────────────────────────

class TestFakeoutDetection(unittest.TestCase):
    """
    check_fakeout(candle, direction) returns True if the candle looks like a
    false breakout (trade should be rejected), False if it looks genuine.

    For LONG breakouts — check for Shooting Star:
        upper_wick = high - max(close, open)
        fakeout if upper_wick > 0.5 × body

    For SHORT breakouts — check for Hammer:
        lower_wick = min(close, open) - low
        fakeout if lower_wick > 0.5 × body

    Doji candles (body < $0.01) are always treated as fakeouts.
    """

    def setUp(self):
        self.strategy = ORBStrategy()

    def test_detects_shooting_star_on_long(self):
        """
        Fakeout breakout candle: body=$0.10, upper_wick=$1.35 → 1350% of body.
        Blueprint: wick > 50% of body → fakeout = True
        """
        candle = get_breakout_candle(FAKEOUT_BREAKOUT)
        result = self.strategy.check_fakeout(candle, direction='LONG')
        self.assertTrue(result, "Shooting star (upper wick 1350% of body) should be a fakeout")

    def test_accepts_clean_bullish_candle(self):
        """
        Clean breakout candle: body=$0.65, upper_wick=$0.15 → 23% of body.
        Blueprint: wick < 50% → fakeout = False (valid breakout)
        """
        candle = get_breakout_candle(CLEAN_GAP_UP_BREAKOUT)
        result = self.strategy.check_fakeout(candle, direction='LONG')
        self.assertFalse(result, "Clean candle (upper wick 23% of body) should NOT be a fakeout")

    def test_detects_hammer_on_short(self):
        """
        For short breakdowns, rejection manifests as a Hammer (large lower wick).
        Construct a candle with lower_wick > 50% of body.
        """
        # open=96.00, close=95.60 (bearish), low=93.50 (hammer spike down then recovery)
        # body = |95.60 - 96.00| = 0.40
        # lower_wick = 95.60 - 93.50 = 2.10  →  2.10/0.40 = 525%  (>> 50%)
        hammer_candle = pd.Series({
            'open': 96.00, 'high': 96.05, 'low': 93.50, 'close': 95.60, 'volume': 250_000
        })
        result = self.strategy.check_fakeout(hammer_candle, direction='SHORT')
        self.assertTrue(result, "Hammer candle (lower wick 525% of body) should be a fakeout on short")

    def test_accepts_clean_bearish_candle(self):
        """
        Clean short breakdown candle from Scenario 4.
        body=$0.65, lower_wick=$0.10 → 15% of body → NOT a fakeout.
        """
        candle = get_breakout_candle(CLEAN_GAP_DOWN_BREAKDOWN)
        result = self.strategy.check_fakeout(candle, direction='SHORT')
        self.assertFalse(result, "Clean bearish candle (lower wick 15%) should NOT be a fakeout")

    def test_treats_doji_as_fakeout(self):
        """
        Blueprint: "if body < 0.01: return True  (treat doji as potential fakeout)"
        A doji shows indecision — buyers and sellers exactly balanced.
        A breakout candle should show conviction (real body).
        """
        doji_candle = pd.Series({
            'open': 104.05, 'high': 104.85, 'low': 103.50, 'close': 104.05,
            'volume': 250_000
        })
        result = self.strategy.check_fakeout(doji_candle, direction='LONG')
        self.assertTrue(result, "Doji candle (body < $0.01) should be treated as fakeout")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 4: Intraday RVol
# Blueprint ref: Section 4.2 "Calculate Intraday Relative Volume"
# ─────────────────────────────────────────────────────────────────────────────

class TestIntradayRVol(unittest.TestCase):
    """
    calculate_intraday_rvol(current_volume, historical_avg_volume) returns
    the ratio of current bar volume to the historical average volume for that
    same time of day.

    This is intentionally simple — it's a pure division with a guard for zero.
    The complexity lives in HOW the historical avg is computed (done upstream);
    this method just does the ratio.
    """

    def setUp(self):
        self.strategy = ORBStrategy()

    def test_rvol_calculation_is_correct(self):
        """
        250,000 / 80,000 = 3.125
        Blueprint requires RVol > 2.0 for entry confirmation.
        """
        rvol = self.strategy.calculate_intraday_rvol(
            current_volume=250_000,
            historical_avg_volume=HIST_AVG_VOL_9_46
        )
        self.assertAlmostEqual(rvol, 3.125, places=3)

    def test_rvol_exactly_at_threshold(self):
        """
        RVol of exactly 2.0 should be accepted (threshold is >=, not >).
        160,000 / 80,000 = 2.0
        """
        rvol = self.strategy.calculate_intraday_rvol(
            current_volume=160_000,
            historical_avg_volume=HIST_AVG_VOL_9_46
        )
        self.assertAlmostEqual(rvol, 2.0, places=3)

    def test_rvol_below_threshold(self):
        """
        RVol of 1.25 (100,000 / 80,000) — below the 2.0 minimum.
        generate_signal will use this to reject the trade.
        This test just verifies the calculation is correct.
        """
        rvol = self.strategy.calculate_intraday_rvol(
            current_volume=100_000,
            historical_avg_volume=HIST_AVG_VOL_9_46
        )
        self.assertAlmostEqual(rvol, 1.25, places=3)


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 5: Signal generation (end-to-end)
# Blueprint ref: Section 4.2 "Entry Logic" + Section 6.2 "Master Strategy Router"
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalGeneration(unittest.TestCase):
    """
    generate_signal(candle, or_high, or_low, vwap, rvol, hmm_state) is the
    main entry point. It wires together all the sub-checks and either returns
    a signal dict or None.

    Internal decision sequence (ORDER MATTERS):
      1. HMM regime gate  → None if Stress
      2. Direction check  → None if candle doesn't break OR high or low
      3. RVol check       → None if rvol < 2.0
      4. Fakeout check    → None if wick > 50% of body
      5. Compute levels   → entry, stop, target
      6. Return signal dict

    Signal dict keys (all must be present):
      direction   : 'LONG' or 'SHORT'
      entry_price : candle.close (planned trigger price)
      stop_loss   : min(or_low, vwap) for LONG / max(or_high, vwap) for SHORT
      target      : entry + 2×risk (LONG) / entry - 2×risk (SHORT)
      rvol        : the RVol value passed in
    """

    def setUp(self):
        self.strategy = ORBStrategy()

    # ── Happy path: valid signals ─────────────────────────────────────────────

    def test_generates_long_signal_on_clean_breakout(self):
        """
        Full Scenario 1: gap ✓, valid OR ✓, clean breakout candle ✓,
        RVol 3.125× ✓, Normal regime ✓ → LONG signal expected.
        """
        f = CLEAN_GAP_UP_BREAKOUT
        candle = get_breakout_candle(f)
        rvol = self.strategy.calculate_intraday_rvol(
            int(candle['volume']), f['hist_avg_vol_9_46']
        )

        signal = self.strategy.generate_signal(
            candle=candle,
            or_high=f['or_high'],
            or_low=f['or_low'],
            vwap=f['vwap'],
            rvol=rvol,
            hmm_state='Normal',
        )

        self.assertIsNotNone(signal, "Clean breakout should produce a signal")
        self.assertEqual(signal['direction'], 'LONG')

    def test_generates_short_signal_on_clean_breakdown(self):
        """
        Full Scenario 4: gap-down ✓, valid OR ✓, clean breakdown candle ✓,
        RVol 3.125× ✓, Normal regime ✓ → SHORT signal expected.
        """
        f = CLEAN_GAP_DOWN_BREAKDOWN
        candle = get_breakout_candle(f)
        rvol = self.strategy.calculate_intraday_rvol(
            int(candle['volume']), f['hist_avg_vol_9_46']
        )

        signal = self.strategy.generate_signal(
            candle=candle,
            or_high=f['or_high'],
            or_low=f['or_low'],
            vwap=f['vwap'],
            rvol=rvol,
            hmm_state='Normal',
        )

        self.assertIsNotNone(signal, "Clean breakdown should produce a signal")
        self.assertEqual(signal['direction'], 'SHORT')

    def test_generates_signal_in_calm_regime(self):
        """
        ORB is allowed in BOTH Calm and Normal regimes.
        Verify Calm doesn't get accidentally blocked.
        """
        f = CLEAN_GAP_UP_BREAKOUT
        candle = get_breakout_candle(f)
        rvol = self.strategy.calculate_intraday_rvol(
            int(candle['volume']), f['hist_avg_vol_9_46']
        )

        signal = self.strategy.generate_signal(
            candle=candle,
            or_high=f['or_high'], or_low=f['or_low'],
            vwap=f['vwap'], rvol=rvol,
            hmm_state='Calm',
        )
        self.assertIsNotNone(signal, "Calm regime should be allowed for ORB")

    # ── Regime gate ───────────────────────────────────────────────────────────

    def test_rejects_stress_regime(self):
        """
        Blueprint: "Best HMM Regimes: Calm, Normal (skip during Stress)"
        Even a perfect setup must be blocked during Stress.
        This tests the FIRST check inside generate_signal.
        """
        f = CLEAN_GAP_UP_BREAKOUT
        candle = get_breakout_candle(f)
        rvol = self.strategy.calculate_intraday_rvol(
            int(candle['volume']), f['hist_avg_vol_9_46']
        )

        signal = self.strategy.generate_signal(
            candle=candle,
            or_high=f['or_high'], or_low=f['or_low'],
            vwap=f['vwap'], rvol=rvol,
            hmm_state='Stress',   # ← the only change from the clean scenario
        )
        self.assertIsNone(signal, "Stress regime must block ORB regardless of setup quality")

    # ── Fakeout gate ──────────────────────────────────────────────────────────

    def test_rejects_fakeout_breakout(self):
        """
        Blueprint: "Cancel trade immediately if breakout candle is Shooting Star"
        Scenario 2: upper wick is 1350% of body — unambiguous rejection.
        """
        f = FAKEOUT_BREAKOUT
        candle = get_breakout_candle(f)
        rvol = self.strategy.calculate_intraday_rvol(
            int(candle['volume']), f['hist_avg_vol_9_46']
        )

        signal = self.strategy.generate_signal(
            candle=candle,
            or_high=f['or_high'], or_low=f['or_low'],
            vwap=f['vwap'], rvol=rvol,
            hmm_state='Normal',
        )
        self.assertIsNone(signal, "Shooting star (fakeout) must be rejected")

    # ── RVol gate ─────────────────────────────────────────────────────────────

    def test_rejects_low_rvol(self):
        """
        Blueprint: "RVol >= 2.0 for entry confirmation"
        Same clean setup but volume = 100,000 → RVol = 1.25× — rejected.
        """
        f = CLEAN_GAP_UP_BREAKOUT
        candle = get_breakout_candle(f).copy()
        candle['volume'] = 100_000   # deliberately low
        low_rvol = self.strategy.calculate_intraday_rvol(100_000, f['hist_avg_vol_9_46'])
        # 100_000 / 80_000 = 1.25 — below 2.0 threshold

        signal = self.strategy.generate_signal(
            candle=candle,
            or_high=f['or_high'], or_low=f['or_low'],
            vwap=f['vwap'], rvol=low_rvol,
            hmm_state='Normal',
        )
        self.assertIsNone(signal, "RVol 1.25× must be rejected (< 2.0 minimum)")

    # ── Signal structure ──────────────────────────────────────────────────────

    def test_signal_contains_all_required_fields(self):
        """
        Any code that consumes a signal dict (backtester, router) expects
        these exact keys. Missing keys = KeyError downstream.
        """
        f = CLEAN_GAP_UP_BREAKOUT
        candle = get_breakout_candle(f)
        rvol = self.strategy.calculate_intraday_rvol(
            int(candle['volume']), f['hist_avg_vol_9_46']
        )
        signal = self.strategy.generate_signal(
            candle=candle,
            or_high=f['or_high'], or_low=f['or_low'],
            vwap=f['vwap'], rvol=rvol, hmm_state='Normal',
        )
        self.assertIsNotNone(signal)
        required_keys = {'direction', 'entry_price', 'stop_loss', 'target', 'rvol'}
        for key in required_keys:
            self.assertIn(key, signal, f"Signal missing required field: '{key}'")

    def test_long_stop_is_minimum_of_or_low_and_vwap(self):
        """
        Blueprint: "stop = min(or_low, vwap)" for long trades.
        Fixture: or_low=$102.50, vwap=$103.25 → stop must be $102.50.
        The lower of the two gives us the maximum protection distance.
        """
        f = CLEAN_GAP_UP_BREAKOUT
        candle = get_breakout_candle(f)
        rvol = self.strategy.calculate_intraday_rvol(
            int(candle['volume']), f['hist_avg_vol_9_46']
        )
        signal = self.strategy.generate_signal(
            candle=candle,
            or_high=f['or_high'], or_low=f['or_low'],
            vwap=f['vwap'], rvol=rvol, hmm_state='Normal',
        )
        self.assertAlmostEqual(signal['stop_loss'], f['expected_stop'], places=2,
                               msg="LONG stop should be min(or_low, vwap)")

    def test_long_target_is_2r(self):
        """
        Blueprint: "target = entry_price + 2 × (entry_price - stop_loss)"
        entry = $104.70, stop = $102.50, risk = $2.20, target = $109.10
        2R means we need 2× the risk to justify each trade.
        """
        f = CLEAN_GAP_UP_BREAKOUT
        candle = get_breakout_candle(f)
        rvol = self.strategy.calculate_intraday_rvol(
            int(candle['volume']), f['hist_avg_vol_9_46']
        )
        signal = self.strategy.generate_signal(
            candle=candle,
            or_high=f['or_high'], or_low=f['or_low'],
            vwap=f['vwap'], rvol=rvol, hmm_state='Normal',
        )
        self.assertAlmostEqual(signal['target'], f['expected_target'], places=2,
                               msg="LONG target should be entry + 2×risk (2R)")

    def test_short_stop_is_maximum_of_or_high_and_vwap(self):
        """
        Blueprint: "stop = max(or_high, vwap)" for short trades.
        Fixture: or_high=$97.50, vwap=$96.75 → stop must be $97.50.
        For shorts, stop is ABOVE entry — the higher value is the tighter stop.
        """
        f = CLEAN_GAP_DOWN_BREAKDOWN
        candle = get_breakout_candle(f)
        rvol = self.strategy.calculate_intraday_rvol(
            int(candle['volume']), f['hist_avg_vol_9_46']
        )
        signal = self.strategy.generate_signal(
            candle=candle,
            or_high=f['or_high'], or_low=f['or_low'],
            vwap=f['vwap'], rvol=rvol, hmm_state='Normal',
        )
        self.assertAlmostEqual(signal['stop_loss'], f['expected_stop'], places=2,
                               msg="SHORT stop should be max(or_high, vwap)")


if __name__ == '__main__':
    unittest.main(verbosity=2)
