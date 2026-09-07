"""Khop tai GIA THI TRUONG luc DAT LENH — bo kich ban "khop giua" vi no khong co that.

Lenh dung da bi vuot qua thi thanh lenh thi truong; lenh thi truong khong khop tot hon gia
thi truong. Nen khong co dai nao ca: gia tri can dung la GIA THI TRUONG TAI THOI DIEM DAT.

Tinh chinh quan trong: luat vu trang la D+1 14:00 (runner._ARM_BY_CLUSTER), nhung lenh chi
duoc dat khi CO JOB CHAY. Job dau tien sau moc do la 14:05 ET (run_live_day), roi 14:10,
14:15... Nen ca hai thu phai dich cung nhau: khong duoc thoat truoc 14:05, va gia tham chieu
cung lay tai 14:05.

Quet vai moc dat lenh de xem no nhay bao nhieu: 14:00 (ly thuyet), 14:05 (job that),
14:10, 14:30 (neu slot dau hong, slot sau don).

Chay voi ratchet=False — dung luat live: stop dat tai muc tinh luc vao lenh, khong doi.

    python scratch/fill_at_placement.py --data-dir data/cache/futures/frozen_sim
        --regime-csv spy_daily_live.csv --end 2024-12-31
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

SLOTS = [(14.0, "14:00 (luat vu trang)"), (14 + 5 / 60, "14:05 (job that)"),
         (14 + 10 / 60, "14:10"), (14.5, "14:30")]


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

    print("\n=== CONG (ratchet=True, vu trang ranh gioi ngay == engine) ===")
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

    def corr(t, inst, H):
        if t["reason"] != "CHANDELIER":
            return 0.0, None
        cache = caches[inst]
        ts, hl = cache.get("ts", {}), cache["hl"]
        d0 = pd.Timestamp(t["day"]).normalize()
        d1 = pd.Timestamp(t["exit_day"]).normalize()
        if d1 != d0 + pd.Timedelta(days=1):
            return 0.0, None
        day_ts = ts.get(d1)
        if day_ts is None or not len(day_ts):
            return 0.0, None
        naive = day_ts.tz_localize(None) if day_ts.tz is not None else day_ts
        arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=H)
        j = int(np.searchsorted(np.asarray(naive), np.datetime64(arm)))
        if j >= len(naive):
            return 0.0, None
        et = pd.Timestamp(t["exit_time"])
        if et.tzinfo is not None:
            et = et.tz_localize(None)
        if et != pd.Timestamp(naive[j]):
            return 0.0, None
        op = float(hl[d1][2][j])
        stp = float(t["exit"])
        w = (stp - op) if t["direction"] == "LONG" else (op - stp)
        return (w * BASKET[inst].point_value, w) if w > 0 else (0.0, None)

    print("\n=== KHOP TAI GIA THI TRUONG LUC DAT LENH (ratchet=False = luat live) ===")
    print("  {:<24} {:>6} {:>12} {:>7} {:>12} {:>13} {:>9}"
          .format("moc dat lenh", "lenh", "P&L tho", "n sua", "tong sua", "P&L da sua",
                  "tv lech"))
    print("  " + "-" * 92)
    for H, nm in SLOTS:
        raw = 0.0
        n = nc = 0
        tc = 0.0
        gaps = []
        for k in dfs:
            tr, _ = run_loop(dfs[k], labels, costs[k], strat=strat, ema_period=ema,
                             mult=mult, max_hold_days=hold, cache=caches[k],
                             same_day_stop=False, stop_slip_ticks=0.0,
                             sig_cache=sigs[k], stop_active_hour=H, ratchet=False)
            for t in tr:
                raw += t["pnl"]
                n += 1
                c, _w = corr(t, k, H)
                if c > 0:
                    nc += 1
                    tc += c
                    gaps.append(c)
        g = np.array(gaps) if gaps else np.array([0.0])
        print("  {:<24} {:>6} {:>12,.0f} {:>7} {:>12,.0f} {:>13,.0f} {:>9,.0f}"
              .format(nm, n, raw, nc, tc, raw - tc, np.median(g)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
