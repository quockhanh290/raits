"""
Phân tích STRESS_ORB trades từ engine snapshot mới vs cũ.
Mục tiêu: hiểu tại sao engine 2022 WR=38.4% thay vì 55% như sim.
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pickle
import pandas as pd
from collections import defaultdict

OLD = 'data/cache/snapshots/results_20260620_163631.pkl'
NEW = 'data/cache/snapshots/results_20260620_220350.pkl'

with open(OLD,'rb') as f: old=pickle.load(f)
with open(NEW,'rb') as f: new=pickle.load(f)

ETF_UNIVERSE = {"SPY","QQQ","IWM"}

def extract_stress_orb(results):
    trades=[]
    for w in results:
        for t in w.get('trades',[]):
            if t.strategy=='STRESS_ORB':
                trades.append(dict(
                    ticker=t.ticker,
                    year=str(pd.to_datetime(t.entry_time).year),
                    entry_time=pd.to_datetime(t.entry_time),
                    exit_time=pd.to_datetime(t.exit_time),
                    direction=t.direction,
                    entry_px=t.entry_price,
                    exit_px=t.exit_price,
                    exit_reason=t.exit_reason,
                    net_pnl=t.net_pnl,
                    win=t.is_winner,
                    is_etf=t.ticker in ETF_UNIVERSE,
                    hmm=t.hmm_state,
                ))
    return pd.DataFrame(trades)

df_old = extract_stress_orb(old)
df_new = extract_stress_orb(new)

# Identify NEW trades (stocks added)
df_stocks = df_new[~df_new['is_etf']]
df_etf_new = df_new[df_new['is_etf']]

print(f"\n{'='*60}")
print(f"  STRESS_ORB ENGINE DIAGNOSTIC")
print(f"{'='*60}")

print(f"\n── Trade count comparison ───────────────────────────────")
print(f"  Old (ETF only): {len(df_old)}t")
print(f"  New total:      {len(df_new)}t  (+{len(df_new)-len(df_old)})")
print(f"    ETFs in new:  {len(df_etf_new)}t")
print(f"    Stocks added: {len(df_stocks)}t")

print(f"\n── Direction breakdown (new stocks) ─────────────────────")
if len(df_stocks):
    by_dir = df_stocks.groupby('direction')['net_pnl'].agg(n='count',total='sum',wr=lambda x:(x>0).mean()*100)
    for d,row in by_dir.iterrows():
        print(f"  {d}: {int(row.n)}t  P&L={row.total:+,.0f}  WR={row.wr:.0f}%")

print(f"\n── New stocks by year ───────────────────────────────────")
for yr in ['2020','2021','2022']:
    y = df_stocks[df_stocks['year']==yr]
    if len(y):
        print(f"  {yr}: {len(y):3}t  P&L={y['net_pnl'].sum():>+8,.0f}  WR={y['win'].mean()*100:.0f}%  "
              f"LONG={len(y[y['direction']=='LONG'])}  SHORT={len(y[y['direction']=='SHORT'])}")

print(f"\n── Exit reason breakdown (new stocks) ───────────────────")
if len(df_stocks):
    by_exit = df_stocks.groupby(['year','exit_reason'])['net_pnl'].agg(n='count',total='sum')
    for (yr,reason),row in by_exit.iterrows():
        print(f"  {yr} {reason:<18}: {int(row.n):>3}t  {row.total:>+8,.0f}")

print(f"\n── Entry time distribution (new stocks) ─────────────────")
if len(df_stocks):
    df_stocks = df_stocks.copy()
    df_stocks['entry_hm'] = df_stocks['entry_time'].dt.strftime('%H:%M')
    time_grp = df_stocks.groupby('entry_hm')['net_pnl'].agg(n='count',total='sum',wr=lambda x:(x>0).mean()*100)
    for t,row in time_grp.iterrows():
        print(f"  {t}: {int(row.n):>3}t  {row.total:>+8,.0f}  WR={row.wr:.0f}%")

print(f"\n── Top tickers (new stocks, all years) ──────────────────")
if len(df_stocks):
    tk = df_stocks.groupby('ticker')['net_pnl'].agg(n='count',total='sum',wr=lambda x:(x>0).mean()*100).sort_values('total',ascending=False)
    print(f"  {'Ticker':<8} {'N':>4} {'P&L':>9} {'WR':>5}")
    for ticker,row in tk.iterrows():
        print(f"  {ticker:<8} {int(row.n):>4} {row.total:>+9,.0f} {row.wr:>4.0f}%")

print(f"\n── 2022 losing stocks detail ────────────────────────────")
losses_2022 = df_stocks[(df_stocks['year']=='2022')&(~df_stocks['win'])].sort_values('net_pnl')
print(f"  {len(losses_2022)} losing trades in 2022 stocks")
print(f"  {'Ticker':<8} {'Dir':<6} {'Entry':>8} {'Exit':>8} {'Reason':<20} {'P&L':>8}")
for _,r in losses_2022.head(20).iterrows():
    print(f"  {r['ticker']:<8} {r['direction']:<6} {r['entry_px']:>8.2f} {r['exit_px']:>8.2f} {r['exit_reason']:<20} {r['net_pnl']:>+8.0f}")

print(f"\n── 2022 sim vs engine comparison ────────────────────────")
print(f"  Sim Scenario B: 135t 2022, WR=55%, P&L=+$3,601")
print(f"  Engine new:     {len(df_stocks[df_stocks['year']=='2022'])}t 2022, "
      f"WR={df_stocks[df_stocks['year']=='2022']['win'].mean()*100:.0f}%, "
      f"P&L={df_stocks[df_stocks['year']=='2022']['net_pnl'].sum():+,.0f}")
print(f"\n  Extra trades in engine vs sim: "
      f"{len(df_stocks[df_stocks['year']=='2022'])-135} extra")

print(f"\n── ETF trades: old vs new ───────────────────────────────")
print(f"  Old ETF: {len(df_old)}t  P&L={df_old['net_pnl'].sum():+,.0f}  WR={df_old['win'].mean()*100:.0f}%")
print(f"  New ETF: {len(df_etf_new)}t  P&L={df_etf_new['net_pnl'].sum():+,.0f}  WR={df_etf_new['win'].mean()*100:.0f}%")
