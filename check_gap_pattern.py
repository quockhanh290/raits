"""Xem pattern gaps thực tế trong ES parquet để calibrate threshold."""
import pandas as pd, time
from pathlib import Path

t0 = time.time()
f = Path('data/cache/futures/ES_continuous_1m_8y.parquet')
df = pd.read_parquet(f, columns=['close'])  # chỉ đọc 1 cột cho nhanh
df.index = pd.to_datetime(df.index)
if df.index.tz is not None:
    df.index = df.index.tz_convert("America/New_York").tz_localize(None)
t1 = time.time()
print(f"Load time: {t1-t0:.1f}s  ({len(df):,} bars)")

diffs = df.index.to_series().diff()

# Distribution of gap sizes
print("\nGap size distribution (all gaps > 1 min):")
buckets = [2, 5, 30, 60, 120, 300, 600, 1440, 2880, 99999]
labels  = ['1-2m','2-5m','5-30m','30m-1h','1-2h','2-5h','5-10h','10h-2d','2d-3d','>3d']
for lo, hi, lbl in zip([1]+buckets[:-1], buckets, labels):
    n = ((diffs > pd.Timedelta(minutes=lo)) & (diffs <= pd.Timedelta(minutes=hi))).sum()
    if n: print(f"  {lbl:>10}: {n:,}")

# Show all gaps > 2h with weekday info
print("\nSample gaps > 2h (first 20):")
big = diffs[diffs > pd.Timedelta('2h')].head(20)
for ts, delta in big.items():
    start = ts - delta
    print(f"  {start.strftime('%Y-%m-%d %H:%M')} ({start.strftime('%a')}) → {ts.strftime('%Y-%m-%d %H:%M')} ({ts.strftime('%a')})  {delta}")

print(f"\nTotal compute time: {time.time()-t0:.1f}s")
