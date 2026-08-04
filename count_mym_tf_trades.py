"""count_mym_tf_trades.py — count MYM TF trades and PnL from full parquet backtest."""
import sys; sys.path.insert(0, ".")
import collections
import numpy as np
import pandas as pd

from futures._validated_core import benchmark_daily, label_regimes
from futures.basket import REGIME, SWING_TF_PARAM
from futures.swing_tf_harness import backtest_swing_tf
from futures.swing_tf import costs_for_basket

PARQUET = "data/cache/futures/YM_continuous_1m_8y.parquet"

df = pd.read_parquet(PARQUET)
if df.index.tz is not None:
    df.index = df.index.tz_convert("America/New_York").tz_localize(None)
df.columns = [c.lower() for c in df.columns]

bench  = benchmark_daily("spy_daily_live.csv")
labels = label_regimes(bench, "2018-01-01", 3, REGIME["hmm_fit_end"])
cost   = costs_for_basket()["MYM"]

trades = backtest_swing_tf(
    df, labels, cost,
    ema_period=SWING_TF_PARAM["ema_period"],
    chandelier_atr_mult=SWING_TF_PARAM["chandelier_atr_mult"],
    max_hold_days=SWING_TF_PARAM["max_hold_days"],
)

print(f"Total MYM TF trades: {len(trades)}")
by_dir = collections.Counter(t["direction"] for t in trades)
print(f"  LONG : {by_dir.get('LONG',  0)}")
print(f"  SHORT: {by_dir.get('SHORT', 0)}")

total_pnl = sum(t["pnl"] for t in trades)
long_pnl  = sum(t["pnl"] for t in trades if t["direction"] == "LONG")
short_pnl = sum(t["pnl"] for t in trades if t["direction"] == "SHORT")
print(f"  PnL total: ${total_pnl:,.0f}  (LONG ${long_pnl:,.0f} / SHORT ${short_pnl:,.0f})")

# Show entries by month to spot rollover clusters
by_month = collections.Counter(t["day"].strftime("%Y-%m") for t in trades)
print("\nTrades per month (all years, MYM TF):")
for ym, n in sorted(by_month.items()):
    pnl_m = sum(t["pnl"] for t in trades if t["day"].strftime("%Y-%m") == ym)
    print(f"  {ym}: {n:2d} trades  ${pnl_m:+,.0f}")
