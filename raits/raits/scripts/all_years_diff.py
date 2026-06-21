"""
all_years_diff.py — Find FIRST divergence across all years between
baseline (132029) and current (163041).

We know Jan-Feb 2020 non-TF trades are identical. The root cause must
be in 2019 or earlier where a GAP_FILL/GF_SHORT trade differs.
"""
import pickle, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pandas as pd

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

print(f"OLD total trades: {len(old_rows)}")
print(f"NEW total trades: {len(new_rows)}")

# Build (strategy, ticker, entry_date) key map for ALL years
def key(t):
    return (t["strategy"], t["ticker"], t["entry_time"].date())

old_map = {}
for t in old_rows:
    k = key(t)
    if k in old_map:
        old_map[k + ("dup",)] = t  # handle duplicates
    else:
        old_map[k] = t

new_map = {}
for t in new_rows:
    k = key(t)
    if k in new_map:
        new_map[k + ("dup",)] = t
    else:
        new_map[k] = t

old_keys = set(old_map)
new_keys = set(new_map)

lost   = sorted(old_keys - new_keys, key=lambda x: x[2])
gained = sorted(new_keys - old_keys, key=lambda x: x[2])
shared_diff = sorted(
    [k for k in old_keys & new_keys if abs(old_map[k]["net_pnl"] - new_map[k]["net_pnl"]) > 0.001],
    key=lambda x: x[2]
)

print(f"\nLost:  {len(lost)}")
print(f"Gained: {len(gained)}")
print(f"Shared P&L change (>$0.001): {len(shared_diff)}")

# Show first 5 of each
def show_list(label, keys, source_map, other_map=None):
    print(f"\n  --- {label} (showing first 10) ---")
    print(f"  {'Date':12} {'Strategy':14} {'Ticker':8} {'P&L':9}", end="")
    if other_map:
        print(f" {'Other P&L':9} {'Delta':8} {'Old exit':14} {'New exit':14}", end="")
    print()
    for k in keys[:10]:
        t = source_map[k]
        line = f"  {str(k[2]):12} {k[0]:14} {k[1]:8} {t['net_pnl']:+9.2f}"
        if other_map and k in other_map:
            o2 = other_map[k]
            line += f" {o2['net_pnl']:+9.2f} {o2['net_pnl']-t['net_pnl']:+8.2f} {t.get('exit_reason','?'):14} {o2.get('exit_reason','?'):14}"
        print(line)
    if len(keys) > 10:
        print(f"  ... and {len(keys)-10} more")

if lost:
    show_list("LOST (in baseline, not in current)", lost, old_map)
if gained:
    show_list("GAINED (in current, not in baseline)", gained, new_map)
if shared_diff:
    show_list("FIRST SHARED P&L CHANGES", shared_diff, old_map, new_map)

# ── Year-by-year summary ──────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"  YEAR-BY-YEAR SUMMARY")
print(f"{'='*70}")
all_years = sorted(set(t["entry_time"].year for t in old_rows + new_rows))
for yr in all_years:
    old_yr = [t for t in old_rows if t["entry_time"].year == yr]
    new_yr = [t for t in new_rows if t["entry_time"].year == yr]
    old_pnl = sum(t["net_pnl"] for t in old_yr)
    new_pnl = sum(t["net_pnl"] for t in new_yr)
    delta = new_pnl - old_pnl
    print(f"  {yr}: OLD={len(old_yr):3}t P&L={old_pnl:+8.0f}  NEW={len(new_yr):3}t P&L={new_pnl:+8.0f}  delta={delta:+8.0f}  trades_diff={len(new_yr)-len(old_yr):+d}")

# ── Find FIRST divergence in chronological exit-time order ───────────────────
print(f"\n{'='*70}")
print(f"  FIRST DIVERGENCE — chronological exit-time trace")
print(f"{'='*70}")

def exit_sort_key(t):
    et = t.get("exit_time")
    if et is not None:
        return pd.to_datetime(et)
    return t["entry_time"] + pd.Timedelta(hours=8)

old_sorted = sorted(old_rows, key=exit_sort_key)
new_sorted = sorted(new_rows, key=exit_sort_key)

print(f"\n  Scanning for first mismatched trade (strategy/ticker/date)...")
found_first = False
for i, (o, n) in enumerate(zip(old_sorted, new_sorted)):
    o_strat = (o["strategy"], o["ticker"], exit_sort_key(o).date())
    n_strat = (n["strategy"], n["ticker"], exit_sort_key(n).date())
    if o_strat != n_strat:
        # Show context: 3 before, this one, 3 after
        print(f"\n  FIRST MISMATCH at index {i}:")
        for j in range(max(0, i-3), min(i+4, min(len(old_sorted), len(new_sorted)))):
            oo, nn = old_sorted[j], new_sorted[j]
            marker = " <===" if j == i else ""
            print(f"  [{j:4}] OLD: {exit_sort_key(oo).date()} {oo['strategy']:14} {oo['ticker']:8} {oo['net_pnl']:+8.2f} {oo.get('exit_reason','?')}")
            print(f"       NEW: {exit_sort_key(nn).date()} {nn['strategy']:14} {nn['ticker']:8} {nn['net_pnl']:+8.2f} {nn.get('exit_reason','?')}{marker}")
            print()
        found_first = True
        break

if not found_first:
    print("  No identity mismatch found — lists are identical in strategy/ticker/date through the shorter list.")
    print(f"  But lengths differ: OLD={len(old_sorted)}, NEW={len(new_sorted)}")
