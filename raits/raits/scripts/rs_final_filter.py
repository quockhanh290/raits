"""
RS Momentum — final filter confirmation.
Direct entry only + alpha >= 1.5%

Usage:
    cd d:\raits\raits
    python raits/scripts/rs_final_filter.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_scenario_g.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

with open(PKL_RESULTS, "rb") as f:
    results = pickle.load(f)
with open(PKL_5MIN, "rb") as f:
    data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

rows = []
for w in results:
    yr = w.get("label","?")
    for t in w.get("trades",[]):
        d = vars(t).copy(); d["year"] = yr; rows.append(d)
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

def spy_bull(ts):
    return _spy_dict.get(ts.floor("5min"), None)

def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

def simulate_trade(direction, entry_px, stop_px, bars_after):
    stop_dist = abs(entry_px - stop_px)
    shares    = max(1, int(500 / stop_dist)) if stop_dist > 0 else 1
    trailing  = stop_px
    exit_px   = entry_px
    reason    = "TIME_STOP"
    for _, b in bars_after[bars_after.index.time < dtime(13,30)].iterrows():
        if direction == "LONG":
            trailing = max(trailing, float(b["high"]) - stop_dist)
            if b["low"] <= trailing:
                exit_px = trailing; reason = "STOP_HIT"; break
            exit_px = float(b["close"])
        else:
            trailing = min(trailing, float(b["low"]) + stop_dist)
            if b["high"] >= trailing:
                exit_px = trailing; reason = "STOP_HIT"; break
            exit_px = float(b["close"])
    pnl = (exit_px - entry_px) if direction=="LONG" else (entry_px - exit_px)
    return reason, pnl * shares - shares * 0.01 * 2, shares

print("Precomputing caches...")
day_bars_cache = {}
for day in normal_days:
    for ticker in available_tickers:
        if ticker not in data_5min: continue
        db = data_5min[ticker][data_5min[ticker].index.normalize()==day].sort_index()
        if len(db) >= 8:
            day_bars_cache[(ticker, day)] = db

spy_day_cache = {}
for day in normal_days:
    sd = spy[spy.index.normalize()==day].sort_index()
    if len(sd) >= 4:
        spy_day_cache[day] = sd

def get_alpha(ticker, day, day_bars):
    f = day_bars[day_bars.index.time >= dtime(9,30)]
    if f.empty: return None
    sopen = float(f.iloc[0]["open"])
    s1030 = day_bars[day_bars.index.time <= dtime(10,30)]
    if s1030.empty: return None
    sret = (float(s1030.iloc[-1]["close"]) - sopen) / sopen if sopen > 0 else 0

    sd = spy_day_cache.get(day)
    if sd is None: return None
    sf = sd[sd.index.time >= dtime(9,30)]
    if sf.empty: return None
    spy_open = float(sf.iloc[0]["open"])
    s1030s = sd[sd.index.time <= dtime(10,30)]
    if s1030s.empty: return None
    spy_ret = (float(s1030s.iloc[-1]["close"]) - spy_open) / spy_open if spy_open > 0 else 0
    return sret - spy_ret

MIN_ALPHA = 0.015   # 1.5%

print(f"Running RS final filter (direct entry, alpha≥{MIN_ALPHA*100:.0f}%)...")
signals = []

for day in normal_days:
    alphas = {}
    for ticker in available_tickers:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        a = get_alpha(ticker, day, db)
        if a is not None:
            alphas[ticker] = a

    top_longs  = sorted([(tk,a) for tk,a in alphas.items() if a >  MIN_ALPHA], key=lambda x: x[1], reverse=True)
    top_shorts = sorted([(tk,a) for tk,a in alphas.items() if a < -MIN_ALPHA], key=lambda x: x[1])

    for ticker, alpha in top_longs[:1]:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue

        direction = "LONG"
        pre = db[db.index.time < dtime(10,35)]
        if pre.empty: continue
        atr = compute_atr(pre)
        if atr <= 0: continue

        entry_bar = db[db.index.time <= dtime(10,40)]
        if entry_bar.empty: continue
        entry_px = float(entry_bar.iloc[-1]["close"])
        entry_ts = entry_bar.index[-1]

        sb = spy_bull(entry_ts)
        if sb is False: continue

        stop_px    = entry_px - 1.5 * atr
        bars_after = db[db.index > entry_ts]
        reason, pnl, sh = simulate_trade(direction, entry_px, stop_px, bars_after)
        signals.append(dict(ticker=ticker, date=day, year=str(day.year),
                            direction=direction, alpha=round(alpha*100,2),
                            entry_px=entry_px, exit_reason=reason,
                            net_pnl=pnl, shares=sh, win=pnl>0))

    for ticker, alpha in top_shorts[:1]:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue

        direction = "SHORT"
        pre = db[db.index.time < dtime(10,35)]
        if pre.empty: continue
        atr = compute_atr(pre)
        if atr <= 0: continue

        entry_bar = db[db.index.time <= dtime(10,40)]
        if entry_bar.empty: continue
        entry_px = float(entry_bar.iloc[-1]["close"])
        entry_ts = entry_bar.index[-1]

        sb = spy_bull(entry_ts)
        if sb is True: continue

        stop_px    = entry_px + 1.5 * atr
        bars_after = db[db.index > entry_ts]
        reason, pnl, sh = simulate_trade(direction, entry_px, stop_px, bars_after)
        signals.append(dict(ticker=ticker, date=day, year=str(day.year),
                            direction=direction, alpha=round(alpha*100,2),
                            entry_px=entry_px, exit_reason=reason,
                            net_pnl=pnl, shares=sh, win=pnl>0))

sim = pd.DataFrame(signals)
current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)

def div(label, w=72): print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

print(f"\n{'='*72}")
print(f"  RS MOMENTUM — FINAL FILTER (direct entry, alpha≥1.5%)")
print(f"{'='*72}\n")
print(f"  Signals       : {len(sim)}")
print(f"  Total P&L     : ${sim['net_pnl'].sum():>+,.0f}")
print(f"  Win rate      : {sim['win'].mean()*100:.1f}%")
print(f"  Avg / trade   : ${sim['net_pnl'].mean():>+.1f}")
print(f"  Signals/day   : {len(sim)/len(normal_days):.2f}")
print(f"  System + RS   : ${current_sys + sim['net_pnl'].sum():>+,.0f}")

div("By year")
for yr in ["2020","2021","2022"]:
    s = sim[sim["year"]==yr]
    if not len(s): continue
    print(f"  {yr}: {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  "
          f"WR={s['win'].mean()*100:.0f}%  avg=${s['net_pnl'].mean():>+.1f}")
    for d in ["LONG","SHORT"]:
        sd = s[s["direction"]==d]
        if len(sd):
            print(f"    {d}: {len(sd):>2}t  ${sd['net_pnl'].sum():>+7,.0f}  WR={sd['win'].mean()*100:.0f}%")

div("By exit reason")
for r in sim["exit_reason"].unique():
    s = sim[sim["exit_reason"]==r]
    print(f"  {r:<14} {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")

div("By direction")
for d in ["LONG","SHORT"]:
    s = sim[sim["direction"]==d]
    if len(s):
        print(f"  {d}: {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")

div("Top tickers")
tk = sim.groupby("ticker")["net_pnl"].agg(n="count", total="sum")
tk["wr"] = sim.groupby("ticker")["win"].mean()*100
print(tk.sort_values("total", ascending=False).head(12).to_string())

div("System summary")
print(f"\n  {'Strategy':<30} {'Trades':>7} {'P&L':>10} {'WR':>6} {'avg/t':>8}")
print(f"  {'─'*65}")
for strat in ["ORB","TREND_FOLLOW","VWAP_MR","FADE"]:
    s = df_all[df_all["strategy"]==strat]
    if len(s):
        print(f"  {strat:<30} {len(s):>7} {s['net_pnl'].sum():>+10,.0f} "
              f"{(s['net_pnl']>0).mean()*100:>5.0f}% {s['net_pnl'].mean():>+8.1f}")
print(f"  {'RS Momentum (new)':<30} {len(sim):>7} {sim['net_pnl'].sum():>+10,.0f} "
      f"{sim['win'].mean()*100:>5.0f}% {sim['net_pnl'].mean():>+8.1f}")
print(f"  {'Gap Fill LONG (new)':<30} {'~31':>7} {'~+2,318':>10} {'~83':>5}% {'~+75':>8}")
print(f"  {'─'*65}")
print(f"  {'Current system':<30} {'':>7} {current_sys:>+10,.0f}")
print(f"  {'+ RS Momentum':<30} {'':>7} {current_sys+sim['net_pnl'].sum():>+10,.0f}")
print(f"  {'+ RS + Gap Fill':<30} {'':>7} {current_sys+sim['net_pnl'].sum()+2318:>+10,.0f}")
