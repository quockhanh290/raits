"""
stress_mid_diagnostic.py — compare STRESS_MID engine vs sim for 2022

Investigates why engine WR=37% in 2022 vs sim WR=63%.

Usage:
  cd d:\\raits\\raits
  python raits\\scripts\\stress_mid_diagnostic.py
"""

import pickle
import sys
import os
from collections import defaultdict
from datetime import time as dtime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

PKL_NEW  = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots", "results_20260619_132029.pkl")
PKL_OLD  = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots", "results_scenario_g.pkl")
PKL_5MIN = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")


class _FallbackUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        try:
            return super().find_class(module, name)
        except (ModuleNotFoundError, AttributeError, ImportError):
            return type(name, (), {})


print("Loading pkls...")
with open(PKL_NEW, "rb") as f:
    results_new = _FallbackUnpickler(f).load()
with open(PKL_OLD, "rb") as f:
    results_old = _FallbackUnpickler(f).load()
with open(PKL_5MIN, "rb") as f:
    data_5min = _FallbackUnpickler(f).load()

for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)


def load_trades(results) -> list[dict]:
    rows = []
    for window in results:
        for t in window.get("trades", []):
            d = vars(t).copy() if hasattr(t, "__dict__") else dict(t)
            rows.append(d)
    for d in rows:
        d["entry_time"] = pd.to_datetime(d["entry_time"])
        d["exit_time"]  = pd.to_datetime(d["exit_time"])
    return rows


rows_new = load_trades(results_new)
rows_old = load_trades(results_old)

sm_all   = [t for t in rows_new if t.get("strategy") == "STRESS_MID"]
sm_2022  = [t for t in sm_all if t["entry_time"].year == 2022]
orb_new  = [t for t in rows_new if t.get("strategy") == "STRESS_ORB"]
orb_2022 = [t for t in orb_new if t["entry_time"].year == 2022]

# Stress day count from old pkl (sim reference)
old_day_regime = {}
for t in rows_old:
    day = t["entry_time"].date()
    state = t.get("hmm_state", "Normal")
    if day not in old_day_regime:
        old_day_regime[day] = state
old_stress_2022 = sorted(d for d, r in old_day_regime.items() if r == "Stress" and d.year == 2022)

# Stress day count from new pkl
new_day_regime = {}
for t in rows_new:
    day = t["entry_time"].date()
    state = t.get("hmm_state", "Normal")
    if day not in new_day_regime:
        new_day_regime[day] = state
new_stress_2022 = sorted(d for d, r in new_day_regime.items() if r == "Stress" and d.year == 2022)


# ── 1. Stress day count comparison ────────────────────────────────────────────

print("\n" + "="*70)
print("  1. STRESS DAY COUNT — 2022")
print("="*70)
print(f"  Old pkl (sim reference): {len(old_stress_2022)} Stress days")
print(f"  New pkl (engine):        {len(new_stress_2022)} Stress days")

old_set = set(old_stress_2022)
new_set = set(new_stress_2022)
only_new = sorted(new_set - old_set)
only_old = sorted(old_set - new_set)
print(f"  Days only in NEW (extra Stress): {len(only_new)}")
for d in only_new[:20]:
    print(f"    {d}")
print(f"  Days only in OLD (missing from new): {len(only_old)}")
for d in only_old[:10]:
    print(f"    {d}")


# ── 2. STRESS_MID 2022 breakdown ──────────────────────────────────────────────

print("\n" + "="*70)
print("  2. STRESS_MID 2022 — EXIT REASONS")
print("="*70)
by_exit = defaultdict(list)
for t in sm_2022:
    by_exit[t.get("exit_reason", "?")].append(t)
for ex, tl in sorted(by_exit.items(), key=lambda x: -len(x[1])):
    p = sum(t["net_pnl"] for t in tl)
    w = sum(1 for t in tl if t["net_pnl"] > 0)
    print(f"  {ex:15s}: {len(tl):3d}t  P&L={p:+,.0f}  WR={w/len(tl):.0%}")


# ── 3. STRESS_MID 2022 — trades on extra Stress days ─────────────────────────

print("\n" + "="*70)
print("  3. STRESS_MID TRADES ON EXTRA STRESS DAYS (only in new pkl)")
print("="*70)
extra_stress_trades = [t for t in sm_2022 if t["entry_time"].date() in only_new]
normal_stress_trades = [t for t in sm_2022 if t["entry_time"].date() not in only_new]

def quick_stats(tl, label):
    if not tl:
        print(f"  {label}: 0 trades")
        return
    p = sum(t["net_pnl"] for t in tl)
    w = sum(1 for t in tl if t["net_pnl"] > 0)
    print(f"  {label}: {len(tl)}t  P&L={p:+,.0f}  WR={w/len(tl):.0%}  avg={p/len(tl):+.1f}")

quick_stats(extra_stress_trades, "Trades on EXTRA days")
quick_stats(normal_stress_trades, "Trades on shared Stress days")


# ── 4. STRESS_ORB vs STRESS_MID ticker conflicts ──────────────────────────────

print("\n" + "="*70)
print("  4. STRESS_ORB CONFLICT — days where STRESS_ORB open at 10:15")
print("="*70)

# Days where STRESS_ORB has a trade overlapping 10:15
ENTRY_TIME = dtime(10, 15)
conflict_days = set()
for t in orb_2022:
    entry = t["entry_time"]
    exit_ = t["exit_time"]
    if entry.time() < ENTRY_TIME and exit_.time() > ENTRY_TIME:
        conflict_days.add(entry.date())

print(f"  2022 days where STRESS_ORB still open at 10:15: {len(conflict_days)}")

sm_on_conflict = [t for t in sm_2022 if t["entry_time"].date() in conflict_days]
sm_no_conflict = [t for t in sm_2022 if t["entry_time"].date() not in conflict_days]
quick_stats(sm_on_conflict, "STRESS_MID trades on conflict days")
quick_stats(sm_no_conflict, "STRESS_MID trades on clean days")


# ── 5. STRESS_MID 2022 stop-hit analysis ──────────────────────────────────────

print("\n" + "="*70)
print("  5. STOP DISTANCE DISTRIBUTION (2022)")
print("="*70)

stop_losers = [t for t in sm_2022 if t.get("exit_reason") == "STOP_HIT"]
stop_winners = [t for t in sm_2022 if t.get("exit_reason") == "TARGET_HIT"]
time_exits   = [t for t in sm_2022 if t.get("exit_reason") == "TIME_STOP"]

print(f"  STOP_HIT:   {len(stop_losers)}  ({len(stop_losers)/len(sm_2022):.0%})")
print(f"  TARGET_HIT: {len(stop_winners)}  ({len(stop_winners)/len(sm_2022):.0%})")
print(f"  TIME_STOP:  {len(time_exits)}  ({len(time_exits)/len(sm_2022):.0%})")

if time_exits:
    te_wins = [t for t in time_exits if t["net_pnl"] > 0]
    print(f"    TIME_STOP winners: {len(te_wins)}/{len(time_exits)}")

# ── 6. Per-ticker 2022 breakdown ──────────────────────────────────────────────

print("\n" + "="*70)
print("  6. BY TICKER — 2022")
print("="*70)
by_tk = defaultdict(list)
for t in sm_2022:
    by_tk[t.get("ticker", "?")].append(t)
for tk, tl in sorted(by_tk.items()):
    p = sum(t["net_pnl"] for t in tl)
    w = sum(1 for t in tl if t["net_pnl"] > 0)
    stop_h = sum(1 for t in tl if t.get("exit_reason") == "STOP_HIT")
    tgt_h  = sum(1 for t in tl if t.get("exit_reason") == "TARGET_HIT")
    time_h = sum(1 for t in tl if t.get("exit_reason") == "TIME_STOP")
    print(f"  {tk:5s}: {len(tl):3d}t  P&L={p:+,.0f}  WR={w/len(tl):.0%}  "
          f"STOP={stop_h} TGT={tgt_h} TIME={time_h}")
