"""
stress_orb_vix_filter_sim.py — STRESS_ORB + VIX≥30 block filter

Uses existing engine trades (results PKL) + VIX daily cache:
  Baseline : all STRESS_ORB trades (295t, engine $+507)
  Filtered : block STRESS_ORB when VIX < 30  → keep VIX≥30 only

Bootstrap + year-by-year consistency.

Usage:
    cd d:\\raits\\raits
    py -3.11 raits\\scripts\\stress_orb_vix_filter_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
VIX_CACHE   = r'd:\raits\raits\data\cache\vix_daily.pkl'
VIX_THRESH  = 30.0
N_BOOT      = 10_000

with open(PKL_RESULTS, 'rb') as f:
    results = pickle.load(f)
vix = pd.read_pickle(VIX_CACHE)
vix.index = pd.to_datetime(vix.index).normalize()

rows = []
for w in results:
    for t in w.get('trades', []):
        if t.strategy != 'STRESS_ORB':
            continue
        entry_ts = pd.to_datetime(t.entry_time)
        d = entry_ts.normalize()
        rows.append({
            'date'    : d,
            'year'    : str(entry_ts.year),
            'net_pnl' : t.net_pnl,
            'win'     : t.net_pnl > 0,
            'vix'     : vix.get(d, float('nan')),
        })

df = pd.DataFrame(rows).dropna(subset=['vix'])
filtered = df[df['vix'] >= VIX_THRESH]
removed  = df[df['vix'] <  VIX_THRESH]

def summary(label, sub):
    if sub.empty:
        print(f"  {label}: 0 trades"); return
    pnl = sub['net_pnl'].sum()
    wr  = sub['win'].mean()
    avg = sub['net_pnl'].mean()
    print(f"  {label}: {len(sub)}t  P&L=${pnl:+,.0f}  WR={wr:.0%}  avg=${avg:+.1f}/t")

print(f"\n{'='*60}")
print(f"  STRESS_ORB — VIX≥{VIX_THRESH:.0f} GATE (keep VIX≥{VIX_THRESH:.0f} only)")
print(f"{'='*60}")
summary("Baseline  (all STRESS_ORB)", df)
summary(f"Filtered  (VIX ≥{VIX_THRESH:.0f})      ", filtered)
summary(f"Blocked   (VIX < {VIX_THRESH:.0f})      ", removed)
delta = filtered['net_pnl'].sum() - df['net_pnl'].sum()
print(f"  Net engine improvement: ${delta:+,.0f}  "
      f"({'keeps' if delta >= 0 else 'loses'} ${abs(delta):,.0f})")

print(f"\n  By year — BASELINE vs FILTERED:")
print(f"  {'Year':<6} {'Base N':>6} {'Base P&L':>9}  {'Filt N':>6} {'Filt P&L':>9}  {'Delta':>8}  {'Filt WR':>7}")
print(f"  {'-'*63}")
for yr in ['2020', '2021', '2022']:
    b = df[df['year'] == yr]
    f = filtered[filtered['year'] == yr]
    b_pnl = b['net_pnl'].sum()
    f_pnl = f['net_pnl'].sum()
    f_wr  = f['win'].mean() if len(f) else float('nan')
    print(f"  {yr:<6} {len(b):>6} ${b_pnl:>8,.0f}  {len(f):>6} ${f_pnl:>8,.0f}"
          f"  ${f_pnl-b_pnl:>7,.0f}  {f_wr:>6.0%}" if not pd.isna(f_wr) else
          f"  {yr:<6} {len(b):>6} ${b_pnl:>8,.0f}  {len(f):>6} {'—':>9}")

print(f"\n  Blocked trades (VIX < {VIX_THRESH:.0f}) detail:")
for yr in ['2020', '2021', '2022']:
    s = removed[removed['year'] == yr]
    if len(s) == 0:
        print(f"  {yr}:   0t"); continue
    print(f"  {yr}: {len(s):3d}t  ${s['net_pnl'].sum():+7,.0f}  WR={s['win'].mean():.0%}"
          f"  VIX {s['vix'].min():.1f}–{s['vix'].max():.1f}")

print(f"\n  VIX bucket breakdown (all STRESS_ORB trades):")
bins   = [0, 15, 20, 25, 30, 999]
labels = ['<15', '15-20', '20-25', '25-30', '30+']
df['bucket'] = pd.cut(df['vix'], bins=bins, labels=labels, right=False)
print(f"  {'Bucket':<8} {'N':>3}  {'P&L':>8}  {'WR':>5}  {'avg':>8}  {'action'}")
for bkt in labels:
    s = df[df['bucket'] == bkt]
    if len(s) == 0: continue
    action = '✓ keep' if s['vix'].iloc[0] >= VIX_THRESH else '✗ blocked'
    print(f"  {bkt:<8} {len(s):>3}  ${s['net_pnl'].sum():>7,.0f}"
          f"  {s['win'].mean():>4.0%}  ${s['net_pnl'].mean():>7.1f}  {action}")

# ── bootstrap ─────────────────────────────────────────────────────────────────
rng = np.random.default_rng(42)

print(f"\n{'='*60}")
print(f"  BOOTSTRAP — filtered trades (VIX ≥{VIX_THRESH:.0f})")
print(f"{'='*60}")
outcomes = filtered['net_pnl'].values
observed = outcomes.sum()
boot = np.array([rng.choice(outcomes, size=len(outcomes), replace=True).sum()
                 for _ in range(N_BOOT)])
p_val        = (boot <= 0).mean()
ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
sig = "✓ significant" if p_val < 0.05 else "✗ NOT significant"
print(f"  Observed P&L : ${observed:+,.0f}")
print(f"  Bootstrap p  : {p_val:.3f}  {sig}")
print(f"  95% CI       : [${ci_lo:+,.0f}, ${ci_hi:+,.0f}]")

print(f"\n  BOOTSTRAP — blocked trades (VIX < {VIX_THRESH:.0f}, sanity check)")
out2 = removed['net_pnl'].values
boot2 = np.array([rng.choice(out2, size=len(out2), replace=True).sum()
                  for _ in range(N_BOOT)])
p2           = (boot2 >= 0).mean()
ci2_lo, ci2_hi = np.percentile(boot2, [2.5, 97.5])
print(f"  Observed P&L : ${out2.sum():+,.0f}")
print(f"  P(sum≥0)     : {p2:.3f}")
print(f"  95% CI       : [${ci2_lo:+,.0f}, ${ci2_hi:+,.0f}]")
print()
