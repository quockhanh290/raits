"""Bao nhieu lan cham stop bi XOA trong quang tran, va nhung lenh do thanh cai gi? — CHI DOC.

Mo hinh xoa moi lan gia cat muc stop truoc gio vu trang (dung y do: live khong co lenh tren
san). Cau hoi: viec xoa do cham bao nhieu lenh, va sau khi duoc song tiep thi chung ket thuc
ra sao — thanh lenh thang o tran thoi gian, hay thanh lenh lo o mot muc xa hon?

Muc stop lay tu chinh tin hieu vao lenh (sig["initial_stop"]), chay voi ratchet=False (dung
luat live: stop co dinh) nen muc do khong doi suot doi lenh.

    python scratch/deleted_triggers.py --data-dir data/cache/futures/frozen_sim
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
    from futures._validated_core import _swing_cache, daily_atr_series
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

    for H in (0.0, 14.0):
        tot = defaultdict(lambda: [0, 0.0])     # nhom -> [so lenh, pnl]
        n_all = 0
        pnl_all = 0.0
        n_del = 0
        for k in dfs:
            df = dfs[k]
            cache = _swing_cache(df, daily_atr_series(df))
            sig = build_sig_cache(cache, labels, strat, ema, allowed)
            tr, _ = run_loop(df, labels, costs[k], strat=strat, ema_period=ema, mult=mult,
                             max_hold_days=hold, cache=cache, same_day_stop=False,
                             stop_slip_ticks=0.0, sig_cache=sig, stop_active_hour=H,
                             ratchet=False)
            ts, hl = cache.get("ts", {}), cache["hl"]
            for t in tr:
                n_all += 1
                pnl_all += t["pnl"]
                d0 = pd.Timestamp(t["day"]).normalize()
                hit = sig.get(d0)
                if hit is None:
                    continue
                stp0 = float(hit[1]["initial_stop"])
                arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=H)
                ent = pd.Timestamp(t["entry_time"])
                if ent.tzinfo is not None:
                    ent = ent.tz_localize(None)
                # quet moi bar tu luc vao lenh toi gio vu trang
                crossed = False
                cur = d0
                while cur <= arm.normalize() and not crossed:
                    dts = ts.get(cur)
                    if dts is not None and len(dts):
                        naive = dts.tz_localize(None) if dts.tz is not None else dts
                        m = (np.asarray(naive) > np.datetime64(ent)) & \
                            (np.asarray(naive) < np.datetime64(arm))
                        if m.any():
                            w = np.where(m)[0]
                            if t["direction"] == "LONG":
                                crossed = bool(hl[cur][1][w].min() <= stp0)
                            else:
                                crossed = bool(hl[cur][0][w].max() >= stp0)
                    cur = cur + pd.Timedelta(days=1)
                if crossed:
                    n_del += 1
                    key = "BI XOA cham stop -> " + t["reason"]
                else:
                    key = "khong cham stop trong quang tran -> " + t["reason"]
                tot[key][0] += 1
                tot[key][1] += t["pnl"]

        print("\n" + "=" * 86)
        print("VU TRANG {} (stop co dinh, dung luat live)".format(
            "ranh gioi ngay" if H == 0 else "D+1 14:00"))
        print("=" * 86)
        print("  tong {} lenh  ${:,.0f}".format(n_all, pnl_all))
        print("  so lenh co it nhat MOT lan cham stop bi xoa trong quang tran: {} ({:.1f}%)"
              .format(n_del, n_del / max(n_all, 1) * 100))
        print("  {:<48} {:>6} {:>13}".format("nhom", "lenh", "P&L"))
        for key in sorted(tot):
            print("  {:<48} {:>6} {:>13,.0f}".format(key, tot[key][0], tot[key][1]))
        saved = sum(v[1] for kk, v in tot.items() if kk.startswith("BI XOA"))
        print("  --> tong P&L cua nhom bi xoa cham stop: ${:,.0f}".format(saved))
    return 0


if __name__ == "__main__":
    sys.exit(main())
