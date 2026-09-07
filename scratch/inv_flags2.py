"""BT5 o MUC LENH (bat duoc loi ghi de tin hieu), va truy 17 lenh disaster sai muc."""
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
cut = pd.Timestamp("2024-12-31"); ARM = H.ARM_LIVE; ALLOWED = set(c["allowed_regimes"])
DFS = {s: d[d.index <= cut.tz_localize(d.index.tz)] for s, d in bas.items()}
X = 1.0; K = 3.0


def mot_lan(sym, df, cfg, dm=None):
    """Chay dung duong harness: boc generate_signal neu co stop_basis."""
    cache, datr = H._cache(df)
    s = base
    if cfg.stop_basis is not None:
        _o = base.generate_signal
        def _gs(*a, _o=_o, _d=datr, _f=cfg.stop_basis, **k):
            sg = _o(*a, **k)
            if not sg:
                return sg
            try:
                da = float(_d.asof(pd.Timestamp(a[0].index[-1]).normalize()))
            except Exception:
                return sg
            if not np.isfinite(da) or da <= 0:
                return sg
            sg = dict(sg); ep = float(sg["entry_price"])
            sg["initial_stop"] = (ep - _f * da) if sg["direction"] == "LONG" else (ep + _f * da)
            return sg
        import copy
        s = copy.copy(base); s.generate_signal = _gs
    sg = H._make_sig(cache, datr, labels, s, ema, ALLOWED, cfg, True)
    tr, _ = run_loop(df, labels, COSTS[sym], strat=s, ema_period=ema,
                     mult=SWING_TF_PARAM["chandelier_atr_mult"], max_hold_days=5,
                     cache=cache, same_day_stop=False, stop_slip_ticks=0.0,
                     activate_after_h=0.0, sig_cache=sg,
                     stop_active_hour=ARM, ratchet=False, disaster_mult=dm)
    return tr, sg, datr, cache


print("BT5 o MUC LENH — gia thoat CHANDELIER phai o vao -+ {:g} x ATR ngay".format(X))
for nhan, cfg in (("stop_basis=1.0", H.Cfg(stop_basis=X, arm_hours=ARM, ratchet=False)),
                  ("DOI CHUNG goc ", H.Cfg(arm_hours=ARM, ratchet=False))):
    n = vi = 0
    for sym, df in DFS.items():
        tr, sg, datr, _ = mot_lan(sym, df, cfg)
        for t in tr:
            if t["reason"] != "CHANDELIER":
                continue
            day = pd.Timestamp(t["day"]).normalize()
            a = float(datr.asof(day)) if len(datr) else np.nan
            if not np.isfinite(a) or a <= 0:
                continue
            _s = sg.get(day)
            if _s is None:
                continue
            n += 1
            muc = float(_s[1]["initial_stop"])
            if abs(float(t["exit"]) - muc) > 0.02:
                vi += 1
        H._CACHE.clear()
    kq = ("DAT" if (n and vi == 0) else "MAU RONG" if not n else "!! KHONG DAT") \
        if "DOI" not in nhan else ("DAT (phep kiem song)" if vi else "!! phep kiem HONG")
    print("  {} : {:>5}/{:<5} vi pham  {}".format(nhan, vi, n, kq))

