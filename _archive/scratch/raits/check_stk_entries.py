"""Compare STRESS_ORB_STK entry times between 9:40 and 9:35 snapshots."""
import pickle, sys, pandas as pd
sys.path.insert(0,'..')

OLD = 'data/cache/snapshots/results_20260621_072434.pkl'
NEW = 'data/cache/snapshots/results_20260621_130451.pkl'

def get_stk(results):
    rows = []
    for w in results:
        for t in w.get('trades',[]):
            if t.strategy != 'STRESS_ORB_STK': continue
            et = pd.to_datetime(t.entry_time)
            rows.append(dict(day=et.normalize(), entry_t=et.time(),
                             ticker=t.ticker, pnl=t.net_pnl or 0,
                             reason=t.exit_reason))
    return pd.DataFrame(rows)

with open(OLD,'rb') as f: o=pickle.load(f)
with open(NEW,'rb') as f: n=pickle.load(f)

so = get_stk(o)
sn = get_stk(n)

print(f"OLD (9:40): {len(so)}t  P&L={so['pnl'].sum():+,.0f}")
print(f"NEW (9:35): {len(sn)}t  P&L={sn['pnl'].sum():+,.0f}")

print(f"\nOLD entry time distribution:")
print(so['entry_t'].value_counts().sort_index())

print(f"\nNEW entry time distribution:")
print(sn['entry_t'].value_counts().sort_index())
