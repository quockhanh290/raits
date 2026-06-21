"""
stress_orb_stocks_analysis.py — Examine điểm 1 (exit time) và điểm 3 (concentration).

Point 1: 196/200 exits là TIME_STOP → target 2R quá xa. Test exit times khác.
Point 3: Top-3 = 55% of P&L. Check year × ticker để xem có consistent không.
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

OR_END=dtime(9,35); SIGNAL_START=dtime(9,35); SIGNAL_END=dtime(10,15)
MIN_GAP_PCT=0.015; ATR_MULT_STOP=0.5; TARGET_R=2.0; MAX_SLOTS=3

EXIT_TIMES_TO_TEST = [dtime(10,15), dtime(10,30), dtime(11,0), dtime(13,30)]

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

# Build base trades (entry + full forward bars saved)
print("Building trade entries...")
base_entries = []
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
        entry_found=False
        for bar_ts,bar in sig_bars.iterrows():
            if float(bar["low"])<or_low and float(bar["close"])<or_low:
                entry_px=float(bar["close"]); stop_px=or_high+ATR_MULT_STOP*atr
                stop_dist=stop_px-entry_px
                if stop_dist<=0: continue
                target_px=entry_px-TARGET_R*stop_dist
                shares=max(1,int(500/stop_dist))
                fwd=all_day[all_day.index>bar_ts]
                base_entries.append(dict(
                    ticker=ticker, day=day, year=str(day.year),
                    bar_ts=bar_ts, entry_px=entry_px,
                    stop_px=stop_px, target_px=target_px,
                    shares=shares, fwd=fwd,
                ))
                entered.add(ticker); slots+=1; entry_found=True; break
        if entry_found: break

def sim_exit(entry, exit_time):
    fwd = entry["fwd"]
    fwd_w = fwd[fwd.index.time <= exit_time]
    exit_px = entry["entry_px"]; reason = "TIME_STOP"
    for _, b in fwd_w.iterrows():
        if float(b["high"]) >= entry["stop_px"]:
            exit_px = entry["stop_px"]; reason = "STOP_HIT"; break
        if float(b["low"]) <= entry["target_px"]:
            exit_px = entry["target_px"]; reason = "TARGET_HIT"; break
        exit_px = float(b["close"])
    s = entry["shares"]
    net_pnl = (entry["entry_px"] - exit_px) * s - s * 0.01 * 2
    return dict(**{k: v for k, v in entry.items() if k != "fwd"},
                exit_px=exit_px, reason=reason, net_pnl=net_pnl, win=net_pnl > 0)

print(f"\n{'='*60}")
print(f"  POINT 1 — EXIT TIME COMPARISON")
print(f"{'='*60}")
print(f"  {'Exit':>7} {'N':>5} {'P&L':>9} {'WR':>5} {'STOP':>6} {'TARGET':>7} {'p-val':>7}")

all_results = {}
for exit_t in EXIT_TIMES_TO_TEST:
    trades = [sim_exit(e, exit_t) for e in base_entries]
    df = pd.DataFrame(trades)
    total = df["net_pnl"].sum()
    wr    = df["win"].mean()*100
    n_stop   = (df["reason"]=="STOP_HIT").sum()
    n_target = (df["reason"]=="TARGET_HIT").sum()
    outcomes = df["net_pnl"].values
    rng = np.random.default_rng(42)
    boot = np.array([rng.choice(outcomes,size=len(outcomes),replace=True).sum() for _ in range(10_000)])
    p = (boot<=0).mean()
    print(f"  {str(exit_t):>7} {len(df):>5} {total:>+9,.0f} {wr:>4.0f}% {n_stop:>6} {n_target:>7} {p:>7.3f}")
    all_results[exit_t] = df

# Detail by year for each exit time
print(f"\n  By year:")
print(f"  {'Exit':>7} {'2020':>10} {'2021':>10} {'2022':>10}")
for exit_t, df in all_results.items():
    row = []
    for yr in ["2020","2021","2022"]:
        y = df[df["year"]==yr]
        row.append(f"{y['net_pnl'].sum():>+7,.0f}" if len(y) else "        -")
    print(f"  {str(exit_t):>7} {'  '.join(row)}")

print(f"\n{'='*60}")
print(f"  POINT 3 — TICKER CONCENTRATION BY YEAR")
print(f"{'='*60}")

# Use baseline exit (10:15)
df_base = all_results[dtime(10,15)]
total = df_base["net_pnl"].sum()

tk_yr = df_base.groupby(["ticker","year"])["net_pnl"].sum().unstack(fill_value=0)
tk_total = df_base.groupby("ticker")["net_pnl"].agg(n="count", total="sum")
tk_combined = tk_total.join(tk_yr).sort_values("total", ascending=False)

print(f"\n  {'Ticker':<8} {'N':>4} {'Total':>9}  {'2020':>8} {'2021':>8} {'2022':>8}  Consistent?")
for tk, row in tk_combined.iterrows():
    y20 = row.get("2020", 0); y21 = row.get("2021", 0); y22 = row.get("2022", 0)
    active = sum([y20 != 0, y21 != 0, y22 != 0])
    pos = sum([y20 > 0, y21 > 0, y22 > 0])
    consistent = "✓" if (active >= 2 and pos >= active*0.5) else "✗" if active >= 2 else "-"
    print(f"  {tk:<8} {int(row['n']):>4} {row['total']:>+9,.0f}  {y20:>+8,.0f} {y21:>+8,.0f} {y22:>+8,.0f}  {consistent}")

# Top-3 without META/XOM/AAPL
top3 = tk_combined["total"].head(3).sum()
print(f"\n  Top-3 P&L: {top3:+,.0f} = {top3/total*100:.0f}% of total {total:+,.0f}")
print(f"  Are top-3 consistent across years? (see ✓ above)")

# Bootstrap per year
print(f"\n{'='*60}")
print(f"  BOOTSTRAP PER YEAR")
print(f"{'='*60}")
for yr in ["2020","2021","2022"]:
    y = df_base[df_base["year"]==yr]
    if len(y) < 5:
        print(f"  {yr}: too few trades"); continue
    outcomes = y["net_pnl"].values
    rng = np.random.default_rng(42)
    boot = np.array([rng.choice(outcomes,size=len(outcomes),replace=True).sum() for _ in range(10_000)])
    p = (boot<=0).mean()
    ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
    print(f"  {yr}: {len(y)}t  P&L={y['net_pnl'].sum():+,.0f}  p={p:.3f}  CI=[{ci_lo:+,.0f},{ci_hi:+,.0f}]")
