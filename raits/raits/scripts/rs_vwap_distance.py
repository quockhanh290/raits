"""
RS Momentum với real-time VWAP distance filter.

Tại 10:35: nếu stock extended >X×ATR khỏi VWAP → direct entry ngay
           nếu stock gần VWAP → đợi explicit VWAP touch (10:35-12:00)

Test X = 0.5, 1.0, 1.5, 2.0 để tìm optimal threshold.
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

def compute_ticker_vwap(day_bars, at_ts):
    """Cumulative VWAP for ticker up to bar at_ts."""
    pre = day_bars[day_bars.index <= at_ts].copy()
    pre["tp"]  = (pre["high"]+pre["low"]+pre["close"])/3
    pre["tpv"] = pre["tp"]*pre["volume"]
    cum_tpv = pre["tpv"].sum()
    cum_vol = pre["volume"].sum()
    return cum_tpv / cum_vol if cum_vol > 0 else float(pre["close"].iloc[-1])

def run_rs_sim(vwap_dist_mult, min_alpha=0.008, exit_time=dtime(13,30)):
    """
    vwap_dist_mult: nếu |price - vwap| > vwap_dist_mult × ATR tại 10:35
                    → direct entry ngay
                    else → wait for VWAP touch (10:35-12:00)
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

        for candidates, direction in [(top_longs[:1], "LONG"), (top_shorts[:1], "SHORT")]:
            for ticker, alpha in candidates:
                db = day_bars_cache.get((ticker, day))
                if db is None: continue

                pre_1035 = db[db.index.time < dtime(10, 35)]
                if len(pre_1035) < 5: continue
                atr = compute_atr(pre_1035)
                if atr <= 0: continue

                # Bar at 10:35
                bar_1035 = db[db.index.time <= dtime(10, 35)]
                if bar_1035.empty: continue
                ts_1035  = bar_1035.index[-1]
                px_1035  = float(bar_1035.iloc[-1]["close"])
                vwap_1035 = compute_ticker_vwap(db, ts_1035)

                dist_from_vwap = (px_1035 - vwap_1035) if direction == "LONG" else (vwap_1035 - px_1035)

                if dist_from_vwap > vwap_dist_mult * atr:
                    # Stock is extended away from VWAP → direct entry at 10:35
                    entry_ts = ts_1035
                    entry_px = px_1035
                    entry_type = "direct"
                else:
                    # Not extended → wait for explicit VWAP touch (10:35-12:00)
                    window = db[(db.index.time >= dtime(10,35)) &
                                (db.index.time <  dtime(12, 0))]
                    entry_ts = None; entry_px = None; entry_type = "vwap_touch"
                    for ts, bar in window.iterrows():
                        vwap_t = compute_ticker_vwap(db, ts)
                        dist   = (float(bar["close"]) - vwap_t) if direction=="LONG" else (vwap_t - float(bar["close"]))
                        # VWAP touch: price crosses to within 0.5×ATR
                        if abs(float(bar["close"]) - vwap_t) <= 0.5 * atr:
                            entry_ts = ts; entry_px = float(bar["close"]); break

                    if entry_ts is None: continue   # no touch → skip

                # SPY filter
                sb = spy_bull(entry_ts)
                if direction == "LONG"  and sb is False: continue
                if direction == "SHORT" and sb is True:  continue

                stop_px    = (entry_px - 1.5*atr) if direction=="LONG" else (entry_px + 1.5*atr)
                bars_after = db[db.index > entry_ts]
                reason, pnl, sh = simulate_trade(direction, entry_px, stop_px, bars_after, exit_time)

                signals.append(dict(ticker=ticker, date=day, year=str(day.year),
                                    direction=direction, alpha=round(alpha*100,2),
                                    entry_type=entry_type, exit_reason=reason,
                                    net_pnl=pnl, shares=sh, win=pnl>0))
    return pd.DataFrame(signals)

# ── Grid search ───────────────────────────────────────────────────────────────
current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)

print(f"\n{'='*72}")
print(f"  RS MOMENTUM — VWAP DISTANCE THRESHOLD GRID")
print(f"{'='*72}")
print(f"\n  Current system: ${current_sys:>+,.0f}\n")
print(f"  {'dist>X×ATR':>12} {'n':>6} {'P&L':>9} {'WR':>5} {'avg':>7} "
      f"{'sys':>9} {'direct':>8} {'vwap_t':>8}")
print(f"  {'─'*70}")

best_sim = None
best_pnl = -999999

for mult in [0.0, 0.5, 1.0, 1.5, 2.0, 99.0]:
    label = "always direct" if mult == 0.0 else \
            "always wait"   if mult == 99.0 else f">{mult}×ATR direct"
    sim = run_rs_sim(mult)
    if len(sim) == 0:
        print(f"  {label:>12}: no signals"); continue
    pnl = sim["net_pnl"].sum()
    wr  = sim["win"].mean()*100
    avg = sim["net_pnl"].mean()
    sys = current_sys + pnl
    n_d = (sim["entry_type"]=="direct").sum()
    n_v = (sim["entry_type"]=="vwap_touch").sum()
    print(f"  {label:>12} {len(sim):>6} {pnl:>+9,.0f} {wr:>4.0f}% {avg:>+7.1f} "
          f"{sys:>+9,.0f} {n_d:>8} {n_v:>8}")
    if pnl > best_pnl:
        best_pnl = pnl
        best_sim = (mult, sim)

# ── Detail on best threshold ──────────────────────────────────────────────────
if best_sim:
    mult, sim = best_sim
    label = "always direct" if mult==0 else "always wait" if mult==99 else f">{mult}×ATR"
    print(f"\n{'─'*72}")
    print(f"  BEST THRESHOLD: {label}")
    print(f"{'─'*72}")
    for yr in ["2020","2021","2022"]:
        s = sim[sim["year"]==yr]
        if len(s):
            print(f"  {yr}: {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  "
                  f"WR={s['win'].mean()*100:.0f}%  "
                  f"direct={( s['entry_type']=='direct').sum()}  "
                  f"vwap_touch={(s['entry_type']=='vwap_touch').sum()}")
    print()
    for r in sim["exit_reason"].unique():
        s = sim[sim["exit_reason"]==r]
        print(f"  {r:<14} {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")
    for et in sim["entry_type"].unique():
        s = sim[sim["entry_type"]==et]
        print(f"  {et:<14} {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")
