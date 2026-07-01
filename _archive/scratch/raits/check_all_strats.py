"""Compare all strategy stats between baseline vs new snapshot."""
import pickle, sys, pandas as pd
sys.path.insert(0,'..')

BASE = 'data/cache/snapshots/results_20260620_163631.pkl'  # pre-STK baseline
NEW  = 'data/cache/window_debug_results.pkl'              # current run (STK fix)

def summary(results):
    d = {}
    for w in results:
        for t in w.get('trades',[]):
            s = t.strategy
            if s not in d: d[s] = {'n':0,'pnl':0.0,'wins':0}
            d[s]['n'] += 1
            d[s]['pnl'] += t.net_pnl or 0
            if (t.net_pnl or 0) > 0: d[s]['wins'] += 1
    return d

with open(BASE,'rb') as f: b=pickle.load(f)
with open(NEW, 'rb') as f: n=pickle.load(f)
sb=summary(b); sn=summary(n)

strats = sorted(set(sb)|set(sn))
print(f"\n  {'Strategy':<16} {'Base_n':>7} {'New_n':>7} {'Δn':>5} {'Base P&L':>10} {'New P&L':>10} {'ΔP&L':>10}")
print(f"  {'-'*68}")
for s in strats:
    bn = sb[s]['n'] if s in sb else 0
    nn = sn[s]['n'] if s in sn else 0
    bp = sb[s]['pnl'] if s in sb else 0
    np_ = sn[s]['pnl'] if s in sn else 0
    flag = ' <--' if abs(nn-bn) > 5 or abs(np_-bp) > 300 else ''
    print(f"  {s:<16} {bn:>7} {nn:>7} {nn-bn:>+5} {bp:>+10,.0f} {np_:>+10,.0f} {np_-bp:>+10,.0f}{flag}")
print(f"  {'-'*68}")
tb=sum(v['pnl'] for v in sb.values()); tn=sum(v['pnl'] for v in sn.values())
print(f"  {'TOTAL':<16} {sum(v['n'] for v in sb.values()):>7} {sum(v['n'] for v in sn.values()):>7} {'':>5} {tb:>+10,.0f} {tn:>+10,.0f} {tn-tb:>+10,.0f}")
