"""
RS Momentum — Alpha window × Breakeven stop grid.

Fixed: alpha≥2.0%, SHORT, any-time breakout 10:30 H/L, stop=1.5×ATR, exit 12:30.

Grid:
  Alpha window : 9:30→10:30 (baseline), 9:30→10:00 (early), 9:45→10:30 (no-gap)
  Breakeven    : False, True  (BE triggered when unrealized profit ≥ 0.5×ATR)
  Direction    : SHORT, BOTH
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_scenario_g.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

with open(PKL_RESULTS, "rb") as f: results = pickle.load(f)
with open(PKL_5MIN,    "rb") as f: data_5min = pickle.load(f)
for tk in data_5min: data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

rows = []
for w in results:
    for t in w.get("trades",[]):
        d = vars(t).copy(); d["year"] = w.get("label","?"); rows.append(d)
df_all = pd.DataFrame(rows)
df_all["entry_time"] = pd.to_datetime(df_all["entry_time"])
tf_normal = df_all[(df_all["strategy"]=="TREND_FOLLOW") & (df_all["hmm_state"]=="Normal")].copy()
tf_normal["date"] = tf_normal["entry_time"].dt.normalize()
normal_days = sorted(tf_normal["date"].unique())
available_tickers = [tk for tk in data_5min if tk != "SPY"]

spy = data_5min["SPY"].sort_index().copy()
spy["tp"]      = (spy["high"]+spy["low"]+spy["close"])/3
spy["tpv"]     = spy["tp"]*spy["volume"]
spy["date"]    = spy.index.normalize()
spy["cum_tpv"] = spy.groupby("date")["tpv"].cumsum()
spy["cum_vol"] = spy.groupby("date")["volume"].cumsum()
spy["vwap"]    = spy["cum_tpv"] / spy["cum_vol"]
spy["above"]   = spy["close"] > spy["vwap"]
_spy_dict = spy["above"].reindex(
    pd.date_range(spy.index[0], spy.index[-1], freq="5min"), method="ffill"
).to_dict()
def spy_bull(ts): return _spy_dict.get(ts.floor("5min"), None)

def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

def simulate_trade(direction, entry_px, atr, breakeven, bars_after, hard_exit):
    stop_dist = 1.5 * atr
    shares    = max(1, int(500 / stop_dist)) if stop_dist > 0 else 1
    stop_px   = (entry_px - stop_dist) if direction=="LONG" else (entry_px + stop_dist)
    trailing  = stop_px; exit_px = entry_px; reason = "TIME_STOP"
    be_triggered = False
    for _, b in bars_after[bars_after.index.time < hard_exit].iterrows():
        if direction == "LONG":
            unrealized = float(b["high"]) - entry_px
            if breakeven and not be_triggered and unrealized >= 0.5 * atr:
                trailing = max(trailing, entry_px)   # move stop to entry
                be_triggered = True
            trailing = max(trailing, float(b["high"]) - stop_dist)
            if float(b["low"]) <= trailing:
                exit_px = trailing; reason = "STOP_HIT" if not be_triggered else "BE_STOP"; break
            exit_px = float(b["close"])
        else:
            unrealized = entry_px - float(b["low"])
            if breakeven and not be_triggered and unrealized >= 0.5 * atr:
                trailing = min(trailing, entry_px)   # move stop to entry
                be_triggered = True
            trailing = min(trailing, float(b["low"]) + stop_dist)
            if float(b["high"]) >= trailing:
                exit_px = trailing; reason = "STOP_HIT" if not be_triggered else "BE_STOP"; break
            exit_px = float(b["close"])
    pnl = (exit_px - entry_px) if direction=="LONG" else (entry_px - exit_px)
    return reason, pnl * shares - shares * 0.01 * 2, shares

print("Precomputing caches...")
day_bars_cache = {}
for day in normal_days:
    for ticker in available_tickers:
        if ticker not in data_5min: continue
        db = data_5min[ticker][data_5min[ticker].index.normalize()==day].sort_index()
        if len(db) >= 8: day_bars_cache[(ticker, day)] = db

spy_day_cache = {}
for day in normal_days:
    sd = spy[spy.index.normalize()==day].sort_index()
    if len(sd) >= 4: spy_day_cache[day] = sd

EXIT_T    = dtime(12,30)
MIN_ALPHA = 0.020

ALPHA_WINDOWS = {
    "9:30→10:30": (dtime(9,30),  dtime(10,30)),
    "9:30→10:00": (dtime(9,30),  dtime(10, 0)),
    "9:45→10:30": (dtime(9,45),  dtime(10,30)),
}

def get_alpha(ticker, day, day_bars, alpha_start, alpha_end):
    """Alpha = (close_at_end - price_at_start) / price_at_start vs SPY same window."""
    # Ticker
    start_bar = day_bars[day_bars.index.time <= alpha_start]
    if start_bar.empty: return None
    price_start = float(start_bar.iloc[-1]["close"])

    end_bar = day_bars[day_bars.index.time <= alpha_end]
    if end_bar.empty: return None
    price_end = float(end_bar.iloc[-1]["close"])
    t_ret = (price_end - price_start) / price_start if price_start > 0 else 0

    # SPY
    sd = spy_day_cache.get(day)
    if sd is None: return None
    spy_s = sd[sd.index.time <= alpha_start]
    if spy_s.empty: return None
    spy_start = float(spy_s.iloc[-1]["close"])
    spy_e = sd[sd.index.time <= alpha_end]
    if spy_e.empty: return None
    spy_end = float(spy_e.iloc[-1]["close"])
    spy_ret = (spy_end - spy_start) / spy_start if spy_start > 0 else 0

    return t_ret - spy_ret

def run(direction, alpha_window_name, breakeven):
    alpha_start, alpha_end = ALPHA_WINDOWS[alpha_window_name]
    signals = []

    for day in normal_days:
        alphas = {}
        for ticker in available_tickers:
            db = day_bars_cache.get((ticker, day))
            if db is None: continue
            a = get_alpha(ticker, day, db, alpha_start, alpha_end)
            if a is not None: alphas[ticker] = a

        candidates_list = []
        if direction in ("LONG","BOTH"):
            longs = sorted([(tk,a) for tk,a in alphas.items() if a > MIN_ALPHA],
                           key=lambda x: x[1], reverse=True)
            candidates_list.append((longs[:1], "LONG"))
        if direction in ("SHORT","BOTH"):
            shorts = sorted([(tk,a) for tk,a in alphas.items() if a < -MIN_ALPHA],
                            key=lambda x: x[1])
            candidates_list.append((shorts[:1], "SHORT"))

        for candidates, dir_ in candidates_list:
            for ticker, alpha in candidates:
                db = day_bars_cache.get((ticker, day))
                if db is None: continue

                # Reference level always from 10:30 bar (entry is always post-10:35)
                bar_ref = db[db.index.time <= dtime(10,30)]
                if bar_ref.empty: continue
                ref_high = float(bar_ref.iloc[-1]["high"])
                ref_low  = float(bar_ref.iloc[-1]["low"])

                pre = db[db.index.time < dtime(10,35)]
                if len(pre) < 5: continue
                atr = compute_atr(pre)
                if atr <= 0: continue

                window = db[(db.index.time >= dtime(10,35)) & (db.index.time < EXIT_T)]
                if window.empty: continue
                entry_ts = None; entry_px = None
                for ts, b in window.iterrows():
                    if dir_=="LONG"  and float(b["high"]) > ref_high:
                        entry_ts=ts; entry_px=float(b["close"]); break
                    if dir_=="SHORT" and float(b["low"])  < ref_low:
                        entry_ts=ts; entry_px=float(b["close"]); break
                if entry_ts is None: continue

                sb = spy_bull(entry_ts)
                if dir_=="LONG"  and sb is False: continue
                if dir_=="SHORT" and sb is True:  continue

                bars_after = db[db.index > entry_ts]
                reason, pnl, sh = simulate_trade(dir_, entry_px, atr, breakeven,
                                                  bars_after, EXIT_T)
                signals.append(dict(ticker=ticker, date=day, year=str(day.year),
                                    direction=dir_, alpha=round(alpha*100,2),
                                    exit_reason=reason, net_pnl=pnl, shares=sh, win=pnl>0))
    return pd.DataFrame(signals)

current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)

def print_grid(direction):
    print(f"\n{'='*82}")
    print(f"  Direction={direction}  |  alpha≥2.0%, stop=1.5×ATR, exit 12:30, breakout 10:30 H/L")
    print(f"{'='*82}")
    print(f"  {'Alpha window':<16} {'BE':>5} {'n':>5} {'P&L':>9} {'WR':>5} {'avg':>7} {'STOP%':>7} {'20':>8} {'21':>8} {'22':>8}")
    print(f"  {'─'*80}")

    for win_name in ALPHA_WINDOWS:
        for be in [False, True]:
            sim = run(direction, win_name, be)
            bl  = "yes" if be else "no"
            if not len(sim):
                print(f"  {win_name:<16} {bl:>5} {'—':>5}"); continue
            pnl  = sim["net_pnl"].sum()
            wr   = sim["win"].mean()*100
            avg  = sim["net_pnl"].mean()
            stop_= (sim["exit_reason"].isin(["STOP_HIT","BE_STOP"])).mean()*100
            y20  = sim[sim["year"]=="2020"]["net_pnl"].sum()
            y21  = sim[sim["year"]=="2021"]["net_pnl"].sum()
            y22  = sim[sim["year"]=="2022"]["net_pnl"].sum()
            marker = " ◄" if (pnl > 0 and y20 >= 0 and y21 >= 0 and y22 >= 0) else ""
            print(f"  {win_name:<16} {bl:>5} {len(sim):>5} {pnl:>+9,.0f} {wr:>4.0f}% {avg:>+7.1f} {stop_:>6.0f}% "
                  f"{y20:>+8,.0f} {y21:>+8,.0f} {y22:>+8,.0f}{marker}")

    print()

print_grid("SHORT")
print_grid("BOTH")

# Detail on best across all configs
best_pnl = -999999; best_sim = None; best_label = ""
for direction in ["SHORT","BOTH"]:
    for win_name in ALPHA_WINDOWS:
        for be in [False,True]:
            sim = run(direction, win_name, be)
            if not len(sim): continue
            pnl = sim["net_pnl"].sum()
            if pnl > best_pnl:
                best_pnl = pnl; best_sim = sim
                best_label = f"{direction}, {win_name}, BE={'yes' if be else 'no'}"

if best_sim is not None:
    print(f"{'='*82}")
    print(f"  OVERALL BEST: {best_label}  →  ${best_pnl:>+,.0f}  |  System ${current_sys+best_pnl:>+,.0f}")
    print(f"{'='*82}")
    for r in best_sim["exit_reason"].unique():
        s = best_sim[best_sim["exit_reason"]==r]
        print(f"  {r:<14} {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")
