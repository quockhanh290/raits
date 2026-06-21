"""
Retroactive sim: 3 midday strategies (10:15-14:00) on Normal regime days.

A: Bull Flag Continuation  — breakout khỏi consolidation zone
B: VWAP Reclaim            — price cross lại VWAP với volume
C: HOD/LOD Breakout        — break morning HOD/LOD sau 11:00

Usage:
    cd d:\raits\raits
    python raits/scripts/midday_strat_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_scenario_g.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

# ── Load data ─────────────────────────────────────────────────────────────────
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

# Normal days from TF trades
tf_normal = df[(df["strategy"]=="TREND_FOLLOW") & (df["hmm_state"]=="Normal")].copy()
tf_normal["date"] = tf_normal["entry_time"].dt.normalize()
normal_days = sorted(tf_normal["date"].unique())
tf_tickers  = df[df["strategy"]=="TREND_FOLLOW"]["ticker"].value_counts().head(30).index.tolist()

# ── SPY VWAP series ───────────────────────────────────────────────────────────
spy = data_5min.get("SPY", pd.DataFrame()).sort_index()
spy["tp"]  = (spy["high"]+spy["low"]+spy["close"])/3
spy["tpv"] = spy["tp"]*spy["volume"]
spy["date"] = spy.index.normalize()
spy["cum_tpv"] = spy.groupby("date")["tpv"].cumsum()
spy["cum_vol"] = spy.groupby("date")["volume"].cumsum()
spy["spy_vwap"] = spy["cum_tpv"] / spy["cum_vol"]
spy["spy_above"] = spy["close"] > spy["spy_vwap"]
# Precompute lookup: timestamp → bool (forward-fill so any ts lookup is O(1))
_spy_above_ser = spy["spy_above"].reindex(
    pd.date_range(spy.index[0], spy.index[-1], freq="5min"), method="ffill"
)
_spy_above_dict = _spy_above_ser.to_dict()

def get_spy_above_vwap(ts):
    # Round down to nearest 5-min bar
    ts5 = ts.floor("5min")
    return _spy_above_dict.get(ts5, None)

def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    return float(tr.tail(period).mean())

def simulate_trade(direction, entry_px, stop_px, bars_after, hard_exit):
    """Walk bars, return (exit_px, exit_reason, net_pnl)."""
    stop_dist = abs(entry_px - stop_px)
    shares    = max(1, int(500 / stop_dist)) if stop_dist > 0 else 1
    exit_px   = entry_px
    reason    = "TIME_STOP"
    trailing  = stop_px

    for _, b in bars_after[bars_after.index.time < hard_exit].iterrows():
        if direction == "LONG":
            new_trail = float(b["high"]) - stop_dist  # chandelier-lite
            trailing = max(trailing, new_trail)
            if b["low"] <= trailing:
                exit_px = trailing; reason = "STOP_HIT"; break
            exit_px = float(b["close"])
        else:
            new_trail = float(b["low"]) + stop_dist
            trailing = min(trailing, new_trail)
            if b["high"] >= trailing:
                exit_px = trailing; reason = "STOP_HIT"; break
            exit_px = float(b["close"])

    pnl_per_share = (exit_px - entry_px) if direction=="LONG" else (entry_px - exit_px)
    gross = pnl_per_share * shares
    costs = shares * 0.01 * 2
    return exit_px, reason, gross - costs, shares

# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY A: Bull Flag Continuation
# ═══════════════════════════════════════════════════════════════════════════════
def sim_A(ticker, day, day_bars):
    """Consolidation (2+ bars range < 0.35×ATR) → volume breakout."""
    window = day_bars[(day_bars.index.time >= dtime(10,30)) &
                      (day_bars.index.time <  dtime(13, 0))]
    if len(window) < 3: return None

    atr = compute_atr(day_bars[day_bars.index.time < dtime(10,30)])
    if atr <= 0: return None

    avg_vol = day_bars["volume"].mean()
    CONSOL_RANGE = 0.35 * atr
    BREAK_VOL    = 1.5

    consol_bars = []
    for i, (ts, bar) in enumerate(window.iterrows()):
        bar_range = bar["high"] - bar["low"]
        if bar_range <= CONSOL_RANGE:
            consol_bars.append((ts, bar))
        else:
            if len(consol_bars) >= 2:
                # Breakout candidate
                consol_highs = [b["high"] for _, b in consol_bars]
                consol_lows  = [b["low"]  for _, b in consol_bars]
                c_high = max(consol_highs)
                c_low  = min(consol_lows)

                spy_bull = get_spy_above_vwap(ts)

                if bar["close"] > c_high and bar["volume"] > BREAK_VOL * avg_vol:
                    if spy_bull is not False:  # LONG only when SPY not bearish
                        stop_px = c_low
                        bars_after = window[window.index > ts]
                        ep, reason, pnl, sh = simulate_trade(
                            "LONG", float(bar["close"]), stop_px, bars_after, dtime(13,30))
                        return dict(strategy="A_BullFlag", ticker=ticker, date=day,
                                    year=str(day.year), direction="LONG",
                                    entry_px=float(bar["close"]), exit_reason=reason,
                                    net_pnl=pnl, shares=sh, win=pnl>0)

                elif bar["close"] < c_low and bar["volume"] > BREAK_VOL * avg_vol:
                    if spy_bull is True:  # skip SHORT when SPY bullish
                        pass
                    else:
                        stop_px = c_high
                        bars_after = window[window.index > ts]
                        ep, reason, pnl, sh = simulate_trade(
                            "SHORT", float(bar["close"]), stop_px, bars_after, dtime(13,30))
                        return dict(strategy="A_BullFlag", ticker=ticker, date=day,
                                    year=str(day.year), direction="SHORT",
                                    entry_px=float(bar["close"]), exit_reason=reason,
                                    net_pnl=pnl, shares=sh, win=pnl>0)
            consol_bars = []  # reset

    return None

# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY B: VWAP Reclaim
# ═══════════════════════════════════════════════════════════════════════════════
def sim_B(ticker, day, day_bars):
    """First VWAP cross in 10:15-13:30 window with volume, aligned with SPY."""
    window = day_bars[(day_bars.index.time >= dtime(10,15)) &
                      (day_bars.index.time <  dtime(13,30))]
    if len(window) < 2: return None

    # Compute ticker VWAP
    day_bars = day_bars.copy()
    day_bars["tp"]  = (day_bars["high"]+day_bars["low"]+day_bars["close"])/3
    day_bars["tpv"] = day_bars["tp"]*day_bars["volume"]
    day_bars["cum_tpv"] = day_bars["tpv"].cumsum()
    day_bars["cum_vol"] = day_bars["volume"].cumsum()
    day_bars["vwap"] = day_bars["cum_tpv"] / day_bars["cum_vol"].replace(0, np.nan)

    atr     = compute_atr(day_bars[day_bars.index.time < dtime(10,15)])
    avg_vol = day_bars["volume"].mean()
    if atr <= 0: return None

    prev_above = None
    for i in range(1, len(window)):
        ts      = window.index[i]
        bar     = window.iloc[i]
        prev    = window.iloc[i-1]
        vwap    = day_bars.loc[ts, "vwap"] if ts in day_bars.index else np.nan
        if pd.isna(vwap): continue

        curr_above = bar["close"] > vwap
        if prev_above is None:
            prev_above = prev["close"] > day_bars.loc[window.index[i-1], "vwap"] \
                if window.index[i-1] in day_bars.index else curr_above
            continue

        cross_up   = (not prev_above) and curr_above
        cross_down = prev_above and (not curr_above)

        spy_bull = get_spy_above_vwap(ts)

        if cross_up and bar["volume"] > 1.2 * avg_vol and spy_bull is not False:
            stop_px    = vwap - 0.2 * atr   # just below VWAP
            bars_after = window[window.index > ts]
            ep, reason, pnl, sh = simulate_trade(
                "LONG", float(bar["close"]), stop_px, bars_after, dtime(14,0))
            return dict(strategy="B_VWAPReclaim", ticker=ticker, date=day,
                        year=str(day.year), direction="LONG",
                        entry_px=float(bar["close"]), exit_reason=reason,
                        net_pnl=pnl, shares=sh, win=pnl>0)

        elif cross_down and bar["volume"] > 1.2 * avg_vol and spy_bull is not True:
            stop_px    = vwap + 0.2 * atr
            bars_after = window[window.index > ts]
            ep, reason, pnl, sh = simulate_trade(
                "SHORT", float(bar["close"]), stop_px, bars_after, dtime(14,0))
            return dict(strategy="B_VWAPReclaim", ticker=ticker, date=day,
                        year=str(day.year), direction="SHORT",
                        entry_px=float(bar["close"]), exit_reason=reason,
                        net_pnl=pnl, shares=sh, win=pnl>0)

        prev_above = curr_above

    return None

# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY C: HOD/LOD Breakout after 11:00
# ═══════════════════════════════════════════════════════════════════════════════
def sim_C(ticker, day, day_bars):
    """Break above morning HOD (9:30-11:00) after 11:00 with volume + SPY bull."""
    morning = day_bars[day_bars.index.time < dtime(11, 0)]
    if len(morning) < 4: return None

    morning_hod = float(morning["high"].max())
    morning_lod = float(morning["low"].min())

    window = day_bars[(day_bars.index.time >= dtime(11, 0)) &
                      (day_bars.index.time <  dtime(13, 30))]
    if len(window) < 2: return None

    atr     = compute_atr(morning)
    avg_vol = day_bars["volume"].mean()
    if atr <= 0: return None

    for i in range(1, len(window)):
        ts   = window.index[i]
        bar  = window.iloc[i]
        prev = window.iloc[i-1]
        spy_bull = get_spy_above_vwap(ts)

        # LONG: break above morning HOD
        if (prev["close"] <= morning_hod and
                bar["close"] > morning_hod and
                bar["volume"] > 1.5 * avg_vol and
                spy_bull is not False):
            stop_px    = morning_hod - 0.5 * atr
            bars_after = window[window.index > ts]
            ep, reason, pnl, sh = simulate_trade(
                "LONG", float(bar["close"]), stop_px, bars_after, dtime(13,30))
            return dict(strategy="C_HODBreakout", ticker=ticker, date=day,
                        year=str(day.year), direction="LONG",
                        entry_px=float(bar["close"]), exit_reason=reason,
                        net_pnl=pnl, shares=sh, win=pnl>0)

        # SHORT: break below morning LOD (only when SPY bearish)
        if (prev["close"] >= morning_lod and
                bar["close"] < morning_lod and
                bar["volume"] > 1.5 * avg_vol and
                spy_bull is False):
            stop_px    = morning_lod + 0.5 * atr
            bars_after = window[window.index > ts]
            ep, reason, pnl, sh = simulate_trade(
                "SHORT", float(bar["close"]), stop_px, bars_after, dtime(13,30))
            return dict(strategy="C_HODBreakout", ticker=ticker, date=day,
                        year=str(day.year), direction="SHORT",
                        entry_px=float(bar["close"]), exit_reason=reason,
                        net_pnl=pnl, shares=sh, win=pnl>0)

    return None

# ═══════════════════════════════════════════════════════════════════════════════
# RUN ALL 3
# ═══════════════════════════════════════════════════════════════════════════════
print(f"Precomputing day bars...")
# Build {(ticker, date): DataFrame} lookup — avoid O(N) slice per iteration
day_bars_cache = {}
for ticker in tf_tickers:
    if ticker not in data_5min: continue
    bars = data_5min[ticker]
    for day in normal_days:
        db = bars[bars.index.normalize() == day].sort_index()
        if len(db) >= 10:
            day_bars_cache[(ticker, day)] = db

print(f"Simulating 3 strategies on {len(normal_days)} Normal days × {len(tf_tickers)} tickers...")

signals = {k: [] for k in ["A_BullFlag","B_VWAPReclaim","C_HODBreakout"]}

for day in normal_days:
    for ticker in tf_tickers:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue

        r = sim_A(ticker, day, db)
        if r: signals["A_BullFlag"].append(r)

        r = sim_B(ticker, day, db)
        if r: signals["B_VWAPReclaim"].append(r)

        r = sim_C(ticker, day, db)
        if r: signals["C_HODBreakout"].append(r)

# ── Results ───────────────────────────────────────────────────────────────────
def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)
tf_pnl      = df[df["strategy"]=="TREND_FOLLOW"]["net_pnl"].sum()

print(f"\n{'='*72}")
print(f"  MIDDAY STRATEGY COMPARISON  (Normal days, 10:15-14:00)")
print(f"{'='*72}")
print(f"\n  Current TF (14:00-15:55)     : 275t  ${tf_pnl:>+8,.0f}  WR={((df[df['strategy']=='TREND_FOLLOW']['net_pnl']>0).mean()*100):.0f}%")
print(f"  Current system               :       ${current_sys:>+8,.0f}")

print(f"\n  {'Strategy':<22} {'Trades':>7} {'P&L':>9} {'WR':>6} {'avg/t':>7} {'sys':>10}")
print(f"  {'─'*62}")

best = None
for name, sigs in signals.items():
    if not sigs:
        print(f"  {name:<22} {'0':>7} {'—':>9}")
        continue
    sim = pd.DataFrame(sigs)
    n   = len(sim)
    pnl = sim["net_pnl"].sum()
    wr  = sim["win"].mean()*100
    avg = sim["net_pnl"].mean()
    sys = current_sys + pnl
    print(f"  {name:<22} {n:>7} {pnl:>+9,.0f} {wr:>5.0f}% {avg:>+7.1f} {sys:>+10,.0f}")
    if best is None or pnl > best[1]:
        best = (name, pnl, sim)

# Detail on each
for name, sigs in signals.items():
    if not sigs: continue
    sim = pd.DataFrame(sigs)
    div(f"{name} — detail")

    print(f"\n  By year:")
    for yr in ["2020","2021","2022"]:
        s = sim[sim["year"]==yr]
        if len(s):
            print(f"    {yr}: {len(s):>4}t  ${s['net_pnl'].sum():>+8,.0f}  "
                  f"WR={s['win'].mean()*100:.0f}%  avg=${s['net_pnl'].mean():>+.1f}")

    print(f"\n  By direction:")
    for d in ["LONG","SHORT"]:
        s = sim[sim["direction"]==d]
        if len(s):
            print(f"    {d}: {len(s):>4}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")

    print(f"\n  By exit reason:")
    for r in sim["exit_reason"].unique():
        s = sim[sim["exit_reason"]==r]
        print(f"    {r:<12} {len(s):>4}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")

    print(f"\n  Signals/day: {len(sim)/len(normal_days):.2f}")
    print(f"\n  Top 10 tickers:")
    tk = sim.groupby("ticker")["net_pnl"].agg(n="count",total="sum").sort_values("total",ascending=False)
    print(tk.head(10).to_string())
