"""BT5 qua CHINH duong harness (khong tu boc lai). stop_basis=1.0 phai lam khoang cach
stop rong len xap xi ty le ATR ngay / (2,5 x ATR 5 phut). Neu nhanh quet sinh lai khong
nhan stop moi thi phan bo se HAI DINH — mot cum o muc hep cu.

Doi chung: cau hinh goc phai cho cum HEP, va ty le rong phai != 1.
"""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, r"d:\raits"); sys.path.insert(0, r"d:\raits\scratch")
import harness as H
from futures.basket import SWING_TF_PARAM
from futures.swing_tf import basket_labels, load_basket, costs_for_basket
labels = basket_labels("spy_daily_live.csv")
bas = load_basket("data/cache/futures/frozen_sim"); COSTS = costs_for_basket(2.0)
cut = pd.Timestamp("2024-12-31"); ARM = H.ARM_LIVE
DFS = {s: d[d.index <= cut.tz_localize(d.index.tz)] for s, d in bas.items()}
EMA = SWING_TF_PARAM["ema_period"]; MULT = SWING_TF_PARAM["chandelier_atr_mult"]


def qua_harness(cfg):
    ra = {}
    for sym, df in DFS.items():
        stat = {"n": 0, "tot": 0.0}
        _orig, fn = H.patched_engine(cfg, stat)
        tr = fn(df, labels, COSTS[sym], ema_period=EMA,
                chandelier_atr_mult=MULT, max_hold_days=5)
        cache, datr = H._cache(df)
        d = []
        for t in tr:
            if t["reason"] != "CHANDELIER":
                continue
            day = pd.Timestamp(t["day"]).normalize()
            a = float(datr.asof(day)) if len(datr) else np.nan
            if np.isfinite(a) and a > 0:
                d.append(abs(float(t["entry"]) - float(t["exit"])) / a)   # theo ATR ngay
        ra[sym] = np.array(d)
        H._CACHE.clear()
    return ra


print("chay qua patched_engine ...")
G = qua_harness(H.Cfg(arm_hours=ARM, ratchet=False, roska4_only=False))
S = qua_harness(H.Cfg(arm_hours=ARM, ratchet=False, roska4_only=False, stop_basis=1.0))

print("\n" + "=" * 74)
print("BT5 qua duong harness — khoang cach stop do bang BOI SO cua ATR NGAY")
print("=" * 74)
print("  {:<5} {:>22} {:>26}".format("", "cau hinh goc", "stop_basis=1.0"))
for sym in DFS:
    g, s = G[sym], S[sym]
    print("  {:<5}  n={:<4} trung vi {:.3f}   |  n={:<4} trung vi {:.3f}  | %con o muc hep(<0.3) {:.0%}"
          .format(sym, len(g), float(np.median(g)) if len(g) else float("nan"),
                  len(s), float(np.median(s)) if len(s) else float("nan"),
                  float((s < 0.3).mean()) if len(s) else float("nan")))
gg = np.concatenate([G[s] for s in G]); ss = np.concatenate([S[s] for s in S])
print("\n  GOC     : n={} trung vi {:.3f} x ATR ngay".format(len(gg), float(np.median(gg))))
print("  BASIS1.0: n={} trung vi {:.3f} x ATR ngay".format(len(ss), float(np.median(ss))))
print("  ty le rong: {:.1f}x   {}".format(
    float(np.median(ss) / np.median(gg)),
    "DAT (co tac dung)" if np.median(ss) / np.median(gg) > 3 else "!! stop_basis khong toi noi"))
print("  con o muc HEP cu (<0.3 x ATR ngay) khi bat basis: {:.0%}  {}".format(
    float((ss < 0.3).mean()),
    "DAT" if (ss < 0.3).mean() < 0.15 else "!! nhanh quet sinh lai KHONG nhan stop moi"))
