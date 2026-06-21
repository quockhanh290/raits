"""
Gap Fill — quantity expansion grid.

Fixed: gap 1.5-3%, fill+50% target, stop=morning_lod, exit 13:30, Normal days.

Grid:
  A) Direction   : LONG only, SHORT only, BOTH
  B) Retrace min : 50% (baseline), 40%, 30%
  → 3 × 3 = 9 combinations

Detail per-combo: year breakdown, exit reason, ticker concentration.
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
df_all["date"] = df_all["entry_time"].dt.normalize()
tf_normal = df_all[(df_all["strategy"]=="TREND_FOLLOW") & (df_all["hmm_state"]=="Normal")]
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

print("Precomputing caches...")
prev_close_map = {}
for ticker in available_tickers:
    if ticker not in data_5min: continue
    bars = data_5min[ticker].sort_index()
    bars["date"] = bars.index.normalize()
    daily_last = bars.groupby("date")["close"].last()
    dates = daily_last.index.tolist()
    for i in range(1, len(dates)):
        prev_close_map[(ticker, dates[i])] = float(daily_last.iloc[i-1])

day_bars_cache = {}
for day in normal_days:
    for ticker in available_tickers:
        if ticker not in data_5min: continue
        db = data_5min[ticker][data_5min[ticker].index.normalize()==day].sort_index()
        if len(db) >= 8: day_bars_cache[(ticker, day)] = db

def simulate(ticker, day, day_bars, direction_filter, min_retrace):
    prev_c = prev_close_map.get((ticker, day))
    if prev_c is None or prev_c <= 0: return None

    first_bar = day_bars[day_bars.index.time >= dtime(9,30)]
    if first_bar.empty: return None
    session_open = float(first_bar.iloc[0]["open"])
    gap_pct  = (session_open - prev_c) / prev_c
    gap_size = session_open - prev_c   # signed: negative = gap down

    if abs(gap_pct) < 0.015 or abs(gap_pct) > 0.03: return None

    direction = "LONG" if gap_pct < 0 else "SHORT"
    if direction_filter != "BOTH" and direction != direction_filter: return None

    pre = day_bars[day_bars.index.time <= dtime(10,30)]
    if pre.empty: return None
    px_1030 = float(pre.iloc[-1]["close"])

    # retrace: how much of the gap has been filled by 10:30
    retrace = (session_open - px_1030) / gap_size if gap_size != 0 else 0
    if not (min_retrace <= retrace <= 0.85): return None

    sb = spy_bull(pre.index[-1])
    if direction == "LONG"  and sb is False: return None
    if direction == "SHORT" and sb is True:  return None

    if direction == "LONG":
        morning_lod = float(pre["low"].min())
        stop_px   = morning_lod - 0.1 * compute_atr(pre)
        target_px = prev_c + 0.50 * abs(gap_size)
    else:
        morning_hod = float(pre["high"].max())
        atr = compute_atr(pre)
        stop_px   = morning_hod + 0.1 * atr
        target_px = prev_c - 0.50 * abs(gap_size)

    stop_dist = abs(px_1030 - stop_px)
    if stop_dist <= 0: return None
    shares = max(1, int(500 / stop_dist))

    bars_after = day_bars[(day_bars.index.time > dtime(10,30)) &
                          (day_bars.index.time < dtime(13,30))]
    trailing = stop_px; exit_px = px_1030; reason = "TIME_STOP"

    for _, b in bars_after.iterrows():
        if direction == "LONG":
            trailing = max(trailing, float(b["high"]) - stop_dist)
            if float(b["low"]) <= trailing:
                exit_px = trailing; reason = "STOP_HIT"; break
            if float(b["high"]) >= target_px:
                exit_px = target_px; reason = "TARGET_HIT"; break
            exit_px = float(b["close"])
        else:
            trailing = min(trailing, float(b["low"]) + stop_dist)
            if float(b["high"]) >= trailing:
                exit_px = trailing; reason = "STOP_HIT"; break
            if float(b["low"]) <= target_px:
                exit_px = target_px; reason = "TARGET_HIT"; break
            exit_px = float(b["close"])

    pnl = (exit_px - px_1030) if direction=="LONG" else (px_1030 - exit_px)
    net = pnl * shares - shares * 0.01 * 2
    return dict(ticker=ticker, date=day, year=str(day.year),
                direction=direction, gap_pct=round(abs(gap_pct)*100,2),
                retrace=round(retrace,2), exit_reason=reason,
                net_pnl=net, shares=shares, win=net>0)

current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)

DIRECTIONS   = [("LONG","LONG only"), ("SHORT","SHORT only"), ("BOTH","LONG + SHORT")]
RETRACES     = [(0.50,"retrace≥50% (baseline)"), (0.40,"retrace≥40%"), (0.30,"retrace≥30%")]

print(f"\n{'='*84}")
print(f"  GAP FILL — Direction × Retrace Min  [gap 1.5-3%, fill+50% target, Normal days]")
print(f"  Current system: ${current_sys:>+,.0f}")
print(f"{'='*84}")
print(f"  {'Direction':<14} {'Retrace':<26} {'n':>5} {'P&L':>9} {'WR':>5} {'avg':>7} "
      f"{'sys':>10} {'TGT%':>6} {'20':>8} {'21':>8} {'22':>8}")
print(f"  {'─'*90}")

all_sims = {}
for dir_code, dir_label in DIRECTIONS:
    for min_ret, ret_label in RETRACES:
        sigs = []
        for day in normal_days:
            for ticker in available_tickers:
                db = day_bars_cache.get((ticker, day))
                if db is None: continue
                r = simulate(ticker, day, db, dir_code, min_ret)
                if r: sigs.append(r)
        key = (dir_code, min_ret)
        if not sigs:
            print(f"  {dir_label:<14} {ret_label:<26} {'—':>5}"); continue
        sim = pd.DataFrame(sigs)
        pnl  = sim["net_pnl"].sum()
        wr   = sim["win"].mean()*100
        avg  = sim["net_pnl"].mean()
        sys_ = current_sys + pnl
        tgt_ = (sim["exit_reason"]=="TARGET_HIT").mean()*100
        y20  = sim[sim["year"]=="2020"]["net_pnl"].sum()
        y21  = sim[sim["year"]=="2021"]["net_pnl"].sum()
        y22  = sim[sim["year"]=="2022"]["net_pnl"].sum()
        marker = " ◄" if (pnl > 0 and y20 >= 0 and y21 >= 0 and y22 >= 0) else ""
        print(f"  {dir_label:<14} {ret_label:<26} {len(sim):>5} {pnl:>+9,.0f} {wr:>4.0f}% "
              f"{avg:>+7.1f} {sys_:>+10,.0f} {tgt_:>5.0f}% "
              f"{y20:>+8,.0f} {y21:>+8,.0f} {y22:>+8,.0f}{marker}")
        all_sims[key] = sim
    print()

# Detail per direction at retrace≥50%
print(f"\n{'='*84}")
print(f"  DIRECTION BREAKDOWN @ retrace≥50%")
print(f"{'='*84}")
for dir_code, dir_label in DIRECTIONS:
    sim = all_sims.get((dir_code, 0.50))
    if sim is None or not len(sim): continue
    print(f"\n  {dir_label} — {len(sim)}t  ${sim['net_pnl'].sum():>+,.0f}  WR={sim['win'].mean()*100:.0f}%")
    for d in sim["direction"].unique():
        s = sim[sim["direction"]==d]
        print(f"    {d}: {len(s)}t  ${s['net_pnl'].sum():>+,.0f}  WR={s['win'].mean()*100:.0f}%")
    for r in sim["exit_reason"].unique():
        s = sim[sim["exit_reason"]==r]
        print(f"    {r:<14} {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%  avg=${s['net_pnl'].mean():>+.1f}")

# Best combo
best_key = max(all_sims, key=lambda k: all_sims[k]["net_pnl"].sum()) if all_sims else None
if best_key:
    sim = all_sims[best_key]
    pnl = sim["net_pnl"].sum()
    dir_label = dict(DIRECTIONS)[best_key[0]]
    ret_label = dict(RETRACES)[best_key[1]]
    print(f"\n{'='*84}")
    print(f"  OVERALL BEST: {dir_label}, {ret_label}")
    print(f"  P&L=${pnl:>+,.0f}  System=${current_sys+pnl:>+,.0f}  Trades={len(sim)}")
    print(f"{'='*84}")
    for yr in ["2020","2021","2022"]:
        s = sim[sim["year"]==yr]
        if len(s):
            print(f"  {yr}: {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")
    tk = sim.groupby("ticker")["net_pnl"].agg(n="count", total="sum")
    print(f"\n  Top tickers:")
    print(tk.sort_values("total", ascending=False).head(10).to_string())
