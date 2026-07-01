import pickle, sys, pandas as pd
sys.path.insert(0,'..')

SNAP  = 'data/cache/snapshots/results_20260621_063557.pkl'
BASE  = 'data/cache/snapshots/results_20260620_163631.pkl'

def extract(results):
    rows=[]
    for w in results:
        for t in w.get('trades',[]):
            dt=pd.to_datetime(t.entry_time)
            rows.append(dict(
                strategy=t.strategy, ticker=t.ticker,
                year=str(dt.year), entry_time=dt,
                exit_reason=t.exit_reason,
                net_pnl=t.net_pnl or 0.0,
                is_etf=t.ticker in {'SPY','QQQ','IWM'},
            ))
    return pd.DataFrame(rows)

with open(BASE,'rb') as f: b=pickle.load(f)
with open(SNAP,'rb') as f: n=pickle.load(f)
df_b=extract(b); df_n=extract(n)

# ── Total P&L comparison ───────────────────────────────────────
def by_strat(df):
    return df.groupby('strategy')['net_pnl'].agg(n='count',total='sum')

bb=by_strat(df_b); nb=by_strat(df_n)
strats=sorted(set(bb.index)|set(nb.index))
print(f"\n  {'Strategy':<16} {'Base n':>7} {'Base P&L':>10} {'New n':>7} {'New P&L':>10} {'Delta':>10}")
print(f"  {'-'*62}")
for s in strats:
    bn=int(bb.loc[s,'n']) if s in bb.index else 0
    bp=bb.loc[s,'total'] if s in bb.index else 0
    nn=int(nb.loc[s,'n']) if s in nb.index else 0
    np_=nb.loc[s,'total'] if s in nb.index else 0
    print(f"  {s:<16} {bn:>7} {bp:>+10,.0f} {nn:>7} {np_:>+10,.0f} {np_-bp:>+10,.0f}")
print(f"  {'-'*62}")
tb=df_b['net_pnl'].sum(); tn=df_n['net_pnl'].sum()
print(f"  {'TOTAL':<16} {len(df_b):>7} {tb:>+10,.0f} {len(df_n):>7} {tn:>+10,.0f} {tn-tb:>+10,.0f}")

# ── STRESS_ORB_STK detail ──────────────────────────────────────
stk=df_n[df_n['strategy']=='STRESS_ORB_STK'].copy()
print(f"\n  STRESS_ORB_STK: {len(stk)}t  P&L={stk['net_pnl'].sum():+,.0f}  WR={stk['net_pnl'].gt(0).mean()*100:.0f}%")
for yr in ['2020','2021','2022']:
    y=stk[stk['year']==yr]
    if len(y): print(f"    {yr}: {len(y):3}t  P&L={y['net_pnl'].sum():+8,.0f}  WR={y['net_pnl'].gt(0).mean()*100:.0f}%")
by_r=stk.groupby('exit_reason')['net_pnl'].agg(n='count',total='sum')
print()
for r,row in by_r.iterrows():
    print(f"    {r:<16}: {int(row['n'])}t  {row['total']:+,.0f}")

# Check ETF slot integrity
etf_sorb=df_n[(df_n['strategy']=='STRESS_ORB')&(~df_n['is_etf'])]
print(f"\n  Non-ETF under STRESS_ORB slot: {len(etf_sorb)}t  (should be 0)")
