"""
gap_up_fail_detail.py — Show individual trade breakdown for best config
gap≥3%, fail@10:15, All regimes — focus on STOP_HIT vs TARGET_HIT
"""
import sys, os, pickle, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS    = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
PKL_5MIN       = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
EARNINGS_CACHE = r'd:\raits\raits\data\cache\earnings_dates_expanded.json'

PE_UNIVERSE = [
    "AAPL","MSFT","AMZN","GOOGL","META","NVDA","TSLA","AMD",
    "QCOM","INTC","MU","AVGO","TXN","AMAT","ADBE","CRM","ORCL","INTU","CSCO",
    "AMGN","GILD","BIIB","REGN","VRTX","COST","SBUX","NFLX","EBAY",
    "JPM","GS","MS","V","MA","HON","MMM","XOM","CVX",
    "GE","PANW","NOW","PYPL",
]

RISK_PER_TRADE = 500.0
ATR_PERIOD     = 14
STOP_BUFFER    = 0.005
BACKTEST_START = pd.Timestamp("2020-01-01")
BACKTEST_END   = pd.Timestamp("2022-12-31")
GAP_THR        = 0.03
FAIL_TIME      = dtime(10, 15)

with open(PKL_RESULTS, 'rb') as f: results = pickle.load(f)
with open(PKL_5MIN, 'rb') as f:    data_5min = pickle.load(f)
for tk in data_5min: data_5min[tk].index = pd.to_datetime(data_5min[tk].index)
with open(EARNINGS_CACHE) as f: raw_calendar = json.load(f)

earnings_by_date = {}
for tk, dates in raw_calendar.items():
    if tk not in PE_UNIVERSE: continue
    for d in dates:
        ts = pd.Timestamp(d)
        if BACKTEST_START <= ts <= BACKTEST_END:
            earnings_by_date.setdefault(ts, []).append(tk)

all_days = set()
for w in results:
    for t in w.get('trades', []):
        all_days.add(pd.to_datetime(t.entry_time).normalize())

def compute_atr(bars, period=ATR_PERIOD):
    if len(bars) < 2:
        return float(bars['close'].iloc[-1]) * 0.015 if not bars.empty else 0.01
    hl  = bars['high'] - bars['low']
    hpc = (bars['high'] - bars['close'].shift(1)).abs()
    lpc = (bars['low']  - bars['close'].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

trades = []
for day, tickers in sorted(earnings_by_date.items()):
    if day not in all_days: continue
    for ticker in tickers:
        if ticker not in data_5min: continue
        bars = data_5min[ticker]
        day_bars = bars[bars.index.normalize() == day].sort_index()
        if len(day_bars) < 6: continue
        prev_bars = bars[bars.index.normalize() < day].sort_index()
        if prev_bars.empty: continue
        prior_close = float(prev_bars.iloc[-1]['close'])
        if prior_close <= 0: continue
        b930 = day_bars[day_bars.index.time == dtime(9, 30)]
        if b930.empty: continue
        open_px = float(b930.iloc[0]['open'])
        if open_px / prior_close - 1 < GAP_THR: continue

        b_fail = day_bars[day_bars.index.time == FAIL_TIME]
        if b_fail.empty: continue
        fail_close = float(b_fail.iloc[0]['close'])
        if fail_close > open_px: continue

        entry_px  = fail_close
        entry_ts  = b_fail.index[0]
        atr       = compute_atr(day_bars[day_bars.index <= entry_ts])
        if atr <= 0: continue
        stop_px   = open_px * (1 + STOP_BUFFER)
        stop_dist = stop_px - entry_px
        if stop_dist <= 0: continue
        target_px = max(prior_close, entry_px - 2.0 * stop_dist)
        shares    = max(1, int(RISK_PER_TRADE / stop_dist))

        bars_after = day_bars[(day_bars.index > entry_ts) & (day_bars.index.time <= dtime(15, 55))]
        exit_px = entry_px; reason = 'TIME_STOP'
        for _, b in bars_after.iterrows():
            if float(b['high']) >= stop_px:
                exit_px = stop_px; reason = 'STOP_HIT'; break
            if float(b['low']) <= target_px:
                exit_px = target_px; reason = 'TARGET_HIT'; break
            exit_px = float(b['close'])

        net = (entry_px - exit_px) * shares - shares * 0.01 * 2
        gap_pct = (open_px / prior_close - 1) * 100
        fail_drop = (fail_close / open_px - 1) * 100  # how much below open at 10:15

        trades.append(dict(
            ticker=ticker, day=day, year=str(day.year),
            prior_close=round(prior_close,2), open_px=round(open_px,2),
            gap_pct=round(gap_pct,1), fail_close=round(fail_close,2),
            fail_drop=round(fail_drop,1), entry_px=round(entry_px,2),
            stop_px=round(stop_px,2), target_px=round(target_px,2),
            stop_dist=round(stop_dist,2), shares=shares,
            exit_px=round(exit_px,2), reason=reason, net_pnl=round(net,0),
            win=net>0,
        ))

df = pd.DataFrame(trades).sort_values('day')

print(f"\n{'='*90}")
print(f"  ALL 21 TRADES — gap≥3% fail@10:15 (All regimes)")
print(f"{'='*90}")
print(f"  {'Date':<12} {'Tkr':<6} {'Gap':>5} {'Fail@10:15':>10} {'Entry':>7} {'Stop':>7} {'Tgt':>7} {'Exit':>7} {'N':>3} {'P&L':>7}  Exit")
print(f"  {'-'*88}")

for _, r in df.iterrows():
    flag = ' ← STOP' if r['reason'] == 'STOP_HIT' else (' ✓ TGT' if r['reason'] == 'TARGET_HIT' else '')
    print(f"  {str(r['day'].date()):<12} {r['ticker']:<6} {r['gap_pct']:>4.1f}% {r['fail_drop']:>+9.1f}% "
          f"${r['entry_px']:>6.1f} ${r['stop_px']:>6.1f} ${r['target_px']:>6.1f} "
          f"${r['exit_px']:>6.1f} {r['shares']:>3} ${r['net_pnl']:>6.0f}{flag}")

print(f"\n{'='*90}")
print(f"  STOP_HIT trades detail (why SHORT failed)")
print(f"{'='*90}")
stops = df[df['reason'] == 'STOP_HIT']
print(f"  {len(stops)} stops  Total: ${stops['net_pnl'].sum():+,.0f}")
print()
for _, r in stops.iterrows():
    print(f"  {str(r['day'].date())} {r['ticker']}: gap={r['gap_pct']:.1f}% fail_drop={r['fail_drop']:.1f}%")
    print(f"    Entry=${r['entry_px']:.2f}  Stop=${r['stop_px']:.2f} (+{r['stop_dist']:.2f})  Target=${r['target_px']:.2f}")
    print(f"    → stock continued UP through ${r['stop_px']:.2f}  Loss=${r['net_pnl']:+.0f}")
    # show what happened intraday after entry
    brs = data_5min[r['ticker']]
    day_brs = brs[brs.index.normalize() == r['day']].sort_index()
    post = day_brs[day_brs.index.time > FAIL_TIME]
    if not post.empty:
        hi = post['high'].max(); lo = post['low'].min(); last = float(post.iloc[-1]['close'])
        vs_prior = (last / r['prior_close'] - 1) * 100
        print(f"    Post-entry range: low=${lo:.2f}  high=${hi:.2f}  EOD close=${last:.2f} ({vs_prior:+.1f}% vs prior close)")
    print()

print(f"  TARGET_HIT: {len(df[df['reason']=='TARGET_HIT'])}t  ${df[df['reason']=='TARGET_HIT']['net_pnl'].sum():+,.0f}  WR=100%")
print(f"  TIME_STOP:  {len(df[df['reason']=='TIME_STOP'])}t   ${df[df['reason']=='TIME_STOP']['net_pnl'].sum():+,.0f}  WR={df[df['reason']=='TIME_STOP']['win'].mean():.0%}")
print(f"  STOP_HIT:   {len(df[df['reason']=='STOP_HIT'])}t   ${df[df['reason']=='STOP_HIT']['net_pnl'].sum():+,.0f}  WR=0%")
print()
