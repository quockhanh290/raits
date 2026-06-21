"""
fade_bear_filter_sim.py — FADE LONG bear trend filter

Engine currently blocks FADE LONG only on top-2 ATR% tickers.
NEW filter tested: also block FADE LONG when SPY SMA50 < SMA200 (bear macro trend)
  - same filter already applied to ORB LONG (engine line 736)

Approach: retroactively apply to existing FADE trades in pkl.
Valid because the new filter changes WHICH trades enter, not exit logic.
All existing engine FADE filters are already embedded in the pkl results.

Usage:
  cd d:\\raits\\raits
  python raits\\scripts\\fade_bear_filter_sim.py
"""

import pickle
import sys
import os
from collections import defaultdict

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

fade_trades = [t for t in rows if t.get("strategy") == "FADE"]
print(f"FADE trades in pkl: {len(fade_trades)}")


# ── SPY SMA50/200 bull trend ───────────────────────────────────────────────────

spy_5min = data_5min.get("SPY", pd.DataFrame())

# Build daily closes from 5-min data (last bar of each day)
spy_daily = (
    spy_5min["close"]
    .resample("D")
    .last()
    .dropna()
    .sort_index()
)

def is_bull_trend(trade_date) -> bool | None:
    """
    Return True if SPY SMA50 > SMA200 on the DAY BEFORE trade_date
    (same as engine: uses T-1 daily closes).
    Returns None if not enough history (default = allow LONG).
    """
    ts = pd.Timestamp(trade_date)
    prior = spy_daily[spy_daily.index < ts]
    if len(prior) < 200:
        return None  # not enough history → no filter
    sma50  = float(prior.iloc[-50:].mean())
    sma200 = float(prior.iloc[-200:].mean())
    return sma50 > sma200


# Pre-compute bull trend for every unique trade date
unique_dates = sorted({t["entry_time"].date() for t in fade_trades})
bull_trend_map = {d: is_bull_trend(d) for d in unique_dates}

print("\nBull trend by date sample:")
for d in unique_dates[:5]:
    print(f"  {d}: {bull_trend_map[d]}")


# ── Filter logic ──────────────────────────────────────────────────────────────

def passes_bear_filter(trade: dict) -> bool:
    """Keep trade unless it's FADE LONG in a bear trend."""
    direction = trade.get("direction", "")
    if direction != "LONG":
        return True  # FADE SHORT: unaffected
    day = trade["entry_time"].date()
    bull = bull_trend_map.get(day)
    if bull is None:
        return True  # not enough history → allow
    return bull   # block LONG if SMA50 < SMA200


# ── Stats helpers ─────────────────────────────────────────────────────────────

def stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "pnl": 0.0, "wr": 0.0, "avg": 0.0}
    pnl  = sum(t["net_pnl"] for t in trades)
    wins = sum(1 for t in trades if t["net_pnl"] > 0)
    return {"n": len(trades), "pnl": pnl, "wr": wins / len(trades), "avg": pnl / len(trades)}


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

long_trades  = [t for t in fade_trades if t.get("direction") == "LONG"]
short_trades = [t for t in fade_trades if t.get("direction") == "SHORT"]
kept         = [t for t in fade_trades if passes_bear_filter(t)]
dropped      = [t for t in fade_trades if not passes_bear_filter(t)]

# Bull/bear day split for context
bear_days = [d for d, v in bull_trend_map.items() if v is False]
bull_days = [d for d, v in bull_trend_map.items() if v is True]

print(f"\nBull trend days: {len(bull_days)}  |  Bear trend days: {len(bear_days)}")
by_yr_bear = defaultdict(int)
for d in bear_days:
    by_yr_bear[d.year] += 1
for yr in sorted(by_yr_bear):
    print(f"  {yr} bear days: {by_yr_bear[yr]}")

print("\n" + "="*70)
print("  FADE BEAR TREND FILTER SIM")
print("="*70)
print("  Engine already: FADE LONG skipped on top-2 ATR% tickers")
print("  New filter:     also skip FADE LONG when SPY SMA50 < SMA200")
print("  FADE SHORT:     unaffected")

print("\n" + "─"*70)
print("  BASELINE (all FADE trades — current engine)")
print_breakdown("All FADE", fade_trades)
print_breakdown("  LONG only", long_trades)
print_breakdown("  SHORT only", short_trades)

print("\n" + "─"*70)
print("  WITH BEAR TREND FILTER")
print_breakdown("All FADE", kept)
print_breakdown("  LONG only (kept)", [t for t in kept if t.get("direction") == "LONG"])
print_breakdown("  SHORT only", [t for t in kept if t.get("direction") == "SHORT"])

print(f"\n  Trades dropped (LONG in bear trend): {len(dropped)}")
for t in sorted(dropped, key=lambda x: x["entry_time"]):
    print(f"    {t['entry_time'].date()}  {t.get('ticker','?'):6s}  "
          f"P&L={t['net_pnl']:+.0f}  bull={bull_trend_map.get(t['entry_time'].date())}")

# ── Delta summary ─────────────────────────────────────────────────────────────

print("\n" + "="*70)
print("  DELTA SUMMARY")
print("="*70)
sb = stats(fade_trades)
sa = stats(kept)
print(f"  {'':25} {'Baseline':>12} {'+ Bear filter':>14} {'Delta':>10}")
print(f"  {'-'*62}")
print(f"  {'Trades':25} {sb['n']:>12d} {sa['n']:>14d} {sa['n']-sb['n']:>+10d}")
print(f"  {'Total P&L':25} {sb['pnl']:>+12,.0f} {sa['pnl']:>+14,.0f} {sa['pnl']-sb['pnl']:>+10,.0f}")
print(f"  {'WR':25} {sb['wr']:>11.0%} {sa['wr']:>13.0%}")
print(f"  {'Avg/trade':25} {sb['avg']:>+12.1f} {sa['avg']:>+14.1f} {sa['avg']-sb['avg']:>+10.1f}")

print("\n  By year:")
all_yrs = sorted({t["entry_time"].year for t in fade_trades})
by_yr_base  = defaultdict(list)
by_yr_filt  = defaultdict(list)
for t in fade_trades:
    by_yr_base[t["entry_time"].year].append(t)
for t in kept:
    by_yr_filt[t["entry_time"].year].append(t)

print(f"  {'Year':6} {'Base t':>8} {'Base P&L':>10} {'Filt t':>8} {'Filt P&L':>10} {'Delta':>8}")
print(f"  {'-'*55}")
for yr in all_yrs:
    b = stats(by_yr_base[yr])
    a = stats(by_yr_filt[yr])
    print(f"  {yr:6d} {b['n']:>8d} {b['pnl']:>+10,.0f} {a['n']:>8d} {a['pnl']:>+10,.0f} {a['pnl']-b['pnl']:>+8,.0f}")
