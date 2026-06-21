"""
vwap_mr_lowbeta_sim.py — VWAP MR với low-beta universe + fixed (snapshot) VWAP target.

Signal (giữ nguyên từ vwap_mr.py):
  - SHORT: prev_bar.high >= bb_upper AND prev_bar.close < bb_upper
  - LONG:  prev_bar.low  <= bb_lower AND prev_bar.close > bb_lower
  BB params: period=20, std=2.0

Target thay đổi (key hypothesis):
  - Thay vì VWAP moving → snapshot VWAP tại thời điểm signal (fixed target)
  - Stop = entry ± 1.5×ATR (giữ nguyên)
  - Min R:R = 1.5 (giữ nguyên)

Universe: low-beta (PG, KO, PEP, NEE, JNJ, ...) vs high-beta hiện tại
Window: Calm regime, 10:15–14:00 ET

Usage:
    cd D:\raits\raits
    python raits\scripts\vwap_mr_lowbeta_sim.py
"""
import sys, os, pickle, glob as _glob
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\window_debug_results.pkl'
CACHE_5MIN  = r'd:\raits\raits\data\cache\data'

LOW_BETA = [
    "PG","KO","PEP","WMT","MO","CL","KMB","GIS","MDLZ",
    "NEE","DUK","SO","D","AEP",
    "JNJ","ABT","MRK","PFE","BMY",
    "WFC","USB",   # BRK.B excluded (illiquid 5-min)
]

BB_PERIOD  = 20
BB_STD     = 2.0
ATR_PERIOD = 14
STOP_ATR   = 1.5
MIN_RR     = 1.5
MAX_SLOTS  = 3
ENTRY_START = dtime(10, 20)   # bar T open ≥ 10:20 (signal at T-1 ≥ 10:15)
EXIT_TIME   = dtime(14, 0)

# ── Load data ─────────────────────────────────────────────────────────
print("Loading results pkl...")
with open(PKL_RESULTS, "rb") as f: results = pickle.load(f)

print("Loading low-beta 5-min parquets...")
data_5min = {}
for ticker in LOW_BETA:
    files = _glob.glob(os.path.join(CACHE_5MIN, f"{ticker}_5min_*.parquet"))
    if not files:
        print(f"  {ticker}: MISSING — run fetch_lowbeta_5min.py first"); continue
    frames = [pd.read_parquet(f) for f in files]
    df = pd.concat(frames)
    df.index = pd.DatetimeIndex(df.index)
    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df = df.between_time("09:30", "16:00")
    data_5min[ticker] = df

if not data_5min:
    print("No data. Exiting."); sys.exit(1)
print(f"Loaded {len(data_5min)} tickers")

# ── Calm regime days ──────────────────────────────────────────────────
calm_days = set()
for w in results:
    for t in w.get("trades", []):
        if getattr(t, "hmm_state", "") == "Calm":
            calm_days.add(pd.to_datetime(t.entry_time).normalize())
calm_days = sorted(calm_days)
print(f"Calm regime days: {len(calm_days)}")

# ── Precompute per-day bars ───────────────────────────────────────────
print("Precomputing day bars cache...")
day_bars_cache = {}
for ticker in data_5min:
    bars = data_5min[ticker]
    for day in calm_days:
        db = bars[bars.index.normalize() == day]
        if len(db) >= BB_PERIOD + 2:
            day_bars_cache[(ticker, day)] = db.copy()

# ── Helpers ───────────────────────────────────────────────────────────
def compute_indicators(bars):
    """Compute rolling VWAP, BB, ATR on 5-min bars for one day."""
    df = bars.copy()
    # VWAP (cumulative from day start)
    df["tp"]      = (df["high"] + df["low"] + df["close"]) / 3
    df["tpv"]     = df["tp"] * df["volume"]
    df["cum_tpv"] = df["tpv"].cumsum()
    df["cum_vol"] = df["volume"].cumsum()
    df["vwap"]    = df["cum_tpv"] / df["cum_vol"].replace(0, np.nan)
    # Bollinger Bands on close
    df["bb_mid"]   = df["close"].rolling(BB_PERIOD).mean()
    df["bb_std"]   = df["close"].rolling(BB_PERIOD).std()
    df["bb_upper"] = df["bb_mid"] + BB_STD * df["bb_std"]
    df["bb_lower"] = df["bb_mid"] - BB_STD * df["bb_std"]
    # ATR
    hl  = df["high"] - df["low"]
    hpc = (df["high"] - df["close"].shift(1)).abs()
    lpc = (df["low"]  - df["close"].shift(1)).abs()
    df["atr"] = pd.concat([hl, hpc, lpc], axis=1).max(axis=1).rolling(ATR_PERIOD).mean()
    return df

# ── Simulation ────────────────────────────────────────────────────────
print("Running simulation...")
trades = []

for day in calm_days:
    slots = 0
    entered = set()

    for ticker in data_5min:
        if slots >= MAX_SLOTS:
            break
        if ticker in entered:
            continue
        all_day = day_bars_cache.get((ticker, day))
        if all_day is None:
            continue

        df = compute_indicators(all_day)

        # Scan bars from ENTRY_START to EXIT_TIME
        scan = df[(df.index.time >= ENTRY_START) & (df.index.time < EXIT_TIME)]
        if len(scan) < 2:
            continue

        for i in range(1, len(scan)):
            cur_bar  = scan.iloc[i]
            prev_bar = scan.iloc[i - 1]

            bb_upper = prev_bar["bb_upper"]
            bb_lower = prev_bar["bb_lower"]
            if pd.isna(bb_upper) or pd.isna(bb_lower):
                continue

            atr = prev_bar["atr"]
            if pd.isna(atr) or atr <= 0:
                continue

            vwap_snap = prev_bar["vwap"]   # snapshot VWAP at signal time
            if pd.isna(vwap_snap):
                continue

            # SHORT signal
            direction = None
            if prev_bar["high"] >= bb_upper and prev_bar["close"] < bb_upper:
                direction = "SHORT"
            elif prev_bar["low"] <= bb_lower and prev_bar["close"] > bb_lower:
                direction = "LONG"

            if direction is None:
                continue

            entry_px  = float(cur_bar["open"])
            stop_dist = STOP_ATR * atr

            if direction == "SHORT":
                stop_px   = entry_px + stop_dist
                target_px = vwap_snap  # below entry
                if target_px >= entry_px:
                    continue  # VWAP above entry — no short edge
                reward = entry_px - target_px
            else:
                stop_px   = entry_px - stop_dist
                target_px = vwap_snap  # above entry
                if target_px <= entry_px:
                    continue  # VWAP below entry — no long edge
                reward = target_px - entry_px

            if stop_dist <= 0 or reward / stop_dist < MIN_RR:
                continue

            shares = max(1, int(500 / stop_dist))

            # Forward simulate from cur_bar+1 to EXIT_TIME
            fwd = df[(df.index > scan.index[i]) & (df.index.time <= EXIT_TIME)]
            exit_px = entry_px
            reason  = "TIME_STOP"

            for _, b in fwd.iterrows():
                bh = float(b["high"]); bl = float(b["low"]); bc = float(b["close"])
                if direction == "SHORT":
                    if bh >= stop_px:   exit_px = stop_px;   reason = "STOP_HIT";   break
                    if bl <= target_px: exit_px = target_px; reason = "TARGET_HIT"; break
                    exit_px = bc
                else:
                    if bl <= stop_px:   exit_px = stop_px;   reason = "STOP_HIT";   break
                    if bh >= target_px: exit_px = target_px; reason = "TARGET_HIT"; break
                    exit_px = bc

            if direction == "SHORT":
                net_pnl = (entry_px - exit_px) * shares - shares * 0.01 * 2
            else:
                net_pnl = (exit_px - entry_px) * shares - shares * 0.01 * 2

            trades.append(dict(
                ticker=ticker, day=day, year=str(day.year),
                bar_ts=scan.index[i], direction=direction,
                entry_px=entry_px, stop_px=stop_px, target_px=target_px,
                vwap_snap=vwap_snap, atr=atr, stop_dist=stop_dist,
                rr=round(reward/stop_dist, 2), shares=shares,
                exit_px=exit_px, reason=reason,
                net_pnl=net_pnl, win=net_pnl > 0,
            ))
            entered.add(ticker)
            slots += 1
            break  # one trade per ticker per day

# ── Results ───────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  VWAP_MR LOW-BETA SIM — Calm 10:15–14:00")
print(f"  Signal: BB touch+revert | Target: snapshot VWAP (fixed)")
print(f"{'='*60}")

if not trades:
    print("  No trades found."); sys.exit(0)

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

by_dir = df.groupby("direction")["net_pnl"].agg(n="count",total="sum",wins=lambda x:(x>0).sum())
print()
for d, row in by_dir.iterrows():
    print(f"    {d:<6}: {int(row['n'])}t  {row['total']:+,.0f}  WR={row['wins']/row['n']*100:.0f}%")

# Ticker breakdown
tk_grp = df.groupby("ticker")["net_pnl"].agg(n="count",total="sum").sort_values("total",ascending=False)
top3 = tk_grp["total"].head(3).sum()
pct  = top3/total*100 if total != 0 else 0
print(f"\n  Ticker concentration: top-3={top3:+,.0f} ({pct:.0f}% of total)")
print(f"  {'Ticker':<8} {'N':>4} {'P&L':>9}")
for tk, row in tk_grp.iterrows():
    print(f"  {tk:<8} {int(row['n']):>4} {row['total']:>+9,.0f}")

# Bootstrap
outcomes = df["net_pnl"].values
rng  = np.random.default_rng(42)
boot = np.array([rng.choice(outcomes,size=len(outcomes),replace=True).sum() for _ in range(10_000)])
p    = (boot <= 0).mean()
ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
print(f"\n  Bootstrap: p={p:.3f}  95%CI=[{ci_lo:+,.0f},{ci_hi:+,.0f}]  "
      f"{'✓ significant' if p < 0.05 else '✗ NOT significant'}")
