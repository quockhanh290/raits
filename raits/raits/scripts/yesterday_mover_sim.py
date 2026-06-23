"""
yesterday_mover_sim.py — Yesterday's Large Mover: momentum vs reversal

Trigger: |yesterday_intraday_return| > THRESHOLD (default 2.5%)
  - yesterday_ret = (yesterday_close - yesterday_open) / yesterday_open

At 10:15:
  - Yesterday UP + today price > yesterday_close  → MOMENTUM LONG
  - Yesterday UP + today price < yesterday_close  → REVERSAL SHORT
  - Yesterday DOWN + today price < yesterday_close → MOMENTUM SHORT
  - Yesterday DOWN + today price > yesterday_close → REVERSAL LONG

Stop  : LONG = morning_LOD - 0.1xATR | SHORT = morning_HOD + 0.1xATR
Target: 2R
Exit  : 14:00 time stop
Risk  : fixed $500/trade (sim convention)

Results broken down by regime, direction type, year.

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\yesterday_mover_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

THRESHOLD      = 0.025   # 2.5% intraday yesterday
ENTRY_TIME     = dtime(10, 15)
EXIT_TIME      = dtime(14, 0)
RISK_PER_TRADE = 500.0
TARGET_R       = 2.0

print("Loading data...")
with open(PKL_RESULTS, 'rb') as f: results = pickle.load(f)
with open(PKL_5MIN,    'rb') as f: data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# All trading days from engine results, with their HMM state
day_regime = {}
for w in results:
    for t in w.get('trades', []):
        day = pd.to_datetime(t.entry_time).normalize()
        if day not in day_regime:
            day_regime[day] = getattr(t, 'hmm_state', 'Unknown')

all_days = sorted(day_regime.keys())
print(f"Total trading days: {len(all_days)}")

EXCLUDE = {'SPY', 'QQQ', 'IWM'}
available_tickers = [tk for tk in data_5min if tk not in EXCLUDE]


def compute_atr(bars, period=14):
    if len(bars) < 2:
        return float(bars['close'].iloc[-1]) * 0.015
    hl  = bars['high'] - bars['low']
    hpc = (bars['high'] - bars['close'].shift(1)).abs()
    lpc = (bars['low']  - bars['close'].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())


# Precompute daily open/close per ticker
print("Building daily OHLC map...")
daily_oc = {}   # (ticker, date) -> (open, close)
for ticker in available_tickers:
    if ticker not in data_5min:
        continue
    bars = data_5min[ticker].sort_index()
    bars['date'] = bars.index.normalize()
    opens  = bars.groupby('date')['open'].first()
    closes = bars.groupby('date')['close'].last()
    for d in opens.index:
        daily_oc[(ticker, d)] = (float(opens[d]), float(closes[d]))

# Cache intraday bars
print("Caching day bars...")
day_bars_cache = {}
for day in all_days:
    for ticker in available_tickers:
        if ticker not in data_5min:
            continue
        db = data_5min[ticker][data_5min[ticker].index.normalize() == day].sort_index()
        if len(db) >= 6:
            day_bars_cache[(ticker, day)] = db


def simulate_one(ticker, day, day_bars):
    # Yesterday's intraday return
    yesterday = day - pd.Timedelta(days=1)
    while (ticker, yesterday) not in daily_oc and yesterday > day - pd.Timedelta(days=7):
        yesterday -= pd.Timedelta(days=1)
    oc = daily_oc.get((ticker, yesterday))
    if oc is None:
        return None
    prev_open, prev_close = oc
    if prev_open <= 0:
        return None
    yesterday_ret = (prev_close - prev_open) / prev_open
    if abs(yesterday_ret) < THRESHOLD:
        return None

    # Today at 10:15
    pre_entry = day_bars[day_bars.index.time <= ENTRY_TIME]
    if len(pre_entry) < 3:
        return None
    px_entry = float(pre_entry.iloc[-1]['close'])

    # Direction logic
    yesterday_up = yesterday_ret > 0
    price_above_prev_close = px_entry > prev_close

    if yesterday_up and price_above_prev_close:
        direction = 'LONG'; sig_type = 'MOMENTUM'
    elif yesterday_up and not price_above_prev_close:
        direction = 'SHORT'; sig_type = 'REVERSAL'
    elif not yesterday_up and not price_above_prev_close:
        direction = 'SHORT'; sig_type = 'MOMENTUM'
    else:
        direction = 'LONG'; sig_type = 'REVERSAL'

    morning_lod = float(pre_entry['low'].min())
    morning_hod = float(pre_entry['high'].max())
    atr = compute_atr(pre_entry)
    if atr <= 0:
        return None

    if direction == 'LONG':
        stop_px   = morning_lod - 0.1 * atr
        stop_dist = abs(px_entry - stop_px)
        if stop_dist <= 0 or px_entry <= stop_px:
            return None
        target_px = px_entry + TARGET_R * stop_dist
    else:
        stop_px   = morning_hod + 0.1 * atr
        stop_dist = abs(stop_px - px_entry)
        if stop_dist <= 0 or px_entry >= stop_px:
            return None
        target_px = px_entry - TARGET_R * stop_dist

    shares = max(1, int(RISK_PER_TRADE / stop_dist))

    bars_after = day_bars[
        (day_bars.index.time > ENTRY_TIME) &
        (day_bars.index.time <= EXIT_TIME)
    ]
    exit_px = px_entry
    reason  = 'TIME_STOP'
    for _, b in bars_after.iterrows():
        if direction == 'LONG':
            if float(b['low']) <= stop_px:
                exit_px = stop_px; reason = 'STOP_HIT'; break
            if float(b['high']) >= target_px:
                exit_px = target_px; reason = 'TARGET_HIT'; break
        else:
            if float(b['high']) >= stop_px:
                exit_px = stop_px; reason = 'STOP_HIT'; break
            if float(b['low']) <= target_px:
                exit_px = target_px; reason = 'TARGET_HIT'; break
        exit_px = float(b['close'])

    if direction == 'LONG':
        raw_pnl = (exit_px - px_entry) * shares
    else:
        raw_pnl = (px_entry - exit_px) * shares
    net = raw_pnl - shares * 0.01 * 2

    return dict(
        ticker     = ticker,
        day        = day,
        year       = str(day.year),
        regime     = day_regime.get(day, 'Unknown'),
        sig_type   = sig_type,
        direction  = direction,
        yesterday_ret = round(yesterday_ret * 100, 2),
        entry_px   = round(px_entry, 2),
        stop_pct   = round(stop_dist / px_entry * 100, 2),
        exit_reason= reason,
        net_pnl    = net,
        shares     = shares,
        win        = net > 0,
    )


print("Running sim...")
trades = []
for day in all_days:
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
total_pnl = df['net_pnl'].sum()
total_wr  = df['win'].mean()

print(f"\n{'='*70}")
print(f"  YESTERDAY MOVER SIM — threshold={THRESHOLD*100:.1f}%  target={TARGET_R}R  entry=10:15  exit=14:00")
print(f"{'='*70}")
print(f"  TOTAL: {len(df)}t  ${total_pnl:+,.0f}  WR={total_wr:.0%}  avg=${total_pnl/len(df):+.1f}")

# By signal type
print(f"\n  By signal type:")
for st in ['MOMENTUM', 'REVERSAL']:
    s = df[df['sig_type'] == st]
    if len(s) == 0: continue
    p = s['net_pnl'].sum()
    w = s['win'].mean()
    print(f"    {st:<10}: {len(s):4d}t  ${p:+8,.0f}  WR={w:.0%}  avg=${p/len(s):+.1f}")

# By direction + type
print(f"\n  By direction:")
for combo in [('MOMENTUM','LONG'),('MOMENTUM','SHORT'),('REVERSAL','LONG'),('REVERSAL','SHORT')]:
    st, di = combo
    s = df[(df['sig_type']==st) & (df['direction']==di)]
    if len(s) == 0: continue
    p = s['net_pnl'].sum()
    w = s['win'].mean()
    print(f"    {st} {di:<6}: {len(s):4d}t  ${p:+8,.0f}  WR={w:.0%}")

# By regime
print(f"\n  By regime:")
for reg in ['Calm','Normal','Stress','Crisis','Unknown']:
    for st in ['MOMENTUM','REVERSAL']:
        s = df[(df['regime']==reg) & (df['sig_type']==st)]
        if len(s) == 0: continue
        p = s['net_pnl'].sum()
        w = s['win'].mean()
        print(f"    {reg:<8} {st:<10}: {len(s):4d}t  ${p:+8,.0f}  WR={w:.0%}")

# By year
print(f"\n  By year:")
for yr in ['2020','2021','2022']:
    for st in ['MOMENTUM','REVERSAL']:
        s = df[(df['year']==yr) & (df['sig_type']==st)]
        if len(s) == 0: continue
        p = s['net_pnl'].sum()
        w = s['win'].mean()
        print(f"    {yr} {st:<10}: {len(s):4d}t  ${p:+8,.0f}  WR={w:.0%}")

# By exit reason
print(f"\n  By exit reason (MOMENTUM):")
for ex in ['TARGET_HIT','STOP_HIT','TIME_STOP']:
    s = df[(df['sig_type']=='MOMENTUM') & (df['exit_reason']==ex)]
    if len(s) == 0: continue
    p = s['net_pnl'].sum()
    w = s['win'].mean()
    print(f"    {ex:<14}: {len(s):4d}t  ${p:+8,.0f}  WR={w:.0%}")

print(f"\n  By exit reason (REVERSAL):")
for ex in ['TARGET_HIT','STOP_HIT','TIME_STOP']:
    s = df[(df['sig_type']=='REVERSAL') & (df['exit_reason']==ex)]
    if len(s) == 0: continue
    p = s['net_pnl'].sum()
    w = s['win'].mean()
    print(f"    {ex:<14}: {len(s):4d}t  ${p:+8,.0f}  WR={w:.0%}")

# Top/bottom tickers for best signal type
best = 'MOMENTUM' if df[df['sig_type']=='MOMENTUM']['net_pnl'].sum() > df[df['sig_type']=='REVERSAL']['net_pnl'].sum() else 'REVERSAL'
print(f"\n  Top tickers ({best}):")
tk_grp = df[df['sig_type']==best].groupby('ticker')['net_pnl'].agg(n='count', total='sum').sort_values('total', ascending=False)
for ticker, row in tk_grp.head(8).iterrows():
    s = df[(df['sig_type']==best) & (df['ticker']==ticker)]
    w = s['win'].mean()
    print(f"    {ticker:<6}: {int(row['n']):3d}t  ${row['total']:+8,.0f}  WR={w:.0%}")

# Yesterday return bucket
print(f"\n  By |yesterday_ret| bucket (MOMENTUM):")
df['ret_bucket'] = pd.cut(df['yesterday_ret'].abs(), bins=[2.5,3.5,5.0,10.0,100.0],
                          labels=['2.5-3.5%','3.5-5%','5-10%','>10%'])
for bucket, s in df[df['sig_type']=='MOMENTUM'].groupby('ret_bucket', observed=True):
    if len(s) == 0: continue
    p = s['net_pnl'].sum()
    w = s['win'].mean()
    print(f"    {str(bucket):<12}: {len(s):4d}t  ${p:+8,.0f}  WR={w:.0%}")
