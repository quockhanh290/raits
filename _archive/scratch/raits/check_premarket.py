"""Check if market_data has pre-market bars for TSLA on 2022-01-18."""
import sys, pickle
import pandas as pd
from datetime import time as dtime

sys.path.insert(0, '..')

PKL_5MIN = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
DAY = pd.Timestamp("2022-01-18")

with open(PKL_5MIN, "rb") as f:
    data = pickle.load(f)
for tk in data:
    data[tk].index = pd.to_datetime(data[tk].index)

for stk in ["TSLA", "SPY"]:
    if stk not in data: continue
    db = data[stk]
    day_b = db[db.index.normalize() == DAY]
    print(f"\n{stk} on {DAY.date()} — first 5 bars:")
    print(day_b.head(5)[["open","high","low","close"]].to_string())
    print(f"  Earliest bar time: {day_b.index[0].time() if len(day_b) else 'N/A'}")
    pre = day_b[day_b.index.time < dtime(9, 30)]
    print(f"  Pre-market bars (< 9:30): {len(pre)}")
    or_b = day_b[day_b.index.time < dtime(9, 35)]
    print(f"  Bars before 9:35: {len(or_b)}, or_l={float(or_b['low'].min()):.2f}" if len(or_b) else "  No bars before 9:35")
