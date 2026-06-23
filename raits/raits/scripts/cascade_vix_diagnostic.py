"""
cascade_vix_diagnostic.py — STRESS_MID and GAP_FILL breakdown by VIX level

Uses the new VIX-gate results PKL to understand cascade:
- STRESS_MID: does VIX<30 Stress = bad trades?
- GAP_FILL: are the 6 extra trades clustered at high VIX?

Usage:
    cd d:\\raits\\raits
    py -3.11 raits\\scripts\\cascade_vix_diagnostic.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260622_211709.pkl'
VIX_PARQUET = r'd:\raits\raits\data\cache\daily\vix_daily.parquet'
N_BOOT      = 10_000

with open(PKL_RESULTS, 'rb') as f:
    results = pickle.load(f)

vix_df = pd.read_parquet(VIX_PARQUET)
vix_df.index = pd.DatetimeIndex(vix_df.index).normalize()
vix = vix_df['vix']

rng = np.random.default_rng(42)

def bootstrap(pnls):
    if len(pnls) < 5:
        return float('nan'), float('nan'), float('nan')
    a = np.array(pnls)
    boot = np.array([rng.choice(a, size=len(a), replace=True).sum()
                     for _ in range(N_BOOT)])
    return (boot <= 0).mean(), *np.percentile(boot, [2.5, 97.5])

def show(label, sub):
    if sub.empty or len(sub) < 2:
        print(f"    {label:<28}: {len(sub):>3}t  (too few)"); return
    pnl = sub['net_pnl'].sum()
    wr  = sub['win'].mean()
    p, cl, ch = bootstrap(sub['net_pnl'].tolist())
    sig = '✓' if (not pd.isna(p) and p < 0.05) else ' '
    p_s = f"{p:.3f}" if not pd.isna(p) else "  —  "
    print(f"    {label:<28}: {len(sub):>3}t  ${pnl:>8,.0f}  WR={wr:.0%}  p={p_s}{sig}"
          f"  avg=${sub['net_pnl'].mean():+.1f}")

# ── extract trades ────────────────────────────────────────────────────────────
rows = []
for w in results:
    for t in w.get('trades', []):
        if t.strategy not in ('STRESS_MID', 'GAP_FILL'):
            continue
        d = pd.to_datetime(t.entry_time).normalize()
        rows.append(dict(
            strategy=t.strategy,
            date=d,
            year=str(d.year),
            net_pnl=t.net_pnl,
            win=t.net_pnl > 0,
            vix=float(vix.get(d, float('nan'))),
        ))

df = pd.DataFrame(rows).dropna(subset=['vix'])
bins   = [0, 15, 20, 25, 30, 999]
labels = ['<15', '15-20', '20-25', '25-30', '30+']
df['bucket'] = pd.cut(df['vix'], bins=bins, labels=labels, right=False)

# ── STRESS_MID ────────────────────────────────────────────────────────────────
sm = df[df['strategy'] == 'STRESS_MID']
print(f"\n{'='*70}")
print(f"  STRESS_MID — VIX breakdown  ({len(sm)} trades total)")
print(f"{'='*70}")
show("ALL", sm)
print()
show("VIX < 30  (would be BLOCKED)", sm[sm['vix'] < 30])
show("VIX ≥ 30  (would be KEPT)", sm[sm['vix'] >= 30])

print(f"\n  By VIX bucket:")
for bkt in labels:
    s = sm[sm['bucket'] == bkt]
    if len(s): show(bkt, s)

print(f"\n  By year — VIX<30 vs VIX≥30:")
for yr in ['2020', '2021', '2022']:
    s = sm[sm['year'] == yr]
    lo = s[s['vix'] < 30]; hi = s[s['vix'] >= 30]
    print(f"  {yr}: VIX<30={len(lo)}t ${lo['net_pnl'].sum():+,.0f}  "
          f"VIX≥30={len(hi)}t ${hi['net_pnl'].sum():+,.0f}")

# Engine delta if we add VIX≥30 gate to STRESS_MID
blocked = sm[sm['vix'] < 30]
kept    = sm[sm['vix'] >= 30]
delta   = kept['net_pnl'].sum() - sm['net_pnl'].sum()
print(f"\n  Engine delta (VIX≥30 gate on STRESS_MID): ${delta:+,.0f}")

# ── GAP_FILL ──────────────────────────────────────────────────────────────────
gf = df[df['strategy'] == 'GAP_FILL']
print(f"\n{'='*70}")
print(f"  GAP_FILL — VIX breakdown  ({len(gf)} trades total)")
print(f"{'='*70}")
show("ALL", gf)
print()
show("VIX < 20", gf[gf['vix'] < 20])
show("VIX 20-25", gf[(gf['vix'] >= 20) & (gf['vix'] < 25)])
show("VIX ≥ 25  (high vol)", gf[gf['vix'] >= 25])

print(f"\n  By VIX bucket:")
for bkt in labels:
    s = gf[gf['bucket'] == bkt]
    if len(s): show(bkt, s)

print(f"\n  By year:")
for yr in ['2020', '2021', '2022']:
    s = gf[gf['year'] == yr]
    if len(s):
        print(f"  {yr}: {len(s)}t  ${s['net_pnl'].sum():+,.0f}  WR={s['win'].mean():.0%}"
              f"  VIX {s['vix'].min():.0f}–{s['vix'].max():.0f}")
        for _, r in s.sort_values('net_pnl').iterrows():
            print(f"    {str(r['date'].date())}  VIX={r['vix']:.0f}  ${r['net_pnl']:+,.0f}"
                  f"  {'WIN' if r['win'] else 'LOSS'}")
print()
