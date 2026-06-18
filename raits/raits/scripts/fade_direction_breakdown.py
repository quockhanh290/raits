import os, sys, pickle

# Ensure raits package is importable
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

import raits.backtest.data_types  # pre-import so pickle can deserialize

CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_results.pkl")
with open(CACHE, "rb") as f:
    results = pickle.load(f)

results_list = results if isinstance(results, list) else [results]
trades = [t for r in results_list for t in r["trades"]]
fade = [t for t in trades if t.strategy == "FADE"]

print(f"{'Year':<6} {'Dir':<6} {'N':>4}  {'WR':>6}  {'Avg':>8}  {'Total':>10}")
print("-" * 50)
for yr in ["2020", "2021", "2022"]:
    yr_trades = [t for t in fade if str(t.entry_time.year) == yr]
    for direction in ["LONG", "SHORT"]:
        d = [t for t in yr_trades if t.direction == direction]
        if not d:
            continue
        total = sum(t.net_pnl for t in d)
        wr    = sum(1 for t in d if t.net_pnl > 0) / len(d) * 100
        avg   = total / len(d)
        print(f"{yr:<6} {direction:<6} {len(d):>4}  {wr:>5.1f}%  {avg:>+8.2f}  {total:>+10,.0f}")
    print()
