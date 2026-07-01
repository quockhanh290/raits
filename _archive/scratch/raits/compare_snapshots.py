import sys, pickle, pandas as pd
sys.path.insert(0, r'd:\raits\raits')
sys.path.insert(0, r'd:\raits')

base = pickle.load(open(r'd:\raits\raits\data\cache\snapshots\results_20260619_163041.pkl','rb'))
new  = pickle.load(open(r'd:\raits\raits\data\cache\snapshots\results_20260620_163631.pkl','rb'))

def extract(r):
    rows = []
    for w in r:
        for t in w.get('trades', []):
            rows.append({'strategy': getattr(t, 'strategy', '?'), 'pnl': t.net_pnl})
    return pd.DataFrame(rows)

b = extract(base).groupby('strategy')['pnl'].sum().rename('baseline')
n = extract(new).groupby('strategy')['pnl'].sum().rename('new')
cmp = pd.concat([b, n], axis=1).fillna(0)
cmp['delta'] = cmp['new'] - cmp['baseline']
cmp = cmp.sort_values('delta', ascending=False)
print(cmp.to_string())
total = cmp['delta'].sum()
print(f'\nTotal delta: {total:+,.0f}')
