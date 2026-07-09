"""
fetch_oos_remaining.py
-----------------------
Fetch the remaining 2023-2024 5-min data that fetch_oos_data.py missed.

Problem: fetch_oos_data.py used client.get_aggs() with a full-year range.
The Polygon REST client returns ~5,000 bars per page (≈ 64 trading days),
so only Q1 2023 and Q1 2024 were fetched.

Fix: fetch month-by-month using raw requests.get (same pattern as
raits_polygon_fetcher.py), which is proven to return all bars per day.

Strategy:
  1. For each ticker, find the max date in existing 2023/2024 parquets
  2. Fetch missing months (from max_date+1 through Dec 2024)
  3. Save each month as a separate parquet file (not in existing files)
  4. Rebuild window_debug_5min.pkl to include all new data

Usage:
    cd d:\\raits\\raits
    python raits/scripts/fetch_oos_remaining.py
"""
import sys, os, time, pickle
sys.path.insert(0, r'd:\raits\raits')
sys.path.insert(0, r'd:\raits')

import requests
import pandas as pd
from datetime import date, timedelta
from zoneinfo import ZoneInfo

try:
    from config_private import POLYGON_API_KEY
except ImportError:
    print("ERROR: config_private.py not found or POLYGON_API_KEY missing")
    sys.exit(1)

EASTERN       = ZoneInfo("America/New_York")
CACHE_5MIN    = r'd:\raits\raits\data\cache\data'
PKL_5MIN      = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
BASE_URL      = "https://api.polygon.io"
SLEEP_BETWEEN = 0.15   # seconds between API calls

# ── Load existing pkl to get ticker universe ───────────────────────────────────
print("Loading existing pkl to determine ticker universe...")
with open(PKL_5MIN, "rb") as f:
    existing_pkl = pickle.load(f)
ALL_TICKERS = sorted(existing_pkl.keys())
print(f"  Universe: {len(ALL_TICKERS)} tickers")


# ── Determine what's missing per ticker (use pkl, not parquets) ───────────────
# pkl already has more data than parquets (accumulated from earlier runs + Q1 fetch)
# Check pkl max date per ticker so we don't re-fetch what we already have.
OOS_START = date(2023, 1, 3)
OOS_END   = date(2024, 12, 31)
FULL_THRESHOLD = date(2024, 12, 20)   # allow a few days slack for holidays

print("\nAuditing 2023-2024 coverage in pkl per ticker...")
fetch_plan = {}   # ticker -> (start_date, end_date)
pkl_max_dates = {}

for ticker in ALL_TICKERS:
    df = existing_pkl.get(ticker, pd.DataFrame())
    if df.empty:
        pkl_max_dates[ticker] = None
        fetch_plan[ticker] = (OOS_START, OOS_END)
        continue
    idx = pd.DatetimeIndex(df.index)
    oos_bars = idx[(idx.year >= 2023)]
    if len(oos_bars) == 0:
        pkl_max_dates[ticker] = None
        fetch_plan[ticker] = (OOS_START, OOS_END)
    else:
        mx = oos_bars.max().date()
        pkl_max_dates[ticker] = mx
        if mx < FULL_THRESHOLD:
            fetch_plan[ticker] = (mx + timedelta(days=1), OOS_END)
        # else: fully covered — skip

covered = [t for t in ALL_TICKERS if t not in fetch_plan]
partial  = [t for t in ALL_TICKERS if t in fetch_plan and pkl_max_dates[t] is not None]
missing  = [t for t in ALL_TICKERS if t in fetch_plan and pkl_max_dates[t] is None]

print(f"  Fully covered: {len(covered)} tickers (pkl max >= 2024-12-20)")
print(f"  Partial:       {len(partial)} tickers (will fetch remainder)")
print(f"  Missing:       {len(missing)} tickers (no 2023+ data in pkl)")

if not fetch_plan:
    print("\nAll tickers already have complete 2023-2024 data. Nothing to do.")
    sys.exit(0)

# Show a sample
for t in sorted(partial)[:5]:
    mx = pkl_max_dates[t]
    s, e = fetch_plan[t]
    print(f"  {t}: pkl_max={mx}, will fetch {s} -> {e}")
print(f"  ... ({len(fetch_plan)} total to fetch)")


# ── Business day list ─────────────────────────────────────────────────────────
def bday_range(start: date, end: date) -> list[date]:
    """Return list of Mon-Fri dates between start and end inclusive."""
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:   # Mon=0 ... Fri=4
            out.append(d)
        d += timedelta(days=1)
    return out


# ── Fetch one day of 5-min bars ───────────────────────────────────────────────
def fetch_day(ticker: str, day: date) -> pd.DataFrame | None:
    """Fetch 5-min bars for one trading day. Returns None on failure."""
    day_str = day.strftime("%Y-%m-%d")
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/5/minute/{day_str}/{day_str}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": POLYGON_API_KEY}

    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") not in ("OK", "DELAYED"):
                return None
            results = data.get("results", [])
            if not results:
                return None   # market holiday or non-trading day
            rows = []
            for r in results:
                ts = pd.Timestamp(r["t"], unit="ms", tz="UTC").tz_convert("US/Eastern").tz_localize(None)
                if pd.Timestamp("09:30").time() <= ts.time() <= pd.Timestamp("16:00").time():
                    rows.append({"timestamp": ts, "open": r["o"], "high": r["h"],
                                 "low": r["l"], "close": r["c"], "volume": r["v"]})
            if not rows:
                return None
            df = pd.DataFrame(rows).set_index("timestamp")
            return df
        except Exception:
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    return None


# ── Main fetch loop ────────────────────────────────────────────────────────────
print(f"\nFetching remaining data for {len(fetch_plan)} tickers...")
print("(sleeping 0.15s between calls to respect rate limit)")

new_frames = {}   # {ticker: [DataFrame, ...]}
total_calls = 0
total_ok = 0
total_fail = 0

for ticker_idx, (ticker, (start_d, end_d)) in enumerate(sorted(fetch_plan.items())):
    days = bday_range(start_d, end_d)
    ticker_frames = []
    ticker_ok = 0

    for day in days:
        time.sleep(SLEEP_BETWEEN)
        df = fetch_day(ticker, day)
        total_calls += 1
        if df is not None:
            ticker_frames.append(df)
            ticker_ok += 1
            total_ok += 1
        else:
            total_fail += 1

    if ticker_frames:
        combined = pd.concat(ticker_frames).sort_index()
        combined = combined[~combined.index.duplicated(keep="first")]
        new_frames[ticker] = combined
        max_d = combined.index.max()
        # Save as monthly chunks to avoid giant single parquet
        for month_start in pd.date_range(start_d.strftime("%Y-%m-01"), end_d.strftime("%Y-%m-01"), freq="MS"):
            month_end = month_start + pd.offsets.MonthEnd(0)
            chunk = combined[(combined.index >= month_start) & (combined.index <= month_end)]
            if chunk.empty:
                continue
            fname = f"{ticker}_5min_{month_start.date()}_{month_end.date()}.parquet"
            fpath = os.path.join(CACHE_5MIN, fname)
            chunk.to_parquet(fpath)

        progress = f"[{ticker_idx+1}/{len(fetch_plan)}]"
        print(f"  {progress} {ticker}: {ticker_ok}/{len(days)} days → max={max_d.date()}")
    else:
        print(f"  [{ticker_idx+1}/{len(fetch_plan)}] {ticker}: 0 days fetched")

print(f"\nFetch done: {total_ok} OK, {total_fail} failures out of {total_calls} calls")


# ── Rebuild pkl ───────────────────────────────────────────────────────────────
if not new_frames:
    print("No new data fetched. pkl unchanged.")
    sys.exit(0)

print(f"\nRebuilding window_debug_5min.pkl with {len(new_frames)} updated tickers...")
updated = dict(existing_pkl)

for ticker, new_df in new_frames.items():
    old_df = updated.get(ticker, pd.DataFrame())
    if not old_df.empty:
        merged = pd.concat([old_df, new_df]).sort_index()
        merged = merged[~merged.index.duplicated(keep="first")]
    else:
        merged = new_df
    updated[ticker] = merged
    yr23 = len(merged[merged.index.year == 2023])
    yr24 = len(merged[merged.index.year == 2024])
    max_date = merged.index.max()
    print(f"  {ticker}: 2023={yr23:,} bars  2024={yr24:,} bars  max={max_date.date()}")

with open(PKL_5MIN, "wb") as f:
    pickle.dump(updated, f, protocol=4)
print(f"\nSaved: {PKL_5MIN}")
print("Done. Re-run diagnose_oos_2023_2024.py")
