"""
stress_orb_combined_sim.py — STRESS_ORB với combined universe (ETF + stocks).

Thay vì 2 strategies song song, expand universe của STRESS_ORB:
  - ETFs (SPY/QQQ/IWM): không cần gap (giữ nguyên current behavior)
  - Stocks: gap down ≥1.5% (thêm mới)
  - MAX_SLOTS = 2 (giữ nguyên engine cap)
  - Ordering: ETFs trước, stocks sau (mirror engine iteration order)

So sánh 3 scenarios:
  A. Baseline: ETF only (current engine)
  B. Combined: ETF first, stocks fill remaining slots
  C. Stocks only: không có ETF (upper bound nếu stocks thay ETF)

Cũng test exit time từ stress_orb_stocks_analysis.
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
for tk in data_5min: data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

stress_days = set()
for w in results:
    for t in w.get("trades", []):
        if getattr(t, "hmm_state", "") == "Stress":
            stress_days.add(pd.to_datetime(t.entry_time).normalize())
stress_days = sorted(stress_days)
print(f"Stress days: {len(stress_days)}")

ETF_UNIVERSE   = ["SPY", "QQQ", "IWM"]
STOCK_UNIVERSE_RAW = ["TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL",
                      "INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
                      "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX","CSCO","GS","CRM","JPM",
                      "MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM"]
STOCK_UNIVERSE = [tk for tk in STOCK_UNIVERSE_RAW if tk in data_5min]
ALL_TICKERS    = ETF_UNIVERSE + STOCK_UNIVERSE

OR_END=dtime(9,35); SIGNAL_START=dtime(9,35); SIGNAL_END=dtime(10,15); EXIT_TIME=dtime(10,15)
MIN_GAP_PCT=0.015; ATR_MULT_STOP=0.5; TARGET_R=2.0; MAX_SLOTS=3

def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1])*0.015
    hl=(bars["high"]-bars["low"]); hpc=(bars["high"]-bars["close"].shift(1)).abs()
    lpc=(bars["low"]-bars["close"].shift(1)).abs()
    return float(pd.concat([hl,hpc,lpc],axis=1).max(axis=1).tail(period).mean())

print("Precomputing caches...")
prev_close_map={}; day_bars_cache={}
for ticker in ALL_TICKERS:
    if ticker not in data_5min: continue
    bars=data_5min[ticker].sort_index()
    bars_d=bars.copy(); bars_d["date"]=bars_d.index.normalize()
    daily_last=bars_d.groupby("date")["close"].last(); dates=daily_last.index.tolist()
    for i in range(1,len(dates)):
        prev_close_map[(ticker,dates[i])]=float(daily_last.iloc[i-1])
    for day in stress_days:
        db=bars[bars.index.normalize()==day]
        if len(db)>=4: day_bars_cache[(ticker,day)]=db

def try_entry(ticker, day, require_gap):
    all_day=day_bars_cache.get((ticker,day))
    if all_day is None: return None
    if ticker not in data_5min: return None

    first_bar=all_day[all_day.index.time>=dtime(9,30)]
    if first_bar.empty: return None
    session_open=float(first_bar.iloc[0]["open"])

    if require_gap:
        prev_c=prev_close_map.get((ticker,day))
        if prev_c is None: return None
        gap_pct=(session_open-prev_c)/prev_c
        if gap_pct>=-MIN_GAP_PCT: return None
    else:
        gap_pct=0.0

    or_bars=all_day[all_day.index.time<OR_END]
    if len(or_bars)<1: return None
    or_high=float(or_bars["high"].max()); or_low=float(or_bars["low"].min())
    or_range=or_high-or_low
    if or_range<=0: return None
    atr=compute_atr(or_bars)
    if atr>0 and (or_range<0.5*atr or or_range>5*atr): return None

    sig_bars=all_day[(all_day.index.time>=SIGNAL_START)&(all_day.index.time<=SIGNAL_END)]
    if sig_bars.empty: return None

    for bar_ts,bar in sig_bars.iterrows():
        bar_l=float(bar["low"]); bar_c=float(bar["close"])
        if bar_l<or_low and bar_c<or_low:
            entry_px=bar_c; stop_px=or_high+ATR_MULT_STOP*atr
            stop_dist=stop_px-entry_px
            if stop_dist<=0: continue
            target_px=entry_px-TARGET_R*stop_dist
            shares=max(1,int(500/stop_dist))
            fwd=all_day[(all_day.index>bar_ts)&(all_day.index.time<=EXIT_TIME)]
            exit_px=entry_px; reason="TIME_STOP"
            for _,b in fwd.iterrows():
                if float(b["high"])>=stop_px: exit_px=stop_px; reason="STOP_HIT"; break
                if float(b["low"])<=target_px: exit_px=target_px; reason="TARGET_HIT"; break
                exit_px=float(b["close"])
            s=shares
            net_pnl=(entry_px-exit_px)*s-s*0.01*2
            return dict(ticker=ticker,day=day,year=str(day.year),
                        entry_px=entry_px,stop_dist=stop_dist,shares=shares,
                        exit_px=exit_px,reason=reason,net_pnl=net_pnl,win=net_pnl>0,
                        gap_pct=round(gap_pct*100,2))
    return None

def run_scenario(label, ticker_order, require_gap_map):
    trades=[]
    for day in stress_days:
        slots=0; entered=set()
        for ticker in ticker_order:
            if slots>=MAX_SLOTS: break
            if ticker in entered: continue
            trade=try_entry(ticker, day, require_gap=require_gap_map.get(ticker,True))
            if trade is None: continue
            trades.append(trade); entered.add(ticker); slots+=1
    return trades

print("Running scenarios...")

# A: ETF only (baseline = current engine behavior, SHORT only)
trades_A = run_scenario("A_ETF_only",
    ticker_order=ETF_UNIVERSE,
    require_gap_map={tk: False for tk in ETF_UNIVERSE})

# B: ETF first, stocks fill remaining slots
trades_B = run_scenario("B_ETF_first_stocks_fill",
    ticker_order=ETF_UNIVERSE + STOCK_UNIVERSE,
    require_gap_map={**{tk: False for tk in ETF_UNIVERSE},
                     **{tk: True  for tk in STOCK_UNIVERSE}})

# C: Stocks only (no ETF)
trades_C = run_scenario("C_stocks_only",
    ticker_order=STOCK_UNIVERSE,
    require_gap_map={tk: True for tk in STOCK_UNIVERSE})

def show(label, trades):
    if not trades: print(f"  {label}: 0 trades"); return
    df=pd.DataFrame(trades)
    total=df["net_pnl"].sum(); wr=df["win"].mean()*100; avg=df["net_pnl"].mean()
    outcomes=df["net_pnl"].values
    rng=np.random.default_rng(42)
    boot=np.array([rng.choice(outcomes,size=len(outcomes),replace=True).sum() for _ in range(10_000)])
    p=(boot<=0).mean(); ci_lo,ci_hi=np.percentile(boot,[2.5,97.5])

    print(f"\n  [{label}]")
    print(f"  {len(df)}t  P&L={total:+,.0f}  WR={wr:.0f}%  avg={avg:+.1f}/trade")
    for yr in ["2020","2021","2022"]:
        y=df[df["year"]==yr]
        if len(y): print(f"    {yr}: {len(y):3}t  {y['net_pnl'].sum():>+8,.0f}  WR={y['win'].mean()*100:.0f}%")
    by_r=df.groupby("reason")["net_pnl"].agg(n="count",total="sum")
    for r_,row in by_r.iterrows():
        print(f"    {r_:<14}: {int(row.n):>3}t  {row.total:>+8,.0f}")
    print(f"  Bootstrap: p={p:.3f}  95%CI=[{ci_lo:+,.0f},{ci_hi:+,.0f}]  {'✓' if p<0.05 else '✗'}")

    # slot overlap analysis
    etf_trades = df[df["ticker"].isin(ETF_UNIVERSE)]
    stk_trades = df[df["ticker"].isin(STOCK_UNIVERSE)]
    if len(etf_trades) and len(stk_trades):
        print(f"  ETF: {len(etf_trades)}t {etf_trades['net_pnl'].sum():+,.0f}  |  Stocks: {len(stk_trades)}t {stk_trades['net_pnl'].sum():+,.0f}")

print(f"\n{'='*60}")
print(f"  STRESS_ORB COMBINED UNIVERSE SIM  (MAX_SLOTS={MAX_SLOTS})")
print(f"{'='*60}")
show("A: ETF only (current)", trades_A)
show("B: ETF first + stocks fill", trades_B)
show("C: Stocks only", trades_C)

# Slot competition analysis for scenario B
print(f"\n{'='*60}")
print(f"  SLOT OVERLAP ANALYSIS (Scenario B)")
print(f"{'='*60}")
df_B=pd.DataFrame(trades_B)
days_etf_took_both={} # days where ETFs used up all slots
for day in stress_days:
    day_trades=df_B[df_B["day"]==day]
    etf_n=len(day_trades[day_trades["ticker"].isin(ETF_UNIVERSE)])
    stk_n=len(day_trades[day_trades["ticker"].isin(STOCK_UNIVERSE)])
    if etf_n>=MAX_SLOTS:
        days_etf_took_both[day]=(etf_n,stk_n)
n_etf_full=len(days_etf_took_both)
print(f"\n  Days ETFs filled all {MAX_SLOTS} slots (stocks blocked): {n_etf_full}/{len(stress_days)}")
print(f"  Days with mixed ETF+stock: {len(df_B[df_B['ticker'].isin(ETF_UNIVERSE)]['day'].unique()) - n_etf_full}")

# On days stocks DID get in, what was their P&L?
stk_in_B=df_B[df_B["ticker"].isin(STOCK_UNIVERSE)]
etf_in_B=df_B[df_B["ticker"].isin(ETF_UNIVERSE)]
if len(stk_in_B):
    print(f"\n  Stocks that made it into B: {len(stk_in_B)}t  P&L={stk_in_B['net_pnl'].sum():+,.0f}  WR={stk_in_B['win'].mean()*100:.0f}%")
if len(etf_in_B):
    print(f"  ETFs in B:                  {len(etf_in_B)}t  P&L={etf_in_B['net_pnl'].sum():+,.0f}  WR={etf_in_B['win'].mean()*100:.0f}%")
