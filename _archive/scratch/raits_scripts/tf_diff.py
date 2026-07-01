"""
tf_diff.py — Trade-by-trade diff of TREND_FOLLOW between two pkl snapshots.

Compares baseline vs current to find exactly which TF trades changed,
what caused them to appear/disappear, and whether CB or slot-blocking
explains the composition shift.

Usage:
  cd d:\raits\raits
  python raits\scripts\tf_diff.py
"""
import pickle, sys, os
from collections import defaultdict
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
            rows.append(d)
    return rows

print("Loading...")
old_rows = load(PKL_OLD)
new_rows = load(PKL_NEW)

def by_strat(rows, strat):
    return [t for t in rows if t.get("strategy") == strat]

old_tf = by_strat(old_rows, "TREND_FOLLOW")
new_tf = by_strat(new_rows, "TREND_FOLLOW")

# Key: (ticker, entry_date) — TF is swing, entry date identifies uniquely enough
old_keys = {(t["ticker"], t["entry_time"].date()): t for t in old_tf}
new_keys = {(t["ticker"], t["entry_time"].date()): t for t in new_tf}

lost  = {k: v for k, v in old_keys.items() if k not in new_keys}
gained = {k: v for k, v in new_keys.items() if k not in old_keys}
shared = {k: (old_keys[k], new_keys[k]) for k in old_keys if k in new_keys}

print(f"\nTF baseline : {len(old_tf)}t  P&L={sum(t['net_pnl'] for t in old_tf):+,.0f}")
print(f"TF current  : {len(new_tf)}t  P&L={sum(t['net_pnl'] for t in new_tf):+,.0f}")
print(f"Delta       : {len(new_tf)-len(old_tf):+d}t  P&L={sum(t['net_pnl'] for t in new_tf)-sum(t['net_pnl'] for t in old_tf):+,.0f}")

# ── Lost trades (in baseline, not in current) ──────────────────────────────
print(f"\n{'='*70}")
print(f"  LOST TF trades (baseline has, current doesn't): {len(lost)}")
print(f"{'='*70}")
lost_pnl = sum(v["net_pnl"] for v in lost.values())
print(f"  Total P&L of lost trades: {lost_pnl:+,.0f}")
print(f"\n  {'Date':12} {'Ticker':8} {'P&L':8} {'Exit':14} {'HMM':8}")
print("  " + "-"*55)
for (tk, day), t in sorted(lost.items(), key=lambda x: x[0][1]):
    print(f"  {str(day):12} {tk:8} {t['net_pnl']:+8.0f} {t.get('exit_reason','?'):14} {t.get('hmm_state','?')}")

# ── Gained trades (in current, not in baseline) ────────────────────────────
print(f"\n{'='*70}")
print(f"  GAINED TF trades (current has, baseline doesn't): {len(gained)}")
print(f"{'='*70}")
gained_pnl = sum(v["net_pnl"] for v in gained.values())
print(f"  Total P&L of gained trades: {gained_pnl:+,.0f}")
print(f"\n  {'Date':12} {'Ticker':8} {'P&L':8} {'Exit':14} {'HMM':8}")
print("  " + "-"*55)
for (tk, day), t in sorted(gained.items(), key=lambda x: x[0][1]):
    print(f"  {str(day):12} {tk:8} {t['net_pnl']:+8.0f} {t.get('exit_reason','?'):14} {t.get('hmm_state','?')}")

# ── Shared trades with different P&L ──────────────────────────────────────
print(f"\n{'='*70}")
print(f"  SHARED trades with P&L change: {len(shared)} total")
print(f"{'='*70}")
changed = {k: (o, n) for k, (o, n) in shared.items() if abs(o["net_pnl"] - n["net_pnl"]) > 0.5}
shared_delta = sum(n["net_pnl"] - o["net_pnl"] for o, n in shared.values())
print(f"  Total shared P&L delta: {shared_delta:+,.0f}")
print(f"  Shared with P&L difference: {len(changed)}")
if changed:
    print(f"\n  {'Date':12} {'Ticker':8} {'Old P&L':9} {'New P&L':9} {'Delta':8} {'Old exit':14} {'New exit':14}")
    print("  " + "-"*80)
    for (tk, day), (o, n) in sorted(changed.items(), key=lambda x: x[0][1]):
        delta = n["net_pnl"] - o["net_pnl"]
        print(f"  {str(day):12} {tk:8} {o['net_pnl']:+9.0f} {n['net_pnl']:+9.0f} {delta:+8.0f} "
              f"{o.get('exit_reason','?'):14} {n.get('exit_reason','?'):14}")

# ── For each lost TF trade: what OTHER strategies traded on that same day? ─
print(f"\n{'='*70}")
print(f"  WHY LOST? — other strategies on same day as lost TF trades")
print(f"{'='*70}")

old_all_by_day = defaultdict(list)
for t in old_rows:
    old_all_by_day[t["entry_time"].date()].append(t)

new_all_by_day = defaultdict(list)
for t in new_rows:
    new_all_by_day[t["entry_time"].date()].append(t)

for (tk, day) in sorted(lost.keys(), key=lambda x: x[1]):
    lost_t = lost[(tk, day)]
    old_day = old_all_by_day[day]
    new_day = new_all_by_day[day]

    # Count trades by strategy on that day
    old_by_strat = defaultdict(list)
    for t in old_day:
        old_by_strat[t["strategy"]].append(t)
    new_by_strat = defaultdict(list)
    for t in new_day:
        new_by_strat[t["strategy"]].append(t)

    # Check if CB fired on that day in new run
    new_cb = [t for t in new_day if t.get("exit_reason") == "CIRCUIT_BREAKER"]
    old_cb = [t for t in old_day if t.get("exit_reason") == "CIRCUIT_BREAKER"]

    print(f"\n  Lost: {tk} on {day}  (baseline P&L={lost_t['net_pnl']:+.0f})")
    # Show strategy counts old vs new on this day
    all_strats = sorted(set(old_by_strat) | set(new_by_strat))
    for s in all_strats:
        o_n = len(old_by_strat[s])
        n_n = len(new_by_strat[s])
        diff = n_n - o_n
        marker = " ←" if diff != 0 else ""
        print(f"    {s:12}: old={o_n}  new={n_n}  delta={diff:+d}{marker}")
    if new_cb:
        print(f"    *** CB fired in NEW run: {[(t['ticker'], t['strategy']) for t in new_cb]}")
    if old_cb:
        print(f"    *** CB fired in OLD run: {[(t['ticker'], t['strategy']) for t in old_cb]}")

print(f"\n{'='*70}")
print(f"  SUMMARY")
print(f"{'='*70}")
print(f"  Lost {len(lost)} TF trades (P&L={lost_pnl:+,.0f}) — if recovered: {-lost_pnl:+,.0f}")
print(f"  Gained {len(gained)} TF trades (P&L={gained_pnl:+,.0f})")
print(f"  Shared P&L delta: {shared_delta:+,.0f}")
print(f"  Net TF delta: {gained_pnl - lost_pnl + shared_delta:+,.0f}")
