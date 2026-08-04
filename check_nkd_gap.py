import pandas as pd
from pathlib import Path

f = Path('global_index/data/NKD_continuous_1m_8y.parquet')
df = pd.read_parquet(f)
df.index = pd.to_datetime(df.index)
if df.index.tz is not None:
    df.index = df.index.tz_convert("America/New_York").tz_localize(None)
df = df.sort_index()

ws = pd.Timestamp('2026-07-10')
we = pd.Timestamp('2026-07-22')
subset = df[(df.index >= ws) & (df.index <= we)]
diffs = subset.index.to_series().diff()
big_gaps = diffs[diffs > pd.Timedelta('6h')]

print(f'{f.name}: {len(df)} bars, last={df.index[-1]}')
if big_gaps.empty:
    print('  No gaps > 6h in Jul 10-22')
else:
    for ts, delta in big_gaps.items():
        print(f'  GAP: {ts - delta} -> {ts}  ({delta})')
