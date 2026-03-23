# tests/fixtures/trend_fixtures.py
#
# Synthetic 5-minute OHLCV fixtures for Trend Following strategy testing.
#
# KEY DIFFERENCES FROM ORB/VWAP MR FIXTURES
# -------------------------------------------
# 1. All bars are 5-MINUTE resolution (not 1-minute)
#    The EMA, Chandelier stop, and entry all use 5-min bars.
#
# 2. We need 20+ bars of history for a 20-period EMA to be meaningful.
#    History bars cover 2:00–2:30 PM (6 bars at 5-min = only 6 bars —
#    not enough). We use a longer history starting at 10:00 AM so the
#    EMA is well-established by 2:00 PM. In backtest, the full day's
#    5-min bars would be available.
#
# EMA MATHS FOR THESE FIXTURES
# ------------------------------
# The 20-bar history is a steady uptrend: $100 → $110 in steps of $0.50/bar.
# After 20 bars of steady rise, the 20-period EMA lags slightly behind price.
# We set it at $105.00 (midpoint of the history range) as a round number.
#
# ENTRY LOGIC RECAP (blueprint Section 4.4)
# ------------------------------------------
# 1. Stock near HOD (within 3% or 2× ATR — more permissive)
# 2. On 5-min chart: price touches 20 EMA (within 0.2%)
# 3. Volume declined on pullback bar (below 10-bar avg)
# 4. Volume surged on resume bar (> 1.3× 10-bar avg)
# 5. Entry at current bar's close (signal and entry same bar on 5-min)
#
# CHANDELIER STOP MATHS
# ----------------------
# ATR_VALUE = $1.00  (clean round number)
# For a LONG trade:
#   trailing_stop = highest_high_since_entry - 3.0 × ATR
# The stop RISES as price makes new highs. It never moves down.

import pandas as pd

BASE_DATE = '2024-01-15'
ATR_VALUE  = 1.00   # 14-period ATR on 5-min bars

# Pre-computed for signal tests
EMA_20_VALUE    = 105.00   # 20-period EMA at time of signal
HOD_VALUE       = 110.50   # high of day at 2:00 PM
LOD_VALUE        =  99.50  # low of day at 2:00 PM (for short setups)
AVG_VOLUME_10   = 50_000   # 10-bar average volume (for volume pattern check)


def _make_5min_bars(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df['timestamp'] = pd.to_datetime(BASE_DATE + ' ' + df['time'])
    df = df.drop(columns='time').set_index('timestamp')
    return df[['open', 'high', 'low', 'close', 'volume']]


# ── 22-bar history: steady uptrend from $100 → $110 ─────────────────────────
# Each bar rises ~$0.50. Volume is steady at 50,000 (= avg_volume_10).
# This establishes a well-formed uptrend with 20-EMA around $105.
_HISTORY_BARS = [
    {'time':'10:00','open':100.00,'high':100.60,'low': 99.80,'close':100.50,'volume':50_000},
    {'time':'10:05','open':100.50,'high':101.10,'low':100.30,'close':101.00,'volume':50_000},
    {'time':'10:10','open':101.00,'high':101.60,'low':100.80,'close':101.50,'volume':50_000},
    {'time':'10:15','open':101.50,'high':102.10,'low':101.30,'close':102.00,'volume':50_000},
    {'time':'10:20','open':102.00,'high':102.60,'low':101.80,'close':102.50,'volume':50_000},
    {'time':'10:25','open':102.50,'high':103.10,'low':102.30,'close':103.00,'volume':50_000},
    {'time':'10:30','open':103.00,'high':103.60,'low':102.80,'close':103.50,'volume':50_000},
    {'time':'10:35','open':103.50,'high':104.10,'low':103.30,'close':104.00,'volume':50_000},
    {'time':'10:40','open':104.00,'high':104.60,'low':103.80,'close':104.50,'volume':50_000},
    {'time':'10:45','open':104.50,'high':105.10,'low':104.30,'close':105.00,'volume':50_000},
    {'time':'10:50','open':105.00,'high':105.60,'low':104.80,'close':105.50,'volume':50_000},
    {'time':'10:55','open':105.50,'high':106.10,'low':105.30,'close':106.00,'volume':50_000},
    {'time':'11:00','open':106.00,'high':106.60,'low':105.80,'close':106.50,'volume':50_000},
    {'time':'11:05','open':106.50,'high':107.10,'low':106.30,'close':107.00,'volume':50_000},
    {'time':'11:10','open':107.00,'high':107.60,'low':106.80,'close':107.50,'volume':50_000},
    {'time':'11:15','open':107.50,'high':108.10,'low':107.30,'close':108.00,'volume':50_000},
    {'time':'11:20','open':108.00,'high':108.60,'low':107.80,'close':108.50,'volume':50_000},
    {'time':'11:25','open':108.50,'high':109.10,'low':108.30,'close':109.00,'volume':50_000},
    {'time':'11:30','open':109.00,'high':109.60,'low':108.80,'close':109.50,'volume':50_000},
    {'time':'11:35','open':109.50,'high':110.10,'low':109.30,'close':110.00,'volume':50_000},
    {'time':'11:40','open':110.00,'high':110.60,'low':109.80,'close':110.50,'volume':50_000},  # HOD
    {'time':'11:45','open':110.50,'high':110.55,'low':109.80,'close':110.00,'volume':50_000},
]


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 1: CLEAN LONG PULLBACK (should produce LONG signal)
# ──────────────────────────────────────────────────────────────────────────────
#
# After the uptrend history, price pulls back to the 20 EMA ($105.00):
#
# Pullback bar (bar[-2]):
#   close = $105.10  — near EMA ($105.00), within 0.2%
#   volume = 30,000  — BELOW avg (50,000) → pullback on low volume ✓
#
# Resume bar (bar[-1]) — ENTRY BAR:
#   close = $106.00  — pushed back up through EMA
#   volume = 70,000  — ABOVE avg×1.3 (65,000) → volume surge ✓
#
# Entry: $106.00 (close of resume bar)
# HOD:   $110.50  (near HOD within 3% or 2×ATR ✓)
# Initial Chandelier stop: HOD - 3×ATR = $110.50 - $3.00 = $107.50
#   (This updates as price makes new highs)

CLEAN_LONG_PULLBACK = {
    'atr':             ATR_VALUE,
    'ema_20':          EMA_20_VALUE,
    'hod':             HOD_VALUE,
    'lod':              99.50,
    'avg_volume_10':   AVG_VOLUME_10,

    'bars': _make_5min_bars(_HISTORY_BARS + [
        # Pullback bar — price touches EMA, low volume
        {'time':'14:00','open':110.00,'high':110.10,'low':104.90,'close':105.10,
         'volume':30_000},   # 30k < 50k avg → volume declined ✓
        # Resume bar — price pushes back up, high volume
        {'time':'14:05','open':105.10,'high':106.20,'low':105.00,'close':106.00,
         'volume':70_000},   # 70k > 50k×1.3=65k → volume surge ✓
    ]),

    'expected_direction': 'LONG',
    'expected_entry':     106.00,   # close of resume bar
    # Chandelier initial stop: HOD ($110.50) - 3×ATR ($3.00) = $107.50
    # But at entry time, highest high since entry = entry bar high = $106.20
    # So initial stop = $106.20 - $3.00 = $103.20
    'expected_initial_stop': 103.20,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 2: CLEAN SHORT PULLBACK (should produce SHORT signal)
# ──────────────────────────────────────────────────────────────────────────────
#
# Mirror of Scenario 1 but downtrend (near LOD).
# History is a downtrend: $110 → $100, EMA_20 ≈ $105.00 (same value).
# Price bounces up to EMA then resumes downtrend.
#
# Pullback bar: close=$104.90 (near EMA), volume=30,000 (low) ✓
# Resume bar:  close=$104.00 (pushed back down), volume=70,000 (surge) ✓
# Entry: $104.00

CLEAN_SHORT_PULLBACK = {
    'atr':            ATR_VALUE,
    'ema_20':         EMA_20_VALUE,
    'hod':            110.50,
    'lod':             99.50,   # near LOD
    'avg_volume_10':  AVG_VOLUME_10,

    'bars': _make_5min_bars(_HISTORY_BARS + [
        # Pullback bar — price bounces up to EMA, low volume
        {'time':'14:00','open':100.00,'high':105.20,'low': 99.80,'close':104.90,
         'volume':30_000},
        # Resume bar — price drops back down, high volume
        {'time':'14:05','open':104.90,'high':105.10,'low':103.80,'close':104.00,
         'volume':70_000},
    ]),

    'expected_direction': 'SHORT',
    'expected_entry':     104.00,
    # initial stop: lowest_low since entry = 14:05 low = $103.80
    # stop = $103.80 + 3×ATR = $103.80 + $3.00 = $106.80
    'expected_initial_stop': 106.80,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 3: CALM REGIME (should return None — wrong regime for trend follow)
# ──────────────────────────────────────────────────────────────────────────────
#
# Blueprint: "Best HMM Regimes: Normal, Stress (skip during Calm)"
# Calm = range-bound = no trend = Trend Following has no edge.

CALM_REGIME_VALID_SETUP = {
    **CLEAN_LONG_PULLBACK,
    'hmm_state': 'Calm',
    'expected_direction': None,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 4: VOLUME PATTERN FAILS — no volume decline on pullback
# ──────────────────────────────────────────────────────────────────────────────
#
# Pullback bar has HIGH volume (70,000 > avg 50,000).
# This means sellers are aggressively pushing price down — not a healthy
# pullback. A healthy pullback has LOW volume (lack of sellers = temporary).
# We must not enter.

PULLBACK_HIGH_VOLUME = {
    'atr':            ATR_VALUE,
    'ema_20':         EMA_20_VALUE,
    'hod':            HOD_VALUE,
    'lod':             99.50,
    'avg_volume_10':  AVG_VOLUME_10,

    'bars': _make_5min_bars(_HISTORY_BARS + [
        # Pullback bar — HIGH volume (bad: aggressive selling)
        {'time':'14:00','open':110.00,'high':110.10,'low':104.90,'close':105.10,
         'volume':70_000},   # 70k > 50k avg → volume did NOT decline ✗
        # Resume bar — high volume
        {'time':'14:05','open':105.10,'high':106.20,'low':105.00,'close':106.00,
         'volume':70_000},
    ]),

    'expected_direction': None,   # rejected: pullback on high volume
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 5: RESUME BAR VOLUME TOO LOW (no surge)
# ──────────────────────────────────────────────────────────────────────────────
#
# Pullback is healthy (low volume) but resume bar volume = 55,000.
# Threshold: avg × 1.3 = 50,000 × 1.3 = 65,000.
# 55,000 < 65,000 → no volume surge → conviction unclear → no entry.

RESUME_LOW_VOLUME = {
    'atr':            ATR_VALUE,
    'ema_20':         EMA_20_VALUE,
    'hod':            HOD_VALUE,
    'lod':             99.50,
    'avg_volume_10':  AVG_VOLUME_10,

    'bars': _make_5min_bars(_HISTORY_BARS + [
        # Pullback bar — low volume ✓
        {'time':'14:00','open':110.00,'high':110.10,'low':104.90,'close':105.10,
         'volume':30_000},
        # Resume bar — insufficient volume surge ✗
        {'time':'14:05','open':105.10,'high':106.20,'low':105.00,'close':106.00,
         'volume':55_000},   # 55k < 65k threshold → no surge
    ]),

    'expected_direction': None,   # rejected: resume volume insufficient
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 6: SCANNER — valid candidate (near HOD, volume OK, sector positive)
# ──────────────────────────────────────────────────────────────────────────────

SCANNER_VALID_NEAR_HOD = {
    'ticker':           'TSLA',
    'current_price':    109.50,   # HOD = 110.50
    'hod':              110.50,   # within 1% of HOD ✓
    'lod':               99.50,
    'atr':               ATR_VALUE,
    'current_volume':    80_000,
    'avg_daily_volume': 1_000_000,  # ratio = 0.08× (intraday, not daily)
    'avg_intraday_volume': 50_000,  # 10-bar avg ← used for >1.5× check
    'sector_strength':   0.5,       # positive ✓
    'expected_pass':     True,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 7: SCANNER — not near HOD or LOD (rejected)
# ──────────────────────────────────────────────────────────────────────────────
#
# Price is in the middle of the day's range — no momentum setup.
# HOD=110.50, LOD=99.50, current=$105.00
# Distance from HOD: (110.50 - 105.00) / 110.50 = 4.98% > 3% ✗
# Distance from LOD: (105.00 - 99.50) / 99.50 = 5.5% > 3% ✗  (pct based)
# ATR check: (110.50 - 105.00) = 5.50 > 2×ATR=2.00 ✗ (ATR based)
# Both methods fail → rejected.

SCANNER_NOT_NEAR_HOD_OR_LOD = {
    'ticker':            'AAPL',
    'current_price':     105.00,   # middle of range — not near HOD or LOD
    'hod':               110.50,
    'lod':                99.50,
    'atr':                ATR_VALUE,
    'current_volume':     80_000,
    'avg_intraday_volume':50_000,
    'sector_strength':     0.5,
    'expected_pass':       False,
}
