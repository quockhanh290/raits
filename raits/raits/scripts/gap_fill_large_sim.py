"""
gap_fill_large_sim.py — Extended Gap Fill: gaps 3-5% (vs current engine 1.5-3%)

Same parameters as current GAP_FILL engine:
  - LONG only, gap DOWN 3-5% vs prev close
  - Retrace 50-85% by 10:30
  - SPY above VWAP at 10:30
  - Stop  = morning_lod - 0.1xATR
  - Target = prev_close + 50% gap
  - Trailing chandelier stop
  - Time exit 13:30
  - Normal regime only
  - Fixed $500 risk (sim convention)

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\gap_fill_large_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime
from collections import defaultdict

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

GAP_MIN        = 0.03    # 3% lower bound (exclusive of current 1.5-3% range)
GAP_MAX        = 0.05    # 5% upper bound
RETRACE_MIN    = 0.50
RETRACE_MAX    = 0.85
ENTRY_TIME     = dtime(10, 30)
EXIT_TIME      = dtime(13, 30)
RISK_PER_TRADE = 500.0

print("Loading data...")
with open(PKL_RESULTS, 'rb') as f: results = pickle.load(f)
with open(PKL_5MIN,    'rb') as f: data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# Normal regime days from engine results
normal_days = set()
for w in results:
    for t in w.get('trades', []):
        if getattr(t, 'hmm_state', None) == 'Normal':
            normal_days.add(pd.to_datetime(t.entry_time).normalize())
normal_days = sorted(normal_days)
print(f"Normal days: {len(normal_days)}")

available_tickers = [tk for tk in data_5min if tk != 'SPY']

# SPY VWAP lookup
spy = data_5min['SPY'].sort_index().copy()
spy['tp']      = (spy['high'] + spy['low'] + spy['close']) / 3
spy['tpv']     = spy['tp'] * spy['volume']
spy['date']    = spy.index.normalize()
spy['cum_tpv'] = spy.groupby('date')['tpv'].cumsum()
spy['cum_vol'] = spy.groupby('date')['volume'].cumsum()
spy['vwap']    = spy['cum_tpv'] / spy['cum_vol']
spy['above']   = spy['close'] > spy['vwap']
_spy_dict = spy['above'].reindex(
    pd.date_range(spy.index[0], spy.index[-1], freq='5min'), method='ffill'
).to_dict()
def spy_bull(ts): return _spy_dict.get(ts.floor('5min'), None)


def compute_atr(bars, period=14):
    if len(bars) < 2:
        return float(bars['close'].iloc[-1]) * 0.015
    hl  = bars['high'] - bars['low']
    hpc = (bars['high'] - bars['close'].shift(1)).abs()
    lpc = (bars['low']  - bars['close'].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())


# Precompute prev_close
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

# Cache intraday bars per Normal day
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
    gap_pct  = (session_open - prev_c) / prev_c
    gap_size = session_open - prev_c  # negative = gap down

    if gap_pct >= 0 or abs(gap_pct) < GAP_MIN or abs(gap_pct) > GAP_MAX:
        return None

    pre_entry = day_bars[day_bars.index.time <= ENTRY_TIME]
    if pre_entry.empty:
        return None
    px_entry = float(pre_entry.iloc[-1]['close'])

    retrace = (session_open - px_entry) / gap_size if gap_size != 0 else 0
    if not (RETRACE_MIN <= retrace <= RETRACE_MAX):
        return None

    if spy_bull(pre_entry.index[-1]) is False:
        return None

    morning_lod = float(pre_entry['low'].min())
    atr = compute_atr(pre_entry)
    if atr <= 0:
        return None

    stop_px   = morning_lod - 0.1 * atr
    stop_dist = abs(px_entry - stop_px)
    if stop_dist <= 0:
        return None
    shares    = max(1, int(RISK_PER_TRADE / stop_dist))
    target_px = prev_c + 0.50 * abs(gap_size)

    bars_after = day_bars[
        (day_bars.index.time > ENTRY_TIME) &
        (day_bars.index.time < EXIT_TIME)
    ]
    trailing  = stop_px
    exit_px   = px_entry
    reason    = 'TIME_STOP'
    for _, b in bars_after.iterrows():
        trailing = max(trailing, float(b['high']) - stop_dist)
        if float(b['low']) <= trailing:
            exit_px = trailing; reason = 'STOP_HIT'; break
        if float(b['high']) >= target_px:
            exit_px = target_px; reason = 'TARGET_HIT'; break
        exit_px = float(b['close'])

    net = (exit_px - px_entry) * shares - shares * 0.01 * 2
    return dict(
        ticker     = ticker,
        day        = day,
        year       = str(day.year),
        gap_pct    = round(abs(gap_pct) * 100, 2),
        retrace    = round(retrace, 2),
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

# Baseline engine GAP_FILL for comparison
baseline = [t for w in results for t in w.get('trades', []) if t.strategy == 'GAP_FILL']
baseline_pnl = sum(t.net_pnl for t in baseline)
baseline_n   = len(baseline)

print(f"\n{'='*65}")
print(f"  GAP FILL LARGE (3-5%) — SIMULATION RESULTS")
print(f"{'='*65}")
print(f"  Baseline GAP_FILL (1.5-3%): {baseline_n}t  ${baseline_pnl:+,.0f}  WR={sum(1 for t in baseline if t.net_pnl>0)/baseline_n:.0%}")

if not trades:
    print("\n  No trades found in 3-5% range.")
else:
    df = pd.DataFrame(trades)
    pnl = df['net_pnl'].sum()
    wr  = df['win'].mean()
    avg = df['net_pnl'].mean()

    print(f"  This sim  (3-5%):          {len(df)}t  ${pnl:+,.0f}  WR={wr:.0%}  avg=${avg:+.1f}")
    print(f"  Combined estimate:          ${baseline_pnl + pnl:+,.0f}")

    print(f"\n  By year:")
    for yr in ['2020', '2021', '2022']:
        s = df[df['year'] == yr]
        if len(s):
            p = s['net_pnl'].sum()
            w = s['win'].mean()
            print(f"    {yr}: {len(s):3d}t  ${p:+7,.0f}  WR={w:.0%}  avg=${p/len(s):+.1f}")

    print(f"\n  By exit reason:")
    for ex in sorted(df['exit_reason'].unique()):
        s = df[df['exit_reason'] == ex]
        p = s['net_pnl'].sum()
        w = s['win'].mean()
        print(f"    {ex:<14}: {len(s):3d}t  ${p:+7,.0f}  WR={w:.0%}")

    print(f"\n  By gap bucket:")
    bins   = [3.0, 3.5, 4.0, 4.5, 5.0]
    labels = ['3.0-3.5%', '3.5-4.0%', '4.0-4.5%', '4.5-5.0%']
    df['gap_bucket'] = pd.cut(df['gap_pct'], bins=bins, labels=labels)
    for bucket, s in df.groupby('gap_bucket', observed=True):
        if len(s) == 0:
            continue
        p = s['net_pnl'].sum()
        w = s['win'].mean()
        print(f"    {str(bucket):<12}: {len(s):3d}t  ${p:+7,.0f}  WR={w:.0%}  avg=${p/len(s):+.1f}")

    print(f"\n  By ticker (top 10):")
    tk_grp = df.groupby('ticker')['net_pnl'].agg(n='count', total='sum').sort_values('total', ascending=False)
    for ticker, row in tk_grp.head(10).iterrows():
        s = df[df['ticker'] == ticker]
        w = s['win'].mean()
        print(f"    {ticker:<6}: {int(row['n']):2d}t  ${row['total']:+7,.0f}  WR={w:.0%}")

    # Conflict check: same day+ticker as existing GAP_FILL
    baseline_keys = {(t.entry_time.date(), t.ticker) for t in baseline}
    conflicts = [r for r in trades if (r['day'], r['ticker']) in baseline_keys]
    if conflicts:
        print(f"\n  NOTE: {len(conflicts)} trades overlap same day+ticker with baseline GAP_FILL")
        print(f"  (engine would skip — already in position)")
