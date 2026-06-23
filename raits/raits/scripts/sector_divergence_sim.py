"""
sector_divergence_sim.py — Sector ETF Divergence strategy

Signal at 9:35: if sector ETF outperforms SPY by >threshold → LONG
                if sector ETF underperforms SPY by >threshold → SHORT
                (SPY-relative divergence isolates sector strength vs market noise)

Universe: XLF, XLE, XLV, XLU, XLI, XLK, XLP, XLB, XLY
Entry   : 9:35 bar CLOSE (signal confirmed)
Stop    : 1.0×ATR(14) below/above entry
Target  : 2R (fixed)
Time exit: configurable (test 11:00, 12:00, 13:00)
Regime  : Normal only (primary), then Calm check separately

Tests multiple thresholds and exit times. Bootstrap per config.

Usage:
    cd d:\\raits\\raits
    py -3.11 raits\\scripts\\sector_divergence_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np
from datetime import time as dtime
from itertools import product

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
N_BOOT      = 10_000

SECTOR_ETFS = ['XLF', 'XLE', 'XLV', 'XLU', 'XLI', 'XLK', 'XLP', 'XLB', 'XLY']

ENTRY_TIME  = dtime(9, 35)
RISK_PER_TRADE = 500.0
COMM_PER_SHARE = 0.01

# ── load ──────────────────────────────────────────────────────────────────────
print("Loading data...")
with open(PKL_RESULTS, 'rb') as f:
    results = pickle.load(f)
with open(PKL_5MIN, 'rb') as f:
    data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# ── regime days ───────────────────────────────────────────────────────────────
normal_days = sorted({
    pd.to_datetime(t.entry_time).normalize()
    for w in results for t in w.get('trades', [])
    if getattr(t, 'hmm_state', None) == 'Normal'
})
calm_days = sorted({
    pd.to_datetime(t.entry_time).normalize()
    for w in results for t in w.get('trades', [])
    if getattr(t, 'hmm_state', None) == 'Calm'
})
print(f"Normal days: {len(normal_days)}  Calm days: {len(calm_days)}")

spy = data_5min['SPY'].sort_index()

# ── SPY VWAP at entry ─────────────────────────────────────────────────────────
spy_copy = spy.copy()
spy_copy['tp']      = (spy_copy['high'] + spy_copy['low'] + spy_copy['close']) / 3
spy_copy['tpv']     = spy_copy['tp'] * spy_copy['volume']
spy_copy['date']    = spy_copy.index.normalize()
spy_copy['cum_tpv'] = spy_copy.groupby('date')['tpv'].cumsum()
spy_copy['cum_vol'] = spy_copy.groupby('date')['volume'].cumsum()
spy_copy['vwap']    = spy_copy['cum_tpv'] / spy_copy['cum_vol']
spy_vwap = spy_copy['vwap'].to_dict()

def get_spy_vwap(ts):
    return spy_vwap.get(ts, None)

# ── ATR helper ────────────────────────────────────────────────────────────────
def compute_atr(bars, period=14):
    if len(bars) < 2:
        return float(bars['close'].iloc[-1]) * 0.015
    hl  = bars['high'] - bars['low']
    hpc = (bars['high'] - bars['close'].shift(1)).abs()
    lpc = (bars['low']  - bars['close'].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

# ── precompute day caches ─────────────────────────────────────────────────────
print("Precomputing day caches...")
all_days = sorted(set(normal_days) | set(calm_days))

# SPY 9:30 open and 9:35 close per day
spy_open_930  = {}
spy_close_935 = {}
for day in all_days:
    d_bars = spy[spy.index.normalize() == day].sort_index()
    b930 = d_bars[d_bars.index.time == dtime(9, 30)]
    b935 = d_bars[d_bars.index.time == ENTRY_TIME]
    if not b930.empty and not b935.empty:
        spy_open_930[day]  = float(b930.iloc[0]['open'])
        spy_close_935[day] = float(b935.iloc[0]['close'])

# ETF day bars cache
etf_day_cache = {}
for etf in SECTOR_ETFS:
    if etf not in data_5min:
        continue
    bars = data_5min[etf].sort_index()
    for day in all_days:
        d = bars[bars.index.normalize() == day].sort_index()
        if len(d) >= 4:
            etf_day_cache[(etf, day)] = d

# ── simulate one trade ────────────────────────────────────────────────────────
def simulate_one(etf, day, day_bars, divergence, exit_time, target_r=2.0):
    # Entry bar: 9:35 close
    entry_bars = day_bars[day_bars.index.time == ENTRY_TIME]
    if entry_bars.empty:
        return None
    entry_ts  = entry_bars.index[0]
    px_entry  = float(entry_bars.iloc[0]['close'])

    # Direction from divergence
    direction = 'LONG' if divergence > 0 else 'SHORT'

    # SPY direction alignment (optional filter applied outside)
    vwap_val = get_spy_vwap(entry_ts)
    spy_close_at_entry = spy_close_935.get(day)
    if vwap_val and spy_close_at_entry:
        spy_above = spy_close_at_entry > vwap_val
        if direction == 'LONG' and not spy_above:
            return None   # don't long when SPY below VWAP
        if direction == 'SHORT' and spy_above:
            return None   # don't short when SPY above VWAP

    # ATR from bars so far
    bars_to_entry = day_bars[day_bars.index <= entry_ts]
    atr = compute_atr(bars_to_entry)
    if atr <= 0:
        return None

    stop_dist = atr
    if stop_dist <= 0:
        return None

    shares    = max(1, int(RISK_PER_TRADE / stop_dist))
    stop_px   = (px_entry - stop_dist) if direction == 'LONG' else (px_entry + stop_dist)
    target_px = (px_entry + target_r * stop_dist) if direction == 'LONG' else (px_entry - target_r * stop_dist)

    # Execution
    bars_after = day_bars[
        (day_bars.index.time > ENTRY_TIME) & (day_bars.index.time <= exit_time)
    ]
    exit_px = px_entry
    reason  = 'TIME_STOP'

    if direction == 'LONG':
        trailing = stop_px
        for _, b in bars_after.iterrows():
            trailing = max(trailing, float(b['high']) - stop_dist)
            if float(b['low']) <= trailing:
                exit_px = trailing; reason = 'STOP_HIT'; break
            if float(b['high']) >= target_px:
                exit_px = target_px; reason = 'TARGET_HIT'; break
            exit_px = float(b['close'])
        net = (exit_px - px_entry) * shares - shares * COMM_PER_SHARE * 2
    else:
        trailing = stop_px
        for _, b in bars_after.iterrows():
            trailing = min(trailing, float(b['low']) + stop_dist)
            if float(b['high']) >= trailing:
                exit_px = trailing; reason = 'STOP_HIT'; break
            if float(b['low']) <= target_px:
                exit_px = target_px; reason = 'TARGET_HIT'; break
            exit_px = float(b['close'])
        net = (px_entry - exit_px) * shares - shares * COMM_PER_SHARE * 2

    return dict(
        etf=etf, day=day, year=str(day.year),
        direction=direction, divergence=round(divergence * 100, 3),
        exit_reason=reason, net_pnl=net, win=net > 0,
    )

# ── bootstrap ─────────────────────────────────────────────────────────────────
rng = np.random.default_rng(42)

def bootstrap(pnls):
    if len(pnls) < 5:
        return float('nan'), float('nan'), float('nan')
    outcomes = np.array(pnls)
    boot = np.array([rng.choice(outcomes, size=len(outcomes), replace=True).sum()
                     for _ in range(N_BOOT)])
    p_val = (boot <= 0).mean()
    ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
    return p_val, ci_lo, ci_hi

# ── grid search ───────────────────────────────────────────────────────────────
THRESHOLDS  = [0.003, 0.005, 0.007]   # 0.3%, 0.5%, 0.7%
EXIT_TIMES  = [dtime(11, 0), dtime(12, 0), dtime(13, 0)]
REGIME_SETS = [('Normal', normal_days), ('Calm', calm_days), ('Normal+Calm', sorted(set(normal_days)|set(calm_days)))]

print("\nRunning grid search...\n")
best_configs = []

for regime_label, days in REGIME_SETS:
    print(f"\n{'='*70}")
    print(f"  REGIME: {regime_label}  ({len(days)} days)")
    print(f"{'='*70}")
    print(f"  {'Thresh':>7}  {'Exit':>6}  {'N':>4}  {'P&L':>9}  {'WR':>5}  {'avg':>7}  {'p':>6}  {'CI'}")
    print(f"  {'-'*67}")

    for thresh, exit_t in product(THRESHOLDS, EXIT_TIMES):
        trades = []
        for day in days:
            if day not in spy_open_930:
                continue
            spy_o = spy_open_930[day]
            spy_c = spy_close_935.get(day)
            if not spy_c or spy_o <= 0:
                continue
            spy_ret = (spy_c - spy_o) / spy_o

            for etf in SECTOR_ETFS:
                db = etf_day_cache.get((etf, day))
                if db is None:
                    continue
                b930 = db[db.index.time == dtime(9, 30)]
                b935 = db[db.index.time == ENTRY_TIME]
                if b930.empty or b935.empty:
                    continue
                etf_o = float(b930.iloc[0]['open'])
                etf_c = float(b935.iloc[0]['close'])
                if etf_o <= 0:
                    continue
                etf_ret   = (etf_c - etf_o) / etf_o
                divergence = etf_ret - spy_ret

                if abs(divergence) < thresh:
                    continue

                r = simulate_one(etf, day, db, divergence, exit_t)
                if r:
                    trades.append(r)

        if not trades:
            print(f"  {thresh*100:.1f}%    {str(exit_t)[:5]}     0      —")
            continue

        df   = pd.DataFrame(trades)
        pnl  = df['net_pnl'].sum()
        wr   = df['win'].mean()
        avg  = df['net_pnl'].mean()
        p, cl, ch = bootstrap(df['net_pnl'].tolist())
        sig = '✓' if (not pd.isna(p) and p < 0.05) else ' '
        p_str  = f"{p:.3f}" if not pd.isna(p) else "  —  "
        ci_str = f"[${cl:+,.0f},${ch:+,.0f}]" if not pd.isna(p) else ""
        print(f"  {thresh*100:.1f}%    {str(exit_t)[:5]}  {len(df):>4}  ${pnl:>8,.0f}"
              f"  {wr:>4.0%}  ${avg:>6.1f}  {p_str} {sig}  {ci_str}")

        if not pd.isna(p) and p < 0.05 and pnl > 0:
            best_configs.append((regime_label, thresh, exit_t, trades))

# ── detail view for significant configs ──────────────────────────────────────
if best_configs:
    print(f"\n\n{'='*70}")
    print("  SIGNIFICANT CONFIGS — DETAIL")
    print(f"{'='*70}")
    for regime_label, thresh, exit_t, trades in best_configs:
        df  = pd.DataFrame(trades)
        pnl = df['net_pnl'].sum()
        wr  = df['win'].mean()
        p, cl, ch = bootstrap(df['net_pnl'].tolist())
        print(f"\n  [{regime_label}] thresh={thresh*100:.1f}%  exit={exit_t}  "
              f"{len(df)}t  ${pnl:+,.0f}  WR={wr:.0%}  p={p:.3f}")

        print(f"  By year:")
        for yr in ['2020', '2021', '2022']:
            s = df[df['year'] == yr]
            if len(s):
                print(f"    {yr}: {len(s):3d}t  ${s['net_pnl'].sum():+7,.0f}  WR={s['win'].mean():.0%}")

        print(f"  By ETF:")
        grp = df.groupby('etf')['net_pnl'].agg(n='count', total='sum').sort_values('total', ascending=False)
        for etf, row in grp.iterrows():
            s = df[df['etf'] == etf]
            print(f"    {etf}: {int(row['n']):2d}t  ${row['total']:+7,.0f}  WR={s['win'].mean():.0%}")

        print(f"  By direction:")
        for d in ['LONG', 'SHORT']:
            s = df[df['direction'] == d]
            if len(s):
                print(f"    {d}: {len(s):3d}t  ${s['net_pnl'].sum():+7,.0f}  WR={s['win'].mean():.0%}")

        print(f"  By exit:")
        for ex in sorted(df['exit_reason'].unique()):
            s = df[df['exit_reason'] == ex]
            print(f"    {ex:<14}: {len(s):3d}t  ${s['net_pnl'].sum():+7,.0f}  WR={s['win'].mean():.0%}")

        print(f"  Bootstrap: p={p:.3f}  CI=[${cl:+,.0f}, ${ch:+,.0f}]")
else:
    print("\n  No significant configs found (all p ≥ 0.05)")
print()
