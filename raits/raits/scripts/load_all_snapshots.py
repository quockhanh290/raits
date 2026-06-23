"""
load_all_snapshots.py — summarize all window_debug snapshots from a given date
"""
import sys, os, pickle, glob
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd

SNAPSHOT_DIR = r'd:\raits\raits\data\cache\snapshots'
DATE_FILTER  = '20260622'

files = sorted(glob.glob(os.path.join(SNAPSHOT_DIR, f'results_{DATE_FILTER}_*.pkl')))

print(f"\n{'='*75}")
print(f"  Snapshots from {DATE_FILTER}  ({len(files)} files)")
print(f"{'='*75}")
print(f"  {'File':<35}  {'Net P&L':>10}  {'Trades':>7}  {'2020':>8}  {'2021':>8}  {'2022':>8}")
print(f"  {'-'*73}")

for fpath in files:
    fname = os.path.basename(fpath)
    try:
        with open(fpath, 'rb') as f:
            results = pickle.load(f)

        total_pnl = 0.0
        total_trades = 0
        by_year = {'2020': 0.0, '2021': 0.0, '2022': 0.0}

        for w in results:
            for t in w.get('trades', []):
                pnl = getattr(t, 'net_pnl', 0) or 0
                yr  = str(pd.to_datetime(t.entry_time).year)
                total_pnl    += pnl
                total_trades += 1
                if yr in by_year:
                    by_year[yr] += pnl

        print(f"  {fname:<35}  ${total_pnl:>9,.0f}  {total_trades:>7}  "
              f"${by_year['2020']:>7,.0f}  ${by_year['2021']:>7,.0f}  ${by_year['2022']:>7,.0f}")

    except Exception as e:
        print(f"  {fname:<35}  ERROR: {e}")

print()
