"""Stop tinh THANG tu ATR NGAY thay vi ATR 5 phut — CHI DOC.

Phan A da do: khoang cach stop hien nay = 1/21 den 1/23 dai danh nghia (mult x ATR ngay),
tuc ~0,12 x ATR ngay. Lenh giu 5 ngay dang dung muc dung do bang nhip 5 phut.

Bai nay thay THANG: initial_stop = entry -+ f x ATR_ngay(as-of ngay vao lenh), quet f.
`atr` trong generate_signal CHI dung de tinh initial_stop (doc code: dong 416), khong tham
gia dieu kien vao lenh — nen ghi de initial_stop giu NGUYEN tap lenh, chi doi muc dung.
Do la phep so sach, khac han voi quet stop_width_mult (nhan len tu muc 5 phut, giu nguyen
do phan tan cua no).

f = 2,5 chinh la dai danh nghia day du — cung la mau so ma sizing dang dung
(risk_sized = n x mult x ATR_ngay x point_value). Tuc o f=2,5 thi rui ro that cua lenh
lan dau khop voi rui ro ma bo sizing gia dinh.

Muc tieu do = P&L DA SUA KHOP LENH. Vu trang D+1 14:05, ratchet=False (luat live).
Moc mem: f=0,12 nen ra gan cau hinh hien tai (~2.018 lenh, ~$9.5k da sua).

    python scratch/daily_atr_stop.py --data-dir data/cache/futures/frozen_sim
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

FRACS = [0.12, 0.25, 0.5, 0.75, 1.0, 1.5, 2.5]
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

    def make_sig(k, f):
        """Ban sao sig cache voi initial_stop = entry -+ f x ATR ngay. Tap lenh giu nguyen."""
        out = {}
        for day, (ts_, sg) in sigs[k].items():
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

    print("\n" + "=" * 96)
    print("STOP = f x ATR NGAY  (vu trang D+1 14:05, stop co dinh, muc tieu = P&L DA SUA)")
    print("=" * 96)
    print("  {:>6} | {:>6} | {:>12} {:>12} | {:>6} {:>11} | {:>6} | {:>26}"
          .format("f", "lenh", "P&L tho", "P&L da sua", "n sua", "tong sua", "PF sua",
                  "ly do thoat"))
    print("  " + "-" * 108)
    adj_y = {}
    for f in FRACS:
        ry, ay = defaultdict(float), defaultdict(float)
        n = nc = 0
        tc = 0.0
        gw = gl = 0.0
        reasons = defaultdict(int)
        for k in dfs:
            sg = make_sig(k, f)
            tr, _ = run_loop(dfs[k], labels, costs[k], strat=strat, ema_period=ema,
                             mult=mult, max_hold_days=hold, cache=caches[k],
                             same_day_stop=False, stop_slip_ticks=0.0,
                             sig_cache=sg, stop_active_hour=ARM, ratchet=False)
            for t in tr:
                y = str(t.get("exit_day") or t["day"])[:4]
                c = corr_one(t, k)
                ry[y] += t["pnl"]
                ay[y] += t["pnl"] - c
                p = t["pnl"] - c
                if p > 0:
                    gw += p
                else:
                    gl -= p
                n += 1
                reasons[t["reason"]] += 1
                if c > 0:
                    nc += 1
                    tc += c
        adj_y[f] = dict(ay)
        pf = gw / gl if gl > 0 else float("inf")
        rs = "CH {} / MH {} / GAP {}".format(reasons.get("CHANDELIER", 0),
                                             reasons.get("MAX_HOLD", 0),
                                             reasons.get("GAP", 0))
        print("  {:>6.2f} | {:>6} | {:>12,.0f} {:>12,.0f} | {:>6} {:>11,.0f} | {:>6.2f} | {:>26}"
              .format(f, n, sum(ry.values()), sum(ay.values()), nc, tc, pf, rs))

    years = sorted({y for f in FRACS for y in adj_y[f]})
    print("\n=== P&L DA SUA THEO NAM ===")
    print("  {:>6} | ".format("f") + " | ".join("{:>8}".format(y) for y in years))
    for f in FRACS:
        print("  {:>6.2f} | ".format(f)
              + " | ".join("{:>8,.0f}".format(adj_y[f].get(y, 0.)) for y in years))

    print("\n=== WALK-FORWARD tren P&L DA SUA ===")
    tot = 0.0
    picks = []
    for i, y in enumerate(years):
        if i < 2:
            continue
        prev = years[:i]
        best = max(FRACS, key=lambda f: sum(adj_y[f].get(p, 0.) for p in prev))
        v = adj_y[best].get(y, 0.)
        tot += v
        picks.append("{:g}".format(best))
        print("    {} | chon f={:<5} | P&L nam do {:>10,.0f}".format(y, best, v))
    print("    TONG ngoai mau ${:,.0f} | da chon: {}".format(tot, ", ".join(picks)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
