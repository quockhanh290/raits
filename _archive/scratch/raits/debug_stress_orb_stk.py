"""
debug_stress_orb_stk.py — Trả lời 3 câu hỏi về failed STRESS_ORB_STK implementation.

Q1: Tại sao ETF count tăng từ ~40t lên 289t?
Q2: Tại sao 9:35 entry tệ hơn 9:40?
Q3: 19 STOP_HIT = -$2,027 từ đâu?

Usage:
    cd D:\raits\raits
    python debug_stress_orb_stk.py
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pickle
import pandas as pd

BASELINE = 'data/cache/snapshots/results_20260620_163631.pkl'
FAILED   = 'data/cache/snapshots/results_20260620_233125.pkl'

print("Loading snapshots...")
with open(BASELINE, 'rb') as f: baseline = pickle.load(f)
with open(FAILED,   'rb') as f: failed   = pickle.load(f)

ETF_SET = {"SPY", "QQQ", "IWM"}

def extract_trades(results, strategy_filter=None):
    rows = []
    for w in results:
        for t in w.get('trades', []):
            if strategy_filter and t.strategy not in strategy_filter:
                continue
            entry_dt = pd.to_datetime(t.entry_time)
            rows.append(dict(
                strategy    = t.strategy,
                ticker      = t.ticker,
                is_etf      = t.ticker in ETF_SET,
                year        = str(entry_dt.year),
                entry_time  = entry_dt,
                entry_t     = entry_dt.time(),
                direction   = t.direction,
                entry_px    = t.entry_price,
                exit_px     = t.exit_price,
                exit_reason = t.exit_reason,
                net_pnl     = t.net_pnl or 0.0,
                stop        = getattr(t, 'stop', None),
                target      = getattr(t, 'target', None),
            ))
    return pd.DataFrame(rows)

base_df = extract_trades(baseline, {'STRESS_ORB'})
fail_df = extract_trades(failed,   {'STRESS_ORB', 'STRESS_ORB_STK'})

# ─────────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print("  Q1: ETF COUNT EXPLOSION")
print(f"{'='*65}")

base_etf  = base_df[base_df['is_etf']]
base_stk  = base_df[~base_df['is_etf']]
fail_sorb = fail_df[fail_df['strategy'] == 'STRESS_ORB']
fail_sstk = fail_df[fail_df['strategy'] == 'STRESS_ORB_STK']
fail_etf  = fail_sorb[fail_sorb['is_etf']]
fail_non  = fail_sorb[~fail_sorb['is_etf']]

print(f"\n  Baseline STRESS_ORB:  {len(base_df)}t total | ETF={len(base_etf)}t | stock={len(base_stk)}t")
print(f"  Failed STRESS_ORB:    {len(fail_sorb)}t total | ETF={len(fail_etf)}t | non-ETF={len(fail_non)}t")
print(f"  Failed STRESS_ORB_STK:{len(fail_sstk)}t total")
print(f"\n  ETF delta: {len(fail_etf) - len(base_etf):+d} trades")

if len(fail_non) > 0:
    print(f"\n  Non-ETF tickers under STRESS_ORB slot (should be 0):")
    by_tk = fail_non.groupby('ticker')['net_pnl'].agg(n='count', total='sum')
    print(by_tk.sort_values('n', ascending=False).head(20).to_string())
else:
    print(f"\n  No non-ETF tickers under STRESS_ORB slot → ETF explosion from elsewhere")

if len(fail_etf) > 0:
    print(f"\n  ETF breakdown in failed run:")
    by_tk = fail_etf.groupby('ticker')['net_pnl'].agg(n='count', total='sum', wr=lambda x: (x>0).mean()*100)
    print(by_tk.to_string())

    print(f"\n  Baseline ETF breakdown:")
    by_tk2 = base_etf.groupby('ticker')['net_pnl'].agg(n='count', total='sum', wr=lambda x: (x>0).mean()*100)
    print(by_tk2.to_string())

    # Per-year ETF count
    print(f"\n  ETF count by year — baseline vs failed:")
    b_yr = base_etf.groupby('year').size().rename('baseline')
    f_yr = fail_etf.groupby('year').size().rename('failed')
    print(pd.concat([b_yr, f_yr], axis=1).fillna(0).astype(int).to_string())

# ─────────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print("  Q2: 9:35 vs 9:40 ENTRY COMPARISON")
print(f"{'='*65}")

# Look at STRESS_ORB_STK trades in failed run
stk_trades = fail_df[fail_df['strategy'] == 'STRESS_ORB_STK'].copy()
if len(stk_trades) == 0:
    # Maybe stocks were under STRESS_ORB label
    stk_trades = fail_non.copy()
    print("  (Using non-ETF STRESS_ORB trades as proxy)")

if len(stk_trades) > 0:
    stk_trades['entry_min'] = stk_trades['entry_time'].dt.hour * 60 + stk_trades['entry_time'].dt.minute
    # Group by entry minute
    by_min = stk_trades.groupby('entry_min').agg(
        n=('net_pnl','count'),
        total_pnl=('net_pnl','sum'),
        wr=('net_pnl', lambda x: (x>0).mean()*100),
        avg=('net_pnl','mean'),
    )
    by_min['time'] = by_min.index.map(lambda m: f"{m//60:02d}:{m%60:02d}")
    print(f"\n  STRESS_ORB_STK by entry time ({len(stk_trades)}t total):")
    print(f"  {'Time':<6} {'Trades':>6} {'P&L':>9} {'WR%':>6} {'avg':>8}")
    for _, row in by_min.iterrows():
        print(f"  {row['time']:<6} {int(row['n']):>6} {row['total_pnl']:>+9,.0f} {row['wr']:>5.0f}% {row['avg']:>+8.1f}")

    # 9:35 vs rest
    t935 = stk_trades[stk_trades['entry_min'] == 9*60+35]
    t940p = stk_trades[stk_trades['entry_min'] >= 9*60+40]
    print(f"\n  9:35 only:  {len(t935)}t  P&L={t935['net_pnl'].sum():+,.0f}  WR={t935['net_pnl'].gt(0).mean()*100:.0f}%")
    print(f"  9:40+:      {len(t940p)}t  P&L={t940p['net_pnl'].sum():+,.0f}  WR={t940p['net_pnl'].gt(0).mean()*100:.0f}%")

    # By year
    print(f"\n  9:35 trades by year:")
    if len(t935):
        print(t935.groupby('year')['net_pnl'].agg(n='count', total='sum').to_string())
else:
    print("  No stock trades found in failed run — check snapshot contents")

# ─────────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print("  Q3: STOP_HIT TRADES DETAIL")
print(f"{'='*65}")

all_stk = pd.concat([stk_trades, fail_non], ignore_index=True).drop_duplicates()
stop_hits = all_stk[all_stk['exit_reason'] == 'STOP_HIT'].copy() if len(all_stk) else pd.DataFrame()

print(f"\n  All STRESS_ORB_STK exits:")
if len(all_stk):
    by_reason = all_stk.groupby('exit_reason')['net_pnl'].agg(n='count', total='sum', wr=lambda x:(x>0).mean()*100)
    print(by_reason.to_string())

if len(stop_hits):
    stop_hits = stop_hits.copy()
    if 'stop' in stop_hits.columns and 'entry_px' in stop_hits.columns:
        stop_hits['stop_dist'] = (stop_hits['stop'] - stop_hits['entry_px']).abs()
    print(f"\n  {len(stop_hits)} STOP_HIT trades (P&L={stop_hits['net_pnl'].sum():+,.0f}):")
    cols = ['ticker', 'year', 'entry_time', 'entry_px', 'stop', 'stop_dist', 'net_pnl']
    cols = [c for c in cols if c in stop_hits.columns]
    print(stop_hits[cols].sort_values('entry_time').to_string(index=False))

    # Stop distance distribution
    if 'stop_dist' in stop_hits.columns:
        print(f"\n  Stop dist stats: min={stop_hits['stop_dist'].min():.3f}  "
              f"median={stop_hits['stop_dist'].median():.3f}  "
              f"max={stop_hits['stop_dist'].max():.3f}")

# ─────────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print("  STRATEGY P&L COMPARISON")
print(f"{'='*65}")
def total_pnl(results):
    d = {}
    for w in results:
        for t in w.get('trades', []):
            d[t.strategy] = d.get(t.strategy, 0) + (t.net_pnl or 0)
    return d

base_pnl = total_pnl(baseline)
fail_pnl = total_pnl(failed)
strats = sorted(set(list(base_pnl) + list(fail_pnl)))
print(f"\n  {'Strategy':<16} {'Baseline':>10} {'Failed':>10} {'Delta':>10}")
print(f"  {'-'*50}")
for s in strats:
    b = base_pnl.get(s, 0); f = fail_pnl.get(s, 0)
    print(f"  {s:<16} {b:>+10,.0f} {f:>+10,.0f} {f-b:>+10,.0f}")
print(f"  {'-'*50}")
tb = sum(base_pnl.values()); tf = sum(fail_pnl.values())
print(f"  {'TOTAL':<16} {tb:>+10,.0f} {tf:>+10,.0f} {tf-tb:>+10,.0f}")
