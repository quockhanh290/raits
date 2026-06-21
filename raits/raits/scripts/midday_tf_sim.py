"""
Retroactive simulation: TF signal logic applied to 12:00-14:00 window
trên Normal regime days.

Dùng cùng signal logic như TF (EMA pullback + volume pattern),
chỉ thay đổi time window.

Usage:
    cd d:\raits\raits
    python raits/scripts/midday_tf_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_scenario_g.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

with open(PKL_RESULTS, "rb") as f:
    results = pickle.load(f)
with open(PKL_5MIN, "rb") as f:
    data_5min = pickle.load(f)

for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

rows = []
for w in results:
    yr = w.get("label", "?")
    for t in w.get("trades", []):
        d = vars(t).copy()
        d["year"] = yr
        rows.append(d)
df = pd.DataFrame(rows)
df["entry_time"] = pd.to_datetime(df["entry_time"])

# Identify Normal regime days from TF trades
tf_normal = df[(df["strategy"] == "TREND_FOLLOW") & (df["hmm_state"] == "Normal")].copy()
tf_normal["date"] = tf_normal["entry_time"].dt.normalize()
normal_days = sorted(tf_normal["date"].unique())

# TF benchmark per trade
tf_avg_pnl   = tf_normal["net_pnl"].mean()
tf_med_pnl   = tf_normal["net_pnl"].median()
tf_wr        = (tf_normal["net_pnl"] > 0).mean()

EMA_PERIOD       = 30          # locked WFO param
EMA_PROX_PCT     = 0.005       # 0.5% proximity
VOL_SURGE_MULT   = 1.3
MIDDAY_START     = dtime(12, 0)
MIDDAY_END       = dtime(14, 0)
CHANDELIER_MULT  = 3.0

def compute_atr(bars, period=14):
    if len(bars) < 2:
        return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    return float(tr.tail(period).mean())

def simulate_midday_tf(ticker, day):
    """Scan 12:00-14:00 for TF signals on given ticker and day."""
    if ticker not in data_5min:
        return []

    bars = data_5min[ticker]
    day_bars = bars[bars.index.normalize() == day].sort_index()
    if len(day_bars) < EMA_PERIOD + 2:
        return []

    # Only bars in midday window
    midday = day_bars[
        (day_bars.index.time >= MIDDAY_START) &
        (day_bars.index.time < MIDDAY_END)
    ]
    if len(midday) < 2:
        return []

    signals = []
    for i in range(1, len(midday)):
        pullback_bar = midday.iloc[i - 1]
        resume_bar   = midday.iloc[i]
        bar_ts       = midday.index[i]

        # Bars available up to pullback_bar (for EMA and HOD/LOD)
        bars_so_far = day_bars[day_bars.index <= pullback_bar.name]
        if len(bars_so_far) < EMA_PERIOD:
            continue

        # EMA
        ema = float(bars_so_far["close"].ewm(span=EMA_PERIOD, adjust=False).mean().iloc[-1])
        atr = compute_atr(bars_so_far)
        if atr <= 0:
            continue

        # HOD/LOD (from session open to pullback bar)
        hod = float(bars_so_far["high"].max())
        lod = float(bars_so_far["low"].min())
        price = float(pullback_bar["close"])

        # Filter 1: near HOD or LOD (TF scanner logic)
        near_hod = (hod - price) / hod < 0.03 or (hod - price) < 2.0 * atr
        near_lod = (price - lod) / lod < 0.03 or (price - lod) < 2.0 * atr
        if not (near_hod or near_lod):
            continue

        # Filter 2: EMA proximity
        ema_dist = abs(price - ema) / ema
        if ema_dist > EMA_PROX_PCT:
            continue

        # Direction
        direction = "LONG" if price >= ema else "SHORT"

        # Filter 3: Volume pattern
        avg_vol_10 = float(bars_so_far["volume"].tail(10).mean())
        if avg_vol_10 <= 0:
            continue
        pullback_low_vol = pullback_bar["volume"] < avg_vol_10
        resume_high_vol  = resume_bar["volume"] > avg_vol_10 * VOL_SURGE_MULT
        if not (pullback_low_vol and resume_high_vol):
            continue

        # Entry at resume bar close
        entry_px = float(resume_bar["close"])

        # Chandelier initial stop
        stop_dist = CHANDELIER_MULT * atr
        initial_stop = (entry_px - stop_dist) if direction == "LONG" else (entry_px + stop_dist)

        # Simulate trade outcome: walk bars from resume_bar to MIDDAY_END
        remaining = day_bars[day_bars.index > resume_bar.name]
        remaining = remaining[remaining.index.time < MIDDAY_END]

        pnl = None
        exit_reason = "TIME_STOP"
        exit_px = entry_px

        if direction == "LONG":
            running_stop = initial_stop
            for _, b in remaining.iterrows():
                running_high = day_bars[
                    (day_bars.index >= resume_bar.name) &
                    (day_bars.index <= b.name)
                ]["high"].max()
                running_stop = max(running_stop, running_high - stop_dist)
                if b["low"] <= running_stop:
                    exit_px = running_stop
                    exit_reason = "STOP_HIT"
                    break
                exit_px = float(b["close"])
            pnl = (exit_px - entry_px)
        else:  # SHORT
            running_stop = initial_stop
            for _, b in remaining.iterrows():
                running_low = day_bars[
                    (day_bars.index >= resume_bar.name) &
                    (day_bars.index <= b.name)
                ]["low"].min()
                running_stop = min(running_stop, running_low + stop_dist)
                if b["high"] >= running_stop:
                    exit_px = running_stop
                    exit_reason = "STOP_HIT"
                    break
                exit_px = float(b["close"])
            pnl = (entry_px - exit_px)

        # Rough shares (1% risk of $50k = $500 risk / stop_dist)
        shares = max(1, int(500 / stop_dist)) if stop_dist > 0 else 1
        gross_pnl = pnl * shares
        costs     = shares * 0.01 * 2   # $0.01/share round trip
        net_pnl   = gross_pnl - costs

        signals.append({
            "ticker":      ticker,
            "date":        day,
            "year":        str(day.year),
            "bar_ts":      bar_ts,
            "direction":   direction,
            "entry_px":    entry_px,
            "exit_px":     exit_px,
            "exit_reason": exit_reason,
            "atr":         atr,
            "shares":      shares,
            "gross_pnl":   gross_pnl,
            "net_pnl":     net_pnl,
            "win":         net_pnl > 0,
        })
        break  # one trade per ticker per day (same as TF)

    return signals

# Build ticker universe from TF trades (same stocks TF uses)
tf_tickers = df[df["strategy"] == "TREND_FOLLOW"]["ticker"].value_counts().head(30).index.tolist()

print(f"Running midday TF sim on {len(normal_days)} Normal days × {len(tf_tickers)} tickers...")

all_signals = []
for day in normal_days:
    for ticker in tf_tickers:
        sigs = simulate_midday_tf(ticker, day)
        all_signals.extend(sigs)

sim = pd.DataFrame(all_signals)

def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

print(f"\n{'='*72}")
print(f"  MIDDAY TF SIM (12:00-14:00, Normal days)  —  {len(sim)} signals")
print(f"{'='*72}")

if len(sim) == 0:
    print("  No signals generated.")
else:
    div("1. Overall performance")
    print(f"  Signals        : {len(sim)}")
    print(f"  Total P&L      : ${sim['net_pnl'].sum():>+,.0f}")
    print(f"  Win rate       : {sim['win'].mean()*100:.1f}%")
    print(f"  Avg P&L/trade  : ${sim['net_pnl'].mean():>+.1f}")
    print(f"  Signals/day    : {len(sim)/len(normal_days):.2f}")

    div("2. By year")
    for yr in ["2020", "2021", "2022"]:
        s = sim[sim["year"] == yr]
        if len(s):
            print(f"  {yr}: {len(s):>4}t  ${s['net_pnl'].sum():>+8,.0f}  "
                  f"WR={s['win'].mean()*100:.0f}%  avg=${s['net_pnl'].mean():>+.1f}")

    div("3. Exit reason")
    for r in sim["exit_reason"].unique():
        s = sim[sim["exit_reason"] == r]
        print(f"  {r:<15} {len(s):>4}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")

    div("4. Direction split")
    for d in ["LONG", "SHORT"]:
        s = sim[sim["direction"] == d]
        if len(s):
            print(f"  {d}: {len(s):>4}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")

    div("5. Top tickers")
    tk = sim.groupby("ticker")["net_pnl"].agg(n="count", total="sum")
    print(tk.sort_values("total", ascending=False).head(10).to_string())

    div("6. Comparison vs current TF (14:00-15:55)")
    print(f"\n  Current TF (Normal):  {len(tf_normal):>4}t  "
          f"${tf_normal['net_pnl'].sum():>+8,.0f}  "
          f"WR={tf_wr*100:.0f}%  avg=${tf_avg_pnl:>+.1f}")
    print(f"  Midday TF sim:        {len(sim):>4}t  "
          f"${sim['net_pnl'].sum():>+8,.0f}  "
          f"WR={sim['win'].mean()*100:.0f}%  avg=${sim['net_pnl'].mean():>+.1f}")
    print(f"\n  System estimate if added:")
    current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)
    print(f"  Current system : ${current_sys:>+,.0f}")
    print(f"  + Midday TF    : ${current_sys + sim['net_pnl'].sum():>+,.0f}")
    print(f"  Delta          : ${sim['net_pnl'].sum():>+,.0f} "
          f"(${sim['net_pnl'].sum()/3:>+,.0f}/yr)")
