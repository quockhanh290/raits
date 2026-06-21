"""
RS Momentum — Comprehensive parameter grid.

Fixed: alpha≥2.0%, entry at 10:35 breakout of 10:30 high/low, exit 12:30.

Grid axes:
  A) RVOL threshold at 10:30 bar : None, 1.2, 1.5, 2.0
  B) Profit target (×ATR)        : None, 1.5, 2.0, 3.0
  C) Initial stop (×ATR)         : 1.0, 1.5
  D) Direction                   : BOTH, SHORT
  E) Immediate (10:35 only)      : True, False
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime
from itertools import product

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
spy["tp"]  = (spy["high"]+spy["low"]+spy["close"])/3
spy["tpv"] = spy["tp"]*spy["volume"]
spy["date"] = spy.index.normalize()
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

def simulate_trade(direction, entry_px, atr, stop_mult, target_mult, bars_after, hard_exit):
    stop_dist  = stop_mult * atr
    shares     = max(1, int(500 / stop_dist)) if stop_dist > 0 else 1
    stop_px    = (entry_px - stop_dist) if direction=="LONG" else (entry_px + stop_dist)
    target_px  = None
    if target_mult:
        target_px = (entry_px + target_mult*atr) if direction=="LONG" else (entry_px - target_mult*atr)
    trailing  = stop_px; exit_px = entry_px; reason = "TIME_STOP"
    for _, b in bars_after[bars_after.index.time < hard_exit].iterrows():
        if direction == "LONG":
            # Check target
            if target_px and float(b["high"]) >= target_px:
                exit_px = target_px; reason = "TARGET"; break
            trailing = max(trailing, float(b["high"]) - stop_dist)
            if float(b["low"]) <= trailing:
                exit_px = trailing; reason = "STOP_HIT"; break
            exit_px = float(b["close"])
        else:
            if target_px and float(b["low"]) <= target_px:
                exit_px = target_px; reason = "TARGET"; break
            trailing = min(trailing, float(b["low"]) + stop_dist)
            if float(b["high"]) >= trailing:
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
        if len(db) >= 8: day_bars_cache[(ticker, day)] = db

spy_day_cache = {}
for day in normal_days:
    sd = spy[spy.index.normalize()==day].sort_index()
    if len(sd) >= 4: spy_day_cache[day] = sd

def get_alpha(ticker, day, day_bars):
    f = day_bars[day_bars.index.time >= dtime(9,30)]
    if f.empty: return None, None
    sopen  = float(f.iloc[0]["open"])
    s1030  = day_bars[day_bars.index.time <= dtime(10,30)]
    if s1030.empty: return None, None
    last   = s1030.iloc[-1]
    sret   = (float(last["close"]) - sopen) / sopen if sopen > 0 else 0
    # RVOL: 10:30 bar volume vs avg of 9:30-10:25 bars
    pre    = day_bars[(day_bars.index.time >= dtime(9,30)) &
                      (day_bars.index.time <  dtime(10,30))]
    avg_vol = float(pre["volume"].mean()) if len(pre) > 0 else 1
    rvol   = float(last["volume"]) / avg_vol if avg_vol > 0 else 0

    sd = spy_day_cache.get(day)
    if sd is None: return None, None
    sf = sd[sd.index.time >= dtime(9,30)]
    if sf.empty: return None, None
    spy_o  = float(sf.iloc[0]["open"])
    s1030s = sd[sd.index.time <= dtime(10,30)]
    if s1030s.empty: return None, None
    spy_r  = (float(s1030s.iloc[-1]["close"]) - spy_o) / spy_o if spy_o > 0 else 0
    return sret - spy_r, rvol

EXIT_T   = dtime(12,30)
MIN_ALPHA = 0.020

def run(direction, immediate, rvol_min, target_mult, stop_mult):
    signals = []
    for day in normal_days:
        alphas = {}
        for ticker in available_tickers:
            db = day_bars_cache.get((ticker, day))
            if db is None: continue
            a, rvol = get_alpha(ticker, day, db)
            if a is not None: alphas[ticker] = (a, rvol)

        candidates_list = []
        if direction in ("LONG","BOTH"):
            longs = sorted([(tk,v) for tk,v in alphas.items() if v[0] > MIN_ALPHA],
                           key=lambda x: x[1][0], reverse=True)
            candidates_list.append((longs[:1], "LONG"))
        if direction in ("SHORT","BOTH"):
            shorts = sorted([(tk,v) for tk,v in alphas.items() if v[0] < -MIN_ALPHA],
                            key=lambda x: x[1][0])
            candidates_list.append((shorts[:1], "SHORT"))

        for candidates, dir_ in candidates_list:
            for ticker, (alpha, rvol) in candidates:
                if rvol_min and rvol < rvol_min: continue

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

                if immediate:
                    w = db[(db.index.time >= dtime(10,35)) & (db.index.time <= dtime(10,40))]
                    if w.empty: continue
                    b  = w.iloc[0]
                    ts = w.index[0]
                    if dir_=="LONG"  and float(b["high"]) <= ref_high: continue
                    if dir_=="SHORT" and float(b["low"])  >= ref_low:  continue
                    entry_ts = ts; entry_px = float(b["close"])
                else:
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
                reason, pnl, sh = simulate_trade(dir_, entry_px, atr,
                                                  stop_mult, target_mult,
                                                  bars_after, EXIT_T)
                signals.append(dict(ticker=ticker, date=day, year=str(day.year),
                                    direction=dir_, alpha=round(alpha*100,2),
                                    rvol=round(rvol,1), exit_reason=reason,
                                    net_pnl=pnl, shares=sh, win=pnl>0))
    return pd.DataFrame(signals)

current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)

# ── SECTION 1: RVOL × Profit Target grid (fix: SHORT, immediate=False, stop=1.5) ──
print(f"\n{'='*80}")
print(f"  SECTION 1 — RVOL × Profit Target  [SHORT, any-time breakout, stop=1.5×ATR]")
print(f"  Current system: ${current_sys:>+,.0f}")
print(f"{'='*80}")
print(f"  {'RVOL':>6} {'Target':>8} {'n':>5} {'P&L':>9} {'WR':>5} {'avg':>7} {'STOP%':>7} {'20':>8} {'21':>8} {'22':>8}")
print(f"  {'─'*78}")

best1 = None
for rvol_min, target_mult in product([None,1.2,1.5,2.0],[None,1.5,2.0,3.0]):
    sim = run("SHORT", False, rvol_min, target_mult, 1.5)
    rl  = f">{rvol_min}x" if rvol_min else "none"
    tl  = f"{target_mult}×ATR" if target_mult else "none"
    if not len(sim):
        print(f"  {rl:>6} {tl:>8} {'—':>5}"); continue
    pnl  = sim["net_pnl"].sum()
    wr   = sim["win"].mean()*100
    avg  = sim["net_pnl"].mean()
    stop_= (sim["exit_reason"]=="STOP_HIT").mean()*100
    y20  = sim[sim["year"]=="2020"]["net_pnl"].sum()
    y21  = sim[sim["year"]=="2021"]["net_pnl"].sum()
    y22  = sim[sim["year"]=="2022"]["net_pnl"].sum()
    marker = " ◄" if (pnl > 0 and y20 >= 0 and y21 >= 0 and y22 >= 0) else ""
    print(f"  {rl:>6} {tl:>8} {len(sim):>5} {pnl:>+9,.0f} {wr:>4.0f}% {avg:>+7.1f} {stop_:>6.0f}% "
          f"{y20:>+8,.0f} {y21:>+8,.0f} {y22:>+8,.0f}{marker}")
    if best1 is None or pnl > best1[0]:
        best1 = (pnl, sim, rl, tl)

# ── SECTION 2: Stop tightness × RVOL (fix: SHORT, no target, immediate=False) ──
print(f"\n{'='*80}")
print(f"  SECTION 2 — Stop × RVOL  [SHORT, any-time breakout, no profit target]")
print(f"{'='*80}")
print(f"  {'Stop':>8} {'RVOL':>6} {'n':>5} {'P&L':>9} {'WR':>5} {'avg':>7} {'STOP%':>7} {'20':>8} {'21':>8} {'22':>8}")
print(f"  {'─'*78}")

for stop_mult, rvol_min in product([1.0,1.5],[None,1.2,1.5,2.0]):
    sim = run("SHORT", False, rvol_min, None, stop_mult)
    sl  = f"{stop_mult}×ATR"
    rl  = f">{rvol_min}x" if rvol_min else "none"
    if not len(sim):
        print(f"  {sl:>8} {rl:>6} {'—':>5}"); continue
    pnl  = sim["net_pnl"].sum()
    wr   = sim["win"].mean()*100
    avg  = sim["net_pnl"].mean()
    stop_= (sim["exit_reason"]=="STOP_HIT").mean()*100
    y20  = sim[sim["year"]=="2020"]["net_pnl"].sum()
    y21  = sim[sim["year"]=="2021"]["net_pnl"].sum()
    y22  = sim[sim["year"]=="2022"]["net_pnl"].sum()
    print(f"  {sl:>8} {rl:>6} {len(sim):>5} {pnl:>+9,.0f} {wr:>4.0f}% {avg:>+7.1f} {stop_:>6.0f}% "
          f"{y20:>+8,.0f} {y21:>+8,.0f} {y22:>+8,.0f}")

# ── SECTION 3: Direction × Immediate (fix: rvol=1.5, target=2.0×ATR, stop=1.5) ──
print(f"\n{'='*80}")
print(f"  SECTION 3 — Direction × Immediate  [best RVOL+Target combo from S1]")
print(f"{'='*80}")
print(f"  {'Direction':>10} {'Imm':>6} {'n':>5} {'P&L':>9} {'WR':>5} {'avg':>7} {'STOP%':>7} {'20':>8} {'21':>8} {'22':>8}")
print(f"  {'─'*78}")

for dir_, imm in product(["BOTH","SHORT"],[False,True]):
    sim = run(dir_, imm, 1.5, 2.0, 1.5)
    dl  = dir_
    il  = "yes" if imm else "no"
    if not len(sim):
        print(f"  {dl:>10} {il:>6} {'—':>5}"); continue
    pnl  = sim["net_pnl"].sum()
    wr   = sim["win"].mean()*100
    avg  = sim["net_pnl"].mean()
    stop_= (sim["exit_reason"]=="STOP_HIT").mean()*100
    y20  = sim[sim["year"]=="2020"]["net_pnl"].sum()
    y21  = sim[sim["year"]=="2021"]["net_pnl"].sum()
    y22  = sim[sim["year"]=="2022"]["net_pnl"].sum()
    print(f"  {dl:>10} {il:>6} {len(sim):>5} {pnl:>+9,.0f} {wr:>4.0f}% {avg:>+7.1f} {stop_:>6.0f}% "
          f"{y20:>+8,.0f} {y21:>+8,.0f} {y22:>+8,.0f}")

# ── BEST overall ──
if best1:
    pnl, sim, rl, tl = best1
    print(f"\n{'='*80}")
    print(f"  OVERALL BEST (Section 1): RVOL>{rl}, Target={tl}, SHORT, stop=1.5×ATR")
    print(f"  P&L=${pnl:>+,.0f}  |  System=${current_sys+pnl:>+,.0f}")
    print(f"{'='*80}")
    for r in sim["exit_reason"].unique():
        s = sim[sim["exit_reason"]==r]
        print(f"  {r:<12} {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")
    print()
    for yr in ["2020","2021","2022"]:
        s = sim[sim["year"]==yr]
        if len(s):
            print(f"  {yr}: {len(s):>2}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")
