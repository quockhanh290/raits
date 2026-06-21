"""
Sim 2 midday strategies:

Strategy 1 — Gap Fill (10:30-13:30)
  Stock gap up >1.5% so với prev close → SHORT until gap fills
  Stock gap down >1.5%               → LONG until gap fills
  Entry: 10:30 nếu gap mới fill được 30-85%
  Stop: morning HOD/LOD

Strategy 2 — Relative Strength Momentum (10:35-13:30)
  At 10:30: rank tickers by alpha = stock_return - SPY_return (từ session open)
  Top alpha (>+0.8%) → LONG; bottom alpha (<-0.8%) → SHORT
  Entry: first VWAP touch after 10:30 (or 10:35 nếu không có touch)
  Stop: 1.5×ATR

Usage:
    cd d:\raits\raits
    python raits/scripts/midday_gap_rs_sim.py
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
df = pd.DataFrame(rows)
df["entry_time"] = pd.to_datetime(df["entry_time"])

# Normal days (same universe as before)
tf_normal = df[(df["strategy"]=="TREND_FOLLOW") & (df["hmm_state"]=="Normal")].copy()
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

# ── Helpers ───────────────────────────────────────────────────────────────────
def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

def simulate_trade(direction, entry_px, stop_px, bars_after, hard_exit, target_px=None):
    stop_dist = abs(entry_px - stop_px)
    shares    = max(1, int(500 / stop_dist)) if stop_dist > 0 else 1
    trailing  = stop_px
    exit_px   = entry_px
    reason    = "TIME_STOP"
    for _, b in bars_after[bars_after.index.time < hard_exit].iterrows():
        if direction == "LONG":
            trailing = max(trailing, float(b["high"]) - stop_dist)
            if b["low"] <= trailing:
                exit_px = trailing; reason = "STOP_HIT"; break
            if target_px and b["high"] >= target_px:
                exit_px = target_px; reason = "TARGET_HIT"; break
            exit_px = float(b["close"])
        else:
            trailing = min(trailing, float(b["low"]) + stop_dist)
            if b["high"] >= trailing:
                exit_px = trailing; reason = "STOP_HIT"; break
            if target_px and b["low"] <= target_px:
                exit_px = target_px; reason = "TARGET_HIT"; break
            exit_px = float(b["close"])
    pnl = (exit_px - entry_px) if direction=="LONG" else (entry_px - exit_px)
    return reason, pnl * shares - shares * 0.01 * 2, shares

# ── Precompute prev_close ──────────────────────────────────────────────────────
print("Precomputing prev_close and day bars...")
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

# SPY day bars for alpha calculation
spy_day_cache = {}
for day in normal_days:
    sd = spy[spy.index.normalize() == day].sort_index()
    if len(sd) >= 4:
        spy_day_cache[day] = sd

# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY 1: GAP FILL
# ═══════════════════════════════════════════════════════════════════════════════
MIN_GAP_PCT   = 0.015   # 1.5% minimum gap
MIN_RETRACE   = 0.30    # must have retraced 30%+ (some momentum toward fill)
MAX_RETRACE   = 0.85    # not already filled (>85% means we're late)

def sim_gap_fill(ticker, day, day_bars):
    prev_c = prev_close_map.get((ticker, day))
    if prev_c is None or prev_c <= 0: return None

    # Session open = first bar open
    first_bar = day_bars[day_bars.index.time >= dtime(9, 30)]
    if first_bar.empty: return None
    session_open = float(first_bar.iloc[0]["open"])
    gap_pct = (session_open - prev_c) / prev_c   # positive = gap up

    if abs(gap_pct) < MIN_GAP_PCT: return None
    gap_size  = session_open - prev_c   # signed

    # At 10:30: where is price relative to gap?
    pre_entry = day_bars[day_bars.index.time <= dtime(10, 30)]
    if pre_entry.empty: return None
    px_1030 = float(pre_entry.iloc[-1]["close"])

    # How much of gap has been retraced?
    retrace = (session_open - px_1030) / gap_size if gap_size != 0 else 0
    if not (MIN_RETRACE <= retrace <= MAX_RETRACE): return None

    # Morning HOD/LOD for stop
    morning_hod = float(pre_entry["high"].max())
    morning_lod = float(pre_entry["low"].min())

    atr = compute_atr(pre_entry)
    if atr <= 0: return None

    direction = "SHORT" if gap_pct > 0 else "LONG"
    entry_px  = px_1030

    if direction == "SHORT":
        stop_px   = morning_hod + 0.1 * atr   # tiny buffer above HOD
        target_px = prev_c
        sb = spy_bull(pre_entry.index[-1])
        if sb is True: return None  # skip SHORT when SPY strongly bullish
    else:
        stop_px   = morning_lod - 0.1 * atr
        target_px = prev_c
        sb = spy_bull(pre_entry.index[-1])
        if sb is False: return None  # skip LONG when SPY strongly bearish

    bars_after = day_bars[day_bars.index.time > dtime(10, 30)]
    reason, pnl, sh = simulate_trade(
        direction, entry_px, stop_px, bars_after, dtime(13, 30), target_px)

    return dict(strategy="GapFill", ticker=ticker, date=day, year=str(day.year),
                direction=direction, gap_pct=round(gap_pct*100,2),
                retrace=round(retrace,2), entry_px=entry_px, stop_px=stop_px,
                target_px=target_px, exit_reason=reason, net_pnl=pnl,
                shares=sh, win=pnl>0)

# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY 2: RELATIVE STRENGTH MOMENTUM
# ═══════════════════════════════════════════════════════════════════════════════
MIN_ALPHA = 0.008   # 0.8% outperformance vs SPY to qualify

def get_alpha_1030(ticker, day, day_bars):
    """Return alpha (stock excess return vs SPY) from session open to 10:30."""
    # Stock open
    first = day_bars[day_bars.index.time >= dtime(9, 30)]
    if first.empty: return None
    stock_open = float(first.iloc[0]["open"])
    stock_1030 = day_bars[day_bars.index.time <= dtime(10, 30)]
    if stock_1030.empty: return None
    stock_px   = float(stock_1030.iloc[-1]["close"])
    stock_ret  = (stock_px - stock_open) / stock_open if stock_open > 0 else 0

    # SPY
    sd = spy_day_cache.get(day)
    if sd is None: return None
    spy_first = sd[sd.index.time >= dtime(9, 30)]
    if spy_first.empty: return None
    spy_open   = float(spy_first.iloc[0]["open"])
    spy_1030   = sd[sd.index.time <= dtime(10, 30)]
    if spy_1030.empty: return None
    spy_px     = float(spy_1030.iloc[-1]["close"])
    spy_ret    = (spy_px - spy_open) / spy_open if spy_open > 0 else 0

    return stock_ret - spy_ret   # alpha (excess return)

def sim_rs_momentum(ticker, day, day_bars, alpha):
    """Trade in direction of RS from 10:35 with VWAP-touch entry."""
    direction = "LONG" if alpha > 0 else "SHORT"

    # Compute VWAP for this ticker
    db = day_bars.copy()
    db["tp"]  = (db["high"]+db["low"]+db["close"])/3
    db["tpv"] = db["tp"]*db["volume"]
    db["cum_tpv"] = db["tpv"].cumsum()
    db["cum_vol"] = db["volume"].cumsum()
    db["vwap"] = db["cum_tpv"] / db["cum_vol"].replace(0, np.nan)

    atr = compute_atr(day_bars[day_bars.index.time < dtime(10, 30)])
    if atr <= 0: return None

    window = db[(db.index.time >= dtime(10, 35)) &
                (db.index.time <  dtime(12, 30))]
    if window.empty: return None

    # Look for VWAP touch (price within 0.5×ATR of VWAP) then entry
    # If no touch by 11:30 → direct entry at 10:35 (stock running, don't wait)
    entry_bar = None
    for ts, bar in window.iterrows():
        vwap = db.loc[ts, "vwap"] if ts in db.index else np.nan
        if pd.isna(vwap): continue
        if abs(float(bar["close"]) - float(vwap)) <= 0.5 * atr:
            entry_bar = (ts, bar)
            break

    # No VWAP touch → direct entry at first bar if within 12:00
    if entry_bar is None:
        first = window[window.index.time <= dtime(10, 40)]
        if first.empty: return None
        ts  = first.index[0]
        bar = first.iloc[0]
        entry_bar = (ts, bar)

    ts, bar = entry_bar
    entry_px = float(bar["close"])
    stop_px  = (entry_px - 1.5 * atr) if direction == "LONG" else (entry_px + 1.5 * atr)

    # SPY direction filter
    sb = spy_bull(ts)
    if direction == "LONG"  and sb is False: return None
    if direction == "SHORT" and sb is True:  return None

    bars_after = window[window.index > ts]
    reason, pnl, sh = simulate_trade(
        direction, entry_px, stop_px, bars_after, dtime(13, 30))

    return dict(strategy="RS_Momentum", ticker=ticker, date=day, year=str(day.year),
                direction=direction, alpha=round(alpha*100,2),
                entry_px=entry_px, exit_reason=reason,
                net_pnl=pnl, shares=sh, win=pnl>0)

# ── Run ───────────────────────────────────────────────────────────────────────
print(f"Running on {len(normal_days)} Normal days × {len(available_tickers)} tickers...")

gap_signals = []
rs_signals  = []

for day in normal_days:
    # ── Gap fill: all tickers ──
    for ticker in available_tickers:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        r = sim_gap_fill(ticker, day, db)
        if r: gap_signals.append(r)

    # ── RS: compute alpha for all tickers, take top/bottom ──
    alphas = {}
    for ticker in available_tickers:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        a = get_alpha_1030(ticker, day, db)
        if a is not None:
            alphas[ticker] = a

    if not alphas: continue

    # Top LONG: highest positive alpha
    top_longs  = [(tk, a) for tk, a in alphas.items() if a >  MIN_ALPHA]
    top_shorts = [(tk, a) for tk, a in alphas.items() if a < -MIN_ALPHA]

    top_longs.sort(key=lambda x: x[1], reverse=True)
    top_shorts.sort(key=lambda x: x[1])

    # Take top 1 LONG and top 1 SHORT per day
    for ticker, alpha in top_longs[:1]:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        r = sim_rs_momentum(ticker, day, db, alpha)
        if r: rs_signals.append(r)

    for ticker, alpha in top_shorts[:1]:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        r = sim_rs_momentum(ticker, day, db, alpha)
        if r: rs_signals.append(r)

# ── Report ────────────────────────────────────────────────────────────────────
def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)

def report(name, signals):
    sim = pd.DataFrame(signals) if signals else pd.DataFrame()
    print(f"\n{'='*72}")
    print(f"  {name}")
    print(f"{'='*72}")
    if len(sim) == 0:
        print("  No signals."); return

    print(f"\n  Signals        : {len(sim)}")
    print(f"  Total P&L      : ${sim['net_pnl'].sum():>+,.0f}")
    print(f"  Win rate       : {sim['win'].mean()*100:.1f}%")
    print(f"  Avg / trade    : ${sim['net_pnl'].mean():>+.1f}")
    print(f"  Signals/day    : {len(sim)/len(normal_days):.2f}")
    print(f"  System + strat : ${current_sys + sim['net_pnl'].sum():>+,.0f}")

    div("By year")
    for yr in ["2020","2021","2022"]:
        s = sim[sim["year"]==yr]
        if len(s):
            print(f"  {yr}: {len(s):>4}t  ${s['net_pnl'].sum():>+8,.0f}  "
                  f"WR={s['win'].mean()*100:.0f}%  avg=${s['net_pnl'].mean():>+.1f}")

    div("By exit reason")
    for r in sim["exit_reason"].unique():
        s = sim[sim["exit_reason"]==r]
        print(f"  {r:<14} {len(s):>4}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")

    div("By direction")
    for d in sim["direction"].unique():
        s = sim[sim["direction"]==d]
        print(f"  {d}: {len(s):>4}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")

    div("Top 10 tickers")
    tk = sim.groupby("ticker")["net_pnl"].agg(n="count",total="sum").sort_values("total",ascending=False)
    print(tk.head(10).to_string())

report("STRATEGY 1: GAP FILL (10:30-13:30)", gap_signals)
report("STRATEGY 2: RS MOMENTUM (10:35-13:30)", rs_signals)

# Combined
print(f"\n{'='*72}")
print(f"  COMBINED SUMMARY")
print(f"{'='*72}")
print(f"\n  Current system     : ${current_sys:>+,.0f}")
all_sigs = gap_signals + rs_signals
if all_sigs:
    combined_pnl = sum(s["net_pnl"] for s in all_sigs)
    print(f"  Gap Fill           : ${sum(s['net_pnl'] for s in gap_signals):>+,.0f}  ({len(gap_signals)}t)")
    print(f"  RS Momentum        : ${sum(s['net_pnl'] for s in rs_signals):>+,.0f}  ({len(rs_signals)}t)")
    print(f"  System + both      : ${current_sys + combined_pnl:>+,.0f}")
