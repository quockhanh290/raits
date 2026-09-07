"""Tai moc vu trang, neu gia DA o ben kia muc stop: cat hay giu? — CHI DOC.

Hien nay nhom do bi cat sach (636/642 thoat ngay tai moc vu trang). Chua ai do phan thuc:
neu KHONG cat thi sao?

Phan thuc cho tung lenh nhom C:
  - giu tiep voi muc stop VAN o cho cu
  - thoat khi gia quay ve cham muc stop  (luc do lenh co that tren san -> khop trung thuc)
  - hoac thoat tai TRAN 5 ngay (gia mo bar dau ngay thoat)
So voi: cat ngay tai gia thi truong luc vu trang (mo hinh trung thuc hien tai).

Tach theo DO SAU tai moc vu trang — vi de xuat la ra quyet dinh dua tren gia da di bao xa
trong quang tran.

HAN CHE PHAI GHI: phan thuc nay KHONG tinh chi phi chiem cho — giu lenh lau hon thi chan
lenh moi vao. Muon tinh ca cai do phai chay lai ca vong lap.

    python scratch/hold_vs_cut.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

ARM = 14 + 5 / 60
MAXHOLD = 5


def main() -> int:
    from futures.basket import SWING_TF_PARAM, BASKET
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, daily_atr_series
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache, run_loop

    ema = SWING_TF_PARAM["ema_period"]
    mult = SWING_TF_PARAM["chandelier_atr_mult"]
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

    rows = []
    for k in dfs:
        df = dfs[k]
        datr = daily_atr_series(df)
        cache = _swing_cache(df, datr)
        sig = build_sig_cache(cache, labels, strat, ema, set(cfg["allowed_regimes"]))
        tr, _ = run_loop(df, labels, costs[k], strat=strat, ema_period=ema, mult=mult,
                         max_hold_days=MAXHOLD, cache=cache, same_day_stop=False,
                         stop_slip_ticks=0.0, sig_cache=sig, stop_active_hour=ARM,
                         ratchet=False)
        ts, hl = cache.get("ts", {}), cache["hl"]
        pv = BASKET[k].point_value
        rt = costs[k].round_turn_cost()
        idx = df.index.tz_convert("America/New_York").tz_localize(None)
        FH = pd.Series(df["high"].to_numpy(), index=idx)
        FL = pd.Series(df["low"].to_numpy(), index=idx)
        FO = pd.Series(df["open"].to_numpy(), index=idx)
        for s_ in (FH, FL, FO):
            s_.drop_duplicates()
        FH = FH[~FH.index.duplicated(keep="last")]
        FL = FL[~FL.index.duplicated(keep="last")]
        FO = FO[~FO.index.duplicated(keep="last")]

        for t in tr:
            d0 = pd.Timestamp(t["day"]).normalize()
            hit = sig.get(d0)
            if hit is None:
                continue
            stp = float(hit[1]["initial_stop"])
            entry = float(t["entry"])
            LONG = t["direction"] == "LONG"
            arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=ARM)
            d1 = arm.normalize()
            dts = ts.get(d1)
            if dts is None or not len(dts):
                continue
            naive = dts.tz_localize(None) if dts.tz is not None else dts
            j = int(np.searchsorted(np.asarray(naive), np.datetime64(arm)))
            if j >= len(naive):
                continue
            px_arm = float(hl[d1][2][j])
            past = (px_arm < stp) if LONG else (px_arm > stp)
            if not past:
                continue                     # khong thuoc nhom C

            try:
                da = float(datr.asof(d0))
            except Exception:
                continue
            if not np.isfinite(da) or da <= 0:
                continue
            depth = ((stp - px_arm) if LONG else (px_arm - stp)) / da

            # A. CAT NGAY tai gia thi truong luc vu trang
            pnl_cut = ((px_arm - entry) if LONG else (entry - px_arm)) * pv - rt

            # B. GIU TIEP: thoat khi quay ve cham stop, hoac tai tran 5 ngay
            t_arm = pd.Timestamp(naive[j])
            t_max = d0 + pd.Timedelta(days=MAXHOLD)
            seg_h = FH[(FH.index > t_arm) & (FH.index < t_max)]
            seg_l = FL[(FL.index > t_arm) & (FL.index < t_max)]
            back = None
            if LONG:
                c2 = seg_h[seg_h >= stp]
            else:
                c2 = seg_l[seg_l <= stp]
            if len(c2):
                back = c2.index[0]
            if back is not None:
                pnl_hold = ((stp - entry) if LONG else (entry - stp)) * pv - rt
                ket = "quay ve cham stop"
            else:
                nxt = FO[FO.index >= t_max]
                if not len(nxt):
                    continue
                px_end = float(nxt.iloc[0])
                pnl_hold = ((px_end - entry) if LONG else (entry - px_end)) * pv - rt
                ket = "chay toi tran 5 ngay"
            rows.append(dict(inst=k, ngay=str(d0.date()), depth=depth,
                             pnl_cut=pnl_cut, pnl_hold=pnl_hold, ket=ket))
        print("  {} xong".format(k), flush=True)

    R = pd.DataFrame(rows)
    print("\n" + "=" * 96)
    print("NHOM C: TAI MOC VU TRANG DA O BEN KIA MUC STOP — CAT hay GIU?")
    print("=" * 96)
    print("  {} lenh | {} ngay".format(len(R), R.ngay.nunique()))
    print("  CAT ngay tai gia thi truong : ${:>10,.0f}".format(R.pnl_cut.sum()))
    print("  GIU tiep                    : ${:>10,.0f}".format(R.pnl_hold.sum()))
    print("  chenh (giu - cat)           : ${:>+10,.0f}".format(R.pnl_hold.sum() - R.pnl_cut.sum()))
    print("\n  ket cuc khi giu: {}".format(R.ket.value_counts().to_dict()))
    print("  ty le quay ve cham stop: {:.1f}%".format((R.ket == "quay ve cham stop").mean() * 100))

    print("\n=== THEO DO SAU TAI MOC VU TRANG (don vi ATR ngay) ===")
    bins = [-1, .02, .05, .1, .2, .4, 100]
    lbl = ["<0.02", "0.02-0.05", "0.05-0.1", "0.1-0.2", "0.2-0.4", ">0.4"]
    R["b"] = pd.cut(R.depth, bins=bins, labels=lbl)
    print("  {:<12} {:>5} {:>12} {:>12} {:>12} {:>10}".format(
        "do sau", "n", "CAT", "GIU", "chenh", "% ve stop"))
    for b in lbl:
        s = R[R.b == b]
        if len(s) < 10:
            continue
        print("  {:<12} {:>5} {:>12,.0f} {:>12,.0f} {:>+12,.0f} {:>9.0f}%"
              .format(b, len(s), s.pnl_cut.sum(), s.pnl_hold.sum(),
                      s.pnl_hold.sum() - s.pnl_cut.sum(),
                      (s.ket == "quay ve cham stop").mean() * 100))

    print("\n=== TRUNG BINH MOI LENH ===")
    for b in lbl:
        s = R[R.b == b]
        if len(s) < 10:
            continue
        print("  {:<12} n={:<4} cat ${:>8,.0f}/lenh | giu ${:>8,.0f}/lenh"
              .format(b, len(s), s.pnl_cut.mean(), s.pnl_hold.mean()))
    print("\n  LUU Y: phan thuc nay KHONG tinh chi phi chiem cho (giu lau hon chan lenh moi).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
