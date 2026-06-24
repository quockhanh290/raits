"""
fetch_oos_data.py — Fetch all data needed for OOS 2023-2024 backtest.

Checks and fetches:
  1. 5-min OHLCV parquets for 2023-2024 (all 75 tickers in window_debug universe)
  2. Earnings calendar 2023-2024 (62 PE_SHORT tickers, Polygon financials)
  3. Rebuilds window_debug_5min.pkl if new parquets were added

VIX and daily data already cover 2024 — no fetch needed.

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\fetch_oos_data.py
"""
import sys, os, json, time, pickle, glob
sys.path.insert(0, r'd:\raits\raits')
sys.path.insert(0, r'd:\raits')

import pandas as pd
import numpy as np
from datetime import datetime
from polygon import RESTClient
from config_private import POLYGON_API_KEY

client = RESTClient(api_key=POLYGON_API_KEY)

# ── Paths ─────────────────────────────────────────────────────────────────────
CACHE_5MIN_DIR  = r'd:\raits\raits\data\cache\data'
PKL_5MIN        = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
EARNINGS_PATH   = r'd:\raits\raits\data\cache\earnings_dates_expanded.json'

# 5-min OOS windows to fetch
OOS_WINDOWS = [
    ("2023-01-03", "2023-12-29", "2023"),
    ("2024-01-02", "2024-12-31", "2024"),
]

# ── Tickers ───────────────────────────────────────────────────────────────────
# Load from existing pkl — use exactly what window_debug has
print("Loading existing 5-min pkl to determine universe...")
with open(PKL_5MIN, "rb") as f:
    existing_pkl = pickle.load(f)
ALL_TICKERS_5MIN = sorted(existing_pkl.keys())
print(f"  Universe: {len(ALL_TICKERS_5MIN)} tickers")

# Earnings tickers (PE_SHORT universe from earnings JSON)
with open(EARNINGS_PATH) as f:
    existing_earnings = json.load(f)
EARNINGS_TICKERS = sorted(existing_earnings.keys())
print(f"  Earnings tickers: {len(EARNINGS_TICKERS)}")

# ── Step 1: Check 5-min coverage ──────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 1: Check 5-min data coverage for 2023-2024")
print("="*60)

missing = {}   # {(ticker, year_label): (start_str, end_str)}
for ticker in ALL_TICKERS_5MIN:
    bars = existing_pkl[ticker]
    bars.index = pd.DatetimeIndex(bars.index)
    for start_str, end_str, yr in OOS_WINDOWS:
        yr_bars = bars[bars.index.year == int(yr)]
        if len(yr_bars) < 100:   # less than 100 bars = missing/incomplete
            missing[(ticker, yr)] = (start_str, end_str)

if not missing:
    print(f"  All {len(ALL_TICKERS_5MIN)} tickers have 2023-2024 data in pkl. No 5-min fetch needed.")
    pkl_needs_rebuild = False
else:
    tickers_missing = sorted(set(tk for tk, _ in missing.keys()))
    years_missing   = sorted(set(yr for _, yr in missing.keys()))
    print(f"  Missing: {len(missing)} ticker-year combos")
    print(f"  Tickers: {tickers_missing[:10]}{'...' if len(tickers_missing)>10 else ''}")
    print(f"  Years:   {years_missing}")
    pkl_needs_rebuild = True

# ── Step 2: Fetch missing 5-min parquets ──────────────────────────────────────
def fetch_5min_year(ticker: str, start_str: str, end_str: str, yr: str) -> pd.DataFrame:
    """Fetch one year of 5-min bars from Polygon aggs endpoint."""
    aggs = client.get_aggs(
        ticker=ticker,
        multiplier=5,
        timespan="minute",
        from_=start_str,
        to=end_str,
        adjusted=True,
        sort="asc",
        limit=50000,
    )
    if not aggs:
        return pd.DataFrame()
    rows = []
    for bar in aggs:
        ts = pd.Timestamp(bar.timestamp, unit="ms", tz="UTC").tz_convert("US/Eastern").tz_localize(None)
        rows.append({
            "open":   bar.open,
            "high":   bar.high,
            "low":    bar.low,
            "close":  bar.close,
            "volume": bar.volume,
        })
    df = pd.DataFrame(rows)
    df.index = [pd.Timestamp(bar.timestamp, unit="ms", tz="UTC")
                .tz_convert("US/Eastern").tz_localize(None) for bar in aggs]
    df.index.name = "timestamp"
    # Keep only regular session bars (9:30-16:00 ET)
    df = df[(df.index.time >= pd.Timestamp("09:30").time()) &
            (df.index.time <= pd.Timestamp("16:00").time())]
    return df


if missing:
    print(f"\n  Fetching {len(missing)} ticker-year combinations from Polygon...")
    ok_count = fail_count = 0
    new_data: dict = {}   # {ticker: DataFrame (all new years combined)}

    for (ticker, yr), (start_str, end_str) in sorted(missing.items()):
        print(f"    {ticker:<6} {yr}  {start_str} → {end_str} ... ", end="", flush=True)
        try:
            df = fetch_5min_year(ticker, start_str, end_str, yr)
            if df.empty:
                print("EMPTY")
                fail_count += 1
                continue
            # Save as dated parquet
            fname = f"{ticker}_5min_{start_str}_{end_str}.parquet"
            fpath = os.path.join(CACHE_5MIN_DIR, fname)
            df.to_parquet(fpath)
            print(f"OK  {len(df)} bars → {fname}")
            new_data.setdefault(ticker, []).append(df)
            ok_count += 1
        except Exception as e:
            print(f"FAIL — {e}")
            fail_count += 1
        time.sleep(0.15)

    print(f"\n  5-min fetch: {ok_count} OK, {fail_count} failed")

    # ── Rebuild pkl if new parquets were added ────────────────────────────────
    if ok_count > 0:
        print("\n  Rebuilding window_debug_5min.pkl with new data...")
        updated_pkl = dict(existing_pkl)
        for ticker in new_data:
            old = updated_pkl.get(ticker, pd.DataFrame())
            new_frames = new_data[ticker]
            all_frames = ([old] if not old.empty else []) + new_frames
            merged = pd.concat(all_frames).sort_index()
            merged = merged[~merged.index.duplicated(keep="first")]
            updated_pkl[ticker] = merged
            yr23 = len(merged[merged.index.year == 2023])
            yr24 = len(merged[merged.index.year == 2024])
            print(f"    {ticker}: 2023={yr23} bars  2024={yr24} bars")
        with open(PKL_5MIN, "wb") as f:
            pickle.dump(updated_pkl, f, protocol=4)
        print(f"  Saved: {PKL_5MIN}")
else:
    updated_pkl = existing_pkl

# ── Step 3: Fetch earnings 2023-2024 ─────────────────────────────────────────
print("\n" + "="*60)
print("STEP 2: Fetch earnings dates 2023-2024 from Polygon")
print("="*60)

EARNINGS_FETCH_FROM = "2022-10-01"   # overlap Q4-2022 to catch any gaps
EARNINGS_FETCH_TO   = "2024-12-31"

print(f"  Fetching {len(EARNINGS_TICKERS)} tickers: {EARNINGS_FETCH_FROM} → {EARNINGS_FETCH_TO}\n")

updated_earnings = {tk: set(existing_earnings.get(tk, [])) for tk in EARNINGS_TICKERS}
earn_errors = []

for i, tk in enumerate(EARNINGS_TICKERS, 1):
    new_dates = []
    try:
        for r in client.vx.list_stock_financials(
            ticker=tk,
            timeframe="quarterly",
            filing_date_gte=EARNINGS_FETCH_FROM,
            filing_date_lte=EARNINGS_FETCH_TO,
            limit=20,
        ):
            new_dates.append(str(r.filing_date)[:10])
        updated_earnings[tk].update(new_dates)
        all_sorted = sorted(updated_earnings[tk])
        dates_2023_plus = [d for d in all_sorted if d >= "2023-01-01"]
        print(f"  [{i:2d}/{len(EARNINGS_TICKERS)}] {tk:6s}: "
              f"+{len(new_dates)} new  "
              f"2023+: {len(dates_2023_plus)} events  "
              f"total_range: {all_sorted[0]}..{all_sorted[-1]}")
    except Exception as e:
        earn_errors.append((tk, str(e)))
        print(f"  [{i:2d}/{len(EARNINGS_TICKERS)}] {tk:6s}: ERROR — {e}")
    time.sleep(0.12)

# Save updated earnings
output_earnings = {tk: sorted(updated_earnings[tk]) for tk in EARNINGS_TICKERS}
with open(EARNINGS_PATH, "w") as f:
    json.dump(output_earnings, f, indent=2)

total_2023 = sum(1 for tk in EARNINGS_TICKERS
                 for d in output_earnings[tk] if d >= "2023-01-01")
total_2024 = sum(1 for tk in EARNINGS_TICKERS
                 for d in output_earnings[tk] if d >= "2024-01-01")
print(f"\n  Earnings 2023+ events: {total_2023}")
print(f"  Earnings 2024+ events: {total_2024}")
print(f"  Saved: {EARNINGS_PATH}")

if earn_errors:
    print(f"\n  Errors ({len(earn_errors)}):")
    for tk, msg in earn_errors:
        print(f"    {tk}: {msg}")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("DONE — OOS data ready")
print("="*60)

# Final check on pkl
with open(PKL_5MIN, "rb") as f:
    final_pkl = pickle.load(f)
for yr_check in [2023, 2024]:
    covered = sum(
        1 for tk in final_pkl
        if len(pd.DatetimeIndex(final_pkl[tk].index)[
            pd.DatetimeIndex(final_pkl[tk].index).year == yr_check]) > 100
    )
    print(f"  5-min {yr_check}: {covered}/{len(final_pkl)} tickers have data")

with open(EARNINGS_PATH) as f:
    final_ec = json.load(f)
for yr_check in ["2023", "2024"]:
    n = sum(1 for tk in final_ec
            for d in final_ec[tk] if d.startswith(yr_check))
    print(f"  Earnings {yr_check}: {n} events across {len(final_ec)} tickers")

print()
print("Next step:")
print("  cd d:\\raits\\raits")
print("  python raits\\scripts\\window_debug.py")
