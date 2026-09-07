"""A co tu sua luon hinh hoc stop khong? — CHI DOC.

Stop neo vao cuc tri cua nen vao lenh. Khi nen resume di DUNG chieu, gia vao nam sat cuc tri
do, nen bang ATR khong bi an. Gia thuyet: A tu sua luon khuyet tat hinh hoc stop.

So bo tin hieu GOC (build_sig_cache) voi bo tin hieu cua A (_scan_sig require_dir=True):
  - ty le (khoang cach stop that) / (mult x ATR5)   -> 1.0 = khong bi an ti nao
  - so lenh stop roi sang PHIA CO LAI
  - rui ro that moi lenh (USD)

    python scratch/geom_after_A.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, r"d:\raits\scratch")

import harness as H


def main() -> int:
    from futures.basket import SWING_TF_PARAM, BASKET
    from futures.swing_tf import basket_labels, load_basket
    from futures._validated_core import atr14
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache

    ema = SWING_TF_PARAM["ema_period"]
    mult = SWING_TF_PARAM["chandelier_atr_mult"]
    cfg = dict(TrendFollowStrategy().config)
    cfg["ema_period"] = ema
    cfg["chandelier_atr_mult"] = mult
    strat = TrendFollowStrategy(cfg)
    allowed = set(cfg["allowed_regimes"])

    dfs = load_basket("data/cache/futures/frozen_sim")
    cut = pd.Timestamp("2024-12-31")
    labels = basket_labels("spy_daily_live.csv")

    rows = []
    for k in dfs:
        df = dfs[k]
        c = cut.tz_localize(df.index.tz) if df.index.tz is not None else cut
        df = df[df.index <= c]
        cache, datr = H._cache(df)
        goc = build_sig_cache(cache, labels, strat, ema, allowed)
        vaA = H._scan_sig(cache, labels, strat, ema, allowed, True)
        pv = BASKET[k].point_value
        for nhan, sset in (("GOC", goc), ("A", vaA)):
            for day, (ts_, sg) in sset.items():
                b5 = cache["b5"].get(day)
                if b5 is None:
                    continue
                at5 = float(atr14(b5.loc[:ts_]))
                if not np.isfinite(at5) or at5 <= 0:
                    continue
                ep, st = float(sg["entry_price"]), float(sg["initial_stop"])
                band = mult * at5
                dist = (st - ep) if sg["direction"] == "SHORT" else (ep - st)
                rows.append(dict(bo=nhan, inst=k, ratio=dist / band,
                                 risk=dist * pv, dist=dist))
        print("  {} xong".format(k), flush=True)

    R = pd.DataFrame(rows)
    print("\n" + "=" * 84)
    print("HINH HOC MUC STOP BAN DAU — bo tin hieu GOC vs bo tin hieu cua A")
    print("=" * 84)
    print("  {:<6} {:>7} {:>8} {:>8} {:>9} {:>8} {:>8} {:>14}"
          .format("bo", "n", "p01", "p10", "trung vi", "p75", "p90", "sai phia"))
    for b in ("GOC", "A"):
        s = R[R.bo == b]
        q = s.ratio.quantile([.01, .1, .5, .75, .9])
        bad = int((s.dist <= 0).sum())
        print("  {:<6} {:>7} {:>8.3f} {:>8.3f} {:>9.3f} {:>8.3f} {:>8.3f} {:>8} ({:.2f}%)"
              .format(b, len(s), q[.01], q[.1], q[.5], q[.75], q[.9], bad,
                      bad / len(s) * 100))

    print("\n=== RUI RO THAT MOI LENH (USD) ===")
    for b in ("GOC", "A"):
        s = R[R.bo == b]
        q = s.risk.quantile([.1, .5, .9])
        print("  {:<6} p10 ${:>6,.0f} | trung vi ${:>6,.0f} | p90 ${:>6,.0f} | p90/p10 {:.1f} lan"
              .format(b, q[.1], q[.5], q[.9], q[.9] / max(q[.1], 1e-9)))

    print("\n=== DOC ===")
    g = R[R.bo == "GOC"]
    a = R[R.bo == "A"]
    print("  bang ATR bi an: GOC trung vi {:.0f}% | A trung vi {:.0f}%"
          .format((1 - g.ratio.median()) * 100, (1 - a.ratio.median()) * 100))
    print("  stop sai phia : GOC {} lenh | A {} lenh"
          .format(int((g.dist <= 0).sum()), int((a.dist <= 0).sum())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
