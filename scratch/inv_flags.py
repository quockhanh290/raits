"""Ba nhanh co chi dung cho cac truc da dong. Neu mot nhanh cai sai thi ket luan
"dong truc" co the sai theo. Moi bat bien kem doi chung am bat buoc.

BT5 stop_basis=x : khoang cach |vao - stop| phai dung bang x * ATR NGAY.
                   doi chung: cau hinh goc (stop theo ATR 5 phut) phai vi pham.
BT6 entry_mode=wait: cho nen dung chieu chi co the DAY diem vao muon hon hoac bo ngay do.
                   -> ngay cua wait phai la tap con cua off; gio vao wait >= gio vao off.
                   doi chung: doi chieu bat dang thuc phai vi pham.
BT7 disaster=k   : lenh thoat DISASTER phai o dung muc vao -+ k*|vao - stop ban dau|.
                   doi chung: khong bat disaster thi phai KHONG co lenh DISASTER nao.
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
base = TrendFollowStrategy(c)
labels = basket_labels("spy_daily_live.csv")
bas = load_basket("data/cache/futures/frozen_sim"); COSTS = costs_for_basket(2.0)
cut = pd.Timestamp("2024-12-31"); ARM = H.ARM_LIVE
ALLOWED = set(c["allowed_regimes"])
DFS = {s: d[d.index <= cut.tz_localize(d.index.tz)] for s, d in bas.items()}


def sigs(cfg):
    """Bo nho tin hieu theo dung duong harness dung, kem strat da boc neu can."""
    out = {}
    for sym, df in DFS.items():
        cache, datr = H._cache(df)
        s = base
        if cfg.stop_basis is not None:
            s = H._wrap_stop(base, datr, cfg.stop_basis) if hasattr(H, "_wrap_stop") else base
        out[sym] = (H._make_sig(cache, datr, labels, s, ema, ALLOWED, cfg, True),
                    cache, datr)
        H._CACHE.clear()
    return out


# ── BT5 ────────────────────────────────────────────────────────────────────
print("BT5 stop_basis ...")
X = 1.0
n5 = v5 = 0; n5c = v5c = 0
for sym, df in DFS.items():
    cache, datr = H._cache(df)
    for nhan, cfg in (("moi", H.Cfg(stop_basis=X, arm_hours=ARM, ratchet=False)),
                      ("goc", H.Cfg(arm_hours=ARM, ratchet=False))):
        strat_i = base
        if cfg.stop_basis is not None and hasattr(H, "_wrap_stop"):
            strat_i = H._wrap_stop(base, datr, cfg.stop_basis)
        sg = H._make_sig(cache, datr, labels, strat_i, ema, ALLOWED, cfg, True)
        for day, val in sg.items():
            s = val[1]
            d = abs(float(s["entry_price"]) - float(s["initial_stop"]))
            a = float(datr.asof(day)) if len(datr) else np.nan
            if not np.isfinite(a) or a <= 0:
                continue
            ok = abs(d - X * a) <= max(0.01, 0.005 * X * a)
            if nhan == "moi":
                n5 += 1; v5 += 0 if ok else 1
            else:
                n5c += 1; v5c += 0 if ok else 1
    H._CACHE.clear()
print("  chinh  stop_basis=1.0 : {:>5}/{:<5} vi pham  {}".format(
    v5, n5, "DAT" if (n5 and v5 == 0) else ("MAU RONG" if not n5 else "!! KHONG DAT")))
print("  doi chung cau hinh goc: {:>5}/{:<5} vi pham  {}".format(
    v5c, n5c, "DAT (phep kiem song)" if v5c > 0 else "!! phep kiem HONG"))

# ── BT6 ────────────────────────────────────────────────────────────────────
print("\nBT6 entry_mode=wait ...")
ngoai = muon = som = tong = 0
for sym, df in DFS.items():
    cache, datr = H._cache(df)
    off = H._make_sig(cache, datr, labels, base, ema, ALLOWED,
                      H.Cfg(arm_hours=ARM, ratchet=False), True)
    wait = H._make_sig(cache, datr, labels, base, ema, ALLOWED,
                       H.Cfg(arm_hours=ARM, ratchet=False, entry_mode="wait"), True)
    for day, val in wait.items():
        tong += 1
        u = off.get(day)
        if u is None:
            ngoai += 1; continue
        tw = pd.Timestamp(val[0]); to = pd.Timestamp(u[0])
        if tw > to:
            muon += 1
        elif tw < to:
            som += 1
    H._CACHE.clear()
print("  tin hieu wait: {} | ngay khong co trong off: {}  {}".format(
    tong, ngoai, "DAT" if ngoai == 0 else "!! KHONG DAT (wait khong the tao ngay moi)"))
print("  vao MUON hon off: {}  {}".format(
    muon, "(khac 0 -> phep kiem khong rong)" if muon else "!! RONG"))
print("  vao SOM hon off : {}  {}".format(
    som, "DAT" if som == 0 else "!! KHONG DAT (cho khong the vao som hon)"))

# ── BT7 ────────────────────────────────────────────────────────────────────
print("\nBT7 disaster ...")
K = 3.0
nd = vd_ = 0; nd_off = 0
for sym, df in DFS.items():
    cache, datr = H._cache(df)
    sg = H._make_sig(cache, datr, labels, base, ema, ALLOWED,
                     H.Cfg(arm_hours=ARM, ratchet=False), True)
    for k_, dm in ((1, K), (0, None)):
        tr, _ = run_loop(df, labels, COSTS[sym], strat=base, ema_period=ema,
                         mult=SWING_TF_PARAM["chandelier_atr_mult"], max_hold_days=5,
                         cache=cache, same_day_stop=False, stop_slip_ticks=0.0,
                         activate_after_h=0.0, sig_cache=sg,
                         stop_active_hour=ARM, ratchet=False, disaster_mult=dm)
        for t in tr:
            if "DISASTER" not in str(t["reason"]).upper():
                continue
            if not k_:
                nd_off += 1; continue
            nd += 1
            s = sg.get(pd.Timestamp(t["day"]).normalize())
            if s is None:
                continue
            ep = float(s[1]["entry_price"]); s0 = float(s[1]["initial_stop"])
            muc = ep - K * abs(ep - s0) if t["direction"] == "LONG" else ep + K * abs(ep - s0)
            px = float(t["exit"])
            sai = (px > muc + 0.02) if t["direction"] == "LONG" else (px < muc - 0.02)
            if sai:
                vd_ += 1
    H._CACHE.clear()
print("  lenh DISASTER khi bat k=3 : {}  {}".format(
    nd, "" if nd else "!! MAU RONG — nhanh nay chua bao gio chay"))
print("  trong do sai muc          : {}  {}".format(
    vd_, "DAT" if (nd and vd_ == 0) else ""))
print("  doi chung: lenh DISASTER khi TAT: {}  {}".format(
    nd_off, "DAT (khong ro ri)" if nd_off == 0 else "!! KHONG DAT"))
