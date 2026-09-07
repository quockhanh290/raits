"""Bat bien cho cau hinh KHONG CO NEO: ratchet=False + vu trang 14,08h.

Bon menh de dau ra BUOC phai thoa. Moi menh de deu kem DOI CHUNG AM — chay dung phep
kiem do len mot cau hinh phai vi pham; neu doi chung van xanh thi phep kiem hong va
khong duoc doc ket qua chinh.
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
DFS = {s: d[d.index <= cut.tz_localize(d.index.tz)] for s, d in bas.items()}


def chay(arm, ratchet, sua=False):
    """Tra ve (danh sach lenh kem ngu canh nen) cho ca ro."""
    ra = []
    for sym, df in DFS.items():
        cache, datr = H._cache(df)
        sig = H._make_sig(cache, datr, labels, strat, ema, set(c["allowed_regimes"]),
                          H.Cfg(), True)
        tr, _ = run_loop(df, labels, COSTS[sym], strat=strat, ema_period=ema,
                         mult=SWING_TF_PARAM["chandelier_atr_mult"], max_hold_days=5,
                         cache=cache, same_day_stop=False, stop_slip_ticks=0.0,
                         activate_after_h=0.0, sig_cache=sig,
                         stop_active_hour=arm, ratchet=ratchet, disaster_mult=None)
        if sua:
            tr, _, _ = H._correct(tr, df, COSTS[sym].point_value,
                                  0.0 if arm is None else arm)
        ra.append((sym, tr, cache))
        H._CACHE.clear()
    return ra


def bt1(ra, arm):
    """Khong lenh CHANDELIER nao duoc thoat TRUOC moc vu trang."""
    n = vi = 0
    for sym, tr, _ in ra:
        for t in tr:
            if t["reason"] != "CHANDELIER":
                continue
            n += 1
            et = pd.Timestamp(t["exit_time"])
            if et.tzinfo is not None:
                et = et.tz_localize(None)
            moc = (pd.Timestamp(t["day"]).normalize() + pd.Timedelta(days=1)
                   + pd.Timedelta(hours=arm))
            if et < moc:
                vi += 1
    return n, vi


def bt2(ra):
    """ratchet=False: gia thoat CHANDELIER phai bang stop BAN DAU, khong bao gio la
    muc da keo theo."""
    n = vi = 0
    for sym, tr, _ in ra:
        for t in tr:
            if t["reason"] != "CHANDELIER":
                continue
            s0 = t.get("stop0")
            if s0 is None:
                continue
            n += 1
            if abs(float(t["exit"]) - float(s0)) > 1e-6:
                vi += 1
    return n, vi


def bt3(ra):
    """Moi gia thoat phai nam trong bien do [thap, cao] cua CHINH nen thoat."""
    n = vi = 0
    for sym, tr, cache in ra:
        hl, ts = cache["hl"], cache.get("ts", {})
        for t in tr:
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
            n += 1
            lo, hi = float(hl[d1][1][j]), float(hl[d1][0][j])
            px = float(t["exit"])
            if px < lo - 1e-6 or px > hi + 1e-6:
                vi += 1
    return n, vi


def bt4(ra):
    """So ngay cam khong duoc vuot max_hold_days=5, va ngay thoat >= ngay vao."""
    n = vi = 0
    for sym, tr, cache in ra:
        days = list(cache["days"]); pos = {d: i for i, d in enumerate(days)}
        for t in tr:
            i0 = pos.get(pd.Timestamp(t["day"]).normalize())
            i1 = pos.get(pd.Timestamp(t["exit_day"]).normalize())
            if i0 is None or i1 is None:
                continue
            n += 1
            if i1 < i0 or (i1 - i0) > 5:
                vi += 1
    return n, vi


def bang(nhan, hang):
    print("\n" + "=" * 76)
    print(nhan)
    print("=" * 76)
    for ten, (n, vi), mong in hang:
        dat = (vi == 0) if mong == 0 else (vi > 0)
        print("  {:<52} {:>5}/{:<5} {}".format(
            ten, vi, n, "DAT" if dat else "!! KHONG DAT"))


ARM = H.ARM_LIVE
print("dang chay cau hinh chinh: ratchet=False, vu trang {:.4f}h ...".format(ARM))
chinh = chay(ARM, False)
chinh_sua = chay(ARM, False, sua=True)

bang("CAU HINH CHINH — moi so tieu de deu chay o day (vi pham phai = 0)", [
    ("BT1 khong thoat truoc moc vu trang", bt1(chinh, ARM), 0),
    ("BT2 ratchet tat -> thoat dung o stop ban dau", bt2(chinh), 0),
    ("BT3 gia thoat nam trong bien do nen (SAU hieu chinh)", bt3(chinh_sua), 0),
    ("BT4 so ngay cam <= 5 va khong am", bt4(chinh), 0),
])

print("\ndang chay doi chung am ...")
dc_arm = chay(0.0, False)          # vu trang 0h -> BT1 (o moc 14,08) phai vi pham
dc_rat = chay(ARM, True)           # ratchet bat -> BT2 phai vi pham
bang("DOI CHUNG AM — nhung o nay PHAI vi pham, neu khong thi phep kiem hong", [
    ("BT1 do o moc 14,08h nhung chay vu trang 0h", bt1(dc_arm, ARM), 1),
    ("BT2 do 'bang stop ban dau' nhung chay ratchet BAT", bt2(dc_rat), 1),
    ("BT3 do bien do nen tren ban CHUA hieu chinh", bt3(chinh), 1),
])
