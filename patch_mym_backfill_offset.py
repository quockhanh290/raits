"""
patch_mym_backfill_offset.py — fix missing splice offset on Jul 22 MYM backfill
================================================================================
Root cause:
  backfill_gap_jul22.py thêm Jul 22 bars mà KHÔNG apply splice offset (-57).
  update_ibkr_daily.py luôn apply: new_bar + offset_stored = IBKR_raw + (-57).
  → Jul 22 MYM bars trong parquet ở mức IBKR_raw (cao hơn 57 pts so với surrounding).
  → Spike +57 inflate highest_high → chandelier LONG stop quá cao → LONG Jul23 bị stop-out ngay.
  → Backtest thấy SHORT Jul27, trong khi thực tế là LONG Jul23 (không có trade hôm nay).

Fix: subtract 57 từ tất cả OHLC của các bars bị backfill (window quanh Jul 22 gap).

Usage:
    cd d:\\raits
    python patch_mym_backfill_offset.py          # dry-run (print only)
    python patch_mym_backfill_offset.py --apply  # actually patch parquet
"""
import argparse, json, sys
from pathlib import Path

import pandas as pd

PARQUET  = Path("data/cache/futures/YM_continuous_1m_8y.parquet")
OFFSETS  = Path("global_index/data/_ibkr_splice_offsets.json")

# Patch window: bars added by backfill_gap_jul22.py.
# Gap was Jul 22 08:56 UTC → Jul 23 18:00 UTC = Jul 22 04:56 ET → Jul 23 14:00 ET.
# update_ibkr_daily uses ContFuture ("3 D"), adds bars after parquet's last bar.
# To be safe: patch entire Jul 22 trading day and the early Jul 23 session.
PATCH_START = pd.Timestamp("2026-07-22 00:00:00")  # start of Jul 22 ET session
PATCH_END   = pd.Timestamp("2026-07-23 18:00:00")  # 18:00 ET = end of gap boundary

CONTEXT_DAYS = 2  # how many days before/after to show for verification


def load_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Resample to daily OHLC for visual verification."""
    return df.resample("1D").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Actually patch the parquet (default: dry-run only)")
    a = ap.parse_args()

    if not PARQUET.exists():
        sys.exit(f"Parquet not found: {PARQUET}")

    with open(OFFSETS) as f:
        offsets = json.load(f)
    mym_offset = offsets.get("MYM", 0.0)
    print(f"MYM splice offset (from {OFFSETS}): {mym_offset:+.2f}")
    print(f"Patch window: {PATCH_START} → {PATCH_END}")
    print()

    df = pd.read_parquet(PARQUET)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("America/New_York").tz_localize(None)

    print(f"Parquet: {len(df):,} bars  {df.index[0]} → {df.index[-1]}")

    # ── Verify: show daily close around the patch window ─────────────────────
    show_start = PATCH_START - pd.Timedelta(days=CONTEXT_DAYS)
    show_end   = PATCH_END   + pd.Timedelta(days=CONTEXT_DAYS)
    window_df  = df[(df.index >= show_start) & (df.index <= show_end)]
    daily      = load_daily(window_df)

    print()
    print("Daily OHLC around Jul 22 gap (BEFORE patch):")
    print(f"  {'Date':<12} {'Open':>8} {'High':>8} {'Low':>8} {'Close':>8}  {'Note'}")
    print(f"  {'-'*65}")
    for dt, row in daily.iterrows():
        date_str = str(dt.date())
        note = ""
        if PATCH_START.date() <= dt.date() <= PATCH_END.date():
            note = "<── patch window"
        print(f"  {date_str:<12} {row['open']:>8.1f} {row['high']:>8.1f}"
              f" {row['low']:>8.1f} {row['close']:>8.1f}  {note}")

    # ── Find the spike: 1-min close diff at patch window boundary ─────────────
    pre  = df[df.index < PATCH_START]["close"]
    post = df[(df.index >= PATCH_START) & (df.index <= PATCH_END)]["close"]
    after = df[df.index > PATCH_END]["close"]

    if pre.empty or post.empty:
        print("\nNot enough data to diagnose boundary.")
    else:
        step_in  = float(post.iloc[0])  - float(pre.iloc[-1])
        step_out = float(after.iloc[0]) - float(post.iloc[-1]) if not after.empty else None
        print(f"\nBoundary check (close jumps):")
        print(f"  pre_last  = {pre.iloc[-1]:.2f}  at {pre.index[-1]}")
        print(f"  patch_first = {post.iloc[0]:.2f} at {post.index[0]}  jump = {step_in:+.2f} pts")
        if step_out is not None:
            print(f"  patch_last  = {post.iloc[-1]:.2f} at {post.index[-1]}")
            print(f"  after_first = {after.iloc[0]:.2f} at {after.index[0]}  jump = {step_out:+.2f} pts")

        expected_spike = -mym_offset  # should be +57 (bars are 57 too high)
        print(f"\n  Expected spike (= -offset = -{mym_offset:+.2f} = {expected_spike:+.2f}): ", end="")
        if abs(step_in - expected_spike) < 5:
            print("✓ CONFIRMED — spike matches expected value")
        elif abs(step_in) < 5:
            print("⚠ No spike detected — may already be patched or wrong window")
        else:
            print(f"? Unexpected spike = {step_in:+.2f}  (expected ≈ {expected_spike:+.2f})")

    # ── Apply patch ────────────────────────────────────────────────────────────
    mask = (df.index >= PATCH_START) & (df.index <= PATCH_END)
    n_bars = mask.sum()
    print(f"\nBars in patch window: {n_bars}")

    if not a.apply:
        print()
        print("DRY RUN — no changes made.")
        print("Run with --apply to actually patch the parquet.")
        return

    print(f"\nApplying offset {mym_offset:+.2f} to {n_bars} bars...")
    backup = PARQUET.with_suffix(".pre_patch_backup.parquet")
    df.to_parquet(backup)
    print(f"Backup saved: {backup.name}")

    for col in ["open", "high", "low", "close"]:
        if col in df.columns:
            df.loc[mask, col] = df.loc[mask, col] + mym_offset

    df.to_parquet(PARQUET)
    print(f"Patched parquet saved: {PARQUET.name}")

    # ── Verify after patch ─────────────────────────────────────────────────────
    daily_after = load_daily(df[(df.index >= show_start) & (df.index <= show_end)])
    print()
    print("Daily OHLC AFTER patch:")
    print(f"  {'Date':<12} {'Open':>8} {'High':>8} {'Low':>8} {'Close':>8}")
    print(f"  {'-'*55}")
    for dt, row in daily_after.iterrows():
        date_str = str(dt.date())
        note = " <── patched" if PATCH_START.date() <= dt.date() <= PATCH_END.date() else ""
        print(f"  {date_str:<12} {row['open']:>8.1f} {row['high']:>8.1f}"
              f" {row['low']:>8.1f} {row['close']:>8.1f}{note}")

    print()
    print("Done. Run check_mym_signal.py để verify signal sau khi patch.")


if __name__ == "__main__":
    main()
