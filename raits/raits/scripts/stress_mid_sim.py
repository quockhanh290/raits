"""
stress_mid_sim.py — Stress 10:15-14:00 ETF momentum (SHORT only)

Hypothesis: SPY/QQQ/IWM continue trending down after ORB window closes at 10:15.
TREND_FOLLOW only starts at 14:00 — covers the 3.75-hr gap on Stress days.

Entry:    10:15 close if price < VWAP(9:30-10:15) AND price < open
Stop A:   swing high (9:45-10:15) + 0.1%   [wider, structural]
Stop B:   VWAP(9:30-10:15) + 0.1%          [tighter, mean-reversion invalidation]
Target:   2R below entry
Time exit: 14:00

Usage:
  cd d:\\raits\\raits
  python raits\\scripts\\stress_mid_sim.py
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

STRESS_UNIVERSE    = ["SPY", "QQQ", "IWM"]
ENTRY_TIME         = dtime(10, 15)
EXIT_TIME          = dtime(14, 0)
SWING_WINDOW_START = dtime(9, 45)
STOP_PAD           = 0.001       # 0.1% pad above stop reference
TARGET_RR          = 2.0
RISK_PER_TRADE     = 500.0
MAX_POSITIONS      = 2
MAX_STOP_PCT       = 0.015       # swing-high only: reject if stop > 1.5% of entry


# ── Helpers ───────────────────────────────────────────────────────────────────

def _vwap(bars: pd.DataFrame) -> float:
    tp  = (bars["high"] + bars["low"] + bars["close"]) / 3
    vol = bars["volume"]
    return float((tp * vol).sum() / vol.sum()) if vol.sum() > 0 else float(bars["close"].iloc[-1])


def _resolve_exit(stop: float, target: float,
                  forward: pd.DataFrame) -> tuple[float, str]:
    """Scan forward bars for first stop/target hit; else return time-stop close."""
    exit_px, exit_reason = float(forward.iloc[-1]["close"]), "TIME_STOP"
    for _, bar in forward.iterrows():
        if float(bar["high"]) >= stop:
            return stop, "STOP_HIT"
        if float(bar["low"]) <= target:
            return target, "TARGET_HIT"
    return exit_px, exit_reason


def _sim_day(day_bars: pd.DataFrame, stop_mode: str) -> dict | None:
    """
    Evaluate one ETF on one Stress day for the 10:15 SHORT entry.
    stop_mode: "swing_high" | "vwap"
    Returns trade dict or None if no signal fires.
    """
    if day_bars.empty or len(day_bars) < 5:
        return None

    open_px  = float(day_bars.iloc[0]["open"])
    at_entry = day_bars[day_bars.index.time == ENTRY_TIME]
    if at_entry.empty:
        return None

    entry_px = float(at_entry.iloc[-1]["close"])
    pre_entry = day_bars[day_bars.index.time <= ENTRY_TIME]
    vwap_val  = _vwap(pre_entry)

    # Signal: below VWAP AND below open
    if entry_px >= vwap_val or entry_px >= open_px:
        return None

    # Stop reference
    if stop_mode == "swing_high":
        swing_bars = day_bars[
            (day_bars.index.time >= SWING_WINDOW_START) &
            (day_bars.index.time <= ENTRY_TIME)
        ]
        ref = float(swing_bars["high"].max()) if not swing_bars.empty else entry_px * 1.005
    else:  # vwap
        ref = vwap_val

    stop      = ref * (1 + STOP_PAD)
    stop_dist = stop - entry_px

    if stop_dist <= 0:
        return None

    # Only apply wide-stop filter for swing_high mode
    if stop_mode == "swing_high" and stop_dist / entry_px > MAX_STOP_PCT:
        return None

    target  = entry_px - TARGET_RR * stop_dist
    shares  = RISK_PER_TRADE / stop_dist

    forward = day_bars[
        (day_bars.index.time > ENTRY_TIME) &
        (day_bars.index.time <= EXIT_TIME)
    ]
    if forward.empty:
        return None

    exit_px, exit_reason = _resolve_exit(stop, target, forward)
    pnl = (entry_px - exit_px) * shares

    return {
        "direction":   "SHORT",
        "entry_px":    entry_px,
        "exit_px":     exit_px,
        "stop":        stop,
        "stop_dist":   stop_dist,
        "target":      target,
        "shares":      shares,
        "exit_reason": exit_reason,
        "net_pnl":     pnl,
        "vwap":        vwap_val,
        "open_px":     open_px,
    }


# ── Load data ─────────────────────────────────────────────────────────────────

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
    day   = t["entry_time"].date()
    state = t.get("hmm_state", "Normal")
    if day not in day_regime:
        day_regime[day] = state

stress_days = sorted(d for d, r in day_regime.items() if r == "Stress")
print(f"Stress days in pkl: {len(stress_days)}")
by_yr_cnt = defaultdict(int)
for d in stress_days:
    by_yr_cnt[d.year] += 1
for yr in sorted(by_yr_cnt):
    print(f"  {yr}: {by_yr_cnt[yr]} days")


# ── Run both variants ─────────────────────────────────────────────────────────

def run_variant(stop_mode: str) -> list[dict]:
    trades = []
    for day in stress_days:
        day_setups = []
        for ticker in STRESS_UNIVERSE:
            if ticker not in data_5min:
                continue
            day_bars = data_5min[ticker][data_5min[ticker].index.date == day]
            if day_bars.empty:
                continue
            result = _sim_day(day_bars, stop_mode)
            if result:
                result["ticker"] = ticker
                result["day"]    = day
                day_setups.append(result)

        if len(day_setups) > MAX_POSITIONS:
            # Most bearish first (furthest below VWAP)
            day_setups.sort(key=lambda x: x["entry_px"] - x["vwap"])
            day_setups = day_setups[:MAX_POSITIONS]
        trades.extend(day_setups)
    return trades


trades_a = run_variant("swing_high")
trades_b = run_variant("vwap")


# ── Print results ─────────────────────────────────────────────────────────────

def print_variant(label: str, trades: list[dict], stop_desc: str):
    print(f"\n{'='*70}")
    print(f"  {label}  —  {stop_desc}")
    print(f"{'='*70}")

    if not trades:
        print("  No trades fired.")
        return

    pnl   = sum(t["net_pnl"] for t in trades)
    wins  = sum(1 for t in trades if t["net_pnl"] > 0)
    wr    = wins / len(trades)
    avg   = pnl / len(trades)

    print(f"  Trades:    {len(trades)}")
    print(f"  Total P&L: {pnl:+,.0f}")
    print(f"  WR:        {wr:.0%}  ({wins}/{len(trades)})")
    print(f"  Avg/trade: {avg:+.1f}")

    # Year
    print(f"\n  By year:")
    by_yr = defaultdict(list)
    for t in trades:
        by_yr[t["day"].year].append(t)
    for yr in sorted(by_yr):
        tl  = by_yr[yr]
        p   = sum(t["net_pnl"] for t in tl)
        w   = sum(1 for t in tl if t["net_pnl"] > 0)
        print(f"    {yr}: {len(tl):3d}t  P&L={p:+7,.0f}  WR={w/len(tl):.0%}  avg={p/len(tl):+.1f}")

    # Exit
    print(f"\n  By exit reason:")
    by_ex = defaultdict(list)
    for t in trades:
        by_ex[t["exit_reason"]].append(t)
    for ex in sorted(by_ex, key=lambda x: -len(by_ex[x])):
        tl = by_ex[ex]
        p  = sum(t["net_pnl"] for t in tl)
        w  = sum(1 for t in tl if t["net_pnl"] > 0)
        print(f"    {ex:15s}: {len(tl):3d}t  P&L={p:+7,.0f}  WR={w/len(tl):.0%}")

    # Ticker
    print(f"\n  By ticker:")
    by_tk = defaultdict(list)
    for t in trades:
        by_tk[t["ticker"]].append(t)
    for tk, tl in sorted(by_tk.items(), key=lambda x: -sum(t["net_pnl"] for t in x[1])):
        p = sum(t["net_pnl"] for t in tl)
        w = sum(1 for t in tl if t["net_pnl"] > 0)
        print(f"    {tk:5s}: {len(tl):2d}t  P&L={p:+7,.0f}  WR={w/len(tl):.0%}")

    # Stop stats + implied position size
    stop_dists = [t["stop_dist"] for t in trades]
    # Estimate typical ETF price from entry prices
    avg_entry = np.mean([t["entry_px"] for t in trades])
    avg_shares = RISK_PER_TRADE / np.mean(stop_dists)
    avg_notional = avg_shares * avg_entry
    print(f"\n  Stop distance ($/share):")
    print(f"    Mean={np.mean(stop_dists):.3f}  Med={np.median(stop_dists):.3f}  Max={np.max(stop_dists):.3f}")
    print(f"  Implied position (avg entry ${avg_entry:.0f}):")
    print(f"    ~{avg_shares:.0f} shares × ${avg_entry:.0f} = ${avg_notional:,.0f} notional")

    # Raw directional edge
    raw_wins, raw_pnl = 0, 0.0
    for t in trades:
        day_bars = data_5min[t["ticker"]][data_5min[t["ticker"]].index.date == t["day"]]
        cands    = day_bars[day_bars.index.time <= EXIT_TIME]
        raw_exit = float(cands.iloc[-1]["close"]) if not cands.empty else t["entry_px"]
        move     = t["entry_px"] - raw_exit
        raw_pnl += move * t["shares"]
        if move > 0:
            raw_wins += 1
    print(f"\n  Raw edge (no stops → 14:00):")
    print(f"    WR={raw_wins}/{len(trades)}={raw_wins/len(trades):.0%}  P&L={raw_pnl:+,.0f}")


print("\n" + "=" * 70)
print("  STRESS MID-MORNING MOMENTUM — STOP METHOD COMPARISON")
print("=" * 70)
print(f"  Entry:   close[10:15] < VWAP(9:30-10:15) AND < open")
print(f"  Target:  {TARGET_RR}R  |  Time exit: 14:00  |  Risk: ${RISK_PER_TRADE:.0f}/trade")
print(f"  Universe: {STRESS_UNIVERSE}  |  Max {MAX_POSITIONS} positions/day")

print_variant(
    "VARIANT A — Swing-High Stop",
    trades_a,
    "stop = max high(9:45-10:15) + 0.1%  [structural high]"
)

print_variant(
    "VARIANT B — VWAP Stop",
    trades_b,
    "stop = VWAP(9:30-10:15) + 0.1%  [MR invalidation]"
)

# ── Side-by-side summary ──────────────────────────────────────────────────────

print(f"\n{'='*70}")
print(f"  COMPARISON SUMMARY")
print(f"{'='*70}")
print(f"  {'':25} {'Swing-High':>12} {'VWAP':>12}")
print(f"  {'-'*50}")

def _stats(trades):
    if not trades:
        return 0, 0, 0, 0
    pnl  = sum(t["net_pnl"] for t in trades)
    wr   = sum(1 for t in trades if t["net_pnl"] > 0) / len(trades)
    avg  = pnl / len(trades)
    mdst = float(np.median([t["stop_dist"] for t in trades]))
    return len(trades), pnl, wr, avg, mdst

na, pa, wa, aa, da = _stats(trades_a)
nb, pb, wb, ab, db = _stats(trades_b)

print(f"  {'Trades':25} {na:>12d} {nb:>12d}")
print(f"  {'Total P&L':25} {pa:>+12,.0f} {pb:>+12,.0f}")
print(f"  {'WR':25} {wa:>11.0%} {wb:>11.0%}")
print(f"  {'Avg/trade':25} {aa:>+12.1f} {ab:>+12.1f}")
print(f"  {'Median stop ($/share)':25} {da:>12.3f} {db:>12.3f}")
