import sys, collections
import numpy as np, pandas as pd
sys.path.insert(0, r"d:\raits"); sys.path.insert(0, r"d:\raits\scratch")
import harness as H
from futures.basket import SWING_TF_PARAM
from futures.swing_tf import basket_labels, load_basket, costs_for_basket
from raits.strategies.trend_follow import TrendFollowStrategy
from model_sameday_stop import run_loop

ema = SWING_TF_PARAM["ema_period"]
c = dict(TrendFollowStrategy().config)
c["ema_period"] = ema; c["chandelier_atr_mult"] = SWING_TF_PARAM["chandelier_atr_mult"]
strat = TrendFollowStrategy(c)
labels = basket_labels("spy_daily_live.csv")
bas = load_basket("data/cache/futures/frozen_sim"); COSTS = costs_for_basket(2.0)
cut = pd.Timestamp("2024-12-31")

df = bas["MES"]; df = df[df.index <= cut.tz_localize(df.index.tz)]
cache, datr = H._cache(df)
days = list(cache["days"]); ts = cache.get("ts", {})
print("DANH SACH NGAY trong cache — 10 ngay dau:")
for d in days[:10]:
    n = len(ts.get(d, []))
    t0 = ts[d][0] if n else None
    t1 = ts[d][-1] if n else None
    print("  {} {:<4} {:>4} nen | tu {} den {}".format(
        d.date(), d.day_name()[:3], n,
        pd.Timestamp(t0).strftime("%H:%M") if t0 is not None else "-",
        pd.Timestamp(t1).strftime("%H:%M") if t1 is not None else "-"))
print("\nphan bo thu trong danh sach ngay: {}".format(
    dict(collections.Counter(d.day_name()[:3] for d in days))))

sig = H._make_sig(cache, datr, labels, strat, ema, set(c["allowed_regimes"]), H.Cfg(), True)
tr, _ = run_loop(df, labels, COSTS["MES"], strat=strat, ema_period=ema,
                 mult=SWING_TF_PARAM["chandelier_atr_mult"], max_hold_days=5,
                 cache=cache, same_day_stop=False, stop_slip_ticks=0.0,
                 activate_after_h=0.0, sig_cache=sig,
                 stop_active_hour=H.ARM_LIVE, ratchet=False, disaster_mult=None)
pos = {d: i for i, d in enumerate(days)}
cnt = collections.Counter(); vd = []
for t in tr:
    if t["reason"] != "CHANDELIER":
        continue
    d0 = pd.Timestamp(t["day"]).normalize(); d1 = pd.Timestamp(t["exit_day"]).normalize()
    i0 = pos.get(d0)
    if i0 is None or i0 + 1 >= len(days) or days[i0 + 1] != d1:
        continue
    if d1 == d0 + pd.Timedelta(days=1):
        continue
    cnt[(d0.day_name()[:3], d1.day_name()[:3], (d1 - d0).days)] += 1
    et = pd.Timestamp(t["exit_time"])
    if et.tzinfo is not None:
        et = et.tz_localize(None)
    if len(vd) < 6:
        vd.append((d0.date(), d0.day_name()[:3], d1.date(), d1.day_name()[:3],
                   et.strftime("%H:%M"), float(t["pnl"])))
print("\n84 LENH DO thuc su la nhung cap ngay nao (MES):")
for k, v in sorted(cnt.items(), key=lambda x: -x[1]):
    print("   {} -> {}  cach {} ngay lich : {} lenh".format(k[0], k[1], k[2], v))
print("\n vai lenh cu the:")
for r in vd:
    print("   vao {} {} -> thoat {} {} luc {}  P&L ${:,.0f}".format(*r))
