"""
gf_revert_estimate.py — Estimate impact of reverting GF_SHORT universe expansion.

GF_SHORT universe expansion added tickers not in _all_tickers.
These new trades cause circuit breaker issues (consecutive loss counter)
that block TF at 14:00. This script identifies those extra trades
and estimates what reverting GF_SHORT to _all_tickers would give us.

Comparison: results_scenario_g.pkl (original) vs results_20260619_145722.pkl (current)
"""
import pickle, sys, os
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pandas as pd

PKL_OLD = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots", "results_20260619_132029.pkl")
PKL_NEW = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots", "results_20260619_145722.pkl")

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

old_rows = load(PKL_OLD)
new_rows = load(PKL_NEW)

def by_strat(rows, strat):
    return [t for t in rows if t.get("strategy") == strat]

old_gfs = by_strat(old_rows, "GF_SHORT")
new_gfs = by_strat(new_rows, "GF_SHORT")
old_tf  = by_strat(old_rows, "TREND_FOLLOW")
new_tf  = by_strat(new_rows, "TREND_FOLLOW")

# Identify old GF_SHORT (ticker, day) pairs — these are on _all_tickers
old_gfs_keys = {(t["ticker"], t["entry_time"].date()) for t in old_gfs}

# Extra GF_SHORT trades = in new but NOT in old (new tickers expanded universe)
extra_gfs = [t for t in new_gfs
             if (t["ticker"], t["entry_time"].date()) not in old_gfs_keys]

print("=" * 60)
print("  GF_SHORT UNIVERSE EXPANSION — EXTRA TRADES")
print("=" * 60)
print(f"\nOriginal GF_SHORT: {len(old_gfs)}t")
print(f"Current  GF_SHORT: {len(new_gfs)}t")
print(f"Extra trades (new tickers): {len(extra_gfs)}t")

by_yr = defaultdict(list)
for t in extra_gfs:
    by_yr[t["entry_time"].year].append(t)

extra_pnl = sum(t["net_pnl"] for t in extra_gfs)
print(f"\nExtra trade details:")
for yr in sorted(by_yr):
    tl = by_yr[yr]
    p  = sum(t["net_pnl"] for t in tl)
    print(f"  {yr}: {len(tl)}t  P&L={p:+,.2f}")
    for t in tl:
        print(f"    {t['entry_time'].date()} {t['ticker']:6s} "
              f"net_pnl={t['net_pnl']:+.2f}  exit_reason={t.get('exit_reason','?')}")

print(f"\nIf we REVERT GF_SHORT universe:")
print(f"  GF_SHORT direct P&L change: {-extra_pnl:+,.2f}  "
      f"({len(new_gfs)} → {len(old_gfs)} trades)")

# TF lost vs gained
old_tf_keys = {(t["ticker"], t["entry_time"].date()) for t in old_tf}
new_tf_keys = {(t["ticker"], t["entry_time"].date()) for t in new_tf}
lost_tf  = [(t["ticker"], t["entry_time"].date()) for t in old_tf
            if (t["ticker"], t["entry_time"].date()) not in new_tf_keys]
extra_tf = [(t["ticker"], t["entry_time"].date()) for t in new_tf
            if (t["ticker"], t["entry_time"].date()) not in old_tf_keys]

# P&L of lost TF positions (what we'd recover)
lost_tf_trades = [t for t in old_tf
                  if (t["ticker"], t["entry_time"].date()) not in new_tf_keys]
extra_tf_trades = [t for t in new_tf
                   if (t["ticker"], t["entry_time"].date()) not in old_tf_keys]

lost_pnl  = sum(t["net_pnl"] for t in lost_tf_trades)
extra_pnl_tf = sum(t["net_pnl"] for t in extra_tf_trades)

print(f"\n  TF positions lost (old had, new doesn't): {len(lost_tf)}")
print(f"    P&L of those positions: {lost_pnl:+,.2f}")
print(f"  TF positions gained (new has, old doesn't): {len(extra_tf)}")
print(f"    P&L of those positions: {extra_pnl_tf:+,.2f}")

# Days where extra GF_SHORT trades happen → check if TF was blocked those days
print(f"\n  Days with extra GF_SHORT vs TF blocking:")
print(f"  {'Date':12} {'Extra GFS ticker':8} {'GFS P&L':10} {'TF blocked?':15}")
print("  " + "-"*50)
extra_gfs_days = {t["entry_time"].date(): t for t in extra_gfs}
for day, gfs_t in sorted(extra_gfs_days.items()):
    old_tf_day = [t for t in old_tf if t["entry_time"].date() == day]
    new_tf_day = [t for t in new_tf if t["entry_time"].date() == day]
    blocked = len(old_tf_day) > len(new_tf_day)
    print(f"  {str(day):12} {gfs_t['ticker']:8} "
          f"{gfs_t['net_pnl']:+10.2f}  "
          f"{'TF blocked' if blocked else 'TF unaffected'}")

print(f"\n{'='*60}")
print(f"  ESTIMATE: revert GF_SHORT universe")
print(f"{'='*60}")

current_net = sum(t["net_pnl"] for t in new_rows)
gfs_revert_delta = -sum(t["net_pnl"] for t in extra_gfs)
# Upper bound TF recovery: assume all blocked TF positions recover to old_tf P&L
# Conservative: only days directly correlated with extra GFS
print(f"  Current net P&L:        {current_net:+,.2f}")
print(f"  GF_SHORT direct change: {gfs_revert_delta:+,.2f}")
print(f"  TF potential recovery:  UP TO {lost_pnl - extra_pnl_tf:+,.2f} (if all blocking removed)")
print(f"  Net estimate range:     "
      f"{current_net + gfs_revert_delta:+,.2f} to "
      f"{current_net + gfs_revert_delta + (lost_pnl - extra_pnl_tf):+,.2f}")
