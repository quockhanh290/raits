"""Trace TF trades on specific days between baseline vs new snapshot."""
import pickle, sys, pandas as pd
sys.path.insert(0,'..')

BASE = 'data/cache/snapshots/results_20260620_163631.pkl'
NEW  = 'data/cache/snapshots/results_20260621_072434.pkl'

TARGET_DAYS = [
    '2022-11-01', '2021-12-13', '2021-12-30', '2020-10-09',
    '2021-12-06', '2022-05-03', '2022-02-28',
]

COLS = ['strategy','ticker','direction','hmm','entry_px','exit_px','shares','exit_reason','pnl']

with open(BASE,'rb') as f: b=pickle.load(f)
with open(NEW, 'rb') as f: n=pickle.load(f)

def get_day_trades(results, day_str):
    day = pd.Timestamp(day_str)
    rows = []
    for w in results:
        for t in w.get('trades',[]):
            dt = pd.to_datetime(t.entry_time).normalize()
            if dt != day: continue
            rows.append(dict(
                strategy=t.strategy, ticker=t.ticker,
                direction=t.direction, hmm=t.hmm_state,
                entry_px=t.entry_price, exit_px=t.exit_price,
                shares=getattr(t,'shares',None),
                exit_reason=t.exit_reason, pnl=t.net_pnl or 0,
            ))
    return pd.DataFrame(rows, columns=COLS) if rows else pd.DataFrame(columns=COLS)

for day in TARGET_DAYS:
    db = get_day_trades(b, day)
    dn = get_day_trades(n, day)
    tf_b = db[db['strategy']=='TREND_FOLLOW']
    tf_n = dn[dn['strategy']=='TREND_FOLLOW']
    stk_n = dn[dn['strategy']=='STRESS_ORB_STK']

    if tf_b.empty and tf_n.empty: continue

    print(f"\n{'='*60}")
    print(f"  {day}")
    print(f"  Baseline TF: {len(tf_b)}t  P&L={tf_b['pnl'].sum():+.0f}")
    print(f"  New TF:      {len(tf_n)}t  P&L={tf_n['pnl'].sum():+.0f}")
    print(f"  New STK:     {len(stk_n)}t  P&L={stk_n['pnl'].sum():+.0f}")

    if not tf_b.empty:
        print(f"\n  Baseline TF trades:")
        for _, r in tf_b.iterrows():
            sh = f"shares={r['shares']}" if r['shares'] else ""
            print(f"    {r['ticker']} {r['direction']} px={r['entry_px']:.2f} {sh} reason={r['exit_reason']} pnl={r['pnl']:+.0f}")

    if not tf_n.empty:
        print(f"\n  New TF trades:")
        for _, r in tf_n.iterrows():
            sh = f"shares={r['shares']}" if r['shares'] else ""
            print(f"    {r['ticker']} {r['direction']} px={r['entry_px']:.2f} {sh} reason={r['exit_reason']} pnl={r['pnl']:+.0f}")

    if not dn.empty:
        print(f"\n  All new engine trades that day:")
        for _, r in dn.iterrows():
            print(f"    {r['strategy']:<16} {r['ticker']:<6} {r['direction']} hmm={r['hmm']} pnl={r['pnl']:+.0f} reason={r['exit_reason']}")
