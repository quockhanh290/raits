"""Muc dung THAM HOA: cuu duoc bao nhieu o nhom C, giet mat bao nhieu o nhom B? — CHI DOC.

Y tuong: mot muc dung RONG, nam tren san NGAY TU LUC KHOP (nen no co that, khong dinh loi
khop lenh), ben canh muc chandelier hep chi vu trang luc D+1 14:05.

run_loop co san `disaster_mult`: muc = gia vao -+ mult x (khoang cach stop ban dau), va no
KHONG bi che boi cua so hoan — dung nghia mot lenh nam tren san tu dau.

DOC HAI VE TACH RIENG, khong doc tong:
  cuu o nhom C  -> "tong hieu chinh" giam (it lenh toi moc vu trang ma van o ben kia)
  giet o nhom B -> so lenh MAX_HOLD va P&L cua chung giam (lenh le ra hoi lai bi cat som)
Neu chi nhin tong thi lai roi vao bay chon dinh.

    python scratch/disaster_sweep.py
"""
from __future__ import annotations
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

ARM = 14 + 5 / 60
LEVELS = [None, 20.0, 12.0, 8.0, 5.0, 3.0, 2.0]


def main() -> int:
    from futures.basket import SWING_TF_PARAM, BASKET
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, daily_atr_series
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

    caches, sigs, datrs = {}, {}, {}
    for k in dfs:
        datrs[k] = daily_atr_series(dfs[k])
        caches[k] = _swing_cache(dfs[k], datrs[k])
        sigs[k] = build_sig_cache(caches[k], labels, strat, ema, set(cfg["allowed_regimes"]))
    print("cache xong", flush=True)

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

    print("\n" + "=" * 112)
    print("QUET MUC DUNG THAM HOA (muc = gia vao -+ mult x khoang cach stop; nam tren san tu luc khop)")
    print("=" * 112)
    print("  {:>7} | {:>6} | {:>11} {:>12} | {:>10} | {:>8} {:>12} | {:>8}"
          .format("mult", "lenh", "P&L tho", "P&L da sua", "tong sua",
                  "n MAXHOLD", "P&L MAXHOLD", "n DISAST"))
    print("  " + "-" * 108)
    res = {}
    for L in LEVELS:
        raw = adj = tc = 0.0
        n = 0
        rs = defaultdict(int)
        mh_pnl = 0.0
        yr = defaultdict(float)
        for k in dfs:
            tr, _ = run_loop(dfs[k], labels, costs[k], strat=strat, ema_period=ema,
                             mult=mult, max_hold_days=hold, cache=caches[k],
                             same_day_stop=False, stop_slip_ticks=0.0,
                             sig_cache=sigs[k], stop_active_hour=ARM, ratchet=False,
                             disaster_mult=L)
            for t in tr:
                c = corr_one(t, k)
                raw += t["pnl"]
                adj += t["pnl"] - c
                tc += c
                n += 1
                rs[t["reason"]] += 1
                if t["reason"] == "MAX_HOLD":
                    mh_pnl += t["pnl"]
                yr[str(t.get("exit_day") or t["day"])[:4]] += t["pnl"] - c
        res[L] = dict(n=n, raw=raw, adj=adj, tc=tc, rs=dict(rs), mh=mh_pnl, yr=dict(yr))
        print("  {:>7} | {:>6} | {:>11,.0f} {:>12,.0f} | {:>10,.0f} | {:>8} {:>12,.0f} | {:>8}"
              .format("tat" if L is None else "{:g}x".format(L), n, raw, adj, tc,
                      rs.get("MAX_HOLD", 0), mh_pnl, rs.get("DISASTER", 0)))
        sys.stdout.flush()

    base = res[None]
    print("\n=== HAI VE, SO VOI KHI TAT ===")
    print("  {:>7} | {:>22} | {:>24} | {:>14}"
          .format("mult", "CUU (tong sua giam)", "GIET (P&L MAX_HOLD giam)", "rong"))
    print("  " + "-" * 78)
    for L in LEVELS:
        if L is None:
            continue
        r = res[L]
        save = base["tc"] - r["tc"]
        kill = base["mh"] - r["mh"]
        print("  {:>7} | {:>22,.0f} | {:>24,.0f} | {:>14,.0f}"
              .format("{:g}x".format(L), save, kill, r["adj"] - base["adj"]))

    print("\n=== P&L DA SUA THEO NAM ===")
    years = sorted({y for r in res.values() for y in r["yr"]})
    print("  {:>7} | ".format("mult") + " | ".join("{:>8}".format(y) for y in years))
    for L in LEVELS:
        print("  {:>7} | ".format("tat" if L is None else "{:g}x".format(L))
              + " | ".join("{:>8,.0f}".format(res[L]["yr"].get(y, 0.)) for y in years))
    return 0


if __name__ == "__main__":
    sys.exit(main())
