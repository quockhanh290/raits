import pandas as pd
import glob
import os

cache_dir = r"C:\Users\quock\RAITS\raits\raits\data\cache\data"
files = glob.glob(os.path.join(cache_dir, "TSLA_5min_*.parquet"))

if not files:
    print("No TSLA cache files found.")
else:
    all_tsla = []
    for f in files:
        df = pd.read_parquet(f)
        all_tsla.append(df)
    
    tsla_df = pd.concat(all_tsla)
    tsla_df.index = pd.to_datetime(tsla_df.index)
    
    # Filter for 2023-01-03
    target_date = pd.Timestamp('2023-01-03')
    day_bars = tsla_df[tsla_df.index.normalize() == target_date]
    
    if day_bars.empty:
        print("No TSLA data found for 2023-01-03 in cache.")
        # Let's see what dates ARE there
        unique_dates = tsla_df.index.normalize().unique().sort_values()
        print(f"Available dates for TSLA: {unique_dates[:5]} ... {unique_dates[-5:]}")
    else:
        print(f"TSLA bars for 2023-01-03 (first 5):")
        print(day_bars.index[:5])
