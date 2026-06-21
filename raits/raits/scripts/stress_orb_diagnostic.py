"""
stress_orb_diagnostic.py — Analyze STRESS_ORB performance breakdown.

Usage:
    python D:\raits\raits\raits\scripts\stress_orb_diagnostic.py
"""
import sys, pickle
sys.path.insert(0, r'd:\raits\raits')
sys.path.insert(0, r'd:\raits')
import pandas as pd
import numpy as np

PKL = r'd:\raits\raits\data\cache\snapshots\results_20260620_163631.pkl'

with open(PKL, 'rb') as f: results = pickle.load(f)

rows = []
for w in results:
    for t in w.get('trades', []):
        if getattr(t, 'strategy', '') != 'STRESS_ORB':
            continue
        entry = pd.to_datetime(t.entry_time)
        exit_ = pd.to_datetime(t.exit_time)
        rows.append(dict(
            ticker    = getattr(t, 'ticker', '?'),
            year      = str(entry.year),
            direction = getattr(t, 'direction', '?'),
            entry_h   = entry.hour,
            entry_t   = entry.strftime('%H:%M'),
            duration  = round((exit_ - entry).total_seconds() / 60, 1),
            pnl       = t.net_pnl,
            win       = t.net_pnl > 0,
            exit_reason = getattr(t, 'exit_reason', '?'),
        ))

if not rows:
    print("No STRESS_ORB trades found"); sys.exit()

df = pd.DataFrame(rows)

print(f"\n{'='*60}")
print(f"  STRESS_ORB DIAGNOSTIC — {len(df)} trades")
print(f"{'='*60}")

# Overall
total = df['pnl'].sum()
wr = df['win'].mean() * 100
print(f"\n  Total: {len(df)}t  P&L={total:+,.0f}  WR={wr:.0f}%  avg={df['pnl'].mean():+.1f}/trade")

# By year
print(f"\n── By year ──────────────────────────────────────────────")
for yr in ['2020','2021','2022']:
    y = df[df['year']==yr]
    if len(y):
        print(f"  {yr}: {len(y):3}t  P&L={y['pnl'].sum():+7,.0f}  WR={y['win'].mean()*100:.0f}%  avg={y['pnl'].mean():+.1f}")

# By direction
print(f"\n── By direction ─────────────────────────────────────────")
for d in ['LONG','SHORT']:
    s = df[df['direction']==d]
    if len(s):
        print(f"  {d:<6}: {len(s):3}t  P&L={s['pnl'].sum():+7,.0f}  WR={s['win'].mean()*100:.0f}%  avg={s['pnl'].mean():+.1f}")

# By year × direction
print(f"\n── By year × direction ──────────────────────────────────")
for yr in ['2020','2021','2022']:
    for d in ['LONG','SHORT']:
        s = df[(df['year']==yr) & (df['direction']==d)]
        if len(s):
            print(f"  {yr} {d:<6}: {len(s):3}t  P&L={s['pnl'].sum():+7,.0f}  WR={s['win'].mean()*100:.0f}%  avg={s['pnl'].mean():+.1f}")

# By ticker
print(f"\n── By ticker ────────────────────────────────────────────")
tk = df.groupby('ticker')['pnl'].agg(n='count', total='sum', wr=lambda x:(x>0).mean()*100)
tk = tk.sort_values('total', ascending=False)
print(f"  {'Ticker':<8} {'N':>4} {'P&L':>8}  {'WR':>5}")
for tk_, r in tk.iterrows():
    print(f"  {tk_:<8} {int(r.n):>4} {r.total:>+8,.0f}  {r.wr:>4.0f}%")

# By entry time
print(f"\n── By entry time ────────────────────────────────────────")
by_t = df.groupby('entry_t')['pnl'].agg(n='count', total='sum', wr=lambda x:(x>0).mean()*100)
by_t = by_t.sort_index()
print(f"  {'Time':<8} {'N':>4} {'P&L':>8}  {'WR':>5}")
for t_, r in by_t.iterrows():
    print(f"  {t_:<8} {int(r.n):>4} {r.total:>+8,.0f}  {r.wr:>4.0f}%")

# By exit reason
print(f"\n── By exit reason ───────────────────────────────────────")
by_r = df.groupby('exit_reason')['pnl'].agg(n='count', total='sum')
for r_, row in by_r.iterrows():
    print(f"  {r_:<20}: {int(row.n):>3}t  {row.total:>+8,.0f}")

# Duration distribution
print(f"\n── Duration (minutes) ───────────────────────────────────")
bins = [0, 5, 15, 30, 60, 999]
labels = ['0-5m','5-15m','15-30m','30-60m','60m+']
df['dur_bin'] = pd.cut(df['duration'], bins=bins, labels=labels)
by_dur = df.groupby('dur_bin', observed=True)['pnl'].agg(n='count', total='sum', wr=lambda x:(x>0).mean()*100)
for d_, r in by_dur.iterrows():
    if r.n > 0:
        print(f"  {str(d_):<10} {int(r.n):>3}t  {r.total:>+8,.0f}  WR={r.wr:.0f}%")

# P&L distribution
print(f"\n── P&L distribution ─────────────────────────────────────")
print(f"  Min: {df['pnl'].min():+.0f}  Max: {df['pnl'].max():+.0f}")
print(f"  Median: {df['pnl'].median():+.0f}  Std: {df['pnl'].std():.0f}")
winners = df[df['win']]['pnl']
losers  = df[~df['win']]['pnl']
if len(winners): print(f"  Avg win:  {winners.mean():+.0f}  ({len(winners)} trades)")
if len(losers):  print(f"  Avg loss: {losers.mean():+.0f}  ({len(losers)} trades)")
if len(winners) and len(losers):
    print(f"  Win/loss ratio: {abs(winners.mean()/losers.mean()):.2f}")
