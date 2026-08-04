"""
check_resumebar_timing.py — Distribution of TF resume_bar timestamps in historical backtest.

Shows WHEN within 14:00–15:55 ET each TF entry fires.
Key question: can the 14:05 ET runner capture any same-day entries?

Answer from architecture:
  • Runner fetches live IBKR bars at 14:05 ET → bars through ~14:04 ET
  • resample_5m gives only 1 bar in 14:00-15:55 window (the 14:00-14:05 bar)
  • Earliest resume_bar = 14:05 bar (completes at 14:10 ET) → runner MISSES all same-day entries
  • Captured only via rollover path (force_entries, bypasses entry_day guard)

Run: python check_resumebar_timing.py
"""
import pandas as pd, numpy as np, sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, '.')
from futures._validated_core import backtest_swing_tf, label_regimes, benchmark_daily
from futures.basket import BASKET, SWING_TF_PARAM, REGIME, data_filename
from futures.cost import FuturesCost

print("Loading regime labels...")
bench = benchmark_daily('spy_daily_live.csv')
labels = label_regimes(bench, '2018-01-01', REGIME["n_components"], REGIME["hmm_fit_end"])

all_entry_times = []
all_trades = []

for name, c in BASKET.items():
    fpath = Path(f'data/cache/futures/{data_filename(c)}')
    if not fpath.exists():
        print(f"  SKIP {name} — file not found: {fpath}")
        continue
    print(f"  Running backtest: {name} ...", end='', flush=True)
    df = pd.read_parquet(fpath)
    cost = FuturesCost(point_value=c.point_value, tick=c.tick, slippage_ticks_per_side=1.0)
    trades = backtest_swing_tf(
        df, labels, cost,
        ema_period=SWING_TF_PARAM["ema_period"],
        chandelier_atr_mult=SWING_TF_PARAM["chandelier_atr_mult"],
        max_hold_days=SWING_TF_PARAM["max_hold_days"],
        gap_fill=True,
    )
    n_with_time = sum(1 for t in trades if t.get("entry_time") is not None)
    print(f" {len(trades)} trades ({n_with_time} with entry_time)")
    all_trades.extend([(name, t) for t in trades])
    all_entry_times.extend([
        (name, pd.Timestamp(t["entry_time"]))
        for t in trades if t.get("entry_time") is not None
    ])

print(f"\nTotal trades (all instruments): {len(all_trades)}")
print(f"Trades with entry_time: {len(all_entry_times)}")

if not all_entry_times:
    print("No entry_time data — backtest_swing_tf may not return entry_time. Check _validated_core.py line 357.")
    sys.exit(0)

# Distribution by HH:MM (strip date, keep time)
times_hhmm = [ts.strftime('%H:%M') for _, ts in all_entry_times]
counter = Counter(times_hhmm)
total = len(times_hhmm)

print("\nResume bar time distribution (14:00–15:55 ET window, all instruments pooled):")
print(f"{'Time':>8}  {'Count':>6}  {'Pct':>6}  {'Cumul%':>7}")
cumulative = 0
for t in sorted(counter.keys()):
    n = counter[t]
    cumulative += n
    marker = " <-- earliest if runner ≥ 14:10" if t == "14:05" else ""
    print(f"  {t}:  {n:5d}  {n/total*100:5.1f}%  {cumulative/total*100:6.1f}%{marker}")

print()
# Captures: resume_bar = 14:05 completes at 14:10; runner at 14:05 cannot see it
# To capture 14:05 bar, runner must fire at 14:10+
captured_by_14_05 = sum(v for k, v in counter.items() if k < "14:05")  # impossible window
captured_by_14_10 = sum(v for k, v in counter.items() if k <= "14:05")  # runner ≥ 14:10
captured_by_14_15 = sum(v for k, v in counter.items() if k <= "14:10")
captured_by_14_30 = sum(v for k, v in counter.items() if k <= "14:25")
captured_by_15_00 = sum(v for k, v in counter.items() if k <= "14:55")

print("Capture rate if live runner fires at:")
print(f"  14:05 ET (current P0c schedule):  {captured_by_14_05}/{total} = {captured_by_14_05/total*100:.1f}%  [ZERO — can only see 14:00 bar]")
print(f"  14:10 ET (+5 min startup lag):     {captured_by_14_10}/{total} = {captured_by_14_10/total*100:.1f}%")
print(f"  14:15 ET (+10 min startup lag):    {captured_by_14_15}/{total} = {captured_by_14_15/total*100:.1f}%")
print(f"  14:30 ET:                          {captured_by_14_30}/{total} = {captured_by_14_30/total*100:.1f}%")
print(f"  15:00 ET:                          {captured_by_15_00}/{total} = {captured_by_15_00/total*100:.1f}%")

# Slippage risk for force_entries path (same-direction rollover)
# entry_time = resume bar on day D, runner fires 14:05 day D+1
# Price gap = overnight gap from entry bar to D+1 14:05
# Check what % of entries are in the last 30 min of session (high momentum trades at end of day)
late_entries = sum(v for k, v in counter.items() if k >= "15:25")
print(f"\nLate entries (≥15:25 ET, ≤30min before close): {late_entries}/{total} = {late_entries/total*100:.1f}%")
print("  These are highest overnight gap risk for rollover path.")

print("\nConclusion:")
print("  P0c runs once at 14:05 → ZERO same-day TF entries possible.")
print("  TF entries only captured via rollover (force_entries path) or from prior-day held positions.")
print("  Slippage on rollover = overnight gap: fill at 14:05 D+1 vs backtest entry at resume_bar close on D.")
print("  C1 slip logger (runner.py line 1069) tracks this automatically per live fill.")
