"""Nhom qua cuoi tuan/le: mo hinh vu trang o NEN 0 thu Hai, nhung vong thoat bat dau k=1.
Neu thu Hai MO CUA da vuot mức stop thi khop that o gia mo, mo hinh ghi o muc stop.
Ham _correct hien tai khong bat duoc nhom nay.

Doi chung duong: cung logic chay tren nhom ngay-lich-ke-tiep phai ra khac 0.
"""
import sys
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

T = {"ct_n": 0, "ct_sai": 0, "ct_tien": 0.0, "lich_n": 0, "lich_sai": 0}
for sym, df in bas.items():
    df = df[df.index <= cut.tz_localize(df.index.tz)]
    cost = COSTS[sym]
    cache, datr = H._cache(df)
    sig = H._make_sig(cache, datr, labels, strat, ema, set(c["allowed_regimes"]), H.Cfg(), True)
    tr, _ = run_loop(df, labels, cost, strat=strat, ema_period=ema,
                     mult=SWING_TF_PARAM["chandelier_atr_mult"], max_hold_days=5,
                     cache=cache, same_day_stop=False, stop_slip_ticks=0.0,
                     activate_after_h=0.0, sig_cache=sig,
                     stop_active_hour=H.ARM_LIVE, ratchet=False, disaster_mult=None)
    days = list(cache["days"]); pos = {d: i for i, d in enumerate(days)}
    hl = cache["hl"]
    ctn = cts = 0; ctt = 0.0; ln = ls = 0
    for t in tr:
        if t["reason"] != "CHANDELIER":
            continue
        d0 = pd.Timestamp(t["day"]).normalize(); d1 = pd.Timestamp(t["exit_day"]).normalize()
        i0 = pos.get(d0)
        if i0 is None or i0 + 1 >= len(days) or days[i0 + 1] != d1:
            continue
        cuoituan = d1 != d0 + pd.Timedelta(days=1)
        op0 = float(hl[d1][2][0])              # gia mo nen dau tien cua d1
        stp = float(t["exit"])
        w = (stp - op0) if t["direction"] == "LONG" else (op0 - stp)
        if cuoituan:
            ctn += 1
            if w > 0:
                cts += 1; ctt += w * cost.point_value
        else:
            ln += 1
            if w > 0:
                ls += 1
    print("{:<5} cuoi tuan/le {:>3} -> mo cua da vuot stop {:>3} = ${:>8,.0f}   "
          "| (doi chung ngay lich {:>4} -> {:>3})".format(sym, ctn, cts, ctt, ln, ls))
    T["ct_n"] += ctn; T["ct_sai"] += cts; T["ct_tien"] += ctt
    T["lich_n"] += ln; T["lich_sai"] += ls
    H._CACHE.clear()

print("\n=== TONG (Ro 4, 1 hop dong, IS 2018-2024) ===")
print("  nhom qua cuoi tuan/le          : {}".format(T["ct_n"]))
print("  trong do mo cua DA vuot stop   : {} ({:.0%}) = ${:,.0f}".format(
    T["ct_sai"], T["ct_sai"] / max(T["ct_n"], 1), T["ct_tien"]))
print("  DOI CHUNG nhom ngay lich ke tiep: {}/{} -> {}".format(
    T["lich_sai"], T["lich_n"],
    "khac 0, phep do co the do" if T["lich_sai"] else "= 0, LOGIC HONG"))
print("\n  -> {}".format(
    "HAM _correct BO SOT nhom nay, phai bo sung" if T["ct_sai"]
    else "khong bo sot"))
