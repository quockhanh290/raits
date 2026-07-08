"""
create_earnings_from_scratch.py
================================
Build earnings_dates_expanded.json from scratch using Polygon financials API.
Fetches quarterly 8-K filing dates for IS (2017-2022) + OOS (2023-2024).

Run from d:\\raits\\raits:
    python raits\\scripts\\create_earnings_from_scratch.py

After this completes, run fetch_is_earnings.py and fetch_oos_data.py to
fill any gaps if needed.
"""
import sys, os, json, time
sys.path.insert(0, r'd:\raits\raits')
sys.path.insert(0, r'd:\raits')

from polygon import RESTClient
from config_private import POLYGON_API_KEY

EARNINGS_PATH = r'd:\raits\raits\data\cache\earnings_dates_expanded.json'

FETCH_FROM = "2017-01-01"
FETCH_TO   = "2024-12-31"

# Full PE_SHORT_UNIVERSE from raits/backtest/engine.py
TICKERS = [
    # Existing 37-stock pool
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AMD",
    "QCOM", "INTC", "MU", "AVGO", "TXN", "AMAT",
    "ADBE", "CRM", "ORCL", "INTU", "CSCO",
    "AMGN", "GILD", "BIIB", "REGN", "VRTX",
    "COST", "SBUX", "NFLX", "EBAY",
    "JPM", "GS", "MS", "V", "MA",
    "HON", "MMM",
    "XOM", "CVX",
    # Expansion (Phase 2)
    "PFE", "MRK", "LLY", "ABBV", "JNJ", "BMY",
    "BAC", "WFC", "C",
    "WMT", "TGT", "HD", "LOW", "MCD", "NKE",
    "PG", "KO", "PEP",
    "CAT", "DE", "BA", "GE",
    "PYPL", "PANW", "NOW",
]

client = RESTClient(api_key=POLYGON_API_KEY)
earnings = {tk: [] for tk in sorted(TICKERS)}

print(f"Creating earnings_dates_expanded.json from scratch")
print(f"Tickers: {len(TICKERS)}  |  Period: {FETCH_FROM} → {FETCH_TO}")
print()

errors = []
for i, tk in enumerate(sorted(TICKERS), 1):
    dates = set()
    try:
        for r in client.vx.list_stock_financials(
            ticker=tk,
            timeframe="quarterly",
            filing_date_gte=FETCH_FROM,
            filing_date_lte=FETCH_TO,
            limit=50,
        ):
            dates.add(str(r.filing_date)[:10])
        earnings[tk] = sorted(dates)
        print(f"  [{i:2d}/{len(TICKERS)}] {tk:6s}: {len(dates)} events  "
              f"({min(dates) if dates else 'none'} .. {max(dates) if dates else 'none'})")
    except Exception as e:
        errors.append((tk, str(e)))
        print(f"  [{i:2d}/{len(TICKERS)}] {tk:6s}: ERROR — {e}")
    time.sleep(0.15)

with open(EARNINGS_PATH, "w") as f:
    json.dump(earnings, f, indent=2)

total = sum(len(v) for v in earnings.values())
print(f"\nSaved {total} events for {len(TICKERS)} tickers → {EARNINGS_PATH}")

if errors:
    print(f"\nErrors ({len(errors)}):")
    for tk, msg in errors:
        print(f"  {tk}: {msg}")