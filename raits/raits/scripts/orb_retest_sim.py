"""
orb_retest_sim.py — ORB boundary retest trong Calm regime (10:15–14:00).

Setup:
  - Calm regime days only
  - OR range = 9:35–10:15 high/low per ticker
  - bar_high >= OR_high → SHORT at close, stop = OR_high + 0.5×ATR, target = OR_midpoint
  - bar_low  <= OR_low  → LONG  at close, stop = OR_low  - 0.5×ATR, target = OR_midpoint
  - First signal per ticker per day only
  - Exit: target / stop / TIME_STOP at 14:00

Usage:
    cd D:\raits\raits
    python raits\scripts\orb_retest_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime

import glob as _glob

PKL_RESULTS = r'd:\raits\raits\data\cache\window_debug_results.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
CACHE_5MIN  = r'd:\raits\raits\data\cache\data'

print("Loading results...")
with open(PKL_RESULTS, "rb") as f: results = pickle.load(f)

# Load low-beta tickers from parquet cache
LOW_BETA = [
    "PG","KO","PEP","WMT","MO","CL","KMB","GIS","MDLZ",
    "NEE","DUK","SO","D","AEP",
    "JNJ","ABT","MRK","PFE","BMY",
    "BRK.B","WFC","USB",
]

print("Loading low-beta 5-min data from parquet...")
data_5min = {}
missing = []
for ticker in LOW_BETA:
    files = _glob.glob(os.path.join(CACHE_5MIN, f"{ticker}_5min_*.parquet"))
    if not files:
        missing.append(ticker); continue
    frames = [pd.read_parquet(f) for f in files]
    df = pd.concat(frames)
    df.index = pd.DatetimeIndex(df.index)
    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df = df.between_time("09:30", "16:00")
    data_5min[ticker] = df
    print(f"  {ticker}: {len(df):,} bars")

if missing:
    print(f"  Missing (not fetched yet): {missing}")
if not data_5min:
    print("No low-beta data found. Run fetch_lowbeta_5min.py first."); sys.exit(1)

# Calm regime days
calm_days = set()
for w in results:
    for t in w.get("trades", []):
        if getattr(t, "hmm_state", "") == "Calm":
            calm_days.add(pd.to_datetime(t.entry_time).normalize())
calm_days = sorted(calm_days)
print(f"Calm regime days: {len(calm_days)}")

available_tickers = list(data_5min.keys())

ORB_START  = dtime(9, 35)
ORB_END    = dtime(10, 15)
SCAN_START = dtime(10, 20)   # first bar after ORB closes
SCAN_END   = dtime(14, 0)
EXIT_TIME  = dtime(14, 0)
MAX_SLOTS  = 3

def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

print("Precomputing day bars cache...")
day_bars_cache = {}
for ticker in available_tickers:
    if ticker not in data_5min: continue
    bars = data_5min[ticker].sort_index()
    for day in calm_days:
        db = bars[bars.index.normalize() == day]
        if len(db) >= 6:
            day_bars_cache[(ticker, day)] = db

print("Running simulation...")
trades = []

for day in calm_days:
    slots = 0

    for ticker in available_tickers:
        if slots >= MAX_SLOTS: break
        all_day = day_bars_cache.get((ticker, day))
        if all_day is None: continue

        # Compute OR range from 9:35–10:15
        or_bars = all_day[(all_day.index.time >= ORB_START) &
                          (all_day.index.time <= ORB_END)]
        if len(or_bars) < 3: continue
        or_high = float(or_bars["high"].max())
        or_low  = float(or_bars["low"].min())
        or_range = or_high - or_low
        if or_range <= 0: continue
        or_mid  = (or_high + or_low) / 2

        # ATR from OR bars
        atr = compute_atr(or_bars)
        if atr <= 0: continue

        # Scan bars from SCAN_START to SCAN_END
        scan_bars = all_day[(all_day.index.time >= SCAN_START) &
                            (all_day.index.time < SCAN_END)]
        if scan_bars.empty: continue

        trade = None
        for bar_ts, bar in scan_bars.iterrows():
            bar_h = float(bar["high"])
            bar_l = float(bar["low"])
            bar_c = float(bar["close"])

            # SHORT: price touches OR high from below (resistance)
            if bar_h >= or_high and bar_c < or_high:
                entry_px  = bar_c
                stop_px   = or_high + 0.5 * atr
                target_px = or_mid
                stop_dist = abs(stop_px - entry_px)
                if stop_dist <= 0 or target_px >= entry_px: continue
                reward    = abs(entry_px - target_px)
                if reward / stop_dist < 1.0: continue  # min R:R 1:1
                shares    = max(1, int(500 / stop_dist))
                direction = "SHORT"
                trade = dict(ticker=ticker, day=day, year=str(day.year),
                             bar_ts=bar_ts, direction=direction,
                             entry_px=entry_px, stop_px=stop_px,
                             target_px=target_px, shares=shares,
                             or_high=or_high, or_low=or_low)
                break

            # LONG: price touches OR low from above (support)
            if bar_l <= or_low and bar_c > or_low:
                entry_px  = bar_c
                stop_px   = or_low - 0.5 * atr
                target_px = or_mid
                stop_dist = abs(entry_px - stop_px)
                if stop_dist <= 0 or target_px <= entry_px: continue
                reward    = abs(target_px - entry_px)
                if reward / stop_dist < 1.0: continue
                shares    = max(1, int(500 / stop_dist))
                direction = "LONG"
                trade = dict(ticker=ticker, day=day, year=str(day.year),
                             bar_ts=bar_ts, direction=direction,
                             entry_px=entry_px, stop_px=stop_px,
                             target_px=target_px, shares=shares,
                             or_high=or_high, or_low=or_low)
                break

        if trade is None: continue

        # Simulate forward
        fwd = all_day[(all_day.index > trade["bar_ts"]) &
                      (all_day.index.time <= EXIT_TIME)]
        exit_px = trade["entry_px"]
        reason  = "TIME_STOP"

        for _, b in fwd.iterrows():
            bh = float(b["high"]); bl = float(b["low"]); bc = float(b["close"])
            if trade["direction"] == "SHORT":
                if bh >= trade["stop_px"]:
                    exit_px = trade["stop_px"]; reason = "STOP_HIT"; break
                if bl <= trade["target_px"]:
                    exit_px = trade["target_px"]; reason = "TARGET_HIT"; break
                exit_px = bc
            else:
                if bl <= trade["stop_px"]:
                    exit_px = trade["stop_px"]; reason = "STOP_HIT"; break
                if bh >= trade["target_px"]:
                    exit_px = trade["target_px"]; reason = "TARGET_HIT"; break
                exit_px = bc

        s = trade["shares"]
        if trade["direction"] == "SHORT":
            net_pnl = (trade["entry_px"] - exit_px) * s - s * 0.01 * 2
        else:
            net_pnl = (exit_px - trade["entry_px"]) * s - s * 0.01 * 2

        trade.update(exit_px=exit_px, reason=reason,
                     net_pnl=net_pnl, win=net_pnl > 0)
        trades.append(trade)
        slots += 1

# ── Results ──────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  ORB RETEST SIM — Calm regime 10:15–14:00")
print(f"{'='*60}")

if not trades:
    print("  No trades found.")
else:
    df = pd.DataFrame(trades)
    total = df["net_pnl"].sum()
    wr    = df["win"].mean() * 100
    avg   = df["net_pnl"].mean()
    print(f"\n  Total: {len(df)}t  P&L={total:+,.0f}  WR={wr:.0f}%  avg={avg:+.1f}/trade")

    for yr in ["2020","2021","2022"]:
        y = df[df["year"]==yr]
        if len(y):
            print(f"    {yr}: {len(y):3}t  P&L={y['net_pnl'].sum():+8,.0f}  WR={y['win'].mean()*100:.0f}%")

    by_reason = df.groupby("reason")["net_pnl"].agg(n="count", total="sum")
    print()
    for r, row in by_reason.iterrows():
        print(f"    {r:<14}: {int(row['n'])}t  {row['total']:+,.0f}")

    by_dir = df.groupby("direction")["net_pnl"].agg(n="count", total="sum",
                                                      wins=lambda x: (x>0).sum())
    print()
    for d, row in by_dir.iterrows():
        wr_d = row["wins"]/row["n"]*100
        print(f"    {d:<6}: {int(row['n'])}t  {row['total']:+,.0f}  WR={wr_d:.0f}%")

    # Bootstrap
    outcomes = df["net_pnl"].values
    rng = np.random.default_rng(42)
    boot = np.array([rng.choice(outcomes, size=len(outcomes), replace=True).sum()
                     for _ in range(10_000)])
    p = (boot <= 0).mean()
    ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
    print(f"\n  Bootstrap: p={p:.3f}  95%CI=[{ci_lo:+,.0f},{ci_hi:+,.0f}]  "
          f"{'✓ significant' if p < 0.05 else '✗ NOT significant'}")

    # Ticker breakdown
    tk_grp = df.groupby("ticker")["net_pnl"].agg(n="count", total="sum").sort_values("total", ascending=False)
    top3 = tk_grp["total"].head(3).sum()
    print(f"\n  Ticker concentration: top-3={top3:+,.0f} ({top3/total*100:.0f}% of total)")
    print(f"  {'Ticker':<8} {'N':>4} {'P&L':>9}")
    for tk, row in tk_grp.iterrows():
        print(f"  {tk:<8} {int(row['n']):>4} {row['total']:>+9,.0f}")
