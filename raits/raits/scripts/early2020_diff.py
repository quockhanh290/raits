"""
early2020_diff.py — Find ALL strategy differences in early 2020
between baseline (132029) and current (163041).

The cascade starts from NVDA/QCOM/MU TF entries on Feb 7-10 2020.
Those appeared because TF slots were free — something before Feb 7
must be different (CB counter, open positions, or trade selection).

Check every strategy, every trade, in the window leading up to Feb 7.
"""
import pickle, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pandas as pd
from datetime import date

PKL_OLD = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots", "results_20260619_132029.pkl")
PKL_NEW = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots", "results_20260619_163041.pkl")

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
            if hasattr(t, "exit_time") and t.exit_time is not None:
                d["exit_time"] = pd.to_datetime(t.exit_time)
            rows.append(d)
    return rows

print("Loading...")
old_rows = load(PKL_OLD)
new_rows = load(PKL_NEW)

CUTOFF = date(2020, 3, 1)  # look at Jan-Feb 2020 only

old_early = [t for t in old_rows if t["entry_time"].date() < CUTOFF]
new_early = [t for t in new_rows if t["entry_time"].date() < CUTOFF]

# Group by (strategy, ticker, entry_date)
def key(t):
    return (t["strategy"], t["ticker"], t["entry_time"].date())

old_map = {key(t): t for t in old_early}
new_map = {key(t): t for t in new_early}

old_keys = set(old_map)
new_keys = set(new_map)

lost   = old_keys - new_keys
gained = new_keys - old_keys
shared_diff = {k for k in old_keys & new_keys
               if abs(old_map[k]["net_pnl"] - new_map[k]["net_pnl"]) > 0.001}

print(f"\n{'='*70}")
print(f"  ALL STRATEGY DIFF — Jan-Feb 2020")
print(f"{'='*70}")
print(f"  Total trades OLD: {len(old_early)}  NEW: {len(new_early)}")
print(f"  Lost (old has, new doesn't): {len(lost)}")
print(f"  Gained (new has, old doesn't): {len(gained)}")
print(f"  Shared with P&L change: {len(shared_diff)}")

if lost:
    print(f"\n  --- LOST trades ---")
    print(f"  {'Date':12} {'Strategy':14} {'Ticker':8} {'P&L':8} {'Exit':16}")
    for k in sorted(lost, key=lambda x: x[2]):
        t = old_map[k]
        print(f"  {str(k[2]):12} {k[0]:14} {k[1]:8} {t['net_pnl']:+8.0f} {t.get('exit_reason','?')}")

if gained:
    print(f"\n  --- GAINED trades ---")
    print(f"  {'Date':12} {'Strategy':14} {'Ticker':8} {'P&L':8} {'Exit':16}")
    for k in sorted(gained, key=lambda x: x[2]):
        t = new_map[k]
        print(f"  {str(k[2]):12} {k[0]:14} {k[1]:8} {t['net_pnl']:+8.0f} {t.get('exit_reason','?')}")

if shared_diff:
    print(f"\n  --- SHARED with P&L change ---")
    print(f"  {'Date':12} {'Strategy':14} {'Ticker':8} {'Old P&L':9} {'New P&L':9} {'Delta':8} {'Old exit':14} {'New exit':14}")
    for k in sorted(shared_diff, key=lambda x: x[2]):
        o, n = old_map[k], new_map[k]
        print(f"  {str(k[2]):12} {k[0]:14} {k[1]:8} {o['net_pnl']:+9.0f} {n['net_pnl']:+9.0f} "
              f"{n['net_pnl']-o['net_pnl']:+8.0f} {o.get('exit_reason','?'):14} {n.get('exit_reason','?'):14}")

# ── Reconstruct consecutive_loss counter chronologically ──────────────────
print(f"\n{'='*70}")
print(f"  CB COUNTER TRACE — all closed trades in Jan-Feb 2020 (chronological)")
print(f"  (sorted by exit_time if available, else entry_time)")
print(f"{'='*70}")

def exit_sort_key(t):
    et = t.get("exit_time")
    if et is not None:
        return pd.to_datetime(et)
    return t["entry_time"] + pd.Timedelta(hours=8)

old_sorted = sorted(old_early, key=exit_sort_key)
new_sorted = sorted(new_early, key=exit_sort_key)

def simulate_cb(trades):
    consecutive = 0
    cb_fires = []
    history = []
    for t in trades:
        pnl = t["net_pnl"]
        if pnl < 0:
            consecutive += 1
        else:
            consecutive = 0
        history.append({
            "exit": exit_sort_key(t).date() if exit_sort_key(t) else "?",
            "strat": t["strategy"],
            "ticker": t["ticker"],
            "pnl": pnl,
            "consecutive": consecutive,
            "cb_fire": consecutive >= 5,
        })
        if consecutive >= 5:
            cb_fires.append(exit_sort_key(t).date())
            consecutive = 0  # reset after fire
    return history, cb_fires

old_hist, old_cb = simulate_cb(old_sorted)
new_hist, new_cb = simulate_cb(new_sorted)

print(f"\n  OLD CB fires in Jan-Feb 2020: {old_cb}")
print(f"  NEW CB fires in Jan-Feb 2020: {new_cb}")

# Show where counters diverge
print(f"\n  Counter trace (show first divergence):")
print(f"  {'#':4} {'Exit date':12} {'Strategy':14} {'Ticker':8} {'OLD pnl':9} {'OLD consec':11} {'NEW pnl':9} {'NEW consec':11}")
print("  " + "-"*90)
for i, (o, n) in enumerate(zip(old_hist, new_hist)):
    marker = " *** DIVERGE" if o["consecutive"] != n["consecutive"] else ""
    if marker or i < 5 or o["cb_fire"] or n["cb_fire"]:
        print(f"  {i:4} {str(o['exit']):12} {o['strat']:14} {o['ticker']:8} "
              f"{o['pnl']:+9.0f} {o['consecutive']:11} "
              f"{n['pnl']:+9.0f} {n['consecutive']:11}{marker}")
    if marker:
        # Show context around divergence
        pass

# If lists differ in length or have different trades, show first diff
if len(old_hist) != len(new_hist):
    print(f"\n  *** Different trade count: old={len(old_hist)}, new={len(new_hist)}")
    min_len = min(len(old_hist), len(new_hist))
    for i in range(min_len):
        if old_hist[i]["strat"] != new_hist[i]["strat"] or old_hist[i]["ticker"] != new_hist[i]["ticker"]:
            print(f"  First divergent trade at index {i}:")
            print(f"    OLD: {old_hist[i]}")
            print(f"    NEW: {new_hist[i]}")
            break
