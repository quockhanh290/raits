import sys, pickle
import pandas as pd

sys.path.insert(0, r'd:\raits')
sys.path.insert(0, r'd:\raits\raits')

with open(r'data/cache/snapshots/results_20260619_104520.pkl', 'rb') as f:
    r = pickle.load(f)
trades = [t for w in r for t in w.get('trades', []) if t.strategy == 'GAP_FILL']
df = pd.DataFrame([vars(t) for t in trades])
df['year']     = df['entry_time'].dt.year
df['date']     = df['entry_time'].dt.date
df['hold_hrs'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600
df['win']      = df['net_pnl'] > 0

wins = df[df['win']]['net_pnl']
loss = df[~df['win']]['net_pnl']
pf   = wins.sum() / abs(loss.sum()) if len(loss) else float('inf')

print('=== SUMMARY ===')
print(f'Trades: {len(df)}  |  P&L: ${df.net_pnl.sum():.0f}  |  WR: {df.win.mean():.0%}')
print(f'Avg win: ${wins.mean():.0f}  |  Avg loss: ${loss.mean():.0f}  |  Profit factor: {pf:.2f}')
print()

print('=== BY YEAR ===')
yr = df.groupby('year').agg(n=('net_pnl','count'), pnl=('net_pnl','sum'), wr=('win','mean'))
yr['wr'] = yr['wr'].map('{:.0%}'.format)
print(yr)
print()

print('=== BY EXIT REASON ===')
ex = df.groupby('exit_reason').agg(n=('net_pnl','count'), pnl=('net_pnl','sum'),
                                    wr=('win','mean'), avg=('net_pnl','mean')).round(1)
ex['wr'] = ex['wr'].map('{:.0%}'.format)
print(ex)
print()

print('=== EXIT REASON x YEAR ===')
print(df.groupby(['year', 'exit_reason'])['net_pnl'].agg(['count', 'sum']).round(0))
print()

print('=== SAME-DAY CLUSTERS (days with 2+ trades) ===')
day_counts = df.groupby('date').size()
multi_days = day_counts[day_counts >= 2].index
cluster_df = df[df['date'].isin(multi_days)][['date','ticker','net_pnl','exit_reason']]
print(cluster_df.sort_values(['date','net_pnl']).to_string(index=False))
print()

print('=== HOLD TIME BY EXIT (hours) ===')
print(df.groupby('exit_reason')['hold_hrs'].agg(['min','mean','max']).round(2))
print()

print('=== WIN vs LOSS BY YEAR ===')
for y in sorted(df.year.unique()):
    yd = df[df.year == y]
    w = yd[yd.win]['net_pnl']
    l = yd[~yd.win]['net_pnl']
    w_avg = f'${w.mean():.0f}' if len(w) else 'N/A'
    l_avg = f'${l.mean():.0f}' if len(l) else 'N/A'
    print(f'{y}: {len(yd)}t  wins={len(w)} avg={w_avg}  losses={len(l)} avg={l_avg}')
print()

print('=== ALL TRADES (sorted by P&L) ===')
print(df[['date','ticker','net_pnl','exit_reason','hold_hrs']].sort_values('net_pnl', ascending=False).to_string(index=False))
