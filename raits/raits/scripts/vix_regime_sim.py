"""
vix_regime_sim.py — VIX level as strategy filter

Downloads daily VIX (^VIX via yfinance) and cross-references with engine trades
to answer: does VIX level on a trading day predict which strategies win?

If yes → VIX can be added as an HMM feature or a per-strategy filter.

Analysis:
  1. P&L by strategy × VIX bucket (<15 / 15-20 / 20-25 / 25-30 / 30+)
  2. Normal regime days by VIX bucket: trade count, WR, avg P&L
  3. Per-strategy bootstrap on best VIX sub-range vs full baseline
  4. Correlation: VIX level vs trade P&L per strategy

Decision rule: implement filter only if p < 0.05 AND consistent 2020/2021/2022.

Usage:
    cd d:\\raits\\raits
    py -3.11 raits\\scripts\\vix_regime_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np
import yfinance as yf


PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
VIX_CACHE   = r'd:\raits\raits\data\cache\vix_daily.pkl'
N_BOOT      = 10_000

BUCKETS      = [0, 15, 20, 25, 30, 999]
BUCKET_NAMES = ['<15', '15-20', '20-25', '25-30', '30+']

# ── load results ──────────────────────────────────────────────────────────────
print("Loading results PKL...")
with open(PKL_RESULTS, 'rb') as f:
    results = pickle.load(f)

trades_all = [t for w in results for t in w.get('trades', [])]
print(f"Total trades: {len(trades_all)}")

# ── build trades DataFrame ────────────────────────────────────────────────────
rows = []
for t in trades_all:
    entry_ts = pd.to_datetime(t.entry_time)
    rows.append({
        'strategy' : t.strategy,
        'date'     : entry_ts.normalize(),
        'year'     : str(entry_ts.year),
        'hmm_state': getattr(t, 'hmm_state', None),
        'net_pnl'  : t.net_pnl,
        'win'      : t.net_pnl > 0,
    })
df_trades = pd.DataFrame(rows)

# ── fetch / load VIX daily ────────────────────────────────────────────────────
if os.path.exists(VIX_CACHE):
    print("Loading VIX from cache...")
    vix = pd.read_pickle(VIX_CACHE)
else:
    print("Downloading VIX daily from yfinance...")
    raw = yf.download("^VIX", start="2019-01-01", end="2023-01-01",
                      auto_adjust=True, progress=False)
    close = raw['Close']
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]   # multi-ticker columns → take first (only) column
    vix = close.rename('vix').dropna()
    vix.index = pd.to_datetime(vix.index).normalize()
    vix.to_pickle(VIX_CACHE)
    print(f"  Saved to {VIX_CACHE}")

print(f"VIX range: {vix.min():.1f} – {vix.max():.1f}  ({len(vix)} days)")

# ── join VIX to trades ────────────────────────────────────────────────────────
df_trades['vix'] = df_trades['date'].map(vix.to_dict())
missing = df_trades['vix'].isna().sum()
if missing:
    print(f"  WARNING: {missing} trades with no VIX lookup (holidays?) — dropped")
df_trades = df_trades.dropna(subset=['vix'])

df_trades['vix_bucket'] = pd.cut(
    df_trades['vix'], bins=BUCKETS, labels=BUCKET_NAMES, right=False
)

# ── VIX distribution on Normal days ──────────────────────────────────────────
normal_trades = df_trades[df_trades['hmm_state'] == 'Normal']
print(f"\nNormal regime trades: {len(normal_trades)}")

# ── helper: bucket summary table ─────────────────────────────────────────────
def bucket_table(df, label):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"  {'Bucket':<10} {'N':>4}  {'P&L':>9}  {'WR':>6}  {'Avg/t':>8}  {'2020':>7}  {'2021':>7}  {'2022':>7}")
    print(f"  {'-'*67}")
    for bkt in BUCKET_NAMES:
        s = df[df['vix_bucket'] == bkt]
        if len(s) == 0:
            print(f"  {bkt:<10} {'0':>4}  {'—':>9}")
            continue
        pnl = s['net_pnl'].sum()
        wr  = s['win'].mean()
        avg = s['net_pnl'].mean()
        yr  = {y: s[s['year'] == y]['net_pnl'].sum() for y in ['2020','2021','2022']}
        print(f"  {bkt:<10} {len(s):>4}  ${pnl:>8,.0f}  {wr:>5.0%}  ${avg:>7.1f}"
              f"  ${yr['2020']:>6,.0f}  ${yr['2021']:>6,.0f}  ${yr['2022']:>6,.0f}")
    total = df
    pnl = total['net_pnl'].sum()
    wr  = total['win'].mean()
    avg = total['net_pnl'].mean()
    yr  = {y: total[total['year'] == y]['net_pnl'].sum() for y in ['2020','2021','2022']}
    print(f"  {'-'*67}")
    print(f"  {'TOTAL':<10} {len(total):>4}  ${pnl:>8,.0f}  {wr:>5.0%}  ${avg:>7.1f}"
          f"  ${yr['2020']:>6,.0f}  ${yr['2021']:>6,.0f}  ${yr['2022']:>6,.0f}")

# ── per-strategy bucket breakdown ─────────────────────────────────────────────
strategies = df_trades['strategy'].value_counts().index.tolist()

bucket_table(df_trades, "ALL STRATEGIES — P&L by VIX bucket")

for strat in strategies:
    s = df_trades[df_trades['strategy'] == strat]
    if len(s) < 5:
        continue
    bucket_table(s, f"{strat} — P&L by VIX bucket")

# ── VIX correlation with P&L per strategy ────────────────────────────────────
print(f"\n{'='*70}")
print("  CORRELATION: VIX level vs trade P&L")
print(f"{'='*70}")
print(f"  {'Strategy':<18} {'N':>4}  {'Corr(VIX,P&L)':>14}  {'Interpretation'}")
print(f"  {'-'*65}")
for strat in strategies:
    s = df_trades[df_trades['strategy'] == strat]
    if len(s) < 5:
        continue
    corr = s['vix'].corr(s['net_pnl'])
    interp = (
        "higher VIX → better" if corr > 0.1 else
        "higher VIX → worse"  if corr < -0.1 else
        "no relationship"
    )
    print(f"  {strat:<18} {len(s):>4}  {corr:>14.3f}  {interp}")

# ── bootstrap: best VIX range vs full baseline per strategy ──────────────────
print(f"\n{'='*70}")
print("  BOOTSTRAP: best VIX sub-range vs full strategy baseline")
print(f"{'='*70}")
rng = np.random.default_rng(42)

for strat in strategies:
    s = df_trades[df_trades['strategy'] == strat].copy()
    if len(s) < 5:
        continue

    # Find the single bucket with best avg P&L (minimum data requirement: 5 trades)
    best_bkt = None
    best_avg = -np.inf
    for bkt in BUCKET_NAMES:
        sub = s[s['vix_bucket'] == bkt]
        if len(sub) >= 5 and sub['net_pnl'].mean() > best_avg:
            best_avg = sub['net_pnl'].mean()
            best_bkt = bkt

    if best_bkt is None:
        continue

    sub = s[s['vix_bucket'] == best_bkt]
    outcomes = sub['net_pnl'].values
    observed = outcomes.sum()
    boot = np.array([
        rng.choice(outcomes, size=len(outcomes), replace=True).sum()
        for _ in range(N_BOOT)
    ])
    p_val    = (boot <= 0).mean()
    ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
    full_avg = s['net_pnl'].mean()
    sig = "✓" if p_val < 0.05 else "✗"

    print(f"\n  {strat}  best bucket: VIX {best_bkt}  ({len(sub)}t  "
          f"avg=${best_avg:+.1f} vs full avg=${full_avg:+.1f})")
    print(f"  Bootstrap: p={p_val:.3f}  CI=[${ci_lo:+,.0f}, ${ci_hi:+,.0f}]  {sig}")

# ── Normal-day VIX distribution ───────────────────────────────────────────────
print(f"\n{'='*70}")
print("  VIX distribution on Normal regime days (all strategies)")
print(f"{'='*70}")
normal_days_vix = (
    normal_trades.groupby('date')['vix'].first()
)
print(f"  Median VIX on Normal days: {normal_days_vix.median():.1f}")
print(f"  Mean   VIX on Normal days: {normal_days_vix.mean():.1f}")
for bkt, lo, hi in zip(BUCKET_NAMES, BUCKETS[:-1], BUCKETS[1:]):
    cnt = ((normal_days_vix >= lo) & (normal_days_vix < hi)).sum()
    print(f"  VIX {bkt:<8}: {cnt:3d} days")
