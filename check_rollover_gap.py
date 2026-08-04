"""
check_rollover_gap.py — Overnight gap slippage for TF rollover path.

For each historical TF trade:
  entry_price = resume_bar close on day D (backtest)
  d1_price    = 1-min bar close nearest to 14:05 ET on day D+1 (live fill proxy)
  gap         = direction-adjusted (D+1 price - entry) → positive = ADVERSE

This quantifies slippage on the force_entries (same-direction rollover) path,
where signal_layer bypasses the entry_day guard and fires market order at D+1 14:05.

Run from d:\\raits:
  python check_rollover_gap.py
"""
import pandas as pd, numpy as np, sys
from pathlib import Path

sys.path.insert(0, '.')
from futures._validated_core import backtest_swing_tf, label_regimes, benchmark_daily
from futures.basket import BASKET, SWING_TF_PARAM, REGIME, data_filename
from futures.cost import FuturesCost

# ── 1. Regime labels ──────────────────────────────────────────────────────────
print("Loading regime labels...")
bench = benchmark_daily('spy_daily_live.csv')
labels = label_regimes(bench, '2018-01-01', REGIME["n_components"], REGIME["hmm_fit_end"])

# ── 2. Per-instrument: backtest → trades with entry_time + parquet for D+1 lookup ──
results = {}

for name, c in BASKET.items():
    fpath = Path(f'data/cache/futures/{data_filename(c)}')
    if not fpath.exists():
        print(f"  SKIP {name} — {fpath} not found")
        continue
    print(f"  {name} ...", end='', flush=True)

    df = pd.read_parquet(fpath)
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("America/New_York").tz_localize(None)
    df = df.sort_index()

    cost = FuturesCost(point_value=c.point_value, tick=c.tick, slippage_ticks_per_side=1.0)
    trades = backtest_swing_tf(
        df, labels, cost,
        ema_period=SWING_TF_PARAM["ema_period"],
        chandelier_atr_mult=SWING_TF_PARAM["chandelier_atr_mult"],
        max_hold_days=SWING_TF_PARAM["max_hold_days"],
        gap_fill=True,
    )

    # Vectorized D+1 14:05 lookup — O(log N) per trade via searchsorted
    close_s = df["close"]          # Series, ET-naive index, already sorted
    idx_arr  = close_s.index       # DatetimeIndex

    gaps_pts = []
    gaps_usd = []
    entry_times = []
    directions = []

    debug_n = 0
    for t in trades:
        et = t.get("entry_time")
        if et is None:
            continue
        entry_ts  = pd.Timestamp(et)
        entry_px  = float(t["entry"])
        direction = t["direction"]

        # Target = D+1 at 14:05 ET; try D+1 through D+7 to skip weekends/holidays
        found = False
        for delta in range(1, 8):
            target = entry_ts.normalize() + pd.Timedelta(days=delta, hours=14, minutes=5)
            pos = idx_arr.searchsorted(target)
            # check bar at pos and pos-1; pick closer
            candidates_idx = [p for p in [pos - 1, pos] if 0 <= p < len(idx_arr)]
            if not candidates_idx:
                continue
            best = min(candidates_idx, key=lambda p: abs((idx_arr[p] - target).total_seconds()))
            gap_secs = abs((idx_arr[best] - target).total_seconds())
            if gap_secs > 30 * 60:
                continue  # no bar within 30 min of 14:05 on this day — try next
            d1_px = float(close_s.iloc[best])
            d1_ts = idx_arr[best]
            found = True
            break

        if not found:
            continue

        if debug_n < 3:
            print(f"    [DBG] {entry_ts}  px={entry_px:.2f}  dir={direction}")
            print(f"          D+{delta} target={target}  found={d1_ts}  px={d1_px:.2f}  gap={gap_secs:.0f}s")
            debug_n += 1

        # Signed gap: adverse = positive
        if direction == "LONG":
            gap_pts = d1_px - entry_px   # higher price = adverse for buyer
        else:
            gap_pts = entry_px - d1_px   # lower price = adverse for seller

        gap_usd = gap_pts * c.point_value
        gaps_pts.append(gap_pts)
        gaps_usd.append(gap_usd)
        entry_times.append(entry_ts.strftime('%H:%M'))
        directions.append(direction)

    results[name] = dict(
        gaps_pts=gaps_pts, gaps_usd=gaps_usd,
        entry_times=entry_times, directions=directions,
        tick=c.tick, point_value=c.point_value,
    )
    print(f" {len(gaps_pts)} trades analysed")

# ── 3. Print results ──────────────────────────────────────────────────────────
print()
print("=" * 70)
print("OVERNIGHT GAP SLIPPAGE — D+1 14:05 fill vs backtest entry price")
print("Positive gap = ADVERSE (buy higher / sell lower than backtest)")
print("=" * 70)

all_pts, all_usd = [], []

for name, r in results.items():
    g = np.array(r["gaps_pts"])
    u = np.array(r["gaps_usd"])
    pv = r["point_value"]
    tk = r["tick"]
    n  = len(g)
    if n == 0:
        continue
    all_pts.extend(g.tolist())
    all_usd.extend(u.tolist())

    adverse     = g[g > 0]
    favorable   = g[g < 0]
    two_tick_pts = 2 * tk

    print(f"\n{name}  (point_value=${pv:.0f}, tick={tk})")
    print(f"  N trades analysed : {n}")
    print(f"  Mean gap (pts)    : {g.mean():+.2f}  (${g.mean()*pv:+.2f})")
    print(f"  Median gap (pts)  : {np.median(g):+.2f}  (${np.median(g)*pv:+.2f})")
    print(f"  Std dev (pts)     : {g.std():.2f}  (${g.std()*pv:.2f})")
    print(f"  2-tick assumption : {two_tick_pts:.4f} pts = ${two_tick_pts*pv:.2f}")
    print(f"  Adverse trades    : {len(adverse)}/{n} = {len(adverse)/n*100:.1f}%")
    print(f"  Favorable trades  : {len(favorable)}/{n} = {len(favorable)/n*100:.1f}%")
    print(f"  Gap > 2 ticks     : {(g > two_tick_pts).sum()}/{n} = {(g > two_tick_pts).sum()/n*100:.1f}%")
    print(f"  Gap > 5 pts adv   : {(g > 5).sum()}/{n} = {(g > 5).sum()/n*100:.1f}%")
    print(f"  Gap > 10 pts adv  : {(g > 10).sum()}/{n} = {(g > 10).sum()/n*100:.1f}%")
    print(f"  Gap > 20 pts adv  : {(g > 20).sum()}/{n} = {(g > 20).sum()/n*100:.1f}%")
    pct5, pct25, pct75, pct95 = np.percentile(g, [5, 25, 75, 95])
    print(f"  Percentiles (pts) : p5={pct5:+.1f}  p25={pct25:+.1f}  p75={pct75:+.1f}  p95={pct95:+.1f}")

# ── 4. Pooled summary ─────────────────────────────────────────────────────────
if all_usd:
    ua = np.array(all_usd)
    print()
    print("=" * 70)
    print("POOLED (all instruments, in USD)")
    print(f"  N total           : {len(ua)}")
    print(f"  Mean gap USD      : {ua.mean():+.2f}")
    print(f"  Median gap USD    : {np.median(ua):+.2f}")
    print(f"  Std dev USD       : {ua.std():.2f}")
    print(f"  Adverse (>0)      : {(ua > 0).sum()}/{len(ua)} = {(ua > 0).sum()/len(ua)*100:.1f}%")
    print(f"  |gap| > $50       : {(np.abs(ua) > 50).sum()}/{len(ua)} = {(np.abs(ua) > 50).sum()/len(ua)*100:.1f}%")
    print(f"  |gap| > $100      : {(np.abs(ua) > 100).sum()}/{len(ua)} = {(np.abs(ua) > 100).sum()/len(ua)*100:.1f}%")
    print(f"  |gap| > $250      : {(np.abs(ua) > 250).sum()}/{len(ua)} = {(np.abs(ua) > 250).sum()/len(ua)*100:.1f}%")
    pct5, pct25, pct75, pct95 = np.percentile(ua, [5, 25, 75, 95])
    print(f"  Percentiles USD   : p5={pct5:+.0f}  p25={pct25:+.0f}  p75={pct75:+.0f}  p95={pct95:+.0f}")

    print()
    print("Context:")
    print("  2-tick per-side assumption (backtest cost model): MES=$2.50, MNQ=$2.00, MYM=$0.50, M2K=$1.00")
    print("  Rollover path = force_entries, bypasses entry_day guard.")
    print("  Fresh entry path = suppressed by guard → missed trade, $0 slippage but 0 P&L.")
    print("  Run C1 slip logger (runner.py:1069) live to accumulate actual fill stats.")
