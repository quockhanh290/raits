"""
Gap Fill deep-dive diagnostic.

Câu hỏi:
  1. LONG only (gap down fill) có consistent không?
  2. Gap size ảnh hưởng fill rate như nào?
  3. Retrace tại entry cao hơn → fill rate cao hơn?
  4. Tốc độ fill (time to TARGET_HIT)
  5. Ticker concentration

Usage:
    cd d:\raits\raits
    python raits/scripts/gap_fill_diagnostic.py
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
        d = vars(t).copy()
        d["year"] = yr
        rows.append(d)
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
spy["above_vwap"] = spy["close"] > spy["vwap"]
_spy_dict = spy["above_vwap"].reindex(
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

print("Precomputing caches...")
prev_close_map = {}
day_bars_cache = {}

for ticker in available_tickers:
    if ticker not in data_5min: continue
    bars = data_5min[ticker].sort_index()
    bars["date"] = bars.index.normalize()
    daily_last = bars.groupby("date")["close"].last()
    dates = daily_last.index.tolist()
    for i in range(1, len(dates)):
        prev_close_map[(ticker, dates[i])] = float(daily_last.iloc[i-1])

for day in normal_days:
    for ticker in available_tickers:
        if ticker not in data_5min: continue
        db = data_5min[ticker][data_5min[ticker].index.normalize() == day].sort_index()
        if len(db) >= 8:
            day_bars_cache[(ticker, day)] = db

# ── Extended gap fill sim — tracks more features ──────────────────────────────
MIN_GAP_PCT = 0.015
MIN_RETRACE = 0.30
MAX_RETRACE = 0.85

def sim_gap_fill_extended(ticker, day, day_bars, direction_filter=None):
    prev_c = prev_close_map.get((ticker, day))
    if prev_c is None or prev_c <= 0: return None

    first_bar = day_bars[day_bars.index.time >= dtime(9, 30)]
    if first_bar.empty: return None
    session_open = float(first_bar.iloc[0]["open"])
    gap_pct  = (session_open - prev_c) / prev_c
    gap_size = session_open - prev_c   # signed

    if abs(gap_pct) < MIN_GAP_PCT: return None

    pre_entry = day_bars[day_bars.index.time <= dtime(10, 30)]
    if pre_entry.empty: return None
    px_1030 = float(pre_entry.iloc[-1]["close"])

    retrace = (session_open - px_1030) / gap_size if gap_size != 0 else 0
    if not (MIN_RETRACE <= retrace <= MAX_RETRACE): return None

    morning_hod = float(pre_entry["high"].max())
    morning_lod = float(pre_entry["low"].min())
    atr = compute_atr(pre_entry)
    if atr <= 0: return None

    direction = "SHORT" if gap_pct > 0 else "LONG"
    if direction_filter and direction != direction_filter: return None

    entry_px  = px_1030
    sb = spy_bull(pre_entry.index[-1])
    if direction == "SHORT":
        stop_px   = morning_hod + 0.1 * atr
        target_px = prev_c
        if sb is True: return None
    else:
        stop_px   = morning_lod - 0.1 * atr
        target_px = prev_c
        if sb is False: return None

    stop_dist = abs(entry_px - stop_px)
    shares    = max(1, int(500 / stop_dist)) if stop_dist > 0 else 1
    trailing  = stop_px
    exit_px   = entry_px
    reason    = "TIME_STOP"
    exit_ts   = None

    bars_after = day_bars[day_bars.index.time > dtime(10, 30)]
    bars_after = bars_after[bars_after.index.time < dtime(13, 30)]

    for ts, b in bars_after.iterrows():
        if direction == "LONG":
            trailing = max(trailing, float(b["high"]) - stop_dist)
            if b["low"] <= trailing:
                exit_px = trailing; reason = "STOP_HIT"; exit_ts = ts; break
            if float(b["high"]) >= target_px:
                exit_px = target_px; reason = "TARGET_HIT"; exit_ts = ts; break
            exit_px = float(b["close"]); exit_ts = ts
        else:
            trailing = min(trailing, float(b["low"]) + stop_dist)
            if b["high"] >= trailing:
                exit_px = trailing; reason = "STOP_HIT"; exit_ts = ts; break
            if float(b["low"]) <= target_px:
                exit_px = target_px; reason = "TARGET_HIT"; exit_ts = ts; break
            exit_px = float(b["close"]); exit_ts = ts

    pnl   = (exit_px - entry_px) if direction=="LONG" else (entry_px - exit_px)
    net   = pnl * shares - shares * 0.01 * 2
    dist_to_fill = abs(entry_px - target_px)
    dist_to_stop = abs(entry_px - stop_px)
    rr    = dist_to_fill / dist_to_stop if dist_to_stop > 0 else 0

    bars_to_exit = None
    if exit_ts and reason == "TARGET_HIT":
        bars_counted = bars_after[bars_after.index <= exit_ts]
        bars_to_exit = len(bars_counted)

    return dict(
        ticker=ticker, date=day, year=str(day.year), direction=direction,
        gap_pct=round(abs(gap_pct)*100, 2),
        gap_pct_bucket="1.5-2%" if abs(gap_pct) < 0.02 else
                        "2-3%"   if abs(gap_pct) < 0.03 else ">3%",
        retrace_at_entry=round(retrace, 2),
        retrace_bucket="30-50%" if retrace < 0.50 else
                       "50-70%" if retrace < 0.70 else "70-85%",
        entry_px=entry_px, target_px=target_px, stop_px=stop_px,
        dist_to_fill=round(dist_to_fill, 3),
        rr=round(rr, 2),
        exit_reason=reason, net_pnl=net, shares=shares, win=net>0,
        bars_to_fill=bars_to_exit,
        spy_bull=sb,
    )

print(f"Running extended gap fill sim on {len(normal_days)} Normal days × {len(available_tickers)} tickers...")
all_signals = []
for day in normal_days:
    for ticker in available_tickers:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        r = sim_gap_fill_extended(ticker, day, db)
        if r: all_signals.append(r)

sim = pd.DataFrame(all_signals) if all_signals else pd.DataFrame()
current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)
non_gf_pnl  = current_sys  # gap fill is additive

def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

def show(label, s, indent="  "):
    n   = len(s)
    if n == 0: return
    pnl = s["net_pnl"].sum()
    wr  = s["win"].mean()*100
    avg = s["net_pnl"].mean()
    print(f"{indent}{label:<42} {n:>4}t  ${pnl:>+8,.0f}  WR={wr:>3.0f}%  avg=${avg:>+.1f}")

print(f"\n{'='*72}")
print(f"  GAP FILL DIAGNOSTIC  —  {len(sim)} signals")
print(f"{'='*72}")

div("1. Direction split (LONG vs SHORT)")
show("LONG  (gap DOWN fill)", sim[sim["direction"]=="LONG"])
show("SHORT (gap UP fill)",   sim[sim["direction"]=="SHORT"])
print()
# Year breakdown per direction
for d, lbl in [("LONG","gap DOWN"), ("SHORT","gap UP")]:
    s = sim[sim["direction"]==d]
    print(f"  {lbl}:")
    for yr in ["2020","2021","2022"]:
        sy = s[s["year"]==yr]
        if len(sy):
            print(f"    {yr}: {len(sy):>3}t  ${sy['net_pnl'].sum():>+7,.0f}  WR={sy['win'].mean()*100:.0f}%")

div("2. EXIT REASON × DIRECTION")
for d in ["LONG","SHORT"]:
    s = sim[sim["direction"]==d]
    print(f"\n  {d}:")
    for r in ["TARGET_HIT","TIME_STOP","STOP_HIT"]:
        sr = s[s["exit_reason"]==r]
        if len(sr):
            show(f"  {r}", sr, indent="    ")

div("3. GAP SIZE — does bigger gap fill less reliably?")
print(f"\n  {'Gap size':<12} {'n':>4}  {'WR':>5}  {'P&L':>9}  {'avg':>7}")
for bucket in ["1.5-2%","2-3%",">3%"]:
    s = sim[sim["gap_pct_bucket"]==bucket]
    if len(s):
        wr  = s["win"].mean()*100
        pnl = s["net_pnl"].sum()
        avg = s["net_pnl"].mean()
        print(f"  {bucket:<12} {len(s):>4}  {wr:>4.0f}%  {pnl:>+9,.0f}  {avg:>+7.1f}")

div("4. RETRACE AT ENTRY — more retraced = easier fill?")
print(f"\n  {'Retrace':<12} {'n':>4}  {'WR':>5}  {'P&L':>9}  {'avg':>7}  {'fill_rate':>10}")
for bucket in ["30-50%","50-70%","70-85%"]:
    s = sim[sim["retrace_bucket"]==bucket]
    if len(s):
        wr  = s["win"].mean()*100
        pnl = s["net_pnl"].sum()
        avg = s["net_pnl"].mean()
        fill_rate = (s["exit_reason"]=="TARGET_HIT").mean()*100
        print(f"  {bucket:<12} {len(s):>4}  {wr:>4.0f}%  {pnl:>+9,.0f}  {avg:>+7.1f}  {fill_rate:>8.0f}%")

div("5. FILL SPEED — bars to TARGET_HIT")
fills = sim[sim["exit_reason"]=="TARGET_HIT"].copy()
fills["bars_to_fill"] = fills["bars_to_fill"].fillna(0).astype(int)
if len(fills):
    print(f"\n  TARGET_HIT trades: {len(fills)}")
    print(f"  Avg bars to fill : {fills['bars_to_fill'].mean():.1f} bars ({fills['bars_to_fill'].mean()*5:.0f} min)")
    print(f"  Median bars      : {fills['bars_to_fill'].median():.0f} bars")
    for bucket, lo, hi in [("<30min",0,6),("30-60min",6,12),("60-120min",12,24),(">120min",24,999)]:
        s = fills[(fills["bars_to_fill"]>=lo) & (fills["bars_to_fill"]<hi)]
        if len(s):
            print(f"  {bucket:<12} {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}")

div("6. R:R distribution")
print(f"\n  {'R:R bucket':<12} {'n':>4}  {'WR':>5}  {'P&L':>9}")
for lo, hi, lbl in [(0,1,"<1.0x"),(1,2,"1.0-2.0x"),(2,3,"2.0-3.0x"),(3,99,">3.0x")]:
    s = sim[(sim["rr"]>=lo) & (sim["rr"]<hi)]
    if len(s):
        print(f"  {lbl:<12} {len(s):>4}  {s['win'].mean()*100:>4.0f}%  {s['net_pnl'].sum():>+9,.0f}")

div("7. SIMULATION: LONG only")
long_only = sim[sim["direction"]=="LONG"]
print(f"\n  LONG only: {len(long_only)}t  ${long_only['net_pnl'].sum():>+,.0f}  WR={long_only['win'].mean()*100:.0f}%  avg=${long_only['net_pnl'].mean():>+.1f}")
print(f"  System + LONG only GF: ${current_sys + long_only['net_pnl'].sum():>+,.0f}")
for yr in ["2020","2021","2022"]:
    s = long_only[long_only["year"]==yr]
    if len(s):
        print(f"    {yr}: {len(s):>3}t  ${s['net_pnl'].sum():>+7,.0f}  WR={s['win'].mean()*100:.0f}%")

div("8. SIMULATION: LONG + stricter retrace (≥50% retraced at entry)")
long_strict = long_only[long_only["retrace_at_entry"] >= 0.50]
print(f"\n  LONG, retrace≥50%: {len(long_strict)}t  ${long_strict['net_pnl'].sum():>+,.0f}  WR={long_strict['win'].mean()*100:.0f}%  avg=${long_strict['net_pnl'].mean():>+.1f}")
if len(long_strict):
    for yr in ["2020","2021","2022"]:
        s = long_strict[long_strict["year"]==yr]
        if len(s):
            print(f"    {yr}: {len(s):>3}t  ${s['net_pnl'].sum():>+7,.0f}  WR={s['win'].mean()*100:.0f}%")
    print(f"  EXIT reason:")
    for r in long_strict["exit_reason"].unique():
        s = long_strict[long_strict["exit_reason"]==r]
        print(f"    {r}: {len(s)}t  ${s['net_pnl'].sum():>+,.0f}  WR={s['win'].mean()*100:.0f}%")

div("9. Top 15 tickers")
tk = sim.groupby("ticker")["net_pnl"].agg(n="count",total="sum",wr=lambda x: (sim.loc[x.index,"win"]).mean()*100)
print(tk.sort_values("total",ascending=False).head(15).to_string())
