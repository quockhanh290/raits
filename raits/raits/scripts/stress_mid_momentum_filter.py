"""
stress_mid_momentum_filter.py — test SPY momentum threshold for STRESS_MID

Problem: engine fires STRESS_MID on 110 Stress days in 2022, but sim (selection
bias) only tested 46. Extra 64 days have WR=32%, avg=-$4.9 — dragging performance.

Hypothesis: on weak Stress days (SPY only marginally below VWAP), the SHORT
signal is noise. Add a minimum momentum filter: SPY must be down ≥X% from open
at 10:15. This mirrors the existing VWAP-below-open signal but adds magnitude.

Test: retroactively apply to STRESS_MID trades in new snapshot.
Engine conditions already embedded: Stress regime, close<VWAP, close<open,
swing-high stop ≤1.5%, max 2 positions.

Usage:
  cd d:\\raits\\raits
  python raits\\scripts\\stress_mid_momentum_filter.py
"""

import pickle
import sys
import os
from collections import defaultdict
from datetime import time as dtime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

PKL_NEW  = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots", "results_20260619_132029.pkl")
PKL_5MIN = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")

ENTRY_TIME = dtime(10, 15)
THRESHOLDS = [0.001, 0.002, 0.003, 0.005, 0.007, 0.010]  # 0.1% to 1.0% below open


class _FallbackUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        try:
            return super().find_class(module, name)
        except (ModuleNotFoundError, AttributeError, ImportError):
            return type(name, (), {})


print("Loading pkls...")
with open(PKL_NEW, "rb") as f:
    results_new = _FallbackUnpickler(f).load()
with open(PKL_5MIN, "rb") as f:
    data_5min = _FallbackUnpickler(f).load()

for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

rows = []
for window in results_new:
    for t in window.get("trades", []):
        d = vars(t).copy() if hasattr(t, "__dict__") else dict(t)
        rows.append(d)
for d in rows:
    d["entry_time"] = pd.to_datetime(d["entry_time"])
    d["exit_time"]  = pd.to_datetime(d["exit_time"])

sm_trades = [t for t in rows if t.get("strategy") == "STRESS_MID"]
print(f"STRESS_MID trades in new pkl: {len(sm_trades)}")


# ── Compute SPY momentum at 10:15 for each trade day ─────────────────────────

spy_bars = data_5min.get("SPY", pd.DataFrame())

def spy_momentum_at_entry(day) -> float | None:
    """Return (close[10:15] - open) / open — negative = down from open."""
    day_spy = spy_bars[spy_bars.index.date == day]
    if day_spy.empty:
        return None
    spy_open = float(day_spy.iloc[0]["open"])
    at_entry = day_spy[day_spy.index.time == ENTRY_TIME]
    if at_entry.empty:
        return None
    spy_close_1015 = float(at_entry.iloc[-1]["close"])
    return (spy_close_1015 - spy_open) / spy_open  # negative = down


# Cache momentum by date
unique_dates = sorted({t["entry_time"].date() for t in sm_trades})
mom_map = {d: spy_momentum_at_entry(d) for d in unique_dates}

# Attach momentum to each trade
for t in sm_trades:
    t["_spy_mom"] = mom_map.get(t["entry_time"].date())


# ── Stats helper ──────────────────────────────────────────────────────────────

def stats(trades):
    if not trades:
        return {"n": 0, "pnl": 0.0, "wr": 0.0, "avg": 0.0}
    pnl  = sum(t["net_pnl"] for t in trades)
    wins = sum(1 for t in trades if t["net_pnl"] > 0)
    return {"n": len(trades), "pnl": pnl, "wr": wins / len(trades), "avg": pnl / len(trades)}


def yr_breakdown(trades):
    by_yr = defaultdict(list)
    for t in trades:
        by_yr[t["entry_time"].year].append(t)
    return {yr: stats(tl) for yr, tl in sorted(by_yr.items())}


# ── Baseline ──────────────────────────────────────────────────────────────────

print("\n" + "="*70)
print("  STRESS_MID MOMENTUM THRESHOLD FILTER SIM")
print("="*70)
print("  Filter: skip STRESS_MID if SPY close[10:15] < open by LESS than threshold")
print("  (requires SPY to be MORE decisively down to confirm Stress momentum)")
print()

sb = stats(sm_trades)
yd = yr_breakdown(sm_trades)
print(f"  BASELINE: {sb['n']}t  P&L={sb['pnl']:+,.0f}  WR={sb['wr']:.0%}  avg={sb['avg']:+.1f}")
for yr, s in yd.items():
    print(f"    {yr}: {s['n']:3d}t  P&L={s['pnl']:+6,.0f}  WR={s['wr']:.0%}  avg={s['avg']:+.1f}")

# ── Threshold grid ────────────────────────────────────────────────────────────

print("\n" + "─"*70)
print(f"  {'Threshold':>10} {'Trades':>7} {'Dropped':>8} {'P&L':>10} {'WR':>6} {'Avg':>8}   By year (P&L)")
print("  " + "─"*68)

for thr in THRESHOLDS:
    # Keep trade only if SPY is down ≥ threshold from open at 10:15
    kept = [t for t in sm_trades
            if t["_spy_mom"] is not None and t["_spy_mom"] <= -thr]
    dropped_n = sb["n"] - len(kept)
    s  = stats(kept)
    yd = yr_breakdown(kept)
    yr_str = "  ".join(
        f"{yr}:{yd.get(yr, {'pnl':0})['pnl']:+,.0f}({yd.get(yr, {'n':0})['n']}t)"
        for yr in [2020, 2021, 2022]
    )
    print(f"  {thr*100:>9.1f}%  {s['n']:>7d} {dropped_n:>8d} "
          f"{s['pnl']:>+10,.0f} {s['wr']:>5.0%} {s['avg']:>+8.1f}   {yr_str}")

# ── Deep dive on best threshold ───────────────────────────────────────────────

print("\n" + "─"*70)
print("  SPY momentum distribution at 10:15 on STRESS_MID days")
print("─"*70)

moms = [(t["_spy_mom"], t["net_pnl"]) for t in sm_trades if t["_spy_mom"] is not None]
moms.sort(key=lambda x: x[0])

buckets = [
    ("< -1.0%",  lambda m: m < -0.010),
    ("-1.0 to -0.7%", lambda m: -0.010 <= m < -0.007),
    ("-0.7 to -0.5%", lambda m: -0.007 <= m < -0.005),
    ("-0.5 to -0.3%", lambda m: -0.005 <= m < -0.003),
    ("-0.3 to -0.2%", lambda m: -0.003 <= m < -0.002),
    ("-0.2 to -0.1%", lambda m: -0.002 <= m < -0.001),
    ("-0.1 to 0%",    lambda m: -0.001 <= m < 0),
    (">= 0%",         lambda m: m >= 0),
]

print(f"  {'Range':>20} {'Trades':>7} {'P&L':>10} {'WR':>6} {'Avg':>8}")
print("  " + "─"*55)
for label, fn in buckets:
    bucket = [(m, p) for m, p in moms if fn(m)]
    if not bucket:
        continue
    pnl  = sum(p for _, p in bucket)
    wins = sum(1 for _, p in bucket if p > 0)
    avg  = pnl / len(bucket) if bucket else 0
    wr   = wins / len(bucket) if bucket else 0
    print(f"  {label:>20} {len(bucket):>7d} {pnl:>+10,.0f} {wr:>5.0%} {avg:>+8.1f}")
