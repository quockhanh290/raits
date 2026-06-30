import sys; sys.path.insert(0, '.')
import pandas as pd, numpy as np
import gate2_edge_harness as G
from futures.swing_tf import SwingTFEngine, costs_for_basket, load_basket, basket_labels

dfs = load_basket(r'data\cache\futures')
labels = basket_labels('spy_daily.csv')
costs = costs_for_basket()
tf = SwingTFEngine().backtest_basket(dfs, labels, costs)

rows = [(pd.Timestamp(r['day']), r['pnl']) for trs in tf.values() for r in trs]
pnl = pd.DataFrame(rows, columns=['d', 'p']).groupby('d')['p'].sum()
spy = G.benchmark_daily('spy_daily.csv')
ret = spy.pct_change()
df = pd.DataFrame({'pnl': pnl, 'spy': ret}).dropna()

b, a = np.polyfit(df['spy'], df['pnl'], 1)
corr = df['pnl'].corr(df['spy'])
up = df[df.spy > 0].pnl.sum()
down = df[df.spy < 0].pnl.sum()

print('beta (P&L $ per 1%% SPY move): %.1f | corr %.3f' % (b, corr))
print('up-days   net: $%8.0f  (%d days)' % (up, (df.spy > 0).sum()))
print('down-days net: $%8.0f  (%d days)' % (down, (df.spy < 0).sum()))
print('ratio down/total: %.0f%%' % (100 * down / (up + down)))
