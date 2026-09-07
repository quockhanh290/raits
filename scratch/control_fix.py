"""SUA LOI TRONG CHINH PHEP KIEM CUA TOI — CHI DOC.

Lan truoc toi bao "quy uoc engine bi hieu chinh 0 lenh" va goi do la doi chung. Sai:
ham hieu chinh cua toi co dong `if H is None: return 0.0`, nen doi chung PASS theo cau
tao chu khong phai theo do luong.

Engine CUNG co quang tran: vi the vao luc 14:00-15:55 ngay D chi bat dau bi xet stop tu
ngay D+1, tuc ~8-10 tieng khong co lenh dung. Do dem histogram: 24% so lenh thoat ngay
trong PHUT DAU của D+1, tat ca deu khop tai muc stop. Neu gia da o ben kia muc do luc
nua dem thi engine cung dang khop mot muc khong the co.

Bai nay chay lai ca dai voi H=0.0 (= dung ranh gioi ngay, tuong duong engine) de doi
chung la doi chung THAT, va de so sanh moi cot tren CUNG mot co so.

CONG: H=0.0 phai tai tao trung khit backtest_swing_tf (chung minh 0.0 == quy uoc engine).

    python scratch/control_fix.py --data-dir data/cache/futures/frozen_sim
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

HOURS = [0.0, 1.17, 5.0, 9.52, 12.0, 14.0, 16.0, 20.0]
VAULT_START, VAULT_END = "2023-01-01", "2024-12-31"


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

    def corr_one(t, inst, H):
        """Do lech khop lenh. KHONG con loi tat theo H — H=0.0 cung duoc do that."""
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
        arm_at = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=H)
        j = int(np.searchsorted(np.asarray(naive), np.datetime64(arm_at)))
        if j >= len(naive):
            return 0.0
        et = pd.Timestamp(t["exit_time"])
        if et.tzinfo is not None:
            et = et.tz_localize(None)
        if et != pd.Timestamp(naive[j]):
            return 0.0
        op = float(hl[d1][2][j])
        stp = float(t["exit"])
        worse = (stp - op) if t["direction"] == "LONG" else (op - stp)
        return worse * BASKET[inst].point_value if worse > 0 else 0.0

    # ── cong: H=0.0 phai == engine ────────────────────────────────────────────
    print("\n=== CONG: H=0.0 co dung la quy uoc engine khong? ===")
    ok_all = True
    for k in dfs:
        eng = backtest_swing_tf(dfs[k], labels, costs[k], ema_period=ema,
                                chandelier_atr_mult=mult, max_hold_days=hold)
        z, _ = run_loop(dfs[k], labels, costs[k], strat=strat, ema_period=ema, mult=mult,
                        max_hold_days=hold, cache=caches[k], same_day_stop=False,
                        stop_slip_ticks=0.0, sig_cache=sigs[k], stop_active_hour=0.0)
        ok = (len(eng) == len(z)
              and abs(sum(t["pnl"] for t in eng) - sum(t["pnl"] for t in z)) < 0.01)
        ok_all = ok_all and ok
        print("  {:<4} engine {:>4}t ${:>10,.0f} | H=0.0 {:>4}t ${:>10,.0f} -> {}"
              .format(k, len(eng), sum(t["pnl"] for t in eng), len(z),
                      sum(t["pnl"] for t in z), "MATCH" if ok else "MISMATCH"))
    if not ok_all:
        print("!! H=0.0 khong tuong duong engine — dung, doi chung khong dung duoc")
        return 1

    print("\n=== QUET — MOI COT DEU DUOC HIEU CHINH BANG CUNG MOT BO PHAT HIEN ===")
    print("  {:>8} | {:>6} | {:>6} {:>6} | {:>12} {:>13} | {:>10} {:>10}"
          .format("moc", "n", "n sua", "%sua", "P&L tho", "P&L h/chinh", "IS hc", "VAULT hc"))
    print("  " + "-" * 92)
    res = {}
    for H in HOURS:
        raw_y, adj_y = defaultdict(float), defaultdict(float)
        raw_p, adj_p = defaultdict(float), defaultdict(float)
        n = nc = 0
        tot_c = 0.0
        gaps = []
        for k in dfs:
            tr, _ = run_loop(dfs[k], labels, costs[k], strat=strat, ema_period=ema,
                             mult=mult, max_hold_days=hold, cache=caches[k],
                             same_day_stop=False, stop_slip_ticks=0.0,
                             sig_cache=sigs[k], stop_active_hour=H)
            for t in tr:
                d = str(t.get("exit_day") or t["day"])
                per = ("IS" if d < VAULT_START else "VAULT" if d <= VAULT_END else "POST")
                c = corr_one(t, k, H)
                raw_y[d[:4]] += t["pnl"]
                adj_y[d[:4]] += t["pnl"] - c
                raw_p[per] += t["pnl"]
                adj_p[per] += t["pnl"] - c
                n += 1
                if c > 0:
                    nc += 1
                    tot_c += c
                    gaps.append(c)
        res[H] = dict(n=n, nc=nc, tot_c=tot_c, raw=sum(raw_y.values()),
                      adj=sum(adj_y.values()), raw_y=dict(raw_y), adj_y=dict(adj_y),
                      raw_p=dict(raw_p), adj_p=dict(adj_p), gaps=gaps)
        r = res[H]
        print("  {:>8} | {:>6} | {:>6} {:>5.1f}% | {:>12,.0f} {:>13,.0f} | {:>10,.0f} {:>10,.0f}"
              .format("{:g}h".format(H), n, nc, nc / n * 100, r["raw"], r["adj"],
                      r["adj_p"].get("IS", 0.), r["adj_p"].get("VAULT", 0.)))

    print("\n=== DO LECH TRUNG VI / P95 THEO MOC ===")
    for H in HOURS:
        g = np.array(res[H]["gaps"]) if res[H]["gaps"] else np.array([0.0])
        print("  {:>6g}h  n={:>4}  trung vi ${:>7,.0f}  p95 ${:>8,.0f}  max ${:>8,.0f}  tong ${:>10,.0f}"
              .format(H, len(res[H]["gaps"]), np.median(g), np.percentile(g, 95), g.max(),
                      res[H]["tot_c"]))

    print("\n=== P&L HIEU CHINH THEO NAM ===")
    years = sorted({y for H in HOURS for y in res[H]["adj_y"]})
    print("  {:>8} | ".format("moc") + " | ".join("{:>8}".format(y) for y in years))
    for H in HOURS:
        print("  {:>8} | ".format("{:g}h".format(H))
              + " | ".join("{:>8,.0f}".format(res[H]["adj_y"].get(y, 0.)) for y in years))

    print("\n=== WALK-FORWARD tren so DA HIEU CHINH (moi cot cung co so) ===")
    print("    {:>6} | {:>10} | {:>12}".format("nam", "h* chon", "P&L nam do"))
    tot = 0.0
    picks = []
    for i, y in enumerate(years):
        if i < 2:
            continue
        prev = years[:i]
        hstar = max(HOURS, key=lambda h: sum(res[h]["adj_y"].get(p, 0.) for p in prev))
        v = res[hstar]["adj_y"].get(y, 0.)
        tot += v
        picks.append("{:g}h".format(hstar))
        print("    {:>6} | {:>10} | {:>12,.0f}".format(y, "{:g}h".format(hstar), v))
    print("    TONG ngoai mau ${:,.0f} | h*: {}".format(tot, ", ".join(picks)))

    print("\n=== SELF-CHECKS ===")
    ck = [("SC1 H=0.0 == engine", ok_all),
          ("SC2 DOI CHUNG THAT: moc 0h VAN bi hieu chinh (khong phai 0 theo cau tao)",
           res[0.0]["nc"] > 0),
          ("SC3 ty le lenh bi sua tang tu 0h den 14h",
           res[0.0]["nc"] / res[0.0]["n"] < res[14.0]["nc"] / res[14.0]["n"]),
          ("SC4 hieu chinh khong bao gio lam P&L tang",
           all(res[H]["adj"] <= res[H]["raw"] + 1e-6 for H in HOURS))]
    for nm, p in ck:
        print("  [{}] {}".format("PASS" if p else "FAIL", nm))
    return 0


if __name__ == "__main__":
    sys.exit(main())
