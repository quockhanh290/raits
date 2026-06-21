"""
stress_orb_stocks_2021.py — Investigate 2021 failure in STRESS ORB individual stocks.
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\window_debug_results.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

with open(PKL_RESULTS, "rb") as f: results = pickle.load(f)
with open(PKL_5MIN,    "rb") as f: data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

stress_days = set()
for w in results:
    for t in w.get("trades", []):
        if getattr(t, "hmm_state", "") == "Stress":
            stress_days.add(pd.to_datetime(t.entry_time).normalize())
stress_days = sorted(stress_days)

UNIVERSE = ["TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL"]
PHASE1   = ["INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
            "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX","CSCO","GS","CRM","JPM"]
PHASE2   = ["MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM"]
STOCK_UNIVERSE = [tk for tk in UNIVERSE+PHASE1+PHASE2 if tk in data_5min]

OR_END=dtime(9,35); SIGNAL_START=dtime(9,35); SIGNAL_END=dtime(10,15); EXIT_TIME=dtime(10,15)
MIN_GAP_PCT=0.015; ATR_MULT_STOP=0.5; TARGET_R=2.0; MAX_SLOTS=3

def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1])*0.015
    hl=(bars["high"]-bars["low"]); hpc=(bars["high"]-bars["close"].shift(1)).abs()
    lpc=(bars["low"]-bars["close"].shift(1)).abs()
    return float(pd.concat([hl,hpc,lpc],axis=1).max(axis=1).tail(period).mean())

prev_close_map={}; day_bars_cache={}
for ticker in STOCK_UNIVERSE:
    bars=data_5min[ticker].sort_index(); bars_d=bars.copy(); bars_d["date"]=bars_d.index.normalize()
    daily_last=bars_d.groupby("date")["close"].last(); dates=daily_last.index.tolist()
    for i in range(1,len(dates)):
        prev_close_map[(ticker,dates[i])]=float(daily_last.iloc[i-1])
    for day in stress_days:
        db=bars[bars.index.normalize()==day]
        if len(db)>=4: day_bars_cache[(ticker,day)]=db

trades=[]
for day in stress_days:
    slots=0; entered=set()
    for ticker in STOCK_UNIVERSE:
        if slots>=MAX_SLOTS: break
        if ticker in entered: continue
        all_day=day_bars_cache.get((ticker,day))
        if all_day is None: continue
        prev_c=prev_close_map.get((ticker,day))
        if prev_c is None: continue
        first_bar=all_day[all_day.index.time>=dtime(9,30)]
        if first_bar.empty: continue
        session_open=float(first_bar.iloc[0]["open"])
        gap_pct=(session_open-prev_c)/prev_c
        if gap_pct>=-MIN_GAP_PCT: continue
        or_bars=all_day[all_day.index.time<OR_END]
        if len(or_bars)<1: continue
        or_high=float(or_bars["high"].max()); or_low=float(or_bars["low"].min())
        or_range=or_high-or_low
        if or_range<=0: continue
        atr=compute_atr(or_bars)
        if atr>0 and (or_range<0.5*atr or or_range>5*atr): continue
        sig_bars=all_day[(all_day.index.time>=SIGNAL_START)&(all_day.index.time<=SIGNAL_END)]
        if sig_bars.empty: continue
        trade=None
        for bar_ts,bar in sig_bars.iterrows():
            if float(bar["low"])<or_low and float(bar["close"])<or_low:
                entry_px=float(bar["close"]); stop_px=or_high+ATR_MULT_STOP*atr
                stop_dist=stop_px-entry_px
                if stop_dist<=0: continue
                target_px=entry_px-TARGET_R*stop_dist
                shares=max(1,int(500/stop_dist))
                trade=dict(ticker=ticker,day=day,year=str(day.year),bar_ts=bar_ts,
                           entry_px=entry_px,stop_px=stop_px,target_px=target_px,
                           gap_pct=round(gap_pct*100,2),shares=shares,
                           entry_time=bar_ts.strftime("%H:%M"),or_range=round(or_range,3),
                           atr=round(atr,3)); break
        if trade is None: continue
        fwd=all_day[(all_day.index>trade["bar_ts"])&(all_day.index.time<=EXIT_TIME)]
        exit_px=trade["entry_px"]; reason="TIME_STOP"
        for _,b in fwd.iterrows():
            if float(b["high"])>=trade["stop_px"]: exit_px=trade["stop_px"]; reason="STOP_HIT"; break
            if float(b["low"])<=trade["target_px"]: exit_px=trade["target_px"]; reason="TARGET_HIT"; break
            exit_px=float(b["close"])
        s=trade["shares"]
        net_pnl=(trade["entry_px"]-exit_px)*s-s*0.01*2
        trade.update(exit_px=exit_px,reason=reason,net_pnl=net_pnl,win=net_pnl>0,
                     exit_px_chg=round((exit_px-trade["entry_px"])/trade["entry_px"]*100,3))
        trades.append(trade); entered.add(ticker); slots+=1

df=pd.DataFrame(trades)

print(f"\n{'='*60}")
print(f"  2021 STRESS ORB STOCKS — DEEP DIVE")
print(f"{'='*60}")

df21=df[df["year"]=="2021"].copy()
print(f"\n  2021: {len(df21)}t  P&L={df21['net_pnl'].sum():+,.0f}  WR={df21['win'].mean()*100:.0f}%")

# Month breakdown in 2021
df21["month"]=df21["day"].dt.strftime("%Y-%m")
by_month=df21.groupby("month")["net_pnl"].agg(n="count",total="sum",wr=lambda x:(x>0).mean()*100)
print(f"\n── 2021 by month ────────────────────────────────────────")
for m,row in by_month.iterrows():
    if row.n>0: print(f"  {m}: {int(row.n):>3}t  {row.total:>+7,.0f}  WR={row.wr:.0f}%")

# Ticker breakdown 2021
print(f"\n── 2021 by ticker ───────────────────────────────────────")
tk21=df21.groupby("ticker")["net_pnl"].agg(n="count",total="sum").sort_values("total",ascending=False)
for tk,row in tk21.iterrows():
    print(f"  {tk:<8} {int(row.n):>3}t  {row.total:>+7,.0f}")

# Compare 2021 vs 2020/2022 gap characteristics
print(f"\n── Gap size comparison ──────────────────────────────────")
for yr in ["2020","2021","2022"]:
    y=df[df["year"]==yr]
    if len(y):
        print(f"  {yr}: avg_gap={y['gap_pct'].mean():.2f}%  avg_or_range={y['or_range'].mean():.3f}  avg_atr={y['atr'].mean():.3f}")

# Exit price change distribution
print(f"\n── Exit move (entry→exit) by year ───────────────────────")
for yr in ["2020","2021","2022"]:
    y=df[df["year"]==yr]
    if len(y):
        wins=y[y["win"]]; losses=y[~y["win"]]
        print(f"  {yr}: avg_move={y['exit_px_chg'].mean():.3f}%  win_move={wins['exit_px_chg'].mean() if len(wins) else 0:.3f}%  loss_move={losses['exit_px_chg'].mean() if len(losses) else 0:.3f}%")

# 2021 individual trade list (losses)
print(f"\n── 2021 losing trades ───────────────────────────────────")
losses21=df21[~df21["win"]].sort_values("net_pnl")
print(f"  {'Date':<12} {'Ticker':<8} {'Entry':>7} {'Exit':>7} {'Gap%':>6} {'P&L':>8} {'Reason'}")
for _,r in losses21.iterrows():
    print(f"  {str(r['day'].date()):<12} {r['ticker']:<8} {r['entry_px']:>7.2f} {r['exit_px']:>7.2f} {r['gap_pct']:>5.1f}% {r['net_pnl']:>+8.0f} {r['reason']}")

# SPY context on 2021 stress days
print(f"\n── Stress day count by year ─────────────────────────────")
for yr in ["2020","2021","2022"]:
    days=df[df["year"]==yr]["day"].nunique()
    t=len(df[df["year"]==yr])
    print(f"  {yr}: {days} stress days, {t} trades (avg {t/days:.1f}t/day)")
