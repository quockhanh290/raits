"""
fetch_vix_daily.py — Download VIX daily closes from Polygon.io

Fetches I:VIX (CBOE Volatility Index) daily bars 2018-01-01 → today and saves
to data/cache/daily/vix_daily.parquet for use by the engine VIX gate.

Usage:
    cd d:\\raits\\raits
    py -3.11 raits\\scripts\\fetch_vix_daily.py
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

EASTERN    = ZoneInfo("America/New_York")
OUTPUT     = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "daily", "vix_daily.parquet")
OUTPUT     = os.path.normpath(OUTPUT)
START_DATE = "2018-01-01"
END_DATE   = datetime.now(tz=EASTERN).strftime("%Y-%m-%d")

try:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')))
    from config_private import POLYGON_API_KEY
except ImportError:
    print("ERROR: config_private.py not found or POLYGON_API_KEY not set.")
    sys.exit(1)

def fetch_vix_polygon(api_key: str, start: str, end: str) -> pd.Series:
    url = f"https://api.polygon.io/v2/aggs/ticker/I:VIX/range/1/day/{start}/{end}"
    params = {
        "adjusted": "true",
        "sort":     "asc",
        "limit":    50000,
        "apiKey":   api_key,
    }
    print(f"Fetching I:VIX {start} → {end} ...")
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    if data.get("status") not in ("OK", "DELAYED"):
        raise ValueError(f"Polygon status: {data.get('status')} — {data.get('error', '')}")

    results = data.get("results", [])
    if not results:
        raise ValueError("No results returned from Polygon for I:VIX")

    # Polygon returns UTC ms timestamps; convert to ET date
    rows = []
    for r in results:
        utc_dt = datetime.fromtimestamp(r["t"] / 1000, tz=timezone.utc)
        et_date = utc_dt.astimezone(EASTERN).date()
        rows.append({"date": pd.Timestamp(et_date), "vix": r["c"]})

    s = pd.DataFrame(rows).set_index("date")["vix"].sort_index()
    return s

vix = fetch_vix_polygon(POLYGON_API_KEY, START_DATE, END_DATE)
print(f"Fetched {len(vix)} days  |  VIX range: {vix.min():.1f} – {vix.max():.1f}")
print(f"Latest: {vix.index[-1].date()}  VIX={vix.iloc[-1]:.2f}")

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
vix.to_frame().to_parquet(OUTPUT)
print(f"Saved → {OUTPUT}")
