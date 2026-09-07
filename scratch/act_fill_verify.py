"""Dinh 14h cua gio vu trang stop la THAT hay la ao giac cua mo hinh khop lenh? — CHI DOC.

BOI CANH. Live vu trang stop luc D+1 14:00 tren dong ho cua sleeve (runner._ARM_BY_CLUSTER,
Ro 4 = America/New_York 14:00). Moc do do walk-forward chon. Nhung engine mo phong khop
lenh stop TAI MUC STOP moi khi bar cham muc do — ke ca khi thi truong DA di qua muc do tu
truoc, luc chua he co lenh STP nao tren san.

Nghi van co ban: cang hoan lau, cang nhieu lan "toi luc dat stop thi gia da o ben kia".
Live dat STP vao thi truong da xuyen qua => lenh thanh lenh thi truong, khop o gia hien
hanh. Mo phong van ghi muc stop. Neu dung, phan "loi" cua viec hoan chi la phan khop lenh
khong the co that.

Chinh runner da ghi mot dau hieu cua co che nay: vu trang trong gio nghi CME 17-18h ET lam
ty le thoat GAP vot 6% -> 40% va P&L sup +$128.863 -> -$1.091. Do la cung mot tinh huong,
chi khac o cho engine NHIN THAY no (bar co co gap) nen khop tai gia mo. Giua phien thi
engine khong nhin thay, nen khop tai muc stop.

PHEP DO. Quet nhieu moc vu trang. Voi moi moc, tach lam hai con so:
    P&L tho        — dung y engine dang tinh
    P&L hieu chinh — ap DUNG QUY UOC ENGINE DA CO cho lenh thoat qua khe ho (khop tai GIA
                     MO) vao dung nhung lenh thoat ngay tai bar vu trang ma gia mo da o
                     ben kia muc stop
Neu duong cong tho co dinh o 14h ma duong hieu chinh khong co, dinh do la ao giac.

VI SAO HIEU CHINH HAU KY LA DUNG (khong can sua run_loop): doi GIA thoat khong doi THOI
DIEM thoat. Trong run_loop, sau khi dong vi the chi con `exit_ts_today = _et` di tiep;
gia thoat khong tham gia quyet dinh nao sau do. Nen tru phan chenh gia la tuong duong
chinh xac voi viec sua luat khop lenh.

    python scratch/act_fill_verify.py --data-dir data/cache/futures/frozen_sim
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


def stats(tr):
    if not tr:
        return dict(n=0, pnl=0.0, wr=0.0, pf=0.0)
    p = [t["pnl"] for t in tr]
    w = [x for x in p if x > 0]
    gw = sum(w)
    gl = -sum(x for x in p if x <= 0)
    return dict(n=len(p), pnl=sum(p), wr=len(w) / len(p) * 100,
                pf=(gw / gl if gl > 0 else float("inf")))


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
    from global_index.runner import _ARM_BY_CLUSTER

    ema = SWING_TF_PARAM["ema_period"]
    mult = SWING_TF_PARAM["chandelier_atr_mult"]
    hold = SWING_TF_PARAM["max_hold_days"]
    base = dict(TrendFollowStrategy().config)
    base["ema_period"] = ema
    base["chandelier_atr_mult"] = mult
    prod_regimes = set(base["allowed_regimes"])

    print("=== CO SO DO ===")
    print("  gio vu trang cua live (runner._ARM_BY_CLUSTER): {}".format(_ARM_BY_CLUSTER))
    arm_tz, arm_h, arm_m = _ARM_BY_CLUSTER["roska4_swing"]
    arm_hours = arm_h + arm_m / 60.0
    print("  => Ro 4 vu trang D+1 {:02d}:{:02d} {} = {:g}h sau ranh gioi ngay"
          .format(arm_h, arm_m, arm_tz, arm_hours))
    print("  param ema={} mult={} max_hold={}d slippage={} tick/side"
          .format(ema, mult, hold, a.slippage_ticks))
    if arm_hours not in HOURS:
        HOURS.append(arm_hours)

    dfs = load_basket(a.data_dir)
    cut = pd.Timestamp(a.end)
    for k in list(dfs):
        df = dfs[k]
        c = cut.tz_localize(df.index.tz) if df.index.tz is not None else cut
        dfs[k] = df[df.index <= c]
    labels = basket_labels(a.regime_csv)
    costs = costs_for_basket(slippage_ticks=a.slippage_ticks)

    strat_prod = TrendFollowStrategy(dict(base))
    calm_cfg = dict(base)
    calm_cfg["allowed_regimes"] = ["Calm"]
    strat_calm = TrendFollowStrategy(calm_cfg)

    caches, sig_p, sig_c = {}, {}, {}
    for k in dfs:
        caches[k] = _swing_cache(dfs[k], daily_atr_series(dfs[k]))
        sig_p[k] = build_sig_cache(caches[k], labels, strat_prod, ema, prod_regimes)
        sig_c[k] = build_sig_cache(caches[k], labels, strat_calm, ema, {"Calm"})
        print("  cache {} xong".format(k))

    # ── mo neo: quy uoc engine phai trung khit ────────────────────────────────
    print("\n=== MO NEO (stop_active_hour=None phai == backtest_swing_tf) ===")
    anchor_ok = True
    for k in dfs:
        eng = backtest_swing_tf(dfs[k], labels, costs[k], ema_period=ema,
                                chandelier_atr_mult=mult, max_hold_days=hold)
        mine, _ = run_loop(dfs[k], labels, costs[k], strat=strat_prod, ema_period=ema,
                           mult=mult, max_hold_days=hold, cache=caches[k],
                           same_day_stop=False, stop_slip_ticks=0.0, sig_cache=sig_p[k])
        ok = (len(eng) == len(mine)
              and abs(sum(t["pnl"] for t in eng) - sum(t["pnl"] for t in mine)) < 0.01)
        anchor_ok = anchor_ok and ok
        print("  {:<4} engine {:>4}t ${:>10,.0f} | run_loop {:>4}t ${:>10,.0f} -> {}"
              .format(k, len(eng), sum(t["pnl"] for t in eng), len(mine),
                      sum(t["pnl"] for t in mine), "MATCH" if ok else "MISMATCH"))
    if not anchor_ok:
        print("!! mo neo hong — dung")
        return 1

    # ── hieu chinh khop lenh ──────────────────────────────────────────────────
    def correct(trades, inst, H, samples=None):
        """Tra ve (tong hieu chinh USD, so lenh bi hieu chinh, chi tiet do lech)."""
        if H is None:
            return 0.0, 0, []
        cache = caches[inst]
        ts, hl = cache.get("ts", {}), cache["hl"]
        pv = BASKET[inst].point_value
        tot, n, gaps = 0.0, 0, []
        for t in trades:
            if t["reason"] != "CHANDELIER":
                continue          # GAP da khop tai gia mo roi; MAX_HOLD khong lien quan
            d0 = pd.Timestamp(t["day"]).normalize()
            d1 = pd.Timestamp(t["exit_day"]).normalize()
            if d1 != d0 + pd.Timedelta(days=1):
                continue          # chi ngay D+1 moi co cua so tran
            day_ts = ts.get(d1)
            if day_ts is None or not len(day_ts):
                continue
            arm_at = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=H)
            naive = day_ts.tz_localize(None) if day_ts.tz is not None else day_ts
            j = int(np.searchsorted(np.asarray(naive), np.datetime64(arm_at)))
            if j >= len(naive):
                continue
            et = t.get("exit_time")
            if et is None:
                continue
            et = pd.Timestamp(et)
            if et.tzinfo is not None:
                et = et.tz_localize(None)
            if et != pd.Timestamp(naive[j]):
                continue          # khong thoat tai dung bar vu trang -> khong hieu chinh
            op = float(hl[d1][2][j])
            stp = float(t["exit"])
            worse = (stp - op) if t["direction"] == "LONG" else (op - stp)
            if worse <= 0:
                continue          # gia mo chua xuyen qua muc stop -> khop tai stop la hop ly
            tot += worse * pv
            n += 1
            gaps.append(worse * pv)
            if samples is not None and len(samples) < 8:
                samples.append(dict(inst=inst, day=str(d0.date()), dir=t["direction"],
                                    entry=t["entry"], stop_mo_phong=stp, gia_mo=op,
                                    lech_usd=round(worse * pv, 2), pnl_mo_phong=t["pnl"]))
        return tot, n, gaps

    def run_all(strat, sigs, H):
        out = []
        for k in dfs:
            tr, _ = run_loop(dfs[k], labels, costs[k], strat=strat, ema_period=ema,
                             mult=mult, max_hold_days=hold, cache=caches[k],
                             same_day_stop=False, stop_slip_ticks=0.0,
                             sig_cache=sigs[k], stop_active_hour=H)
            for t in tr:
                t["inst"] = k
            out.append((k, tr))
        return out

    print("\n=== QUET MOC VU TRANG — PRODUCTION (Normal+Stress) ===")
    print("  {:>8} {:>6} {:>12} {:>7} {:>8} {:>13} {:>13} {:>7}"
          .format("moc", "n", "P&L tho", "GAP%", "n sua", "tong sua", "P&L hieu chinh", "PF hc"))
    rows = []
    samples = []
    for H in sorted(HOURS, key=lambda x: (-1 if x is None else x)):
        per = run_all(strat_prod, sig_p, H)
        allt = [t for _, tr in per for t in tr]
        s = stats(allt)
        ngap = sum(1 for t in allt if t["reason"] == "GAP")
        tot_c, n_c, gaps = 0.0, 0, []
        for k, tr in per:
            c, nn, g = correct(tr, k, H, samples if H == arm_hours else None)
            tot_c += c
            n_c += nn
            gaps += g
        adj = s["pnl"] - tot_c
        # PF sau hieu chinh: tru phan lech vao chinh cac lenh do (chung deu am san)
        gw = sum(t["pnl"] for t in allt if t["pnl"] > 0)
        gl = -sum(t["pnl"] for t in allt if t["pnl"] <= 0) + tot_c
        pf_adj = gw / gl if gl > 0 else float("inf")
        rows.append(dict(H=H, n=s["n"], pnl=s["pnl"], gappct=ngap / max(s["n"], 1) * 100,
                         nc=n_c, tot_c=tot_c, adj=adj, pf_adj=pf_adj, gaps=gaps))
        print("  {:>8} {:>6} {:>12,.0f} {:>6.1f}% {:>8} {:>13,.0f} {:>13,.0f} {:>7.2f}"
              .format("engine" if H is None else "{:g}h".format(H), s["n"], s["pnl"],
                      ngap / max(s["n"], 1) * 100, n_c, tot_c, adj, pf_adj))

    print("\n=== SELF-CHECKS ===")
    r_none = [r for r in rows if r["H"] is None][0]
    r_arm = [r for r in rows if r["H"] == arm_hours][0]
    ck = [("SC1 mo neo engine trung khit", anchor_ok),
          ("SC2 quy uoc engine gan nhu khong bi hieu chinh (doi chung)",
           r_none["nc"] == 0),
          ("SC3 moc vu trang cua live co bi hieu chinh dang ke", r_arm["nc"] > 50),
          ("SC4 so lenh bi sua tang theo do tre",
           all(rows[i]["nc"] <= rows[i + 1]["nc"] + 5 for i in range(len(rows) - 2))),
          ("SC5 moi do lech deu duong (theo dinh nghia)",
           all(g > 0 for r in rows for g in r["gaps"]))]
    for n, p in ck:
        print("  [{}] {}".format("PASS" if p else "FAIL", n))

    print("\n=== VI DU CU THE tai moc {:g}h (de soi bang mat) ===".format(arm_hours))
    for s in samples:
        print("  {inst} {day} {dir}: vao {entry} | mo phong khop tai stop {stop_mo_phong} "
              "| gia MO cua bar vu trang {gia_mo} | lech ${lech_usd} | pnl mo phong {pnl_mo_phong}"
              .format(**s))

    print("\n=== PHAN BO DO LECH tai moc {:g}h ===".format(arm_hours))
    g = np.array(r_arm["gaps"]) if r_arm["gaps"] else np.array([0.0])
    print("  n={} | trung vi ${:,.2f} | tb ${:,.2f} | p95 ${:,.2f} | max ${:,.2f}"
          .format(len(g), np.median(g), g.mean(), np.percentile(g, 95), g.max()))

    print("\n=== CALM tai moc vu trang cua live ({:g}h) ===".format(arm_hours))
    per = run_all(strat_calm, sig_c, arm_hours)
    allc = [t for _, tr in per for t in tr]
    sc = stats(allc)
    totc, nc = 0.0, 0
    for k, tr in per:
        c, nn, _g = correct(tr, k, arm_hours)
        totc += c
        nc += nn
    print("  tho          {:>5}t  ${:>10,.0f}  PF {:.2f}".format(sc["n"], sc["pnl"], sc["pf"]))
    print("  sua {:>3} lenh, tong sua ${:,.0f}".format(nc, totc))
    print("  HIEU CHINH               ${:>10,.0f}".format(sc["pnl"] - totc))
    by = defaultdict(float)
    byn = defaultdict(float)
    for k, tr in per:
        c_by = defaultdict(float)
        for t in tr:
            byn[pd.Timestamp(t["day"]).year] += t["pnl"]
        cache = caches[k]
        ts, hl = cache.get("ts", {}), cache["hl"]
        pv = BASKET[k].point_value
        for t in tr:
            if t["reason"] != "CHANDELIER":
                continue
            d0 = pd.Timestamp(t["day"]).normalize()
            d1 = pd.Timestamp(t["exit_day"]).normalize()
            if d1 != d0 + pd.Timedelta(days=1):
                continue
            day_ts = ts.get(d1)
            if day_ts is None or not len(day_ts):
                continue
            naive = day_ts.tz_localize(None) if day_ts.tz is not None else day_ts
            arm_at = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=arm_hours)
            j = int(np.searchsorted(np.asarray(naive), np.datetime64(arm_at)))
            if j >= len(naive):
                continue
            et = pd.Timestamp(t["exit_time"])
            if et.tzinfo is not None:
                et = et.tz_localize(None)
            if et != pd.Timestamp(naive[j]):
                continue
            op = float(hl[d1][2][j])
            stp = float(t["exit"])
            worse = (stp - op) if t["direction"] == "LONG" else (op - stp)
            if worse > 0:
                c_by[d0.year] += worse * pv
        for y, v in c_by.items():
            by[y] += v
    print("  -- theo nam: tho -> hieu chinh --")
    for y in sorted(byn):
        print("     {}  ${:>9,.0f} -> ${:>9,.0f}".format(y, byn[y], byn[y] - by.get(y, 0.0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
