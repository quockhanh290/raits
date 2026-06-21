"""
midday_hod_lod_sim.py — Midday HOD/LOD breakout strategy

Window: 11:30-13:00 (Normal + Calm regime)
Hypothesis: stocks that break their morning range (9:30-11:25) in the
midday window often continue to 14:00 when TREND_FOLLOW picks up.

Signal:
  - SPY bullish (close[11:30] > open[9:30]) → LONG only (stocks breaking HOD)
  - SPY bearish (close[11:30] < open[9:30]) → SHORT only (stocks breaking LOD)
  - FLAT (±0.1% from open) → no trades

Entry:  close of first bar breaking morning HOD/LOD after 11:30
Stop:   morning LOD - 0.1×ATR  (LONG) | morning HOD + 0.1×ATR  (SHORT)
Target: 1.5R
Time:   exit at 14:00 if no stop/target hit
Cap:    2 positions/day, ranked by breakout magnitude (most decisive first)

Engine conditions replicated:
  - Normal OR Calm regime (from pkl hmm_state)
  - SPY directional filter at 11:30
  - ATR-based stop (same formula as engine GAP_FILL)
  - Max 2 positions/day cap

Usage:
  cd d:\\raits\\raits
  python raits\\scripts\\midday_hod_lod_sim.py
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
MORNING_END    = dtime(11, 25)   # last bar of morning range
SCAN_START     = dtime(11, 30)   # first bar eligible for breakout
SCAN_END       = dtime(13, 0)    # last entry bar
TIME_EXIT      = dtime(14, 0)
SPY_REF_TIME   = dtime(11, 30)   # SPY direction measured at this bar
SPY_FLAT_BAND  = 0.001           # ±0.1% → flat, no trades
ATR_STOP_MULT  = 0.1
TARGET_RR      = 1.5
RISK_PER_TRADE = 500.0
MAX_POSITIONS  = 2
MAX_STOP_PCT   = 0.02            # reject if stop > 2% of entry


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

# Day → regime map
day_regime: dict = {}
for t in rows:
    day = t["entry_time"].date()
    if day not in day_regime:
        day_regime[day] = t.get("hmm_state", "Normal")

# Normal + Calm days only
target_days = sorted(
    d for d, r in day_regime.items() if r in ("Normal", "Calm")
)
print(f"Normal+Calm days: {len(target_days)}")
by_yr = defaultdict(int)
for d in target_days:
    by_yr[d.year] += 1
for yr in sorted(by_yr):
    print(f"  {yr}: {by_yr[yr]} days")

spy_bars = data_5min.get("SPY", pd.DataFrame())
tickers  = [tk for tk in data_5min if tk != "SPY"]
print(f"Tickers available: {len(tickers)}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def compute_atr(bars: pd.DataFrame) -> float:
    if len(bars) < 2:
        return 0.0
    tr = (bars["high"] - bars["low"]).abs()
    return float(tr.mean())


def spy_direction(day) -> str:
    """Return 'UP', 'DOWN', or 'FLAT' based on SPY at 11:30 vs open."""
    day_spy = spy_bars[spy_bars.index.date == day]
    if day_spy.empty:
        return "FLAT"
    spy_open = float(day_spy.iloc[0]["open"])
    at_ref = day_spy[day_spy.index.time <= SPY_REF_TIME]
    if at_ref.empty:
        return "FLAT"
    spy_ref_close = float(at_ref.iloc[-1]["close"])
    move = (spy_ref_close - spy_open) / spy_open
    if move > SPY_FLAT_BAND:
        return "UP"
    if move < -SPY_FLAT_BAND:
        return "DOWN"
    return "FLAT"


def sim_ticker(ticker: str, day, direction: str) -> dict | None:
    """
    Sim one ticker on one day for the given direction (LONG or SHORT).
    Returns trade dict or None.
    """
    bars = data_5min[ticker][data_5min[ticker].index.date == day].sort_index()
    if bars.empty:
        return None

    morning = bars[
        (bars.index.time >= MORNING_START) &
        (bars.index.time <= MORNING_END)
    ]
    if len(morning) < 4:
        return None

    morning_hod = float(morning["high"].max())
    morning_lod = float(morning["low"].min())
    atr = compute_atr(morning)
    if atr <= 0:
        return None

    scan_bars = bars[
        (bars.index.time >= SCAN_START) &
        (bars.index.time <= SCAN_END)
    ]
    if scan_bars.empty:
        return None

    # Find first breakout bar
    entry_bar = None
    entry_ts  = None
    for ts, bar in scan_bars.iterrows():
        close = float(bar["close"])
        if direction == "LONG"  and close > morning_hod:
            entry_bar, entry_ts = bar, ts
            break
        if direction == "SHORT" and close < morning_lod:
            entry_bar, entry_ts = bar, ts
            break

    if entry_bar is None:
        return None

    entry_px = float(entry_bar["close"])

    if direction == "LONG":
        stop_px   = morning_lod - ATR_STOP_MULT * atr
        stop_dist = entry_px - stop_px
    else:
        stop_px   = morning_hod + ATR_STOP_MULT * atr
        stop_dist = stop_px - entry_px

    if stop_dist <= 0 or stop_dist / entry_px > MAX_STOP_PCT:
        return None

    target_px = (entry_px + TARGET_RR * stop_dist) if direction == "LONG" \
                else (entry_px - TARGET_RR * stop_dist)

    # Breakout magnitude: how far beyond the HOD/LOD
    breakout_mag = (entry_px - morning_hod) if direction == "LONG" \
                   else (morning_lod - entry_px)

    # Simulate exit
    forward = bars[
        (bars.index.time > entry_ts.time()) &
        (bars.index.time <= TIME_EXIT)
    ]
    if forward.empty:
        return None

    shares    = RISK_PER_TRADE / stop_dist
    exit_px   = float(forward.iloc[-1]["close"])
    exit_why  = "TIME_STOP"

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
        "ticker":       ticker,
        "day":          day,
        "direction":    direction,
        "entry_px":     entry_px,
        "entry_ts":     entry_ts,
        "exit_px":      exit_px,
        "exit_why":     exit_why,
        "stop_px":      stop_px,
        "stop_dist":    stop_dist,
        "target_px":    target_px,
        "shares":       shares,
        "net_pnl":      pnl,
        "breakout_mag": breakout_mag,
        "morning_hod":  morning_hod,
        "morning_lod":  morning_lod,
    }


# ── Run simulation ─────────────────────────────────────────────────────────────

print("\nRunning simulation...")
all_trades = []

for day in target_days:
    spy_dir = spy_direction(day)
    if spy_dir == "FLAT":
        continue

    direction = "LONG" if spy_dir == "UP" else "SHORT"
    day_setups = []

    for ticker in tickers:
        if ticker not in data_5min:
            continue
        result = sim_ticker(ticker, day, direction)
        if result:
            day_setups.append(result)

    # Sort by breakout magnitude, take top MAX_POSITIONS
    day_setups.sort(key=lambda x: -x["breakout_mag"])
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
print("  MIDDAY HOD/LOD BREAKOUT SIM")
print("="*70)
print(f"  Window:   {SCAN_START}–{SCAN_END} entry  |  time exit {TIME_EXIT}")
print(f"  Stop:     morning LOD/HOD ± {ATR_STOP_MULT}×ATR")
print(f"  Target:   {TARGET_RR}R")
print(f"  Filter:   SPY direction at {SPY_REF_TIME} (flat band ±{SPY_FLAT_BAND:.1%})")
print(f"  Cap:      {MAX_POSITIONS} positions/day (most decisive breakout first)")

print_breakdown("All trades", all_trades)

longs  = [t for t in all_trades if t["direction"] == "LONG"]
shorts = [t for t in all_trades if t["direction"] == "SHORT"]
print_breakdown("LONG  (SPY UP days)", longs)
print_breakdown("SHORT (SPY DOWN days)", shorts)

# By exit reason
print("\n  By exit reason:")
by_ex = defaultdict(list)
for t in all_trades:
    by_ex[t["exit_why"]].append(t)
for ex, tl in sorted(by_ex.items(), key=lambda x: -len(x[1])):
    p = sum(t["net_pnl"] for t in tl)
    w = sum(1 for t in tl if t["net_pnl"] > 0)
    print(f"    {ex:12s}: {len(tl):3d}t  P&L={p:+,.0f}  WR={w/len(tl):.0%}")

# By regime
print("\n  By regime:")
by_reg = defaultdict(list)
for t in all_trades:
    day   = t["day"]
    regime = day_regime.get(day, "?")
    by_reg[regime].append(t)
for reg, tl in sorted(by_reg.items()):
    p = sum(t["net_pnl"] for t in tl)
    w = sum(1 for t in tl if t["net_pnl"] > 0)
    print(f"    {reg:8s}: {len(tl):3d}t  P&L={p:+,.0f}  WR={w/len(tl):.0%}")

# Stop distance stats
stop_dists = [t["stop_dist"] for t in all_trades]
entries    = [t["entry_px"]  for t in all_trades]
avg_entry  = float(np.mean(entries)) if entries else 0
avg_stop   = float(np.mean(stop_dists)) if stop_dists else 0
avg_shares = RISK_PER_TRADE / avg_stop if avg_stop > 0 else 0
print(f"\n  Stop distance: mean=${avg_stop:.2f}  →  ~{avg_shares:.0f} shares @ ${avg_entry:.0f}")
