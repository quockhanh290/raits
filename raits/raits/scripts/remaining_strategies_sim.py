"""
remaining_strategies_sim.py — Three strategy sims with engine-grade filters

1. LATE-DAY BREAKOUT (Normal, 15:00-15:55)
   Signal: stock makes new intraday high at 15:00, up≥1% from open, SPY positive
   Universe: DailyUniverseScanner | Skip stocks already in TF position

2. CALM SWING LONG (Calm, T+1 hold)
   Signal: T-1 close within -1% to +0.5% of SMA20, 3-day pullback, today reversal candle
   Universe: vol≥500k + ATR≥1.5% | Entry: next-day 9:30 open | Exit: next-day 15:55

3. NORMAL SHORT BREAKDOWN (Normal, T+1 hold)
   Signal: today close breaks BELOW SMA20 (was above yesterday), SPY red
   Universe: vol≥500k | Entry: next-day 9:30 open SHORT | Exit: next-day 15:55

All filters:
  - Circuit breaker check
  - Engine-grade position overlap block where applicable
  - Bootstrap CI + p-value

Usage:
    cd d:\\raits\\raits
    py -3.11 raits\\scripts\\remaining_strategies_sim.py
"""

import sys, os, pickle, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
logging.disable(logging.CRITICAL)
import warnings; warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from datetime import time as dtime

from raits.strategies.universe_scanner import DailyUniverseScanner

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260623_070518.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

RISK_PER_TRADE = 500.0
TARGET_RR      = 2.0
STOP_ATR_MULT  = 1.5
N_BOOT         = 2000
BACKTEST_START = pd.Timestamp("2020-01-01")
BACKTEST_END   = pd.Timestamp("2022-12-31")

# ── 1. Load ────────────────────────────────────────────────────────────────────
print("Loading data...")
with open(PKL_RESULTS, 'rb') as f: results = pickle.load(f)
with open(PKL_5MIN,    'rb') as f: data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

spy_all = data_5min.get('SPY', pd.DataFrame())

# Days by regime
def _regime_days(regime):
    days = set()
    for w in results:
        for t in w.get('trades', []):
            d = pd.to_datetime(t.entry_time).normalize()
            if getattr(t, 'hmm_state', None) == regime and BACKTEST_START <= d <= BACKTEST_END:
                days.add(d)
    return sorted(days)

normal_days = _regime_days('Normal')
calm_days   = _regime_days('Calm')
print(f"Normal days: {len(normal_days)}  |  Calm days: {len(calm_days)}")

# ── 2. Build daily_data ────────────────────────────────────────────────────────
print("Building daily OHLCV...")
daily_data: dict = {}
for tk, bars in data_5min.items():
    d = bars.resample('D').agg(
        open=('open','first'), high=('high','max'),
        low=('low','min'),    close=('close','last'),
        volume=('volume','sum'),
    ).dropna(subset=['close'])
    if not d.empty and d['volume'].mean() > 0:
        daily_data[tk] = d

# ── 3. Pre-compute per-ticker indicators ───────────────────────────────────────
print("Pre-computing ATR14 + SMA20...")
ticker_atr  : dict = {}   # date-indexed ATR14
ticker_sma20: dict = {}   # SMA20 series
ticker_avgvol: dict = {}  # 20-day avg volume series
ticker_atrpct: dict = {}  # ATR / price

for tk, daily in daily_data.items():
    if len(daily) < 22:
        continue
    h = daily['high'].values
    l = daily['low'].values
    c = daily['close'].values
    tr = np.maximum(h[1:]-l[1:],
         np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
    idx = daily.index[1:]
    ticker_atr[tk]   = pd.Series(tr, index=idx)
    ticker_sma20[tk] = daily['close'].rolling(20).mean()
    ticker_avgvol[tk]= daily['volume'].rolling(20).mean()

def get_atr(tk, date):
    if tk not in ticker_atr: return None
    p = ticker_atr[tk][ticker_atr[tk].index.normalize() < date]
    return float(p.tail(14).mean()) if len(p) >= 14 else None

def get_sma20(tk, date):
    if tk not in ticker_sma20: return None
    p = ticker_sma20[tk][ticker_sma20[tk].index.normalize() < date]
    return float(p.iloc[-1]) if len(p) >= 1 and not pd.isna(p.iloc[-1]) else None

def get_avgvol(tk, date):
    if tk not in ticker_avgvol: return None
    p = ticker_avgvol[tk][ticker_avgvol[tk].index.normalize() < date]
    return float(p.iloc[-1]) if len(p) >= 1 and not pd.isna(p.iloc[-1]) else None

# ── 4. Engine state from snapshot ──────────────────────────────────────────────
print("Extracting engine state...")
cb_days        : set  = set()
tf_open_at_1500: dict = {}   # date → set of tickers with open TF position at 15:00
orb_open_at_1030: dict = {}

fade_open_eod: dict = {}    # date → set of tickers with FADE position open at EOD
orb_open_next_930: dict = {}  # date → set of tickers with ORB still open next morning

for w in results:
    for t in w.get('trades', []):
        ets = pd.Timestamp(t.entry_time)
        exs = pd.Timestamp(t.exit_time)
        day = ets.normalize()
        if (getattr(t,'exit_reason','') == 'CIRCUIT_BREAKER' and
                exs.time() < dtime(10, 30)):
            cb_days.add(day)
        if t.strategy == 'TREND_FOLLOW':
            if ets.time() < dtime(15, 0) and exs.time() >= dtime(15, 0):
                tf_open_at_1500.setdefault(day, set()).add(t.ticker)
        if t.strategy == 'ORB':
            if ets.time() < dtime(10, 30) and exs.time() > dtime(10, 30):
                orb_open_at_1030.setdefault(day, set()).add(t.ticker)
        # FADE: if exit is next day (swing), block same ticker next day
        if t.strategy == 'FADE':
            exit_day = exs.normalize()
            if exit_day > day:  # held overnight
                fade_open_eod.setdefault(exit_day, set()).add(t.ticker)
        # ORB held overnight (rare MAX_HOLD): block next day morning
        if t.strategy == 'ORB':
            exit_day = exs.normalize()
            if exit_day > day:
                orb_open_next_930.setdefault(exit_day, set()).add(t.ticker)

print(f"  CB days: {len(cb_days)}  |  TF-open-at-15:00 ticker-days: "
      f"{sum(len(v) for v in tf_open_at_1500.values())}")

# ── 5. Scanner for Normal days ─────────────────────────────────────────────────
print("Running DailyUniverseScanner for Normal days...")
scanner = DailyUniverseScanner(top_n=20, candidate_pool=list(data_5min.keys()))
normal_universe: dict = {}
for day in normal_days:
    t1 = day - pd.tseries.offsets.BDay(1)
    try:   normal_universe[day] = set(scanner.scan(daily_data, t1))
    except: normal_universe[day] = set()

# Simple universe for Calm/breakdown (vol≥500k, ATR≥1.5%)
def simple_universe(date, min_vol=500_000, min_atr_pct=0.015):
    out = set()
    for tk in data_5min:
        if tk in ('SPY', 'QQQ', 'IWM'): continue
        v = get_avgvol(tk, date)
        a = get_atr(tk, date)
        if not v or v < min_vol: continue
        # ATR% filter: need daily close for denominator
        if tk in daily_data:
            d = daily_data[tk]
            d2 = d[d.index.normalize() < date]
            if d2.empty: continue
            price = float(d2['close'].iloc[-1])
            if a and price > 0 and a / price >= min_atr_pct:
                out.add(tk)
    return out

def bootstrap(pnls, n=N_BOOT):
    boot = [np.random.choice(pnls, size=len(pnls), replace=True).sum()
            for _ in range(n)]
    ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
    p = float(np.mean(np.array(boot) <= 0))
    return p, ci_lo, ci_hi

def print_results(name, trades):
    if not trades:
        print(f"\n  {name}: 0 trades"); return
    df = pd.DataFrame(trades)
    tot = df.net_pnl.sum()
    wr  = (df.net_pnl > 0).mean() * 100
    print(f"\n{'='*60}")
    print(f"{name}")
    print(f"{'='*60}")
    print(f"  {len(df)}t  P&L=${tot:+,.0f}  WR={wr:.1f}%  avg=${df.net_pnl.mean():+.1f}")
    print("  By year:")
    for yr, g in df.groupby('year'):
        print(f"  {yr}  {len(g):>4}t  WR={(g.net_pnl>0).mean()*100:.0f}%  ${g.net_pnl.sum():+,.0f}")
    if 'exit_reason' in df.columns:
        print("  By exit reason:")
        for r, g in df.groupby('exit_reason'):
            print(f"  {r:<16} {len(g):>4}t  avg=${g.net_pnl.mean():+.1f}")
    print("  Top tickers:")
    tk_s = df.groupby('ticker')['net_pnl'].sum().sort_values(ascending=False)
    for tk, p in tk_s.head(8).items():
        cnt = len(df[df.ticker==tk])
        print(f"  {tk:<6} {cnt:>3}t  ${p:+,.0f}")
    p_val, ci_lo, ci_hi = bootstrap(df.net_pnl.values)
    sig = "✓ Significant" if p_val < 0.05 else "✗ NOT significant"
    print(f"  Bootstrap: p={p_val:.3f}  CI=[${ci_lo:+,.0f}, ${ci_hi:+,.0f}]  {sig}")

# ══════════════════════════════════════════════════════════════════════════════
# SIM A: LATE-DAY BREAKOUT (Normal, 15:00-15:55)
# ══════════════════════════════════════════════════════════════════════════════
print("\n>>> Running Sim A: Late-Day Breakout...")

LATE_MIN_MOMENTUM = 0.010   # up ≥1% from open by 14:55
MAX_SLOTS_LATE    = 2

def sim_late_day(day):
    if day in cb_days: return []
    universe = normal_universe.get(day, set())
    if not universe: return []
    tf_blocked = tf_open_at_1500.get(day, set())

    spy_day = spy_all[spy_all.index.normalize() == day]
    if spy_day.empty: return []
    spy_930 = spy_day[spy_day.index.time == dtime(9, 30)]
    spy_now = spy_day[(spy_day.index.time >= dtime(14, 55)) &
                      (spy_day.index.time <= dtime(15, 0))]
    if spy_930.empty or spy_now.empty: return []
    if float(spy_now.iloc[-1]['close']) <= float(spy_930.iloc[0]['open']): return []

    candidates = []
    for tk in universe:
        if tk in tf_blocked: continue
        bars  = data_5min.get(tk)
        if bars is None: continue
        day_b = bars[bars.index.normalize() == day]
        if len(day_b) < 10: continue

        b930  = day_b[day_b.index.time == dtime(9, 30)]
        b1500 = day_b[day_b.index.time == dtime(15, 0)]
        if b930.empty or b1500.empty: continue

        stock_open = float(b930.iloc[0]['open'])
        entry      = float(b1500.iloc[0]['open'])
        if stock_open <= 0: continue

        # Momentum by 14:55
        pre_1500 = day_b[day_b.index.time < dtime(15, 0)]
        if pre_1500.empty: continue
        price_1455 = float(pre_1500.iloc[-1]['close'])
        momentum = (price_1455 - stock_open) / stock_open
        if momentum < LATE_MIN_MOMENTUM: continue

        # New intraday high at 14:55 bar (signal confirmed before 15:00 open)
        b1455 = day_b[day_b.index.time == dtime(14, 55)]
        if b1455.empty: continue
        prior_high = float(day_b[day_b.index.time < dtime(14, 55)]['high'].max())
        if float(b1455.iloc[0]['high']) <= prior_high: continue

        atr = get_atr(tk, day)
        if not atr or atr <= 0: continue

        # Stop: LOD of last 30 min (14:30-14:55) − 0.5×ATR
        recent = day_b[(day_b.index.time >= dtime(14, 30)) &
                       (day_b.index.time < dtime(15, 0))]
        lod = float(recent['low'].min()) if not recent.empty else entry - atr
        stop = lod - 0.5 * atr
        stop_dist = entry - stop
        if stop_dist <= 0 or stop_dist / entry > 0.05: continue

        shares = int(RISK_PER_TRADE / stop_dist)
        if shares < 1: continue

        candidates.append(dict(
            ticker=tk, momentum=momentum,
            entry=entry, stop=stop,
            target=entry + TARGET_RR * stop_dist,
            shares=shares, day_b=day_b,
        ))

    candidates.sort(key=lambda x: -x['momentum'])
    trades = []
    for c in candidates[:MAX_SLOTS_LATE]:
        trade_bars = c['day_b'][c['day_b'].index.time >= dtime(15, 0)]
        if trade_bars.empty: continue
        ep = er = None
        for ts, bar in trade_bars.iterrows():
            if ts.time() >= dtime(15, 55):
                ep, er = float(bar['open']), 'EOD'; break
            if float(bar['low']) <= c['stop']:
                ep, er = c['stop'], 'STOP_HIT'; break
            if float(bar['high']) >= c['target']:
                ep, er = c['target'], 'TARGET_HIT'; break
        if ep is None:
            last = trade_bars.iloc[-1]
            ep, er = float(last['close']), 'EOD'
        trades.append(dict(
            ticker=c['ticker'], date=day, year=day.year,
            net_pnl=(ep - c['entry']) * c['shares'],
            exit_reason=er, momentum_pct=c['momentum']*100,
        ))
    return trades

late_trades = []
for d in normal_days:
    late_trades.extend(sim_late_day(d))
print_results("A. LATE-DAY BREAKOUT (Normal, 15:00-15:55)", late_trades)

# ══════════════════════════════════════════════════════════════════════════════
# SIM B: CALM SWING LONG (Calm regime, T+1 hold)
# ══════════════════════════════════════════════════════════════════════════════
print("\n>>> Running Sim B: Calm Swing LONG...")

MAX_SLOTS_CALM = 2
all_calm_trading_days = sorted(set(calm_days))

def sim_calm_swing(signal_day):
    # Entry is T+1 open
    t1_idx = all_calm_trading_days.index(signal_day) if signal_day in all_calm_trading_days else -1
    if t1_idx < 0 or t1_idx + 1 >= len(all_calm_trading_days): return []
    entry_day = all_calm_trading_days[t1_idx + 1]
    if entry_day in cb_days: return []

    universe = simple_universe(signal_day)
    if not universe: return []

    # SPY filter: signal_day SPY close < open (slight pullback day for entry setup)
    spy_sig = spy_all[spy_all.index.normalize() == signal_day]
    if spy_sig.empty: return []
    spy_open  = spy_sig[spy_sig.index.time == dtime(9, 30)]
    spy_close = spy_sig[spy_sig.index.time >= dtime(15, 50)]
    if spy_open.empty or spy_close.empty: return []

    fade_blocked = fade_open_eod.get(entry_day, set())

    candidates = []
    for tk in universe:
        if tk in fade_blocked: continue   # FADE swing still open on entry day
        # Signal conditions from daily bars (T-1 = signal_day)
        daily = daily_data.get(tk)
        if daily is None: continue
        d_sig = daily[daily.index.normalize() <= signal_day]
        if len(d_sig) < 22: continue

        sma20 = float(d_sig['close'].rolling(20).mean().iloc[-1])
        if pd.isna(sma20) or sma20 <= 0: continue

        close_today = float(d_sig['close'].iloc[-1])
        open_today  = float(d_sig['open'].iloc[-1])

        # Signal: close within -1% to +0.5% of SMA20
        dev = (close_today - sma20) / sma20
        if not (-0.01 <= dev <= 0.005): continue

        # 3-day pullback: closes declining
        if len(d_sig) < 4: continue
        c3 = d_sig['close'].iloc[-4:-1].values
        if not (c3[0] > c3[1] > c3[2]): continue

        # Today reversal candle: close > open
        if close_today <= open_today: continue

        # ATR for sizing
        atr = get_atr(tk, signal_day)
        if not atr or atr <= 0: continue

        # Entry day 5-min bars
        bars = data_5min.get(tk)
        if bars is None: continue
        entry_bars = bars[bars.index.normalize() == entry_day]
        if entry_bars.empty: continue
        b930 = entry_bars[entry_bars.index.time == dtime(9, 30)]
        if b930.empty: continue
        entry = float(b930.iloc[0]['open'])

        stop      = entry - STOP_ATR_MULT * atr
        stop_dist = entry - stop
        if stop_dist <= 0 or stop_dist / entry > 0.07: continue

        shares = int(RISK_PER_TRADE / stop_dist)
        if shares < 1: continue

        proximity = abs(dev)
        candidates.append(dict(
            ticker=tk, proximity=proximity,
            entry=entry, stop=stop,
            target=entry + TARGET_RR * stop_dist,
            shares=shares, entry_bars=entry_bars,
            entry_day=entry_day,
        ))

    candidates.sort(key=lambda x: x['proximity'])   # closest to SMA20 first
    trades = []
    for c in candidates[:MAX_SLOTS_CALM]:
        trade_bars = c['entry_bars'][c['entry_bars'].index.time >= dtime(9, 30)]
        if trade_bars.empty: continue
        ep = er = None
        for ts, bar in trade_bars.iterrows():
            if ts.time() >= dtime(15, 55):
                ep, er = float(bar['open']), 'EOD'; break
            if float(bar['low']) <= c['stop']:
                ep, er = c['stop'], 'STOP_HIT'; break
            if float(bar['high']) >= c['target']:
                ep, er = c['target'], 'TARGET_HIT'; break
        if ep is None:
            last = trade_bars.iloc[-1]
            ep, er = float(last['close']), 'EOD'
        trades.append(dict(
            ticker=c['ticker'], date=c['entry_day'],
            year=c['entry_day'].year,
            net_pnl=(ep - c['entry']) * c['shares'],
            exit_reason=er,
        ))
    return trades

calm_trades = []
for d in all_calm_trading_days[:-1]:   # skip last (no T+1)
    calm_trades.extend(sim_calm_swing(d))
print_results("B. CALM SWING LONG (Calm regime, T+1)", calm_trades)

# ══════════════════════════════════════════════════════════════════════════════
# SIM C: NORMAL SHORT BREAKDOWN (Normal regime, T+1 hold)
# ══════════════════════════════════════════════════════════════════════════════
print("\n>>> Running Sim C: Normal SHORT Breakdown...")

MAX_SLOTS_SHORT = 2
all_normal_sorted = sorted(normal_days)

def sim_normal_short(signal_day):
    idx = all_normal_sorted.index(signal_day) if signal_day in all_normal_sorted else -1
    if idx < 0 or idx + 1 >= len(all_normal_sorted): return []
    entry_day = all_normal_sorted[idx + 1]
    if entry_day in cb_days: return []

    universe = simple_universe(signal_day)
    if not universe: return []

    # SPY must be red today (confirms weakness)
    spy_sig = spy_all[spy_all.index.normalize() == signal_day]
    if spy_sig.empty: return []
    spy_open  = spy_sig[spy_sig.index.time == dtime(9, 30)]
    spy_close = spy_sig[spy_sig.index.time >= dtime(15, 50)]
    if spy_open.empty or spy_close.empty: return []
    if float(spy_close.iloc[-1]['close']) >= float(spy_open.iloc[0]['open']): return []

    orb_blocked = orb_open_next_930.get(entry_day, set())

    candidates = []
    for tk in universe:
        if tk in orb_blocked: continue    # ORB swing position still open at 9:30
        daily = daily_data.get(tk)
        if daily is None: continue
        d_sig = daily[daily.index.normalize() <= signal_day]
        if len(d_sig) < 22: continue

        sma20_series = d_sig['close'].rolling(20).mean()
        sma20_today  = float(sma20_series.iloc[-1])
        sma20_yest   = float(sma20_series.iloc[-2]) if len(sma20_series) >= 2 else None
        if pd.isna(sma20_today) or sma20_today <= 0: continue

        close_today = float(d_sig['close'].iloc[-1])
        close_yest  = float(d_sig['close'].iloc[-2]) if len(d_sig) >= 2 else None
        if close_yest is None: continue

        # Fresh breakdown: yesterday ABOVE SMA20, today BELOW SMA20
        if close_yest <= sma20_yest: continue         # was already below
        if close_today >= sma20_today: continue       # didn't break below
        if close_today < sma20_today * 0.97: continue # too far below (avoid gaps)

        atr = get_atr(tk, signal_day)
        if not atr or atr <= 0: continue

        # Entry day
        bars = data_5min.get(tk)
        if bars is None: continue
        entry_bars = bars[bars.index.normalize() == entry_day]
        if entry_bars.empty: continue
        b930 = entry_bars[entry_bars.index.time == dtime(9, 30)]
        if b930.empty: continue
        entry = float(b930.iloc[0]['open'])

        # SHORT: stop = SMA20 + 0.5×ATR (above breakdown), target = entry - 2R
        stop      = sma20_today + 0.5 * atr
        stop_dist = stop - entry
        if stop_dist <= 0 or stop_dist / entry > 0.06: continue

        shares = int(RISK_PER_TRADE / stop_dist)
        if shares < 1: continue

        breakdown_pct = (sma20_today - close_today) / sma20_today
        candidates.append(dict(
            ticker=tk, breakdown_pct=breakdown_pct,
            entry=entry, stop=stop,
            target=entry - TARGET_RR * stop_dist,
            shares=shares, entry_bars=entry_bars,
            entry_day=entry_day,
        ))

    candidates.sort(key=lambda x: -x['breakdown_pct'])
    trades = []
    for c in candidates[:MAX_SLOTS_SHORT]:
        trade_bars = c['entry_bars'][c['entry_bars'].index.time >= dtime(9, 30)]
        if trade_bars.empty: continue
        ep = er = None
        for ts, bar in trade_bars.iterrows():
            if ts.time() >= dtime(15, 55):
                ep, er = float(bar['open']), 'EOD'; break
            if float(bar['high']) >= c['stop']:        # stop = price goes UP (SHORT)
                ep, er = c['stop'], 'STOP_HIT'; break
            if float(bar['low']) <= c['target']:       # target = price goes DOWN
                ep, er = c['target'], 'TARGET_HIT'; break
        if ep is None:
            last = trade_bars.iloc[-1]
            ep, er = float(last['close']), 'EOD'
        pnl = (c['entry'] - ep) * c['shares']         # SHORT: profit when price falls
        trades.append(dict(
            ticker=c['ticker'], date=c['entry_day'],
            year=c['entry_day'].year,
            net_pnl=pnl, exit_reason=er,
        ))
    return trades

short_trades = []
for d in all_normal_sorted[:-1]:
    short_trades.extend(sim_normal_short(d))
print_results("C. NORMAL SHORT BREAKDOWN (Normal, T+1)", short_trades)

print("\nDone.")
