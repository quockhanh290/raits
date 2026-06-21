"""
non_gap_orb_sim.py — Non-gap stocks Opening Range Breakout

Existing ORB only scans stocks with gap ≥1.5% vs prev close.
This sim tests stocks with gap <1.5% — no directional gap bias,
but still form clean OR ranges and break cleanly.

OR formation:  9:30–9:44 (same 15-min window as engine ORB)
Entry:         first 5-min bar close breaking OR high/low, 9:45–10:15
Stop:          OR_low - 0.1×ATR (LONG) | OR_high + 0.1×ATR (SHORT)
Target:        2R
Time exit:     15:55 (same as engine ORB)
Bear filter:   SMA50 < SMA200 → block LONG (same as engine ORB)

Filters (to reduce false breaks on non-gap stocks):
  - gap < 1.5% (not in existing ORB universe)
  - ATR% 0.5–3% (liquid but not hyper-volatile)
  - OR range ≥ 0.3% of price (meaningful range formed)
  - stop ≤ 2% of entry price

Engine conditions replicated:
  - Normal regime (from pkl hmm_state)
  - SMA50/200 bear trend LONG block
  - Max 3 positions/day (sorted by tightest OR range relative to ATR)

Usage:
  cd d:\\raits\\raits
  python raits\\scripts\\non_gap_orb_sim.py
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

OR_START       = dtime(9, 30)
OR_END         = dtime(9, 44)
ENTRY_START    = dtime(9, 45)
ENTRY_END      = dtime(10, 15)
TIME_EXIT      = dtime(15, 55)

MAX_GAP_PCT    = 0.015   # exclude stocks in existing ORB universe (gap ≥ 1.5%)
MIN_ATR_PCT    = 0.005   # 0.5% — filter illiquid/flat stocks
MAX_ATR_PCT    = 0.030   # 3.0% — filter hyper-volatile (those tend toward ORB)
MIN_OR_RANGE   = 0.003   # OR range ≥ 0.3% of price
MAX_STOP_PCT   = 0.020   # reject if stop > 2% of entry
TARGET_RR      = 2.0
RISK_PER_TRADE = 500.0
MAX_POSITIONS  = 3


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
print(f"Tickers available: {len(tickers)}")


# ── SMA50/200 bear trend (same as engine) ─────────────────────────────────────

spy_daily = (
    spy_bars["close"]
    .resample("D")
    .last()
    .dropna()
    .sort_index()
)

def is_bull_trend(trade_date) -> bool:
    ts = pd.Timestamp(trade_date)
    prior = spy_daily[spy_daily.index < ts]
    if len(prior) < 200:
        return True   # not enough history → allow LONG
    return float(prior.iloc[-50:].mean()) > float(prior.iloc[-200:].mean())


bull_map = {d: is_bull_trend(d) for d in normal_days}


# ── Helpers ───────────────────────────────────────────────────────────────────

def compute_atr(bars: pd.DataFrame) -> float:
    if len(bars) < 2:
        return 0.0
    return float((bars["high"] - bars["low"]).abs().mean())


def sim_ticker(ticker: str, day, bull_trend: bool) -> dict | None:
    bars = data_5min[ticker][data_5min[ticker].index.date == day].sort_index()
    if bars.empty:
        return None

    # OR bars (9:30–9:44)
    or_bars = bars[
        (bars.index.time >= OR_START) &
        (bars.index.time <= OR_END)
    ]
    if len(or_bars) < 2:
        return None

    or_high = float(or_bars["high"].max())
    or_low  = float(or_bars["low"].min())
    or_open = float(or_bars.iloc[0]["open"])
    atr     = compute_atr(or_bars)
    if atr <= 0:
        return None

    or_range_pct = (or_high - or_low) / or_open
    atr_pct      = atr / or_open

    if or_range_pct < MIN_OR_RANGE:
        return None
    if atr_pct < MIN_ATR_PCT or atr_pct > MAX_ATR_PCT:
        return None

    # Prev close → gap check
    prev_bars = bars[bars.index.time < OR_START]
    prev_close = float(prev_bars.iloc[-1]["close"]) if not prev_bars.empty else None
    if prev_close is None:
        # Try to get prev day last close from full data
        all_bars = data_5min[ticker]
        day_ts   = pd.Timestamp(day)
        prev_day = all_bars[all_bars.index.normalize() < day_ts]
        if prev_day.empty:
            return None
        prev_close = float(prev_day.iloc[-1]["close"])

    gap_pct = abs(or_open - prev_close) / prev_close
    if gap_pct >= MAX_GAP_PCT:
        return None   # belongs to existing ORB universe

    # Entry scan (9:45–10:15)
    entry_bars = bars[
        (bars.index.time >= ENTRY_START) &
        (bars.index.time <= ENTRY_END)
    ]
    if entry_bars.empty:
        return None

    entry_bar = None
    direction = None
    for ts, bar in entry_bars.iterrows():
        close = float(bar["close"])
        if close > or_high and (bull_trend or True):   # LONG allowed
            if not bull_trend:
                continue   # bear trend → skip LONG
            entry_bar, direction = bar, "LONG"
            entry_ts = ts
            break
        if close < or_low:
            entry_bar, direction = bar, "SHORT"
            entry_ts = ts
            break

    if entry_bar is None:
        return None

    entry_px = float(entry_bar["close"])

    if direction == "LONG":
        stop_px   = or_low  - 0.1 * atr
        stop_dist = entry_px - stop_px
    else:
        stop_px   = or_high + 0.1 * atr
        stop_dist = stop_px - entry_px

    if stop_dist <= 0 or stop_dist / entry_px > MAX_STOP_PCT:
        return None

    target_px = (entry_px + TARGET_RR * stop_dist) if direction == "LONG" \
                else (entry_px - TARGET_RR * stop_dist)

    # OR tightness: how tight OR was relative to ATR (tighter = more decisive breakout)
    or_tightness = or_range_pct / atr_pct  # < 1 means range tighter than usual ATR

    # Forward simulation
    forward = bars[
        (bars.index.time > entry_ts.time()) &
        (bars.index.time <= TIME_EXIT)
    ]
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
        "ticker":       ticker,
        "day":          day,
        "direction":    direction,
        "entry_px":     entry_px,
        "exit_px":      exit_px,
        "exit_why":     exit_why,
        "stop_px":      stop_px,
        "stop_dist":    stop_dist,
        "target_px":    target_px,
        "shares":       shares,
        "net_pnl":      pnl,
        "or_range_pct": or_range_pct,
        "atr_pct":      atr_pct,
        "gap_pct":      gap_pct,
        "or_tightness": or_tightness,
    }


# ── Run sim ────────────────────────────────────────────────────────────────────

print("\nRunning simulation (Normal days × all tickers)...")
all_trades = []

for day in normal_days:
    bull = bull_map[day]
    day_setups = []

    for ticker in tickers:
        if ticker not in data_5min:
            continue
        result = sim_ticker(ticker, day, bull)
        if result:
            day_setups.append(result)

    # Sort: tightest OR range relative to ATR first (most coiled = cleanest break)
    day_setups.sort(key=lambda x: x["or_tightness"])
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
print("  NON-GAP STOCKS ORB SIM")
print("="*70)
print(f"  OR window: {OR_START}–{OR_END}  |  Entry: {ENTRY_START}–{ENTRY_END}  |  Exit: {TIME_EXIT}")
print(f"  Gap filter:   < {MAX_GAP_PCT:.1%} (avoid existing ORB universe)")
print(f"  ATR filter:   {MIN_ATR_PCT:.1%}–{MAX_ATR_PCT:.1%}")
print(f"  OR range:     ≥ {MIN_OR_RANGE:.1%} of price")
print(f"  Stop cap:     ≤ {MAX_STOP_PCT:.1%} of entry")
print(f"  Target:       {TARGET_RR}R  |  Cap: {MAX_POSITIONS}/day (tightest OR first)")
print(f"  Bear filter:  LONG blocked when SMA50 < SMA200")

print_breakdown("All trades", all_trades)

longs  = [t for t in all_trades if t["direction"] == "LONG"]
shorts = [t for t in all_trades if t["direction"] == "SHORT"]
print_breakdown("LONG", longs)
print_breakdown("SHORT", shorts)

# Exit reasons
print("\n  By exit reason:")
by_ex = defaultdict(list)
for t in all_trades:
    by_ex[t["exit_why"]].append(t)
for ex, tl in sorted(by_ex.items(), key=lambda x: -len(x[1])):
    p = sum(t["net_pnl"] for t in tl)
    w = sum(1 for t in tl if t["net_pnl"] > 0)
    print(f"    {ex:12s}: {len(tl):3d}t  P&L={p:+,.0f}  WR={w/len(tl):.0%}")

# Stop distance
stop_dists = [t["stop_dist"]    for t in all_trades]
entries    = [t["entry_px"]     for t in all_trades]
or_ranges  = [t["or_range_pct"] for t in all_trades]
if stop_dists:
    avg_stop   = float(np.mean(stop_dists))
    avg_entry  = float(np.mean(entries))
    avg_shares = RISK_PER_TRADE / avg_stop
    print(f"\n  Stop distance:  mean=${avg_stop:.2f}  →  ~{avg_shares:.0f} shares @ ${avg_entry:.0f}")
    print(f"  OR range:       mean={float(np.mean(or_ranges)):.2%}  "
          f"med={float(np.median(or_ranges)):.2%}")
