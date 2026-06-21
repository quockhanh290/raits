"""
pre_tf_sim.py — Pre-TREND_FOLLOW entry at 13:00 (Normal regime)

TREND_FOLLOW fires at 14:00. Hypothesis: stocks already at/near HOD or LOD
by 13:00 with SPY confirming direction will continue into the afternoon.
Entering earlier gets a tighter stop (1-hr range) vs TF's wider stop.

Signal (fires once at 13:00):
  SPY bullish (close[13:00] > open > ±0.1%) + stock close ≥ 99% morning HOD → LONG
  SPY bearish (close[13:00] < open > ±0.1%) + stock close ≤ 101% morning LOD → SHORT

Stop:    1-hour low/high (12:00-12:59) ± 0.1×ATR  [recent support/resistance]
Target:  2R
Hold:    to 15:55 (same as TF — capture full afternoon)
Cap:     3 positions/day, sorted by proximity to HOD/LOD (most extreme first)
Max stop: ≤ 2% of entry

Engine conditions replicated:
  - Normal regime (from pkl hmm_state)
  - SMA50 < SMA200 → block LONG (same as engine ORB + TF)
  - SPY directional filter at 13:00

Usage:
  cd d:\\raits\\raits
  python raits\\scripts\\pre_tf_sim.py
"""

import pickle
import sys
import os
from collections import defaultdict
from datetime import time as dtime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

PKL_RESULTS = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots", "results_scenario_g.pkl")
PKL_5MIN    = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")

MORNING_START  = dtime(9, 30)
MORNING_END    = dtime(12, 59)
HOUR_START     = dtime(12, 0)
ENTRY_TIME     = dtime(13, 0)
DAY_CLOSE      = dtime(15, 55)

SPY_FLAT_BAND  = 0.001     # ±0.1%
HOD_THRESHOLD  = 0.99      # stock close ≥ 99% of morning HOD → LONG
LOD_THRESHOLD  = 1.01      # stock close ≤ 101% of morning LOD → SHORT
ATR_STOP_MULT  = 0.1
MAX_STOP_PCT   = 0.040     # reject if stop > 4% of entry (wider morning range)
TARGET_RR      = 2.0
RISK_PER_TRADE = 500.0
MAX_POSITIONS  = 3
MAX_HOLD_DAYS  = 5         # same as engine TF


# ── Load ──────────────────────────────────────────────────────────────────────

class _FallbackUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        try:
            return super().find_class(module, name)
        except (ModuleNotFoundError, AttributeError, ImportError):
            return type(name, (), {})


print("Loading pkl files...")
with open(PKL_RESULTS, "rb") as f:
    results = _FallbackUnpickler(f).load()
with open(PKL_5MIN, "rb") as f:
    data_5min = _FallbackUnpickler(f).load()

for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

rows = []
for window in results:
    for t in window.get("trades", []):
        d = vars(t).copy() if hasattr(t, "__dict__") else dict(t)
        rows.append(d)
for d in rows:
    d["entry_time"] = pd.to_datetime(d["entry_time"])

day_regime: dict = {}
for t in rows:
    day = t["entry_time"].date()
    if day not in day_regime:
        day_regime[day] = t.get("hmm_state", "Normal")

normal_days = sorted(d for d, r in day_regime.items() if r == "Normal")
print(f"Normal days: {len(normal_days)}")
by_yr = defaultdict(int)
for d in normal_days:
    by_yr[d.year] += 1
for yr in sorted(by_yr):
    print(f"  {yr}: {by_yr[yr]} days")

spy_bars = data_5min.get("SPY", pd.DataFrame())
tickers  = [tk for tk in data_5min if tk != "SPY"]
print(f"Tickers: {len(tickers)}")

# Pre-group by (ticker, date) for O(1) lookups — avoids full index scan per call
print("Pre-grouping data by date...")
ticker_by_date: dict[str, dict] = {}
ticker_all_dates: dict[str, list] = {}
for tk in data_5min:
    df = data_5min[tk]
    grp = {}
    for norm_ts, day_df in df.groupby(df.index.normalize()):
        grp[norm_ts] = day_df
    ticker_by_date[tk] = grp
    ticker_all_dates[tk] = sorted(grp.keys())

# SPY direction: pre-compute for all normal days
spy_grp = ticker_by_date.get("SPY", {})


# ── Bull trend filter (same as engine) ────────────────────────────────────────

spy_daily = spy_bars["close"].resample("D").last().dropna().sort_index()

def is_bull_trend(trade_date) -> bool:
    prior = spy_daily[spy_daily.index < pd.Timestamp(trade_date)]
    if len(prior) < 200:
        return True
    return float(prior.iloc[-50:].mean()) > float(prior.iloc[-200:].mean())

bull_map = {d: is_bull_trend(d) for d in normal_days}


# ── SPY direction at 13:00 ─────────────────────────────────────────────────────

def spy_dir_at_1300(day) -> str:
    day_ts  = pd.Timestamp(day)
    day_spy = spy_grp.get(day_ts)
    if day_spy is None or day_spy.empty:
        return "FLAT"
    spy_open = float(day_spy.iloc[0]["open"])
    at_1300  = day_spy[day_spy.index.time <= ENTRY_TIME]
    if at_1300.empty:
        return "FLAT"
    close = float(at_1300.iloc[-1]["close"])
    move  = (close - spy_open) / spy_open
    if move >  SPY_FLAT_BAND: return "UP"
    if move < -SPY_FLAT_BAND: return "DOWN"
    return "FLAT"


# ── Per-ticker sim ────────────────────────────────────────────────────────────

def compute_atr(bars: pd.DataFrame) -> float:
    if len(bars) < 2:
        return 0.0
    return float((bars["high"] - bars["low"]).abs().mean())


def sim_ticker(ticker: str, day, direction: str) -> dict | None:
    day_ts   = pd.Timestamp(day)
    tk_grp   = ticker_by_date.get(ticker, {})
    bars     = tk_grp.get(day_ts)
    if bars is None or bars.empty:
        return None

    # Morning bars up to 12:59
    morning = bars[
        (bars.index.time >= MORNING_START) &
        (bars.index.time <= MORNING_END)
    ]
    if len(morning) < 6:
        return None

    morning_hod = float(morning["high"].max())
    morning_lod = float(morning["low"].min())

    # Entry bar: close at 13:00
    at_entry = bars[bars.index.time == ENTRY_TIME]
    if at_entry.empty:
        return None
    entry_px = float(at_entry.iloc[-1]["close"])

    # Signal: near HOD or LOD
    if direction == "LONG"  and entry_px < morning_hod * HOD_THRESHOLD:
        return None
    if direction == "SHORT" and entry_px > morning_lod * LOD_THRESHOLD:
        return None

    # Stop: full morning range (9:30-12:59) — wider, less noise-swept
    hour_bars = bars[
        (bars.index.time >= MORNING_START) &
        (bars.index.time <= MORNING_END)
    ]
    if hour_bars.empty:
        return None

    atr = compute_atr(hour_bars)
    if atr <= 0:
        return None

    if direction == "LONG":
        stop_ref  = float(hour_bars["low"].min())
        stop_px   = stop_ref - ATR_STOP_MULT * atr
        stop_dist = entry_px - stop_px
    else:
        stop_ref  = float(hour_bars["high"].max())
        stop_px   = stop_ref + ATR_STOP_MULT * atr
        stop_dist = stop_px - entry_px

    if stop_dist <= 0 or stop_dist / entry_px > MAX_STOP_PCT:
        return None

    target_px = (entry_px + TARGET_RR * stop_dist) if direction == "LONG" \
                else (entry_px - TARGET_RR * stop_dist)

    # Proximity score: how close to extreme (0 = exactly at HOD/LOD)
    proximity = (morning_hod - entry_px) if direction == "LONG" \
                else (entry_px - morning_lod)

    # Forward sim — hold up to MAX_HOLD_DAYS (same as engine TF swing hold)
    # Use pre-grouped data: rest of entry day + up to 4 future days
    tk_dates     = ticker_all_dates.get(ticker, [])
    future_dates = [d for d in tk_dates if d > day_ts][:MAX_HOLD_DAYS - 1]

    rest_of_day  = bars[
        (bars.index.time > ENTRY_TIME) &
        (bars.index.time <= DAY_CLOSE)
    ]
    future_parts = [rest_of_day]
    for fd in future_dates:
        fd_bars = tk_grp.get(fd)
        if fd_bars is not None and not fd_bars.empty:
            future_parts.append(fd_bars[fd_bars.index.time <= DAY_CLOSE])

    forward = pd.concat(future_parts).sort_index() if future_parts else pd.DataFrame()
    if forward.empty:
        return None

    shares   = RISK_PER_TRADE / stop_dist
    exit_px  = float(forward.iloc[-1]["close"])
    exit_why = "TIME_STOP"

    for _, fbar in forward.iterrows():
        fh = float(fbar["high"])
        fl = float(fbar["low"])
        if direction == "LONG":
            if fl <= stop_px:
                exit_px, exit_why = stop_px, "STOP_HIT"
                break
            if fh >= target_px:
                exit_px, exit_why = target_px, "TARGET_HIT"
                break
        else:
            if fh >= stop_px:
                exit_px, exit_why = stop_px, "STOP_HIT"
                break
            if fl <= target_px:
                exit_px, exit_why = target_px, "TARGET_HIT"
                break

    pnl = ((exit_px - entry_px) if direction == "LONG"
           else (entry_px - exit_px)) * shares

    return {
        "ticker":    ticker,
        "day":       day,
        "direction": direction,
        "entry_px":  entry_px,
        "exit_px":   exit_px,
        "exit_why":  exit_why,
        "stop_px":   stop_px,
        "stop_dist": stop_dist,
        "target_px": target_px,
        "shares":    shares,
        "net_pnl":   pnl,
        "proximity": proximity,
        "morning_hod": morning_hod,
        "morning_lod": morning_lod,
    }


# ── Run simulation ─────────────────────────────────────────────────────────────

print("\nRunning pre-TF simulation...")
all_trades = []

for day in normal_days:
    spy_dir = spy_dir_at_1300(day)
    if spy_dir == "FLAT":
        continue

    bull = bull_map[day]
    # Bear trend → only SHORT allowed (same as engine ORB)
    direction = "LONG" if spy_dir == "UP" else "SHORT"
    if direction == "LONG" and not bull:
        continue

    day_setups = []
    for ticker in tickers:
        result = sim_ticker(ticker, day, direction)
        if result:
            day_setups.append(result)

    # Sort by proximity (closest to HOD/LOD first)
    day_setups.sort(key=lambda x: x["proximity"])
    all_trades.extend(day_setups[:MAX_POSITIONS])

print(f"Total trades: {len(all_trades)}")


# ── Results ────────────────────────────────────────────────────────────────────

def stats(trades):
    if not trades:
        return {"n": 0, "pnl": 0.0, "wr": 0.0, "avg": 0.0}
    pnl  = sum(t["net_pnl"] for t in trades)
    wins = sum(1 for t in trades if t["net_pnl"] > 0)
    return {"n": len(trades), "pnl": pnl, "wr": wins / len(trades), "avg": pnl / len(trades)}


def print_breakdown(label, trades):
    s = stats(trades)
    print(f"\n  {label}: {s['n']}t  P&L={s['pnl']:+,.0f}  WR={s['wr']:.0%}  avg={s['avg']:+.1f}")
    by_yr = defaultdict(list)
    for t in trades:
        by_yr[t["day"].year].append(t)
    for yr in sorted(by_yr):
        tl = by_yr[yr]
        p  = sum(t["net_pnl"] for t in tl)
        w  = sum(1 for t in tl if t["net_pnl"] > 0)
        print(f"    {yr}: {len(tl):3d}t  P&L={p:+6,.0f}  WR={w/len(tl):.0%}  avg={p/len(tl):+.1f}")


print("\n" + "="*70)
print("  PRE-TREND_FOLLOW ENTRY SIM — 13:00 entry, 15:55 exit")
print("="*70)
print(f"  Signal:  stock at/near HOD (≥99%) or LOD (≤101%) at 13:00")
print(f"  Filter:  SPY direction + SMA50/200 bear block for LONG")
print(f"  Stop:    morning low/high (9:30-12:59) ± {ATR_STOP_MULT}×ATR, max {MAX_STOP_PCT:.0%}")
print(f"  Target:  {TARGET_RR}R  |  Hold: up to {MAX_HOLD_DAYS} days (same as engine TF)")
print(f"  Cap:     {MAX_POSITIONS}/day (closest to HOD/LOD first)")

print_breakdown("All trades", all_trades)

longs  = [t for t in all_trades if t["direction"] == "LONG"]
shorts = [t for t in all_trades if t["direction"] == "SHORT"]
print_breakdown("LONG", longs)
print_breakdown("SHORT", shorts)

print("\n  By exit reason:")
by_ex = defaultdict(list)
for t in all_trades:
    by_ex[t["exit_why"]].append(t)
for ex, tl in sorted(by_ex.items(), key=lambda x: -len(x[1])):
    p = sum(t["net_pnl"] for t in tl)
    w = sum(1 for t in tl if t["net_pnl"] > 0)
    print(f"    {ex:12s}: {len(tl):3d}t  P&L={p:+,.0f}  WR={w/len(tl):.0%}")

# HOD proximity buckets
print("\n  By HOD/LOD proximity (entry distance from extreme):")
prox = [(t["proximity"], t["net_pnl"]) for t in all_trades]
prox.sort(key=lambda x: x[0])
buckets = [
    ("exactly at",   lambda p: p <= 0.05),
    ("0-0.5% away",  lambda p: 0.05 < p <= 0.5),
    ("0.5-1% away",  lambda p: 0.5  < p <= 1.0),
    ("> 1% away",    lambda p: p > 1.0),
]
for label, fn in buckets:
    b = [(p, pnl) for p, pnl in prox if fn(p)]
    if not b:
        continue
    pl = sum(x[1] for x in b)
    w  = sum(1 for x in b if x[1] > 0)
    print(f"    {label:16s}: {len(b):3d}t  P&L={pl:+,.0f}  WR={w/len(b):.0%}")

stop_dists = [t["stop_dist"] for t in all_trades]
entries    = [t["entry_px"]  for t in all_trades]
if stop_dists:
    avg_stop  = float(np.mean(stop_dists))
    avg_entry = float(np.mean(entries))
    print(f"\n  Stop distance: mean=${avg_stop:.2f}  →  ~{RISK_PER_TRADE/avg_stop:.0f} shares @ ${avg_entry:.0f}")
