"""Live vu trang 18:30 CN (slot stop_repair). Mo hinh vu trang 18:00 (nen dau phien).
Dem lenh dong trong dung nua tieng do — nhung lenh mo hinh co stop ma live chua co.

Doi chung duong bat buoc: tong 84 lenh phai khac 0 va phan bo gio phai trai rong,
neu tat ca don ve mot moc thi phep dem hong.
"""
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

T = {"n": 0, "trong_ho": 0, "pnl_ho": 0.0}
gio = collections.Counter()
for sym, df in bas.items():
    df = df[df.index <= cut.tz_localize(df.index.tz)]
    cache, datr = H._cache(df)
    sig = H._make_sig(cache, datr, labels, strat, ema, set(c["allowed_regimes"]), H.Cfg(), True)
    tr, _ = run_loop(df, labels, COSTS[sym], strat=strat, ema_period=ema,
                     mult=SWING_TF_PARAM["chandelier_atr_mult"], max_hold_days=5,
                     cache=cache, same_day_stop=False, stop_slip_ticks=0.0,
                     activate_after_h=0.0, sig_cache=sig,
                     stop_active_hour=H.ARM_LIVE, ratchet=False, disaster_mult=None)
    days = list(cache["days"]); pos = {d: i for i, d in enumerate(days)}
    n = nh = 0; ph = 0.0
    for t in tr:
        if t["reason"] != "CHANDELIER":
            continue
        d0 = pd.Timestamp(t["day"]).normalize(); d1 = pd.Timestamp(t["exit_day"]).normalize()
        i0 = pos.get(d0)
        if i0 is None or i0 + 1 >= len(days) or days[i0 + 1] != d1:
            continue
        if d1 == d0 + pd.Timedelta(days=1):
            continue
        n += 1
        et = pd.Timestamp(t["exit_time"])
        if et.tzinfo is not None:
            et = et.tz_localize(None)
        gio[et.hour] += 1
        if et < d1 + pd.Timedelta(hours=18, minutes=30):
            nh += 1; ph += float(t["pnl"])
    print("{:<5} thu Sau->CN {:>3} | dong trong ho 18:00-18:30 {:>2} = ${:>7,.0f}"
          .format(sym, n, nh, ph))
    T["n"] += n; T["trong_ho"] += nh; T["pnl_ho"] += ph
    H._CACHE.clear()

print("\n=== TONG (Ro 4, 1 hop dong, IS 2018-2024) ===")
print("  lenh thu Sau -> CN                        : {}".format(T["n"]))
print("  mo hinh co stop, live CHUA co (18:00-18:30): {} ({:.0%}) = ${:,.0f}"
      .format(T["trong_ho"], T["trong_ho"] / max(T["n"], 1), T["pnl_ho"]))
print("  DOI CHUNG phan bo gio dong (phai trai rong, khong don ve 1 moc):")
for h in sorted(gio):
    print("     {:02d}h: {}".format(h, gio[h]))
