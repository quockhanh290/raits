"""
orb_spy_align_sim.py — ORB intraday SPY alignment filter

ENGINE already has: LONG blocked when SPY SMA50 < SMA200 (bear macro trend)
NEW filter tested: also block if ORB direction ≠ SPY intraday direction
  SPY close[entry_time] < SPY open → only SHORT ORB
  SPY close[entry_time] > SPY open → only LONG ORB

Approach: take existing ORB trades from pkl, apply retroactively.
This is valid because the filter changes WHICH trades enter, not exit logic.

Usage:
  cd d:\\raits\\raits
  python raits\\scripts\\orb_spy_align_sim.py
"""

import pickle
import sys
import os
from datetime import time as dtime
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

PKL_RESULTS = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots", "results_scenario_g.pkl")
PKL_5MIN    = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")


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
    d["exit_time"]  = pd.to_datetime(d["exit_time"])

orb_trades = [t for t in rows if t.get("strategy") == "ORB"]
print(f"ORB trades in pkl: {len(orb_trades)}")

spy_bars_all = data_5min.get("SPY", pd.DataFrame())


# ── SPY alignment helper ──────────────────────────────────────────────────────

def spy_direction(day, entry_time) -> str:
    """Return 'UP', 'DOWN', or 'FLAT' based on SPY intraday direction at entry."""
    if spy_bars_all.empty:
        return "FLAT"
    day_spy = spy_bars_all[spy_bars_all.index.date == day]
    if day_spy.empty:
        return "FLAT"

    spy_open = float(day_spy.iloc[0]["open"])

    # SPY close at or just before entry_time
    up_to_entry = day_spy[day_spy.index.time <= entry_time.time()]
    if up_to_entry.empty:
        return "FLAT"
    spy_now = float(up_to_entry.iloc[-1]["close"])

    if spy_now < spy_open * 0.9995:   # at least 0.05% below open → DOWN
        return "DOWN"
    if spy_now > spy_open * 1.0005:   # at least 0.05% above open → UP
        return "UP"
    return "FLAT"                      # neutral — allow both


def passes_align_filter(trade: dict) -> bool:
    """Return True if ORB direction matches SPY intraday direction."""
    day       = trade["entry_time"].date()
    direction = trade.get("direction", "")
    spy_dir   = spy_direction(day, trade["entry_time"])

    if spy_dir == "FLAT":
        return True   # neutral — don't block either direction
    if direction == "LONG"  and spy_dir == "DOWN":
        return False  # LONG ORB on a DOWN SPY day → skip
    if direction == "SHORT" and spy_dir == "UP":
        return False  # SHORT ORB on an UP SPY day → skip
    return True


# ── Stats helpers ─────────────────────────────────────────────────────────────

def stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "pnl": 0, "wr": 0, "avg": 0}
    pnl  = sum(t["net_pnl"] for t in trades)
    wins = sum(1 for t in trades if t["net_pnl"] > 0)
    return {
        "n":   len(trades),
        "pnl": pnl,
        "wr":  wins / len(trades),
        "avg": pnl / len(trades),
    }


def print_breakdown(label: str, trades: list[dict]):
    s = stats(trades)
    print(f"\n  {label}: {s['n']}t  P&L={s['pnl']:+,.0f}  WR={s['wr']:.0%}  avg={s['avg']:+.1f}")

    by_yr = defaultdict(list)
    for t in trades:
        by_yr[t["entry_time"].year].append(t)
    for yr in sorted(by_yr):
        tl = by_yr[yr]
        p  = sum(t["net_pnl"] for t in tl)
        w  = sum(1 for t in tl if t["net_pnl"] > 0)
        print(f"    {yr}: {len(tl):3d}t  P&L={p:+6,.0f}  WR={w/len(tl):.0%}  avg={p/len(tl):+.1f}")


# ── Run sim ───────────────────────────────────────────────────────────────────

print("\n" + "="*70)
print("  ORB SPY INTRADAY ALIGNMENT FILTER SIM")
print("="*70)
print("  Engine already: LONG blocked when SPY SMA50 < SMA200")
print("  New filter:     also skip if direction ≠ SPY intraday at entry")
print("  FLAT zone:      ±0.05% from open → no filter applied")
print()

# Categorise every ORB trade
aligned   = [t for t in orb_trades if     passes_align_filter(t)]
filtered  = [t for t in orb_trades if not passes_align_filter(t)]

# Spy direction breakdown for context
spy_dirs = {"UP": 0, "DOWN": 0, "FLAT": 0}
dir_breakdown = defaultdict(lambda: defaultdict(list))  # spy_dir → direction → trades
for t in orb_trades:
    day     = t["entry_time"].date()
    spy_dir = spy_direction(day, t["entry_time"])
    spy_dirs[spy_dir] += 1
    dir_breakdown[spy_dir][t.get("direction", "?")].append(t)

print(f"  SPY direction at entry breakdown:")
for d in ["UP", "DOWN", "FLAT"]:
    n = spy_dirs[d]
    for direction in ["LONG", "SHORT"]:
        tl = dir_breakdown[d][direction]
        if not tl:
            continue
        pnl = sum(t["net_pnl"] for t in tl)
        w   = sum(1 for t in tl if t["net_pnl"] > 0)
        tag = " ✓ aligned" if (
            (d == "UP" and direction == "LONG") or
            (d == "DOWN" and direction == "SHORT")
        ) else " ✗ misaligned"
        print(f"    SPY {d:4s} + {direction:5s}: {len(tl):2d}t  P&L={pnl:+6,.0f}  WR={w/len(tl):.0%}{tag}")

# ── Core comparison ───────────────────────────────────────────────────────────

print("\n" + "─"*70)
print("  BASELINE  (current engine — SMA50/200 filter only)")
print_breakdown("All years", orb_trades)

by_yr_base = defaultdict(list)
for t in orb_trades:
    by_yr_base[t["entry_time"].year].append(t)

print("\n" + "─"*70)
print("  WITH SPY ALIGNMENT FILTER  (new — intraday direction match)")
print_breakdown("All years", aligned)

print(f"\n  Trades dropped: {len(filtered)}")
for t in sorted(filtered, key=lambda x: x["entry_time"]):
    day = t["entry_time"].date()
    sd  = spy_direction(day, t["entry_time"])
    print(f"    {day}  {t.get('ticker','?'):6s}  {t.get('direction','?'):5s}  "
          f"SPY={sd:4s}  P&L={t['net_pnl']:+.0f}")

# ── Delta summary ─────────────────────────────────────────────────────────────

print("\n" + "="*70)
print("  DELTA SUMMARY")
print("="*70)
sb = stats(orb_trades)
sa = stats(aligned)
print(f"  {'':25} {'Baseline':>12} {'+ Align filter':>14} {'Delta':>10}")
print(f"  {'-'*62}")
print(f"  {'Trades':25} {sb['n']:>12d} {sa['n']:>14d} {sa['n']-sb['n']:>+10d}")
print(f"  {'Total P&L':25} {sb['pnl']:>+12,.0f} {sa['pnl']:>+14,.0f} {sa['pnl']-sb['pnl']:>+10,.0f}")
print(f"  {'WR':25} {sb['wr']:>11.0%} {sa['wr']:>13.0%}")
print(f"  {'Avg/trade':25} {sb['avg']:>+12.1f} {sa['avg']:>+14.1f} {sa['avg']-sb['avg']:>+10.1f}")

print("\n  By year:")
all_yrs = sorted(set(t["entry_time"].year for t in orb_trades))
by_yr_align = defaultdict(list)
for t in aligned:
    by_yr_align[t["entry_time"].year].append(t)

print(f"  {'Year':6} {'Base trades':>12} {'Base P&L':>10} {'Align trades':>13} {'Align P&L':>10} {'Delta P&L':>10}")
print(f"  {'-'*64}")
for yr in all_yrs:
    b = stats(by_yr_base[yr])
    a = stats(by_yr_align[yr])
    print(f"  {yr:6d} {b['n']:>12d} {b['pnl']:>+10,.0f} {a['n']:>13d} {a['pnl']:>+10,.0f} {a['pnl']-b['pnl']:>+10,.0f}")
