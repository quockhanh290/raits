import numpy as np, sys
sys.path.insert(0, '.')
from futures._validated_core import benchmark_daily
df = benchmark_daily('spy_daily_live.csv').rename('close').to_frame()
ret = df['close'].pct_change()
vol10 = ret.rolling(10).std().iloc[-1] * np.sqrt(252) * 100
vol21 = ret.rolling(21).std().iloc[-1] * np.sqrt(252) * 100
ret5  = (df['close'].iloc[-1] / df['close'].iloc[-6] - 1) * 100
print(f'SPY close today : {df.close.iloc[-1]:.2f}')
print(f'Return 5d       : {ret5:+.2f}%')
print(f'RealVol 10d ann : {vol10:.1f}%')
print(f'RealVol 21d ann : {vol21:.1f}%')
if vol10 < 12:   print('Vol 10d < 12%  -> Calm  OK')
elif vol10 < 20: print('Vol 10d 12-20% -> Normal (border)')
else:            print('Vol 10d > 20%  -> Stress/Crisis')
