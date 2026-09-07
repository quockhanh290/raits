"""Phep sua khop lenh cua toi co DAY DU khong? — CHI DOC.

Luat dung phai la: neu bar MO o ben kia muc stop thi khong khop duoc tai muc stop, BAT KE
co khe ho thoi gian hay khong. Hien engine khoa luat do sau co `isg`.

Phep sua hau ky cua toi CHI cham lenh thoat tai dung bar vu trang. Neu con truong hop khac
— bar mo o ben kia muc stop nhung khong phai bar vu trang — thi con so hieu chinh cua toi
THIEU, va moi thu dung tren no lech theo.

Duyet MOI lenh thoat, tach ba nhom:
  1. bar thoat mo o ben kia muc stop, VA la bar vu trang      -> phep sua da cham
  2. bar thoat mo o ben kia muc stop, KHONG phai bar vu trang -> phep sua BO SOT
  3. nhan GAP (engine da tu khop tai gia mo)                  -> khong lien quan

Chay cho ca hai quy uoc.

    python scratch/correction_complete.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, r"d:\raits\scratch")

import harness as H

ARM = H.ARM_LIVE


def main() -> int:
    from futures.basket import SWING_TF_PARAM, BASKET
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import backtest_swing_tf
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache, run_loop

    ema = SWING_TF_PARAM["ema_period"]
    mult = SWING_TF_PARAM["chandelier_atr_mult"]
    hold = SWING_TF_PARAM["max_hold_days"]
    cfg = dict(TrendFollowStrategy().config)
    cfg["ema_period"] = ema
    cfg["chandelier_atr_mult"] = mult
    strat = TrendFollowStrategy(cfg)

    dfs = load_basket("data/cache/futures/frozen_sim")
    cut = pd.Timestamp("2024-12-31")
    for k in list(dfs):
        df = dfs[k]
        c = cut.tz_localize(df.index.tz) if df.index.tz is not None else cut
        dfs[k] = df[df.index <= c]
    labels = basket_labels("spy_daily_live.csv")
    costs = costs_for_basket(slippage_ticks=2.0)

    for nhan, H_arm in (("QUY UOC ENGINE (vu trang ranh gioi ngay)", 0.0),
                        ("LUAT LIVE (vu trang D+1 14:05, stop co dinh)", ARM)):
        n_all = 0
        g1 = g2 = g3 = 0
        s1 = s2 = 0.0
        vidu = []
        for k in dfs:
            df = dfs[k]
            cache, _ = H._cache(df)
            if H_arm == 0.0:
                tr = backtest_swing_tf(df, labels, costs[k], ema_period=ema,
                                       chandelier_atr_mult=mult, max_hold_days=hold)
            else:
                sig = build_sig_cache(cache, labels, strat, ema,
                                      set(cfg["allowed_regimes"]))
                tr, _ = run_loop(df, labels, costs[k], strat=strat, ema_period=ema,
                                 mult=mult, max_hold_days=hold, cache=cache,
                                 same_day_stop=False, stop_slip_ticks=0.0,
                                 sig_cache=sig, stop_active_hour=ARM, ratchet=False)
            ts, hl = cache.get("ts", {}), cache["hl"]
            pv = BASKET[k].point_value
            for t in tr:
                n_all += 1
                if t["reason"] == "GAP":
                    g3 += 1
                    continue
                if t["reason"] != "CHANDELIER":
                    continue
                et = t.get("exit_time")
                if et is None:
                    continue
                et = pd.Timestamp(et)
                if et.tzinfo is not None:
                    et = et.tz_localize(None)
                d1 = pd.Timestamp(t["exit_day"]).normalize()
                dts = ts.get(d1)
                if dts is None or not len(dts):
                    continue
                nv = dts.tz_localize(None) if dts.tz is not None else dts
                arr = np.asarray(nv)
                i = int(np.searchsorted(arr, np.datetime64(et)))
                if i >= len(arr) or pd.Timestamp(arr[i]) != et:
                    continue
                op = float(hl[d1][2][i])
                stp = float(t["exit"])
                w = (stp - op) if t["direction"] == "LONG" else (op - stp)
                if w <= 0:
                    continue                      # gia mo chua vuot -> khop tai stop hop ly
                d0 = pd.Timestamp(t["day"]).normalize()
                arm_at = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=H_arm)
                j = int(np.searchsorted(arr, np.datetime64(arm_at)))
                la_bar_vu_trang = (d1 == d0 + pd.Timedelta(days=1)
                                   and j < len(arr) and pd.Timestamp(arr[j]) == et)
                if la_bar_vu_trang:
                    g1 += 1
                    s1 += w * pv
                else:
                    g2 += 1
                    s2 += w * pv
                    if len(vidu) < 6:
                        vidu.append((k, str(d0.date()), str(d1.date()), t["direction"],
                                     round(stp, 2), round(op, 2), round(w * pv, 2),
                                     str(et.time()), t["hold_days"]))
        print("\n" + "=" * 88)
        print(nhan)
        print("=" * 88)
        print("  tong lenh {}".format(n_all))
        print("  1. bar mo vuot muc stop VA la bar vu trang   : {:>5} lenh  ${:>10,.0f}"
              .format(g1, s1))
        print("  2. bar mo vuot muc stop, KHONG phai bar vu trang: {:>3} lenh  ${:>10,.0f}"
              .format(g2, s2))
        print("  3. nhan GAP (engine da khop tai gia mo)      : {:>5} lenh".format(g3))
        tong = s1 + s2
        print("\n  -> phep sua cua toi cham nhom 1: ${:,.0f}".format(s1))
        print("  -> BO SOT nhom 2               : ${:,.0f}  ({:.1f}% cua tong {:,.0f})"
              .format(s2, s2 / tong * 100 if tong else 0, tong))
        if vidu:
            print("\n  vi du nhom BO SOT:")
            for v in vidu:
                print("    {} vao {} thoat {} {} | stop {} | gia mo {} | lech ${} | luc {} | giu {} ngay"
                      .format(*v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
