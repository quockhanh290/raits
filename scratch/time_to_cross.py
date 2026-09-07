"""Sau bao lau tu luc vao lenh thi gia da di qua muc stop tinh luc vao lenh? — CHI DOC.

Muc dich: cua so hoan hien nay (D+1 14:00 tren dong ho sleeve) duoc chon bang P&L backtest,
tren thuoc do co loi khop lenh. Mot tieu chi KHONG dua vao P&L: dat stop TRUOC khi gia
thuong di qua muc do. Muon dung tieu chi ay thi phai biet phan bo thoi gian toi luc cham.

Do: voi moi lenh, tinh so gio tu entry_time toi bar DAU TIEN gia cham muc stop ban dau
(sig["initial_stop"], = dung muc live ghi so). ratchet=False cho khop luat live.

LUU Y KHUNG: "14h" la tinh tu NUA DEM, khong phai tu luc vao lenh. Vao lenh 14:00-15:55
ngay D, vu trang D+1 14:00 -> quang tran thuc te 22-24 gio. Quy uoc engine (vu trang nua
dem) -> 8-10 gio. Bang duoi tinh theo GIO TU LUC VAO LENH.

    python scratch/time_to_cross.py --data-dir data/cache/futures/frozen_sim
        --regime-csv spy_daily_live.csv --end 2024-12-31
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    a = ap.parse_args()

    from futures.basket import SWING_TF_PARAM
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, daily_atr_series
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache, run_loop

    ema = SWING_TF_PARAM["ema_period"]
    mult = SWING_TF_PARAM["chandelier_atr_mult"]
    hold = SWING_TF_PARAM["max_hold_days"]
    base = dict(TrendFollowStrategy().config)
    base["ema_period"] = ema
    base["chandelier_atr_mult"] = mult
    strat = TrendFollowStrategy(dict(base))
    allowed = set(base["allowed_regimes"])

    dfs = load_basket(a.data_dir)
    cut = pd.Timestamp(a.end)
    for k in list(dfs):
        df = dfs[k]
        c = cut.tz_localize(df.index.tz) if df.index.tz is not None else cut
        dfs[k] = df[df.index <= c]
    labels = basket_labels(a.regime_csv)
    costs = costs_for_basket(slippage_ticks=a.slippage_ticks)

    recs = []
    for k in dfs:
        df = dfs[k]
        cache = _swing_cache(df, daily_atr_series(df))
        sig = build_sig_cache(cache, labels, strat, ema, allowed)
        # chay voi cua so hoan RAT DAI de moi lenh song du lau ma quan sat
        tr, _ = run_loop(df, labels, costs[k], strat=strat, ema_period=ema, mult=mult,
                         max_hold_days=hold, cache=cache, same_day_stop=False,
                         stop_slip_ticks=0.0, sig_cache=sig, stop_active_hour=10_000.0,
                         ratchet=False)
        ts, hl = cache.get("ts", {}), cache["hl"]
        for t in tr:
            d0 = pd.Timestamp(t["day"]).normalize()
            hit = sig.get(d0)
            if hit is None:
                continue
            stp = float(hit[1]["initial_stop"])
            ent = pd.Timestamp(t["entry_time"])
            if ent.tzinfo is not None:
                ent = ent.tz_localize(None)
            xd = pd.Timestamp(t["exit_day"]).normalize()
            cross_at = None
            cur = d0
            while cur <= xd and cross_at is None:
                dts = ts.get(cur)
                if dts is not None and len(dts):
                    naive = dts.tz_localize(None) if dts.tz is not None else dts
                    arr = np.asarray(naive)
                    m = arr > np.datetime64(ent)
                    if m.any():
                        w = np.where(m)[0]
                        if t["direction"] == "LONG":
                            c = np.where(hl[cur][1][w] <= stp)[0]
                        else:
                            c = np.where(hl[cur][0][w] >= stp)[0]
                        if len(c):
                            cross_at = pd.Timestamp(naive[w[c[0]]])
                cur = cur + pd.Timedelta(days=1)
            recs.append(dict(inst=k, dir=t["direction"], reason=t["reason"],
                             pnl=t["pnl"],
                             hours=((cross_at - ent).total_seconds() / 3600.0
                                    if cross_at is not None else np.nan)))
        print("  {} xong".format(k))

    R = pd.DataFrame(recs)
    n = len(R)
    cr = R[R.hours.notna()]
    print("\n" + "=" * 84)
    print("THOI GIAN TU LUC VAO LENH TOI LAN DAU GIA CHAM MUC STOP BAN DAU")
    print("=" * 84)
    print("  tong {} lenh | co cham: {} ({:.1f}%) | khong bao gio cham: {} ({:.1f}%)"
          .format(n, len(cr), len(cr) / n * 100, n - len(cr), (n - len(cr)) / n * 100))
    if len(cr):
        q = cr.hours.quantile([.1, .25, .5, .75, .9]).round(2)
        print("  gio toi luc cham — p10 {} | p25 {} | trung vi {} | p75 {} | p90 {}"
              .format(q[.1], q[.25], q[.5], q[.75], q[.9]))

    print("\n=== NEU DAT STOP SAU N GIO KE TU LUC VAO LENH ===")
    print("  {:>8} | {:>28} | {:>24}".format(
        "N gio", "% lenh DA cham truoc do", "so lenh"))
    for h in (0.5, 1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 22, 24, 30):
        share = (cr.hours <= h).sum() / n * 100
        print("  {:>8} | {:>27.1f}% | {:>24}".format(h, share, int((cr.hours <= h).sum())))

    print("\n  moc dang dung:")
    print("    quy uoc engine  = vu trang nua dem  -> 8-10 gio ke tu vao lenh")
    print("    luat live       = vu trang D+1 14h  -> 22-24 gio ke tu vao lenh")

    print("\n=== TACH THEO KET CUC ===")
    for rs in sorted(R.reason.unique()):
        s = R[R.reason == rs]
        sc = s[s.hours.notna()]
        print("  {:<12} {:>5} lenh | co cham {:>5.1f}% | trung vi gio {:>6}"
              .format(rs, len(s), len(sc) / max(len(s), 1) * 100,
                      round(sc.hours.median(), 2) if len(sc) else "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
