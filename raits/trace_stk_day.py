"""
Trace STRESS_ORB_STK logic for a single Stress day.
Shows exactly why 7f and 7g do / don't fire.
"""
import sys, pickle
import pandas as pd
from datetime import time as dtime

sys.path.insert(0, '..')

PKL_5MIN   = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
PKL_RESULTS = r'd:\raits\raits\data\cache\window_debug_results.pkl'

ORB_SCAN_TIME   = dtime(9, 35)
SIGNAL_START    = dtime(9, 35)
ORB_SIGNAL_END  = dtime(10, 15)
MIN_GAP         = 0.015
ETFs            = ["SPY", "QQQ", "IWM"]
UNIVERSE = [
    "TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL",
    "INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
    "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX","CSCO","GS","CRM","JPM",
    "MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM",
]

print("Loading data...")
with open(PKL_5MIN, "rb") as f:
    data = pickle.load(f)
for tk in data:
    data[tk].index = pd.to_datetime(data[tk].index)

with open(PKL_RESULTS, "rb") as f:
    results = pickle.load(f)

# Find Stress days
stress_days = set()
for w in results:
    for t in w.get("trades", []):
        if getattr(t, "hmm_state", "") == "Stress":
            stress_days.add(pd.to_datetime(t.entry_time).normalize())
stress_days = sorted(stress_days)
print(f"Stress days found: {len(stress_days)}")

def compute_atr(bars):
    if len(bars) < 2:
        return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(14).mean())

days_checked = 0
days_with_etf_ranges = 0
days_with_stk_scan = 0
days_with_coconfirm = 0
days_with_signal = 0

for day in stress_days[:50]:  # check first 50 stress days
    days_checked += 1

    # Build _stk_etf_or_ranges (9:30 bar only)
    stk_etf_or = {}
    for etf in ETFs:
        if etf not in data: continue
        db = data[etf]
        day_bars = db[db.index.normalize() == day]
        or_bars = day_bars[day_bars.index.time < ORB_SCAN_TIME]
        if or_bars.empty: continue
        stk_etf_or[etf] = (float(or_bars["high"].max()), float(or_bars["low"].min()))

    if not stk_etf_or:
        print(f"  {day.date()} - NO ETF OR ranges")
        continue
    days_with_etf_ranges += 1

    # Build _stress_stk_or_ranges (stock scan at 9:35)
    stk_or = {}
    for stk in UNIVERSE:
        if stk not in data: continue
        db = data[stk]
        day_bars = db[db.index.normalize() == day]
        bars_at_scan = day_bars[day_bars.index <= (day + pd.Timedelta(hours=9, minutes=35))]
        if bars_at_scan.empty: continue
        # prev close
        prev_bars = db[db.index.normalize() < day]
        if prev_bars.empty: continue
        prev_c = float(prev_bars["close"].iloc[-1])
        # open
        first = bars_at_scan[bars_at_scan.index.time >= dtime(9, 30)]
        if first.empty: continue
        stk_open = float(first.iloc[0]["open"])
        if (stk_open - prev_c) / prev_c >= -MIN_GAP: continue
        # OR bars
        or_bars = bars_at_scan[bars_at_scan.index.time < ORB_SCAN_TIME]
        if or_bars.empty: continue
        or_h = float(or_bars["high"].max())
        or_l = float(or_bars["low"].min())
        or_range = or_h - or_l
        if or_range <= 0: continue
        atr = compute_atr(or_bars)
        if atr <= 0: continue
        if or_range < 0.5 * atr or or_range > 5 * atr: continue
        stk_or[stk] = (or_h, or_l, atr)

    if not stk_or:
        continue
    days_with_stk_scan += 1

    # Check co-confirmation bar by bar
    coconf_fired = False
    coconf_bar   = None
    for etf, (or_h, or_l) in stk_etf_or.items():
        if etf not in data: continue
        etf_day = data[etf]
        etf_day = etf_day[etf_day.index.normalize() == day]
        sig_bars = etf_day[(etf_day.index.time >= SIGNAL_START) &
                           (etf_day.index.time <= ORB_SIGNAL_END)]
        for bar_ts, row in sig_bars.iterrows():
            bars_up_to = etf_day[etf_day.index <= bar_ts]
            cur_low = float(bars_up_to.iloc[-1]["low"])
            if cur_low < or_l:
                coconf_fired = True
                coconf_bar   = bar_ts
                break
        if coconf_fired: break

    if not coconf_fired:
        # Show ETF behavior to debug
        if days_with_stk_scan <= 5:
            for etf, (or_h, or_l) in stk_etf_or.items():
                if etf not in data: continue
                etf_day = data[etf][data[etf].index.normalize() == day]
                sig_bars = etf_day[(etf_day.index.time >= SIGNAL_START) &
                                   (etf_day.index.time <= ORB_SIGNAL_END)]
                print(f"  {day.date()} | {etf} OR_LOW={or_l:.2f} | bars: {[(str(b.name.time()), round(b['low'],2)) for _,b in sig_bars.iterrows()][:6]}")
        continue
    days_with_coconfirm += 1

    # Check if any stock fires signal at co-confirm bar
    for stk, (or_h, or_l, atr) in stk_or.items():
        if stk not in data: continue
        stk_day = data[stk][data[stk].index.normalize() == day]
        if coconf_bar not in stk_day.index: continue
        bar = stk_day.loc[coconf_bar]
        if float(bar["low"]) < or_l and float(bar["close"]) < or_l:
            days_with_signal += 1
            break

print(f"""
Summary (first 50 Stress days):
  Days checked:           {days_checked}
  Days with ETF OR ranges: {days_with_etf_ranges}
  Days with stock scan:   {days_with_stk_scan}
  Days with co-confirm:   {days_with_coconfirm}
  Days with signal:       {days_with_signal}
""")
