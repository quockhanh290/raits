import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from raits.data.raits_polygon_fetcher import PolygonDataFetcher
from config_private import POLYGON_API_KEY

fetcher = PolygonDataFetcher(api_key=POLYGON_API_KEY, use_cache=True,
                              cache_dir="./raits/data/cache")
TICKERS = ["TSLA", "MSTR", "SMCI", "PLTR", "NVDA", "AMD"]
START, END = "2020-01-06", "2020-12-31"

results = []
for ticker in TICKERS:
    gaps = []
    prev_close = None
    for day in pd.bdate_range(START, END):
        try:
            hist = fetcher.fetch_intraday_bars(
                ticker=ticker, date=day.to_pydatetime(),
                interval_minutes=5, use_cache=True)
            df = hist.to_dataframe()
            df.columns = [c.lower() for c in df.columns]
            df = df.between_time("09:30", "16:00")
            if df.empty:
                continue
            open_p  = float(df.iloc[0]["open"])
            close_p = float(df.iloc[-1]["close"])
            if prev_close and prev_close > 0:
                gaps.append(abs(open_p - prev_close) / prev_close)
            prev_close = close_p
        except Exception:
            pass
    if gaps:
        n = len(gaps)
        results.append((
            ticker, n,
            sum(1 for g in gaps if g >= 0.010) / n,
            sum(1 for g in gaps if g >= 0.015) / n,
            sum(1 for g in gaps if g >= 0.020) / n,
            sum(1 for g in gaps if g >= 0.030) / n,
        ))

print("Gap frequency 2020")
print(f"{'Ticker':<8} {'Days':>6} {'>=1%':>6} {'>=1.5%':>8} {'>=2%':>6} {'>=3%':>6}")
print("-" * 45)
for r in results:
    print(f"{r[0]:<8} {r[1]:>6} {r[2]:>6.0%} {r[3]:>8.0%} {r[4]:>6.0%} {r[5]:>6.0%}")
print()
print("Signals per year at each threshold (assuming all pass other filters):")
for r in results:
    print(f"  {r[0]}: 1%={r[2]*252:.0f}d  1.5%={r[3]*252:.0f}d  2%={r[4]*252:.0f}d  3%={r[5]*252:.0f}d")
