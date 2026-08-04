"""verify_mnq_jul27_v2.py — chạy backtest_swing_tf trực tiếp, tìm Jul27 MNQ trade."""
import sys; sys.path.insert(0, ".")
from futures._validated_core import load_parquet, benchmark_daily, label_regimes
from futures.basket import BASKET, data_filename, SWING_TF_PARAM, REGIME
from futures.swing_tf import costs_for_basket
from futures.swing_tf_harness import backtest_swing_tf
from pathlib import Path

PARQUET = Path("data/cache/futures") / data_filename(BASKET["MNQ"])
df = load_parquet(str(PARQUET))
bench  = benchmark_daily("spy_daily_live.csv")
labels = label_regimes(bench, "2018-01-01", 3, REGIME["hmm_fit_end"])
cost   = costs_for_basket()["MNQ"]

trades = backtest_swing_tf(
    df, labels, cost,
    ema_period=SWING_TF_PARAM["ema_period"],
    chandelier_atr_mult=SWING_TF_PARAM["chandelier_atr_mult"],
    max_hold_days=SWING_TF_PARAM["max_hold_days"],
)

# Tìm trades gần Jul27
recent = [t for t in trades if str(t["day"])[:10] >= "2026-07-01"]
if trades:
    print(f"Trade dict keys: {list(trades[0].keys())}")
print(f"\nMNQ TF trades từ Jul 2026 ({len(recent)} trades):")
for t in recent:
    print(f"  {t}")

# desired_basket reference
print()
print("desired_basket reported: MNQ SHORT entry=28312.25 stop=28361.42 entry_day=2026-07-27")
