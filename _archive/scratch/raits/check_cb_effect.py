"""Check if STRESS_ORB_STK losses trigger CB that blocks TREND_FOLLOW."""
import pickle, sys, pandas as pd
sys.path.insert(0,'..')

BASE = 'data/cache/snapshots/results_20260620_163631.pkl'
NEW  = 'data/cache/snapshots/results_20260621_072434.pkl'

def get_trades(results, strat=None):
    rows = []
    for w in results:
        for t in w.get('trades',[]):
            if strat and t.strategy != strat: continue
            dt = pd.to_datetime(t.entry_time)
            rows.append(dict(strategy=t.strategy, day=dt.normalize(),
                             exit_reason=t.exit_reason, pnl=t.net_pnl or 0))
    return pd.DataFrame(rows)

with open(BASE,'rb') as f: b=pickle.load(f)
with open(NEW, 'rb') as f: n=pickle.load(f)

# TREND_FOLLOW per day comparison
tf_b = get_trades(b,'TREND_FOLLOW').groupby('day')['pnl'].sum().rename('base')
tf_n = get_trades(n,'TREND_FOLLOW').groupby('day')['pnl'].sum().rename('new')
stk  = get_trades(n,'STRESS_ORB_STK')

tf_cmp = pd.concat([tf_b, tf_n], axis=1).fillna(0)
tf_cmp['delta'] = tf_cmp['new'] - tf_cmp['base']

# Days where TF got worse
worse = tf_cmp[tf_cmp['delta'] < -100].sort_values('delta')
print(f"Days where TREND_FOLLOW degraded > $100: {len(worse)}")
print(f"\n{'Day':<12} {'Base TF':>9} {'New TF':>9} {'Delta':>9} {'STK trades'}")
print('-'*55)
for day, row in worse.iterrows():
    stk_day = stk[stk['day']==day]
    stk_pnl = stk_day['pnl'].sum()
    stk_cb  = (stk_day['exit_reason']=='CIRCUIT_BREAKER').sum()
    print(f"{str(day.date()):<12} {row['base']:>+9,.0f} {row['new']:>+9,.0f} {row['delta']:>+9,.0f}  "
          f"STK={len(stk_day)}t pnl={stk_pnl:+.0f} CB={stk_cb}")

# CIRCUIT_BREAKER exits in STK
stk_cb = stk[stk['exit_reason']=='CIRCUIT_BREAKER']
print(f"\nSTRESS_ORB_STK CIRCUIT_BREAKER exits: {len(stk_cb)}t  P&L={stk_cb['pnl'].sum():+,.0f}")

# Days where TF disappeared (base had TF, new doesn't)
tf_lost = tf_cmp[(tf_cmp['base'] != 0) & (tf_cmp['new'] == 0)]
print(f"\nDays where TF completely disappeared (base had trades, new=0): {len(tf_lost)}")
for day, row in tf_lost.iterrows():
    stk_day = stk[stk['day']==day]
    print(f"  {str(day.date())}  base={row['base']:+.0f}  STK={len(stk_day)}t pnl={stk_day['pnl'].sum():+.0f}")
