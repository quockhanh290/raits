"""
vwap_reclaim_sim.py — VWAP Reclaim LONG

Signal: stock dipped below VWAP before 10:30, then reclaims (close > VWAP) at 11:00
  + SPY above VWAP at 11:00

Trade: LONG
  Entry  : 11:00 close
  Stop   : morning LOD (9:30–11:00) - 0.1xATR
  Target : 2R
  Exit   : 14:00 time stop
  Regime : Normal only
  Risk   : fixed $500/trade

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\vwap_reclaim_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

ENTRY_TIME     = dtime(11, 0)
EXIT_TIME      = dtime(14, 0)
DIPPED_BY      = dtime(10, 30)   # must have dipped below VWAP by this time
TARGET_R       = 2.0
RISK_PER_TRADE = 500.0

print("Loading data...")
with open(PKL_RESULTS, 'rb') as f: results = pickle.load(f)
with open(PKL_5MIN,    'rb') as f: data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# Normal regime days
normal_days = set()
for w in results:
    for t in w.get('trades', []):
        if getattr(t, 'hmm_state', None) == 'Normal':
            normal_days.add(pd.to_datetime(t.entry_time).normalize())
normal_days = sorted(normal_days)
print(f"Normal days: {len(normal_days)}")

EXCLUDE = {'SPY', 'QQQ', 'IWM'}
available_tickers = [tk for tk in data_5min if tk not in EXCLUDE]

# Build per-ticker VWAP per day
def build_vwap(bars):
    b = bars.copy()
    b['tp']  = (b['high'] + b['low'] + b['close']) / 3
    b['tpv'] = b['tp'] * b['volume']
    b['date'] = b.index.normalize()
    b['cum_tpv'] = b.groupby('date')['tpv'].cumsum()
    b['cum_vol'] = b.groupby('date')['volume'].cumsum()
    b['vwap'] = b['cum_tpv'] / b['cum_vol']
    return b

# SPY VWAP lookup
spy_bars = build_vwap(data_5min['SPY'].sort_index())
spy_above = (spy_bars['close'] > spy_bars['vwap'])
spy_above = spy_above.reindex(
    pd.date_range(spy_bars.index[0], spy_bars.index[-1], freq='5min'), method='ffill'
)
def spy_bull(ts): return bool(spy_above.get(ts.floor('5min'), False))


def compute_atr(bars, period=14):
    if len(bars) < 2:
        return float(bars['close'].iloc[-1]) * 0.015
    hl  = bars['high'] - bars['low']
    hpc = (bars['high'] - bars['close'].shift(1)).abs()
    lpc = (bars['low']  - bars['close'].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())


print("Running sim...")
trades = []

for day in normal_days:
    for ticker in available_tickers:
        if ticker not in data_5min:
            continue
        all_bars = data_5min[ticker][data_5min[ticker].index.normalize() == day].sort_index()
        if len(all_bars) < 10:
            continue

        # Build VWAP for this ticker this day
        b = all_bars.copy()
        b['tp']  = (b['high'] + b['low'] + b['close']) / 3
        b['tpv'] = b['tp'] * b['volume']
        b['cum_tpv'] = b['tpv'].cumsum()
        b['cum_vol'] = b['volume'].cumsum()
        b['vwap'] = b['cum_tpv'] / b['cum_vol']

        # Must have dipped below VWAP at some point before 10:30
        morning = b[b.index.time <= DIPPED_BY]
        if morning.empty:
            continue
        dipped = (morning['close'] < morning['vwap']).any()
        if not dipped:
            continue

        # At 11:00: close must be above VWAP (reclaimed)
        pre_entry = b[b.index.time <= ENTRY_TIME]
        if pre_entry.empty:
            continue
        last = pre_entry.iloc[-1]
        if last['close'] <= last['vwap']:
            continue

        # SPY must be above VWAP at 11:00
        if not spy_bull(pre_entry.index[-1]):
            continue

        px_entry   = float(last['close'])
        morning_lod = float(pre_entry['low'].min())
        atr = compute_atr(pre_entry)
        if atr <= 0:
            continue

        stop_px   = morning_lod - 0.1 * atr
        stop_dist = abs(px_entry - stop_px)
        if stop_dist <= 0 or px_entry <= stop_px:
            continue
        shares    = max(1, int(RISK_PER_TRADE / stop_dist))
        target_px = px_entry + TARGET_R * stop_dist

        bars_after = b[
            (b.index.time > ENTRY_TIME) &
            (b.index.time <= EXIT_TIME)
        ]
        exit_px = px_entry
        reason  = 'TIME_STOP'
        for _, row in bars_after.iterrows():
            if float(row['low']) <= stop_px:
                exit_px = stop_px; reason = 'STOP_HIT'; break
            if float(row['high']) >= target_px:
                exit_px = target_px; reason = 'TARGET_HIT'; break
            exit_px = float(row['close'])

        net = (exit_px - px_entry) * shares - shares * 0.01 * 2
        trades.append(dict(
            ticker     = ticker,
            day        = day,
            year       = str(day.year),
            entry_px   = round(px_entry, 2),
            stop_pct   = round(stop_dist / px_entry * 100, 2),
            exit_reason= reason,
            net_pnl    = net,
            shares     = shares,
            win        = net > 0,
        ))

if not trades:
    print("\nNo trades found.")
    sys.exit(0)

df = pd.DataFrame(trades)
pnl = df['net_pnl'].sum()
wr  = df['win'].mean()
avg = df['net_pnl'].mean()

print(f"\n{'='*60}")
print(f"  VWAP RECLAIM LONG SIM")
print(f"{'='*60}")
print(f"  {len(df)}t  P&L=${pnl:+,.0f}  WR={wr:.0%}  avg=${avg:+.1f}")

print(f"\n  By year:")
for yr in ['2020', '2021', '2022']:
    s = df[df['year'] == yr]
    if not len(s): continue
    p = s['net_pnl'].sum(); w = s['win'].mean()
    print(f"    {yr}: {len(s):3d}t  ${p:+7,.0f}  WR={w:.0%}  avg=${p/len(s):+.1f}")

print(f"\n  By exit reason:")
for ex in ['TARGET_HIT', 'STOP_HIT', 'TIME_STOP']:
    s = df[df['exit_reason'] == ex]
    if not len(s): continue
    p = s['net_pnl'].sum(); w = s['win'].mean()
    print(f"    {ex:<14}: {len(s):3d}t  ${p:+7,.0f}  WR={w:.0%}")

print(f"\n  Top tickers:")
tk_grp = df.groupby('ticker')['net_pnl'].agg(n='count', total='sum').sort_values('total', ascending=False)
for ticker, row in tk_grp.head(10).iterrows():
    s = df[df['ticker'] == ticker]; w = s['win'].mean()
    print(f"    {ticker:<6}: {int(row['n']):2d}t  ${row['total']:+7,.0f}  WR={w:.0%}")

# Bootstrap
outcomes = df['net_pnl'].values
rng = np.random.default_rng(42)
boot = np.array([rng.choice(outcomes, size=len(outcomes), replace=True).sum()
                 for _ in range(10_000)])
p_val = (boot <= 0).mean()
ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
print(f"\n  Bootstrap: p={p_val:.3f}  CI=[${ci_lo:+,.0f}, ${ci_hi:+,.0f}]  "
      f"{'✓ significant' if p_val < 0.05 else '✗ NOT significant'}")
