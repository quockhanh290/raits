"""
orb_vix_filter_sim.py — ORB + VIX≥25 block filter

Uses existing engine trades (results PKL) + VIX daily cache to evaluate:
  Baseline : all ORB trades (49t, engine $+1,282)
  Filtered : block ORB when VIX ≥ 25  → keep VIX <25 trades only

Bootstrap on filtered trades + year-by-year consistency check.

Usage:
    cd d:\\raits\\raits
    py -3.11 raits\\scripts\\orb_vix_filter_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
VIX_CACHE   = r'd:\raits\raits\data\cache\vix_daily.pkl'
VIX_THRESH  = 25.0
N_BOOT      = 10_000

# ── load ──────────────────────────────────────────────────────────────────────
with open(PKL_RESULTS, 'rb') as f:
    results = pickle.load(f)
vix = pd.read_pickle(VIX_CACHE)
vix.index = pd.to_datetime(vix.index).normalize()

# ── build ORB trades DataFrame ────────────────────────────────────────────────
rows = []
for w in results:
    for t in w.get('trades', []):
        if t.strategy != 'ORB':
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
df['blocked'] = df['vix'] >= VIX_THRESH

baseline = df
filtered = df[~df['blocked']]
removed  = df[df['blocked']]

# ── print comparison ──────────────────────────────────────────────────────────
def summary(label, sub):
    if sub.empty:
        print(f"  {label}: 0 trades")
        return
    pnl = sub['net_pnl'].sum()
    wr  = sub['win'].mean()
    avg = sub['net_pnl'].mean()
    print(f"  {label}: {len(sub)}t  P&L=${pnl:+,.0f}  WR={wr:.0%}  avg=${avg:+.1f}/t")

print(f"\n{'='*60}")
print(f"  ORB — VIX≥{VIX_THRESH:.0f} BLOCK FILTER")
print(f"{'='*60}")
summary("Baseline  (all ORB)   ", baseline)
summary(f"Filtered  (VIX <{VIX_THRESH:.0f})  ", filtered)
summary(f"Blocked   (VIX ≥{VIX_THRESH:.0f})  ", removed)
print(f"  Net engine improvement: ${filtered['net_pnl'].sum() - baseline['net_pnl'].sum():+,.0f}")

print(f"\n  By year — BASELINE vs FILTERED:")
print(f"  {'Year':<6} {'Base N':>6} {'Base P&L':>9}  {'Filt N':>6} {'Filt P&L':>9}  {'Delta':>8}")
print(f"  {'-'*55}")
for yr in ['2020', '2021', '2022']:
    b = baseline[baseline['year'] == yr]
    f = filtered[filtered['year'] == yr]
    b_pnl = b['net_pnl'].sum()
    f_pnl = f['net_pnl'].sum()
    print(f"  {yr:<6} {len(b):>6} ${b_pnl:>8,.0f}  {len(f):>6} ${f_pnl:>8,.0f}  ${f_pnl-b_pnl:>7,.0f}")

print(f"\n  Blocked trades (VIX ≥{VIX_THRESH:.0f}) detail:")
print(f"  {'Year':<6} {'N':>3}  {'P&L':>8}  {'WR':>5}  {'VIX range'}")
for yr in ['2020', '2021', '2022']:
    s = removed[removed['year'] == yr]
    if len(s) == 0:
        print(f"  {yr:<6}   0")
        continue
    print(f"  {yr:<6} {len(s):>3}  ${s['net_pnl'].sum():>7,.0f}  {s['win'].mean():>4.0%}"
          f"  {s['vix'].min():.1f}–{s['vix'].max():.1f}")

# ── VIX bucket breakdown ──────────────────────────────────────────────────────
print(f"\n  VIX bucket breakdown (all ORB trades):")
bins   = [0, 15, 20, 25, 30, 999]
labels = ['<15', '15-20', '20-25', '25-30', '30+']
df['bucket'] = pd.cut(df['vix'], bins=bins, labels=labels, right=False)
print(f"  {'Bucket':<8} {'N':>3}  {'P&L':>8}  {'WR':>5}  {'avg':>8}  {'keep?'}")
for bkt in labels:
    s = df[df['bucket'] == bkt]
    if len(s) == 0:
        continue
    keep = '✓' if s['vix'].iloc[0] < VIX_THRESH else '✗ blocked'
    print(f"  {bkt:<8} {len(s):>3}  ${s['net_pnl'].sum():>7,.0f}  {s['win'].mean():>4.0%}"
          f"  ${s['net_pnl'].mean():>7.1f}  {keep}")

# ── bootstrap: filtered trades ────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  BOOTSTRAP — filtered trades (VIX <{VIX_THRESH:.0f})")
print(f"{'='*60}")
outcomes = filtered['net_pnl'].values
observed = outcomes.sum()
rng  = np.random.default_rng(42)
boot = np.array([
    rng.choice(outcomes, size=len(outcomes), replace=True).sum()
    for _ in range(N_BOOT)
])
p_val        = (boot <= 0).mean()
ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
sig = "✓ significant" if p_val < 0.05 else "✗ NOT significant"
print(f"  Observed P&L : ${observed:+,.0f}")
print(f"  Bootstrap p  : {p_val:.3f}  {sig}")
print(f"  95% CI       : [${ci_lo:+,.0f}, ${ci_hi:+,.0f}]")

# ── bootstrap: removed trades (sanity check — should be negative) ─────────────
print(f"\n  BOOTSTRAP — blocked trades (VIX ≥{VIX_THRESH:.0f}, sanity check: should be bad)")
if len(removed) > 0:
    out2 = removed['net_pnl'].values
    boot2 = np.array([
        rng.choice(out2, size=len(out2), replace=True).sum()
        for _ in range(N_BOOT)
    ])
    p2        = (boot2 >= 0).mean()
    ci2_lo, ci2_hi = np.percentile(boot2, [2.5, 97.5])
    print(f"  Observed P&L : ${out2.sum():+,.0f}")
    print(f"  P(sum≥0)     : {p2:.3f}  {'(CI spans zero — noise)' if ci2_lo < 0 < ci2_hi else ''}")
    print(f"  95% CI       : [${ci2_lo:+,.0f}, ${ci2_hi:+,.0f}]")

print()
