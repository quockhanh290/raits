"""
orb_regime_sim.py — ORB analysis across all regimes

Sections:
  1. Normal ORB deep-dive: year / direction / exit / entry-time breakdown
  2. Calm ORB sim: run ORB logic on Calm days using 5-min data
  3. STRESS_ORB sim: run ORB on SPY/QQQ/IWM on Stress days
  4. Summary: enablement recommendation

Usage:
  cd d:\\raits\\raits
  python raits\\scripts\\orb_regime_sim.py
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

# ── Config matching engine ─────────────────────────────────────────────────────
MIN_GAP_PCT          = 0.01     # 1% gap filter
MIN_RANGE_ATR_MULT   = 0.5
MAX_RANGE_ATR_MULT   = 5.0
MIN_RANGE_ABS        = 0.20
RVOL_THRESHOLD       = 2.0
FAKEOUT_WICK_RATIO   = 0.5
TARGET_RR            = 2.0
OR_START             = dtime(9, 30)
OR_END               = dtime(9, 44)
SIG_START            = dtime(9, 45)
SIG_END              = dtime(10, 15)
STRESS_UNIVERSE      = ["SPY", "QQQ", "IWM"]
RISK_PER_TRADE       = 500.0   # same as sim convention

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _atr(bars: pd.DataFrame, n: int = 14) -> float:
    hi = bars["high"]
    lo = bars["low"]
    cl = bars["close"].shift(1)
    tr = pd.concat([hi - lo, (hi - cl).abs(), (lo - cl).abs()], axis=1).max(axis=1)
    return float(tr.rolling(n, min_periods=1).mean().iloc[-1])


def _vwap(bars: pd.DataFrame) -> float:
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3
    return float((tp * bars["volume"]).sum() / bars["volume"].sum())


def _check_fakeout(candle: pd.Series, direction: str) -> bool:
    body = abs(float(candle["close"]) - float(candle["open"]))
    if body < 0.01:
        return True
    if direction == "LONG":
        wick = float(candle["high"]) - max(float(candle["close"]), float(candle["open"]))
        return wick > FAKEOUT_WICK_RATIO * body
    else:
        wick = min(float(candle["close"]), float(candle["open"])) - float(candle["low"])
        return wick > FAKEOUT_WICK_RATIO * body


def _sim_orb_day(day_bars: pd.DataFrame, prev_close: float | None = None,
                 require_gap: bool = True) -> list[dict]:
    """
    Run ORB simulation on a single ticker's intraday 5-min bars for one day.
    RVOL uses engine's exact formula: bars_so_far["volume"].mean().
    Note: with 5-min data this is stricter than engine's 1-min behavior.
    Returns list of trade dicts (empty if no setup fires).
    """
    if day_bars.empty or len(day_bars) < 4:
        return []

    open_price = float(day_bars.iloc[0]["open"])

    # Gap filter
    if require_gap and prev_close is not None:
        gap_pct = abs(open_price - prev_close) / prev_close
        if gap_pct < MIN_GAP_PCT:
            return []

    # OR formation: 9:30–9:44
    or_bars = day_bars[
        (day_bars.index.time >= OR_START) & (day_bars.index.time <= OR_END)
    ]
    if or_bars.empty:
        return []

    atr = _atr(day_bars)
    if atr <= 0:
        return []

    or_high = float(or_bars["high"].max())
    or_low  = float(or_bars["low"].min())
    or_range = or_high - or_low

    min_range = max(MIN_RANGE_ATR_MULT * atr, MIN_RANGE_ABS)
    max_range = MAX_RANGE_ATR_MULT * atr
    if or_range < min_range or or_range > max_range:
        return []

    # Signal window: 9:45–10:15
    sig_bars = day_bars[
        (day_bars.index.time >= SIG_START) & (day_bars.index.time <= SIG_END)
    ]
    if sig_bars.empty:
        return []

    trades_out = []
    pending = None

    bars_up_to = day_bars[day_bars.index.time <= SIG_END]

    for ts, candle in sig_bars.iterrows():
        close = float(candle["close"])

        # Check pending (delayed entry: bar B+1)
        if pending is not None:
            direction = pending["direction"]
            is_fakeout = pending.get("is_fakeout", False)

            confirmed = False
            if direction == "LONG" and close > or_high and not is_fakeout:
                confirmed = True
                entry_px = close
            elif direction == "SHORT" and close < or_low and not is_fakeout:
                confirmed = True
                entry_px = close

            if confirmed:
                bars_for_vwap = bars_up_to.loc[:ts]
                vwap_val = _vwap(bars_for_vwap)
                if direction == "LONG":
                    stop = min(or_low, vwap_val)
                else:
                    stop = max(or_high, vwap_val)
                risk = abs(entry_px - stop)
                if risk > 0:
                    target = (entry_px + TARGET_RR * risk) if direction == "LONG" else (entry_px - TARGET_RR * risk)
                    shares = RISK_PER_TRADE / risk
                    trades_out.append({
                        "direction": direction,
                        "entry_px":  entry_px,
                        "stop":      stop,
                        "target":    target,
                        "risk":      risk,
                        "shares":    shares,
                        "entry_ts":  ts,
                    })
            pending = None
            continue

        # Already have a trade for today (max 1 per ticker per day in this sim)
        if trades_out:
            continue

        # Detect breakout
        direction = None
        if close > or_high:
            direction = "LONG"
        elif close < or_low:
            direction = "SHORT"
        else:
            continue

        # RVOL — exact engine formula: bars_so_far["volume"].mean()
        # NOTE: Engine uses 1-min bars (17+ bars at 9:46 → 9:30 spike diluted).
        #       Sim uses 5-min bars (4 bars at 9:45 → spike dominates → RVOL low).
        #       This will show how many trades survive engine formula with 5-min data.
        bars_so_far_rvol = day_bars[day_bars.index <= ts]
        hist_avg = max(float(bars_so_far_rvol["volume"].mean()), 1.0)
        rvol = float(candle["volume"]) / hist_avg
        if rvol < RVOL_THRESHOLD:
            continue

        is_fakeout = _check_fakeout(candle, direction)
        pending = {"direction": direction, "is_fakeout": is_fakeout}

    return trades_out


def _resolve_pnl(setup: dict, day_bars: pd.DataFrame, direction_filter: str | None = None) -> dict:
    """
    Given an ORB setup (with entry_px, stop, target, shares, entry_ts),
    scan forward bars to determine exit and P&L.
    direction_filter: if set, skip setups not matching this direction.
    """
    if direction_filter and setup["direction"] != direction_filter:
        return None

    direction = setup["direction"]
    entry_px  = setup["entry_px"]
    stop      = setup["stop"]
    target    = setup["target"]
    shares    = setup["shares"]
    entry_ts  = setup["entry_ts"]

    after_entry = day_bars[day_bars.index > entry_ts]
    exit_reason = "TIME_STOP"
    exit_px = float(after_entry.iloc[-1]["close"]) if not after_entry.empty else entry_px

    for _, bar in after_entry.iterrows():
        if direction == "LONG":
            if float(bar["low"]) <= stop:
                exit_px = stop
                exit_reason = "STOP_HIT"
                break
            if float(bar["high"]) >= target:
                exit_px = target
                exit_reason = "TARGET_HIT"
                break
        else:
            if float(bar["high"]) >= stop:
                exit_px = stop
                exit_reason = "STOP_HIT"
                break
            if float(bar["low"]) <= target:
                exit_px = target
                exit_reason = "TARGET_HIT"
                break

    if direction == "LONG":
        pnl = (exit_px - entry_px) * shares
    else:
        pnl = (entry_px - exit_px) * shares

    return {**setup, "exit_px": exit_px, "exit_reason": exit_reason, "net_pnl": pnl}


# ─────────────────────────────────────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────────────────────────────────────

class _FallbackUnpickler(pickle.Unpickler):
    """Return a plain object stub for any class that can't be imported."""
    def find_class(self, module, name):
        try:
            return super().find_class(module, name)
        except (ModuleNotFoundError, AttributeError, ImportError):
            # Return a generic stub class whose instances will have __dict__
            return type(name, (), {})

print("Loading pkl files...")
with open(PKL_RESULTS, "rb") as f:
    results = _FallbackUnpickler(f).load()
with open(PKL_5MIN, "rb") as f:
    data_5min = _FallbackUnpickler(f).load()

for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# Flatten window list → list of plain dicts (matching vmr_improve_sim.py pattern)
rows = []
for window in results:
    yr = window.get("label", "?")
    for t in window.get("trades", []):
        d = vars(t).copy() if hasattr(t, "__dict__") else dict(t)
        d["year"] = yr
        rows.append(d)

for d in rows:
    d["entry_time"] = pd.to_datetime(d["entry_time"])
    d["exit_time"]  = pd.to_datetime(d["exit_time"])

all_trades = rows
orb_trades = [t for t in all_trades if t.get("strategy") == "ORB"]
print(f"Total trades: {len(all_trades)} | ORB trades: {len(orb_trades)}")

# ─────────────────────────────────────────────────────────────────────────────
# Determine regime per calendar day from trade records
# ─────────────────────────────────────────────────────────────────────────────

day_regime: dict = {}
for t in all_trades:
    d = t["entry_time"].date()
    state = t.get("hmm_state", "Normal")
    if d not in day_regime:
        day_regime[d] = state
    # ORB only fires in Normal → if any ORB trade on this day, it's Normal
    if t.get("strategy") == "ORB":
        day_regime[d] = "Normal"

regime_days = defaultdict(set)
for d, r in day_regime.items():
    regime_days[r].add(d)

print(f"\nDays with trades by regime:")
for r in ["Calm", "Normal", "Stress"]:
    print(f"  {r}: {len(regime_days[r])} days")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1: Normal ORB deep-dive
# ═════════════════════════════════════════════════════════════════════════════

print("\n" + "="*70)
print("SECTION 1: NORMAL ORB — EXISTING TRADES")
print("="*70)

total_pnl = sum(t["net_pnl"] for t in orb_trades)
wins = [t for t in orb_trades if t["net_pnl"] > 0]
losses = [t for t in orb_trades if t["net_pnl"] <= 0]
wr = len(wins) / len(orb_trades) if orb_trades else 0

print(f"\nOverall: {len(orb_trades)}t  P&L={total_pnl:+.0f}  WR={wr:.0%}")
print(f"  Avg win:  ${np.mean([t['net_pnl'] for t in wins]):.1f}" if wins else "  No wins")
print(f"  Avg loss: ${np.mean([t['net_pnl'] for t in losses]):.1f}" if losses else "  No losses")

# Year breakdown
print("\nBy year:")
by_year = defaultdict(list)
for t in orb_trades:
    by_year[t["entry_time"].year].append(t)
for yr in sorted(by_year):
    tl = by_year[yr]
    pnl = sum(t["net_pnl"] for t in tl)
    w = sum(1 for t in tl if t["net_pnl"] > 0)
    print(f"  {yr}: {len(tl):3d}t  P&L={pnl:+6.0f}  WR={w/len(tl):.0%}")

# Direction
print("\nBy direction:")
for direction in ["LONG", "SHORT"]:
    dt = [t for t in orb_trades if t["direction"] == direction]
    if not dt:
        print(f"  {direction}: 0 trades")
        continue
    pnl = sum(t["net_pnl"] for t in dt)
    w = sum(1 for t in dt if t["net_pnl"] > 0)
    print(f"  {direction}: {len(dt):3d}t  P&L={pnl:+6.0f}  WR={w/len(dt):.0%}")

# Year × Direction
print("\nYear × Direction:")
for yr in sorted(by_year):
    for direction in ["LONG", "SHORT"]:
        dt = [t for t in by_year[yr] if t["direction"] == direction]
        if not dt:
            continue
        pnl = sum(t["net_pnl"] for t in dt)
        w = sum(1 for t in dt if t["net_pnl"] > 0)
        print(f"  {yr} {direction}: {len(dt):2d}t  P&L={pnl:+6.0f}  WR={w/len(dt):.0%}")

# Exit type
print("\nExit type:")
by_exit = defaultdict(list)
for t in orb_trades:
    by_exit[t.get("exit_reason", "?")].append(t)
for ex in sorted(by_exit, key=lambda x: -len(by_exit[x])):
    tl = by_exit[ex]
    pnl = sum(t["net_pnl"] for t in tl)
    w = sum(1 for t in tl if t["net_pnl"] > 0)
    print(f"  {ex}: {len(tl):3d}t  P&L={pnl:+6.0f}  WR={w/len(tl):.0%}")

# Entry time slot
print("\nEntry time slot:")
slots = [
    ("9:45-9:54", dtime(9, 45), dtime(9, 54)),
    ("9:55-10:04", dtime(9, 55), dtime(10, 4)),
    ("10:05-10:15", dtime(10, 5), dtime(10, 15)),
]
for label, t_lo, t_hi in slots:
    st = [t for t in orb_trades if t_lo <= t["entry_time"].time() <= t_hi]
    if not st:
        continue
    pnl = sum(t["net_pnl"] for t in st)
    w = sum(1 for t in st if t["net_pnl"] > 0)
    print(f"  {label}: {len(st):2d}t  P&L={pnl:+6.0f}  WR={w/len(st):.0%}")

# Ticker breakdown (top 10 by |P&L|)
print("\nTop tickers:")
by_ticker = defaultdict(list)
for t in orb_trades:
    by_ticker[t["ticker"]].append(t)
ticker_pnl = [(tk, sum(t["net_pnl"] for t in tl), len(tl)) for tk, tl in by_ticker.items()]
ticker_pnl.sort(key=lambda x: x[1], reverse=True)
for tk, pnl, n in ticker_pnl[:10]:
    tl = by_ticker[tk]
    w = sum(1 for t in tl if t["net_pnl"] > 0)
    print(f"  {tk:6s}: {n:2d}t  P&L={pnl:+6.0f}  WR={w/n:.0%}")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2: CALM ORB SIMULATION
# ═════════════════════════════════════════════════════════════════════════════

print("\n" + "="*70)
print("SECTION 2: CALM ORB SIM (ORB added to Calm regime)")
print("="*70)

calm_days = sorted(regime_days["Calm"])
print(f"\nCalm days found: {len(calm_days)}")

by_year_calm = defaultdict(list)
for d in calm_days:
    by_year_calm[d.year].append(d)
for yr in sorted(by_year_calm):
    print(f"  {yr}: {len(by_year_calm[yr])} days")

# Build prev_close lookup: for each (ticker, date) → prev day's close
print("\nBuilding prev_close + timeslot-avg cache...")
ticker_daily_close: dict = {}
ticker_timeslot_avg: dict = {}   # {ticker: {time → avg_volume}}
for ticker, bars in data_5min.items():
    if bars.empty:
        continue
    daily = bars["close"].resample("D").last().dropna()
    ticker_daily_close[ticker] = daily
    # Per-timeslot avg from full dataset — proxy for per-slot historical avg
    ticker_timeslot_avg[ticker] = bars.groupby(bars.index.time)["volume"].mean().to_dict()

def get_prev_close(ticker: str, day) -> float | None:
    daily = ticker_daily_close.get(ticker)
    if daily is None:
        return None
    day_ts = pd.Timestamp(day)
    prior = daily[daily.index < day_ts]
    if prior.empty:
        return None
    return float(prior.iloc[-1])

# Calm ORB universe: tickers that appeared in actual ORB trades — these are
# what the ORBUniverseScanner selected in Normal regime. Same criteria apply
# in Calm (gap + ATR). This is more faithful than all-non-TF tickers.
calm_orb_tickers = set(t["ticker"] for t in orb_trades)
print(f"\nCalm ORB universe (from ORB scanner history): {len(calm_orb_tickers)} tickers")

MAX_ORB_POSITIONS = 2   # engine: MAX_ORB = 2

calm_sim_trades = []
calm_day_stats = []

for day in calm_days:
    day_setups = []

    for ticker in calm_orb_tickers:
        if ticker not in data_5min:
            continue
        bars = data_5min[ticker]
        day_bars = bars[bars.index.date == day]
        if day_bars.empty:
            continue

        prev_close = get_prev_close(ticker, day)
        ts_avg = ticker_timeslot_avg.get(ticker)
        setups = _sim_orb_day(day_bars, prev_close, require_gap=True)
        for s in setups:
            result = _resolve_pnl(s, day_bars)
            if result:
                result["ticker"] = ticker
                result["day"] = day
                day_setups.append(result)

    # Apply position cap: take only first MAX_ORB_POSITIONS by entry time
    day_setups.sort(key=lambda x: x["entry_ts"])
    day_setups = day_setups[:MAX_ORB_POSITIONS]

    calm_day_stats.append({"day": day, "n_trades": len(day_setups)})
    calm_sim_trades.extend(day_setups)

print(f"\nCalm ORB sim results:")
print(f"  Total setups fired: {len(calm_sim_trades)}")
if calm_sim_trades:
    pnl_total = sum(t["net_pnl"] for t in calm_sim_trades)
    wins_c = sum(1 for t in calm_sim_trades if t["net_pnl"] > 0)
    wr_c = wins_c / len(calm_sim_trades)
    print(f"  Total P&L:  {pnl_total:+.0f}")
    print(f"  WR:         {wr_c:.0%}")
    avg_per_trade = pnl_total / len(calm_sim_trades)
    print(f"  Avg/trade:  {avg_per_trade:+.1f}")

    print("\nCalm ORB by year:")
    by_yr_c = defaultdict(list)
    for t in calm_sim_trades:
        by_yr_c[t["day"].year].append(t)
    for yr in sorted(by_yr_c):
        tl = by_yr_c[yr]
        pnl = sum(t["net_pnl"] for t in tl)
        w = sum(1 for t in tl if t["net_pnl"] > 0)
        print(f"  {yr}: {len(tl):3d}t  P&L={pnl:+6.0f}  WR={w/len(tl):.0%}")

    print("\nCalm ORB by direction:")
    for direction in ["LONG", "SHORT"]:
        dt = [t for t in calm_sim_trades if t["direction"] == direction]
        if not dt:
            continue
        pnl = sum(t["net_pnl"] for t in dt)
        w = sum(1 for t in dt if t["net_pnl"] > 0)
        print(f"  {direction}: {len(dt):3d}t  P&L={pnl:+6.0f}  WR={w/len(dt):.0%}")

    print("\nCalm ORB exit type:")
    by_ex_c = defaultdict(list)
    for t in calm_sim_trades:
        by_ex_c[t["exit_reason"]].append(t)
    for ex in sorted(by_ex_c, key=lambda x: -len(by_ex_c[x])):
        tl = by_ex_c[ex]
        pnl = sum(t["net_pnl"] for t in tl)
        print(f"  {ex}: {len(tl):3d}t  P&L={pnl:+6.0f}")

    days_with_trade = sum(1 for s in calm_day_stats if s["n_trades"] > 0)
    print(f"\n  Days with ≥1 trade: {days_with_trade}/{len(calm_days)} ({days_with_trade/len(calm_days):.0%})")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3: STRESS_ORB SIMULATION (SPY/QQQ/IWM only)
# ═════════════════════════════════════════════════════════════════════════════

print("\n" + "="*70)
print("SECTION 3: STRESS_ORB SIM (SPY/QQQ/IWM, SHORT only in bear)")
print("="*70)

stress_days = sorted(regime_days["Stress"])
print(f"\nStress days found: {len(stress_days)}")

by_year_stress = defaultdict(list)
for d in stress_days:
    by_year_stress[d.year].append(d)
for yr in sorted(by_year_stress):
    print(f"  {yr}: {len(by_year_stress[yr])} days")

# Determine bear/bull trend per day from SPY (SMA50 vs SMA200)
spy_bars_all = data_5min.get("SPY", pd.DataFrame())
spy_daily_close = spy_bars_all["close"].resample("D").last().dropna() if not spy_bars_all.empty else pd.Series()

def is_bull_trend(day) -> bool:
    if spy_daily_close.empty:
        return True
    prior = spy_daily_close[spy_daily_close.index < pd.Timestamp(day)]
    if len(prior) < 50:
        return True
    sma50  = float(prior.iloc[-50:].mean())
    sma200 = float(prior.iloc[-200:].mean()) if len(prior) >= 200 else float(prior.mean())
    return sma50 > sma200

MAX_STRESS_ORB_POSITIONS = 2   # engine: STRATEGY_CAPS["STRESS_ORB"] = 2

stress_sim_trades = []
stress_day_stats = []

for day in stress_days:
    day_bull = is_bull_trend(day)
    day_setups = []

    for ticker in STRESS_UNIVERSE:
        if ticker not in data_5min:
            continue
        bars = data_5min[ticker]
        day_bars = bars[bars.index.date == day]
        if day_bars.empty:
            continue

        ts_avg = ticker_timeslot_avg.get(ticker)
        # No gap filter for ETFs (same as engine config: min_gap_pct=0.0)
        setups = _sim_orb_day(day_bars, prev_close=None, require_gap=False)
        for s in setups:
            # SHORT only — regardless of trend (testing pure directional filter)
            direction_filter = "SHORT"
            result = _resolve_pnl(s, day_bars, direction_filter=direction_filter)
            if result:
                result["ticker"] = ticker
                result["day"] = day
                result["bull_trend"] = day_bull
                day_setups.append(result)

    # Apply position cap: take only first MAX_STRESS_ORB_POSITIONS by entry time
    day_setups.sort(key=lambda x: x["entry_ts"])
    day_setups = day_setups[:MAX_STRESS_ORB_POSITIONS]

    stress_day_stats.append({"day": day, "n_trades": len(day_setups)})
    stress_sim_trades.extend(day_setups)

print(f"\nSTRESS_ORB sim results:")
print(f"  Total setups fired: {len(stress_sim_trades)}")
if stress_sim_trades:
    pnl_total = sum(t["net_pnl"] for t in stress_sim_trades)
    wins_s = sum(1 for t in stress_sim_trades if t["net_pnl"] > 0)
    wr_s = wins_s / len(stress_sim_trades)
    print(f"  Total P&L:  {pnl_total:+.0f}")
    print(f"  WR:         {wr_s:.0%}")
    avg_per_trade = pnl_total / len(stress_sim_trades)
    print(f"  Avg/trade:  {avg_per_trade:+.1f}")

    print("\nSTRESS_ORB by year:")
    by_yr_s = defaultdict(list)
    for t in stress_sim_trades:
        by_yr_s[t["day"].year].append(t)
    for yr in sorted(by_yr_s):
        tl = by_yr_s[yr]
        pnl = sum(t["net_pnl"] for t in tl)
        w = sum(1 for t in tl if t["net_pnl"] > 0)
        print(f"  {yr}: {len(tl):3d}t  P&L={pnl:+6.0f}  WR={w/len(tl):.0%}")

    print("\nSTRESS_ORB by direction:")
    for direction in ["LONG", "SHORT"]:
        dt = [t for t in stress_sim_trades if t["direction"] == direction]
        if not dt:
            continue
        pnl = sum(t["net_pnl"] for t in dt)
        w = sum(1 for t in dt if t["net_pnl"] > 0)
        print(f"  {direction}: {len(dt):3d}t  P&L={pnl:+6.0f}  WR={w/len(dt):.0%}")

    print("\nSTRESS_ORB by ticker:")
    by_tk_s = defaultdict(list)
    for t in stress_sim_trades:
        by_tk_s[t["ticker"]].append(t)
    for tk, tl in sorted(by_tk_s.items(), key=lambda x: -sum(t["net_pnl"] for t in x[1])):
        pnl = sum(t["net_pnl"] for t in tl)
        w = sum(1 for t in tl if t["net_pnl"] > 0)
        print(f"  {tk:5s}: {len(tl):2d}t  P&L={pnl:+6.0f}  WR={w/len(tl):.0%}")

    print("\nSTRESS_ORB exit type:")
    by_ex_s = defaultdict(list)
    for t in stress_sim_trades:
        by_ex_s[t["exit_reason"]].append(t)
    for ex in sorted(by_ex_s, key=lambda x: -len(by_ex_s[x])):
        tl = by_ex_s[ex]
        pnl = sum(t["net_pnl"] for t in tl)
        print(f"  {ex}: {len(tl):3d}t  P&L={pnl:+6.0f}")

    days_with_trade = sum(1 for s in stress_day_stats if s["n_trades"] > 0)
    print(f"\n  Days with ≥1 trade: {days_with_trade}/{len(stress_days)} ({days_with_trade/len(stress_days):.0%})")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 4: SUMMARY
# ═════════════════════════════════════════════════════════════════════════════

print("\n" + "="*70)
print("SECTION 4: SUMMARY")
print("="*70)

base_orb_pnl  = sum(t["net_pnl"] for t in orb_trades)
calm_orb_pnl  = sum(t["net_pnl"] for t in calm_sim_trades)  if calm_sim_trades  else 0
stress_orb_pnl = sum(t["net_pnl"] for t in stress_sim_trades) if stress_sim_trades else 0

print(f"\nNormal ORB (existing): {len(orb_trades)}t  P&L={base_orb_pnl:+.0f}")
print(f"Calm ORB (sim):        {len(calm_sim_trades)}t  P&L={calm_orb_pnl:+.0f}")
print(f"STRESS_ORB (sim):      {len(stress_sim_trades)}t  P&L={stress_orb_pnl:+.0f}")
print(f"\nPotential system P&L uplift from enabling both: {calm_orb_pnl + stress_orb_pnl:+.0f}")

baseline_sys = sum(t["net_pnl"] for t in all_trades)
new_sys = baseline_sys + calm_orb_pnl + stress_orb_pnl
print(f"\nCurrent system P&L:    {baseline_sys:+.0f}")
print(f"With Calm+Stress ORB:  {new_sys:+.0f}")
