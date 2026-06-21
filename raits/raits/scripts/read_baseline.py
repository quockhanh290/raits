"""
read_baseline.py — Đọc snapshot pkl và breakdown chi tiết theo strategy + year.

Usage:
    cd D:\raits\raits
    python raits\scripts\read_baseline.py [snapshot_name]

Default snapshot: results_20260619_163041 (baseline $14,203)
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
from collections import defaultdict

SNAP_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots")

snap_name = sys.argv[1] if len(sys.argv) > 1 else "results_20260619_163041"
if not snap_name.endswith(".pkl"):
    snap_name += ".pkl"
PKL = os.path.join(SNAP_DIR, snap_name)

if not os.path.exists(PKL):
    print(f"[FAIL] Not found: {PKL}")
    sys.exit(1)

with open(PKL, "rb") as f:
    results = pickle.load(f)

print(f"\nLoaded: {snap_name}")
print(f"Windows: {len(results)}")

# Collect all trades across windows
all_trades = []
for w in results:
    for t in w.get("trades", []):
        all_trades.append(t)

print(f"Total trades: {len(all_trades)}")

years = ["2020", "2021", "2022"]

def yr(t):
    return str(pd.to_datetime(t.entry_time).year)

def summarise(trades):
    n   = len(trades)
    pnl = sum(t.net_pnl or 0 for t in trades)
    wr  = sum(1 for t in trades if (t.net_pnl or 0) > 0) / n * 100 if n else 0
    avg = pnl / n if n else 0
    return n, pnl, wr, avg

# ── System total ──────────────────────────────────────────────────────────────
print(f"\n{'='*72}")
print(f"  SYSTEM TOTAL")
print(f"{'='*72}")
total_pnl = sum(t.net_pnl or 0 for t in all_trades)
print(f"  Grand total: {total_pnl:+,.0f}  ({len(all_trades)} trades)")
for y in years:
    yt = [t for t in all_trades if yr(t) == y]
    n, p, wr, avg = summarise(yt)
    print(f"    {y}: {n:3}t  P&L={p:>+8,.0f}  WR={wr:.0f}%  avg={avg:>+.1f}")

# ── Per-strategy breakdown ────────────────────────────────────────────────────
strats = sorted(set(getattr(t, "strategy", "?") for t in all_trades))
print(f"\n{'='*72}")
print(f"  BY STRATEGY  ({', '.join(strats)})")
print(f"{'='*72}")

for s in strats:
    st = [t for t in all_trades if getattr(t, "strategy", "") == s]
    n, p, wr, avg = summarise(st)
    print(f"\n  {s}  →  {n}t  P&L={p:>+,.0f}  WR={wr:.0f}%  avg={avg:>+.1f}/trade")
    for y in years:
        yt = [t for t in st if yr(t) == y]
        if not yt:
            print(f"    {y}:   0t")
            continue
        n2, p2, wr2, avg2 = summarise(yt)
        # exit reason breakdown
        reasons = defaultdict(int)
        for t in yt:
            reasons[getattr(t, "exit_reason", "?")] += 1
        reason_str = "  ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
        print(f"    {y}: {n2:3}t  P&L={p2:>+8,.0f}  WR={wr2:.0f}%  avg={avg2:>+.1f}  [{reason_str}]")

# ── Regime breakdown per strategy ─────────────────────────────────────────────
print(f"\n{'='*72}")
print(f"  REGIME × STRATEGY")
print(f"{'='*72}")
regimes = sorted(set(getattr(t, "hmm_state", "?") for t in all_trades))
for s in strats:
    st = [t for t in all_trades if getattr(t, "strategy", "") == s]
    if not st: continue
    parts = []
    for r in regimes:
        rt = [t for t in st if getattr(t, "hmm_state", "") == r]
        if rt:
            n2, p2, wr2, _ = summarise(rt)
            parts.append(f"{r}: {n2}t {p2:+,.0f} WR={wr2:.0f}%")
    print(f"  {s:<14} | " + "  |  ".join(parts))

# ── Direction breakdown for FADE ──────────────────────────────────────────────
fade = [t for t in all_trades if getattr(t, "strategy", "") == "FADE"]
if fade:
    print(f"\n{'='*72}")
    print(f"  FADE DIRECTION BREAKDOWN")
    print(f"{'='*72}")
    for y in years:
        yt = [t for t in fade if yr(t) == y]
        if not yt: continue
        longs  = [t for t in yt if getattr(t, "direction", "") == "LONG"]
        shorts = [t for t in yt if getattr(t, "direction", "") == "SHORT"]
        _, lp, lwr, _ = summarise(longs)
        _, sp, swr, _ = summarise(shorts)
        _, tp, twr, _ = summarise(yt)
        print(f"  {y}: {len(yt):3}t {tp:>+8,.0f} WR={twr:.0f}% | "
              f"LONG {len(longs):2}t {lp:>+7,.0f} WR={lwr:.0f}% | "
              f"SHORT {len(shorts):2}t {sp:>+7,.0f} WR={swr:.0f}%")

# ── Time-of-day heatmap (entry hour) ──────────────────────────────────────────
print(f"\n{'='*72}")
print(f"  ENTRY TIME DISTRIBUTION (by strategy)")
print(f"{'='*72}")
print(f"  {'Strategy':<14} {'09:30':>7} {'09:45':>7} {'10:15':>7} {'10:30':>7} {'12:00':>7} {'14:00':>7} {'other':>7}")

def hour_bucket(t):
    import datetime
    dt = pd.to_datetime(t.entry_time)
    tm = dt.time()
    if tm < datetime.time(9, 45):   return "09:30"
    if tm < datetime.time(10, 15):  return "09:45"
    if tm < datetime.time(10, 30):  return "10:15"
    if tm < datetime.time(12, 0):   return "10:30"
    if tm < datetime.time(14, 0):   return "12:00"
    if tm < datetime.time(16, 0):   return "14:00"
    return "other"

buckets = ["09:30","09:45","10:15","10:30","12:00","14:00","other"]
for s in strats:
    st = [t for t in all_trades if getattr(t, "strategy", "") == s]
    if not st: continue
    counts = defaultdict(int)
    for t in st:
        counts[hour_bucket(t)] += 1
    row = "".join(f"{counts.get(b,0):>7}" for b in buckets)
    print(f"  {s:<14} {row}")

print(f"\n{'='*72}")
print(f"  Total system P&L: {total_pnl:+,.0f}")
print(f"{'='*72}\n")
