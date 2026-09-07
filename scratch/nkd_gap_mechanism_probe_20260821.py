"""Why the NKD stop books a price that never traded.

Reads the NKD 1-minute frame around the failing exit and prints the bar sequence,
the time spacing between bars, and the >15-minute gap flag the engine uses to
decide whether a stop 'gapped through' (fill at the bar open) or was 'touched'
(fill at the stop). Scratch/read-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index._core import load_parquet as gi_load
from global_index import specs as gi_specs

PARQ = "global_index/data/NKD_continuous_1m_8y.parquet"
TARGET = pd.Timestamp("2026-03-11 02:20:00", tz="Asia/Tokyo")
STOP = 55738.57
GAP_MIN = 15.0

c = gi_specs.SPECS["MNKD"]
df = gi_load(PARQ)
df.index = df.index.tz_convert(c.session_tz)

lo = TARGET - pd.Timedelta(minutes=25)
hi = TARGET + pd.Timedelta(minutes=5)
w = df.loc[lo:hi]
prev_all = df.loc[:TARGET]
delta_min = (prev_all.index[-1] - prev_all.index[-2]).total_seconds() / 60.0

print("NKD 1-minute bars around the failing exit (Asia/Tokyo)")
print("stop booked at {:.2f}; SHORT position, so the stop is a BUY".format(STOP))
print()
print("{:<26} {:>10} {:>10} {:>10} {:>10} {:>9} {:>7} {:>8}".format(
    "ts", "open", "high", "low", "close", "vol", "d_min", "above stop?"))
prev_ts = None
for ts, r in w.iterrows():
    d = "" if prev_ts is None else "{:.0f}".format((ts - prev_ts).total_seconds() / 60.0)
    print("{:<26} {:>10.2f} {:>10.2f} {:>10.2f} {:>10.2f} {:>9.0f} {:>7} {:>8}".format(
        str(ts), r["open"], r["high"], r["low"], r["close"], r["volume"], d,
        "YES" if r["high"] >= STOP else "no"))
    prev_ts = ts

print()
print("time spacing into the exit bar : {:.1f} min  (engine gap threshold {:.0f} min)".format(
    delta_min, GAP_MIN))
print("engine flags this bar as a GAP : {}".format(delta_min > GAP_MIN))
print("exit-bar open                  : {:.2f}".format(float(df.loc[TARGET, "open"])))
print("exit-bar low                   : {:.2f}".format(float(df.loc[TARGET, "low"])))
print("booked fill                    : {:.2f}  -> {:.2f} points BELOW the bar low".format(
    STOP, float(df.loc[TARGET, "low"]) - STOP))

# how many minutes before the exit had the price already crossed the stop?
before = df.loc[:TARGET].iloc[:-1]
same_day = before[before.index.normalize() == TARGET.normalize()]
crossed = same_day[same_day["high"] >= STOP]
print()
print("bars earlier on 2026-03-11 whose high already reached the stop: {}".format(len(crossed)))
if len(crossed):
    print("  first at {}  high {:.2f}".format(crossed.index[0], float(crossed["high"].iloc[0])))

# session-wide census: how often do adjacent NKD bars jump, vs R4?
print()
print("=" * 78)
print("CENSUS: adjacent-bar price jumps (|open_t - close_(t-1)|) with NO >15-min break")
print("=" * 78)


def census(frame, label, tick):
    idx = frame.index
    dmin = idx.to_series().diff().dt.total_seconds().to_numpy() / 60.0
    contiguous = dmin <= GAP_MIN
    jump = (frame["open"].to_numpy() - frame["close"].shift(1).to_numpy())
    import numpy as np
    m = contiguous & ~np.isnan(jump)
    j = np.abs(jump[m])
    n = int(m.sum())
    print("{:<8} bars {:>9,}  contiguous {:>9,}  jump>1 tick {:>8,} ({:>5.2f}%)  "
          "jump>4 ticks {:>7,} ({:>5.3f}%)  max {:>8.2f} pts".format(
              label, len(frame), n,
              int((j > tick).sum()), 100.0 * (j > tick).sum() / max(n, 1),
              int((j > 4 * tick).sum()), 100.0 * (j > 4 * tick).sum() / max(n, 1),
              float(j.max()) if n else 0.0))


census(df, "NKD", c.tick)
from futures._validated_core import load_parquet
from futures.basket import BASKET, data_filename
for name, ct in BASKET.items():
    f = load_parquet(str(Path("data/cache/futures") / data_filename(ct)))
    census(f, name, ct.tick)
