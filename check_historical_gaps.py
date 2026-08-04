"""
Full historical gap check (2017→now) cho 5 active parquets.
Flag gaps > 6h bắt đầu không phải Friday (weekend = normal, skip).
"""
import pandas as pd, time
from pathlib import Path

FILES = [
    Path('data/cache/futures/ES_continuous_1m_8y.parquet'),
    Path('data/cache/futures/NQ_continuous_1m_8y.parquet'),
    Path('data/cache/futures/YM_continuous_1m_8y.parquet'),
    Path('data/cache/futures/RTY_continuous_1m_8y.parquet'),
    Path('global_index/data/NKD_continuous_1m_8y.parquet'),
]

THRESHOLD = pd.Timedelta('6h')

for f in FILES:
    t0 = time.time()
    df = pd.read_parquet(f, columns=['close'])
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("America/New_York").tz_localize(None)
    df = df.sort_index()

    diffs = df.index.to_series().diff()
    big = diffs[diffs > THRESHOLD]

    anomalies = []
    for ts, delta in big.items():
        start = ts - delta
        if start.dayofweek == 4:   # Friday → weekend, skip
            continue
        anomalies.append((start, ts, delta))

    print(f'\n{f.name}  ({len(df):,} bars, {time.time()-t0:.1f}s)')
    if not anomalies:
        print('  OK — no anomalous gaps')
    else:
        for start, end, delta in anomalies:
            print(f'  GAP {start.strftime("%Y-%m-%d %H:%M")} ({start.strftime("%a")}) '
                  f'→ {end.strftime("%Y-%m-%d %H:%M")} ({end.strftime("%a")})  [{delta}]')
