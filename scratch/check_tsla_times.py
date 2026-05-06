import os
import sys
import pandas as pd
from datetime import time as dtime

# Set up paths
# Root is C:\Users\quock\RAITS\raits
project_root = r"C:\Users\quock\RAITS\raits"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load API key from config_private.py
config_path = os.path.join(project_root, "config_private.py")
if os.path.exists(config_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("config_private", config_path)
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    POLYGON_API_KEY = getattr(config, "POLYGON_API_KEY", None)
else:
    POLYGON_API_KEY = None

if not POLYGON_API_KEY:
    print("Warning: POLYGON_API_KEY not found. Fetcher might use mock data.")

from raits.data.raits_polygon_fetcher import PolygonDataFetcher

def check_tsla_data():
    fetcher = PolygonDataFetcher(api_key=POLYGON_API_KEY)
    
    ticker = "TSLA"
    start_date = "2023-01-03"
    end_date = "2023-01-03"
    
    print(f"Fetching {ticker} data for {start_date}...")
    # fetch_intraday_bars is the method used in wfo_real_run.py
    # fetch_aggregate_bars is not a method in the fetcher, let's use the correct one.
    from datetime import datetime
    target_dt = datetime.strptime(start_date, "%Y-%m-%d")
    
    hist = fetcher.fetch_intraday_bars(
        ticker=ticker,
        date=target_dt,
        interval_minutes=5,
        use_cache=False # Force fresh fetch since user cleared cache
    )
    
    df = hist.to_dataframe()
    if df is None or df.empty:
        print("No data fetched.")
        return

    # Check timezone if any
    print(f"Index timezone: {df.index.tz}")
    
    print("\nFirst 5 bars (expecting 04:00, 04:05, 04:10...):")
    print(df.index[:5])
    
    print("\nFirst 3 bars after market open (expecting 09:30, 09:35...):")
    open_bars = df[df.index.time >= dtime(9, 30)]
    print(open_bars.index[:3])

if __name__ == "__main__":
    check_tsla_data()
