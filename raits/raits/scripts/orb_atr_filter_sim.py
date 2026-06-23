"""
orb_atr_filter_sim.py — ORB Opening Bar size filter

Hypothesis: if the 9:30 bar is unusually large vs its own historical average,
the breakout has already happened and ORB entry is too late → skip those days.

Signal: 9:30 bar range (H-L) / ticker's mean 9:30 bar range across all days
        if ratio > threshold → skip (bar is "too large")

Tests thresholds: 1.0×, 1.5×, 2.0×, 2.5× mean bar size
Also checks SPY 9:30 bar as a market-level proxy (same idea but one signal for all).

Usage:
    cd d:\\raits\\raits
    py -3.11 raits\\scripts\\orb_atr_filter_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
N_BOOT      = 10_000
OPEN_TIME   = dtime(9, 30)

print("Loading data...")
with open(PKL_RESULTS, 'rb') as f:
    results = pickle.load(f)
with open(PKL_5MIN, 'rb') as f:
    data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# ── extract ORB trades ────────────────────────────────────────────────────────
rows = []
for w in results:
    for t in w.get('trades', []):
        if t.strategy != 'ORB':
            continue
        entry_ts = pd.to_datetime(t.entry_time)
        rows.append({
            'ticker'   : t.ticker,
            'date'     : entry_ts.normalize(),
            'year'     : str(entry_ts.year),
            'direction': getattr(t, 'direction', None),
            'net_pnl'  : t.net_pnl,
            'win'      : t.net_pnl > 0,
        })

df = pd.DataFrame(rows)
print(f"ORB trades: {len(df)}  Tickers: {sorted(df['ticker'].unique())}")

# ── compute 9:30 bar range for each ticker × day ─────────────────────────────
# For normalization: mean 9:30 bar range per ticker across ALL days in PKL
print("Computing 9:30 bar ranges...")

ticker_mean_range = {}   # ticker → mean 9:30 bar range
day_ranges        = {}   # (ticker, date) → 9:30 bar range

for ticker in df['ticker'].unique():
    if ticker not in data_5min:
        continue
    bars = data_5min[ticker].sort_index()
    open_bars = bars[bars.index.time == OPEN_TIME].copy()
    open_bars['range'] = open_bars['high'] - open_bars['low']
    open_bars['date']  = open_bars.index.normalize()

    ticker_mean_range[ticker] = float(open_bars['range'].mean())
    for _, row in open_bars.iterrows():
        day_ranges[(ticker, row['date'])] = float(row['range'])

# ── SPY 9:30 bar as market proxy ──────────────────────────────────────────────
spy = data_5min['SPY'].sort_index()
spy_open = spy[spy.index.time == OPEN_TIME].copy()
spy_open['range'] = spy_open['high'] - spy_open['low']
spy_open['date']  = spy_open.index.normalize()
spy_mean_range    = float(spy_open['range'].mean())
spy_day_range     = {row['date']: float(row['range']) for _, row in spy_open.iterrows()}

# ── attach range info to trades ───────────────────────────────────────────────
df['bar_range']      = df.apply(lambda r: day_ranges.get((r['ticker'], r['date']), np.nan), axis=1)
df['mean_range']     = df['ticker'].map(ticker_mean_range)
df['range_ratio']    = df['bar_range'] / df['mean_range']   # >1 = larger than avg
df['spy_range']      = df['date'].map(spy_day_range)
df['spy_range_ratio']= df['spy_range'] / spy_mean_range

print(f"\nRange ratio stats (ORB trade days):")
print(f"  Ticker range ratio: min={df['range_ratio'].min():.2f}  mean={df['range_ratio'].mean():.2f}  max={df['range_ratio'].max():.2f}")
print(f"  SPY range ratio:    min={df['spy_range_ratio'].min():.2f}  mean={df['spy_range_ratio'].mean():.2f}  max={df['spy_range_ratio'].max():.2f}")

rng = np.random.default_rng(42)

def bootstrap(pnls):
    if len(pnls) < 5:
        return float('nan'), float('nan'), float('nan')
    a = np.array(pnls)
    boot = np.array([rng.choice(a, size=len(a), replace=True).sum() for _ in range(N_BOOT)])
    return (boot <= 0).mean(), *np.percentile(boot, [2.5, 97.5])

def show(label, sub, baseline_n=None):
    if sub.empty or len(sub) < 2:
        print(f"  {label:<30}: {len(sub):>2}t  (too few)"); return
    pnl = sub['net_pnl'].sum()
    wr  = sub['win'].mean()
    p, cl, ch = bootstrap(sub['net_pnl'].tolist())
    sig = '✓' if (not pd.isna(p) and p < 0.05) else ' '
    p_s = f"{p:.3f}" if not pd.isna(p) else "  —  "
    kept = f"  [keeps {len(sub)}/{baseline_n}t]" if baseline_n else ""
    print(f"  {label:<30}: {len(sub):>2}t  ${pnl:>7,.0f}  WR={wr:.0%}  p={p_s}{sig}  CI=[${cl:+,.0f},${ch:+,.0f}]{kept}")

print(f"\n{'='*80}")
print("  TICKER-LEVEL BAR FILTER (skip if ticker's 9:30 bar > threshold × its mean)")
print(f"{'='*80}")
baseline_n = len(df)
show("Baseline (all ORB)", df)

for thr in [1.0, 1.5, 2.0, 2.5, 3.0]:
    kept    = df[df['range_ratio'] <= thr]
    skipped = df[df['range_ratio'] >  thr]
    delta   = kept['net_pnl'].sum() - df['net_pnl'].sum()
    show(f"Keep ratio ≤ {thr:.1f}×", kept, baseline_n)
    if len(skipped):
        sk_pnl = skipped['net_pnl'].sum()
        print(f"    Skipped: {len(skipped)}t  ${sk_pnl:+,.0f}  WR={skipped['win'].mean():.0%}  (engine delta: ${delta:+,.0f})")

print(f"\n{'='*80}")
print("  SPY-LEVEL BAR FILTER (skip ALL ORB if SPY 9:30 bar > threshold × SPY mean)")
print(f"{'='*80}")
show("Baseline (all ORB)", df)

for thr in [1.0, 1.5, 2.0, 2.5, 3.0]:
    kept    = df[df['spy_range_ratio'] <= thr]
    skipped = df[df['spy_range_ratio'] >  thr]
    delta   = kept['net_pnl'].sum() - df['net_pnl'].sum()
    show(f"SPY ratio ≤ {thr:.1f}×", kept, baseline_n)
    if len(skipped):
        sk_pnl = skipped['net_pnl'].sum()
        print(f"    Skipped: {len(skipped)}t  ${sk_pnl:+,.0f}  WR={skipped['win'].mean():.0%}  (engine delta: ${delta:+,.0f})")

# ── show individual ORB trades with their range ratios ───────────────────────
print(f"\n{'='*80}")
print("  ALL ORB TRADES — bar size breakdown")
print(f"{'='*80}")
print(f"  {'Date':<12} {'Ticker':<6} {'Dir':<6} {'P&L':>8}  {'ratio':>6}  {'SPY_r':>6}")
for _, r in df.sort_values('range_ratio', ascending=False).iterrows():
    flag = ' ← LARGE' if r['range_ratio'] > 2.0 else ''
    print(f"  {str(r['date'].date()):<12} {r['ticker']:<6} {str(r['direction']):<6} "
          f"${r['net_pnl']:>7,.0f}  {r['range_ratio']:>5.2f}×  {r['spy_range_ratio']:>5.2f}×{flag}")
print()
