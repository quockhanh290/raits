"""
stress_orb_stocks_sim.py — Individual stocks ORB SHORT trong Stress regime.

Hypothesis: In Stress days, high-beta individual stocks gap down harder và
follow-through tốt hơn ETFs (SPY/QQQ/IWM) vì beta cao hơn.

Replicates engine ORB logic:
  - Stress regime days only
  - Gap down ≥1.5% từ prev close
  - OR = 9:30–9:35 (5 min)
  - SHORT: bar breaks below OR low trong 9:35–10:15
  - Stop = OR high + 0.5×ATR (same as engine)
  - Target = 2R
  - SHORT only (mirror STRESS_ORB direction constraint)

Usage:
    cd D:\raits\raits
    python raits\scripts\stress_orb_stocks_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\window_debug_results.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

print("Loading data...")
with open(PKL_RESULTS, "rb") as f: results = pickle.load(f)
with open(PKL_5MIN,    "rb") as f: data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# Stress regime days
stress_days = set()
for w in results:
    for t in w.get("trades", []):
        if getattr(t, "hmm_state", "") == "Stress":
            stress_days.add(pd.to_datetime(t.entry_time).normalize())
stress_days = sorted(stress_days)
print(f"Stress regime days: {len(stress_days)}")

UNIVERSE = ["TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL"]
PHASE1   = ["INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
            "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX","CSCO","GS","CRM","JPM"]
PHASE2   = ["MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM"]
STOCK_UNIVERSE = [tk for tk in UNIVERSE+PHASE1+PHASE2 if tk in data_5min]

OR_END        = dtime(9, 35)
SIGNAL_START  = dtime(9, 35)
SIGNAL_END    = dtime(10, 15)
EXIT_TIME     = dtime(10, 15)
MIN_GAP_PCT   = 0.015
ATR_MULT_STOP = 0.5
TARGET_R      = 2.0
MAX_SLOTS     = 3

def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

# Precompute prev close + day bars
print("Precomputing caches...")
prev_close_map = {}
day_bars_cache = {}
for ticker in STOCK_UNIVERSE:
    bars = data_5min[ticker].sort_index()
    bars_d = bars.copy(); bars_d["date"] = bars_d.index.normalize()
    daily_last = bars_d.groupby("date")["close"].last()
    dates = daily_last.index.tolist()
    for i in range(1, len(dates)):
        prev_close_map[(ticker, dates[i])] = float(daily_last.iloc[i-1])
    for day in stress_days:
        db = bars[bars.index.normalize() == day]
        if len(db) >= 4:
            day_bars_cache[(ticker, day)] = db

print("Running simulation...")
trades = []

for day in stress_days:
    slots = 0
    entered = set()

    for ticker in STOCK_UNIVERSE:
        if slots >= MAX_SLOTS: break
        if ticker in entered: continue
        all_day = day_bars_cache.get((ticker, day))
        if all_day is None: continue
        prev_c = prev_close_map.get((ticker, day))
        if prev_c is None: continue

        # Gap check: must be gap DOWN ≥1.5%
        first_bar = all_day[all_day.index.time >= dtime(9, 30)]
        if first_bar.empty: continue
        session_open = float(first_bar.iloc[0]["open"])
        gap_pct = (session_open - prev_c) / prev_c
        if gap_pct >= -MIN_GAP_PCT: continue  # must gap DOWN

        # OR range (9:30–9:35)
        or_bars = all_day[all_day.index.time < OR_END]
        if len(or_bars) < 1: continue
        or_high = float(or_bars["high"].max())
        or_low  = float(or_bars["low"].min())
        or_range = or_high - or_low
        if or_range <= 0: continue

        atr = compute_atr(or_bars)
        # OR range validation: 0.5–5×ATR
        if atr > 0 and (or_range < 0.5 * atr or or_range > 5 * atr):
            continue

        # Signal bars: 9:35–10:15
        sig_bars = all_day[
            (all_day.index.time >= SIGNAL_START) &
            (all_day.index.time <= SIGNAL_END)
        ]
        if sig_bars.empty: continue

        trade = None
        for bar_ts, bar in sig_bars.iterrows():
            bar_c = float(bar["close"])
            bar_l = float(bar["low"])

            # SHORT: bar breaks below OR low
            if bar_l < or_low and bar_c < or_low:
                entry_px  = bar_c
                stop_px   = or_high + ATR_MULT_STOP * atr
                stop_dist = stop_px - entry_px
                if stop_dist <= 0: continue
                target_px = entry_px - TARGET_R * stop_dist
                shares    = max(1, int(500 / stop_dist))
                trade = dict(
                    ticker=ticker, day=day, year=str(day.year),
                    bar_ts=bar_ts, entry_px=entry_px,
                    stop_px=stop_px, target_px=target_px,
                    gap_pct=round(gap_pct*100, 2),
                    shares=shares,
                )
                break

        if trade is None: continue

        # Forward simulate
        fwd = all_day[
            (all_day.index > trade["bar_ts"]) &
            (all_day.index.time <= EXIT_TIME)
        ]
        exit_px = trade["entry_px"]
        reason  = "TIME_STOP"

        for _, b in fwd.iterrows():
            bh = float(b["high"]); bl = float(b["low"]); bc = float(b["close"])
            if bh >= trade["stop_px"]:
                exit_px = trade["stop_px"]; reason = "STOP_HIT"; break
            if bl <= trade["target_px"]:
                exit_px = trade["target_px"]; reason = "TARGET_HIT"; break
            exit_px = bc

        s = trade["shares"]
        net_pnl = (trade["entry_px"] - exit_px) * s - s * 0.01 * 2
        trade.update(exit_px=exit_px, reason=reason, net_pnl=net_pnl, win=net_pnl > 0)
        trades.append(trade)
        entered.add(ticker)
        slots += 1

# ── Results ───────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  STRESS ORB — INDIVIDUAL STOCKS SIM")
print(f"  SHORT only, gap↓≥1.5%, OR=9:30-9:35, signal=9:35-10:15")
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

by_r = df.groupby("reason")["net_pnl"].agg(n="count", total="sum")
print()
for r, row in by_r.iterrows():
    print(f"    {r:<14}: {int(row['n'])}t  {row['total']:+,.0f}")

tk_grp = df.groupby("ticker")["net_pnl"].agg(n="count", total="sum").sort_values("total", ascending=False)
top3 = tk_grp["total"].head(3).sum()
pct  = top3/total*100 if total != 0 else 0
print(f"\n  Ticker concentration: top-3={top3:+,.0f} ({pct:.0f}% of total)")
print(f"  {'Ticker':<8} {'N':>4} {'P&L':>9}")
for tk, row in tk_grp.iterrows():
    print(f"  {tk:<8} {int(row['n']):>4} {row['total']:>+9,.0f}")

# Bootstrap
outcomes = df["net_pnl"].values
rng  = np.random.default_rng(42)
boot = np.array([rng.choice(outcomes, size=len(outcomes), replace=True).sum()
                 for _ in range(10_000)])
p    = (boot <= 0).mean()
ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
print(f"\n  Bootstrap: p={p:.3f}  95%CI=[{ci_lo:+,.0f},{ci_hi:+,.0f}]  "
      f"{'✓ significant' if p < 0.05 else '✗ NOT significant'}")
