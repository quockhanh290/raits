"""WFO do rong stop, TREN THUOC DO DA SUA — CHI DOC.

Hai dieu bat buoc, neu khong se lap lai dung cai bay vua dao ra:
  1) Muc tieu toi uu phai la P&L DA SUA KHOP LENH. Chay tren thuoc cu thi WFO se chon dung
     cai do rong khai thac loi khop lenh (do rong cang lon cang it lenh dinh loi -> so tho
     cang xau -> WFO chon HEP, dung vi ly do sai).
  2) Quet DO RONG CO LAP (`stop_width_mult`), khong quet `chandelier_atr_mult`: he so do
     vua dat initial_stop, vua la mau so sizing, vua la dai trail — quet no doi ca ba cung
     luc (ghi chep 08-05: khong ket luan duoc gi).

Phan A — kiem cau truc: khoang cach stop ban dau bang bao nhieu phan cua dai danh nghia
(mult x ATR NGAY)? runner noi ~1/22. Neu dung thi stop duoc tinh tu ATR 5 PHUT trong khi
dai trail tinh tu ATR NGAY — lech tang khung, khong phai lech tham so.

Phan B — WFO: chon do rong tren cac nam TRUOC, do o nam SAU. Bao ca hai muc tieu (tho va
da sua) de thay chung chon khac nhau khong.

Vu trang = luat live (D+1 14:05), ratchet=False (dung luat live: stop co dinh).

    python scratch/wfo_stop_width.py --data-dir data/cache/futures/frozen_sim
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

WIDTHS = [1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0]
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

    caches, sigs, datrs = {}, {}, {}
    for k in dfs:
        datrs[k] = daily_atr_series(dfs[k])
        caches[k] = _swing_cache(dfs[k], datrs[k])
        sigs[k] = build_sig_cache(caches[k], labels, strat, ema, allowed)
    print("cache xong")

    print("\n=== CONG (ratchet=True, vu trang nua dem == engine) ===")
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
        print("  {:<4} {:>4}t -> {}".format(k, len(eng), "MATCH" if m else "MISMATCH"))
    if not ok:
        return 1

    # ── PHAN A: stop ban dau rong bao nhieu so voi dai danh nghia ────────────
    print("\n" + "=" * 84)
    print("PHAN A — KHOANG CACH STOP BAN DAU / (mult x ATR NGAY)")
    print("=" * 84)
    for k in dfs:
        ratios = []
        for day, (ts_, sg) in sigs[k].items():
            d = float(abs(float(sg["entry_price"]) - float(sg["initial_stop"])))
            try:
                da = float(datrs[k].asof(pd.Timestamp(day)))
            except Exception:
                continue
            if np.isfinite(da) and da > 0:
                ratios.append(d / (mult * da))
        r = np.array(ratios)
        if len(r):
            print("  {:<5} n={:<5} trung vi {:.4f}  (= 1/{:.0f})   p10 {:.4f}  p90 {:.4f}"
                  .format(k, len(r), np.median(r), 1 / np.median(r),
                          np.percentile(r, 10), np.percentile(r, 90)))

    # ── PHAN B: WFO do rong ──────────────────────────────────────────────────
    def corr_one(t, inst, H):
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

    print("\n" + "=" * 84)
    print("PHAN B — QUET DO RONG CO LAP (vu trang D+1 14:05, stop co dinh)")
    print("=" * 84)
    print("  {:>7} | {:>6} | {:>12} {:>12} | {:>6} {:>12} | {:>6}"
          .format("x rong", "lenh", "P&L tho", "P&L da sua", "n sua", "tong sua", "PF sua"))
    print("  " + "-" * 84)
    raw_y, adj_y = {}, {}
    for w in WIDTHS:
        ry, ay = defaultdict(float), defaultdict(float)
        n = nc = 0
        tc = 0.0
        gw = gl = 0.0
        for k in dfs:
            tr, _ = run_loop(dfs[k], labels, costs[k], strat=strat, ema_period=ema,
                             mult=mult, max_hold_days=hold, cache=caches[k],
                             same_day_stop=False, stop_slip_ticks=0.0,
                             sig_cache=sigs[k], stop_active_hour=ARM, ratchet=False,
                             stop_width_mult=w)
            for t in tr:
                y = str(t.get("exit_day") or t["day"])[:4]
                c = corr_one(t, k, ARM)
                ry[y] += t["pnl"]
                ay[y] += t["pnl"] - c
                p = t["pnl"] - c
                if p > 0:
                    gw += p
                else:
                    gl -= p
                n += 1
                if c > 0:
                    nc += 1
                    tc += c
        raw_y[w], adj_y[w] = dict(ry), dict(ay)
        pf = gw / gl if gl > 0 else float("inf")
        print("  {:>6.1f}x | {:>6} | {:>12,.0f} {:>12,.0f} | {:>6} {:>12,.0f} | {:>6.2f}"
              .format(w, n, sum(ry.values()), sum(ay.values()), nc, tc, pf))

    years = sorted({y for w in WIDTHS for y in adj_y[w]})
    print("\n=== P&L DA SUA THEO NAM ===")
    print("  {:>7} | ".format("x rong") + " | ".join("{:>8}".format(y) for y in years))
    for w in WIDTHS:
        print("  {:>6.1f}x | ".format(w)
              + " | ".join("{:>8,.0f}".format(adj_y[w].get(y, 0.)) for y in years))

    for tag, D in (("THO (thuoc do cu)", raw_y), ("DA SUA", adj_y)):
        print("\n=== WALK-FORWARD — muc tieu {} ===".format(tag))
        tot = 0.0
        picks = []
        for i, y in enumerate(years):
            if i < 2:
                continue
            prev = years[:i]
            best = max(WIDTHS, key=lambda w: sum(D[w].get(p, 0.) for p in prev))
            v = D[best].get(y, 0.)
            tot += v
            picks.append("{:g}x".format(best))
            print("    {} | chon {:>5}x | P&L nam do {:>10,.0f}".format(y, best, v))
        print("    TONG ngoai mau ${:,.0f} | da chon: {}".format(tot, ", ".join(picks)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
