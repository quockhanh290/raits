"""
midday_continuation_sim.py — Midday Momentum Continuation LONG

Signal: stock ≥THRESHOLD% from 9:30 open by 10:30, SPY positive
Entry:  10:30 bar open
Stop:   session LOD (9:30-10:25) - 0.5×ATR14
Target: 2R | Time stop: 14:00 ET open
Regime: Normal only | MAX_SLOTS=3 (top by momentum %)
Risk:   $500/trade

Threshold grid: 1.0%, 1.5%, 2.0%, 2.5%, 3.0%

Usage:
    cd d:\\raits\\raits
    py -3.11 raits\\scripts\\midday_continuation_sim.py
"""

import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260623_070518.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

THRESHOLD_GRID = [0.010, 0.015, 0.020, 0.025, 0.030]
MAX_SLOTS      = 3
STOP_ATR_MULT  = 0.5
TARGET_RR      = 2.0
RISK_PER_TRADE = 500.0
N_BOOT         = 2000
BACKTEST_START = pd.Timestamp("2020-01-01")
BACKTEST_END   = pd.Timestamp("2022-12-31")

# ── Load ───────────────────────────────────────────────────────────────────────
print("Loading data...")
with open(PKL_RESULTS, 'rb') as f: results = pickle.load(f)
with open(PKL_5MIN,    'rb') as f: data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# Normal days from engine snapshot
normal_days = set()
for w in results:
    for t in w.get('trades', []):
        d = pd.to_datetime(t.entry_time).normalize()
        if getattr(t, 'hmm_state', None) == 'Normal':
            normal_days.add(d)
normal_days = sorted(d for d in normal_days
                     if BACKTEST_START <= d <= BACKTEST_END)
print(f"Normal days: {len(normal_days)}")

spy_all = data_5min.get('SPY', pd.DataFrame())
tickers  = [tk for tk in data_5min if tk != 'SPY']

# ── Pre-compute ATR14 per ticker ───────────────────────────────────────────────
print("Pre-computing ATR14...")
ticker_atr: dict[str, pd.Series] = {}
for tk in tickers:
    bars = data_5min[tk]
    if bars.empty:
        continue
    daily = bars.resample('D').agg(
        high=('high', 'max'), low=('low', 'min'), close=('close', 'last')
    ).dropna()
    daily = daily[daily.index.normalize() >= pd.Timestamp("2019-01-01")]
    if len(daily) < 16:
        continue
    h = daily['high'].values
    l = daily['low'].values
    c = daily['close'].values
    tr = np.maximum(h[1:] - l[1:],
         np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    idx = daily.index[1:]
    ticker_atr[tk] = pd.Series(tr, index=idx)

print(f"ATR ready for {len(ticker_atr)} tickers")

def get_atr(ticker: str, date: pd.Timestamp) -> float | None:
    if ticker not in ticker_atr:
        return None
    prior = ticker_atr[ticker][ticker_atr[ticker].index.normalize() < date]
    if len(prior) < 14:
        return None
    return float(prior.tail(14).mean())

# ── Per-day simulation ─────────────────────────────────────────────────────────
def sim_day(day: pd.Timestamp, threshold: float) -> list:
    # SPY check: must be positive by 10:30
    spy_day = spy_all[spy_all.index.normalize() == day]
    if spy_day.empty:
        return []
    spy_930 = spy_day[spy_day.index.time == dtime(9, 30)]
    spy_ref  = spy_day[(spy_day.index.time >= dtime(10, 25)) &
                       (spy_day.index.time <= dtime(10, 30))]
    if spy_930.empty or spy_ref.empty:
        return []
    if float(spy_ref.iloc[-1]['close']) <= float(spy_930.iloc[0]['open']):
        return []

    candidates = []
    for tk in tickers:
        bars    = data_5min[tk]
        day_b   = bars[bars.index.normalize() == day]
        if len(day_b) < 5:
            continue

        b930 = day_b[day_b.index.time == dtime(9, 30)]
        b1030 = day_b[day_b.index.time == dtime(10, 30)]
        if b930.empty or b1030.empty:
            continue

        stock_open = float(b930.iloc[0]['open'])
        entry      = float(b1030.iloc[0]['open'])
        if stock_open <= 0 or entry <= 0:
            continue

        momentum = (entry - stock_open) / stock_open
        if momentum < threshold:
            continue

        atr = get_atr(tk, day)
        if not atr or atr <= 0:
            continue

        pre_bars = day_b[day_b.index.time < dtime(10, 30)]
        if pre_bars.empty:
            continue
        lod = float(pre_bars['low'].min())

        stop      = lod - STOP_ATR_MULT * atr
        stop_dist = entry - stop
        if stop_dist <= 0 or stop_dist / entry > 0.06:
            continue

        shares = int(RISK_PER_TRADE / stop_dist)
        if shares < 1:
            continue

        candidates.append(dict(
            ticker=tk, momentum=momentum,
            entry=entry, stop=stop,
            target=entry + TARGET_RR * stop_dist,
            shares=shares, day_b=day_b,
        ))

    candidates.sort(key=lambda x: -x['momentum'])
    trades = []
    for c in candidates[:MAX_SLOTS]:
        trade_bars = c['day_b'][c['day_b'].index.time >= dtime(10, 30)]
        if trade_bars.empty:
            continue

        ep, er, et = None, None, None
        for ts, bar in trade_bars.iterrows():
            if ts.time() >= dtime(14, 0):
                ep, er, et = float(bar['open']), 'TIME_STOP', ts
                break
            if float(bar['low']) <= c['stop']:
                ep, er, et = c['stop'], 'STOP_HIT', ts
                break
            if float(bar['high']) >= c['target']:
                ep, er, et = c['target'], 'TARGET_HIT', ts
                break

        if ep is None:
            last = trade_bars.iloc[-1]
            ep, er, et = float(last['close']), 'TIME_STOP', last.name

        pnl = (ep - c['entry']) * c['shares']
        trades.append(dict(
            ticker=c['ticker'], date=day, year=day.year,
            entry=c['entry'], exit_price=ep, shares=c['shares'],
            net_pnl=pnl, exit_reason=er,
            momentum_pct=c['momentum'] * 100,
        ))
    return trades

# ── Grid run ───────────────────────────────────────────────────────────────────
print("\nRunning threshold grid...")
print(f"{'Thresh':>7} {'Trades':>7} {'WR%':>6} {'Avg$':>8} {'Total$':>9}"
      f" {'2020':>7} {'2021':>7} {'2022':>7}")
print('-' * 65)

all_results: dict[float, pd.DataFrame] = {}
for thr in THRESHOLD_GRID:
    rows = []
    for day in normal_days:
        rows.extend(sim_day(day, thr))
    if not rows:
        print(f"  {thr*100:.1f}%        0 trades")
        continue
    df = pd.DataFrame(rows)
    by_yr = df.groupby('year')['net_pnl'].sum()
    print(f"  {thr*100:.1f}%   {len(df):>7}"
          f" {(df.net_pnl>0).mean()*100:>6.1f}"
          f" {df.net_pnl.mean():>+8.1f}"
          f" {df.net_pnl.sum():>+9.0f}"
          f" {by_yr.get(2020,0):>+7.0f}"
          f" {by_yr.get(2021,0):>+7.0f}"
          f" {by_yr.get(2022,0):>+7.0f}")
    all_results[thr] = df

# ── Best threshold detail ──────────────────────────────────────────────────────
if not all_results:
    print("No trades found for any threshold.")
    sys.exit(0)

best_thr = max(all_results, key=lambda t: all_results[t]['net_pnl'].sum())
df = all_results[best_thr]

print(f"\n{'='*60}")
print(f"DETAILED — threshold={best_thr*100:.1f}%")
print(f"{'='*60}")
total = df.net_pnl.sum()
wr    = (df.net_pnl > 0).mean() * 100
print(f"  {len(df)}t  P&L=${total:+,.0f}  WR={wr:.1f}%  avg=${df.net_pnl.mean():+.1f}")

print("\n  By year:")
for yr, g in df.groupby('year'):
    print(f"  {yr}  {len(g):>4}t  WR={(g.net_pnl>0).mean()*100:.0f}%"
          f"  avg=${g.net_pnl.mean():+.1f}  ${g.net_pnl.sum():+,.0f}")

print("\n  By exit reason:")
for r, g in df.groupby('exit_reason'):
    print(f"  {r:<16} {len(g):>4}t  WR={(g.net_pnl>0).mean()*100:.0f}%"
          f"  avg=${g.net_pnl.mean():+.1f}  total=${g.net_pnl.sum():+,.0f}")

print("\n  Top 10 tickers:")
tk_s = df.groupby('ticker')['net_pnl'].sum().sort_values(ascending=False)
for tk, p in tk_s.head(10).items():
    cnt = len(df[df.ticker == tk])
    wr2 = (df[df.ticker == tk].net_pnl > 0).mean() * 100
    print(f"  {tk:<6} {cnt:>4}t  WR={wr2:.0f}%  ${p:+,.0f}")
print("  Bottom 5:")
for tk, p in tk_s.tail(5).items():
    cnt = len(df[df.ticker == tk])
    print(f"  {tk:<6} {cnt:>4}t  ${p:+,.0f}")

print(f"\n  Momentum stats: avg={df.momentum_pct.mean():.1f}%"
      f"  median={df.momentum_pct.median():.1f}%"
      f"  max={df.momentum_pct.max():.1f}%")

print(f"\n  Bootstrap ({N_BOOT} runs)...")
pnls = df['net_pnl'].values
boot = [np.random.choice(pnls, size=len(pnls), replace=True).sum()
        for _ in range(N_BOOT)]
ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
p_val = float(np.mean(np.array(boot) <= 0))
sig   = "✓ Significant" if p_val < 0.05 else "✗ NOT significant"
print(f"  p={p_val:.3f}  CI=[${ci_lo:+,.0f}, ${ci_hi:+,.0f}]  {sig}")
