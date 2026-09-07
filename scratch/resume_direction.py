"""Bat nen resume phai di DUNG CHIEU lenh — sua khuyet tat, khong phai chinh tham so. CHI DOC.

generate_signal chon huong bang viec nen PULLBACK dong o phia nao cua EMA, roi vao lenh tai
GIA DONG cua nen RESUME — nhung khong dong nao kiem nen resume di dung chieu. Docstring goi
no la "the bar where price moved back in trend direction"; code khong bat dieu do.

Hau qua da thay: MES 2018-11-02 ban tai dinh mot nen tang 20 diem; MNQ 2022-05-12 ban giua
mot gio tang 240 diem.

Bai nay LOC lai tap tin hieu: chi giu tin hieu ma nen resume dong dung chieu lenh
  LONG  : close resume > open resume
  SHORT : close resume < open resume
roi do lai bang thuoc do DA SUA khop lenh, vu trang D+1 14:05, ratchet=False.

CACH DOC CAM KET TRUOC: day la sua khuyet tat, khong phai toi uu. Doc "no doi gi", va
hieu ung phai giu dau o CA HAI NUA thoi gian.

    python scratch/resume_direction.py
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

    caches, sigs = {}, {}
    for k in dfs:
        caches[k] = _swing_cache(dfs[k], daily_atr_series(dfs[k]))
        sigs[k] = build_sig_cache(caches[k], labels, strat, ema, set(cfg["allowed_regimes"]))

    # loc: nen resume phai dong dung chieu
    kept = {}
    n_all = n_keep = 0
    for k in dfs:
        out = {}
        for day, (bar_ts, sg) in sigs[k].items():
            b5 = caches[k]["b5"].get(day)
            if b5 is None:
                continue
            try:
                bar = b5.loc[bar_ts]
            except Exception:
                continue
            n_all += 1
            up = float(bar["close"]) > float(bar["open"])
            ok = up if sg["direction"] == "LONG" else (not up)
            if ok:
                out[day] = (bar_ts, sg)
                n_keep += 1
        kept[k] = out
    print("  tin hieu goc {} | giu lai {} ({:.1f}%) | loai {}"
          .format(n_all, n_keep, n_keep / n_all * 100, n_all - n_keep), flush=True)

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

    def run(sigset, nhan):
        raw = adj = tc = 0.0
        n = 0
        yr = defaultdict(float)
        rs = defaultdict(int)
        wins = 0
        for k in dfs:
            tr, _ = run_loop(dfs[k], labels, costs[k], strat=strat, ema_period=ema,
                             mult=mult, max_hold_days=hold, cache=caches[k],
                             same_day_stop=False, stop_slip_ticks=0.0,
                             sig_cache=sigset[k], stop_active_hour=ARM, ratchet=False)
            for t in tr:
                c = corr_one(t, k)
                p = t["pnl"] - c
                raw += t["pnl"]
                adj += p
                tc += c
                n += 1
                rs[t["reason"]] += 1
                if p > 0:
                    wins += 1
                yr[str(t.get("exit_day") or t["day"])[:4]] += p
        print("\n=== {} ===".format(nhan))
        print("  {} lenh | P&L tho ${:,.0f} | P&L DA SUA ${:,.0f} | ty le thang {:.1f}%"
              .format(n, raw, adj, wins / max(n, 1) * 100))
        print("  ly do thoat: {}".format(dict(rs)))
        return dict(n=n, adj=adj, yr=dict(yr))

    a = run(sigs, "GOC — khong rang buoc huong nen resume")
    b = run(kept, "DA LOC — nen resume phai dong dung chieu")

    print("\n=== SO SANH ===")
    print("  so lenh   {} -> {}".format(a["n"], b["n"]))
    print("  P&L da sua ${:,.0f} -> ${:,.0f}   ({:+,.0f})"
          .format(a["adj"], b["adj"], b["adj"] - a["adj"]))
    print("  P&L moi lenh ${:,.0f} -> ${:,.0f}"
          .format(a["adj"] / max(a["n"], 1), b["adj"] / max(b["n"], 1)))

    years = sorted(set(a["yr"]) | set(b["yr"]))
    print("\n=== THEO NAM (P&L da sua) ===")
    print("  {:<8} | {:>10} | {:>10} | {:>10}".format("nam", "goc", "da loc", "chenh"))
    h1 = h2 = 0.0
    mid = years[len(years) // 2]
    for y in years:
        d = b["yr"].get(y, 0.) - a["yr"].get(y, 0.)
        if y <= mid:
            h1 += d
        else:
            h2 += d
        print("  {:<8} | {:>10,.0f} | {:>10,.0f} | {:>+10,.0f}"
              .format(y, a["yr"].get(y, 0.), b["yr"].get(y, 0.), d))
    print("\n  CUA KIEM: nua dau {:+,.0f} | nua sau {:+,.0f} -> {}"
          .format(h1, h2, "cung dau" if h1 * h2 > 0 else "DOI DAU"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
