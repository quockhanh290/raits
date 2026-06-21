import sys, pickle
sys.path.insert(0, '..')
import pandas as pd

with open('data/cache/snapshots/results_20260620_233125.pkl', 'rb') as f:
    new = pickle.load(f)

ETF = {"SPY", "QQQ", "IWM"}
trades = []
for w in new:
    for t in w.get('trades', []):
        if t.strategy == 'STRESS_ORB' and t.ticker not in ETF:
            trades.append(t)
            break
    if trades:
        break

if trades:
    t0 = trades[0]
    print("=== Trade fields ===")
    print(vars(t0))
else:
    print("No stock STRESS_ORB trades found")
