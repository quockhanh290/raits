"""
diagnose_trades.py
Run a short backtest and print every trade with exit reason,
P&L, and how far price moved toward target vs stop.

Usage:
    cd <your project root>
    python diagnose_trades.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from collections import defaultdict

from raits.backtest.engine import BacktestEngine
from raits.backtest.data_types import BacktestConfig
from raits.data.raits_polygon_fetcher import PolygonDataFetcher
from config_private import POLYGON_API_KEY

# ── Fetch 3 months of data ────────────────────────────────────────────────────
print("Loading data from cache...")
fetcher = PolygonDataFetcher(
    api_key=POLYGON_API_KEY,
    use_cache=True,
    cache_dir="./raits/data/cache",
)

UNIVERSE     = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMD", "META"]
ORB_UNIVERSE = ["TSLA", "PLTR", "AMD", "NVDA", "META", "MSTR", "SMCI", "COIN"]
TICKERS      = ["SPY"] + UNIVERSE + [t for t in ORB_UNIVERSE if t not in UNIVERSE]
START = "2021-01-05"
END   = "2021-06-30"

market_data = {}
for ticker in TICKERS:
    frames = []
    for day in pd.bdate_range(START, END):
        try:
            hist = fetcher.fetch_intraday_bars(
                ticker=ticker,
                date=day.to_pydatetime(),
                interval_minutes=5,
                use_cache=True,
            )
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
        market_data[ticker] = market_data[ticker][
            ~market_data[ticker].index.duplicated(keep="first")
        ]

print(f"Loaded {len(market_data)} tickers")
for t, df in market_data.items():
    print(f"  {t}: {len(df)} bars, {df.index.normalize().nunique()} days")

# ── Run backtest ──────────────────────────────────────────────────────────────
cfg = BacktestConfig(
    start_date=START,
    end_date=END,
    universe=UNIVERSE,
    orb_universe=ORB_UNIVERSE,
    account_equity=50_000.0,
    enable_pdt_guard=False,
    enable_costs=True,
    orb_range_minutes=15,
    vwap_bb_std=2.0,
    ema_period=20,
    log_level="WARNING",
)

print(f"\nRunning backtest {START} → {END}...")
engine = BacktestEngine(cfg)
result = engine.run(market_data)

trades = result.trade_log
print(f"\nTotal trades: {len(trades)}")
if not trades:
    print("No trades fired — check signal generation")
    sys.exit(0)

# ── Analyse exit reasons ──────────────────────────────────────────────────────
exit_counts = defaultdict(int)
exit_pnl    = defaultdict(list)
strategy_counts = defaultdict(int)

for t in trades:
    reason = getattr(t, 'exit_reason', 'UNKNOWN')
    exit_counts[reason] += 1
    exit_pnl[reason].append(getattr(t, 'net_pnl', 0) or 0)
    strategy_counts[getattr(t, 'strategy', 'UNKNOWN')] += 1

print("\n=== Exit Reason Breakdown ===")
print(f"{'Reason':<20} {'Count':>7} {'%':>7} {'Avg P&L':>10} {'Total P&L':>12}")
print("-" * 60)
total = len(trades)
for reason, count in sorted(exit_counts.items(), key=lambda x: -x[1]):
    pnls = exit_pnl[reason]
    avg  = sum(pnls) / len(pnls)
    tot  = sum(pnls)
    pct  = count / total * 100
    print(f"{reason:<20} {count:>7} {pct:>6.1f}% ${avg:>8.2f} ${tot:>10.2f}")

print("\n=== Strategy Breakdown ===")
print(f"{'Strategy':<20} {'Count':>7} {'%':>7}")
print("-" * 35)
for strat, count in sorted(strategy_counts.items(), key=lambda x: -x[1]):
    print(f"{strat:<20} {count:>7} {count/total*100:>6.1f}%")

print("\n=== P&L Distribution ===")
pnls = [getattr(t, 'net_pnl', 0) or 0 for t in trades]
winners = [p for p in pnls if p > 0]
losers  = [p for p in pnls if p <= 0]
print(f"Winners:  {len(winners)} trades, avg ${sum(winners)/max(len(winners),1):.2f}, total ${sum(winners):.2f}")
print(f"Losers:   {len(losers)} trades, avg ${sum(losers)/max(len(losers),1):.2f}, total ${sum(losers):.2f}")
print(f"Win rate: {len(winners)/total:.1%}")
print(f"Win/loss: {sum(winners)/max(abs(sum(losers)),1):.2f}x")

print("\n=== Sample Trades (first 20) ===")
print(f"{'Ticker':<6} {'Strategy':<12} {'Dir':<6} {'Entry':>8} {'Stop':>8} "
      f"{'Target':>8} {'Exit':>8} {'Reason':<15} {'P&L':>8}")
print("-" * 90)
for t in trades[:20]:
    print(
        f"{getattr(t,'ticker','?'):<6} "
        f"{getattr(t,'strategy','?'):<12} "
        f"{getattr(t,'direction','?'):<6} "
        f"${getattr(t,'entry_price',0):>6.2f} "
        f"${getattr(t,'stop',0):>6.2f} "
        f"${getattr(t,'target',0):>6.2f} "
        f"${getattr(t,'exit_price',0):>6.2f} "
        f"{getattr(t,'exit_reason','?'):<15} "
        f"${getattr(t,'net_pnl',0) or 0:>7.2f}"
    )

print("\n=== Risk/Reward Realised ===")
for t in trades[:20]:
    entry  = getattr(t, 'entry_price', 0)
    stop   = getattr(t, 'stop', entry)
    target = getattr(t, 'target', entry)
    exit_p = getattr(t, 'exit_price', entry)
    risk   = abs(entry - stop)
    if risk > 0:
        actual_r = (exit_p - entry) / risk if getattr(t,'direction','') == 'LONG' \
                   else (entry - exit_p) / risk
        target_r = abs(target - entry) / risk
        print(f"  {getattr(t,'ticker','?')} {getattr(t,'strategy','?')}: "
              f"target={target_r:.1f}R  actual={actual_r:.1f}R  "
              f"exit={getattr(t,'exit_reason','?')}")
