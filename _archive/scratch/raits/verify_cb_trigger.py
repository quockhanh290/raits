"""
Trace the exact CB trigger sequence on days where TF was blocked in new engine
but NOT blocked in baseline. Goal: confirm STK caused CB vs. other reasons.
"""
import pickle, sys, pandas as pd
sys.path.insert(0,'..')

BASE = 'data/cache/snapshots/results_20260620_163631.pkl'
NEW  = 'data/cache/snapshots/results_20260621_072434.pkl'

# Days where TF trade is in baseline but not new, and CB may have fired
# Focus on confirmed: 2021-12-13 (CB exits visible), and sample others
TARGET_DAYS = [
    '2021-12-13',
    '2022-11-01',
    '2022-02-28',
    '2021-01-27',
    '2022-05-03',
    '2021-12-06',
    '2021-12-30',
    '2020-10-09',
]

with open(BASE,'rb') as f: b=pickle.load(f)
with open(NEW, 'rb') as f: n=pickle.load(f)

def get_day_all(results, day_str):
    day = pd.Timestamp(day_str)
    rows = []
    for w in results:
        for t in w.get('trades',[]):
            et = pd.to_datetime(t.entry_time)
            xt = pd.to_datetime(t.exit_time) if t.exit_time else None
            if et.normalize() != day: continue
            rows.append(dict(
                strategy=t.strategy, ticker=t.ticker,
                direction=t.direction, hmm=t.hmm_state,
                entry_t=et.time(), exit_t=xt.time() if xt else None,
                pnl=t.net_pnl or 0, reason=t.exit_reason,
            ))
    # Sort by exit time to get chronological CB sequence
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values('exit_t')
    return df

for day in TARGET_DAYS:
    db = get_day_all(b, day)
    dn = get_day_all(n, day)

    tf_b = db[db['strategy']=='TREND_FOLLOW'] if not db.empty else pd.DataFrame()
    tf_n = dn[dn['strategy']=='TREND_FOLLOW'] if not dn.empty else pd.DataFrame()
    cb_in_new = dn[dn['reason']=='CIRCUIT_BREAKER'] if not dn.empty else pd.DataFrame()

    has_interest = len(tf_b) > 0 and len(tf_n) == 0
    if not has_interest: continue

    print(f"\n{'='*65}")
    print(f"  {day}  | Base TF: {len(tf_b)}t {tf_b['pnl'].sum():+.0f}  | New TF: 0t")

    # Baseline: show all trades in chronological order
    if not db.empty:
        print(f"\n  [BASELINE] All trades (chronological):")
        running = 0
        consec_loss = 0
        for _, r in db.sort_values('exit_t').iterrows():
            running += r['pnl']
            if r['pnl'] < 0:
                consec_loss += 1
            else:
                consec_loss = 0
            print(f"    {str(r['exit_t']):<10} {r['strategy']:<16} {r['ticker']:<6} "
                  f"pnl={r['pnl']:>+7.0f}  cum={running:>+8.0f}  consec_loss={consec_loss}  reason={r['reason']}")

    # New engine: show all trades in chronological order + note CB
    if not dn.empty:
        print(f"\n  [NEW ENGINE] All trades (chronological):")
        running = 0
        consec_loss = 0
        for _, r in dn.sort_values('exit_t').iterrows():
            running += r['pnl']
            if r['pnl'] < 0:
                consec_loss += 1
            else:
                consec_loss = 0
            flag = ' <-- CB TRIGGER?' if r['reason'] == 'CIRCUIT_BREAKER' else ''
            print(f"    {str(r['exit_t']):<10} {r['strategy']:<16} {r['ticker']:<6} "
                  f"pnl={r['pnl']:>+7.0f}  cum={running:>+8.0f}  consec_loss={consec_loss}  reason={r['reason']}{flag}")
    else:
        print(f"\n  [NEW ENGINE] No trades at all on this day.")
