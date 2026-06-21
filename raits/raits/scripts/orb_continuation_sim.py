"""
ORB Continuation: second leg entry after ORB morning breakout.

Logic:
  1. Load ORB trades (morning 9:45-10:15)
  2. After 10:30: stock must be holding above ORB breakout level (LONG)
     or below (SHORT) — xác nhận momentum vẫn còn
  3. Find 2+ bar consolidation (range < 0.5×ATR, vol thấp)
  4. Volume resume breakout → entry same direction as ORB
  5. Stop: below consolidation low (wider than before)
  6. Exit: time stop 13:30 or chandelier 2×ATR

Usage:
    cd d:\raits\raits
    python raits/scripts/orb_continuation_sim.py
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

# ── ORB trades only (không include ORB_FADE) ─────────────────────────────────
orb = df[df["strategy"] == "ORB"].copy()
orb["date"] = orb["entry_time"].dt.normalize()
print(f"ORB trades in pkl: {len(orb)}  "
      f"({orb['hmm_state'].value_counts().to_dict()})")

# ── SPY VWAP precompute ───────────────────────────────────────────────────────
spy = data_5min.get("SPY", pd.DataFrame()).sort_index()
spy["tp"]     = (spy["high"]+spy["low"]+spy["close"])/3
spy["tpv"]    = spy["tp"]*spy["volume"]
spy["date"]   = spy.index.normalize()
spy["cum_tpv"] = spy.groupby("date")["tpv"].cumsum()
spy["cum_vol"] = spy.groupby("date")["volume"].cumsum()
spy["spy_vwap"] = spy["cum_tpv"] / spy["cum_vol"]
spy["spy_above"] = spy["close"] > spy["spy_vwap"]
_spy_dict = spy["spy_above"].reindex(
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

def simulate_trade(direction, entry_px, stop_px, bars_after, hard_exit):
    stop_dist = abs(entry_px - stop_px)
    shares    = max(1, int(500 / stop_dist)) if stop_dist > 0 else 1
    trailing  = stop_px
    exit_px   = entry_px
    reason    = "TIME_STOP"
    for _, b in bars_after[bars_after.index.time < hard_exit].iterrows():
        if direction == "LONG":
            trailing  = max(trailing, float(b["high"]) - stop_dist)
            if b["low"] <= trailing:
                exit_px = trailing; reason = "STOP_HIT"; break
            exit_px = float(b["close"])
        else:
            trailing  = min(trailing, float(b["low"]) + stop_dist)
            if b["high"] >= trailing:
                exit_px = trailing; reason = "STOP_HIT"; break
            exit_px = float(b["close"])
    pnl = (exit_px - entry_px) if direction == "LONG" else (entry_px - exit_px)
    return reason, pnl * shares - shares * 0.01 * 2, shares

# ── Precompute day_bars cache ─────────────────────────────────────────────────
print("Precomputing day bars...")
orb_pairs = set(zip(orb["ticker"], orb["date"]))
day_bars_cache = {}
for (ticker, day) in orb_pairs:
    if ticker not in data_5min: continue
    db = data_5min[ticker][data_5min[ticker].index.normalize() == day].sort_index()
    if len(db) >= 10:
        day_bars_cache[(ticker, day)] = db

# ── Core sim ──────────────────────────────────────────────────────────────────
def sim_orb_cont(ticker, day, direction, orb_entry_px, hmm_state, day_bars):
    """Scan 10:30-12:30 for consolidation then volume breakout."""
    # Pre-10:30 bars for ATR + avg vol
    pre  = day_bars[day_bars.index.time < dtime(10, 30)]
    if len(pre) < 5: return None
    atr     = compute_atr(pre)
    avg_vol = float(day_bars["volume"].mean())
    if atr <= 0: return None

    window = day_bars[(day_bars.index.time >= dtime(10, 30)) &
                      (day_bars.index.time <  dtime(12, 30))]
    if len(window) < 3: return None

    CONSOL_RANGE = 0.5 * atr
    RESUME_VOL   = 1.3
    HOLD_SLACK   = 0.5 * atr  # how far below ORB entry before we give up

    consol_bars = []

    for i, (ts, bar) in enumerate(window.iterrows()):
        # Key filter: stock must be HOLDING the ORB breakout level
        if direction == "LONG" and float(bar["close"]) < orb_entry_px - HOLD_SLACK:
            consol_bars = []
            continue
        if direction == "SHORT" and float(bar["close"]) > orb_entry_px + HOLD_SLACK:
            consol_bars = []
            continue

        bar_range = float(bar["high"]) - float(bar["low"])

        if bar_range <= CONSOL_RANGE and float(bar["volume"]) <= avg_vol * 1.2:
            # Quiet consolidation bar
            consol_bars.append((ts, bar))
        else:
            # Either a wide bar or volume surge → check for breakout
            if len(consol_bars) >= 2:
                c_high = max(float(b["high"]) for _, b in consol_bars)
                c_low  = min(float(b["low"])  for _, b in consol_bars)

                sb = spy_bull(ts)

                # LONG continuation
                if (direction == "LONG" and
                        float(bar["close"]) > c_high and
                        float(bar["volume"]) > RESUME_VOL * avg_vol and
                        sb is not False):
                    stop_px    = max(c_low - 0.2 * atr, orb_entry_px - atr)
                    bars_after = window[window.index > ts]
                    reason, pnl, sh = simulate_trade(
                        "LONG", float(bar["close"]), stop_px, bars_after, dtime(13, 30))
                    return dict(strategy="ORB_CONT", ticker=ticker, date=day,
                                year=str(day.year), direction="LONG",
                                hmm_state=hmm_state, orb_entry=orb_entry_px,
                                entry_px=float(bar["close"]), exit_reason=reason,
                                net_pnl=pnl, shares=sh, win=pnl > 0,
                                consol_n=len(consol_bars))

                # SHORT continuation
                if (direction == "SHORT" and
                        float(bar["close"]) < c_low and
                        float(bar["volume"]) > RESUME_VOL * avg_vol and
                        sb is not True):
                    stop_px    = min(c_high + 0.2 * atr, orb_entry_px + atr)
                    bars_after = window[window.index > ts]
                    reason, pnl, sh = simulate_trade(
                        "SHORT", float(bar["close"]), stop_px, bars_after, dtime(13, 30))
                    return dict(strategy="ORB_CONT", ticker=ticker, date=day,
                                year=str(day.year), direction="SHORT",
                                hmm_state=hmm_state, orb_entry=orb_entry_px,
                                entry_px=float(bar["close"]), exit_reason=reason,
                                net_pnl=pnl, shares=sh, win=pnl > 0,
                                consol_n=len(consol_bars))

            # Reset consolidation tracking
            consol_bars = []

    return None

# ── Run ───────────────────────────────────────────────────────────────────────
print(f"Running ORB continuation sim on {len(orb_pairs)} ticker-day pairs...")
signals = []
for _, row in orb.iterrows():
    ticker = row["ticker"]
    day    = row["date"]
    db     = day_bars_cache.get((ticker, day))
    if db is None: continue
    r = sim_orb_cont(
        ticker, day,
        direction    = row.get("direction","LONG"),
        orb_entry_px = float(row["entry_price"]),
        hmm_state    = row.get("hmm_state","?"),
        day_bars     = db,
    )
    if r: signals.append(r)

sim = pd.DataFrame(signals) if signals else pd.DataFrame()

# ── Report ────────────────────────────────────────────────────────────────────
def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)
orb_pnl     = df[df["strategy"]=="ORB"]["net_pnl"].sum()
orb_n       = len(orb)

print(f"\n{'='*72}")
print(f"  ORB CONTINUATION SIM")
print(f"{'='*72}")
print(f"\n  ORB morning trades         : {orb_n}t  ${orb_pnl:>+,.0f}")
print(f"  ORB CONT signals           : {len(sim)}t")
print(f"  Conversion rate            : {len(sim)/orb_n*100:.1f}% of ORB trades → continuation")

if len(sim) == 0:
    print("\n  No signals generated.")
else:
    print(f"\n  Total P&L                  : ${sim['net_pnl'].sum():>+,.0f}")
    print(f"  Win rate                   : {sim['win'].mean()*100:.1f}%")
    print(f"  Avg P&L / trade            : ${sim['net_pnl'].mean():>+.1f}")
    print(f"  System + ORB CONT          : ${current_sys + sim['net_pnl'].sum():>+,.0f}")

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
    for d in ["LONG","SHORT"]:
        s = sim[sim["direction"]==d]
        if len(s):
            print(f"  {d}: {len(s):>4}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")

    div("By HMM regime")
    for st in sim["hmm_state"].unique():
        s = sim[sim["hmm_state"]==st]
        print(f"  {st:<10} {len(s):>4}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")

    div("Consolidation length (bars before breakout)")
    for n in sorted(sim["consol_n"].unique()):
        s = sim[sim["consol_n"]==n]
        print(f"  {n} bars: {len(s):>3}t  ${s['net_pnl'].sum():>+7,.0f}  WR={s['win'].mean()*100:.0f}%")

    div("Top 10 tickers")
    tk = sim.groupby("ticker")["net_pnl"].agg(n="count", total="sum").sort_values("total",ascending=False)
    print(tk.head(10).to_string())

    div("Comparison summary")
    print(f"\n  Current system             : ${current_sys:>+,.0f}")
    print(f"  + ORB CONT                 : ${sim['net_pnl'].sum():>+,.0f}")
    print(f"  New system estimate        : ${current_sys + sim['net_pnl'].sum():>+,.0f}")
    print(f"\n  Current ORB (morning)      : {orb_n:>4}t  ${orb_pnl:>+,.0f}  avg=${orb_pnl/orb_n:>+.1f}")
    print(f"  ORB CONT (midday)          : {len(sim):>4}t  ${sim['net_pnl'].sum():>+,.0f}  avg=${sim['net_pnl'].mean():>+.1f}")
