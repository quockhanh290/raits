"""Neu BIET no quay ve thi HUY stop chu khong phai thoat tai stop. — CHI DOC.

Lan truoc toi do nhanh "giu" nhung VAN de lenh stop nam do, nen khi gia quay ve thi cham
stop va bi cat — chan tran phan loi cua chinh phuong an dang kiem. Sai.

Lan nay ba nhanh, cho nhom C (tai moc vu trang gia da o ben kia muc stop):
  A. CAT ngay tai gia thi truong luc vu trang            (he dang lam)
  B. GIU, van de stop -> thoat khi quay ve cham stop      (phep do sai cua lan truoc)
  C. HUY STOP, giu toi tran 5 ngay                        (dung y de xuat)

Va TRAN CUA MOI BO DU DOAN: biet truoc hoan hao, moi lenh chon max(A, C).
Neu tran do khong hon A bao nhieu thi ca huong "tim chi bao" khong dang di, bat ke
du doan gioi den may.

    python scratch/hold_no_stop.py
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
            if not ((px_arm < stp) if LONG else (px_arm > stp)):
                continue
            try:
                da = float(datr.asof(d0))
            except Exception:
                continue
            if not np.isfinite(da) or da <= 0:
                continue
            depth = ((stp - px_arm) if LONG else (px_arm - stp)) / da

            t_arm = pd.Timestamp(naive[j])
            t_max = d0 + pd.Timedelta(days=MAXHOLD)

            # A. cat ngay
            A = ((px_arm - entry) if LONG else (entry - px_arm)) * pv - rt

            # B. giu, VAN de stop
            segh = FH[(FH.index > t_arm) & (FH.index < t_max)]
            segl = FL[(FL.index > t_arm) & (FL.index < t_max)]
            back = (segh[segh >= stp] if LONG else segl[segl <= stp])
            nxt = FO[FO.index >= t_max]
            if not len(nxt):
                continue
            px_end = float(nxt.iloc[0])
            if len(back):
                B = ((stp - entry) if LONG else (entry - stp)) * pv - rt
            else:
                B = ((px_end - entry) if LONG else (entry - px_end)) * pv - rt

            # C. HUY STOP, giu toi tran
            C = ((px_end - entry) if LONG else (entry - px_end)) * pv - rt

            rows.append(dict(inst=k, ngay=str(d0.date()), depth=depth,
                             A=A, B=B, C=C, oracle=max(A, C),
                             C_lai=1 if C > 0 else 0,
                             C_hon_A=1 if C > A else 0))
        print("  {} xong".format(k), flush=True)

    R = pd.DataFrame(rows)
    R.to_csv("scratch/hold_no_stop.csv", index=False)
    n = len(R)
    print("\n" + "=" * 92)
    print("NHOM C — BA CACH XU LY TAI MOC VU TRANG")
    print("=" * 92)
    print("  {} lenh | {} ngay".format(n, R.ngay.nunique()))
    print("  A. CAT ngay tai gia thi truong          : ${:>10,.0f}".format(R.A.sum()))
    print("  B. GIU, van de stop (phep do cu, SAI)   : ${:>10,.0f}".format(R.B.sum()))
    print("  C. HUY STOP, giu toi tran 5 ngay        : ${:>10,.0f}".format(R.C.sum()))
    print("  -" * 40)
    print("  TRAN: biet truoc hoan hao, moi lenh chon max(A,C) : ${:>10,.0f}"
          .format(R.oracle.sum()))
    print("  => tran cao hon 'cat het' {:+,.0f}  ({} lenh nen giu = {:.0f}%)"
          .format(R.oracle.sum() - R.A.sum(), int(R.C_hon_A.sum()),
                  R.C_hon_A.mean() * 100))
    print("\n  so lenh ma HUY STOP cho ra LAI: {} ({:.1f}%)".format(int(R.C_lai.sum()),
                                                                    R.C_lai.mean() * 100))

    print("\n=== THEO DO SAU TAI MOC VU TRANG ===")
    bins = [-1, .05, .1, .2, .4, 100]
    lbl = ["<0.05", "0.05-0.1", "0.1-0.2", "0.2-0.4", ">0.4"]
    R["b"] = pd.cut(R.depth, bins=bins, labels=lbl)
    print("  {:<11} {:>5} {:>11} {:>11} {:>11} {:>9} {:>9}".format(
        "do sau", "n", "A cat", "C huy stop", "tran", "%C>A", "%C lai"))
    for b in lbl:
        s = R[R.b == b]
        if len(s) < 10:
            continue
        print("  {:<11} {:>5} {:>11,.0f} {:>11,.0f} {:>11,.0f} {:>8.0f}% {:>8.0f}%"
              .format(b, len(s), s.A.sum(), s.C.sum(), s.oracle.sum(),
                      s.C_hon_A.mean() * 100, s.C_lai.mean() * 100))

    print("\n=== TRUNG BINH MOI LENH ===")
    print("  cat ${:,.0f} | huy stop ${:,.0f} | tran ${:,.0f}"
          .format(R.A.mean(), R.C.mean(), R.oracle.mean()))
    print("\n  LUU Y: van chua tinh chi phi chiem cho.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
