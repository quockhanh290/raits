"""Khoang cach tu gia vao toi stop co phai mot dai luong DUOC THIET KE khong? — CHI DOC.

stop (SHORT) = min(low cua nen vao lenh) + mult x ATR5
=> khoang cach that tu gia vao = mult x ATR5 - (gia vao - low cua nen)
Tuc no la phan du cua bang ATR tru vi tri gia vao TRONG chinh cay nen do.

Ba cau:
  1. ty le (khoang cach that)/(mult x ATR5) phan bo the nao? Gan 1 = anchor khong an gi.
  2. rui ro moi lenh co on dinh khong (spread rong = sizing 1% khong dung nghia).
  3. CO lenh nao stop roi sang PHIA CO LAI khong? (SHORT: stop <= gia vao). Neu co thi
     vong lap thoat kiem `high >= stop` dung ngay lap tuc -> backtest ghi LAI khong co that.

    python scratch/stop_geometry.py --data-dir data/cache/futures/frozen_sim
        --regime-csv spy_daily_live.csv
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

    dfs = load_basket(a.data_dir)
    cut = pd.Timestamp(a.end)
    for k in list(dfs):
        df = dfs[k]
        c = cut.tz_localize(df.index.tz) if df.index.tz is not None else cut
        dfs[k] = df[df.index <= c]
    labels = basket_labels(a.regime_csv)

    rows = []
    for k in dfs:
        df = dfs[k]
        datr = daily_atr_series(df)
        cache = _swing_cache(df, datr)
        sig = build_sig_cache(cache, labels, strat, ema, set(cfg["allowed_regimes"]))
        for day, (bar_ts, sg) in sig.items():
            b5 = cache["b5"].get(day)
            if b5 is None:
                continue
            hist = b5.loc[:bar_ts]
            at5 = float(atr14(hist))
            if not np.isfinite(at5) or at5 <= 0:
                continue
            ep = float(sg["entry_price"])
            st = float(sg["initial_stop"])
            band = mult * at5
            dist = (st - ep) if sg["direction"] == "SHORT" else (ep - st)
            try:
                da = float(datr.asof(pd.Timestamp(day)))
            except Exception:
                da = np.nan
            rows.append(dict(inst=k, day=day, dir=sg["direction"], entry=ep, stop=st,
                             atr5=at5, band=band, dist=dist, ratio=dist / band,
                             datr=da, pv=BASKET[k].point_value))
        print("  {} xong".format(k), flush=True)

    R = pd.DataFrame(rows)
    n = len(R)
    print("\n" + "=" * 84)
    print("1. KHOANG CACH THAT / BANG DANH NGHIA (mult x ATR5)")
    print("=" * 84)
    q = R.ratio.quantile([.01, .1, .25, .5, .75, .9, .99]).round(3)
    print("  n={} | p01 {} | p10 {} | p25 {} | trung vi {} | p75 {} | p90 {} | p99 {}"
          .format(n, q[.01], q[.1], q[.25], q[.5], q[.75], q[.9], q[.99]))
    print("  trung binh {:.3f} | do lech chuan {:.3f}".format(R.ratio.mean(), R.ratio.std()))
    print("  => anchor an mat trung vi {:.0f}% cua bang".format((1 - q[.5]) * 100))

    print("\n=== 2. RUI RO MOI LENH CO ON DINH KHONG (tinh bang USD) ===")
    R["risk_usd"] = R.dist * R.pv
    qq = R.risk_usd.quantile([.1, .25, .5, .75, .9]).round(0)
    print("  rui ro that/lenh: p10 ${:,.0f} | p25 ${:,.0f} | trung vi ${:,.0f} "
          "| p75 ${:,.0f} | p90 ${:,.0f}".format(qq[.1], qq[.25], qq[.5], qq[.75], qq[.9]))
    print("  p90/p10 = {:.1f} lan".format(qq[.9] / max(qq[.1], 1e-9)))
    R["sizer_assumed"] = mult * R.datr * R.pv
    ok = R[R.sizer_assumed.notna() & (R.sizer_assumed > 0)]
    print("  bo sizing gia dinh rui ro/hop dong = mult x ATR ngay x pv:")
    print("    trung vi gia dinh ${:,.0f} vs trung vi THAT ${:,.0f}  -> gia dinh gap {:.1f} lan"
          .format(ok.sizer_assumed.median(), ok.risk_usd.median(),
                  ok.sizer_assumed.median() / max(ok.risk_usd.median(), 1e-9)))
    rr = (ok.sizer_assumed / ok.risk_usd)
    print("    ty le gia-dinh/that: p10 {:.1f} | trung vi {:.1f} | p90 {:.1f} lan"
          .format(rr.quantile(.1), rr.median(), rr.quantile(.9)))

    print("\n=== 3. CO LENH NAO STOP ROI SANG PHIA CO LAI KHONG? ===")
    bad = R[R.dist <= 0]
    print("  so lenh co khoang cach stop <= 0 : {} ({:.2f}%)".format(len(bad), len(bad) / n * 100))
    tiny = R[R.dist <= 0.05 * R.band]
    print("  so lenh co khoang cach < 5% bang : {} ({:.2f}%)".format(len(tiny), len(tiny) / n * 100))
    if len(bad):
        print("  vi du:")
        for _, r in bad.head(8).iterrows():
            print("    {} {} {}  vao {:.2f}  stop {:.2f}  (lech {:.2f} diem SAI PHIA)"
                  .format(r.inst, str(r.day.date()), r["dir"], r.entry, r.stop, r.dist))
    return 0


if __name__ == "__main__":
    sys.exit(main())
