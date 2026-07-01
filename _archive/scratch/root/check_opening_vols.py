import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from raits.data.raits_polygon_fetcher import PolygonDataFetcher
from config_private import POLYGON_API_KEY

fetcher = PolygonDataFetcher(api_key=POLYGON_API_KEY, use_cache=True, cache_dir="./raits/data/cache")

for ticker in ["TSLA", "NVDA", "AMD"]:
    frames = []
    for day in pd.bdate_range("2020-07-01", "2020-08-20"):
        try:
            hist = fetcher.fetch_intraday_bars(ticker=ticker, date=day.to_pydatetime(), interval_minutes=5, use_cache=True)
            df = hist.to_dataframe()
            df.columns = [c.lower() for c in df.columns]
            df = df.between_time("09:30", "16:00")
            if not df.empty:
                frames.append(df)
        except Exception:
            pass
    if frames:
        combined = pd.concat(frames).sort_index()
        opening = combined.groupby(combined.index.normalize()).first()["volume"].tail(20)
        print(f"{ticker}: avg opening bar vol={int(opening.mean()):,}  threshold=2x={int(opening.mean()*2):,}")
        print(f"  range: {int(opening.min()):,} - {int(opening.max()):,}")
