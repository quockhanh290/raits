"""
orb_direction_sim.py — ORB LONG vs SHORT diagnostic

Split existing ORB trades (from results PKL) by direction.
If SHORT ORB is dragging performance → gate it out.
Also checks day-of-week breakdown.

Usage:
    cd d:\\raits\\raits
    py -3.11 raits\\scripts\\orb_direction_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
N_BOOT = 10_000

with open(PKL_RESULTS, 'rb') as f:
    results = pickle.load(f)

rows = []
for w in results:
    for t in w.get('trades', []):
        if t.strategy != 'ORB':
            continue
        entry_ts = pd.to_datetime(t.entry_time)
        rows.append({
            'date'     : entry_ts.normalize(),
            'year'     : str(entry_ts.year),
            'dow'      : entry_ts.day_name(),
            'dow_n'    : entry_ts.weekday(),
            'direction': getattr(t, 'direction', None),
            'net_pnl'  : t.net_pnl,
            'win'      : t.net_pnl > 0,
        })

df = pd.DataFrame(rows)
print(f"\nTotal ORB trades: {len(df)}")
print(f"Directions found: {df['direction'].unique()}")

rng = np.random.default_rng(42)

def bootstrap(pnls):
    if len(pnls) < 5:
        return float('nan'), float('nan'), float('nan')
    a = np.array(pnls)
    boot = np.array([rng.choice(a, size=len(a), replace=True).sum() for _ in range(N_BOOT)])
    p = (boot <= 0).mean()
    return p, *np.percentile(boot, [2.5, 97.5])

def show(label, sub):
    if sub.empty:
        print(f"  {label}: 0 trades"); return
    pnl = sub['net_pnl'].sum()
    wr  = sub['win'].mean()
    avg = sub['net_pnl'].mean()
    p, cl, ch = bootstrap(sub['net_pnl'].tolist())
    sig = '✓' if (not pd.isna(p) and p < 0.05) else ' '
    p_s = f"{p:.3f}" if not pd.isna(p) else "  —  "
    print(f"  {label:<22}: {len(sub):>3}t  ${pnl:>8,.0f}  WR={wr:.0%}  avg=${avg:+.1f}  p={p_s} {sig}  CI=[${cl:+,.0f},${ch:+,.0f}]")

# ── Direction breakdown ───────────────────────────────────────────────────────
print(f"\n{'='*75}")
print("  ORB — DIRECTION BREAKDOWN")
print(f"{'='*75}")
show("ALL ORB", df)
for d in ['LONG', 'SHORT']:
    show(d, df[df['direction'] == d])

print(f"\n  By year:")
for yr in ['2020', '2021', '2022']:
    print(f"  {yr}:")
    s = df[df['year'] == yr]
    for d in ['LONG', 'SHORT']:
        show(f"    {d}", s[s['direction'] == d])

# ── Day-of-week breakdown ─────────────────────────────────────────────────────
print(f"\n{'='*75}")
print("  ORB — DAY-OF-WEEK BREAKDOWN (all directions)")
print(f"{'='*75}")
dow_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
for dow in dow_order:
    show(dow, df[df['dow'] == dow])

print(f"\n  Day-of-week × Direction:")
for dow in dow_order:
    for d in ['LONG', 'SHORT']:
        s = df[(df['dow'] == dow) & (df['direction'] == d)]
        if len(s):
            show(f"  {dow[:3]} {d}", s)

# ── LONG-only VIX<25 combined ─────────────────────────────────────────────────
# Try to load VIX if available
VIX_CACHE = r'd:\raits\raits\data\cache\vix_daily.pkl'
if os.path.exists(VIX_CACHE):
    vix = pd.read_pickle(VIX_CACHE)
    vix.index = pd.to_datetime(vix.index).normalize()
    df['vix'] = df['date'].map(vix)

    print(f"\n{'='*75}")
    print("  ORB — LONG-only + VIX<25 combined")
    print(f"{'='*75}")
    long_only   = df[df['direction'] == 'LONG']
    long_vix    = df[(df['direction'] == 'LONG') & (df['vix'] < 25)]
    short_only  = df[df['direction'] == 'SHORT']
    show("LONG only", long_only)
    show("LONG + VIX<25", long_vix)
    show("SHORT only", short_only)
    delta = long_vix['net_pnl'].sum() - df['net_pnl'].sum()
    print(f"\n  Engine delta vs baseline (LONG+VIX<25 only): ${delta:+,.0f}")
print()
