"""
fade_short_vol_filter.py — FADE SHORT realized-vol filter

Problem: FADE SHORT is -$493 in 2020 (WR=29%) and -$299 in 2022 (WR=27%)
but +$1,491 in 2021 (WR=56%). Root cause: high realized vol = violent reversals
after ORB breakdowns. Low vol = stocks stay down after breaking range.

Filter tested: skip FADE SHORT when SPY 5-day realized vol > threshold
  Same metric engine uses for _cur_vol (5-day log-return std × sqrt252).

FADE SHORT engine conditions already in pkl:
  - Normal or Calm regime
  - OR range 9:30-9:44; stock breaks DOWN out of range
  - Delayed entry: confirmed revert into OR on bar B+1
  - SPY filter: skip if SPY > OR_high (SPY bullish = bad for SHORT)
  - _position_ok() cap: MAX_FADE=5

Approach: retroactively apply vol filter to FADE SHORT trades.

Usage:
  cd d:\\raits\\raits
  python raits\\scripts\\fade_short_vol_filter.py
"""

import pickle
import sys
import os
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

PKL_RESULTS = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots", "results_scenario_g.pkl")
PKL_5MIN    = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")

THRESHOLDS = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]


# ── Load ──────────────────────────────────────────────────────────────────────

class _FallbackUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        try:
            return super().find_class(module, name)
        except (ModuleNotFoundError, AttributeError, ImportError):
            return type(name, (), {})


print("Loading pkls...")
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

fade_all   = [t for t in rows if t.get("strategy") == "FADE"]
fade_short = [t for t in fade_all if t.get("direction") == "SHORT"]
fade_long  = [t for t in fade_all if t.get("direction") == "LONG"]
print(f"FADE trades: {len(fade_all)} total, {len(fade_short)} SHORT, {len(fade_long)} LONG")


# ── Compute 5-day realized vol (same as engine _cur_vol) ─────────────────────

spy_5min = data_5min.get("SPY", pd.DataFrame())
spy_daily = (
    spy_5min["close"]
    .resample("D")
    .last()
    .dropna()
    .sort_index()
)

def realized_vol(trade_date) -> float | None:
    """5-day annualized realized vol from SPY daily log-returns ending T-1."""
    ts = pd.Timestamp(trade_date)
    prior = spy_daily[spy_daily.index < ts]
    if len(prior) < 6:
        return None
    log_ret = np.log(prior / prior.shift(1)).dropna()
    rv = float(log_ret.iloc[-5:].std() * np.sqrt(252))
    return rv


unique_dates = sorted({t["entry_time"].date() for t in fade_short})
vol_map = {d: realized_vol(d) for d in unique_dates}

for t in fade_short:
    t["_rv"] = vol_map.get(t["entry_time"].date())


# ── Stats helpers ─────────────────────────────────────────────────────────────

def stats(trades):
    if not trades:
        return {"n": 0, "pnl": 0.0, "wr": 0.0, "avg": 0.0}
    pnl  = sum(t["net_pnl"] for t in trades)
    wins = sum(1 for t in trades if t["net_pnl"] > 0)
    return {"n": len(trades), "pnl": pnl, "wr": wins / len(trades), "avg": pnl / len(trades)}


def yr_line(trades):
    by_yr = defaultdict(list)
    for t in trades:
        by_yr[t["entry_time"].year].append(t)
    parts = []
    for yr in [2020, 2021, 2022]:
        s = stats(by_yr[yr])
        parts.append(f"{yr}:{s['pnl']:+,.0f}({s['n']}t)")
    return "  ".join(parts)


# ── Baseline ──────────────────────────────────────────────────────────────────

print("\n" + "="*70)
print("  FADE SHORT REALIZED-VOL FILTER SIM")
print("="*70)
print("  Skip FADE SHORT when SPY 5-day realized vol > threshold")
print()

sb_all   = stats(fade_all)
sb_short = stats(fade_short)
sb_long  = stats(fade_long)

print(f"  BASELINE (all FADE):  {sb_all['n']}t  P&L={sb_all['pnl']:+,.0f}  WR={sb_all['wr']:.0%}  avg={sb_all['avg']:+.1f}")
print(f"    SHORT only:         {sb_short['n']}t  P&L={sb_short['pnl']:+,.0f}  WR={sb_short['wr']:.0%}  avg={sb_short['avg']:+.1f}")
print(f"    LONG  only:         {sb_long['n']}t  P&L={sb_long['pnl']:+,.0f}  WR={sb_long['wr']:.0%}  avg={sb_long['avg']:+.1f}")
print(f"\n  Year breakdown ({yr_line(fade_short)})")


# ── Vol distribution ──────────────────────────────────────────────────────────

print("\n" + "─"*70)
print("  REALIZED VOL DISTRIBUTION at FADE SHORT entry")
print("─"*70)

buckets = [
    ("< 10%",      lambda v: v < 0.10),
    ("10–15%",     lambda v: 0.10 <= v < 0.15),
    ("15–20%",     lambda v: 0.15 <= v < 0.20),
    ("20–25%",     lambda v: 0.20 <= v < 0.25),
    ("25–30%",     lambda v: 0.25 <= v < 0.30),
    ("30–40%",     lambda v: 0.30 <= v < 0.40),
    ("> 40%",      lambda v: v >= 0.40),
]

print(f"  {'Vol bucket':>12} {'Trades':>7} {'P&L':>10} {'WR':>6} {'Avg':>8}")
print("  " + "─"*46)
for label, fn in buckets:
    bucket = [t for t in fade_short if t["_rv"] is not None and fn(t["_rv"])]
    if not bucket:
        continue
    s = stats(bucket)
    print(f"  {label:>12} {s['n']:>7d} {s['pnl']:>+10,.0f} {s['wr']:>5.0%} {s['avg']:>+8.1f}")


# ── Threshold grid ────────────────────────────────────────────────────────────

print("\n" + "─"*70)
print("  THRESHOLD GRID — skip SHORT when vol > threshold")
print("─"*70)
print(f"  {'Threshold':>10} {'SHORT kept':>11} {'SHORT P&L':>11} {'SHORT WR':>9}   {'FADE total P&L':>15}   By year")
print("  " + "─"*70)

for thr in THRESHOLDS:
    short_kept    = [t for t in fade_short if t["_rv"] is not None and t["_rv"] <= thr]
    short_dropped = [t for t in fade_short if t["_rv"] is None or t["_rv"] > thr]
    all_kept      = fade_long + short_kept
    ss = stats(short_kept)
    sa = stats(all_kept)
    print(f"  {thr*100:>9.0f}%  {ss['n']:>11d} {ss['pnl']:>+11,.0f} {ss['wr']:>8.0%}   "
          f"{sa['pnl']:>+15,.0f}   {yr_line(all_kept)}")
