import pandas as pd
from pathlib import Path

parquet_dir = Path('data/cache/futures')
window_start = pd.Timestamp('2026-07-10', tz='UTC')
window_end   = pd.Timestamp('2026-07-22', tz='UTC')

for f in sorted(parquet_dir.glob('*.parquet')):
    df = pd.read_parquet(f)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    ws = window_start.tz_localize(None) if df.index.tz is None else window_start
    we = window_end.tz_localize(None)   if df.index.tz is None else window_end
    subset = df[(df.index >= ws) & (df.index <= we)]
    diffs = subset.index.to_series().diff()
    big_gaps = diffs[diffs > pd.Timedelta('6h')]
    print(f'{f.name}: last={df.index[-1]}')
    if big_gaps.empty:
        print('  No gaps > 6h in Jul 10-22')
    else:
        for ts, delta in big_gaps.items():
            print(f'  GAP: {ts - delta} -> {ts}  ({delta})')
