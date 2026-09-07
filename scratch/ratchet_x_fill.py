"""Ratchet va khop lenh phai do CUNG NHAU — CHI DOC.

Dot do truoc ket luan ratchet la nhieu (+$132 / 0,3%, 9 lenh khac). Dung — DUOI gia dinh
khop lenh cu. Nhung ratchet doi chinh MUC STOP ma phep sua so voi gia mo:
  - LONG: stop ratchet CAO hon stop co dinh -> nhieu lenh cham hon, va cu vuot (stop - gia
    mo) LON hon.
  - stop co dinh (dung luat live) -> it lenh cham hon, cu vuot nho hon.
Nen sai lech khop lenh PHAI nho hon o nhanh live. Cau hoi: nho bao nhieu, va o cell
"stop co dinh + khop dung + vu trang 14h" — gan nhat voi live that — con lai bao nhieu.

Luoi 2x2x2: vu trang {ranh gioi ngay, 14h} x ratchet {True, False} x khop {tho, sua}.
CONG: ratchet=True + vu trang ranh gioi ngay + khop tho PHAI trung engine.

    python scratch/ratchet_x_fill.py --data-dir data/cache/futures/frozen_sim
        --regime-csv spy_daily_live.csv --end 2024-12-31
"""
from __future__ import annotations
import argparse, sys
from collections import defaultdict
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

    from futures.basket import SWING_TF_PARAM, BASKET
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, daily_atr_series, backtest_swing_tf
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

    caches, sigs = {}, {}
    for k in dfs:
        caches[k] = _swing_cache(dfs[k], daily_atr_series(dfs[k]))
        sigs[k] = build_sig_cache(caches[k], labels, strat, ema, allowed)
    print("cache xong")

    print("\n=== CONG ===")
    ok = True
    for k in dfs:
        eng = backtest_swing_tf(dfs[k], labels, costs[k], ema_period=ema,
                                chandelier_atr_mult=mult, max_hold_days=hold)
        z, _ = run_loop(dfs[k], labels, costs[k], strat=strat, ema_period=ema, mult=mult,
                        max_hold_days=hold, cache=caches[k], same_day_stop=False,
                        stop_slip_ticks=0.0, sig_cache=sigs[k], stop_active_hour=0.0,
                        ratchet=True)
        m = (len(eng) == len(z)
             and abs(sum(t["pnl"] for t in eng) - sum(t["pnl"] for t in z)) < 0.01)
        ok = ok and m
        print("  {:<4} {:>4}t ${:>10,.0f} -> {}".format(k, len(eng),
              sum(t["pnl"] for t in eng), "MATCH" if m else "MISMATCH"))
    if not ok:
        print("!! cong hong")
        return 1

    def corr_one(t, inst, H):
        if t["reason"] != "CHANDELIER":
            return 0.0
        cache = caches[inst]
        ts, hl = cache.get("ts", {}), cache["hl"]
        d0 = pd.Timestamp(t["day"]).normalize()
        d1 = pd.Timestamp(t["exit_day"]).normalize()
        if d1 != d0 + pd.Timedelta(days=1):
            return 0.0
        day_ts = ts.get(d1)
        if day_ts is None or not len(day_ts):
            return 0.0
        naive = day_ts.tz_localize(None) if day_ts.tz is not None else day_ts
        arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=H)
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

    print("\n=== LUOI (1 hop dong, 2-tick, IS 2018-2024) ===")
    print("  {:>14} {:>9} | {:>6} {:>12} | {:>6} {:>11} {:>13}"
          .format("vu trang", "ratchet", "lenh", "P&L tho", "n sua", "tong sua", "P&L da sua"))
    print("  " + "-" * 92)
    res = {}
    for H in (0.0, 14.0):
        for rt in (True, False):
            raw = 0.0
            nc = 0
            tc = 0.0
            n = 0
            reasons = defaultdict(int)
            for k in dfs:
                tr, _ = run_loop(dfs[k], labels, costs[k], strat=strat, ema_period=ema,
                                 mult=mult, max_hold_days=hold, cache=caches[k],
                                 same_day_stop=False, stop_slip_ticks=0.0,
                                 sig_cache=sigs[k], stop_active_hour=H, ratchet=rt)
                for t in tr:
                    raw += t["pnl"]
                    reasons[t["reason"]] += 1
                    n += 1
                    c = corr_one(t, k, H)
                    if c > 0:
                        nc += 1
                        tc += c
            res[(H, rt)] = dict(n=n, raw=raw, nc=nc, tc=tc, adj=raw - tc,
                                reasons=dict(reasons))
            print("  {:>14} {:>9} | {:>6} {:>12,.0f} | {:>6} {:>11,.0f} {:>13,.0f}"
                  .format("ranh gioi ngay" if H == 0 else "14h",
                          "CO" if rt else "KHONG (live)", n, raw, nc, tc, raw - tc))

    print("\n=== LY DO THOAT ===")
    for key in res:
        r = res[key]
        print("  vu trang {:<15} ratchet {:<12} {}".format(
            "ranh gioi ngay" if key[0] == 0 else "14h",
            "CO" if key[1] else "KHONG", r["reasons"]))

    print("\n=== DOC ===")
    a0 = res[(14.0, True)]
    a1 = res[(14.0, False)]
    print("  Tai moc vu trang 14h (luat live):")
    print("    ratchet CO   : tho ${:,.0f} | sua {} lenh ${:,.0f} | con ${:,.0f}"
          .format(a0["raw"], a0["nc"], a0["tc"], a0["adj"]))
    print("    ratchet KHONG: tho ${:,.0f} | sua {} lenh ${:,.0f} | con ${:,.0f}"
          .format(a1["raw"], a1["nc"], a1["tc"], a1["adj"]))
    print("    => bo ratchet lam sai lech khop lenh {} ${:,.0f}"
          .format("GIAM" if a1["tc"] < a0["tc"] else "TANG", abs(a1["tc"] - a0["tc"])))
    print("    => cell gan live nhat (stop co dinh + khop dung + 14h) = ${:,.0f}"
          .format(a1["adj"]))
    b0 = res[(0.0, True)]
    b1 = res[(0.0, False)]
    print("  Doi chieu, ratchet CO vs KHONG khi khop THO (nhu dot do cu): "
          "${:,.0f} vs ${:,.0f} = chenh ${:+,.0f}".format(b0["raw"], b1["raw"],
                                                          b1["raw"] - b0["raw"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
