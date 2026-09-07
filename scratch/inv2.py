"""Va hai lo hong bo kiem: BT2 chay mau rong, va truy lenh vi pham BT3 con lai.

BT2 lay stop ban dau tu bo nho tin hieu (sig[day][1]["initial_stop"]) vi _close khong
mang stop0 vao ban ghi. Bat buoc in co mau — mau rong = phep kiem hong.
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
ARM = H.ARM_LIVE


def chay(ratchet):
    ra = []
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
        ra.append((sym, tr, cache, sig, df))
        H._CACHE.clear()
    return ra


def bt2(ra):
    n = vi = 0; lech = []
    for sym, tr, cache, sig, _ in ra:
        for t in tr:
            if t["reason"] != "CHANDELIER":
                continue
            k = pd.Timestamp(t["day"]).normalize()
            s = sig.get(k)
            if s is None:
                continue
            s0 = float(s[1]["initial_stop"])
            n += 1
            if abs(float(t["exit"]) - round(s0, 2)) > 0.005:
                vi += 1
                if len(lech) < 3:
                    lech.append((sym, t["day"], float(t["exit"]), round(s0, 2)))
    return n, vi, lech


print("dang chay ratchet=False ...")
A = chay(False)
print("dang chay ratchet=True (doi chung am) ...")
B = chay(True)

nA, vA, lA = bt2(A)
nB, vB, lB = bt2(B)
print("\n" + "=" * 72)
print("BT2 — ratchet tat thi gia thoat phai bang stop BAN DAU")
print("=" * 72)
print("  cau hinh chinh  ratchet=False : {:>4}/{:<5} vi pham   {}".format(
    vA, nA, "DAT" if (nA > 0 and vA == 0) else ("MAU RONG" if nA == 0 else "!! KHONG DAT")))
for x in lA:
    print("     {} {} thoat {:.2f} nhung stop ban dau {:.2f}".format(*x))
print("  doi chung am    ratchet=True  : {:>4}/{:<5} vi pham   {}".format(
    vB, nB, "DAT (phep kiem song)" if vB > 0 else "!! phep kiem HONG"))
for x in lB[:2]:
    print("     {} {} thoat {:.2f} nhung stop ban dau {:.2f}".format(*x))

# ── BT3: truy lenh vi pham con lai tren ban DA hieu chinh ──────────────────
print("\n" + "=" * 72)
print("BT3 — truy lenh con ghi gia ngoai bien do nen SAU hieu chinh")
print("=" * 72)
tong = viol = 0
for sym, tr, cache, sig, df in A:
    trc, _, _ = H._correct(tr, df, COSTS[sym].point_value, ARM)
    hl, ts = cache["hl"], cache.get("ts", {})
    for t in trc:
        d1 = pd.Timestamp(t["exit_day"]).normalize()
        dts = ts.get(d1)
        if dts is None or not len(dts):
            continue
        nv = dts.tz_localize(None) if dts.tz is not None else dts
        et = pd.Timestamp(t["exit_time"])
        if et.tzinfo is not None:
            et = et.tz_localize(None)
        j = int(np.searchsorted(np.asarray(nv), np.datetime64(et)))
        if j >= len(nv) or pd.Timestamp(nv[j]) != et:
            continue
        tong += 1
        lo, hi = float(hl[d1][1][j]), float(hl[d1][0][j])
        px = float(t["exit"])
        if px < lo - 1e-6 or px > hi + 1e-6:
            viol += 1
            print("  {} {} {} vao {} -> thoat {} luc {}".format(
                sym, t["direction"], t["reason"], t["day"], t["exit_day"],
                et.strftime("%H:%M")))
            print("     gia ghi {:.2f} | nen do: thap {:.2f} cao {:.2f} mo {:.2f}"
                  .format(px, lo, hi, float(hl[d1][2][j])))
            print("     lech ra ngoai {:.2f} diem | P&L ghi ${:,.0f}".format(
                (lo - px) if px < lo else (px - hi), float(t["pnl"])))
print("  tong {} lenh doi chieu duoc | vi pham {}".format(tong, viol))
