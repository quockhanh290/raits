
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from raits.backtest.engine import BacktestEngine
from raits.backtest.data_types import BacktestConfig
from raits.data.raits_polygon_fetcher import PolygonDataFetcher
from config_private import POLYGON_API_KEY

fetcher = PolygonDataFetcher(api_key=POLYGON_API_KEY, use_cache=True, cache_dir="./raits/data/cache")
UNIVERSE     = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMD", "META"]
ORB_UNIVERSE = ["TSLA", "PLTR", "AMD", "NVDA", "META", "MSTR", "SMCI", "COIN"]
TICKERS      = ["SPY"] + UNIVERSE + [t for t in ORB_UNIVERSE if t not in UNIVERSE]

# Run Aug + Dec 2020 to see ORB trades
market_data = {}
for ticker in TICKERS:
    frames = []
    for day in pd.bdate_range("2020-08-01", "2020-08-31"):
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
    for day in pd.bdate_range("2020-12-01", "2020-12-31"):
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
    start_date="2020-08-01", end_date="2020-12-31",
    universe=UNIVERSE, orb_universe=ORB_UNIVERSE,
    account_equity=50_000.0, enable_pdt_guard=False,
    enable_costs=True, orb_range_minutes=15,
    vwap_bb_std=2.0, ema_period=30, log_level="WARNING",
)
result = BacktestEngine(cfg).run(market_data)

orb_trades = [t for t in result.trade_log if t.strategy == "ORB"]
print(f"ORB trades Aug-Dec 2020: {len(orb_trades)}")
print()
print(f"{'Date':<12} {'Ticker':<8} {'Dir':<6} {'Entry':>8} {'Stop':>8} {'Target':>8} {'Exit':>8} {'Stop%':>7} {'P&L':>10} {'Reason'}")
print("-" * 95)
for t in orb_trades:
    stop_pct = abs(t.entry_price - t.stop) / t.entry_price * 100
    print(
        f"{str(t.entry_time.date()):<12} {t.ticker:<8} {t.direction:<6} "
        f"${t.entry_price:>6.2f} ${t.stop:>6.2f} ${t.target:>6.2f} "
        f"${t.exit_price or 0:>6.2f} {stop_pct:>6.2f}% "
        f"${t.net_pnl or 0:>8.2f} {t.exit_reason}"
    )

winners = [t for t in orb_trades if (t.net_pnl or 0) > 0]
losers  = [t for t in orb_trades if (t.net_pnl or 0) <= 0]
print(f"\nWin rate: {len(winners)}/{len(orb_trades)} = {len(winners)/max(len(orb_trades),1):.0%}")
print(f"Avg stop distance: {sum(abs(t.entry_price-t.stop)/t.entry_price*100 for t in orb_trades)/max(len(orb_trades),1):.2f}%")
print(f"Max stop distance: {max(abs(t.entry_price-t.stop)/t.entry_price*100 for t in orb_trades):.2f}%")
print(f"Min stop distance: {min(abs(t.entry_price-t.stop)/t.entry_price*100 for t in orb_trades):.2f}%")
