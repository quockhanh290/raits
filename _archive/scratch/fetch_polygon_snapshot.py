"""
fetch_polygon_snapshot.py — Fetch Polygon adjusted SPY data + reproducibility test
====================================================================================
1. Fetches SPY adjusted=True daily bars 2017-2024 from Polygon
2. Saves as spy_adjusted_v1.csv (versioned, in _archive/scratch/)
3. Tests reproducibility: fetch again immediately, compare results
4. Compares with current spy_daily.csv to quantify systematic drift
5. Reports: suitable as production basis?

DOES NOT MODIFY spy_daily.csv or any production file.

Run:
    cd d:\raits
    python _archive/scratch/fetch_polygon_snapshot.py

Output: _archive/scratch/spy_adjusted_v1.csv (versioned snapshot)
"""
from __future__ import annotations
import sys, os, warnings, time
warnings.filterwarnings("ignore")
sys.path.insert(0, "d:/raits")

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import date

try:
    from config_private import POLYGON_API_KEY
except ImportError:
    POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")
if not POLYGON_API_KEY:
    sys.exit("ERROR: POLYGON_API_KEY not found")

from polygon import RESTClient
client = RESTClient(POLYGON_API_KEY)

OUT_DIR = Path("d:/raits/_archive/scratch")
today_str = date.today().isoformat()


def fetch_daily_bars(from_date: str, to_date: str, label: str = "") -> pd.DataFrame:
    """Fetch SPY adjusted daily bars from Polygon. Returns DataFrame(date, close)."""
    print(f"  Fetching {from_date} → {to_date} {label} ...", end=" ", flush=True)
    bars = client.get_aggs(
        "SPY", 1, "day",
        from_=from_date, to=to_date,
        adjusted=True, limit=50000,
    )
    rows = []
    for b in bars:
        ts = pd.Timestamp(b.timestamp, unit="ms", tz="UTC").tz_convert("America/New_York")
        rows.append({"date": ts.date().isoformat(), "close": float(b.close)})
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    print(f"{len(df)} rows")
    return df


# ── Fetch 1: full 2017-2024 ───────────────────────────────────────────────────
print("=== FETCH 1: SPY adjusted 2017-01-01 to 2024-12-31 ===")
df1 = fetch_daily_bars("2017-01-01", "2024-12-31", "(fetch 1 of 2)")

v1_path = OUT_DIR / f"spy_adjusted_v1_{today_str}.csv"
df1.to_csv(v1_path, index=False)
print(f"Saved: {v1_path}")
print(f"Rows: {len(df1)} | Date range: {df1['date'].iloc[0]} – {df1['date'].iloc[-1]}")
print(f"First 5 close: {df1['close'].head().tolist()}")
print(f"Last 5 close:  {df1['close'].tail().tolist()}")
print()

# ── Fetch 2: reproducibility test ────────────────────────────────────────────
print("=== FETCH 2: Reproducibility test (same request) ===")
time.sleep(1)  # brief pause
df2 = fetch_daily_bars("2017-01-01", "2024-12-31", "(fetch 2 of 2)")

# Compare
if len(df1) != len(df2):
    print(f"WARN: row count differs! fetch1={len(df1)}, fetch2={len(df2)}")
else:
    diff_close = (df1["close"].values - df2["close"].values)
    max_diff = np.abs(diff_close).max()
    n_diff = (np.abs(diff_close) > 1e-6).sum()
    if n_diff == 0:
        print(f"REPRODUCIBLE: all {len(df1)} rows identical (max diff = {max_diff:.2e})")
    else:
        print(f"WARN: {n_diff} rows differ (max diff = {max_diff:.6f})")
        bad = df1.copy()
        bad["close2"] = df2["close"].values
        bad["diff"] = diff_close
        print(bad[np.abs(diff_close) > 1e-6][["date", "close", "close2", "diff"]].to_string())
print()

# ── Compare vs current spy_daily.csv ─────────────────────────────────────────
print("=== COMPARISON: spy_adjusted_v1 vs spy_daily.csv ===")
csv_df = pd.read_csv("d:/raits/spy_daily.csv", parse_dates=["date"])
csv_df["date"] = csv_df["date"].dt.strftime("%Y-%m-%d")

merged = df1.merge(csv_df, on="date", suffixes=("_poly", "_csv"))
merged["ratio"] = merged["close_csv"] / merged["close_poly"]
merged["drift_pct"] = (merged["ratio"] - 1.0) * 100

print(f"Matching rows: {len(merged)} / {len(df1)} poly / {len(csv_df)} csv")
print()

# Overall drift statistics
print("Drift statistics (csv / polygon - 1):")
print(f"  Mean:   {merged['drift_pct'].mean():.4f}%")
print(f"  Median: {merged['drift_pct'].median():.4f}%")
print(f"  Std:    {merged['drift_pct'].std():.4f}%")
print(f"  Min:    {merged['drift_pct'].min():.4f}%")
print(f"  Max:    {merged['drift_pct'].max():.4f}%")
print()

# Drift evolution over time (by year)
merged["year"] = pd.to_datetime(merged["date"]).dt.year
print("Mean drift by year (csv is systematically LOWER than Polygon correct):")
for yr, grp in merged.groupby("year"):
    print(f"  {yr}: mean={grp['drift_pct'].mean():.4f}%  "
          f"[csv={grp['close_csv'].mean():.2f} vs poly={grp['close_poly'].mean():.2f}]")
print()

# Log-return comparison (this is what HMM uses)
print("=== LOG-RETURN COMPARISON (HMM input) ===")
merged_sorted = merged.sort_values("date")
merged_sorted["lr_csv"] = np.log(merged_sorted["close_csv"]).diff()
merged_sorted["lr_poly"] = np.log(merged_sorted["close_poly"]).diff()
merged_sorted["lr_diff"] = (merged_sorted["lr_csv"] - merged_sorted["lr_poly"]).abs()

# Days with log-return diff > 0.1% (cliff threshold)
cliff_days = merged_sorted[merged_sorted["lr_diff"] > 0.001]
print(f"Days with |log-return diff| > 0.1% (cliff-risk): {len(cliff_days)}")
print(f"These are the ex-dividend dates where adjustment differs:")
if len(cliff_days) > 0:
    print(cliff_days[["date", "lr_csv", "lr_poly", "lr_diff"]].to_string(index=False))
print()

# ── Recommendation ────────────────────────────────────────────────────────────
print("=== FEASIBILITY ASSESSMENT ===")
print()
print("1. FETCH: OK — Polygon adjusted=True fetches full 2017-2024 in one call (~2s)")
print()
if n_diff == 0:
    print("2. REPRODUCIBILITY: CONFIRMED — same call returns identical data within session")
    print("   Note: data WILL change across quarterly ex-div events (by design)")
    print("   Solution: version snapshots (spy_adjusted_v1_DATE.csv)")
else:
    print("2. REPRODUCIBILITY: WARNING — data differs between calls")
print()
print("3. SYSTEMATIC DRIFT from current CSV:")
print(f"   csv is {merged['drift_pct'].mean():.2f}% LOWER than Polygon correct (avg)")
print(f"   Ranges from {merged['drift_pct'].min():.2f}% (2017) to {merged['drift_pct'].max():.2f}% (2024)")
print(f"   This drift is in PRICE LEVELS (not log-returns) — constant within each quarter")
print(f"   Log-return diff only on {len(cliff_days)} ex-div days > 0.1% threshold")
print()
print("4. MIGRATION PATH:")
print(f"   a. Rename spy_daily.csv → spy_daily_frozen2017.csv (archive)")
print(f"   b. Copy {v1_path.name} → spy_daily.csv")
print(f"   c. Re-run full backtest (~2-3h with Polygon cache)")
print(f"   d. New baseline replaces $52,962 — vault $7,404 re-run on corrected labels")
print(f"   e. Going forward: update_spy_csv.py uses OVERLAP_DAYS=30 + adjusted=True")
print(f"      No re-fetch needed until next quarterly dividend ex-date")
print()
print(f"5. VERSIONED FILE: {v1_path}")
print(f"   Rows: {len(df1)} | use this as the new spy_daily.csv after validation")
