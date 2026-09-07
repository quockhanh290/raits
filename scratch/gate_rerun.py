"""Vi sao dot kiem dinh 09/08 khong bat duoc sai lech khop lenh? — CHI DOC.

Dot do ket luan "khoang an han 14-16h qua 4 cua". Chay lai DUNG bon cua ay tren thuoc do
da hieu chinh khop lenh, de chi ra tung cua mu o dau.

Cua 1 — quet nhieu moc, vung cao RONG chu khong nhon
Cua 2 — tach nam, 9/9 nam thang moc ranh gioi ngay
Cua 3 — IS / VAULT (ngoai mau) deu duong
Cua 4 — doi chung co lap: NOI DO RONG stop cu xu NGUOC chieu
Va: walk-forward chon h* (runner ghi h*=14h 6/7 nam) — chay lai tren so da hieu chinh.

Hieu chinh = ap dung dung quy uoc engine cho lenh thoat qua khe ho (khop tai GIA MO) vao
nhung lenh thoat NGAY TAI bar vu trang ma gia mo da nam ben kia muc stop. Doi gia thoat
khong doi thoi diem thoat, nen tru hau ky la tuong duong chinh xac voi sua luat khop lenh.

    python scratch/gate_rerun.py --data-dir data/cache/futures/frozen_sim
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

HOURS = [None, 1.17, 5.0, 9.52, 12.0, 14.0, 16.0, 20.0]
WIDTHS = [1.0, 2.0, 6.0]
VAULT_START, VAULT_END = "2023-01-01", "2024-12-31"


def lab(h):
    return "ranh gioi ngay" if h is None else "{:g}h".format(h)


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

    print("\n=== MO NEO ===")
    anchor_ok = True
    for k in dfs:
        eng = backtest_swing_tf(dfs[k], labels, costs[k], ema_period=ema,
                                chandelier_atr_mult=mult, max_hold_days=hold)
        mine, _ = run_loop(dfs[k], labels, costs[k], strat=strat, ema_period=ema,
                           mult=mult, max_hold_days=hold, cache=caches[k],
                           same_day_stop=False, stop_slip_ticks=0.0, sig_cache=sigs[k])
        ok = (len(eng) == len(mine)
              and abs(sum(t["pnl"] for t in eng) - sum(t["pnl"] for t in mine)) < 0.01)
        anchor_ok = anchor_ok and ok
        print("  {:<4} {:>4}t ${:>10,.0f} -> {}".format(k, len(eng),
              sum(t["pnl"] for t in eng), "MATCH" if ok else "MISMATCH"))
    if not anchor_ok:
        print("!! mo neo hong")
        return 1

    def corr_one(t, inst, H):
        """Do lech khop lenh cua MOT lenh (USD, >0 = mo phong lac quan)."""
        if H is None or t["reason"] != "CHANDELIER":
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

    def sweep(H, width=1.0):
        raw_y, adj_y = defaultdict(float), defaultdict(float)
        raw_p, adj_p = defaultdict(float), defaultdict(float)
        n = ncorr = 0
        tot_c = 0.0
        for k in dfs:
            tr, _ = run_loop(dfs[k], labels, costs[k], strat=strat, ema_period=ema,
                             mult=mult, max_hold_days=hold, cache=caches[k],
                             same_day_stop=False, stop_slip_ticks=0.0,
                             sig_cache=sigs[k], stop_active_hour=H,
                             stop_width_mult=width)
            for t in tr:
                d = str(t.get("exit_day") or t["day"])
                y = d[:4]
                per = ("IS" if d < VAULT_START else "VAULT" if d <= VAULT_END else "POST")
                c = corr_one(t, k, H)
                raw_y[y] += t["pnl"]
                adj_y[y] += t["pnl"] - c
                raw_p[per] += t["pnl"]
                adj_p[per] += t["pnl"] - c
                n += 1
                if c > 0:
                    ncorr += 1
                    tot_c += c
        return dict(n=n, ncorr=ncorr, tot_c=tot_c, raw_y=dict(raw_y), adj_y=dict(adj_y),
                    raw_p=dict(raw_p), adj_p=dict(adj_p),
                    raw=sum(raw_y.values()), adj=sum(adj_y.values()))

    R = {}
    for H in HOURS:
        R[H] = sweep(H)
        print("  quet {} xong".format(lab(H)))

    years = sorted({y for H in HOURS for y in R[H]["raw_y"]})
    b_raw, b_adj = R[None]["raw_y"], R[None]["adj_y"]

    print("\n" + "=" * 104)
    print("CUA 1 + 2 + 3 — CHAY LAI TREN THUOC DO DA HIEU CHINH")
    print("=" * 104)
    print("  {:>15} | {:>6} | {:>11} {:>11} | {:>6} {:>6} | {:>10} {:>10} | {:>10} {:>10}"
          .format("moc", "n sua", "P&L tho", "P&L h/chinh", "nam+", "nam+hc",
                  "IS tho", "IS hc", "VAULT tho", "VAULT hc"))
    print("  " + "-" * 118)
    for H in HOURS:
        r = R[H]
        w_raw = sum(1 for y in years if r["raw_y"].get(y, 0.) > b_raw.get(y, 0.))
        w_adj = sum(1 for y in years if r["adj_y"].get(y, 0.) > b_adj.get(y, 0.))
        print("  {:>15} | {:>6} | {:>11,.0f} {:>11,.0f} | {:>6} {:>6} | {:>10,.0f} {:>10,.0f} "
              "| {:>10,.0f} {:>10,.0f}".format(
                  lab(H), r["ncorr"], r["raw"], r["adj"],
                  "{}/{}".format(w_raw, len(years)), "{}/{}".format(w_adj, len(years)),
                  r["raw_p"].get("IS", 0.), r["adj_p"].get("IS", 0.),
                  r["raw_p"].get("VAULT", 0.), r["adj_p"].get("VAULT", 0.)))

    print("\n  P&L tung nam tai moc 14h: tho -> hieu chinh  (nen so voi ranh gioi ngay)")
    for y in years:
        print("    {}  tho {:>9,.0f} -> hc {:>9,.0f}   | ranh gioi ngay {:>9,.0f}"
              .format(y, R[14.0]["raw_y"].get(y, 0.), R[14.0]["adj_y"].get(y, 0.),
                      b_raw.get(y, 0.)))

    print("\n" + "=" * 104)
    print("CUA 4 — DOI CHUNG 'NOI DO RONG STOP' (kich hoat giu nguyen 1,17h, dung nhu ban goc)")
    print("=" * 104)
    print("  {:>10} | {:>6} | {:>6} | {:>12} {:>12}".format(
        "x do rong", "n", "n sua", "P&L tho", "P&L h/chinh"))
    print("  " + "-" * 60)
    for w in WIDTHS:
        r = sweep(1.17, width=w)
        print("  {:>9.1f}x | {:>6} | {:>6} | {:>12,.0f} {:>12,.0f}".format(
            w, r["n"], r["ncorr"], r["raw"], r["adj"]))

    print("\n" + "=" * 104)
    print("WALK-FORWARD — chon h* tren cac nam TRUOC, do o nam SAU (dung cach model_peak_is_real)")
    print("=" * 104)
    for tag, key in (("THO (nhu dot 09/08)", "raw_y"), ("HIEU CHINH", "adj_y")):
        print("\n  -- {} --".format(tag))
        print("    {:>6} | {:>16} | {:>12}".format("nam", "h* chon tu qua khu", "P&L nam do"))
        tot = 0.0
        picks = []
        for i, y in enumerate(years):
            if i < 2:
                continue
            prev = years[:i]
            hstar = max(HOURS, key=lambda h: sum(R[h][key].get(p, 0.) for p in prev))
            v = R[hstar][key].get(y, 0.)
            tot += v
            picks.append(lab(hstar))
            print("    {:>6} | {:>16} | {:>12,.0f}".format(y, lab(hstar), v))
        print("    TONG ngoai mau: ${:,.0f}   | h* da chon: {}".format(tot, ", ".join(picks)))

    print("\n=== SELF-CHECKS ===")
    ck = [("SC1 mo neo trung khit engine", anchor_ok),
          ("SC2 moc 'ranh gioi ngay' khong bi hieu chinh (doi chung)", R[None]["ncorr"] == 0),
          ("SC3 tong theo nam = tong chung",
           all(abs(sum(R[H]["raw_y"].values()) - R[H]["raw"]) < 1.0 for H in HOURS)),
          ("SC4 ty le lenh bi sua tang theo do tre (1,17h -> 14h)",
           R[1.17]["ncorr"] / R[1.17]["n"] < R[14.0]["ncorr"] / R[14.0]["n"]),
          ("SC5 hieu chinh khong bao gio lam P&L TANG",
           all(R[H]["adj"] <= R[H]["raw"] + 1e-6 for H in HOURS))]
    for n, p in ck:
        print("  [{}] {}".format("PASS" if p else "FAIL", n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
