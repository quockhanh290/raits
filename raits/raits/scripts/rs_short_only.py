"""
RS Momentum — SHORT only + immediate breakout filter.

Hypothesis: SHORT alpha với immediate 10:35 breakout là signal mạnh nhất.

Grid:
  - SHORT only vs LONG only vs both
  - alpha threshold
  - immediate (10:35) vs allow later breakouts
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

def simulate_trade(direction, entry_px, stop_px, bars_after, hard_exit):
    stop_dist = abs(entry_px - stop_px)
    shares    = max(1, int(500 / stop_dist)) if stop_dist > 0 else 1
    trailing  = stop_px; exit_px = entry_px; reason = "TIME_STOP"
    for _, b in bars_after[bars_after.index.time < hard_exit].iterrows():
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
    sret  = (float(s1030.iloc[-1]["close"]) - sopen) / sopen if sopen > 0 else 0
    sd    = spy_day_cache.get(day)
    if sd is None: return None
    sf    = sd[sd.index.time >= dtime(9,30)]
    if sf.empty: return None
    spy_o = float(sf.iloc[0]["open"])
    s1030s = sd[sd.index.time <= dtime(10,30)]
    if s1030s.empty: return None
    spy_r = (float(s1030s.iloc[-1]["close"]) - spy_o) / spy_o if spy_o > 0 else 0
    return sret - spy_r

def run(min_alpha, exit_time, directions, immediate_only):
    """
    directions: "LONG", "SHORT", or "BOTH"
    immediate_only: if True, only take 10:35 breakouts
    """
    signals = []
    EXIT = exit_time

    for day in normal_days:
        alphas = {}
        for ticker in available_tickers:
            db = day_bars_cache.get((ticker, day))
            if db is None: continue
            a = get_alpha(ticker, day, db)
            if a is not None: alphas[ticker] = a

        candidates_list = []
        if directions in ("LONG","BOTH"):
            longs = sorted([(tk,a) for tk,a in alphas.items() if a > min_alpha],
                           key=lambda x: x[1], reverse=True)
            candidates_list.append((longs[:1], "LONG"))
        if directions in ("SHORT","BOTH"):
            shorts = sorted([(tk,a) for tk,a in alphas.items() if a < -min_alpha],
                            key=lambda x: x[1])
            candidates_list.append((shorts[:1], "SHORT"))

        for candidates, direction in candidates_list:
            for ticker, alpha in candidates:
                db = day_bars_cache.get((ticker, day))
                if db is None: continue

                bar_1030 = db[db.index.time <= dtime(10,30)]
                if bar_1030.empty: continue
                ref_high = float(bar_1030.iloc[-1]["high"])
                ref_low  = float(bar_1030.iloc[-1]["low"])

                pre = db[db.index.time < dtime(10,35)]
                if len(pre) < 5: continue
                atr = compute_atr(pre)
                if atr <= 0: continue

                if immediate_only:
                    # Only the 10:35 bar
                    bar_1035 = db[db.index.time == dtime(10,35)]
                    if bar_1035.empty:
                        # Try ≤10:40 and take first
                        bar_1035 = db[(db.index.time >= dtime(10,35)) &
                                      (db.index.time <= dtime(10,40))]
                        if bar_1035.empty: continue
                    b = bar_1035.iloc[0]
                    ts = bar_1035.index[0]
                    if direction == "LONG"  and float(b["high"]) <= ref_high: continue
                    if direction == "SHORT" and float(b["low"])  >= ref_low:  continue
                    entry_ts = ts
                    entry_px = float(b["close"])
                else:
                    window = db[(db.index.time >= dtime(10,35)) &
                                 (db.index.time <  EXIT)]
                    if window.empty: continue
                    entry_ts = None; entry_px = None
                    for ts, b in window.iterrows():
                        if direction == "LONG"  and float(b["high"]) > ref_high:
                            entry_ts = ts; entry_px = float(b["close"]); break
                        if direction == "SHORT" and float(b["low"])  < ref_low:
                            entry_ts = ts; entry_px = float(b["close"]); break
                    if entry_ts is None: continue

                sb = spy_bull(entry_ts)
                if direction == "LONG"  and sb is False: continue
                if direction == "SHORT" and sb is True:  continue

                stop_px    = (entry_px - 1.5*atr) if direction=="LONG" else (entry_px + 1.5*atr)
                bars_after = db[db.index > entry_ts]
                reason, pnl, sh = simulate_trade(direction, entry_px, stop_px,
                                                  bars_after, EXIT)
                signals.append(dict(ticker=ticker, date=day, year=str(day.year),
                                    direction=direction, alpha=round(alpha*100,2),
                                    exit_reason=reason, net_pnl=pnl, shares=sh, win=pnl>0))
    return pd.DataFrame(signals)

current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)
EXIT_T = dtime(12,30)

print(f"\n{'='*74}")
print(f"  RS BREAKOUT — direction × immediate filter (alpha≥2.0%, exit 12:30)")
print(f"{'='*74}")
print(f"\n  Current system: ${current_sys:>+,.0f}\n")
print(f"  {'Config':<40} {'n':>5} {'P&L':>9} {'WR':>5} {'avg':>7} {'sys':>10} {'STOP%':>7}")
print(f"  {'─'*75}")

configs = [
    ("BOTH,  any time",     "BOTH",  False),
    ("BOTH,  10:35 only",   "BOTH",  True),
    ("LONG,  any time",     "LONG",  False),
    ("LONG,  10:35 only",   "LONG",  True),
    ("SHORT, any time",     "SHORT", False),
    ("SHORT, 10:35 only",   "SHORT", True),
]

sims = {}
for label, dirs, imm in configs:
    sim = run(0.020, EXIT_T, dirs, imm)
    if not len(sim):
        print(f"  {label:<40} no signals"); continue
    pnl   = sim["net_pnl"].sum()
    wr    = sim["win"].mean()*100
    avg   = sim["net_pnl"].mean()
    sys_  = current_sys + pnl
    stop_ = (sim["exit_reason"]=="STOP_HIT").mean()*100
    print(f"  {label:<40} {len(sim):>5} {pnl:>+9,.0f} {wr:>4.0f}% {avg:>+7.1f} {sys_:>+10,.0f} {stop_:>6.0f}%")
    sims[label] = (pnl, sim)

# Year-by-year for each direction × immediate combination
print(f"\n{'─'*74}")
print(f"  YEAR-BY-YEAR BREAKDOWN")
print(f"{'─'*74}")
for label, dirs, imm in configs:
    if label not in sims: continue
    pnl, sim = sims[label]
    row = f"  {label:<38}"
    for yr in ["2020","2021","2022"]:
        s = sim[sim["year"]==yr]
        if len(s): row += f"  {yr}:{s['net_pnl'].sum():>+8,.0f}({len(s)}t)"
        else: row += f"  {yr}:{'no sig':>11}"
    print(row)

# Detail best
best_label = max(sims, key=lambda k: sims[k][0]) if sims else None
if best_label:
    pnl, sim = sims[best_label]
    print(f"\n{'─'*74}")
    print(f"  BEST: {best_label}  →  ${pnl:>+,.0f}")
    print(f"{'─'*74}")
    for r in sim["exit_reason"].unique():
        s = sim[sim["exit_reason"]==r]
        print(f"  {r:<14} {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")
    tk = sim.groupby("ticker")["net_pnl"].agg(n="count", total="sum")
    print(f"\n  Tickers: {tk.sort_values('total',ascending=False).head(8).to_string()}")
