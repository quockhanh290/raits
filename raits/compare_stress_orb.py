import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pickle
from collections import defaultdict

with open('data/cache/snapshots/results_20260620_163631.pkl','rb') as f: old=pickle.load(f)
with open('data/cache/snapshots/results_20260620_220350.pkl','rb') as f: new=pickle.load(f)

def by_strat(results):
    d=defaultdict(float)
    for w in results:
        for t in w.get('trades',[]):
            pnl = getattr(t,'net_pnl', getattr(t,'pnl', getattr(t,'profit',0)))
            d[t.strategy]+=pnl
    return d

o,n=by_strat(old),by_strat(new)
strats=sorted(set(list(o)+list(n)))
print(f"  {'Strategy':<14} {'Old':>9} {'New':>9} {'Delta':>9}")
print(f"  {'-'*44}")
for s in strats:
    delta=n[s]-o[s]
    print(f"  {s:<14} {o[s]:>+9,.0f} {n[s]:>+9,.0f} {delta:>+9,.0f}")
print(f"  {'-'*44}")
total_o=sum(o.values()); total_n=sum(n.values())
print(f"  {'TOTAL':<14} {total_o:>+9,.0f} {total_n:>+9,.0f} {total_n-total_o:>+9,.0f}")
