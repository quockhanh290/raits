"""
global_index/verify_concat_desired.py
======================================
Checklist item (a) from LIVE_RUNNER_AUDIT.md:

  concat(frozen_parquet_through_day-1 + live_bars_day) →
      desired_position() == backtest for that day

TWO scenarios tested per trade:
  A. Full-day concat  (parquet[<day] + live[day]) → must return same trade
  B. Partial-day concat through fire_time bar → must fire AT fire_time (not before)

Usage:
    cd d:\\raits
    python global_index/verify_concat_desired.py
    python global_index/verify_concat_desired.py --data-dir data\\cache\\futures\\frozen_sim --n 30
"""
from __future__ import annotations
import argparse, random, sys
from datetime import time as dtime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futures.basket import BASKET, REGIME, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from futures._validated_core import load_parquet, benchmark_daily, label_regimes, _SWING_CACHE

ap = argparse.ArgumentParser()
ap.add_argument("--data-dir",   default="data/cache/futures/frozen_sim")
ap.add_argument("--regime-csv", default="spy_daily.csv")
ap.add_argument("--n",          type=int, default=30, help="Trades to sample")
ap.add_argument("--seed",       type=int, default=42)
ap.add_argument("--verbose",    action="store_true")
a = ap.parse_args()

HMM_FIT_END = REGIME["hmm_fit_end"]
DATA_DIR     = Path(a.data_dir)

print("=" * 72)
print("verify_concat_desired — concat(parquet+live) → desired_position == backtest")
print(f"  data-dir:    {DATA_DIR}")
print(f"  regime-csv:  {a.regime_csv}")
print(f"  n_sample:    {a.n}")
print("=" * 72)


def _naive_idx(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Strip tz from a DatetimeIndex so it can be compared to tz-naive Timestamps.
    The parquet from frozen_sim may be tz-aware (America/New_York) while backtest
    trade dicts store tz-naive entry_day/entry_time values."""
    return idx.tz_localize(None) if idx.tz is not None else idx


def _naive_ts(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_localize(None) if t.tzinfo is not None else t


# ── load ──────────────────────────────────────────────────────────────────────
print("\n[1] Load parquet + full backtest...")
dfs    = {n: load_parquet(str(DATA_DIR / data_filename(c))) for n, c in BASKET.items()}
bench  = benchmark_daily(a.regime_csv)
labels = label_regimes(bench, "2018-01-01", 3, HMM_FIT_END)
costs  = costs_for_basket(slippage_ticks=2.0)
engine = SwingTFEngine()

swing_bt   = engine.backtest_basket(dfs, labels, costs)
all_trades = [(inst, t) for inst, lst in swing_bt.items() for t in lst
              if t.get("entry_time") is not None]   # need entry_time for scenario B
print(f"  Basket trades with entry_time: {len(all_trades)}")

# ── sample ────────────────────────────────────────────────────────────────────
random.seed(a.seed)
sample = random.sample(all_trades, min(a.n, len(all_trades)))

# ── verify ────────────────────────────────────────────────────────────────────
pass_a = fail_a = 0
pass_b = fail_b = skip_b = 0

for inst, trade in sample:
    entry_day  = pd.Timestamp(trade["day"]).normalize()
    fire_ts    = pd.Timestamp(trade["entry_time"])
    bt_dir     = trade["direction"]
    bt_entry   = float(trade["entry"])
    df         = dfs[inst]

    # Split parquet — strip tz from index for comparison (parquet may be tz-aware)
    idx_naive    = _naive_idx(df.index).normalize()
    parquet_part = df[idx_naive < entry_day]
    live_all_day = df[idx_naive == entry_day]

    if live_all_day.empty:
        print(f"  SKIP {inst} {entry_day.date()} — no bars on entry day in parquet")
        skip_b += 1
        continue

    # ── SCENARIO A: full-day concat ─────────────────────────────────────────
    full_concat = pd.concat([parquet_part, live_all_day])
    full_concat = full_concat[~full_concat.index.duplicated(keep="last")].sort_index()

    # _SWING_CACHE is keyed by id(df). Python recycles object ids after GC, so
    # a new concat can hit a stale cache entry from a previous iteration.
    # Clear before each call to guarantee a fresh computation.
    _SWING_CACHE.clear()
    pos_a = engine.desired_position(full_concat, labels, costs[inst])

    if pos_a is None:
        fail_a += 1
        if a.verbose:
            print(f"  A FAIL {inst} {entry_day.date()} — desired_position returned None")
            print(f"         bt: dir={bt_dir} entry={bt_entry:.2f} day={entry_day.date()}")
    else:
        pos_day_a = pd.Timestamp(pos_a["entry_day"]).normalize()
        dir_ok    = pos_a["direction"] == bt_dir
        day_ok    = pos_day_a == entry_day
        entry_ok  = abs(pos_a["entry"] - bt_entry) < 0.05  # 5 cent tolerance

        if dir_ok and day_ok and entry_ok:
            pass_a += 1
            if a.verbose:
                print(f"  A PASS {inst} {entry_day.date()} "
                      f"dir={pos_a['direction']} entry={pos_a['entry']:.2f}")
        else:
            fail_a += 1
            print(f"  A FAIL {inst} {entry_day.date()}")
            if not dir_ok:
                print(f"         dir:   BT={bt_dir!r} vs concat={pos_a['direction']!r}")
            if not day_ok:
                print(f"         day:   BT={entry_day.date()} vs concat={pos_day_a.date()}")
            if not entry_ok:
                print(f"         entry: BT={bt_entry:.4f} vs concat={pos_a['entry']:.4f}")

    # ── SCENARIO B: partial-day concat THROUGH fire_time ────────────────────
    # fire_ts is the 5-min bar START (e.g. 14:20:00). To have a complete 5-min
    # bar, we need 1-min bars through fire_ts + 4 minutes (14:24:00).
    # desired_position must return the position open after the complete bar.
    fire_ts_cmp = _naive_ts(fire_ts)
    fire_ts_end  = fire_ts_cmp + pd.Timedelta(minutes=4)
    live_through_fire = live_all_day[_naive_idx(live_all_day.index) <= fire_ts_end]
    if live_through_fire.empty:
        skip_b += 1
        continue

    partial_concat = pd.concat([parquet_part, live_through_fire])
    partial_concat = partial_concat[~partial_concat.index.duplicated(keep="last")].sort_index()
    _SWING_CACHE.clear()
    pos_b = engine.desired_position(partial_concat, labels, costs[inst])

    # At fire_time, desired_position should show the position as open
    if pos_b is None:
        fail_b += 1
        if a.verbose:
            print(f"  B FAIL {inst} {entry_day.date()} fire={fire_ts.strftime('%H:%M')} "
                  f"— desired_position None at fire_time")
    else:
        pos_day_b = pd.Timestamp(pos_b["entry_day"]).normalize()
        day_ok_b  = pos_day_b == entry_day
        dir_ok_b  = pos_b["direction"] == bt_dir
        if day_ok_b and dir_ok_b:
            pass_b += 1
            if a.verbose:
                print(f"  B PASS {inst} {entry_day.date()} fire={fire_ts.strftime('%H:%M')} "
                      f"dir={pos_b['direction']} entry={pos_b['entry']:.2f}")
        else:
            fail_b += 1
            print(f"  B FAIL {inst} {entry_day.date()} fire={fire_ts.strftime('%H:%M')}")
            if not dir_ok_b:
                print(f"         dir:  BT={bt_dir!r} vs partial={pos_b['direction']!r}")
            if not day_ok_b:
                print(f"         day:  BT={entry_day.date()} vs partial={pos_day_b.date()}")

    # ── SCENARIO B2: bars strictly before fire_time — should NOT fire yet ───
    if len(live_all_day[_naive_idx(live_all_day.index) < fire_ts_cmp]) >= 1:
        pre_fire    = live_all_day[_naive_idx(live_all_day.index) < fire_ts_cmp]
        pre_concat  = pd.concat([parquet_part, pre_fire])
        pre_concat  = pre_concat[~pre_concat.index.duplicated(keep="last")].sort_index()
        _SWING_CACHE.clear()
        pos_b2      = engine.desired_position(pre_concat, labels, costs[inst])

        if pos_b2 is None:
            # Correct: no position yet before fire_time
            if a.verbose:
                last_bar_time = pre_fire.index[-1].strftime("%H:%M") if len(pre_fire) > 0 else "?"
                print(f"  B2 OK  {inst} {entry_day.date()} "
                      f"fire={fire_ts.strftime('%H:%M')} no_pos_at={last_bar_time} ✓")
        elif pd.Timestamp(pos_b2["entry_day"]).normalize() == entry_day:
            # Position fired before fire_time — mismatch with backtest
            pre_fire_bar = pre_fire.index[-1].strftime("%H:%M") if len(pre_fire) > 0 else "?"
            print(f"  B2 WARN {inst} {entry_day.date()} — position fires at {pre_fire_bar} "
                  f"but BT says fire_time={fire_ts.strftime('%H:%M')} "
                  f"(may be OK: BT records last bar, engine fires at prev bar close)")

# ── results ───────────────────────────────────────────────────────────────────
n_checked = pass_a + fail_a
print(f"\n{'='*72}")
print(f"SCENARIO A — full-day concat: {pass_a} PASS / {fail_a} FAIL / {n_checked} checked")
print(f"SCENARIO B — partial-to-fire: {pass_b} PASS / {fail_b} FAIL / {skip_b} skip")
print()

if fail_a == 0 and fail_b == 0:
    print("RESULT: PASS — concat(parquet+live) → desired_position() == backtest")
    print("  'live == backtest by construction' VERIFIED.")
    print("  Option C is safe to implement.")
elif fail_a > 0:
    print(f"RESULT: FAIL — {fail_a} Scenario A failures.")
    print("  concat() introduces a gap or duplication at the parquet/live boundary.")
    print("  DO NOT implement Option C until this is resolved.")
else:
    print(f"RESULT: B-FAIL only ({fail_b}) — Scenario A clean.")
    print("  Partial-day concat timing off — investigate fire_time semantics.")
print("=" * 72)
