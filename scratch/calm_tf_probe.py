"""Co edge nao trong regime Calm cho nhanh futures khong? — CHI DOC, khong dung engine.

Do DUNG luat TF hien tai (ema30 / chandelier 2.5 / max_hold 5 ngay / cua so 14:00-15:55 /
2-tick), chi doi hai thu:
  1) tap regime duoc phep: production {Normal,Stress}  vs  {Calm}
  2) quy uoc vu trang stop:
       BACKTEST — stop co hieu luc ngay tu ranh gioi ngay ke tiep (engine dang lam vay)
       LIVE     — stop chi len san luc NGAY-KE-TIEP + H gio (Ro 4 that su dat luc 14:05 ET)
Khong doi tham so nao khac.

MO NEO: nhanh production quy uoc BACKTEST phai tai tao dung con so da do lan truoc
(MES 615t/6276 - MNQ 618t/16275 - MYM 644t/6140 - M2K 619t/4002), va rieng MES doi chieu
lai truc tiep voi engine trong lan chay nay.

    python scratch/calm_tf_probe.py --data-dir data/cache/futures/frozen_sim
        --regime-csv spy_daily_live.csv --end 2024-12-31 --stop-active-hour 14
"""
from __future__ import annotations
import argparse, sys
from collections import defaultdict
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

ANCHOR = {"MES": (615, 6276.0), "MNQ": (618, 16275.0),
          "MYM": (644, 6140.0), "M2K": (619, 4002.0)}


def stats(tr):
    if not tr:
        return dict(n=0, pnl=0.0, wr=0.0, pf=0.0, exp=0.0)
    p = [t["pnl"] for t in tr]
    w = [x for x in p if x > 0]
    l = [x for x in p if x <= 0]
    gw = sum(w)
    gl = -sum(l)
    return dict(n=len(p), pnl=sum(p), wr=len(w) / len(p) * 100,
                pf=(gw / gl if gl > 0 else float("inf")), exp=sum(p) / len(p))


def line(tag, s):
    pf = "inf" if s["pf"] == float("inf") else format(s["pf"], ".2f")
    return ("  {:<26} {:>5}t  ${:>10,.0f}  WR {:>5.1f}%  PF {:>5}  exp ${:>8,.2f}"
            .format(tag, s["n"], s["pnl"], s["wr"], pf, s["exp"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--end", default=None)
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--only", default=None)
    ap.add_argument("--stop-active-hour", type=float, default=14.0)
    a = ap.parse_args()

    import pandas as pd
    from futures.basket import SWING_TF_PARAM
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, daily_atr_series, backtest_swing_tf
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache, run_loop

    ema = SWING_TF_PARAM["ema_period"]
    mult = SWING_TF_PARAM["chandelier_atr_mult"]
    hold = SWING_TF_PARAM["max_hold_days"]
    H = a.stop_active_hour
    base = dict(TrendFollowStrategy().config)
    base["ema_period"] = ema
    base["chandelier_atr_mult"] = mult
    prod_regimes = set(base["allowed_regimes"])

    print("=== CO SO DO ===")
    print("  data-dir   " + a.data_dir)
    print("  param      ema={} mult={} max_hold={}d  slippage={} tick/side"
          .format(ema, mult, hold, a.slippage_ticks))
    print("  production allowed_regimes = {}  (nguon: trend_follow.py)".format(sorted(prod_regimes)))
    print("  quy uoc LIVE: stop vu trang luc (ngay vao lenh + 1 ngay) + {:g}h".format(H))

    dfs = load_basket(a.data_dir)
    if a.only:
        dfs = {a.only: dfs[a.only]}
    if a.end:
        cut = pd.Timestamp(a.end)
        for k in list(dfs):
            df = dfs[k]
            c = cut.tz_localize(df.index.tz) if df.index.tz is not None else cut
            dfs[k] = df[df.index <= c]
    labels = basket_labels(a.regime_csv)
    costs = costs_for_basket(slippage_ticks=a.slippage_ticks)
    for k in dfs:
        df = dfs[k]
        print("  {}: {:,} bars  {} .. {}".format(k, len(df), df.index.min().date(),
                                                 df.index.max().date()))

    strat_prod = TrendFollowStrategy(dict(base))
    calm_cfg = dict(base)
    calm_cfg["allowed_regimes"] = ["Calm"]
    strat_calm = TrendFollowStrategy(calm_cfg)

    prod_b, calm_b, prod_l, calm_l = [], [], [], []
    anchor_ok = True
    print("\n=== MO NEO ===")
    for k in dfs:
        df = dfs[k]
        cache = _swing_cache(df, daily_atr_series(df))
        cost = costs[k]
        sig_p = build_sig_cache(cache, labels, strat_prod, ema, prod_regimes)
        sig_c = build_sig_cache(cache, labels, strat_calm, ema, {"Calm"})

        def go(strat, sig, sah):
            tr, _ = run_loop(df, labels, cost, strat=strat, ema_period=ema, mult=mult,
                             max_hold_days=hold, cache=cache, same_day_stop=False,
                             stop_slip_ticks=0.0, sig_cache=sig, stop_active_hour=sah)
            for t in tr:
                t["inst"] = k
            return tr

        pb = go(strat_prod, sig_p, None)
        s = stats(pb)
        if k in ANCHOR:
            en, ep = ANCHOR[k]
            # mo neo ghi tu so DA LAM TRON khi in lan truoc -> dung sai $1, khong phai $0.01
            ok = (s["n"] == en) and abs(s["pnl"] - ep) < 1.0
            anchor_ok = anchor_ok and ok
            print("  {:<4} ghi nhan {:>4}t ${:>10,.0f} | do lai {:>4}t ${:>10,.0f} -> {}"
                  .format(k, en, ep, s["n"], s["pnl"], "MATCH" if ok else "MISMATCH"))
        if k == "MES":
            e = stats(backtest_swing_tf(df, labels, cost, ema_period=ema,
                                        chandelier_atr_mult=mult, max_hold_days=hold))
            ok = (e["n"] == s["n"]) and abs(e["pnl"] - s["pnl"]) < 0.01
            anchor_ok = anchor_ok and ok
            print("  MES  doi chieu engine truc tiep {:>4}t ${:>10,.0f} -> {}"
                  .format(e["n"], e["pnl"], "MATCH" if ok else "MISMATCH"))

        prod_b += pb
        calm_b += go(strat_calm, sig_c, None)
        prod_l += go(strat_prod, sig_p, H)
        calm_l += go(strat_calm, sig_c, H)
        print("  {} xong".format(k))

    # ghi lenh ra dia truoc moi self-check: chay lai het 40 phut, dung de mat du lieu
    out = Path("scratch")
    for nm, pool in (("prod_backtest", prod_b), ("calm_backtest", calm_b),
                     ("prod_live{:g}h".format(H), prod_l), ("calm_live{:g}h".format(H), calm_l)):
        pd.DataFrame(pool).to_csv(out / ("calm_probe_" + nm + ".csv"), index=False)
    print("\n  (da ghi 4 tep lenh vao scratch/calm_probe_*.csv)")

    print("\n=== SELF-CHECKS ===")
    ck = [("SC1 mo neo trung khit", anchor_ok),
          ("SC2 nhanh Calm co lenh", len(calm_b) > 0),
          ("SC3 moi lenh Calm mang nhan Calm",
           all(t["regime"] == "Calm" for t in calm_b + calm_l)),
          ("SC4 khong lenh production nao mang nhan Calm",
           all(t["regime"] != "Calm" for t in prod_b + prod_l)),
          ("SC5 doi quy uoc stop PHAI doi ket qua",
           abs(stats(prod_b)["pnl"] - stats(prod_l)["pnl"]) > 1.0),
          ("SC6 hoan stop thi khong the vao nhieu lenh hon",
           stats(prod_l)["n"] <= stats(prod_b)["n"])]
    for n, p in ck:
        print("  [{}] {}".format("PASS" if p else "FAIL", n))
    if not all(p for _, p in ck):
        print("\n!! SELF-CHECK FAIL — khong doc ket qua ben duoi")
        return 1

    print("\n=== KET QUA (1 hop dong/ma, khong cap danh muc, 2-tick, max_hold 5 ngay) ===")
    print("  -- quy uoc BACKTEST: stop co hieu luc tu ranh gioi ngay ke tiep --")
    print(line("PRODUCTION Normal+Stress", stats(prod_b)))
    print(line("CALM", stats(calm_b)))
    print("\n  -- quy uoc LIVE: stop vu trang ngay-ke-tiep + {:g}h --".format(H))
    print(line("PRODUCTION Normal+Stress", stats(prod_l)))
    print(line("CALM", stats(calm_l)))
    print("\n  -- doi quy uoc stop lam gi --")
    for nm, x, y in (("PRODUCTION", stats(prod_b), stats(prod_l)),
                     ("CALM", stats(calm_b), stats(calm_l))):
        print("  {:<11} ${:>10,.0f} -> ${:>10,.0f}  ({:+10,.0f})   exp ${:>7.2f} -> ${:>7.2f}   n {} -> {}"
              .format(nm, x["pnl"], y["pnl"], y["pnl"] - x["pnl"], x["exp"], y["exp"],
                      x["n"], y["n"]))

    for tag, pool in (("BACKTEST", calm_b), ("LIVE {:g}h".format(H), calm_l)):
        print("\n########## CHI TIET NHANH CALM — quy uoc {} ##########".format(tag))
        print("  -- theo ma --")
        for k in dfs:
            print(line("CALM " + k, stats([t for t in pool if t["inst"] == k])))
        print("  -- theo nam --")
        by = defaultdict(list)
        for t in pool:
            by[t["day"].year].append(t)
        for y in sorted(by):
            print(line("CALM {}".format(y), stats(by[y])))
        print("  -- theo huong --")
        for d in ("LONG", "SHORT"):
            print(line("CALM " + d, stats([t for t in pool if t["direction"] == d])))
        print("  -- theo ly do thoat --")
        rc = defaultdict(list)
        for t in pool:
            rc[t["reason"]].append(t)
        for r in sorted(rc):
            print(line("CALM " + r, stats(rc[r])))

    print("\n########## PRODUCTION theo nam — quy uoc LIVE {:g}h ##########".format(H))
    byp = defaultdict(list)
    for t in prod_l:
        byp[t["day"].year].append(t)
    for y in sorted(byp):
        print(line("PROD {}".format(y), stats(byp[y])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
