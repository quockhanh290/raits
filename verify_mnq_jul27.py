"""
verify_mnq_jul27.py — Option A P0c: verify desired_basket Jul27 MNQ signal
against actual parquet bars.

Checks:
  1. Entry bar close ≈ 28312.25 (resume bar in TF window Jul27)
  2. Chandelier stop ≈ 28361.42 (highest_high - atr_mult * atr over lookback)
  3. Direction SHORT (close < EMA20 at resume bar)
"""
import sys; sys.path.insert(0, ".")
import pandas as pd
import numpy as np
from futures.basket import SWING_TF_PARAM, data_filename, BASKET
from pathlib import Path

PARQUET = Path("data/cache/futures") / data_filename(BASKET["MNQ"])
ATR_MULT = SWING_TF_PARAM["chandelier_atr_mult"]
EMA_PERIOD = SWING_TF_PARAM["ema_period"]

# ── Load MNQ parquet ──────────────────────────────────────────────────────────
df = pd.read_parquet(PARQUET)
if df.index.tz is not None:
    df.index = df.index.tz_convert("America/New_York").tz_localize(None)
df.columns = [c.lower() for c in df.columns]
df = df.sort_index()

# ── Jul27 intraday bars ────────────────────────────────────────────────────────
day = "2026-07-27"
day_bars = df.loc[day]
bars5 = day_bars["close"].resample("5min").last().dropna()
bars5_ohlc = day_bars.resample("5min").agg(
    {"open": "first", "high": "max", "low": "min", "close": "last"}
).dropna()

tf_bars = bars5_ohlc.between_time("14:00", "15:55")
print(f"MNQ 5-min TF window Jul27 ({len(tf_bars)} bars):")
print(f"  {'Time':<8}  {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10}")
for ts, row in tf_bars.iterrows():
    print(f"  {str(ts.time()):<8}  {row['open']:>10.2f} {row['high']:>10.2f}"
          f" {row['low']:>10.2f} {row['close']:>10.2f}")

# ── EMA20 on full-day 5-min bars up to TF window ─────────────────────────────
full_day_5m = day_bars["close"].resample("5min").last().dropna()
ema_series = full_day_5m.ewm(span=EMA_PERIOD, adjust=False).mean()

print(f"\nEMA{EMA_PERIOD} at TF bars (close vs EMA → direction):")
tf_idx = tf_bars.index
for ts in tf_idx:
    if ts in ema_series.index:
        c = bars5_ohlc.loc[ts, "close"]
        e = ema_series.loc[ts]
        dirn = "LONG" if c >= e else "SHORT"
        print(f"  {str(ts.time())}  close={c:.2f}  EMA{EMA_PERIOD}={e:.2f}  diff={c-e:+.2f}  → {dirn}")

# ── Chandelier stop ────────────────────────────────────────────────────────────
# ATR on 5-min bars (True Range), rolling window same as chandelier lookback
# swing_tf_harness uses chandelier over session bars
print(f"\nChandelier stop estimate (atr_mult={ATR_MULT}):")
# Need session bars (18:00 prev day to 18:00 today) for ATR
prev = pd.Timestamp(day) - pd.Timedelta(days=1)
sess = df.loc[str(prev.date()) + " 18:00":day + " 18:00"]
sess5 = sess.resample("5min").agg({"high": "max", "low": "min", "close": "last"}).dropna()
tr = pd.concat([
    sess5["high"] - sess5["low"],
    (sess5["high"] - sess5["close"].shift()).abs(),
    (sess5["low"]  - sess5["close"].shift()).abs(),
], axis=1).max(axis=1)
atr = tr.ewm(span=14, adjust=False).mean()

# At first TF bar: highest_high over session, chandelier SHORT stop = lowest_low + mult*atr
tf_start = pd.Timestamp(day + " 14:00")
sess_up_to_tf = sess5[sess5.index <= tf_start]
if not sess_up_to_tf.empty:
    highest_high = sess_up_to_tf["high"].max()
    lowest_low   = sess_up_to_tf["low"].min()
    atr_at_tf = atr.loc[atr.index <= tf_start].iloc[-1] if len(atr.loc[atr.index <= tf_start]) > 0 else np.nan
    stop_long  = highest_high - ATR_MULT * atr_at_tf   # LONG stop (below high)
    stop_short = lowest_low   + ATR_MULT * atr_at_tf   # SHORT stop (above low)
    print(f"  At 14:00 ET: highest_high={highest_high:.2f}  lowest_low={lowest_low:.2f}")
    print(f"  ATR14 = {atr_at_tf:.2f}  mult={ATR_MULT}")
    print(f"  Chandelier SHORT stop = lowest_low + mult*atr = {stop_short:.2f}")
    print(f"  Chandelier LONG  stop = highest_high - mult*atr = {stop_long:.2f}")
    print(f"  desired_basket reported stop = 28361.42")

print(f"\n--- Verify summary ---")
print(f"  entry    reported=28312.25  (check if resume bar close ≈ this)")
print(f"  stop     reported=28361.42  (check chandelier above)")
print(f"  direction=SHORT             (check EMA diff < 0 above)")
