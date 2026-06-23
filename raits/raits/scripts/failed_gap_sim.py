"""
failed_gap_sim.py — Failed Gap Short

Trigger: stock gaps UP 1.5-3% from prev_close
  + at 10:30, price < session_open (gap failed — gave back open)
  + SPY below VWAP at 10:30 (weak market confirms)

Trade: SHORT
  Entry  : 10:30 close
  Stop   : morning HOD + 0.1xATR
  Target : prev_close (full gap fill)
  Exit   : 13:30 time stop
  Regime : Normal only
  Risk   : fixed $500/trade (sim convention)

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\failed_gap_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

GAP_MIN        = 0.015
GAP_MAX        = 0.030
ENTRY_TIME     = dtime(10, 30)
EXIT_TIME      = dtime(13, 30)
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

# SPY VWAP — need BELOW vwap (opposite of GAP_FILL)
spy = data_5min['SPY'].sort_index().copy()
spy['tp']      = (spy['high'] + spy['low'] + spy['close']) / 3
spy['tpv']     = spy['tp'] * spy['volume']
spy['date']    = spy.index.normalize()
spy['cum_tpv'] = spy.groupby('date')['tpv'].cumsum()
spy['cum_vol'] = spy.groupby('date')['volume'].cumsum()
spy['vwap']    = spy['cum_tpv'] / spy['cum_vol']
spy['below']   = spy['close'] < spy['vwap']
_spy_dict = spy['below'].reindex(
    pd.date_range(spy.index[0], spy.index[-1], freq='5min'), method='ffill'
).to_dict()
def spy_bear(ts): return _spy_dict.get(ts.floor('5min'), None)


def compute_atr(bars, period=14):
    if len(bars) < 2:
        return float(bars['close'].iloc[-1]) * 0.015
    hl  = bars['high'] - bars['low']
    hpc = (bars['high'] - bars['close'].shift(1)).abs()
    lpc = (bars['low']  - bars['close'].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())


# Prev close map
print("Precomputing prev close map...")
prev_close_map = {}
for ticker in available_tickers:
    if ticker not in data_5min:
        continue
    bars = data_5min[ticker].sort_index()
    bars['date'] = bars.index.normalize()
    daily_last = bars.groupby('date')['close'].last()
    dates = daily_last.index.tolist()
    for i in range(1, len(dates)):
        prev_close_map[(ticker, dates[i])] = float(daily_last.iloc[i - 1])

# Cache day bars
print("Caching day bars...")
day_bars_cache = {}
for day in normal_days:
    for ticker in available_tickers:
        if ticker not in data_5min:
            continue
        db = data_5min[ticker][data_5min[ticker].index.normalize() == day].sort_index()
        if len(db) >= 8:
            day_bars_cache[(ticker, day)] = db


def simulate_one(ticker, day, day_bars):
    prev_c = prev_close_map.get((ticker, day))
    if prev_c is None or prev_c <= 0:
        return None

    first_bar = day_bars[day_bars.index.time >= dtime(9, 30)]
    if first_bar.empty:
        return None
    session_open = float(first_bar.iloc[0]['open'])
    gap_pct = (session_open - prev_c) / prev_c

    # Gap UP 1.5-3%
    if gap_pct <= 0 or gap_pct < GAP_MIN or gap_pct > GAP_MAX:
        return None

    pre_entry = day_bars[day_bars.index.time <= ENTRY_TIME]
    if pre_entry.empty:
        return None
    px_entry = float(pre_entry.iloc[-1]['close'])

    # Failed: price gave back the gap — now below session open
    if px_entry >= session_open:
        return None

    # SPY below VWAP at entry
    if spy_bear(pre_entry.index[-1]) is False:
        return None

    morning_hod = float(pre_entry['high'].max())
    atr = compute_atr(pre_entry)
    if atr <= 0:
        return None

    stop_px   = morning_hod + 0.1 * atr
    stop_dist = abs(stop_px - px_entry)
    if stop_dist <= 0:
        return None
    shares    = max(1, int(RISK_PER_TRADE / stop_dist))
    target_px = prev_c  # full gap fill

    bars_after = day_bars[
        (day_bars.index.time > ENTRY_TIME) &
        (day_bars.index.time < EXIT_TIME)
    ]
    exit_px = px_entry
    reason  = 'TIME_STOP'
    for _, b in bars_after.iterrows():
        if float(b['high']) >= stop_px:
            exit_px = stop_px; reason = 'STOP_HIT'; break
        if float(b['low']) <= target_px:
            exit_px = target_px; reason = 'TARGET_HIT'; break
        exit_px = float(b['close'])

    net = (px_entry - exit_px) * shares - shares * 0.01 * 2
    return dict(
        ticker     = ticker,
        day        = day,
        year       = str(day.year),
        gap_pct    = round(gap_pct * 100, 2),
        entry_px   = round(px_entry, 2),
        stop_pct   = round(stop_dist / px_entry * 100, 2),
        exit_reason= reason,
        net_pnl    = net,
        shares     = shares,
        win        = net > 0,
    )


print("Running sim...")
trades = []
for day in normal_days:
    for ticker in available_tickers:
        db = day_bars_cache.get((ticker, day))
        if db is None:
            continue
        r = simulate_one(ticker, day, db)
        if r:
            trades.append(r)

if not trades:
    print("\nNo trades found.")
    sys.exit(0)

df = pd.DataFrame(trades)
pnl = df['net_pnl'].sum()
wr  = df['win'].mean()
avg = df['net_pnl'].mean()

print(f"\n{'='*60}")
print(f"  FAILED GAP SHORT SIM")
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

print(f"\n  By gap bucket:")
df['gap_bucket'] = pd.cut(df['gap_pct'], bins=[1.5, 2.0, 2.5, 3.0],
                          labels=['1.5-2.0%', '2.0-2.5%', '2.5-3.0%'])
for bucket, s in df.groupby('gap_bucket', observed=True):
    if not len(s): continue
    p = s['net_pnl'].sum(); w = s['win'].mean()
    print(f"    {str(bucket):<10}: {len(s):3d}t  ${p:+7,.0f}  WR={w:.0%}  avg=${p/len(s):+.1f}")

print(f"\n  Top tickers:")
tk_grp = df.groupby('ticker')['net_pnl'].agg(n='count', total='sum').sort_values('total', ascending=False)
for ticker, row in tk_grp.head(10).iterrows():
    s = df[df['ticker'] == ticker]; w = s['win'].mean()
    print(f"    {ticker:<6}: {int(row['n']):2d}t  ${row['total']:+7,.0f}  WR={w:.0%}")

# Bootstrap
outcomes = df['net_pnl'].values
N_BOOT = 10_000
rng = np.random.default_rng(42)
boot = np.array([rng.choice(outcomes, size=len(outcomes), replace=True).sum()
                 for _ in range(N_BOOT)])
p_val = (boot <= 0).mean()
ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
print(f"\n  Bootstrap (N={N_BOOT:,}): P(sum<=0)={p_val:.3f}  "
      f"CI=[${ci_lo:+,.0f}, ${ci_hi:+,.0f}]  "
      f"{'✓ significant' if p_val < 0.05 else '✗ NOT significant'}")
