"""Deep dive: STRESS_ORB_STK in new engine — trace entry time, stop dist, target dist."""
import pickle, sys, pandas as pd
sys.path.insert(0,'..')

SNAP = 'data/cache/snapshots/results_20260621_063557.pkl'
with open(SNAP,'rb') as f: r=pickle.load(f)

rows=[]
for w in r:
    for t in w.get('trades',[]):
        if t.strategy != 'STRESS_ORB_STK': continue
        edt = pd.to_datetime(t.entry_time)
        xdt = pd.to_datetime(t.exit_time) if t.exit_time else None
        stop_dist = abs((t.stop or 0) - t.entry_price) if t.stop else None
        target_dist = abs((t.target or 0) - t.entry_price) if t.target else None
        rows.append(dict(
            year=str(edt.year), ticker=t.ticker,
            entry_time=edt, entry_min=edt.hour*60+edt.minute,
            exit_reason=t.exit_reason,
            entry_px=t.entry_price, stop=t.stop, target=t.target,
            stop_dist=stop_dist, target_dist=target_dist,
            net_pnl=t.net_pnl or 0.0,
            win=(t.net_pnl or 0) > 0,
        ))

df = pd.DataFrame(rows)
print(f"\nSTRESS_ORB_STK: {len(df)}t  P&L={df['net_pnl'].sum():+,.0f}  WR={df['win'].mean()*100:.0f}%")

# ── Entry time ────────────────────────────────────────────────────────
print(f"\nEntry time distribution:")
by_min = df.groupby('entry_min').agg(n=('net_pnl','count'), total=('net_pnl','sum'),
    wr=('win','mean')).reset_index()
by_min['time'] = by_min['entry_min'].map(lambda m: f"{m//60:02d}:{m%60:02d}")
print(f"  {'Time':<6} {'n':>5} {'P&L':>9} {'WR%':>6}")
for _, row in by_min.iterrows():
    print(f"  {row['time']:<6} {int(row['n']):>5} {row['total']:>+9,.0f} {row['wr']*100:>5.0f}%")

# ── Stop/target distances ─────────────────────────────────────────────
print(f"\nStop dist (OR_high+1.0×ATR - entry):")
print(f"  min={df['stop_dist'].min():.2f}  median={df['stop_dist'].median():.2f}  "
      f"mean={df['stop_dist'].mean():.2f}  max={df['stop_dist'].max():.2f}")
print(f"  stop_dist as % of entry: mean={( df['stop_dist']/df['entry_px']*100).mean():.2f}%")

print(f"\nTarget dist (2R below entry):")
print(f"  min={df['target_dist'].min():.2f}  median={df['target_dist'].median():.2f}  "
      f"mean={df['target_dist'].mean():.2f}  max={df['target_dist'].max():.2f}")
print(f"  target_dist as % of entry: mean={(df['target_dist']/df['entry_px']*100).mean():.2f}%")

# ── Exit reasons by year ──────────────────────────────────────────────
print(f"\nExit reasons by year:")
pvt = df.groupby(['year','exit_reason'])['net_pnl'].agg(n='count',total='sum').unstack(fill_value=0)
print(pvt.to_string())

# ── TIME_STOP breakdown ───────────────────────────────────────────────
ts = df[df['exit_reason']=='TIME_STOP']
print(f"\nTIME_STOP {len(ts)}t  P&L={ts['net_pnl'].sum():+,.0f}  WR={ts['win'].mean()*100:.0f}%")
print(f"  avg pnl per TIME_STOP: {ts['net_pnl'].mean():+.2f}")

# Top losing tickers
by_tk = df.groupby('ticker')['net_pnl'].agg(n='count',total='sum').sort_values('total')
print(f"\nBottom 10 tickers by P&L:")
print(by_tk.head(10).to_string())

# ── Sim entry time comparison (run sim's own logic quickly) ──────────
print(f"\n{'─'*50}")
print("Loading sim data for entry-time breakdown comparison...")
try:
    PKL_5MIN = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
    with open(PKL_5MIN,'rb') as f: data_5min = pickle.load(f)
    for tk in data_5min: data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

    PKL_RESULTS = r'd:\raits\raits\data\cache\window_debug_results.pkl'
    with open(PKL_RESULTS,'rb') as f: results = pickle.load(f)
    stress_days = sorted(set(
        pd.to_datetime(t.entry_time).normalize()
        for w in results for t in w.get('trades',[])
        if getattr(t,'hmm_state','')=='Stress'
    ))

    from datetime import time as dtime
    import numpy as np
    UNIVERSE = ["TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL",
                "INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
                "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX","CSCO","GS","CRM","JPM",
                "MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM"]
    STOCK_UNIVERSE = [tk for tk in UNIVERSE if tk in data_5min]

    OR_END=dtime(9,35); SIGNAL_START=dtime(9,35); SIGNAL_END=dtime(10,15)
    EXIT_TIME=dtime(10,15); MIN_GAP_PCT=0.015; ATR_MULT=0.5; TARGET_R=2.0; MAX_SLOTS=3

    def compute_atr(bars, period=14):
        if len(bars)<2: return float(bars["close"].iloc[-1])*0.015
        hl=bars["high"]-bars["low"]
        hpc=(bars["high"]-bars["close"].shift(1)).abs()
        lpc=(bars["low"]-bars["close"].shift(1)).abs()
        return float(pd.concat([hl,hpc,lpc],axis=1).max(axis=1).tail(period).mean())

    prev_close_map={}; day_bars_cache={}
    for ticker in STOCK_UNIVERSE:
        bars=data_5min[ticker].sort_index()
        bars_d=bars.copy(); bars_d["date"]=bars_d.index.normalize()
        daily_last=bars_d.groupby("date")["close"].last(); dates=daily_last.index.tolist()
        for i in range(1,len(dates)): prev_close_map[(ticker,dates[i])]=float(daily_last.iloc[i-1])
        for day in stress_days:
            db=bars[bars.index.normalize()==day]
            if len(db)>=4: day_bars_cache[(ticker,day)]=db

    sim_trades=[]
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
            for bar_ts,bar in sig_bars.iterrows():
                bar_c=float(bar["close"]); bar_l=float(bar["low"])
                if bar_l<or_low and bar_c<or_low:
                    entry_min=bar_ts.hour*60+bar_ts.minute
                    stop_px=or_high+ATR_MULT*atr; stop_dist=stop_px-bar_c
                    if stop_dist<=0: continue
                    target_px=bar_c-TARGET_R*stop_dist; shares=max(1,int(500/stop_dist))
                    fwd=all_day[(all_day.index>bar_ts)&(all_day.index.time<=EXIT_TIME)]
                    exit_px=bar_c; reason="TIME_STOP"
                    for _,b in fwd.iterrows():
                        bh=float(b["high"]); bl=float(b["low"]); bc=float(b["close"])
                        if bh>=stop_px: exit_px=stop_px; reason="STOP_HIT"; break
                        if bl<=target_px: exit_px=target_px; reason="TARGET_HIT"; break
                        exit_px=bc
                    s=shares; net_pnl=(bar_c-exit_px)*s-s*0.01*2
                    sim_trades.append(dict(ticker=ticker,day=day,year=str(day.year),
                        entry_min=entry_min,reason=reason,net_pnl=net_pnl,win=net_pnl>0,
                        stop_dist=stop_dist))
                    entered.add(ticker); slots+=1; break

    sdf=pd.DataFrame(sim_trades)
    print(f"\nSim: {len(sdf)}t  P&L={sdf['net_pnl'].sum():+,.0f}  WR={sdf['win'].mean()*100:.0f}%")
    by_min2=sdf.groupby('entry_min').agg(n=('net_pnl','count'),total=('net_pnl','sum'),wr=('win','mean')).reset_index()
    by_min2['time']=by_min2['entry_min'].map(lambda m:f"{m//60:02d}:{m%60:02d}")
    print(f"\nSim entry time breakdown:")
    print(f"  {'Time':<6} {'n':>5} {'P&L':>9} {'WR%':>6}")
    for _,row in by_min2.iterrows():
        print(f"  {row['time']:<6} {int(row['n']):>5} {row['total']:>+9,.0f} {row['wr']*100:>5.0f}%")

    s935=sdf[sdf['entry_min']==9*60+35]; s940=sdf[sdf['entry_min']>=9*60+40]
    print(f"\nSim 9:35: {len(s935)}t P&L={s935['net_pnl'].sum():+,.0f} WR={s935['win'].mean()*100:.0f}%")
    print(f"Sim 9:40+: {len(s940)}t P&L={s940['net_pnl'].sum():+,.0f} WR={s940['win'].mean()*100:.0f}%")
except Exception as e:
    print(f"Sim load failed: {e}")
