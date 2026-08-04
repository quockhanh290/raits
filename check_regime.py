import pandas as pd, sys
sys.path.insert(0, '.')
from futures._validated_core import benchmark_daily, label_regimes
bench = benchmark_daily('spy_daily_live.csv')
labels = label_regimes(bench, '2018-01-01', 3, '2024-12-31')
s = pd.Series(labels).sort_index()
last_date = s.index[-1]
regime = s.iloc[-1]
print(f'SPY last bar : {last_date.date()}')
print(f'Regime today : {regime}')
if regime == 'Calm':
    print('SAFE — Calm, 0 entries, P1 non-dry-run OK')
else:
    print(f'STOP — regime is {regime}, KHÔNG chay non-dry-run')
