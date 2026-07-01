import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import logging
from raits.data.raits_polygon_fetcher import PolygonDataFetcher
from raits.strategies.orb import ORBStrategy
from config_private import POLYGON_API_KEY

logging.basicConfig(level=logging.DEBUG, format="%(message)s")
logging.getLogger("RAITS.backtest").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

fetcher = PolygonDataFetcher(api_key=POLYGON_API_KEY, use_cache=True, cache_dir="./raits/data/cache")
orb = ORBStrategy(config={"opening_vol_multiplier": 1.2, "min_gap_pct": 0.015})
ORB_TICKERS = ["TSLA", "MSTR", "SMCI", "NVDA", "AMD"]
START, END = "2020-07-01", "2020-09-30"
sample_days = list(pd.bdate_range("2020-08-01", "2020-09-30"))[:20]

print("Loading data...")
all_data = {}
for ticker in ORB_TICKERS:
    frames = []
    for day in pd.bdate_range(START, END):
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
        all_data[ticker] = combined[~combined.index.duplicated(keep="first")]

print(f"Loaded {len(all_data)} tickers\n")
accepted_total = 0
total_candidates = 0

for day in sample_days:
    day_ts = pd.Timestamp(day)
    candidates = []
    for ticker in ORB_TICKERS:
        if ticker not in all_data:
            continue
        full_df = all_data[ticker]
        today_bars = full_df[full_df.index.normalize() == day_ts]
        if today_bars.empty:
            continue
        prior_bars = full_df[full_df.index.normalize() < day_ts]
        if prior_bars.empty:
            continue
        first = today_bars.iloc[0]
        open_p = float(first["open"])
        prev_close = float(prior_bars.iloc[-1]["close"])
        if prev_close <= 0:
            continue
        gap_pct = abs(open_p - prev_close) / prev_close
        if gap_pct < 0.005:
            continue
        prior_first = prior_bars.groupby(prior_bars.index.normalize()).first()["volume"].tail(20)
        avg_open_vol = int(prior_first.mean()) if len(prior_first) > 0 else int(first["volume"])
        avg_daily_volume = max(avg_open_vol * 78, 1)
        candidates.append({
            "ticker": ticker,
            "prev_close": round(prev_close, 2),
            "open_price": open_p,
            "premarket_volume": 0,
            "avg_daily_volume": avg_daily_volume,
            "opening_5min_volume": int(first["volume"]),
        })
        total_candidates += 1
    accepted = orb.run_scanner(candidates)
    accepted_total += len(accepted)

print()
print("=== ORB Scanner Analysis (Aug-Sep 2020, 20 days) ===")
print(f"Total candidates presented: {total_candidates}")
print(f"Total accepted:             {accepted_total}")
print(f"Acceptance rate:            {accepted_total/max(total_candidates,1):.1%}")
print(f"Avg accepted per day:       {accepted_total/len(sample_days):.1f}")
