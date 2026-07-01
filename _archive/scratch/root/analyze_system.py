import pickle, pandas as pd, numpy as np

SNAP = r'd:\raits\raits\data\cache\snapshots\results_20260623_070518.pkl'
with open(SNAP,'rb') as f: results = pickle.load(f)

all_trades = []
for w in results:
    all_trades.extend(w['trades'])

df = pd.DataFrame([{
    'strategy':    t.strategy,
    'ticker':      t.ticker,
    'direction':   t.direction,
    'entry_time':  pd.Timestamp(t.entry_time),
    'exit_time':   pd.Timestamp(t.exit_time),
    'entry_price': t.entry_price,
    'exit_price':  t.exit_price,
    'shares':      t.shares,
    'net_pnl':     t.net_pnl,
    'exit_reason': t.exit_reason,
    'hmm_state':   getattr(t, 'hmm_state', '?'),
} for t in all_trades])

df['year']      = df['entry_time'].dt.year
df['hold_mins'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 60
df['win']       = df['net_pnl'] > 0
df['is_swing']  = df['hold_mins'] > 400

total_pnl = df.net_pnl.sum()

print('='*62)
print('SYSTEM ANALYSIS — results_20260623_070518.pkl')
print('='*62)
print(f'Total trades : {len(df)}')
print(f'Period       : 2020-2022  |  Account: $50,000')
print(f'Total P&L    : ${total_pnl:+,.0f}  |  Avg/yr: ${total_pnl/3:+,.0f}  |  Return: {total_pnl/50000*100:.1f}%/yr')

# 1. By strategy
print()
print('BY STRATEGY')
print(f'  {"Strategy":<15} {"Trades":>6} {"WR%":>6} {"Avg$":>8} {"Total$":>9} {"Share%":>7}')
print('  ' + '-'*55)
strat_rows = []
for s, g in df.groupby('strategy'):
    wr  = g['win'].mean() * 100
    avg = g['net_pnl'].mean()
    tot = g['net_pnl'].sum()
    pct = tot / total_pnl * 100
    strat_rows.append((tot, s, len(g), wr, avg, tot, pct))
for row in sorted(strat_rows, reverse=True):
    _, s, n, wr, avg, tot, pct = row
    print(f'  {s:<15} {n:>6} {wr:>6.1f} {avg:>+8.1f} {tot:>+9.0f} {pct:>6.1f}%')

# 2. By regime
print()
print('BY REGIME')
print(f'  {"Regime":<10} {"Trades":>6} {"WR%":>6} {"Total$":>9}')
print('  ' + '-'*36)
for r, g in df.groupby('hmm_state'):
    print(f'  {r:<10} {len(g):>6} {g["win"].mean()*100:>6.1f} {g["net_pnl"].sum():>+9.0f}')

# 3. By year
print()
print('BY YEAR')
print(f'  {"Year":<6} {"Trades":>6} {"WR%":>6} {"Total$":>9} {"Return%":>8}')
print('  ' + '-'*42)
for yr, g in df.groupby('year'):
    ret = g['net_pnl'].sum() / 50000 * 100
    print(f'  {yr:<6} {len(g):>6} {g["win"].mean()*100:>6.1f} {g["net_pnl"].sum():>+9.0f} {ret:>7.1f}%')

# 4. Exit reasons
print()
print('EXIT REASONS')
print(f'  {"Reason":<18} {"Trades":>6} {"WR%":>6} {"Avg$":>8} {"Total$":>9}')
print('  ' + '-'*52)
for r, g in df.groupby('exit_reason'):
    print(f'  {r:<18} {len(g):>6} {g["win"].mean()*100:>6.1f} {g["net_pnl"].mean():>+8.1f} {g["net_pnl"].sum():>+9.0f}')

# 5. Hold time
print()
print('HOLD TIME')
day   = df[~df['is_swing']]
swing = df[df['is_swing']]
print(f'  Intraday : {len(day):>4}t  avg={day["hold_mins"].mean():.0f}min  WR={day["win"].mean()*100:.1f}%  P&L=${day["net_pnl"].sum():+,.0f}')
if len(swing):
    print(f'  Swing    : {len(swing):>4}t  avg={swing["hold_mins"].mean()/60:.1f}hr   WR={swing["win"].mean()*100:.1f}%  P&L=${swing["net_pnl"].sum():+,.0f}')

# 6. Direction
print()
print('DIRECTION')
for d, g in df.groupby('direction'):
    print(f'  {d:<6}  {len(g):>4}t  WR={g["win"].mean()*100:.1f}%  P&L=${g["net_pnl"].sum():+,.0f}')

# 7. Top / bottom tickers
print()
print('TOP 10 TICKERS BY P&L')
tk = df.groupby('ticker')['net_pnl'].sum().sort_values(ascending=False)
for t, p in tk.head(10).items():
    cnt = len(df[df['ticker'] == t])
    wr  = df[df['ticker'] == t]['win'].mean() * 100
    print(f'  {t:<6}  {cnt:>4}t  WR={wr:.0f}%  ${p:+,.0f}')
print('BOTTOM 5:')
for t, p in tk.tail(5).items():
    cnt = len(df[df['ticker'] == t])
    print(f'  {t:<6}  {cnt:>4}t  ${p:+,.0f}')

# 8. Monthly avg P&L
print()
print('MONTHLY AVG P&L (across 3 years)')
df['month'] = df['entry_time'].dt.month
monthly = df.groupby('month')['net_pnl'].sum() / 3
for m, p in monthly.items():
    bar = '#' * int(abs(p) / 80)
    sign = '+' if p >= 0 else ''
    print(f'  M{m:02d}  ${p:>+6.0f}  {bar}')

# 9. Daily PnL distribution
print()
print('DAILY P&L DISTRIBUTION')
df['date'] = df['entry_time'].dt.normalize()
daily = df.groupby('date')['net_pnl'].sum()
print(f'  Trading days with trades: {len(daily)}')
print(f'  Avg P&L/day : ${daily.mean():+.1f}')
print(f'  Std/day     : ${daily.std():.1f}')
print(f'  Max win/day : ${daily.max():+,.0f}')
print(f'  Max loss/day: ${daily.min():+,.0f}')
pos_days = (daily > 0).sum()
print(f'  Win days    : {pos_days}/{len(daily)} = {pos_days/len(daily)*100:.1f}%')

# 10. Max drawdown (simple)
cum = daily.sort_index().cumsum()
running_max = cum.cummax()
dd = cum - running_max
print(f'  Max DD      : ${dd.min():+,.0f}  ({dd.min()/50000*100:.1f}%)')

# 11. Concentration risk
print()
print('CONCENTRATION RISK')
top5_strat = df.groupby('strategy')['net_pnl'].sum().sort_values(ascending=False).head(1)
for s, v in top5_strat.items():
    print(f'  Top strategy: {s} = {v/total_pnl*100:.1f}% of P&L')
top5_tk = tk.head(5).sum()
print(f'  Top 5 tickers: {top5_tk/total_pnl*100:.1f}% of P&L')
top1_tk = tk.head(1)
for t, v in top1_tk.items():
    print(f'  Top ticker  : {t} = {v/total_pnl*100:.1f}% of P&L')

# 12. PDT check (day trades per week)
print()
print('PDT / TRADE FREQUENCY')
df['week'] = df['entry_time'].dt.isocalendar().week.astype(int)
df['yw']   = df['entry_time'].dt.year * 100 + df['week']
day_trades = df[~df['is_swing']].copy()
dt_per_week = day_trades.groupby('yw').apply(lambda g: g.groupby('ticker').size().gt(0).sum())
print(f'  Day trades/week: avg={dt_per_week.mean():.1f}  max={dt_per_week.max()}')
print(f'  (PDT limit = 3/week for accounts < $25k)')
print(f'  Swing trades: {len(swing)}t over 3yr = {len(swing)/156:.1f}/week')
