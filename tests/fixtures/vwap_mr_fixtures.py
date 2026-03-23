# tests/fixtures/vwap_mr_fixtures.py
#
# Synthetic 1-minute OHLCV fixtures for VWAP Mean Reversion strategy testing.
#
# BLUEPRINT RECAP (Section 4.3)
# ------------------------------
# Signal confirmation rule:
#   PREVIOUS bar touches Bollinger Band AND closes back inside
#   → Entry at CURRENT bar's open (not next-bar-open like ORB)
#
# This means fixtures must provide:
#   - 20+ bars of history so BB can be calculated (rolling 20-period window)
#   - A "confirmation bar" (bar[-2]) that touches and closes back inside band
#   - An "entry bar" (bar[-1]) whose open is the fill price
#
# BOLLINGER BAND MATHS FOR THESE FIXTURES
# ----------------------------------------
# The history bars all oscillate tightly: alternating closes of $99.90/$100.10
# over 20 bars.
#
#   mean    = $100.00
#   std     = $0.10  (all values exactly ±$0.10 from mean)
#   BB_upper (2σ) = $100.00 + 2×$0.10 = $100.20
#   BB_lower (2σ) = $100.00 - 2×$0.10 = $99.80
#
# These round numbers make hand-verification of tests trivial.
# ATR for all fixtures: $0.30 (used for stop calculation: stop = entry ± 1.5×ATR)

import pandas as pd
import numpy as np
from datetime import datetime

BASE_DATE = '2024-01-15'

# Pre-computed indicator values (match the history bars below exactly)
BB_UPPER   = 100.20
BB_LOWER   =  99.80
BB_MIDDLE  = 100.00   # 20-period SMA
VWAP_VALUE = 100.00   # fair value / target for mean reversion
ATR_VALUE  =   0.30   # 14-period ATR


def _make_bars(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df['timestamp'] = pd.to_datetime(BASE_DATE + ' ' + df['time'])
    df = df.drop(columns='time').set_index('timestamp')
    return df[['open', 'high', 'low', 'close', 'volume']]


# ── 20-bar history base (used by all fixtures) ────────────────────────────────
# Alternating closes $99.90 / $100.10 → mean=$100, std=$0.10
# All bars have narrow range so ADX would be low (range-bound, not trending)
_HISTORY_BARS = [
    {'time':'10:15','open':100.00,'high':100.15,'low':99.85,'close':99.90,'volume':40_000},
    {'time':'10:16','open': 99.90,'high':100.20,'low':99.80,'close':100.10,'volume':38_000},
    {'time':'10:17','open':100.10,'high':100.18,'low':99.88,'close': 99.90,'volume':37_000},
    {'time':'10:18','open': 99.90,'high':100.15,'low':99.82,'close':100.10,'volume':36_000},
    {'time':'10:19','open':100.10,'high':100.17,'low':99.87,'close': 99.90,'volume':35_000},
    {'time':'10:20','open': 99.90,'high':100.14,'low':99.83,'close':100.10,'volume':34_000},
    {'time':'10:21','open':100.10,'high':100.16,'low':99.86,'close': 99.90,'volume':33_000},
    {'time':'10:22','open': 99.90,'high':100.13,'low':99.84,'close':100.10,'volume':32_000},
    {'time':'10:23','open':100.10,'high':100.15,'low':99.85,'close': 99.90,'volume':31_000},
    {'time':'10:24','open': 99.90,'high':100.12,'low':99.85,'close':100.10,'volume':30_000},
    {'time':'10:25','open':100.10,'high':100.14,'low':99.86,'close': 99.90,'volume':30_000},
    {'time':'10:26','open': 99.90,'high':100.11,'low':99.86,'close':100.10,'volume':30_000},
    {'time':'10:27','open':100.10,'high':100.13,'low':99.87,'close': 99.90,'volume':30_000},
    {'time':'10:28','open': 99.90,'high':100.10,'low':99.87,'close':100.10,'volume':30_000},
    {'time':'10:29','open':100.10,'high':100.12,'low':99.88,'close': 99.90,'volume':30_000},
    {'time':'10:30','open': 99.90,'high':100.09,'low':99.88,'close':100.10,'volume':30_000},
    {'time':'10:31','open':100.10,'high':100.11,'low':99.89,'close': 99.90,'volume':30_000},
    {'time':'10:32','open': 99.90,'high':100.08,'low':99.89,'close':100.10,'volume':30_000},
    {'time':'10:33','open':100.10,'high':100.10,'low':99.90,'close': 99.90,'volume':30_000},
    {'time':'10:34','open': 99.90,'high':100.07,'low':99.90,'close':100.10,'volume':30_000},
]


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 1: CLEAN SHORT FADE — upper BB touch (should produce SHORT signal)
# ──────────────────────────────────────────────────────────────────────────────
#
# Confirmation bar (10:35 — bar[-2]):
#   high  = $100.25  ≥ BB_upper ($100.20) ✓ — touched band
#   close = $100.15  < BB_upper ($100.20) ✓ — closed back inside
#   → SHORT signal confirmed
#
# Entry bar (10:36 — bar[-1]):
#   open  = $100.12  → SHORT entry at $100.12
#
# Stop:   $100.12 + 1.5 × $0.30 = $100.12 + $0.45 = $100.57
# Target: VWAP = $100.00
# Risk:   $100.57 - $100.12 = $0.45/share

CLEAN_SHORT_FADE = {
    'atr':        ATR_VALUE,
    'vwap':       VWAP_VALUE,
    'bb_upper':   BB_UPPER,
    'bb_lower':   BB_LOWER,

    'bars': _make_bars(_HISTORY_BARS + [
        # Confirmation bar: touches upper band (high=$100.25), closes back inside
        {'time':'10:35','open':100.10,'high':100.25,'low':100.05,'close':100.15,'volume':45_000},
        # Entry bar: we SHORT at this bar's open
        {'time':'10:36','open':100.12,'high':100.18,'low':99.95,'close':100.00,'volume':40_000},
    ]),

    'expected_direction': 'SHORT',
    'expected_entry':     100.12,
    'expected_stop':      100.57,   # 100.12 + 1.5×0.30
    'expected_target':    VWAP_VALUE,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 2: CLEAN LONG FADE — lower BB touch (should produce LONG signal)
# ──────────────────────────────────────────────────────────────────────────────
#
# Confirmation bar (10:35):
#   low   = $99.75  ≤ BB_lower ($99.80) ✓ — touched band
#   close = $99.85  > BB_lower ($99.80) ✓ — closed back inside
#
# Entry bar (10:36):
#   open = $99.88  → LONG entry at $99.88
#
# Stop:   $99.88 - 1.5 × $0.30 = $99.88 - $0.45 = $99.43
# Target: VWAP = $100.00

CLEAN_LONG_FADE = {
    'atr':       ATR_VALUE,
    'vwap':      VWAP_VALUE,
    'bb_upper':  BB_UPPER,
    'bb_lower':  BB_LOWER,

    'bars': _make_bars(_HISTORY_BARS + [
        # Confirmation bar: touches lower band (low=$99.75), closes back inside
        {'time':'10:35','open':99.90,'high':99.95,'low':99.75,'close':99.85,'volume':45_000},
        # Entry bar: we LONG at this bar's open
        {'time':'10:36','open':99.88,'high':100.05,'low':99.82,'close':99.95,'volume':40_000},
    ]),

    'expected_direction': 'LONG',
    'expected_entry':     99.88,
    'expected_stop':      99.43,    # 99.88 - 1.5×0.30
    'expected_target':    VWAP_VALUE,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 3: NORMAL REGIME — valid setup, wrong regime (should return None)
# ──────────────────────────────────────────────────────────────────────────────
#
# Blueprint: "Best HMM Regime: Calm only (skip during Normal/Stress)"
# VWAP MR is the most restrictive — it requires CALM specifically.
# Normal regime means too much trending potential.

NORMAL_REGIME_VALID_SETUP = {
    **CLEAN_SHORT_FADE,
    'hmm_state': 'Normal',
    'expected_direction': None,
}

STRESS_REGIME_VALID_SETUP = {
    **CLEAN_SHORT_FADE,
    'hmm_state': 'Stress',
    'expected_direction': None,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 4: NO CONFIRMATION — bar touches band but does NOT close back inside
# ──────────────────────────────────────────────────────────────────────────────
#
# The confirmation rule is both conditions:
#   1. high >= BB_upper  (touched the band)
#   2. close < BB_upper  (closed back inside)
#
# If the bar closes ABOVE BB_upper, momentum is strong — don't fade.
# This is the "runaway move" case. No signal.

NO_CONFIRMATION_CLOSES_OUTSIDE = {
    'atr':       ATR_VALUE,
    'vwap':      VWAP_VALUE,
    'bb_upper':  BB_UPPER,
    'bb_lower':  BB_LOWER,

    'bars': _make_bars(_HISTORY_BARS + [
        # Bar touches AND closes ABOVE BB_upper — no confirmation
        {'time':'10:35','open':100.10,'high':100.30,'low':100.05,'close':100.28,'volume':60_000},
        {'time':'10:36','open':100.28,'high':100.35,'low':100.20,'close':100.30,'volume':55_000},
    ]),

    'expected_direction': None,  # no signal — bar didn't close back inside
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 5: SCANNER — ADX too high (trending market, not range-bound)
# ──────────────────────────────────────────────────────────────────────────────
#
# Blueprint: "ADX >= 25 → return False (Too much trend)"
# ADX measures trend strength. >= 25 = trending. VWAP MR only works in ranges.

SCANNER_ADX_TOO_HIGH = {
    'ticker':          'AAPL',
    'adx':             28.0,      # >= 25 → REJECT
    'sma_20':         100.00,
    'current_price':  100.50,     # within 3% of SMA ✓
    'current_volume':  500_000,
    'avg_daily_volume': 1_000_000,# volume ratio = 0.5× ✓
    'atr_current':       0.30,
    'atr_5bars_ago':     0.35,    # ATR decreasing ✓
    'has_earnings':      False,
    'expected_pass':     False,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 6: SCANNER — price too far from SMA (ADX lag protection)
# ──────────────────────────────────────────────────────────────────────────────
#
# Blueprint ADX Lag Protection Filter #1:
#   "Require price within ±3% of 20-period SMA"
#   Catches crashing stocks before ADX responds (14-period lag).
#
# Price $75 vs SMA $100 = 25% deviation → REJECT

SCANNER_SMA_TOO_FAR = {
    'ticker':           'MSFT',
    'adx':               18.0,    # low ADX ✓ — but price has moved far
    'sma_20':           100.00,
    'current_price':     75.00,   # 25% below SMA → REJECT
    'current_volume':   500_000,
    'avg_daily_volume': 1_000_000,
    'atr_current':        0.30,
    'atr_5bars_ago':      0.35,
    'has_earnings':       False,
    'expected_pass':      False,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 7: SCANNER — volume spike (news event in progress)
# ──────────────────────────────────────────────────────────────────────────────
#
# Blueprint ADX Lag Protection Filter #2:
#   "Reject stocks showing volume > 3× average daily volume"
#   Catches news events before price has moved enough to fail SMA filter.
#
# volume_ratio = 4,000,000 / 1,000,000 = 4.0× > 3.0 → REJECT

SCANNER_VOLUME_SPIKE = {
    'ticker':           'NVDA',
    'adx':               20.0,    # low ADX ✓
    'sma_20':           100.00,
    'current_price':    100.50,   # within 3% ✓
    'current_volume': 4_000_000,  # 4× average → REJECT
    'avg_daily_volume':1_000_000,
    'atr_current':        0.30,
    'atr_5bars_ago':      0.35,
    'has_earnings':       False,
    'expected_pass':      False,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 8: SCANNER — valid candidate (all filters pass)
# ──────────────────────────────────────────────────────────────────────────────

SCANNER_VALID_CANDIDATE = {
    'ticker':           'TSLA',
    'adx':               18.0,    # < 25 ✓
    'sma_20':           100.00,
    'current_price':    100.50,   # 0.5% from SMA ✓
    'current_volume':   500_000,  # 0.5× avg ✓
    'avg_daily_volume': 1_000_000,
    'atr_current':        0.28,   # decreasing ✓
    'atr_5bars_ago':      0.35,
    'has_earnings':       False,  # no earnings ✓
    'expected_pass':      True,
}
