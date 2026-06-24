"""
fetch_is_earnings.py — Backfill earnings calendar for IS period 2017-2019.

Existing earnings_dates_expanded.json starts 2019-10-03.
This script fetches Polygon 8-K filing dates for 2017-01-01 → 2019-09-30
and merges them into the existing JSON.

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\fetch_is_earnings.py
"""
import sys, os, json, time
sys.path.insert(0, r'd:\raits\raits')
sys.path.insert(0, r'd:\raits')

from polygon import RESTClient
from config_private import POLYGON_API_KEY

EARNINGS_PATH   = r'd:\raits\raits\data\cache\earnings_dates_expanded.json'
FETCH_FROM      = "2017-01-01"
FETCH_TO        = "2019-09-30"

client = RESTClient(api_key=POLYGON_API_KEY)

# Load existing calendar
with open(EARNINGS_PATH) as f:
    earnings = json.load(f)

tickers = sorted(earnings.keys())
print(f"Backfilling {len(tickers)} tickers: {FETCH_FROM} → {FETCH_TO}")
print()

added_total = 0
for i, tk in enumerate(tickers):
    existing = set(earnings[tk])
    new_dates = []
    try:
        for r in client.vx.list_stock_financials(
            ticker=tk,
            timeframe="quarterly",
            filing_date_gte=FETCH_FROM,
            filing_date_lte=FETCH_TO,
            limit=20,
        ):
            d = str(r.filing_date)[:10]
            if d not in existing:
                new_dates.append(d)
        if new_dates:
            earnings[tk] = sorted(set(earnings[tk]) | set(new_dates))
            print(f"  {tk}: +{len(new_dates)} dates {new_dates}")
            added_total += len(new_dates)
        else:
            print(f"  {tk}: no new dates")
    except Exception as e:
        print(f"  {tk}: ERROR {e}")
    time.sleep(0.15)

print(f"\nTotal new dates added: {added_total}")

with open(EARNINGS_PATH, "w") as f:
    json.dump(earnings, f, indent=2)
print(f"Saved → {EARNINGS_PATH}")

# Summary by year
all_dates = sorted([d for dates in earnings.values() for d in dates])
from collections import Counter
years = Counter(d[:4] for d in all_dates)
print("\nCoverage by year:")
for yr in sorted(years):
    print(f"  {yr}: {years[yr]} events")
