"""
gf_tf_overlap.py — Check GF_SHORT/GAP_FILL vs TF ticker overlap.

Does GF_SHORT universe expansion steal tickers from TF via same-day trading rules?
Compare old pkl (results_scenario_g) vs new pkl (results_20260619_145722).
"""
import pickle, sys, os
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

PKL_OLD = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots", "results_scenario_g.pkl")
PKL_NEW = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots", "results_20260619_145722.pkl")

import pandas as pd

class _FU(pickle.Unpickler):
    def find_class(self, m, n):
        try: return super().find_class(m, n)
        except: return type(n, (), {})

def load(path):
    with open(path, "rb") as f:
        results = _FU(f).load()
    rows = []
    for w in results:
        for t in w.get("trades", []):
            d = vars(t).copy() if hasattr(t, "__dict__") else dict(t)
            d["entry_time"] = pd.to_datetime(d["entry_time"])
            rows.append(d)
    return rows

print("Loading...")
old_rows = load(PKL_OLD)
new_rows = load(PKL_NEW)

def by_strat(rows, strat):
    return [t for t in rows if t.get("strategy") == strat]

def by_day(trades):
    d = defaultdict(list)
    for t in trades:
        d[t["entry_time"].date()].append(t["ticker"])
    return d

old_tf  = by_day(by_strat(old_rows, "TREND_FOLLOW"))
new_tf  = by_day(by_strat(new_rows, "TREND_FOLLOW"))
new_gfs = by_day(by_strat(new_rows, "GF_SHORT"))
new_gf  = by_day(by_strat(new_rows, "GAP_FILL"))

# Days where TF dropped trades
all_days = sorted(set(old_tf) | set(new_tf))
print("\n=== Days where TF has FEWER trades in new pkl ===")
print(f"{'Date':12} {'Old TF':8} {'New TF':8} {'Lost tickers':30} {'GF_SHORT same day':30}")
print("-"*90)
total_lost = 0
overlap_days = 0
for day in all_days:
    old_tks = set(old_tf.get(day, []))
    new_tks = set(new_tf.get(day, []))
    lost    = old_tks - new_tks
    if not lost:
        continue
    total_lost += len(lost)
    gfs_day = set(new_gfs.get(day, []))
    gf_day  = set(new_gf.get(day, []))
    overlap  = lost & (gfs_day | gf_day)
    if overlap:
        overlap_days += 1
    print(f"{str(day):12} {len(old_tks):8} {len(new_tks):8} {str(sorted(lost)):30} "
          f"GFS:{sorted(gfs_day)} GF:{sorted(gf_day)} overlap={sorted(overlap)}")

print(f"\nTotal lost TF positions: {total_lost}")
print(f"Days with GF/GFS overlap: {overlap_days}")

# Check days where TF gained trades (new tickers in new pkl)
print("\n=== Days where TF has MORE trades in new pkl ===")
gained_total = 0
for day in all_days:
    old_tks = set(old_tf.get(day, []))
    new_tks = set(new_tf.get(day, []))
    gained  = new_tks - old_tks
    if gained:
        gained_total += len(gained)
        print(f"{str(day):12} gained: {sorted(gained)}")
print(f"Total gained TF positions: {gained_total}")
