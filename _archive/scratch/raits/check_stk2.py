import pickle, sys, pandas as pd
sys.path.insert(0,'..')

SNAP = 'data/cache/snapshots/results_20260621_072434.pkl'
BASE = 'data/cache/snapshots/results_20260620_163631.pkl'

def summary(results):
    d = {}
    for w in results:
        for t in w.get('trades',[]):
            s = t.strategy
            if s not in d: d[s] = {'n':0,'pnl':0.0,'wins':0}
            d[s]['n'] += 1; d[s]['pnl'] += t.net_pnl or 0
            if (t.net_pnl or 0) > 0: d[s]['wins'] += 1
    return d

with open(BASE,'rb') as f: b=pickle.load(f)
with open(SNAP,'rb') as f: n=pickle.load(f)
sb=summary(b); sn=summary(n)

strats=sorted(set(sb)|set(sn))
print(f"\n  {'Strategy':<16} {'Base P&L':>10} {'New P&L':>10} {'Delta':>10}")
print(f"  {'-'*50}")
for s in strats:
    bp=sb[s]['pnl'] if s in sb else 0
    np_=sn[s]['pnl'] if s in sn else 0
    nn=sn[s]['n'] if s in sn else 0
    wr=sn[s]['wins']/nn*100 if nn else 0
    tag=f"  {nn}t WR={wr:.0f}%" if s=='STRESS_ORB_STK' else ''
    print(f"  {s:<16} {bp:>+10,.0f} {np_:>+10,.0f} {np_-bp:>+10,.0f}{tag}")
print(f"  {'-'*50}")
tb=sum(v['pnl'] for v in sb.values()); tn=sum(v['pnl'] for v in sn.values())
print(f"  {'TOTAL':<16} {tb:>+10,.0f} {tn:>+10,.0f} {tn-tb:>+10,.0f}")
