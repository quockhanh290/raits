"""Nhanh NKD co dinh khuyet stop sai phia khong? — CHI DOC.

NKD dung CHUNG generate_signal cua trend_follow (ema=10), nen cung cong thuc chandelier
neo vao cuc tri cua nen, va cung khong co dong nao kiem stop nam ve phia thua.

    python scratch/stop_geometry_nkd.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))


def main() -> int:
    from global_index._core import load_parquet as gi_load
    from global_index.regime import RegimeLabels
    from global_index.specs import SPECS
    from futures._validated_core import (_swing_cache, daily_atr_series, atr14,
                                         benchmark_daily, label_regimes)
    from futures.basket import REGIME
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache

    EMA, MULT = 10, 2.5
    cfg = dict(TrendFollowStrategy().config)
    cfg["ema_period"] = EMA
    cfg["chandelier_atr_mult"] = MULT
    strat = TrendFollowStrategy(cfg)

    c = SPECS["MNKD"]
    ndf = gi_load("global_index/data/NKD_frozen_2024.parquet")
    ndf.index = ndf.index.tz_convert(c.session_tz)
    spy = pd.Series(label_regimes(benchmark_daily("spy_daily_live.csv"),
                                  "2018-01-01", 3, REGIME["hmm_fit_end"]))
    idx = pd.DatetimeIndex(spy.index)
    spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    labels = RegimeLabels(spy.sort_index(), lag_days=1)

    datr = daily_atr_series(ndf)
    cache = _swing_cache(ndf, datr)
    sig = build_sig_cache(cache, labels, strat, EMA, set(cfg["allowed_regimes"]))
    print("so tin hieu NKD: {}".format(len(sig)))

    rows = []
    for day, (bar_ts, sg) in sig.items():
        b5 = cache["b5"].get(day)
        if b5 is None:
            continue
        at5 = float(atr14(b5.loc[:bar_ts]))
        if not np.isfinite(at5) or at5 <= 0:
            continue
        ep, st = float(sg["entry_price"]), float(sg["initial_stop"])
        band = MULT * at5
        dist = (st - ep) if sg["direction"] == "SHORT" else (ep - st)
        rows.append(dict(day=day, dir=sg["direction"], entry=ep, stop=st,
                         dist=dist, ratio=dist / band, pv=c.point_value))
    R = pd.DataFrame(rows)
    n = len(R)
    print("\n=== NKD (MNKD) — hinh hoc muc stop ban dau ===")
    q = R.ratio.quantile([.01, .1, .5, .9]).round(3)
    print("  n={} | ty le dist/bang: p01 {} | p10 {} | trung vi {} | p90 {}"
          .format(n, q[.01], q[.1], q[.5], q[.9]))
    print("  rui ro that/lenh: trung vi ${:,.0f} | p10 ${:,.0f} | p90 ${:,.0f}"
          .format((R.dist * R.pv).median(), (R.dist * R.pv).quantile(.1),
                  (R.dist * R.pv).quantile(.9)))
    bad = R[R.dist <= 0]
    print("\n  STOP ROI SANG PHIA CO LAI: {} lenh ({:.2f}%)".format(len(bad), len(bad) / n * 100))
    for _, r in bad.head(8).iterrows():
        print("    {} {}  vao {:.2f}  stop {:.2f}  (lech {:.2f} SAI PHIA)"
              .format(str(r.day.date()), r["dir"], r.entry, r.stop, r.dist))
    return 0


if __name__ == "__main__":
    sys.exit(main())
