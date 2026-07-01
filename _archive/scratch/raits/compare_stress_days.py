"""
So sánh stress_days extracted từ baseline snapshot vs kết quả mới.
Sau đó chạy sim với từng bộ stress_days để isolate ảnh hưởng.
"""
import pickle, sys, pandas as pd
sys.path.insert(0,'..')
from datetime import time as dtime

BASE_SNAP = 'data/cache/snapshots/results_20260620_163631.pkl'  # $14,932 baseline
NEW_SNAP  = 'data/cache/snapshots/results_20260621_063557.pkl'  # với STRESS_ORB_STK

def get_stress_days(results):
    days = set()
    for w in results:
        for t in w.get('trades', []):
            if getattr(t, 'hmm_state', '') == 'Stress':
                days.add(pd.to_datetime(t.entry_time).normalize())
    return sorted(days)

with open(BASE_SNAP, 'rb') as f: base = pickle.load(f)
with open(NEW_SNAP,  'rb') as f: new  = pickle.load(f)

base_days = get_stress_days(base)
new_days  = get_stress_days(new)

base_set = set(base_days)
new_set  = set(new_days)

print(f"Baseline stress days: {len(base_days)}")
print(f"New (w/ STK) stress days: {len(new_days)}")
print(f"Days only in baseline: {sorted(base_set - new_set)}")
print(f"Days only in new:      {sorted(new_set - base_set)}")

# Run sim với cả 2 bộ days để thấy impact
PKL_5MIN = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
with open(PKL_5MIN, 'rb') as f: data_5min = pickle.load(f)
for tk in data_5min: data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

UNIVERSE = ["TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL",
            "INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
            "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX","CSCO","GS","CRM","JPM",
            "MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM"]
STOCK_UNIVERSE = [tk for tk in UNIVERSE if tk in data_5min]

OR_END=dtime(9,35); SIGNAL_START=dtime(9,35); SIGNAL_END=dtime(10,15)
EXIT_TIME=dtime(10,15); MIN_GAP_PCT=0.015; ATR_MULT=0.5; MAX_SLOTS=3

def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1]) * 0.015
    hl=bars["high"]-bars["low"]
    hpc=(bars["high"]-bars["close"].shift(1)).abs()
    lpc=(bars["low"]-bars["close"].shift(1)).abs()
    return float(pd.concat([hl,hpc,lpc],axis=1).max(axis=1).tail(period).mean())

# Build caches once
all_days = sorted(base_set | new_set)
prev_close_map = {}; day_bars_cache = {}
for ticker in STOCK_UNIVERSE:
    bars = data_5min[ticker].sort_index()
    bars_d = bars.copy(); bars_d["date"] = bars_d.index.normalize()
    daily_last = bars_d.groupby("date")["close"].last()
    dates = daily_last.index.tolist()
    for i in range(1, len(dates)):
        prev_close_map[(ticker, dates[i])] = float(daily_last.iloc[i-1])
    for day in all_days:
        db = bars[bars.index.normalize() == day]
        if len(db) >= 4: day_bars_cache[(ticker, day)] = db

def run_sim(stress_days, label):
    trades = []
    for day in stress_days:
        slots = 0; entered = set()
        for ticker in STOCK_UNIVERSE:
            if slots >= MAX_SLOTS: break
            if ticker in entered: continue
            all_day = day_bars_cache.get((ticker, day))
            if all_day is None: continue
            prev_c = prev_close_map.get((ticker, day))
            if prev_c is None: continue
            first_bar = all_day[all_day.index.time >= dtime(9,30)]
            if first_bar.empty: continue
            gap_pct = (float(first_bar.iloc[0]["open"]) - prev_c) / prev_c
            if gap_pct >= -MIN_GAP_PCT: continue
            or_bars = all_day[all_day.index.time < OR_END]
            if len(or_bars) < 1: continue
            or_high = float(or_bars["high"].max()); or_low = float(or_bars["low"].min())
            or_range = or_high - or_low
            if or_range <= 0: continue
            atr = compute_atr(or_bars)
            if atr > 0 and (or_range < 0.5*atr or or_range > 5*atr): continue
            sig_bars = all_day[(all_day.index.time>=SIGNAL_START)&(all_day.index.time<=SIGNAL_END)]
            if sig_bars.empty: continue
            for bar_ts, bar in sig_bars.iterrows():
                bar_c=float(bar["close"]); bar_l=float(bar["low"])
                if bar_l < or_low and bar_c < or_low:
                    stop_px = or_high + ATR_MULT*atr; stop_dist = stop_px - bar_c
                    if stop_dist <= 0: continue
                    target_px = bar_c - 2.0*stop_dist; shares = max(1, int(500/stop_dist))
                    fwd = all_day[(all_day.index>bar_ts)&(all_day.index.time<=EXIT_TIME)]
                    exit_px = bar_c; reason = "TIME_STOP"
                    for _, b in fwd.iterrows():
                        bh=float(b["high"]); bl=float(b["low"]); bc=float(b["close"])
                        if bh >= stop_px: exit_px=stop_px; reason="STOP_HIT"; break
                        if bl <= target_px: exit_px=target_px; reason="TARGET_HIT"; break
                        exit_px = bc
                    net_pnl = (bar_c - exit_px)*shares - shares*0.01*2
                    trades.append(dict(year=str(day.year), reason=reason, net_pnl=net_pnl))
                    entered.add(ticker); slots += 1; break

    df = pd.DataFrame(trades) if trades else pd.DataFrame(columns=['year','reason','net_pnl'])
    total = df['net_pnl'].sum() if len(df) else 0
    wr = (df['net_pnl'] > 0).mean()*100 if len(df) else 0
    print(f"\n[{label}] {len(stress_days)} stress days → {len(df)}t  P&L={total:+,.0f}  WR={wr:.0f}%")
    for yr in ['2020','2021','2022']:
        y = df[df['year']==yr]
        if len(y): print(f"  {yr}: {len(y)}t  {y['net_pnl'].sum():+,.0f}")
    by_r = df.groupby('reason')['net_pnl'].agg(n='count', total='sum')
    for r, row in by_r.iterrows():
        print(f"  {r}: {int(row['n'])}t  {row['total']:+,.0f}")

print()
run_sim(base_days, "BASELINE stress_days")
run_sim(new_days,  "NEW stress_days (w/ STK)")

# Days chỉ có trong baseline — chạy riêng
only_base = sorted(base_set - new_set)
only_new  = sorted(new_set - base_set)
if only_base: run_sim(only_base, f"Days ONLY in baseline ({len(only_base)}d)")
if only_new:  run_sim(only_new,  f"Days ONLY in new ({len(only_new)}d)")
