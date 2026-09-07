"""Doi co so tinh stop co lam DICH lua chon ema / max_hold khong? — CHI DOC.

Cac phep quet truoc deu giu ema=30, hold=5 co dinh — hai gia tri do duoc WFO goc chon TREN
THUOC DO CU va tren co so stop cu. Neu ba truc tuong tac manh thi quet mot truc la lat cat
qua mot mat ma hai toa do kia dat sai cho.

Bai nay KHONG di tim cau hinh tot nhat (lam vay tren cung du lieu la curve fitting). No hoi
mot cau hep hon: **argmax co DICH khong khi doi co so stop**. Argmax dung yen -> ba truc
tach roi duoc, ket luan mot truc dung. Argmax nhay -> phai quet chung.

Hai lat cat, muc tieu = P&L DA SUA KHOP LENH, vu trang D+1 14:05, ratchet=False:
  Lat 1: ema=30 co dinh, quet hold x f
  Lat 2: hold=5 co dinh, quet ema x f   (moi ema phai dung lai bang tin hieu)

Moc mem: (ema=30, hold=5, f=0.12) phai ra gan $6.807 cua lan chay truoc.

    python scratch/interaction_grid.py --data-dir data/cache/futures/frozen_sim
        --regime-csv spy_daily_live.csv --end 2024-12-31
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

FRACS = [0.12, 0.5, 2.5]
HOLDS = [3, 5, 7, 10]
EMAS = [20, 30, 50]
ARM = 14 + 5 / 60


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    a = ap.parse_args()

    from futures.basket import SWING_TF_PARAM, BASKET
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, daily_atr_series
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache, run_loop

    mult = SWING_TF_PARAM["chandelier_atr_mult"]
    dfs = load_basket(a.data_dir)
    cut = pd.Timestamp(a.end)
    for k in list(dfs):
        df = dfs[k]
        c = cut.tz_localize(df.index.tz) if df.index.tz is not None else cut
        dfs[k] = df[df.index <= c]
    labels = basket_labels(a.regime_csv)
    costs = costs_for_basket(slippage_ticks=a.slippage_ticks)

    caches, datrs = {}, {}
    for k in dfs:
        datrs[k] = daily_atr_series(dfs[k])
        caches[k] = _swing_cache(dfs[k], datrs[k])

    strats, sigs = {}, {}
    for e in EMAS:
        cfg = dict(TrendFollowStrategy().config)
        cfg["ema_period"] = e
        cfg["chandelier_atr_mult"] = mult
        s = TrendFollowStrategy(cfg)
        strats[e] = s
        sigs[e] = {}
        for k in dfs:
            sigs[e][k] = build_sig_cache(caches[k], labels, s, e,
                                         set(s.config["allowed_regimes"]))
        print("  sig cache ema={} xong".format(e))

    def make_sig(e, k, f):
        out = {}
        for day, (ts_, sg) in sigs[e][k].items():
            try:
                da = float(datrs[k].asof(pd.Timestamp(day)))
            except Exception:
                continue
            if not np.isfinite(da) or da <= 0:
                continue
            s2 = dict(sg)
            ep = float(s2["entry_price"])
            s2["initial_stop"] = (ep - f * da) if s2["direction"] == "LONG" else (ep + f * da)
            out[day] = (ts_, s2)
        return out

    def corr_one(t, inst):
        if t["reason"] != "CHANDELIER":
            return 0.0
        cache = caches[inst]
        ts, hl = cache.get("ts", {}), cache["hl"]
        d0 = pd.Timestamp(t["day"]).normalize()
        d1 = pd.Timestamp(t["exit_day"]).normalize()
        if d1 != d0 + pd.Timedelta(days=1):
            return 0.0
        dts = ts.get(d1)
        if dts is None or not len(dts):
            return 0.0
        naive = dts.tz_localize(None) if dts.tz is not None else dts
        arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=ARM)
        j = int(np.searchsorted(np.asarray(naive), np.datetime64(arm)))
        if j >= len(naive):
            return 0.0
        et = pd.Timestamp(t["exit_time"])
        if et.tzinfo is not None:
            et = et.tz_localize(None)
        if et != pd.Timestamp(naive[j]):
            return 0.0
        op = float(hl[d1][2][j])
        stp = float(t["exit"])
        w = (stp - op) if t["direction"] == "LONG" else (op - stp)
        return w * BASKET[inst].point_value if w > 0 else 0.0

    def cell(e, hold, f):
        adj = 0.0
        n = 0
        for k in dfs:
            sg = make_sig(e, k, f)
            tr, _ = run_loop(dfs[k], labels, costs[k], strat=strats[e], ema_period=e,
                             mult=mult, max_hold_days=hold, cache=caches[k],
                             same_day_stop=False, stop_slip_ticks=0.0,
                             sig_cache=sg, stop_active_hour=ARM, ratchet=False)
            for t in tr:
                adj += t["pnl"] - corr_one(t, k)
                n += 1
        return adj, n

    print("\n" + "=" * 78)
    print("LAT 1 — ema=30 co dinh | P&L DA SUA (so lenh trong ngoac)")
    print("=" * 78)
    print("  {:>8} | ".format("hold") + " | ".join("{:>18}".format("f=" + str(f))
                                                   for f in FRACS))
    best1 = {}
    for hold in HOLDS:
        row = []
        for f in FRACS:
            v, n = cell(30, hold, f)
            best1[(hold, f)] = v
            row.append("{:>10,.0f} ({:>4})".format(v, n))
        print("  {:>8} | ".format(hold) + " | ".join(row))
    print("\n  argmax hold theo tung f:")
    for f in FRACS:
        b = max(HOLDS, key=lambda h: best1[(h, f)])
        print("    f={:<5} -> hold={:<3} (${:,.0f})".format(f, b, best1[(b, f)]))

    print("\n" + "=" * 78)
    print("LAT 2 — hold=5 co dinh | P&L DA SUA (so lenh trong ngoac)")
    print("=" * 78)
    f2 = [0.12, 2.5]
    print("  {:>8} | ".format("ema") + " | ".join("{:>18}".format("f=" + str(f))
                                                  for f in f2))
    best2 = {}
    for e in EMAS:
        row = []
        for f in f2:
            v, n = cell(e, 5, f)
            best2[(e, f)] = v
            row.append("{:>10,.0f} ({:>4})".format(v, n))
        print("  {:>8} | ".format(e) + " | ".join(row))
    print("\n  argmax ema theo tung f:")
    for f in f2:
        b = max(EMAS, key=lambda e: best2[(e, f)])
        print("    f={:<5} -> ema={:<3} (${:,.0f})".format(f, b, best2[(b, f)]))

    print("\n=== MOC MEM ===")
    print("  (ema=30, hold=5, f=0.12) = ${:,.0f}  — lan truoc do ${:,.0f}"
          .format(best1[(5, 0.12)], 6807))
    return 0


if __name__ == "__main__":
    sys.exit(main())
