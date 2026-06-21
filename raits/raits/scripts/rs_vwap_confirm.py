"""
RS Momentum — VWAP touch với confirmation filter.

Tại VWAP touch bar, require:
  LONG : close > VWAP (bounce, not breakdown) + volume < X×avg
  SHORT: close < VWAP (rejection, not breakout) + volume < X×avg

Grid search vol threshold (0.8, 1.0, 1.2, 1.5, no filter).
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

def spy_bull(ts): return _spy_dict.get(ts.floor("5min"), None)

def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

def simulate_trade(direction, entry_px, stop_px, bars_after):
    stop_dist = abs(entry_px - stop_px)
    shares    = max(1, int(500 / stop_dist)) if stop_dist > 0 else 1
    trailing  = stop_px; exit_px = entry_px; reason = "TIME_STOP"
    for _, b in bars_after[bars_after.index.time < dtime(13,30)].iterrows():
        if direction == "LONG":
            trailing = max(trailing, float(b["high"]) - stop_dist)
            if b["low"] <= trailing: exit_px = trailing; reason = "STOP_HIT"; break
            exit_px = float(b["close"])
        else:
            trailing = min(trailing, float(b["low"]) + stop_dist)
            if b["high"] >= trailing: exit_px = trailing; reason = "STOP_HIT"; break
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
    s1030s   = sd[sd.index.time <= dtime(10,30)]
    if s1030s.empty: return None
    spy_ret = (float(s1030s.iloc[-1]["close"]) - spy_open) / spy_open if spy_open > 0 else 0
    return sret - spy_ret

def compute_ticker_vwap_series(day_bars):
    db = day_bars.copy()
    db["tp"]      = (db["high"]+db["low"]+db["close"])/3
    db["tpv"]     = db["tp"]*db["volume"]
    db["cum_tpv"] = db["tpv"].cumsum()
    db["cum_vol"] = db["volume"].cumsum()
    db["vwap"]    = db["cum_tpv"] / db["cum_vol"].replace(0, np.nan)
    return db

def run_rs_confirm(vol_mult, min_alpha=0.008):
    """
    VWAP touch + confirmation:
      LONG : touch bar close > vwap AND volume < vol_mult×avg
      SHORT: touch bar close < vwap AND volume < vol_mult×avg
    vol_mult=None → no volume filter (close confirmation only)
    """
    signals = []
    for day in normal_days:
        alphas = {}
        for ticker in available_tickers:
            db = day_bars_cache.get((ticker, day))
            if db is None: continue
            a = get_alpha(ticker, day, db)
            if a is not None: alphas[ticker] = a

        top_longs  = sorted([(tk,a) for tk,a in alphas.items() if a >  min_alpha],
                             key=lambda x: x[1], reverse=True)
        top_shorts = sorted([(tk,a) for tk,a in alphas.items() if a < -min_alpha],
                             key=lambda x: x[1])

        for candidates, direction in [(top_longs[:1],"LONG"),(top_shorts[:1],"SHORT")]:
            for ticker, alpha in candidates:
                db = day_bars_cache.get((ticker, day))
                if db is None: continue

                db_vwap = compute_ticker_vwap_series(db)
                pre  = db[db.index.time < dtime(10,35)]
                if len(pre) < 5: continue
                atr     = compute_atr(pre)
                avg_vol = float(db["volume"].mean())
                if atr <= 0: continue

                window = db_vwap[(db_vwap.index.time >= dtime(10,35)) &
                                 (db_vwap.index.time <  dtime(12, 0))]
                if window.empty: continue

                entry_ts = None; entry_px = None

                for ts, bar in window.iterrows():
                    vwap = float(bar["vwap"]) if not pd.isna(bar["vwap"]) else None
                    if vwap is None: continue
                    close = float(bar["close"])

                    # Step 1: price must be within 0.5×ATR of VWAP
                    if abs(close - vwap) > 0.5 * atr: continue

                    # Step 2: close confirmation (must close on RS side of VWAP)
                    if direction == "LONG"  and close <= vwap: continue
                    if direction == "SHORT" and close >= vwap: continue

                    # Step 3: volume filter (optional)
                    if vol_mult is not None:
                        if float(bar["volume"]) >= vol_mult * avg_vol: continue

                    entry_ts = ts; entry_px = close; break

                if entry_ts is None: continue

                sb = spy_bull(entry_ts)
                if direction == "LONG"  and sb is False: continue
                if direction == "SHORT" and sb is True:  continue

                stop_px    = (entry_px - 1.5*atr) if direction=="LONG" else (entry_px + 1.5*atr)
                bars_after = db[db.index > entry_ts]
                reason, pnl, sh = simulate_trade(direction, entry_px, stop_px, bars_after)

                signals.append(dict(ticker=ticker, date=day, year=str(day.year),
                                    direction=direction, alpha=round(alpha*100,2),
                                    exit_reason=reason, net_pnl=pnl,
                                    shares=sh, win=pnl>0))
    return pd.DataFrame(signals)

current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)

print(f"\n{'='*72}")
print(f"  RS MOMENTUM — VWAP TOUCH CONFIRMATION GRID")
print(f"{'='*72}")
print(f"\n  Current system: ${current_sys:>+,.0f}\n")
print(f"  {'Filter':<28} {'n':>5} {'P&L':>9} {'WR':>5} {'avg':>7} {'sys':>10} {'STOP%':>7}")
print(f"  {'─'*70}")

results_grid = []
configs = [
    ("close confirm only", None),
    ("close + vol<0.8×avg", 0.8),
    ("close + vol<1.0×avg", 1.0),
    ("close + vol<1.2×avg", 1.2),
    ("close + vol<1.5×avg", 1.5),
]

for label, vol_mult in configs:
    sim = run_rs_confirm(vol_mult)
    if len(sim) == 0:
        print(f"  {label:<28} no signals"); continue
    pnl   = sim["net_pnl"].sum()
    wr    = sim["win"].mean()*100
    avg   = sim["net_pnl"].mean()
    sys_  = current_sys + pnl
    stop_pct = (sim["exit_reason"]=="STOP_HIT").mean()*100
    print(f"  {label:<28} {len(sim):>5} {pnl:>+9,.0f} {wr:>4.0f}% {avg:>+7.1f} {sys_:>+10,.0f} {stop_pct:>6.0f}%")
    results_grid.append((label, vol_mult, pnl, sim))

# Best
best = max(results_grid, key=lambda x: x[2]) if results_grid else None
if best:
    label, vol_mult, pnl, sim = best
    print(f"\n{'─'*72}")
    print(f"  BEST: {label}")
    print(f"{'─'*72}")

    for yr in ["2020","2021","2022"]:
        s = sim[sim["year"]==yr]
        if len(s):
            print(f"  {yr}: {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")

    print()
    for r in sim["exit_reason"].unique():
        s = sim[sim["exit_reason"]==r]
        print(f"  {r:<14} {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")

    print()
    for d in ["LONG","SHORT"]:
        s = sim[sim["direction"]==d]
        if len(s):
            print(f"  {d}: {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")

    print(f"\n  System summary:")
    print(f"    Current system : ${current_sys:>+,.0f}")
    print(f"    + RS Momentum  : ${pnl:>+,.0f}")
    print(f"    + Gap Fill     : ~+$2,318")
    print(f"    New system est : ${current_sys + pnl + 2318:>+,.0f}")
