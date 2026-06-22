"""Check 2022-01-18: tại sao 13 stocks + co-confirm nhưng 0 trades."""
import sys, pickle
import pandas as pd
from datetime import time as dtime

sys.path.insert(0, '..')

PKL_5MIN = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
DAY = pd.Timestamp("2022-01-18")
ORB_SCAN = dtime(9, 35)
SIGNAL_END = dtime(10, 15)
MIN_GAP = 0.015
ETFs = ["SPY", "QQQ", "IWM"]
UNIVERSE = [
    "TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL",
    "INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
    "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX","CSCO","GS","CRM","JPM",
    "MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM",
]

with open(PKL_5MIN, "rb") as f:
    data = pickle.load(f)
for tk in data:
    data[tk].index = pd.to_datetime(data[tk].index)

def day_bars(tk):
    return data[tk][data[tk].index.normalize() == DAY] if tk in data else pd.DataFrame()

# ETF OR (9:30 bar only)
etf_or = {}
for etf in ETFs:
    db = day_bars(etf)
    ob = db[db.index.time < ORB_SCAN]
    if not ob.empty:
        etf_or[etf] = (float(ob["high"].max()), float(ob["low"].min()))
print(f"ETF OR ranges: {etf_or}")

# Stock scan
def compute_atr(bars):
    if len(bars) < 2:
        return float(bars["close"].iloc[-1]) * 0.015
    hl = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(14).mean())

stk_or = {}
for stk in UNIVERSE:
    if stk not in data: continue
    db = data[stk]
    prev = db[db.index.normalize() < DAY]
    if prev.empty: continue
    prev_c = float(prev["close"].iloc[-1])
    day_b = day_bars(stk)
    scan_b = day_b[day_b.index <= (DAY + pd.Timedelta(hours=9, minutes=35))]
    first = scan_b[scan_b.index.time >= dtime(9, 30)]
    if first.empty: continue
    op = float(first.iloc[0]["open"])
    if (op - prev_c) / prev_c >= -MIN_GAP: continue
    or_b = scan_b[scan_b.index.time < ORB_SCAN]
    if or_b.empty: continue
    or_h = float(or_b["high"].max())
    or_l = float(or_b["low"].min())
    atr = compute_atr(or_b)
    if atr > 0 and (or_h - or_l < 0.5 * atr or or_h - or_l > 5 * atr): continue
    stk_or[stk] = (or_h, or_l, atr)
print(f"\nStocks qualified: {list(stk_or.keys())}")

# Bar-by-bar signal check
print(f"\n{'Bar':<10} {'ETFconf':<9} {'Stk':<6} {'close':>8} {'low':>8} {'or_l':>8} {'break?'}")
print("-" * 60)
spy_day = day_bars("SPY")
for bar_ts in pd.date_range(DAY + pd.Timedelta(hours=9, minutes=35),
                            DAY + pd.Timedelta(hours=10, minutes=15), freq="5min"):
    # Co-confirm
    etf_ok = False
    for etf, (or_h, or_l) in etf_or.items():
        eb = day_bars(etf)
        eb = eb[eb.index <= bar_ts]
        if eb.empty: continue
        if float(eb.iloc[-1]["low"]) < or_l:
            etf_ok = True
            break

    if not etf_ok:
        print(f"{str(bar_ts.time()):<10} {'NO':<9}")
        continue

    for stk, (or_h, or_l, atr) in stk_or.items():
        db = day_bars(stk)
        sb = db[db.index <= bar_ts]
        if sb.empty: continue
        c = float(sb.iloc[-1]["close"])
        l = float(sb.iloc[-1]["low"])
        broke = l < or_l and c < or_l
        print(f"{str(bar_ts.time()):<10} {'YES':<9} {stk:<6} {c:>8.2f} {l:>8.2f} {or_l:>8.2f} {'SIGNAL' if broke else '-'}")
    print()
