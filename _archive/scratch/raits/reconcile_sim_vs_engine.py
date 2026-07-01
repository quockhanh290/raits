"""
Reconcile: tại sao sim +$5,581 mà engine regression?
Chạy sim với từng fix để isolate từng gap.
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\window_debug_results.pkl'
PKL_BASE    = r'd:\raits\raits\data\cache\snapshots\results_20260620_163631.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

print("Loading data...")
with open(PKL_RESULTS, "rb") as f: results_new = pickle.load(f)
with open(PKL_BASE, "rb") as f: results_base = pickle.load(f)
with open(PKL_5MIN, "rb") as f: data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

UNIVERSE = ["TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL"]
PHASE1   = ["INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
            "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX","CSCO","GS","CRM","JPM"]
PHASE2   = ["MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM"]
STOCK_UNIVERSE = [tk for tk in UNIVERSE+PHASE1+PHASE2 if tk in data_5min]
ETFs = ['SPY','QQQ','IWM']

def get_stress_days(results):
    days = set()
    for w in results:
        for t in w.get("trades", []):
            if getattr(t, "hmm_state", "") == "Stress":
                days.add(pd.to_datetime(t.entry_time).normalize())
    return sorted(days)

def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

def run_sim(stress_days, signal_start, atr_mult, use_coconfirm):
    """Run sim with configurable params. Returns (n_trades, total_pnl, wr)."""
    # Precompute ETF OR ranges
    etf_or_cache = {}
    for etf in ETFs:
        if etf not in data_5min: continue
        bars = data_5min[etf]
        for day in stress_days:
            db = bars[bars.index.normalize() == day]
            or_bars = db[db.index.time < dtime(9, 35)]
            if len(or_bars) < 1: continue
            etf_or_cache[(etf, day)] = (
                float(or_bars["high"].max()),
                float(or_bars["low"].min()),
            )

    # Precompute stock caches
    prev_close_map = {}
    day_bars_cache = {}
    for ticker in STOCK_UNIVERSE:
        bars = data_5min[ticker].sort_index()
        bars_d = bars.copy(); bars_d["date"] = bars_d.index.normalize()
        daily_last = bars_d.groupby("date")["close"].last()
        dates = daily_last.index.tolist()
        for i in range(1, len(dates)):
            prev_close_map[(ticker, dates[i])] = float(daily_last.iloc[i-1])
        for day in stress_days:
            db = bars[bars.index.normalize() == day]
            if len(db) >= 4:
                day_bars_cache[(ticker, day)] = db

    OR_END = dtime(9, 35)
    EXIT_TIME = dtime(10, 15)
    MIN_GAP_PCT = 0.015
    TARGET_R = 2.0
    MAX_SLOTS = 3

    trades = []
    for day in stress_days:
        # Co-confirmation: check if any ETF broke below OR low at any signal bar
        if use_coconfirm:
            etf_confirmed = False
            for etf in ETFs:
                key = (etf, day)
                if key not in etf_or_cache: continue
                or_h, or_l = etf_or_cache[key]
                if etf not in data_5min: continue
                etf_bars = data_5min[etf]
                db = etf_bars[etf_bars.index.normalize() == day]
                sig_bars = db[(db.index.time >= dtime(9, 35)) & (db.index.time <= dtime(10, 15))]
                for _, b in sig_bars.iterrows():
                    if float(b["low"]) < or_l and float(b["close"]) < or_l:
                        etf_confirmed = True
                        break
                if etf_confirmed: break
            if not etf_confirmed:
                continue

        slots = 0
        entered = set()
        for ticker in STOCK_UNIVERSE:
            if slots >= MAX_SLOTS: break
            if ticker in entered: continue
            all_day = day_bars_cache.get((ticker, day))
            if all_day is None: continue
            prev_c = prev_close_map.get((ticker, day))
            if prev_c is None: continue

            first_bar = all_day[all_day.index.time >= dtime(9, 30)]
            if first_bar.empty: continue
            session_open = float(first_bar.iloc[0]["open"])
            gap_pct = (session_open - prev_c) / prev_c
            if gap_pct >= -MIN_GAP_PCT: continue

            or_bars = all_day[all_day.index.time < OR_END]
            if len(or_bars) < 1: continue
            or_high = float(or_bars["high"].max())
            or_low  = float(or_bars["low"].min())
            or_range = or_high - or_low
            if or_range <= 0: continue
            atr = compute_atr(or_bars)
            if atr > 0 and (or_range < 0.5 * atr or or_range > 5 * atr): continue

            sig_bars = all_day[
                (all_day.index.time >= signal_start) &
                (all_day.index.time <= dtime(10, 15))
            ]
            if sig_bars.empty: continue

            trade = None
            for bar_ts, bar in sig_bars.iterrows():
                bar_c = float(bar["close"]); bar_l = float(bar["low"])
                if bar_l < or_low and bar_c < or_low:
                    stop_px = or_high + atr_mult * atr
                    stop_dist = stop_px - bar_c
                    if stop_dist <= 0: continue
                    shares = max(1, int(500 / stop_dist))
                    trade = dict(ticker=ticker, day=day, year=str(day.year),
                                 bar_ts=bar_ts, entry_px=bar_c, stop_px=stop_px,
                                 target_px=bar_c - TARGET_R * stop_dist, shares=shares)
                    break
            if trade is None: continue

            fwd = all_day[(all_day.index > trade["bar_ts"]) & (all_day.index.time <= EXIT_TIME)]
            exit_px = trade["entry_px"]; reason = "TIME_STOP"
            for _, b in fwd.iterrows():
                bh = float(b["high"]); bl = float(b["low"]); bc = float(b["close"])
                if bh >= trade["stop_px"]: exit_px = trade["stop_px"]; reason = "STOP_HIT"; break
                if bl <= trade["target_px"]: exit_px = trade["target_px"]; reason = "TARGET_HIT"; break
                exit_px = bc
            s = trade["shares"]
            pnl = (trade["entry_px"] - exit_px) * s - s * 0.01 * 2
            trade.update(exit_px=exit_px, reason=reason, net_pnl=pnl, win=pnl > 0)
            trades.append(trade)
            entered.add(ticker)
            slots += 1

    if not trades: return 0, 0.0, 0.0
    df = pd.DataFrame(trades)
    return len(df), df["net_pnl"].sum(), df["win"].mean() * 100

# ── Stress days ──
sd_base = get_stress_days(results_base)  # baseline pkl (215 days)
sd_new  = get_stress_days(results_new)   # current pkl after running with STK
print(f"stress_days: baseline={len(sd_base)}  new_engine={len(sd_new)}")

print(f"\n{'Config':<50} {'N':>5} {'P&L':>9} {'WR':>6}")
print('-'*74)

# Step 1: Original sim conditions (as written) on BASELINE stress_days
n, pnl, wr = run_sim(sd_base, dtime(9,35), 0.5, False)
print(f"{'[1] Original sim (9:35, ATR×0.5, no coconf, base days)':<50} {n:>5} {pnl:>+9,.0f} {wr:>5.0f}%")

# Step 2: Same but on NEW stress_days (what sim gives when run after engine change)
n, pnl, wr = run_sim(sd_new, dtime(9,35), 0.5, False)
print(f"{'[2] Same sim on new stress_days':<50} {n:>5} {pnl:>+9,.0f} {wr:>5.0f}%")

# Step 3: Fix signal start 9:35→9:40
n, pnl, wr = run_sim(sd_base, dtime(9,40), 0.5, False)
print(f"{'[3] Fix: signal_start=9:40 (base days)':<50} {n:>5} {pnl:>+9,.0f} {wr:>5.0f}%")

# Step 4: Fix ATR mult 0.5→1.0
n, pnl, wr = run_sim(sd_base, dtime(9,35), 1.0, False)
print(f"{'[4] Fix: ATR_mult=1.0 (base days)':<50} {n:>5} {pnl:>+9,.0f} {wr:>5.0f}%")

# Step 5: Both fixes on base days
n, pnl, wr = run_sim(sd_base, dtime(9,40), 1.0, False)
print(f"{'[5] Fix: 9:40 + ATR×1.0 (base days)':<50} {n:>5} {pnl:>+9,.0f} {wr:>5.0f}%")

# Step 6: Both fixes + co-confirmation on base days
n, pnl, wr = run_sim(sd_base, dtime(9,40), 1.0, True)
print(f"{'[6] Fix: 9:40 + ATR×1.0 + coconf (base days)':<50} {n:>5} {pnl:>+9,.0f} {wr:>5.0f}%")

# Step 7: Engine conditions (9:40, ATR×1.0, coconf) on NEW stress_days
n, pnl, wr = run_sim(sd_new, dtime(9,40), 1.0, True)
print(f"{'[7] Full engine params + coconf (new days)':<50} {n:>5} {pnl:>+9,.0f} {wr:>5.0f}%")

print(f"\n  [8] Engine actual (STK direct):                                   184t   -$154  WR=49%")
print(f"  [CB] TF indirect loss (not in sim):                                          -$1,544")
print(f"  [TOTAL] Net system impact:                                                   -$1,698")
