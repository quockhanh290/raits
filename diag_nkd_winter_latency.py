"""Slot dem NKD ghim theo ET, cua so vao lenh theo JST — DST lam do tre gap 7 lan.

    mua he  cua so 14:00-15:55 JST = 01:00-02:55 ET  -> slot dau 01:10 = 14:10 JST (tre 10')
    mua dong cua so 14:00-15:55 JST = 00:00-01:55 ET -> slot dau 01:10 = 15:10 JST (tre 70')

Tin hieu khong mat (replay van thay), nhung lenh khop muon hon nhieu. Do bang chinh
tham so entry_latency_min da dung cho swing.
"""
from __future__ import annotations
import sys
from pathlib import Path
if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures.basket import SWING_TF_PARAM
from futures._validated_core import _swing_cache, daily_atr_series
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index.regime import RegimeLabels, load_spy_regime
from global_index.specs import SPECS
from raits.strategies.trend_follow import TrendFollowStrategy
from model_sameday_stop import build_sig_cache, run_loop

mult, hold, ema = SWING_TF_PARAM["chandelier_atr_mult"], SWING_TF_PARAM["max_hold_days"], 10
strat = TrendFollowStrategy({**TrendFollowStrategy().config,
                             "ema_period": ema, "chandelier_atr_mult": mult})
allowed = set(strat.config["allowed_regimes"])
c = SPECS["MNKD"]
ndf = gi_load("global_index/data/NKD_continuous_1m_8y.parquet")
ndf.index = ndf.index.tz_convert(c.session_tz)
lab = RegimeLabels(load_spy_regime("spy_daily_live.csv"), lag_days=1)
cost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
            slippage_ticks_per_side=1.0)
cache = _swing_cache(ndf, daily_atr_series(ndf))
sig = build_sig_cache(cache, lab, strat, ema, allowed)

print()
print("=" * 72)
print("MNKD — do tre vao lenh do slot dem ghim theo ET (kich hoat stop giu 14h JST)")
print("=" * 72)
print(f"  {'do tre':>28} | {'lenh':>6} | {'P&L':>11} | so voi 10'")
print("  " + "-" * 62)
base = None
for lbl, lat in (("10' (mua he)", 10), ("30'", 30), ("50'", 50),
                 ("70' (mua dong)", 70), ("90'", 90)):
    m, _ = run_loop(ndf, lab, cost, strat=strat, ema_period=ema, mult=mult,
                    max_hold_days=hold, cache=cache, same_day_stop=False,
                    stop_slip_ticks=0.0, stop_active_hour=14.0, sig_cache=sig,
                    entry_latency_min=lat)
    tot = sum(t["pnl"] for t in m)
    if base is None:
        base = tot
    print(f"  {lbl:>28} | {len(m):>6} | ${tot:>+10,.0f} | ${tot-base:>+9,.0f}")
print()
