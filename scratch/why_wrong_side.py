"""Vi sao stop roi sang phia co lai? In ra chinh cay nen vao lenh. — CHI DOC.

    python scratch/why_wrong_side.py --inst MES --date 2018-11-02
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

    from futures.basket import SWING_TF_PARAM
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
        print("khong co tin hieu ngay {}".format(a.date))
        return 1
    bar_ts, sg = hit
    b5 = cache["b5"][day]
    hist = b5.loc[:bar_ts]
    at5 = float(atr14(hist))
    band = mult * at5
    bar = b5.loc[bar_ts]
    prev = b5.loc[:bar_ts].iloc[-2] if len(hist) >= 2 else None

    print("\n=== {} {} — {} ===".format(a.inst, str(day.date()), sg["direction"]))
    print("\n  NEN VAO LENH ({}):".format(bar_ts))
    print("    open  {:>10.2f}".format(float(bar["open"])))
    print("    high  {:>10.2f}".format(float(bar["high"])))
    print("    low   {:>10.2f}".format(float(bar["low"])))
    print("    close {:>10.2f}   <- gia vao lenh = {:.2f}".format(float(bar["close"]),
                                                                  float(sg["entry_price"])))
    print("    bien do nen = {:.2f} diem".format(float(bar["high"]) - float(bar["low"])))
    if prev is not None:
        print("\n  nen truoc do (nen 'pullback'):")
        print("    O {:.2f}  H {:.2f}  L {:.2f}  C {:.2f}".format(
            float(prev["open"]), float(prev["high"]), float(prev["low"]),
            float(prev["close"])))

    print("\n  CONG THUC (SHORT): stop = low cua nen + {} x ATR5".format(mult))
    print("    ATR5                 = {:.2f}".format(at5))
    print("    bang {} x ATR5        = {:.2f}".format(mult, band))
    print("    low cua nen          = {:.2f}".format(float(bar["low"])))
    print("    => stop = {:.2f} + {:.2f} = {:.2f}".format(float(bar["low"]), band,
                                                          float(sg["initial_stop"])))
    print("    (engine ghi: {:.2f})".format(float(sg["initial_stop"])))

    ep = float(sg["entry_price"])
    lo = float(bar["low"])
    print("\n  VI SAO ROI SANG PHIA CO LAI:")
    print("    gia vao cach low cua chinh nen do = {:.2f} - {:.2f} = {:.2f} diem"
          .format(ep, lo, ep - lo))
    print("    ma bang chi rong                  = {:.2f} diem".format(band))
    print("    {:.2f} > {:.2f}  ->  stop tut xuong DUOI gia vao {:.2f} diem"
          .format(ep - lo, band, ep - float(sg["initial_stop"])))
    print("\n    tuc: nen vao lenh chay tu day len sat dinh dai hon ca bang ATR.")
    print("    Cong thuc chandelier neo vao CUC TRI CUA NEN, khong neo vao gia vao,")
    print("    va khong co dong nao kiem rang stop phai nam ve phia THUA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
