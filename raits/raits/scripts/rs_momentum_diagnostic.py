"""
RS Momentum deep-dive diagnostic.

Câu hỏi:
  1. 2020 failure — LONG hay SHORT gây ra? COVID hay structural?
  2. Alpha threshold grid — 0.5/0.8/1.0/1.5/2.0% cutoff
  3. Entry type — VWAP touch vs direct entry
  4. Alpha size — bigger RS = more persistent?
  5. SPY context — edge khác nhau khi SPY above/below VWAP?
  6. Nếu hold đến 14:00 thay vì 13:30?

Usage:
    cd d:\raits\raits
    python raits/scripts/rs_momentum_diagnostic.py
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

# ── SPY ───────────────────────────────────────────────────────────────────────
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

def simulate_trade(direction, entry_px, stop_px, bars_after, hard_exit):
    stop_dist = abs(entry_px - stop_px)
    shares    = max(1, int(500 / stop_dist)) if stop_dist > 0 else 1
    trailing  = stop_px
    exit_px   = entry_px
    reason    = "TIME_STOP"
    for ts, b in bars_after[bars_after.index.time < hard_exit].iterrows():
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

# ── Precompute caches ─────────────────────────────────────────────────────────
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

# ── Alpha calc ────────────────────────────────────────────────────────────────
def get_alpha(ticker, day, day_bars):
    first = day_bars[day_bars.index.time >= dtime(9,30)]
    if first.empty: return None
    stock_open = float(first.iloc[0]["open"])
    s1030 = day_bars[day_bars.index.time <= dtime(10,30)]
    if s1030.empty: return None
    stock_ret = (float(s1030.iloc[-1]["close"]) - stock_open) / stock_open if stock_open > 0 else 0

    sd = spy_day_cache.get(day)
    if sd is None: return None
    sf = sd[sd.index.time >= dtime(9,30)]
    if sf.empty: return None
    spy_open = float(sf.iloc[0]["open"])
    s1030s = sd[sd.index.time <= dtime(10,30)]
    if s1030s.empty: return None
    spy_ret = (float(s1030s.iloc[-1]["close"]) - spy_open) / spy_open if spy_open > 0 else 0

    return stock_ret - spy_ret

# ── Extended RS sim with tracking ────────────────────────────────────────────
def sim_rs_extended(ticker, day, day_bars, alpha, exit_time=dtime(13,30)):
    direction = "LONG" if alpha > 0 else "SHORT"

    db = day_bars.copy()
    db["tp"]  = (db["high"]+db["low"]+db["close"])/3
    db["tpv"] = db["tp"]*db["volume"]
    db["cum_tpv"] = db["tpv"].cumsum()
    db["cum_vol"] = db["volume"].cumsum()
    db["vwap"] = db["cum_tpv"] / db["cum_vol"].replace(0, np.nan)

    atr = compute_atr(day_bars[day_bars.index.time < dtime(10,30)])
    if atr <= 0: return None

    window = db[(db.index.time >= dtime(10,35)) &
                (db.index.time <  dtime(12,30))]
    if window.empty: return None

    # Try VWAP touch first
    entry_bar = None
    entry_type = "direct"
    for ts, bar in window.iterrows():
        vwap = db.loc[ts,"vwap"] if ts in db.index else np.nan
        if pd.isna(vwap): continue
        if abs(float(bar["close"]) - float(vwap)) <= 0.5 * atr:
            entry_bar  = (ts, bar)
            entry_type = "vwap_touch"
            break

    if entry_bar is None:
        first = window[window.index.time <= dtime(10,40)]
        if first.empty: return None
        entry_bar  = (first.index[0], first.iloc[0])
        entry_type = "direct"

    ts, bar  = entry_bar
    entry_px = float(bar["close"])
    stop_px  = (entry_px - 1.5*atr) if direction=="LONG" else (entry_px + 1.5*atr)

    sb = spy_bull(ts)
    if direction == "LONG"  and sb is False: return None
    if direction == "SHORT" and sb is True:  return None

    bars_after = window[window.index > ts]
    reason, pnl, sh = simulate_trade(direction, entry_px, stop_px, bars_after, exit_time)

    return dict(
        ticker=ticker, date=day, year=str(day.year),
        direction=direction,
        alpha=round(alpha*100, 2),
        alpha_abs=round(abs(alpha)*100, 2),
        alpha_bucket="0.8-1.5%" if abs(alpha) < 0.015 else
                     "1.5-3%"   if abs(alpha) < 0.030 else ">3%",
        entry_type=entry_type,
        entry_px=entry_px, stop_px=stop_px,
        spy_bull=sb,
        exit_reason=reason,
        net_pnl=pnl, shares=sh, win=pnl>0,
        exit_time_limit=exit_time.strftime("%H:%M"),
    )

# ── Run base sim (MIN_ALPHA=0.008, exit 13:30) ────────────────────────────────
print(f"Running RS momentum diagnostic on {len(normal_days)} Normal days...")

BASE_ALPHA = 0.008
all_signals = []

for day in normal_days:
    alphas = {}
    for ticker in available_tickers:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        a = get_alpha(ticker, day, db)
        if a is not None:
            alphas[ticker] = a

    top_longs  = sorted([(tk,a) for tk,a in alphas.items() if a >  BASE_ALPHA], key=lambda x: x[1], reverse=True)
    top_shorts = sorted([(tk,a) for tk,a in alphas.items() if a < -BASE_ALPHA], key=lambda x: x[1])

    for ticker, alpha in top_longs[:1]:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        r = sim_rs_extended(ticker, day, db, alpha)
        if r: all_signals.append(r)

    for ticker, alpha in top_shorts[:1]:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        r = sim_rs_extended(ticker, day, db, alpha)
        if r: all_signals.append(r)

sim = pd.DataFrame(all_signals)
current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)

def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

def show(label, s, indent="  "):
    if len(s) == 0: return
    print(f"{indent}{label:<42} {len(s):>4}t  ${s['net_pnl'].sum():>+8,.0f}  "
          f"WR={s['win'].mean()*100:>3.0f}%  avg=${s['net_pnl'].mean():>+.1f}")

print(f"\n{'='*72}")
print(f"  RS MOMENTUM DIAGNOSTIC  —  {len(sim)} signals")
print(f"{'='*72}")
print(f"  Current system: ${current_sys:>+,.0f}  |  System + RS: ${current_sys+sim['net_pnl'].sum():>+,.0f}")

div("1. YEAR × DIRECTION — 2020 failure breakdown")
for yr in ["2020","2021","2022"]:
    s = sim[sim["year"]==yr]
    print(f"\n  [{yr}] {len(s)}t total  ${s['net_pnl'].sum():>+,.0f}  WR={s['win'].mean()*100:.0f}%")
    for d in ["LONG","SHORT"]:
        sd = s[s["direction"]==d]
        if len(sd):
            show(f"  {d}", sd, indent="    ")

div("2. ALPHA THRESHOLD GRID — MIN_ALPHA impact")
print(f"\n  {'MIN_ALPHA':>10} {'Signals':>8} {'P&L':>9} {'WR':>6} {'avg/t':>8} {'sys':>10}")
print(f"  {'─'*55}")
for min_a in [0.005, 0.008, 0.010, 0.015, 0.020]:
    # Re-filter from base signals
    filtered = []
    for day in normal_days:
        alphas = {}
        for ticker in available_tickers:
            db = day_bars_cache.get((ticker, day))
            if db is None: continue
            a = get_alpha(ticker, day, db)
            if a is not None:
                alphas[ticker] = a

        top_longs  = sorted([(tk,a) for tk,a in alphas.items() if a >  min_a], key=lambda x: x[1], reverse=True)
        top_shorts = sorted([(tk,a) for tk,a in alphas.items() if a < -min_a], key=lambda x: x[1])

        for ticker, alpha in top_longs[:1]:
            db = day_bars_cache.get((ticker, day))
            if db is None: continue
            r = sim_rs_extended(ticker, day, db, alpha)
            if r: filtered.append(r)

        for ticker, alpha in top_shorts[:1]:
            db = day_bars_cache.get((ticker, day))
            if db is None: continue
            r = sim_rs_extended(ticker, day, db, alpha)
            if r: filtered.append(r)

    if not filtered: continue
    fs  = pd.DataFrame(filtered)
    n   = len(fs)
    pnl = fs["net_pnl"].sum()
    wr  = fs["win"].mean()*100
    avg = fs["net_pnl"].mean()
    sys = current_sys + pnl
    print(f"  {min_a*100:>9.1f}% {n:>8} {pnl:>+9,.0f} {wr:>5.0f}% {avg:>+8.1f} {sys:>+10,.0f}")

div("3. ALPHA SIZE — bigger RS = more persistent momentum?")
for bucket in ["0.8-1.5%","1.5-3%",">3%"]:
    s = sim[sim["alpha_bucket"]==bucket]
    if len(s): show(bucket, s)

div("4. ENTRY TYPE — VWAP touch vs direct entry")
for et in sim["entry_type"].unique():
    s = sim[sim["entry_type"]==et]
    show(et, s)
print()
for et in sim["entry_type"].unique():
    s = sim[sim["entry_type"]==et]
    print(f"\n  {et}:")
    for yr in ["2020","2021","2022"]:
        sy = s[s["year"]==yr]
        if len(sy): show(yr, sy, indent="    ")

div("5. SPY CONTEXT — edge khi SPY above vs below VWAP")
show("SPY above VWAP (bullish)", sim[sim["spy_bull"]==True])
show("SPY below VWAP (bearish)", sim[sim["spy_bull"]==False])
print()
for sb_val, lbl in [(True,"SPY BULL"),(False,"SPY BEAR")]:
    s = sim[sim["spy_bull"]==sb_val]
    print(f"\n  {lbl}:")
    for d in ["LONG","SHORT"]:
        sd = s[s["direction"]==d]
        if len(sd): show(f"  {d}", sd, indent="    ")

div("6. HOLD TIME — exit 13:30 vs 14:00")
# Re-run with exit at 14:00
signals_1400 = []
for day in normal_days:
    alphas = {}
    for ticker in available_tickers:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        a = get_alpha(ticker, day, db)
        if a is not None:
            alphas[ticker] = a

    top_longs  = sorted([(tk,a) for tk,a in alphas.items() if a >  BASE_ALPHA], key=lambda x: x[1], reverse=True)
    top_shorts = sorted([(tk,a) for tk,a in alphas.items() if a < -BASE_ALPHA], key=lambda x: x[1])

    for ticker, alpha in top_longs[:1]:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        r = sim_rs_extended(ticker, day, db, alpha, exit_time=dtime(14,0))
        if r: signals_1400.append(r)

    for ticker, alpha in top_shorts[:1]:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        r = sim_rs_extended(ticker, day, db, alpha, exit_time=dtime(14,0))
        if r: signals_1400.append(r)

s14 = pd.DataFrame(signals_1400)
print(f"\n  Exit 13:30 : {len(sim)}t  ${sim['net_pnl'].sum():>+,.0f}  WR={sim['win'].mean()*100:.0f}%")
print(f"  Exit 14:00 : {len(s14)}t  ${s14['net_pnl'].sum():>+,.0f}  WR={s14['win'].mean()*100:.0f}%")
for yr in ["2020","2021","2022"]:
    a = sim[sim["year"]==yr]; b = s14[s14["year"]==yr]
    if len(a):
        print(f"  {yr}:  13:30=${a['net_pnl'].sum():>+7,.0f}  14:00=${b['net_pnl'].sum():>+7,.0f}")

div("7. EXIT REASON breakdown")
for r in sim["exit_reason"].unique():
    s = sim[sim["exit_reason"]==r]
    show(r, s)
    for yr in ["2020","2021","2022"]:
        sy = s[s["year"]==yr]
        if len(sy): show(yr, sy, indent="    ")

div("8. 2020 FAILURE ANALYSIS — what's different?")
s20 = sim[sim["year"]=="2020"]
s_rest = sim[sim["year"]!="2020"]
print(f"\n  2020    : {len(s20)}t   avg alpha={s20['alpha_abs'].mean():.2f}%  "
      f"entry_type={s20['entry_type'].value_counts().to_dict()}")
print(f"  2021-22 : {len(s_rest)}t  avg alpha={s_rest['alpha_abs'].mean():.2f}%  "
      f"entry_type={s_rest['entry_type'].value_counts().to_dict()}")
print(f"\n  2020 exit reasons: {s20['exit_reason'].value_counts().to_dict()}")
print(f"  2020 direction  : {s20['direction'].value_counts().to_dict()}")
print(f"  2020 alpha dist : min={s20['alpha_abs'].min():.2f}% max={s20['alpha_abs'].max():.2f}% "
      f"median={s20['alpha_abs'].median():.2f}%")
print(f"\n  2020 STOP_HIT trades:")
s20_stop = s20[s20["exit_reason"]=="STOP_HIT"]
if len(s20_stop):
    print(s20_stop[["ticker","direction","alpha","net_pnl"]].to_string())

div("9. Top tickers")
tk = sim.groupby("ticker")["net_pnl"].agg(n="count",total="sum")
tk["wr"] = sim.groupby("ticker")["win"].mean()*100
print(tk.sort_values("total",ascending=False).head(15).to_string())
