"""
midday_continuation_sim_v2.py — Midday Momentum Continuation LONG (engine-grade filters)

Filters vs v1:
  1. DailyUniverseScanner (T-1): price>SMA50>SMA200 | ATH≥85% | RS>SPY | vol≥500k | ATR%≥1.5%
  2. ORB overlap: skip tickers with open ORB position at 10:30
  3. Circuit breaker: skip days where CB fired before 10:30

Signal: stock ≥THRESHOLD% from 9:30 open by 10:30, SPY positive
Entry:  10:30 bar open
Stop:   session LOD (9:30-10:25) - 0.5×ATR14
Target: 2R | Time stop: 14:00 ET
Regime: Normal only | MAX_SLOTS=3 (top by momentum %) | Risk $500/trade

Usage:
    cd d:\\raits\\raits
    py -3.11 raits\\scripts\\midday_continuation_sim_v2.py
"""

import sys, os, pickle, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
logging.disable(logging.CRITICAL)   # silence scanner debug/info logs
import warnings; warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from datetime import time as dtime

from raits.strategies.universe_scanner import DailyUniverseScanner

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
SCANNER_TOP_N  = 20   # broader than TF(15); momentum filter does final cut

# ── 1. Load ────────────────────────────────────────────────────────────────────
print("Loading data...")
with open(PKL_RESULTS, 'rb') as f: results = pickle.load(f)
with open(PKL_5MIN,    'rb') as f: data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# Normal days from engine snapshot
normal_days = sorted(
    d for w in results for t in w.get('trades', [])
    if getattr(t, 'hmm_state', None) == 'Normal'
    for d in [pd.to_datetime(t.entry_time).normalize()]
    if BACKTEST_START <= d <= BACKTEST_END
)
normal_days = sorted(set(normal_days))
print(f"Normal days: {len(normal_days)}")

spy_all = data_5min.get('SPY', pd.DataFrame())

# ── 2. Build daily_data from 5-min bars ───────────────────────────────────────
print("Building daily OHLCV from 5-min bars...")
daily_data: dict = {}
for tk, bars in data_5min.items():
    d = bars.resample('D').agg(
        open=('open', 'first'), high=('high', 'max'),
        low=('low', 'min'),   close=('close', 'last'),
        volume=('volume', 'sum'),
    ).dropna(subset=['close'])
    d = d[d['volume'] > 0]
    if not d.empty:
        daily_data[tk] = d

print(f"Daily data built for {len(daily_data)} tickers")

# ── 3. Pre-compute ATR14 series per ticker (from daily) ───────────────────────
print("Pre-computing ATR14...")
ticker_atr: dict = {}
for tk, daily in daily_data.items():
    if len(daily) < 16:
        continue
    h = daily['high'].values
    l = daily['low'].values
    c = daily['close'].values
    tr = np.maximum(h[1:] - l[1:],
         np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    idx = daily.index[1:]
    ticker_atr[tk] = pd.Series(tr, index=idx)

def get_atr(ticker: str, date: pd.Timestamp) -> float | None:
    if ticker not in ticker_atr:
        return None
    prior = ticker_atr[ticker][ticker_atr[ticker].index.normalize() < date]
    return float(prior.tail(14).mean()) if len(prior) >= 14 else None

# ── 4. Pre-extract engine state from snapshot ──────────────────────────────────
print("Extracting ORB overlap & circuit breaker state...")

# ORB positions open at 10:30: entered before 10:30, exited after 10:30
orb_open_at_1030: dict = {}   # date → set of tickers
cb_days: set = set()          # dates where CB fired before 10:30

for w in results:
    for t in w.get('trades', []):
        entry_ts = pd.Timestamp(t.entry_time)
        exit_ts  = pd.Timestamp(t.exit_time)
        day      = entry_ts.normalize()

        if t.strategy == 'ORB':
            if (entry_ts.time() < dtime(10, 30) and
                    exit_ts.time() > dtime(10, 30)):
                orb_open_at_1030.setdefault(day, set()).add(t.ticker)

        if (getattr(t, 'exit_reason', '') == 'CIRCUIT_BREAKER' and
                exit_ts.time() < dtime(10, 30)):
            cb_days.add(day)

orb_block_count = sum(len(v) for v in orb_open_at_1030.values())
print(f"  ORB open-at-10:30: {orb_block_count} ticker-days blocked")
print(f"  CB before 10:30:   {len(cb_days)} days blocked")

# ── 5. Pre-run scanner for all normal days ─────────────────────────────────────
print(f"Running DailyUniverseScanner (top_n={SCANNER_TOP_N}) for {len(normal_days)} days...")
scanner = DailyUniverseScanner(
    top_n=SCANNER_TOP_N,
    candidate_pool=list(data_5min.keys()),   # all cached tickers
)

day_universe: dict = {}   # date → set of tickers passing scanner
for i, day in enumerate(normal_days):
    t_minus_1 = day - pd.tseries.offsets.BDay(1)
    try:
        selected = scanner.scan(daily_data, t_minus_1)
        day_universe[day] = set(selected)
    except Exception:
        day_universe[day] = set()
    if (i + 1) % 50 == 0:
        print(f"  {i+1}/{len(normal_days)} days scanned...")

avg_universe = np.mean([len(v) for v in day_universe.values()])
print(f"  Avg scanner universe size: {avg_universe:.1f} tickers/day")

# ── 6. Per-day simulation ─────────────────────────────────────────────────────
def sim_day(day: pd.Timestamp, threshold: float) -> list:
    # Filter A: circuit breaker
    if day in cb_days:
        return []

    # Filter B: scanner universe for this day
    universe = day_universe.get(day, set())
    if not universe:
        return []

    # Filter C: ORB-blocked tickers
    orb_blocked = orb_open_at_1030.get(day, set())

    # SPY check: positive by 10:30
    spy_day = spy_all[spy_all.index.normalize() == day]
    if spy_day.empty:
        return []
    spy_930  = spy_day[spy_day.index.time == dtime(9, 30)]
    spy_ref  = spy_day[(spy_day.index.time >= dtime(10, 25)) &
                       (spy_day.index.time <= dtime(10, 30))]
    if spy_930.empty or spy_ref.empty:
        return []
    if float(spy_ref.iloc[-1]['close']) <= float(spy_930.iloc[0]['open']):
        return []

    candidates = []
    for tk in universe:
        # Filter D: ORB overlap
        if tk in orb_blocked:
            continue

        bars  = data_5min.get(tk)
        if bars is None:
            continue
        day_b = bars[bars.index.normalize() == day]
        if len(day_b) < 5:
            continue

        b930  = day_b[day_b.index.time == dtime(9, 30)]
        b1030 = day_b[day_b.index.time == dtime(10, 30)]
        if b930.empty or b1030.empty:
            continue

        stock_open = float(b930.iloc[0]['open'])
        entry      = float(b1030.iloc[0]['open'])
        if stock_open <= 0 or entry <= 0:
            continue

        # Filter E: momentum threshold
        momentum = (entry - stock_open) / stock_open
        if momentum < threshold:
            continue

        # ATR & stop
        atr = get_atr(tk, day)
        if not atr or atr <= 0:
            continue

        pre_bars  = day_b[day_b.index.time < dtime(10, 30)]
        if pre_bars.empty:
            continue
        lod       = float(pre_bars['low'].min())
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

        ep = er = et = None
        for ts, bar in trade_bars.iterrows():
            if ts.time() >= dtime(14, 0):
                ep, er, et = float(bar['open']), 'TIME_STOP', ts; break
            if float(bar['low']) <= c['stop']:
                ep, er, et = c['stop'], 'STOP_HIT', ts; break
            if float(bar['high']) >= c['target']:
                ep, er, et = c['target'], 'TARGET_HIT', ts; break

        if ep is None:
            last = trade_bars.iloc[-1]
            ep, er, et = float(last['close']), 'TIME_STOP', last.name

        trades.append(dict(
            ticker=c['ticker'], date=day, year=day.year,
            net_pnl=(ep - c['entry']) * c['shares'],
            exit_reason=er, momentum_pct=c['momentum'] * 100,
        ))
    return trades

# ── 7. Run grid ────────────────────────────────────────────────────────────────
print("\nRunning threshold grid...")
print(f"{'Thresh':>7} {'Trades':>7} {'WR%':>6} {'Avg$':>8} {'Total$':>9}"
      f" {'2020':>7} {'2021':>7} {'2022':>7}")
print('-' * 65)

all_results: dict = {}
for thr in THRESHOLD_GRID:
    rows = []
    for day in normal_days:
        rows.extend(sim_day(day, thr))
    if not rows:
        print(f"  {thr*100:.1f}%        0 trades"); continue
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

if not all_results:
    print("No trades found."); sys.exit(0)

# ── 8. Detailed output for best threshold ──────────────────────────────────────
best_thr = max(all_results, key=lambda t: all_results[t]['net_pnl'].sum())
df = all_results[best_thr]

print(f"\n{'='*60}")
print(f"DETAILED — threshold={best_thr*100:.1f}%")
print(f"{'='*60}")
print(f"  {len(df)}t  P&L=${df.net_pnl.sum():+,.0f}  WR={(df.net_pnl>0).mean()*100:.1f}%"
      f"  avg=${df.net_pnl.mean():+.1f}")

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
if len(tk_s) > 10:
    print("  Bottom 5:")
    for tk, p in tk_s.tail(5).items():
        cnt = len(df[df.ticker == tk])
        print(f"  {tk:<6} {cnt:>4}t  ${p:+,.0f}")

print(f"\n  Momentum: avg={df.momentum_pct.mean():.1f}%"
      f"  median={df.momentum_pct.median():.1f}%"
      f"  max={df.momentum_pct.max():.1f}%")

# ── 9. Filter impact summary ───────────────────────────────────────────────────
print(f"\n{'='*60}")
print("FILTER IMPACT (vs v1 unfiltered)")
print(f"{'='*60}")
v1_trades_est = {0.010: 323, 0.015: 278, 0.020: 184, 0.025: 90, 0.030: 43}
v1_pnl_est    = {0.010: 1326, 0.015: 4747, 0.020: 3859, 0.025: 1294, 0.030: 516}
for thr, dfr in all_results.items():
    v1t = v1_trades_est.get(thr, '?')
    v1p = v1_pnl_est.get(thr, '?')
    print(f"  {thr*100:.1f}%: v1={v1t}t ${v1p:+,}  →  v2={len(dfr)}t ${dfr.net_pnl.sum():+,.0f}"
          f"  (Δtrades={len(dfr)-v1t:+d}  ΔP&L=${dfr.net_pnl.sum()-v1p:+,.0f})")

# ── 10. Bootstrap ──────────────────────────────────────────────────────────────
print(f"\n  Bootstrap ({N_BOOT} runs) for {best_thr*100:.1f}%...")
pnls = df['net_pnl'].values
boot = [np.random.choice(pnls, size=len(pnls), replace=True).sum()
        for _ in range(N_BOOT)]
ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
p_val = float(np.mean(np.array(boot) <= 0))
sig   = "✓ Significant" if p_val < 0.05 else "✗ NOT significant"
print(f"  p={p_val:.3f}  CI=[${ci_lo:+,.0f}, ${ci_hi:+,.0f}]  {sig}")
