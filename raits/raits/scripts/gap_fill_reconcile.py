"""
Reconcile sim vs engine GAP_FILL trades.

Sim:    TF-Normal-days proxy, fixed $500 risk, prev_close+50%gap target
Engine: HMM Normal days, position_sizer, same target formula

Questions:
  1. Which trades overlap (same date + ticker)?
  2. For overlapping: same exit reason? P&L difference?
  3. Sim-only: which dates/tickers did sim find that engine missed?
  4. Engine-only: which did engine find that sim didn't? (the losers)
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
from datetime import time as dtime

PKL_RESULTS  = r'd:\raits\raits\data\cache\snapshots\results_scenario_g.pkl'
PKL_5MIN     = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
PKL_BACKTEST = r'd:\raits\raits\data\cache\snapshots\results_20260619_104520.pkl'

# ── Load data ─────────────────────────────────────────────────────────────────
with open(PKL_RESULTS,  'rb') as f: results_old  = pickle.load(f)
with open(PKL_5MIN,     'rb') as f: data_5min    = pickle.load(f)
with open(PKL_BACKTEST, 'rb') as f: results_new  = pickle.load(f)

for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# ── Engine trades ─────────────────────────────────────────────────────────────
eng_trades = [t for w in results_new for t in w.get('trades', []) if t.strategy == 'GAP_FILL']
eng_df = pd.DataFrame([{
    'date':   t.entry_time.date(),
    'ticker': t.ticker,
    'net_pnl_eng': t.net_pnl,
    'exit_eng':    t.exit_reason,
    'shares_eng':  t.shares,
} for t in eng_trades])

# ── Sim setup ─────────────────────────────────────────────────────────────────
rows_old = []
for w in results_old:
    for t in w.get('trades', []):
        d = vars(t).copy(); d['year'] = w.get('label', '?')
        rows_old.append(d)
df_all = pd.DataFrame(rows_old)
df_all['entry_time'] = pd.to_datetime(df_all['entry_time'])
tf_normal = df_all[(df_all['strategy'] == 'TREND_FOLLOW') & (df_all['hmm_state'] == 'Normal')].copy()
tf_normal['date'] = tf_normal['entry_time'].dt.normalize()
normal_days = sorted(tf_normal['date'].unique())
available_tickers = [tk for tk in data_5min if tk != 'SPY']

# SPY VWAP
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
    if len(bars) < 2: return float(bars['close'].iloc[-1]) * 0.015
    hl  = bars['high'] - bars['low']
    hpc = (bars['high'] - bars['close'].shift(1)).abs()
    lpc = (bars['low']  - bars['close'].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

# Precompute
prev_close_map = {}
day_bars_cache = {}
for ticker in available_tickers:
    if ticker not in data_5min: continue
    bars = data_5min[ticker].sort_index()
    bars['date'] = bars.index.normalize()
    daily_last = bars.groupby('date')['close'].last()
    dates = daily_last.index.tolist()
    for i in range(1, len(dates)):
        prev_close_map[(ticker, dates[i])] = float(daily_last.iloc[i-1])
for day in normal_days:
    for ticker in available_tickers:
        if ticker not in data_5min: continue
        db = data_5min[ticker][data_5min[ticker].index.normalize() == day].sort_index()
        if len(db) >= 8:
            day_bars_cache[(ticker, day)] = db

# ── Sim: extend_50 target (same as engine) ───────────────────────────────────
def run_sim(ticker, day, day_bars):
    prev_c = prev_close_map.get((ticker, day))
    if prev_c is None or prev_c <= 0: return None

    first_bar = day_bars[day_bars.index.time >= dtime(9, 30)]
    if first_bar.empty: return None
    session_open = float(first_bar.iloc[0]['open'])
    gap_pct  = (session_open - prev_c) / prev_c
    gap_size = session_open - prev_c

    if abs(gap_pct) < 0.015 or abs(gap_pct) > 0.03: return None
    if gap_pct >= 0: return None  # LONG only

    pre_entry = day_bars[day_bars.index.time <= dtime(10, 30)]
    if pre_entry.empty: return None
    px_1030 = float(pre_entry.iloc[-1]['close'])

    retrace = (session_open - px_1030) / gap_size if gap_size != 0 else 0
    if not (0.50 <= retrace <= 0.85): return None

    if spy_bull(pre_entry.index[-1]) is False: return None

    morning_lod = float(pre_entry['low'].min())
    atr = compute_atr(pre_entry)
    if atr <= 0: return None

    entry_px  = px_1030
    stop_px   = morning_lod - 0.1 * atr
    stop_dist = abs(entry_px - stop_px)
    if stop_dist <= 0: return None
    shares    = max(1, int(500 / stop_dist))

    # Same target as engine: prev_c + 50% of gap (above prev_c)
    target_px = prev_c + 0.50 * abs(gap_size)

    bars_after = day_bars[day_bars.index.time > dtime(10, 30)]
    bars_after = bars_after[bars_after.index.time < dtime(13, 30)]

    trailing = stop_px; exit_px = entry_px; reason = 'TIME_STOP'
    for _, b in bars_after.iterrows():
        trailing = max(trailing, float(b['high']) - stop_dist)
        if float(b['low']) <= trailing:
            exit_px = trailing; reason = 'STOP_HIT'; break
        if float(b['high']) >= target_px:
            exit_px = target_px; reason = 'TARGET_HIT'; break
        exit_px = float(b['close'])

    net = (exit_px - entry_px) * shares - shares * 0.01 * 2
    return dict(date=day.date(), ticker=ticker, net_pnl_sim=net,
                exit_sim=reason, shares_sim=shares)

print('Running sim on TF Normal days...')
sim_trades = []
for day in normal_days:
    for ticker in available_tickers:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        r = run_sim(ticker, day, db)
        if r: sim_trades.append(r)

sim_df = pd.DataFrame(sim_trades)

# ── Summary ───────────────────────────────────────────────────────────────────
print(f'\n=== SIM   : {len(sim_df)}t  P&L=${sim_df.net_pnl_sim.sum():.0f}  WR={(sim_df.net_pnl_sim>0).mean():.0%}')
print(f'=== ENGINE: {len(eng_df)}t  P&L=${eng_df.net_pnl_eng.sum():.0f}  WR={(eng_df.net_pnl_eng>0).mean():.0%}')

# ── Overlap analysis ──────────────────────────────────────────────────────────
sim_df['key']  = sim_df['date'].astype(str) + '|' + sim_df['ticker']
eng_df['key']  = eng_df['date'].astype(str) + '|' + eng_df['ticker']

sim_keys = set(sim_df['key'])
eng_keys = set(eng_df['key'])

overlap    = sim_keys & eng_keys
sim_only   = sim_keys - eng_keys
eng_only   = eng_keys - sim_keys

print(f'\n=== OVERLAP ({len(overlap)} trades in both) ===')
ov_sim = sim_df[sim_df['key'].isin(overlap)].set_index('key')
ov_eng = eng_df[eng_df['key'].isin(overlap)].set_index('key')
ov = ov_sim.join(ov_eng[['net_pnl_eng','exit_eng','shares_eng']])
ov['pnl_diff'] = ov['net_pnl_eng'] - ov['net_pnl_sim']
ov['same_exit'] = ov['exit_sim'] == ov['exit_eng']
print(ov[['ticker','date','net_pnl_sim','net_pnl_eng','pnl_diff','exit_sim','exit_eng','shares_sim','shares_eng']].sort_values('pnl_diff').to_string())
print(f'\nOverlap P&L: sim=${ov.net_pnl_sim.sum():.0f}  eng=${ov.net_pnl_eng.sum():.0f}  diff=${ov.pnl_diff.sum():.0f}')
print(f'Same exit reason: {ov.same_exit.sum()}/{len(ov)}')

print(f'\n=== SIM ONLY ({len(sim_only)} trades sim found, engine missed) ===')
print(sim_df[sim_df['key'].isin(sim_only)][['date','ticker','net_pnl_sim','exit_sim']].sort_values('net_pnl_sim',ascending=False).to_string(index=False))

print(f'\n=== ENGINE ONLY ({len(eng_only)} trades engine found, sim missed) ===')
print(eng_df[eng_df['key'].isin(eng_only)][['date','ticker','net_pnl_eng','exit_eng']].sort_values('net_pnl_eng',ascending=False).to_string(index=False))

print(f'\n=== SIM Normal days: {len(normal_days)}  |  Engine Normal days from GAP_FILL trades: {len(eng_df.date.unique())}')
print(f'Sim P&L attribution:')
print(f'  Overlap portion:  ${ov.net_pnl_sim.sum():.0f}')
sim_only_pnl = sim_df[sim_df['key'].isin(sim_only)]['net_pnl_sim'].sum()
print(f'  Sim-only portion: ${sim_only_pnl:.0f}')
eng_only_pnl = eng_df[eng_df['key'].isin(eng_only)]['net_pnl_eng'].sum()
print(f'  Eng-only portion: ${eng_only_pnl:.0f}')
