"""
diagnose_mym_boundary.py — find actual price discontinuities in MYM parquet
============================================================================
Gap description: "Jul 22 08:56 UTC → Jul 23 18:00 UTC"
  = Jul 22 04:56 ET → Jul 23 14:00 ET

backfill_gap_jul22.py added bars WITHOUT splice offset (-57).
Expected: +57 spike at ~04:56 ET Jul 22, -57 step at ~14:00 ET Jul 23.

This script:
1. Looks at 1-min bars around Jul 22 04:56 ET and Jul 23 14:00 ET
2. Finds large close jumps in a wider window (Jul 21 - Jul 25)
3. Checks if Jul 23 TF window bars have a step-change at 14:00 ET
"""
import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
from pathlib import Path

PARQUET = Path("data/cache/futures/YM_continuous_1m_8y.parquet")
OFFSET  = -57.0

def main():
    df = pd.read_parquet(PARQUET)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("America/New_York").tz_localize(None)
    df = df.sort_index()

    # ── 1. Show 1-min bars around Jul 22 04:56 ET (expected +57 spike) ───────
    print("=" * 72)
    print("A. 1-min bars around Jul 22 04:40-05:10 ET (expected +57 spike at 04:56)")
    window_a = df.loc["2026-07-22 04:40":"2026-07-22 05:10", "close"]
    if window_a.empty:
        print("  NO BARS in this window — gap confirmed here")
    else:
        diffs = window_a.diff()
        for ts, cl in window_a.items():
            d = diffs[ts]
            flag = f"  ← JUMP {d:+.1f}" if abs(d) > 10 and not np.isnan(d) else ""
            print(f"  {ts}  close={cl:.2f}  diff={d:+.2f}{flag}")

    # ── 2. Show 1-min bars around Jul 23 14:00 ET (expected -57 step) ─────────
    print()
    print("B. 1-min bars around Jul 23 13:50-14:10 ET (expected -57 step at 14:00)")
    window_b = df.loc["2026-07-23 13:50":"2026-07-23 14:10", "close"]
    if window_b.empty:
        print("  NO BARS in this window")
    else:
        diffs = window_b.diff()
        for ts, cl in window_b.items():
            d = diffs[ts]
            flag = f"  ← JUMP {d:+.1f}" if abs(d) > 10 and not np.isnan(d) else ""
            print(f"  {ts}  close={cl:.2f}  diff={d:+.2f}{flag}")

    # ── 3. Scan ALL large jumps in Jul 21-25 ───────────────────────────────────
    print()
    print("C. All 1-min close jumps > 20 pts in Jul 21-25:")
    scan = df.loc["2026-07-21":"2026-07-25", "close"]
    diffs = scan.diff().abs()
    big = diffs[diffs > 20]
    if big.empty:
        print("  No jumps > 20 pts found")
    else:
        for ts in big.index:
            prev = scan.iloc[scan.index.get_loc(ts) - 1]
            curr = scan[ts]
            print(f"  {ts}  {prev:.2f} → {curr:.2f}  jump={curr-prev:+.2f}")

    # ── 4. Jul 23 TF window: show 5-min resampled bars 13:30-15:00 ET ────────
    print()
    print("D. Jul 23 5-min close 13:30-15:10 ET (TF window starts 14:00):")
    day23 = df.loc["2026-07-23 13:30":"2026-07-23 15:10"]
    if day23.empty:
        print("  NO BARS")
    else:
        bars5 = day23["close"].resample("5min").last().dropna()
        diffs5 = bars5.diff()
        for ts, cl in bars5.items():
            d = diffs5[ts]
            flag = f"  ← JUMP {d:+.1f}" if abs(d) > 10 and not np.isnan(d) else ""
            print(f"  {ts}  close={cl:.2f}  diff={d:+.2f}{flag}")

    # ── 5. Quick EMA sanity: EMA30 on 5-min bars at Jul 23 14:05 ET ──────────
    print()
    print("E. EMA30 on 5-min bars at Jul 23 14:05 ET (parquet actual vs corrected):")
    # Full Jul 23 session: Jul 22 18:00 ET to Jul 23 18:00 ET
    sess23 = df.loc["2026-07-22 18:00":"2026-07-23 18:00", "close"]
    if len(sess23) < 35:
        print("  Not enough bars")
    else:
        bars5_sess = sess23.resample("5min").last().dropna()
        up_to_1405 = bars5_sess[bars5_sess.index <= pd.Timestamp("2026-07-23 14:05")]
        if len(up_to_1405) < 31:
            print("  Not enough 5-min bars before 14:05")
        else:
            ema_actual  = up_to_1405.ewm(span=30, adjust=False).mean().iloc[-1]
            close_14x   = up_to_1405.iloc[-1]
            # Corrected: apply +57 to bars BEFORE 14:00 ET (the backfilled ones)
            corrected = up_to_1405.copy()
            mask = corrected.index < pd.Timestamp("2026-07-23 14:00")
            corrected[mask] = corrected[mask] - 57.0   # undo the +57 overshoot
            ema_corrected = corrected.ewm(span=30, adjust=False).mean().iloc[-1]
            close_corrected = close_14x  # 14:05 bar same (it's update_ibkr_daily, correct)
            print(f"  5-min bar at 14:05 ET: close = {close_14x:.2f}")
            print(f"  EMA30 (parquet, buggy): {ema_actual:.2f}"
                  f"  → close - EMA = {close_14x - ema_actual:+.2f}")
            print(f"  EMA30 (corrected):     {ema_corrected:.2f}"
                  f"  → close - EMA = {close_corrected - ema_corrected:+.2f}")
            direction_actual    = "LONG" if close_14x > ema_actual    else "SHORT"
            direction_corrected = "LONG" if close_corrected > ema_corrected else "SHORT"
            print(f"  Direction (actual):   {direction_actual}")
            print(f"  Direction (corrected):{direction_corrected}")

if __name__ == "__main__":
    main()
