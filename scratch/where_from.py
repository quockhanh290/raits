"""Muc stop cua MOT lenh duoc tinh tu dau? — CHI DOC.

In ra tung thanh phan: gia vao, ATR 5 phut tai bar vao lenh, ATR NGAY hom do, muc stop
engine dat, ty le giua khoang cach stop va bien do mot ngay, roi duong gia tu luc vao lenh
toi luc engine ghi thoat.

    python scratch/where_from.py --inst MNQ --date 2022-05-12
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
    ap.add_argument("--inst", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    a = ap.parse_args()

    from futures.basket import SWING_TF_PARAM, BASKET
    from futures.swing_tf import basket_labels, load_basket
    from futures._validated_core import _swing_cache, daily_atr_series, atr14
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache

    ema = SWING_TF_PARAM["ema_period"]
    mult = SWING_TF_PARAM["chandelier_atr_mult"]
    cfg = dict(TrendFollowStrategy().config)
    cfg["ema_period"] = ema
    cfg["chandelier_atr_mult"] = mult
    strat = TrendFollowStrategy(cfg)

    df = load_basket(a.data_dir)[a.inst]
    datr = daily_atr_series(df)
    cache = _swing_cache(df, datr)
    labels = basket_labels(a.regime_csv)
    sig = build_sig_cache(cache, labels, strat, ema, set(cfg["allowed_regimes"]))

    day = pd.Timestamp(a.date).normalize()
    hit = sig.get(day)
    if hit is None:
        print("khong co tin hieu vao lenh ngay {}".format(a.date))
        return 1
    bar_ts, sg = hit

    b5 = cache["b5"][day]
    hist = b5.loc[:bar_ts]
    atr5 = float(atr14(hist))
    da = float(datr.asof(day))
    entry = float(sg["entry_price"])
    stop = float(sg["initial_stop"])
    dist = abs(entry - stop)

    print("\n=== {} — lenh vao ngay {} ===".format(a.inst, day.date()))
    print("  huong          : {}".format(sg["direction"]))
    print("  bar vao lenh   : {}".format(bar_ts))
    print("  gia vao        : {:.2f}".format(entry))
    print("\n  --- muc stop duoc tinh tu dau ---")
    print("  ATR14 tren bar 5 PHUT tai luc vao lenh : {:.2f} diem".format(atr5))
    print("  he so chandelier_atr_mult              : {}".format(mult))
    print("  khoang cach stop = {} x {:.2f}          = {:.2f} diem".format(mult, atr5, dist))
    print("  => muc stop = {:.2f} {} {:.2f} = {:.2f}"
          .format(entry, "+" if sg["direction"] == "SHORT" else "-", dist, stop))
    print("  (khop voi so engine ghi: {:.2f})".format(stop))

    print("\n  --- so voi nhip NGAY, la nhip ma lenh nay thuc su song ---")
    print("  ATR14 tren bar NGAY hom do : {:.2f} diem".format(da))
    print("  dai chandelier danh nghia  = {} x {:.2f} = {:.2f} diem".format(mult, da, mult * da))
    print("  khoang cach stop / dai danh nghia = {:.4f}  (= 1/{:.0f})"
          .format(dist / (mult * da), (mult * da) / dist))
    idx = df.index.tz_convert("America/New_York").tz_localize(None)
    F = pd.DataFrame({"h": df["high"].to_numpy(), "l": df["low"].to_numpy(),
                      "o": df["open"].to_numpy()}, index=idx)
    F = F[~F.index.duplicated(keep="last")]
    dd = F[(F.index >= day) & (F.index < day + pd.Timedelta(days=1))]
    if len(dd):
        rng = dd["h"].max() - dd["l"].min()
        print("  bien do THUC TE cua ngay vao lenh : {:.2f} diem".format(rng))
        print("  => stop bang {:.1f}% bien do mot ngay".format(dist / rng * 100))

    print("\n  --- gia di dau sau khi vao lenh ---")
    ent_naive = pd.Timestamp(bar_ts)
    if ent_naive.tzinfo is not None:
        ent_naive = ent_naive.tz_localize(None)
    after = F[F.index > ent_naive].head(60 * 20)
    if sg["direction"] == "SHORT":
        crossed = after[after["h"] >= stop]
    else:
        crossed = after[after["l"] <= stop]
    if len(crossed):
        t0 = crossed.index[0]
        mins = (t0 - ent_naive).total_seconds() / 60.0
        print("  gia cham muc stop lan dau luc {}  = {:.0f} phut sau khi vao lenh"
              .format(t0, mins))
    else:
        print("  khong cham trong 20 gio dau")
    nxt = day + pd.Timedelta(days=1)
    nd = F[(F.index >= nxt) & (F.index < nxt + pd.Timedelta(days=1))]
    if len(nd):
        first = nd.iloc[0]
        print("  bar dau tien cua ngay ke tiep ({}) mo o {:.2f}"
              .format(nxt.date(), float(first["o"])))
        print("  => luc engine 'xet stop' lan dau, gia da cach muc stop {:.2f} diem"
              .format(abs(float(first["o"]) - stop)))
        pv = BASKET[a.inst].point_value
        print("  => tren 1 hop dong: engine ghi lo {:.0f} diem = ${:,.0f}; "
              "thoat o gia thuc te thi lo {:.0f} diem = ${:,.0f}"
              .format(dist, dist * pv,
                      abs(float(first["o"]) - entry), abs(float(first["o"]) - entry) * pv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
