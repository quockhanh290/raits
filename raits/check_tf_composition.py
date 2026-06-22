"""Find TF trades that differ between baseline and new snapshot."""
import pickle, sys, pandas as pd
sys.path.insert(0,'..')

BASE = 'data/cache/snapshots/results_20260620_163631.pkl'
NEW  = 'data/cache/snapshots/results_20260621_072434.pkl'

with open(BASE,'rb') as f: b=pickle.load(f)
with open(NEW, 'rb') as f: n=pickle.load(f)

def get_tf(results):
    rows = []
    for w in results:
        for t in w.get('trades',[]):
            if t.strategy != 'TREND_FOLLOW': continue
            dt = pd.to_datetime(t.entry_time)
            rows.append(dict(
                key=f"{dt.date()}_{t.ticker}_{t.direction}",
                day=dt.normalize(), ticker=t.ticker,
                direction=t.direction, hmm=t.hmm_state,
                pnl=t.net_pnl or 0, reason=t.exit_reason,
                shares=getattr(t,'shares',None),
            ))
    return pd.DataFrame(rows)

tb = get_tf(b)
tn = get_tf(n)

# Trades only in baseline
keys_b = set(tb['key']); keys_n = set(tn['key'])
only_b = tb[tb['key'].isin(keys_b - keys_n)].sort_values('pnl', ascending=False)
only_n = tn[tn['key'].isin(keys_n - keys_b)].sort_values('pnl', ascending=False)

print(f"TF trades ONLY in baseline: {len(only_b)}  P&L={only_b['pnl'].sum():+,.0f}")
print(f"TF trades ONLY in new:      {len(only_n)}  P&L={only_n['pnl'].sum():+,.0f}")
print(f"TF trades in BOTH:          {len(keys_b & keys_n)}")
print(f"Baseline total: {len(tb)}  New total: {len(tn)}")

print(f"\n--- Only in BASELINE (missing in new) ---")
print(f"{'Day':<12} {'Ticker':<6} {'Dir':<6} {'HMM':<8} {'Shares':>7} {'P&L':>8} {'Reason'}")
print('-'*65)
for _, r in only_b.iterrows():
    print(f"{str(r['day'].date()):<12} {r['ticker']:<6} {r['direction']:<6} {r['hmm']:<8} {str(r['shares']):>7} {r['pnl']:>+8,.0f} {r['reason']}")

print(f"\n--- Only in NEW (not in baseline) ---")
print(f"{'Day':<12} {'Ticker':<6} {'Dir':<6} {'HMM':<8} {'Shares':>7} {'P&L':>8} {'Reason'}")
print('-'*65)
for _, r in only_n.iterrows():
    print(f"{str(r['day'].date()):<12} {r['ticker']:<6} {r['direction']:<6} {r['hmm']:<8} {str(r['shares']):>7} {r['pnl']:>+8,.0f} {r['reason']}")
