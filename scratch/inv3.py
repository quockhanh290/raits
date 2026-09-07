"""BT2 viet lai: co kiem duoc tu ngoai.

Keo theo chi NANG stop cua LONG va HA stop cua SHORT. Nen tren cac lenh khop cap
(cung ngay vao + cung chieu + cung gia vao) giua hai lan chay:
    LONG : gia thoat(ratchet TAT) <= gia thoat(ratchet BAT)
    SHORT: gia thoat(ratchet TAT) >= gia thoat(ratchet BAT)
Vi pham = co huong nao do keo theo lam stop di sai chieu -> co ratchet hong.

Doi chung bat buoc: (a) so cap khop phai lon, (b) so cap KHAC NHAU phai lon —
neu hai lan chay cho y het nhau thi co ratchet khong lam gi va phep kiem rong.
"""
import sys
import pandas as pd
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
cut = pd.Timestamp("2024-12-31"); ARM = H.ARM_LIVE


def chay(ratchet):
    out = {}
    for sym, d in bas.items():
        df = d[d.index <= cut.tz_localize(d.index.tz)]
        cache, datr = H._cache(df)
        sig = H._make_sig(cache, datr, labels, strat, ema, set(c["allowed_regimes"]),
                          H.Cfg(), True)
        tr, _ = run_loop(df, labels, COSTS[sym], strat=strat, ema_period=ema,
                         mult=SWING_TF_PARAM["chandelier_atr_mult"], max_hold_days=5,
                         cache=cache, same_day_stop=False, stop_slip_ticks=0.0,
                         activate_after_h=0.0, sig_cache=sig,
                         stop_active_hour=ARM, ratchet=ratchet, disaster_mult=None)
        out[sym] = tr
        H._CACHE.clear()
    return out


print("chay ratchet=False ...");  TAT = chay(False)
print("chay ratchet=True  ...");  BAT = chay(True)

khop = khac = vi = 0
vd = []
for sym in TAT:
    kb = {}
    for t in BAT[sym]:
        if t["reason"] == "CHANDELIER":
            kb[(t["day"], t["direction"], t["entry"])] = t
    for t in TAT[sym]:
        if t["reason"] != "CHANDELIER":
            continue
        u = kb.get((t["day"], t["direction"], t["entry"]))
        if u is None:
            continue
        khop += 1
        a, b = float(t["exit"]), float(u["exit"])
        if abs(a - b) > 0.005:
            khac += 1
        sai = (a > b + 0.005) if t["direction"] == "LONG" else (a < b - 0.005)
        if sai:
            vi += 1
            if len(vd) < 3:
                vd.append((sym, t["day"], t["direction"], a, b))

print("\n" + "=" * 74)
print("BT2 viet lai — keo theo phai day stop dung mot chieu")
print("=" * 74)
print("  cap lenh khop duoc giua hai lan chay : {}".format(khop))
print("  trong do hai ben cho gia KHAC nhau   : {}  {}".format(
    khac, "(co ratchet co tac dung -> phep kiem khong rong)" if khac
    else "!! ratchet khong doi gi -> PHEP KIEM RONG"))
print("  vi pham (stop di sai chieu)          : {}  {}".format(
    vi, "DAT" if vi == 0 else "!! KHONG DAT"))
for x in vd:
    print("     {} {} {} tat={:.2f} bat={:.2f}".format(*x))
