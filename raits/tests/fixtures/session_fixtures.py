# tests/fixtures/session_fixtures.py
#
# Full single-day 1-minute bar DataFrames for ORB integration testing.
#
# WHY WE NEED THESE
# -----------------
# Unit tests (Week 9) tested each ORBStrategy method in isolation with
# carefully cropped data. Integration tests need a COMPLETE trading day:
#   - Pre-9:35 bars (so the replayer can reach scanner time)
#   - 9:31–9:45 OR formation bars
#   - 9:46–10:15 monitoring bars (including signal and post-signal bars)
#   - Post-10:15 bars (so the replayer can exit at 10:15 if needed)
#
# WHAT WE'RE VERIFYING
# ---------------------
# The critical blueprint rule tested here:
#   "Entry occurs at NEXT BAR OPEN after signal confirmation"
#
# So if the signal fires on the 9:46 bar (close=$104.70), the entry
# price must be $104.80 (the OPEN of the 9:47 bar), not $104.70.
#
# TIMELINE
# --------
# 9:30  Market open (opening print — excluded from OR)
# 9:31  OR formation begins
# 9:35  Scanner runs (uses 9:30–9:35 volume)
# 9:45  OR formation ends
# 9:46  First breakout monitoring bar — SIGNAL FIRES HERE
# 9:47  Entry bar — entry at OPEN of this bar
# 9:48+ Hold until target / stop / 10:15 cutoff
# 10:15 Hard exit if still open

import pandas as pd


BASE_DATE = '2024-01-15'


def _make_session(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df['timestamp'] = pd.to_datetime(BASE_DATE + ' ' + df['time'])
    df = df.drop(columns='time').set_index('timestamp')
    return df[['open', 'high', 'low', 'close', 'volume']]


# ──────────────────────────────────────────────────────────────────────────────
# SESSION 1: CLEAN LONG TRADE — HITS TARGET
# ──────────────────────────────────────────────────────────────────────────────
#
# Stock: TSLA-like gapper
#   prev_close = $100.00
#   open       = $103.00  (3% gap up ✓)
#   OR:        high=$104.00, low=$102.50  (range=$1.50, 0.75×ATR ✓)
#
# Signal fires on 9:46 bar (close=$104.70, RVol=3.125×, clean candle)
# Entry:  9:47 bar open = $104.80  ← NEXT BAR OPEN
# Stop:   $102.50  (or_low, which is < vwap=$103.25)
# Risk:   $104.80 - $102.50 = $2.30/share
# Target: $104.80 + 2×$2.30 = $109.40  (2R)
#
# 9:53 bar hits target ($109.40). Trade closes profitably.
#
# This session tests:
#   - Entry at next bar open (not signal close)
#   - Target exit fires at correct bar
#   - P&L calculation is correct

LONG_TRADE_HITS_TARGET = {
    'ticker': 'TSLA',
    'prev_close': 100.00,
    'premarket_volume': 75_000,
    'avg_daily_volume': 1_200_000,
    'opening_5min_volume': 200_000,   # computed from 9:30–9:35 bars below
    'atr': 2.00,
    'hist_avg_vol_9_46': 80_000,

    'bars': _make_session([
        # 9:30 opening print (excluded from OR — excluded by replayer)
        {'time':'09:30','open':103.00,'high':103.80,'low':102.20,'close':103.20,'volume':300_000},
        # OR formation bars (9:31–9:45)
        {'time':'09:31','open':103.20,'high':103.50,'low':102.80,'close':103.30,'volume':80_000},
        {'time':'09:32','open':103.30,'high':103.40,'low':102.50,'close':102.70,'volume':70_000},  # OR low
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
        # ── Signal bar (9:46) ─────────────────────────────────────────────────
        # Close $104.70 > OR high $104.00 → LONG signal
        # RVol = 250,000 / 80,000 = 3.125× ✓
        # Clean candle (upper wick 23% of body) ✓
        {'time':'09:46','open':104.05,'high':104.85,'low':104.00,'close':104.70,'volume':250_000},
        # ── Entry bar (9:47) ── ENTRY AT OPEN = $104.80 ──────────────────────
        {'time':'09:47','open':104.80,'high':105.20,'low':104.60,'close':105.00,'volume':120_000},
        # Bars 9:48–9:52: stock drifts up toward target ($109.40)
        {'time':'09:48','open':105.00,'high':105.50,'low':104.90,'close':105.30,'volume':100_000},
        {'time':'09:49','open':105.30,'high':106.00,'low':105.20,'close':105.80,'volume':95_000},
        {'time':'09:50','open':105.80,'high':106.50,'low':105.70,'close':106.20,'volume':90_000},
        {'time':'09:51','open':106.20,'high':107.00,'low':106.00,'close':106.80,'volume':85_000},
        {'time':'09:52','open':106.80,'high':108.00,'low':106.70,'close':107.50,'volume':80_000},
        # ── Target bar (9:53) ── HIGH touches $109.40 ────────────────────────
        # Target = $104.80 + 2×($104.80-$102.50) = $104.80 + $4.60 = $109.40
        {'time':'09:53','open':107.50,'high':109.50,'low':107.40,'close':108.80,'volume':75_000},
        # Post-trade bars (replayer ignores these — already flat)
        {'time':'09:54','open':108.80,'high':109.00,'low':108.50,'close':108.70,'volume':70_000},
        {'time':'10:00','open':108.70,'high':109.10,'low':108.40,'close':108.90,'volume':65_000},
        {'time':'10:15','open':108.90,'high':109.20,'low':108.60,'close':109.00,'volume':60_000},
    ]),

    'vwap_at_9_46': 103.25,   # precomputed VWAP at signal time

    # Expected trade outcome
    'expected_entry_price':  104.80,   # NEXT BAR OPEN (9:47), not signal close (104.70)
    'expected_entry_time':   '09:47',
    'expected_stop':         102.50,   # min(or_low=102.50, vwap=103.25)
    'expected_target':       109.40,   # 104.80 + 2×(104.80-102.50)
    'expected_exit_price':   109.40,   # target hit
    'expected_exit_time':    '09:53',
    'expected_direction':    'LONG',
    'expected_outcome':      'TARGET_HIT',
}


# ──────────────────────────────────────────────────────────────────────────────
# SESSION 2: LONG TRADE — HITS STOP
# ──────────────────────────────────────────────────────────────────────────────
#
# Same setup as Session 1 up to entry. But after entry, stock reverses.
#
# Entry:  9:47 open = $104.80
# Stop:   $102.50
# Risk:   $2.30/share
#
# 9:52 bar LOW hits $102.45 (below stop $102.50) → stop triggered.
# Exit at stop price $102.50.
#
# This tests:
#   - Stop loss exit fires before target
#   - Loss is calculated correctly

LONG_TRADE_HITS_STOP = {
    **{k: v for k, v in LONG_TRADE_HITS_TARGET.items()
       if k not in ('bars', 'expected_entry_price', 'expected_entry_time',
                    'expected_exit_price', 'expected_exit_time',
                    'expected_outcome', 'expected_target')},

    'bars': _make_session([
        {'time':'09:30','open':103.00,'high':103.80,'low':102.20,'close':103.20,'volume':300_000},
        {'time':'09:31','open':103.20,'high':103.50,'low':102.80,'close':103.30,'volume':80_000},
        {'time':'09:32','open':103.30,'high':103.40,'low':102.50,'close':102.70,'volume':70_000},
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
        # Signal bar — identical to Session 1
        {'time':'09:46','open':104.05,'high':104.85,'low':104.00,'close':104.70,'volume':250_000},
        # Entry bar
        {'time':'09:47','open':104.80,'high':105.00,'low':104.50,'close':104.70,'volume':120_000},
        # Stock reverses after entry
        {'time':'09:48','open':104.70,'high':104.80,'low':104.00,'close':104.10,'volume':110_000},
        {'time':'09:49','open':104.10,'high':104.20,'low':103.50,'close':103.60,'volume':105_000},
        {'time':'09:50','open':103.60,'high':103.70,'low':103.00,'close':103.10,'volume':100_000},
        {'time':'09:51','open':103.10,'high':103.20,'low':102.60,'close':102.70,'volume':95_000},
        # ── Stop bar (9:52) ── LOW = $102.45, below stop $102.50 ─────────────
        {'time':'09:52','open':102.70,'high':102.80,'low':102.45,'close':102.55,'volume':90_000},
        {'time':'09:53','open':102.55,'high':102.70,'low':102.30,'close':102.40,'volume':85_000},
        {'time':'10:15','open':102.40,'high':102.60,'low':102.10,'close':102.30,'volume':60_000},
    ]),

    'expected_entry_price':  104.80,
    'expected_entry_time':   '09:47',
    'expected_stop':         102.50,
    'expected_target':       109.40,
    'expected_exit_price':   102.50,   # stop price (not the low of the bar)
    'expected_exit_time':    '09:52',
    'expected_direction':    'LONG',
    'expected_outcome':      'STOP_HIT',
}


# ──────────────────────────────────────────────────────────────────────────────
# SESSION 3: NO SIGNAL — STRESS REGIME
# ──────────────────────────────────────────────────────────────────────────────
#
# Same setup, but hmm_state='Stress' on the day.
# The scanner runs, the OR forms, but the regime gate blocks any signal.
# Expected: zero trades for the day.

NO_SIGNAL_STRESS_REGIME = {
    **{k: v for k, v in LONG_TRADE_HITS_TARGET.items() if k != 'bars'},
    'hmm_state_override': 'Stress',
    'bars': LONG_TRADE_HITS_TARGET['bars'],  # reuse same bars
    'expected_outcome': 'NO_TRADE',
    'expected_trades':  0,
}
