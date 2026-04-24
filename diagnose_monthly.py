
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from collections import defaultdict
from raits.backtest.engine import BacktestEngine
from raits.backtest.data_types import BacktestConfig
from raits.data.raits_polygon_fetcher import PolygonDataFetcher
from config_private import POLYGON_API_KEY

fetcher = PolygonDataFetcher(api_key=POLYGON_API_KEY, use_cache=True, cache_dir="./raits/data/cache")
UNIVERSE     = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMD", "META"]
ORB_UNIVERSE = ["TSLA", "PLTR", "AMD", "NVDA", "META", "MSTR", "SMCI", "COIN"]
TICKERS      = ["SPY"] + UNIVERSE + [t for t in ORB_UNIVERSE if t not in UNIVERSE]
START, END   = "2020-01-06", "2020-12-31"

print("Loading data...")
market_data = {}
for ticker in TICKERS:
    frames = []
    for day in pd.bdate_range(START, END):
        try:
            hist = fetcher.fetch_intraday_bars(ticker=ticker, date=day.to_pydatetime(), interval_minutes=5, use_cache=True)
            df = hist.to_dataframe().reset_index()
            df.rename(columns={"timestamp": "datetime"}, inplace=True)
            df.set_index("datetime", inplace=True)
            df.index = pd.DatetimeIndex(df.index)
            df.columns = [c.lower() for c in df.columns]
            df = df.between_time("09:30", "16:00")
            if not df.empty:
                frames.append(df)
        except Exception:
            pass
    if frames:
        market_data[ticker] = pd.concat(frames).sort_index()
        market_data[ticker] = market_data[ticker][~market_data[ticker].index.duplicated(keep="first")]

cfg = BacktestConfig(
    start_date=START, end_date=END,
    universe=UNIVERSE, orb_universe=ORB_UNIVERSE,
    account_equity=50_000.0, enable_pdt_guard=False,
    enable_costs=True, orb_range_minutes=15,
    vwap_bb_std=2.0, ema_period=30, log_level="WARNING",
)
result = BacktestEngine(cfg).run(market_data)

# Break down by month and strategy
monthly = defaultdict(lambda: defaultdict(list))
for t in result.trade_log:
    month = t.entry_time.strftime("%Y-%m")
    monthly[month][t.strategy].append(t.net_pnl or 0)

print("\n=== Monthly P&L by Strategy ===")
print(f"{'Month':<10} {'TREND_FOLLOW':>14} {'VWAP_MR':>10} {'ORB':>8} {'Total':>10} {'#Trades':>8}")
print("-" * 60)
total_tf = total_vwap = total_orb = 0
for month in sorted(monthly.keys()):
    tf   = sum(monthly[month].get("TREND_FOLLOW", []))
    vwap = sum(monthly[month].get("VWAP_MR", []))
    orb  = sum(monthly[month].get("ORB", []))
    n    = sum(len(v) for v in monthly[month].values())
    total = tf + vwap + orb
    total_tf += tf; total_vwap += vwap; total_orb += orb
    print(f"{month:<10} ${tf:>12.2f} ${vwap:>8.2f} ${orb:>6.2f} ${total:>8.2f} {n:>8}")

print("-" * 60)
print(f"{'TOTAL':<10} ${total_tf:>12.2f} ${total_vwap:>8.2f} ${total_orb:>6.2f} ${total_tf+total_vwap+total_orb:>8.2f}")
