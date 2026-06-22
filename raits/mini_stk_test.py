"""
Simulate engine 7f + 7g for 2022-01-18 using the EXACT same data/paths as the engine.
"""
import sys, os, pickle
sys.path.insert(0, '..')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'raits', 'scripts'))

import pandas as pd
from datetime import time as dtime

# Load market data via the same function window_debug uses
from window_debug import fetch_market_data

UNIVERSE = [
    "TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL",
    "INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
    "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX","CSCO","GS","CRM","JPM",
    "MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM",
    "SPY","QQQ","IWM",
]
ETFs = ["SPY","QQQ","IWM"]
ORB_SCAN_TIME = dtime(9, 35)
SIGNAL_START  = dtime(9, 35)
ORB_SIGNAL_END = dtime(10, 15)
MIN_GAP = 0.015
ATR_MULT = 1.0
DAY = pd.Timestamp("2022-01-18")

print("Loading market data...")
market_data = fetch_market_data(UNIVERSE, force_cache=True)
print(f"Loaded {len(market_data)} tickers")

# Build day_stocks (same as engine)
day_spy = market_data["SPY"][market_data["SPY"].index.normalize() == DAY] if "SPY" in market_data else pd.DataFrame()
print(f"day_spy: {len(day_spy)} bars, cols={list(day_spy.columns)}")

day_stocks = {tk: market_data[tk][market_data[tk].index.normalize() == DAY]
              for tk in market_data if tk != "SPY"}

# _stress_stocks (same as engine)
_stress_stocks = {"SPY": day_spy}
for etf in ("QQQ","IWM"):
    if etf in day_stocks and not day_stocks[etf].empty:
        _stress_stocks[etf] = day_stocks[etf]
print(f"_stress_stocks: {list(_stress_stocks.keys())}")

# Compute ATR
def compute_atr(bars):
    if len(bars) < 2:
        return float(bars["close"].iloc[-1]) * 0.015
    hl = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"] - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(14).mean())

# Simulate bar loop — only bar_t == 9:35 matters for 7f
bar_ts = day_spy.index[day_spy.index.time == ORB_SCAN_TIME][0]
print(f"\n=== Simulating bar_ts={bar_ts} ===")

# 7f: build _stk_etf_or_ranges
_stk_etf_or_ranges = {}
for etf in ETFs:
    _src = _stress_stocks if etf in _stress_stocks else day_stocks
    if etf not in _src: continue
    _etf_ob = _src[etf]
    _etf_ob = _etf_ob[_etf_ob.index.time < ORB_SCAN_TIME]
    if _etf_ob.empty: continue
    _stk_etf_or_ranges[etf] = (float(_etf_ob["high"].max()), float(_etf_ob["low"].min()))
print(f"_stk_etf_or_ranges: {_stk_etf_or_ranges}")

# 7f: stock scan
_stress_stk_or_ranges = {}
for stk in [tk for tk in UNIVERSE if tk not in ETFs]:
    if stk not in day_stocks: continue
    _stk_bars = day_stocks[stk][day_stocks[stk].index <= bar_ts]
    if _stk_bars.empty: continue
    try:
        _stk_open_bar = _stk_bars[_stk_bars.index.time >= dtime(9,30)]
        if _stk_open_bar.empty: continue
        _stk_open = float(_stk_open_bar.iloc[0]["open"])
        prev = market_data[stk][market_data[stk].index.normalize() < DAY]
        if prev.empty: continue
        _stk_prev_c = float(prev["close"].iloc[-1])
        if _stk_prev_c <= 0: continue
        if (_stk_open - _stk_prev_c) / _stk_prev_c >= -MIN_GAP: continue
        _or_bars = _stk_bars[_stk_bars.index.time < ORB_SCAN_TIME]
        if _or_bars.empty: continue
        or_h = float(_or_bars["high"].max())
        or_l = float(_or_bars["low"].min())
        or_range = or_h - or_l
        if or_range <= 0: continue
        atr = compute_atr(_or_bars)
        if atr <= 0: continue
        if or_range < 0.5 * atr or or_range > 5 * atr: continue
        _stress_stk_or_ranges[stk] = (or_h, or_l, atr)
    except Exception as e:
        print(f"  scan error {stk}: {e}")
print(f"_stress_stk_or_ranges: {list(_stress_stk_or_ranges.keys())}")

# 7g: simulate bar by bar
print(f"\n{'Bar':<10} {'Conf':<6} {'Stk':<6} {'close':>8} {'low':>8} {'or_l':>8} {'signal'}")
print("-"*55)
for sig_bar_ts in day_spy[day_spy.index.time >= SIGNAL_START].index:
    if sig_bar_ts.time() > ORB_SIGNAL_END: break

    # co-confirm
    _etf_confirmed = False
    for etf, (or_h, or_l) in _stk_etf_or_ranges.items():
        _src = _stress_stocks if etf in _stress_stocks else day_stocks
        if etf not in _src: continue
        _cf_bars = _src[etf].loc[:sig_bar_ts]
        if _cf_bars.empty: continue
        cur_low = float(_cf_bars.iloc[-1]["low"])
        if cur_low < or_l:
            _etf_confirmed = True
            break

    for stk, (or_h, or_l, satr) in _stress_stk_or_ranges.items():
        if stk not in day_stocks: continue
        _stk_bars = day_stocks[stk].loc[:sig_bar_ts]
        if _stk_bars.empty: continue
        _close = float(_stk_bars.iloc[-1]["close"])
        _low   = float(_stk_bars.iloc[-1]["low"])
        signal = _etf_confirmed and _low < or_l and _close < or_l
        if signal or stk in ("TSLA","MS","GS"):
            print(f"{str(sig_bar_ts.time()):<10} {'Y' if _etf_confirmed else 'N':<6} {stk:<6} {_close:>8.2f} {_low:>8.2f} {or_l:>8.2f} {'SIGNAL' if signal else '-'}")
    if _etf_confirmed:
        print()
