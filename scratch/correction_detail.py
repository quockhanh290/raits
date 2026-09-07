"""Bang chi tiet TUNG LENH bi hieu chinh — de soi lai bang mat. CHI DOC.

Hai quy uoc:
  engine : backtest_swing_tf nguyen ban, vu trang tai ranh gioi ngay (H=0)
  live   : run_loop, vu trang D+1 14:05, stop co dinh (ratchet=False)

Moi dong: gia vao, muc stop (= gia engine ghi thoat), thoi diem vu trang, GIA THI TRUONG
tai thoi diem do, khoang cach, tien hieu chinh, P&L truoc/sau.

TU KIEM: tong phai khop so da bao — engine 591 lenh/$38,904 ; live 645 lenh/$99,502.

    python scratch/correction_detail.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

ARM_LIVE = 14 + 5 / 60
EXPECT = {"engine": (591, 38904.0), "live": (645, 99502.0)}


def main() -> int:
    from futures.basket import SWING_TF_PARAM, BASKET
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, daily_atr_series, backtest_swing_tf
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

    caches, sigs = {}, {}
    for k in dfs:
        caches[k] = _swing_cache(dfs[k], daily_atr_series(dfs[k]))
        sigs[k] = build_sig_cache(caches[k], labels, strat, ema,
                                  set(cfg["allowed_regimes"]))

    for mode in ("engine", "live"):
        H = 0.0 if mode == "engine" else ARM_LIVE
        rows = []
        n_all = 0
        pnl_all = 0.0
        for k in dfs:
            if mode == "engine":
                tr = backtest_swing_tf(dfs[k], labels, costs[k], ema_period=ema,
                                       chandelier_atr_mult=mult, max_hold_days=hold)
            else:
                tr, _ = run_loop(dfs[k], labels, costs[k], strat=strat, ema_period=ema,
                                 mult=mult, max_hold_days=hold, cache=caches[k],
                                 same_day_stop=False, stop_slip_ticks=0.0,
                                 sig_cache=sigs[k], stop_active_hour=H, ratchet=False)
            cache = caches[k]
            ts, hl = cache.get("ts", {}), cache["hl"]
            pv = BASKET[k].point_value
            for t in tr:
                n_all += 1
                pnl_all += t["pnl"]
                if t["reason"] != "CHANDELIER":
                    continue
                d0 = pd.Timestamp(t["day"]).normalize()
                d1 = pd.Timestamp(t["exit_day"]).normalize()
                if d1 != d0 + pd.Timedelta(days=1):
                    continue
                dts = ts.get(d1)
                if dts is None or not len(dts):
                    continue
                naive = dts.tz_localize(None) if dts.tz is not None else dts
                arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=H)
                j = int(np.searchsorted(np.asarray(naive), np.datetime64(arm)))
                if j >= len(naive):
                    continue
                et = pd.Timestamp(t["exit_time"])
                if et.tzinfo is not None:
                    et = et.tz_localize(None)
                if et != pd.Timestamp(naive[j]):
                    continue
                op = float(hl[d1][2][j])
                stp = float(t["exit"])
                w = (stp - op) if t["direction"] == "LONG" else (op - stp)
                if w <= 0:
                    continue
                rows.append(dict(
                    inst=k, ngay_vao=str(d0.date()), huong=t["direction"],
                    gia_vao=t["entry"], muc_stop=stp,
                    luc_vu_trang=str(pd.Timestamp(naive[j])),
                    gia_thi_truong=round(op, 2),
                    lech_diem=round(w, 2), lech_usd=round(w * pv, 2),
                    pnl_engine=t["pnl"], pnl_dung=round(t["pnl"] - w * pv, 2)))

        R = pd.DataFrame(rows).sort_values("lech_usd", ascending=False)
        out = "scratch/correction_detail_{}.csv".format(mode)
        R.to_csv(out, index=False)

        print("\n" + "=" * 108)
        print("QUY UOC {}   (vu trang {})".format(
            mode.upper(), "ranh gioi ngay" if H == 0 else "D+1 14:05"))
        print("=" * 108)
        exp_n, exp_t = EXPECT[mode]
        ok_n = len(R) == exp_n
        ok_t = abs(R.lech_usd.sum() - exp_t) < 5
        print("  tong lenh {} | P&L engine ${:,.0f}".format(n_all, pnl_all))
        print("  so lenh bi hieu chinh {}  (da bao {})  -> {}".format(
            len(R), exp_n, "KHOP" if ok_n else "LECH"))
        print("  tong hieu chinh ${:,.0f}  (da bao ${:,.0f})  -> {}".format(
            R.lech_usd.sum(), exp_t, "KHOP" if ok_t else "LECH"))
        print("  P&L sau hieu chinh ${:,.0f}".format(pnl_all - R.lech_usd.sum()))
        print("  da ghi: {}".format(out))

        print("\n  --- 15 lenh lech NHIEU nhat ---")
        print("  {:<5} {:<11} {:<6} {:>10} {:>10} {:>10} {:>8} {:>9} {:>10} {:>10}".format(
            "ma", "ngay vao", "huong", "gia vao", "muc stop", "gia t.truong",
            "lech d", "lech $", "P&L engine", "P&L dung"))
        for _, r in R.head(15).iterrows():
            print("  {:<5} {:<11} {:<6} {:>10.2f} {:>10.2f} {:>10.2f} {:>8.2f} "
                  "{:>9,.0f} {:>10,.2f} {:>10,.2f}".format(
                      r.inst, r.ngay_vao, r.huong, r.gia_vao, r.muc_stop,
                      r.gia_thi_truong, r.lech_diem, r.lech_usd, r.pnl_engine, r.pnl_dung))

        print("\n  --- 10 lenh lech IT nhat (de thay phep sua khong bat bua) ---")
        for _, r in R.tail(10).iterrows():
            print("  {:<5} {:<11} {:<6} {:>10.2f} {:>10.2f} {:>10.2f} {:>8.2f} "
                  "{:>9,.0f} {:>10,.2f} {:>10,.2f}".format(
                      r.inst, r.ngay_vao, r.huong, r.gia_vao, r.muc_stop,
                      r.gia_thi_truong, r.lech_diem, r.lech_usd, r.pnl_engine, r.pnl_dung))

        print("\n  --- phan bo lech ---")
        q = R.lech_usd.quantile([.25, .5, .75, .9, .99]).round(0)
        print("    p25 ${:,.0f} | trung vi ${:,.0f} | p75 ${:,.0f} | p90 ${:,.0f} | p99 ${:,.0f}"
              .format(q[.25], q[.5], q[.75], q[.9], q[.99]))
        print("    so lenh lech duoi $50: {} ({:.0f}%)".format(
            int((R.lech_usd < 50).sum()), (R.lech_usd < 50).mean() * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
