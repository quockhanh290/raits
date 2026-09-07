"""Cham stop roi HOI (nhieu) hay cham roi DI TIEP (that)? — CHI DOC.

Day la ly do kinh te duy nhat biem minh cho khoang an han: neu phan lon cu cham muc stop
trong quang tran la nhieu roi gia hoi lai, thi hoan la bat duoc thu that. Neu phan lon la
khoi dau mot chuyen dong that, thi hoan chi la hoan thua voi gia te hon.

Chia moi lenh lam ba nhom:
  A. KHONG cham muc stop trong quang tran
  B. CHAM roi HOI  — truoc gio vu trang, gia da quay ve phia co loi cua muc stop
  C. CHAM va VAN o ben kia luc vu trang  — nhom phai hieu chinh khop lenh

Bao so lenh, P&L engine, P&L da sua, va ly do thoat cua tung nhom.

Vu trang D+1 14:05, ratchet=False (luat live). Muc stop lay tu tin hieu vao lenh.

    python scratch/noise_vs_real.py
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

    grp = defaultdict(lambda: dict(n=0, raw=0.0, adj=0.0, reasons=defaultdict(int)))
    n_unk = 0

    for k in dfs:
        df = dfs[k]
        datr = daily_atr_series(df)
        cache = _swing_cache(df, datr)
        sig = build_sig_cache(cache, labels, strat, ema, set(cfg["allowed_regimes"]))
        tr, _ = run_loop(df, labels, costs[k], strat=strat, ema_period=ema, mult=mult,
                         max_hold_days=hold, cache=cache, same_day_stop=False,
                         stop_slip_ticks=0.0, sig_cache=sig, stop_active_hour=ARM,
                         ratchet=False)
        ts, hl = cache.get("ts", {}), cache["hl"]
        pv = BASKET[k].point_value
        for t in tr:
            d0 = pd.Timestamp(t["day"]).normalize()
            hit = sig.get(d0)
            if hit is None:
                n_unk += 1
                continue
            stp0 = float(hit[1]["initial_stop"])
            ent = pd.Timestamp(t["entry_time"])
            if ent.tzinfo is not None:
                ent = ent.tz_localize(None)
            arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=ARM)
            LONG = t["direction"] == "LONG"

            crossed = False
            cur = d0
            while cur <= arm.normalize():
                dts = ts.get(cur)
                if dts is not None and len(dts):
                    naive = dts.tz_localize(None) if dts.tz is not None else dts
                    arr = np.asarray(naive)
                    m = (arr > np.datetime64(ent)) & (arr < np.datetime64(arm))
                    if m.any():
                        w = np.where(m)[0]
                        if LONG:
                            crossed = crossed or bool(hl[cur][1][w].min() <= stp0)
                        else:
                            crossed = crossed or bool(hl[cur][0][w].max() >= stp0)
                cur = cur + pd.Timedelta(days=1)

            # trang thai TAI moc vu trang
            d1 = arm.normalize()
            past_at_arm = False
            corr = 0.0
            dts = ts.get(d1)
            if dts is not None and len(dts):
                naive = dts.tz_localize(None) if dts.tz is not None else dts
                j = int(np.searchsorted(np.asarray(naive), np.datetime64(arm)))
                if j < len(naive):
                    op = float(hl[d1][2][j])
                    past_at_arm = (op < stp0) if LONG else (op > stp0)
                    if past_at_arm and t["reason"] == "CHANDELIER":
                        et = pd.Timestamp(t["exit_time"])
                        if et.tzinfo is not None:
                            et = et.tz_localize(None)
                        if et == pd.Timestamp(naive[j]):
                            stp = float(t["exit"])
                            w2 = (stp - op) if LONG else (op - stp)
                            if w2 > 0:
                                corr = w2 * pv

            if not crossed:
                key = "A. khong cham stop"
            elif past_at_arm:
                key = "C. cham va VAN o ben kia luc vu trang"
            else:
                key = "B. cham roi HOI (nhieu)"
            g = grp[key]
            g["n"] += 1
            g["raw"] += t["pnl"]
            g["adj"] += t["pnl"] - corr
            g["reasons"][t["reason"]] += 1
        print("  {} xong".format(k), flush=True)

    tot_n = sum(g["n"] for g in grp.values())
    print("\n" + "=" * 96)
    print("CHAM STOP TRONG QUANG TRAN ROI SAO? (vu trang D+1 14:05, stop co dinh)")
    print("=" * 96)
    print("  {:<42} {:>6} {:>7} {:>13} {:>13}".format("nhom", "lenh", "%", "P&L engine",
                                                       "P&L da sua"))
    print("  " + "-" * 88)
    for key in sorted(grp):
        g = grp[key]
        print("  {:<42} {:>6} {:>6.1f}% {:>13,.0f} {:>13,.0f}"
              .format(key, g["n"], g["n"] / tot_n * 100, g["raw"], g["adj"]))
    print("  " + "-" * 88)
    print("  {:<42} {:>6} {:>7} {:>13,.0f} {:>13,.0f}"
          .format("TONG", tot_n, "", sum(g["raw"] for g in grp.values()),
                  sum(g["adj"] for g in grp.values())))
    if n_unk:
        print("  ({} lenh khong phan loai duoc — khong co trong bang tin hieu)".format(n_unk))

    print("\n  --- ly do thoat tung nhom ---")
    for key in sorted(grp):
        print("  {:<42} {}".format(key, dict(grp[key]["reasons"])))

    a = grp.get("B. cham roi HOI (nhieu)", {"n": 0})
    c = grp.get("C. cham va VAN o ben kia luc vu trang", {"n": 0})
    if a["n"] + c["n"]:
        print("\n  => trong so lenh CO cham stop: {:.1f}% la nhieu (hoi lai), "
              "{:.1f}% di tiep".format(a["n"] / (a["n"] + c["n"]) * 100,
                                       c["n"] / (a["n"] + c["n"]) * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
