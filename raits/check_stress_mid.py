import sys, pickle, pandas as pd
sys.path.insert(0, r'd:\raits\raits')
sys.path.insert(0, r'd:\raits')

with open(r'd:\raits\raits\data\cache\window_debug_results.pkl', 'rb') as f:
    r = pickle.load(f)

trades = [t for w in r for t in w.get('trades', []) if getattr(t, 'strategy', '') == 'STRESS_MID']
if not trades:
    print('No STRESS_MID trades found'); sys.exit()

df = pd.DataFrame([{
    'year': str(pd.to_datetime(t.entry_time).year),
    'pnl':  t.net_pnl,
    'win':  t.net_pnl > 0,
    'ticker': getattr(t, 'ticker', ''),
} for t in trades])

print(f'Total: {len(df)}t  PnL={df.pnl.sum():+,.0f}  WR={df.win.mean()*100:.0f}%  avg={df.pnl.mean():+.0f}/trade')
for yr in ['2020','2021','2022']:
    y = df[df.year==yr]
    if len(y):
        print(f'  {yr}: {len(y)}t  PnL={y.pnl.sum():+,.0f}  WR={y.win.mean()*100:.0f}%')
print()
tk = df.groupby('ticker')['pnl'].agg(n='count', total='sum').sort_values('total', ascending=False)
for tk_, row in tk.iterrows():
    print(f'  {tk_:<8} {int(row.n):>3}t  {row.total:>+8,.0f}')
