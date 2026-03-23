# tests/fixtures/orb_fixtures.py
#
# Synthetic 1-minute OHLCV DataFrames for ORB strategy testing.
#
# WHY SYNTHETIC DATA INSTEAD OF REAL DATA?
# -----------------------------------------
# Real market data has two problems for unit tests:
#   1. It changes — a live API call today returns different data tomorrow,
#      making tests non-deterministic.
#   2. It's ambiguous — real bars don't perfectly isolate one behaviour.
#      We need a bar with *exactly* a 23% wick to test the fakeout boundary.
#
# Synthetic fixtures give us complete control: every price level is chosen
# to test exactly one rule from the blueprint spec. Nothing is accidental.
#
# TIMELINE ALL FIXTURES FOLLOW
# ------------------------------
# Base date: 2024-01-15 (Monday, valid US trading day)
# prev_close: always $100.00 (or $100.00 for short side)
# OR bars:    9:31 AM - 9:45 AM  (15 bars, 1-minute resolution)
#             (9:30 AM bar = opening print, excluded from OR per blueprint)
# Breakout:   9:46 AM bar
# ATR(14):    $2.00  (used for OR range validation: must be 0.5x-5.0x ATR)
# VWAP:       $103.25 (precomputed for long scenarios, passed in by caller)

import pandas as pd
import numpy as np
from datetime import datetime


# ──────────────────────────────────────────────────────────────────────────────
# SHARED CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

BASE_DATE = '2024-01-15'

# ATR value used in all fixtures.
# In production this would be calculated from 14-day daily bars.
# Here it is fixed so OR range validation is predictable.
ATR_VALUE = 2.00

# Historical average volume for the 9:46 AM time slot.
# In production this is the mean volume of the 9:46 bar over the past 20 days.
# Here fixed at 80,000 shares so RVol = bar_volume / 80_000.
HIST_AVG_VOL_9_46 = 80_000


# ──────────────────────────────────────────────────────────────────────────────
# HELPER: build a DataFrame of 1-minute bars with a DatetimeIndex
# ──────────────────────────────────────────────────────────────────────────────

def _make_bars(rows: list[dict]) -> pd.DataFrame:
    """
    Convert a list of bar dicts into a DataFrame with a proper DatetimeIndex.

    Each dict must have keys: time (str 'HH:MM'), open, high, low, close, volume.
    The date is always BASE_DATE.
    """
    df = pd.DataFrame(rows)
    df['timestamp'] = pd.to_datetime(BASE_DATE + ' ' + df['time'])
    df = df.drop(columns='time').set_index('timestamp')
    df = df[['open', 'high', 'low', 'close', 'volume']]  # canonical column order
    return df


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 1: CLEAN GAP-UP BREAKOUT (should produce LONG signal)
# ──────────────────────────────────────────────────────────────────────────────
#
# Setup:
#   prev_close = $100.00
#   open       = $103.00  →  gap = +3.0%  ✓ (min 2%)
#   price      = $103.00  ✓  ($10–$200 range)
#   premarket_volume = 75,000  ✓  (min 50,000)
#
# Opening Range (9:31–9:45):
#   OR high = $104.00  (hit at 9:40)
#   OR low  = $102.50  (hit at 9:32)
#   OR range = $1.50   ✓  (0.75× ATR — within 0.5×–5.0× bounds)
#
# Breakout bar (9:46):
#   open   = $104.05  (gaps slightly above OR high on first print)
#   high   = $104.85
#   low    = $104.00
#   close  = $104.70  ✓ (closes above OR high — confirms breakout)
#   body   = |104.70 - 104.05| = $0.65
#   upper wick = 104.85 - 104.70 = $0.15  →  0.15/0.65 = 23%  ✓  (< 50% fakeout)
#   volume = 250,000  →  RVol = 250,000 / 80,000 = 3.125×  ✓  (min 2.0×)
#
# Expected signal:
#   direction  = 'LONG'
#   entry      = $104.70 (candle close = trigger price; actual fill = next bar open)
#   stop       = min(OR low, VWAP) = min(102.50, 103.25) = $102.50
#   risk       = 104.70 - 102.50 = $2.20
#   target     = 104.70 + 2 × 2.20 = $109.10  (2R)
#   rvol       = 3.125

CLEAN_GAP_UP_BREAKOUT = {
    # Scanner inputs — passed separately, not in the bar DataFrame
    'prev_close': 100.00,
    'open_price': 103.00,
    'premarket_volume': 75_000,
    'avg_daily_volume': 1_200_000,     # used to compute 5-min fallback threshold
    'opening_5min_volume': 200_000,    # first 5-min volume (not needed here, premarket passes)
    'atr': ATR_VALUE,
    'vwap': 103.25,
    'hist_avg_vol_9_46': HIST_AVG_VOL_9_46,

    # Bar data
    'bars': _make_bars([
        # ── Opening Range bars (9:31–9:45) ──────────────────────────────────
        # Deliberately oscillating. OR high (104.00) established at 9:40.
        # OR low (102.50) established at 9:32.
        {'time':'09:31','open':103.00,'high':103.50,'low':102.80,'close':103.20,'volume':80_000},
        {'time':'09:32','open':103.20,'high':103.30,'low':102.50,'close':102.70,'volume':70_000},  # OR low
        {'time':'09:33','open':102.70,'high':103.10,'low':102.60,'close':103.00,'volume':65_000},
        {'time':'09:34','open':103.00,'high':103.40,'low':102.80,'close':103.20,'volume':60_000},
        {'time':'09:35','open':103.20,'high':103.60,'low':103.10,'close':103.40,'volume':55_000},
        {'time':'09:36','open':103.40,'high':103.70,'low':103.20,'close':103.50,'volume':50_000},
        {'time':'09:37','open':103.50,'high':103.80,'low':103.30,'close':103.60,'volume':48_000},
        {'time':'09:38','open':103.60,'high':103.90,'low':103.40,'close':103.70,'volume':47_000},
        {'time':'09:39','open':103.70,'high':103.90,'low':103.50,'close':103.80,'volume':46_000},
        {'time':'09:40','open':103.80,'high':104.00,'low':103.60,'close':103.90,'volume':45_000},  # OR high
        {'time':'09:41','open':103.90,'high':103.95,'low':103.70,'close':103.80,'volume':44_000},
        {'time':'09:42','open':103.80,'high':103.90,'low':103.60,'close':103.70,'volume':43_000},
        {'time':'09:43','open':103.70,'high':103.85,'low':103.50,'close':103.60,'volume':42_000},
        {'time':'09:44','open':103.60,'high':103.80,'low':103.40,'close':103.55,'volume':41_000},
        {'time':'09:45','open':103.55,'high':103.75,'low':103.35,'close':103.50,'volume':40_000},
        # ── Breakout bar (9:46) ─────────────────────────────────────────────
        {'time':'09:46','open':104.05,'high':104.85,'low':104.00,'close':104.70,'volume':250_000},
    ]),

    # Pre-computed values (in production, caller computes these before calling generate_signal)
    'or_high': 104.00,
    'or_low':  102.50,

    # Expected outputs (used in test assertions)
    'expected_direction': 'LONG',
    'expected_stop':  102.50,   # min(or_low=102.50, vwap=103.25) = 102.50
    'expected_target': 109.10,  # 104.70 + 2*(104.70-102.50) = 104.70+4.40
    'expected_rvol':   3.125,   # 250000 / 80000
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 2: FAKEOUT BREAKOUT — SHOOTING STAR (should return None)
# ──────────────────────────────────────────────────────────────────────────────
#
# Everything is identical to Scenario 1 except the breakout candle.
# The stock pierces above OR high to $105.50 but COLLAPSES back to $104.15.
#
# Breakout bar (9:46):
#   open  = $104.05
#   high  = $105.50  ← spike high
#   low   = $104.00
#   close = $104.15  ← closes near open (shooting star)
#   body  = |104.15 - 104.05| = $0.10
#   upper wick = 105.50 - 104.15 = $1.35  →  1.35/0.10 = 1350%  ✗  (>> 50%)
#   volume = 250,000  (volume is fine — but pattern overrides)
#
# Expected: None  (fakeout detected, trade rejected)

FAKEOUT_BREAKOUT = {
    **{k: v for k, v in CLEAN_GAP_UP_BREAKOUT.items() if k != 'bars'},
    'bars': _make_bars([
        # OR bars identical to Scenario 1
        {'time':'09:31','open':103.00,'high':103.50,'low':102.80,'close':103.20,'volume':80_000},
        {'time':'09:32','open':103.20,'high':103.30,'low':102.50,'close':102.70,'volume':70_000},
        {'time':'09:33','open':102.70,'high':103.10,'low':102.60,'close':103.00,'volume':65_000},
        {'time':'09:34','open':103.00,'high':103.40,'low':102.80,'close':103.20,'volume':60_000},
        {'time':'09:35','open':103.20,'high':103.60,'low':103.10,'close':103.40,'volume':55_000},
        {'time':'09:36','open':103.40,'high':103.70,'low':103.20,'close':103.50,'volume':50_000},
        {'time':'09:37','open':103.50,'high':103.80,'low':103.30,'close':103.60,'volume':48_000},
        {'time':'09:38','open':103.60,'high':103.90,'low':103.40,'close':103.70,'volume':47_000},
        {'time':'09:39','open':103.70,'high':103.90,'low':103.50,'close':103.80,'volume':46_000},
        {'time':'09:40','open':103.80,'high':104.00,'low':103.60,'close':103.90,'volume':45_000},
        {'time':'09:41','open':103.90,'high':103.95,'low':103.70,'close':103.80,'volume':44_000},
        {'time':'09:42','open':103.80,'high':103.90,'low':103.60,'close':103.70,'volume':43_000},
        {'time':'09:43','open':103.70,'high':103.85,'low':103.50,'close':103.60,'volume':42_000},
        {'time':'09:44','open':103.60,'high':103.80,'low':103.40,'close':103.55,'volume':41_000},
        {'time':'09:45','open':103.55,'high':103.75,'low':103.35,'close':103.50,'volume':40_000},
        # ── Shooting star breakout bar ────────────────────────────────────────
        # Stock spikes to 105.50 then collapses — sellers overwhelmed buyers.
        # Upper wick = $1.35, body = $0.10 → wick is 1350% of body (>> 50% threshold)
        {'time':'09:46','open':104.05,'high':105.50,'low':104.00,'close':104.15,'volume':250_000},
    ]),
    'expected_direction': None,  # fakeout — no trade
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 3: STRESS REGIME — VALID SETUP, WRONG REGIME (should return None)
# ──────────────────────────────────────────────────────────────────────────────
#
# Identical to Scenario 1 (gap, OR, breakout, volume all valid) but
# hmm_state = 'Stress'. ORB is only allowed in Calm and Normal.
#
# This tests the HMM regime gate specifically — the FIRST check in generate_signal.
# If the regime gate is working, we never even look at the candle.
#
# Expected: None  (regime gate blocks the trade)

STRESS_REGIME_VALID_SETUP = {
    **CLEAN_GAP_UP_BREAKOUT,
    'hmm_state': 'Stress',
    'expected_direction': None,  # blocked by regime gate
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 4: CLEAN GAP-DOWN BREAKDOWN (should produce SHORT signal)
# ──────────────────────────────────────────────────────────────────────────────
#
# Mirror of Scenario 1 but on the short side.
#
# Setup:
#   prev_close = $100.00
#   open       = $96.50  →  gap = -3.5%  ✓ (abs value 3.5% > 2%)
#   OR high    = $97.50
#   OR low     = $96.00
#   OR range   = $1.50   ✓  (same as long scenario)
#
# Breakdown bar (9:46):
#   open  = $95.95  (gaps below OR low)
#   high  = $96.00
#   low   = $95.20
#   close = $95.30  ✓ (closes below OR low — confirms breakdown)
#   body  = |95.30 - 95.95| = $0.65  (bearish candle — open > close)
#   lower wick = 95.30 - 95.20 = $0.10  →  0.10/0.65 = 15%  ✓  (< 50% hammer threshold)
#   volume = 250,000  →  RVol = 3.125×  ✓
#
# Expected signal:
#   direction  = 'SHORT'
#   entry      = $95.30  (candle close)
#   VWAP       = $96.75  (precomputed)
#   stop       = max(OR high, VWAP) = max(97.50, 96.75) = $97.50  (for short)
#   risk       = 97.50 - 95.30 = $2.20
#   target     = 95.30 - 2 × 2.20 = $90.90  (2R downside)

CLEAN_GAP_DOWN_BREAKDOWN = {
    'prev_close': 100.00,
    'open_price':  96.50,
    'premarket_volume': 80_000,
    'avg_daily_volume': 1_200_000,
    'opening_5min_volume': 220_000,
    'atr': ATR_VALUE,
    'vwap': 96.75,
    'hist_avg_vol_9_46': HIST_AVG_VOL_9_46,

    'bars': _make_bars([
        # OR bars oscillate inside 96.00–97.50
        {'time':'09:31','open':96.50,'high':97.10,'low':96.20,'close':96.80,'volume':80_000},
        {'time':'09:32','open':96.80,'high':97.50,'low':96.60,'close':97.30,'volume':70_000},  # OR high
        {'time':'09:33','open':97.30,'high':97.40,'low':96.90,'close':97.00,'volume':65_000},
        {'time':'09:34','open':97.00,'high':97.20,'low':96.70,'close':96.85,'volume':60_000},
        {'time':'09:35','open':96.85,'high':97.10,'low':96.60,'close':96.70,'volume':55_000},
        {'time':'09:36','open':96.70,'high':96.90,'low':96.40,'close':96.55,'volume':50_000},
        {'time':'09:37','open':96.55,'high':96.80,'low':96.20,'close':96.40,'volume':48_000},
        {'time':'09:38','open':96.40,'high':96.70,'low':96.15,'close':96.30,'volume':47_000},
        {'time':'09:39','open':96.30,'high':96.60,'low':96.05,'close':96.20,'volume':46_000},
        {'time':'09:40','open':96.20,'high':96.50,'low':96.00,'close':96.10,'volume':45_000},  # OR low
        {'time':'09:41','open':96.10,'high':96.40,'low':96.05,'close':96.20,'volume':44_000},
        {'time':'09:42','open':96.20,'high':96.50,'low':96.10,'close':96.35,'volume':43_000},
        {'time':'09:43','open':96.35,'high':96.60,'low':96.20,'close':96.45,'volume':42_000},
        {'time':'09:44','open':96.45,'high':96.70,'low':96.25,'close':96.50,'volume':41_000},
        {'time':'09:45','open':96.50,'high':96.75,'low':96.30,'close':96.55,'volume':40_000},
        # ── Breakdown bar (9:46) ─────────────────────────────────────────────
        # Opens below OR low ($96.00), closes even lower. Small lower wick.
        {'time':'09:46','open':95.95,'high':96.00,'low':95.20,'close':95.30,'volume':250_000},
    ]),

    'or_high': 97.50,
    'or_low':  96.00,

    'expected_direction': 'SHORT',
    'expected_stop':  97.50,   # max(or_high=97.50, vwap=96.75) = 97.50
    'expected_target': 90.90,  # 95.30 - 2*(97.50-95.30) = 95.30 - 4.40
    'expected_rvol':   3.125,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 5: INSUFFICIENT GAP — SCANNER REJECTS (should return False from scanner)
# ──────────────────────────────────────────────────────────────────────────────
#
# The stock barely moved overnight. A 0.5% gap is noise, not a meaningful
# catalyst. The scanner filters this out before we even look at the chart.
#
# Rule tested: gap_pct = abs(open - prev_close) / prev_close >= 0.02
#
#   gap = abs(100.50 - 100.00) / 100.00 = 0.5%  ✗  (< 2% minimum)
#
# Expected: scanner returns False for this candidate

INSUFFICIENT_GAP = {
    'prev_close': 100.00,
    'open_price': 100.50,          # 0.5% gap — fails the 2% minimum
    'premarket_volume': 75_000,    # volume would be fine
    'avg_daily_volume': 1_200_000,
    'opening_5min_volume': 200_000,
    'atr': ATR_VALUE,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 6: NARROW OPENING RANGE (calculate_opening_range returns RANGE_TOO_NARROW)
# ──────────────────────────────────────────────────────────────────────────────
#
# The stock gaps up fine (3%) and passes the scanner. But during the
# 9:31–9:45 window, it barely moves — the entire OR is only $0.15 wide.
#
# Rule tested: or_range >= 0.5 * ATR
#
#   or_range = 103.10 - 102.95 = $0.15
#   0.5 × ATR = 0.5 × 2.00 = $1.00
#   0.15 < 1.00  ✗  → RANGE_TOO_NARROW
#
# Why reject narrow ranges?
# A stop placed at OR low would be only $0.15 below entry. Any random
# 1-cent wiggle could stop you out. The range must be meaningful.
#
# Expected: calculate_opening_range returns (None, None, 'RANGE_TOO_NARROW')

NARROW_OPENING_RANGE = {
    'prev_close': 100.00,
    'open_price': 103.00,   # 3% gap ✓ — passes scanner
    'premarket_volume': 75_000,
    'avg_daily_volume': 1_200_000,
    'opening_5min_volume': 200_000,
    'atr': ATR_VALUE,       # $2.00

    'bars': _make_bars([
        # All bars clustered tightly — OR range = 103.10 - 102.95 = $0.15
        {'time':'09:31','open':103.00,'high':103.05,'low':102.95,'close':103.00,'volume':80_000},
        {'time':'09:32','open':103.00,'high':103.08,'low':102.97,'close':103.02,'volume':70_000},
        {'time':'09:33','open':103.02,'high':103.10,'low':102.98,'close':103.05,'volume':65_000},
        {'time':'09:34','open':103.05,'high':103.08,'low':102.97,'close':103.00,'volume':60_000},
        {'time':'09:35','open':103.00,'high':103.06,'low':102.96,'close':103.03,'volume':55_000},
        {'time':'09:36','open':103.03,'high':103.09,'low':102.98,'close':103.01,'volume':50_000},
        {'time':'09:37','open':103.01,'high':103.07,'low':102.97,'close':103.04,'volume':48_000},
        {'time':'09:38','open':103.04,'high':103.10,'low':102.99,'close':103.02,'volume':47_000},
        {'time':'09:39','open':103.02,'high':103.06,'low':102.95,'close':103.00,'volume':46_000},
        {'time':'09:40','open':103.00,'high':103.05,'low':102.96,'close':103.02,'volume':45_000},
        {'time':'09:41','open':103.02,'high':103.08,'low':102.98,'close':103.04,'volume':44_000},
        {'time':'09:42','open':103.04,'high':103.09,'low':102.97,'close':103.01,'volume':43_000},
        {'time':'09:43','open':103.01,'high':103.07,'low':102.96,'close':103.03,'volume':42_000},
        {'time':'09:44','open':103.03,'high':103.08,'low':102.98,'close':103.00,'volume':41_000},
        {'time':'09:45','open':103.00,'high':103.05,'low':102.97,'close':103.02,'volume':40_000},
    ]),
}
