"""
Gap Fill — expand sang Calm regime.

Baseline: Normal days only, 23t, +$2,838 (fill+50% target)
Test: Normal + Calm days combined
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

# Normal days: TREND_FOLLOW in Normal regime
tf_normal = df_all[(df_all["strategy"]=="TREND_FOLLOW") & (df_all["hmm_state"]=="Normal")]
normal_days = sorted(tf_normal["date"].unique())

# Calm days: FADE in Calm regime (FADE only runs in Calm/Normal — use Calm subset)
fade_calm = df_all[(df_all["strategy"]=="FADE") & (df_all["hmm_state"]=="Calm")]
calm_days = sorted(fade_calm["date"].unique())

all_days = sorted(set(normal_days) | set(calm_days))
available_tickers = [tk for tk in data_5min if tk != "SPY"]

print(f"Normal days: {len(normal_days)}")
print(f"Calm days  : {len(calm_days)}")
print(f"Total days : {len(all_days)}")

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
for day in all_days:
    for ticker in available_tickers:
        if ticker not in data_5min: continue
        db = data_5min[ticker][data_5min[ticker].index.normalize()==day].sort_index()
        if len(db) >= 8: day_bars_cache[(ticker, day)] = db

def simulate(ticker, day, day_bars):
    prev_c = prev_close_map.get((ticker, day))
    if prev_c is None or prev_c <= 0: return None

    first_bar = day_bars[day_bars.index.time >= dtime(9,30)]
    if first_bar.empty: return None
    session_open = float(first_bar.iloc[0]["open"])
    gap_pct  = (session_open - prev_c) / prev_c
    gap_size = session_open - prev_c

    # LONG only: gap down
    if gap_pct >= 0: return None
    if abs(gap_pct) < 0.015 or abs(gap_pct) > 0.03: return None

    pre = day_bars[day_bars.index.time <= dtime(10,30)]
    if pre.empty: return None
    px_1030 = float(pre.iloc[-1]["close"])

    retrace = (session_open - px_1030) / gap_size if gap_size != 0 else 0
    if not (0.50 <= retrace <= 0.85): return None

    if spy_bull(pre.index[-1]) is False: return None

    morning_lod = float(pre["low"].min())
    atr = compute_atr(pre)
    if atr <= 0: return None

    entry_px  = px_1030
    stop_px   = morning_lod - 0.1 * atr
    stop_dist = abs(entry_px - stop_px)
    if stop_dist <= 0: return None
    shares    = max(1, int(500 / stop_dist))

    target_px = prev_c + 0.50 * abs(gap_size)   # fill+50% extension

    bars_after = day_bars[(day_bars.index.time > dtime(10,30)) &
                          (day_bars.index.time < dtime(13,30))]
    trailing = stop_px; exit_px = entry_px; reason = "TIME_STOP"
    for _, b in bars_after.iterrows():
        trailing = max(trailing, float(b["high"]) - stop_dist)
        if float(b["low"]) <= trailing:
            exit_px = trailing; reason = "STOP_HIT"; break
        if float(b["high"]) >= target_px:
            exit_px = target_px; reason = "TARGET_HIT"; break
        exit_px = float(b["close"])

    pnl = exit_px - entry_px
    net = pnl * shares - shares * 0.01 * 2
    return dict(ticker=ticker, date=day, year=str(day.year),
                regime="Calm" if day in set(calm_days) else "Normal",
                gap_pct=round(abs(gap_pct)*100,2),
                retrace=round(retrace,2),
                exit_reason=reason, net_pnl=net, shares=shares, win=net>0)

def run_on(days, label):
    sigs = []
    for day in days:
        for ticker in available_tickers:
            db = day_bars_cache.get((ticker, day))
            if db is None: continue
            r = simulate(ticker, day, db)
            if r: sigs.append(r)
    if not sigs: return pd.DataFrame()
    sim = pd.DataFrame(sigs)
    pnl = sim["net_pnl"].sum()
    wr  = sim["win"].mean()*100
    avg = sim["net_pnl"].mean()
    print(f"\n  {label}")
    print(f"  Trades: {len(sim)}  P&L: ${pnl:>+,.0f}  WR: {wr:.0f}%  avg: ${avg:>+.1f}")
    for yr in ["2020","2021","2022"]:
        s = sim[sim["year"]==yr]
        if len(s):
            print(f"  {yr}: {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")
    print()
    for r in sim["exit_reason"].unique():
        s = sim[sim["exit_reason"]==r]
        print(f"  {r:<14} {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%  avg=${s['net_pnl'].mean():>+.1f}")
    return sim

current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)

print(f"\n{'='*68}")
print(f"  GAP FILL — Regime Expansion  [LONG, gap 1.5-3%, retrace≥50%, fill+50% target]")
print(f"  Current system: ${current_sys:>+,.0f}")
print(f"{'='*68}")

sim_n = run_on(normal_days, "Normal only (baseline)")
sim_c = run_on(calm_days,   "Calm only")
sim_a = run_on(all_days,    "Normal + Calm combined")

# Summary table
print(f"\n{'='*68}")
print(f"  SUMMARY")
print(f"{'='*68}")
print(f"  {'Config':<25} {'n':>5} {'P&L':>9} {'WR':>5} {'avg':>7} {'system':>10}")
print(f"  {'─'*60}")
for sim, label in [(sim_n,"Normal only"), (sim_c,"Calm only"), (sim_a,"Normal+Calm")]:
    if not len(sim): continue
    pnl = sim["net_pnl"].sum()
    print(f"  {label:<25} {len(sim):>5} {pnl:>+9,.0f} {sim['win'].mean()*100:>4.0f}% "
          f"{sim['net_pnl'].mean():>+7.1f} {current_sys+pnl:>+10,.0f}")

if len(sim_a):
    print(f"\n  Ticker breakdown (Normal+Calm):")
    tk = sim_a.groupby("ticker")["net_pnl"].agg(n="count", total="sum", wr=lambda x: (sim_a.loc[x.index,"win"]).mean()*100)
    print(tk.sort_values("total", ascending=False).head(12).to_string())
