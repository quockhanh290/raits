"""Cu quet mac stop: gio nao, va co dong thoi ca ro khong? — CHI DOC.

Su kien = lan DAU TIEN gia cat qua muc stop ban dau, trong quang tran.
Do sau tai khoanh khac do = 0 voi MOI su kien -> bien gay nhieu lon nhat tu bi khu.
Con phai kiem soat: THOI GIAN CON LAI toi moc vu trang.

Hai dac trung:
  1. GIO trong ngay (ET) cua cu cat
  2. DONG THOI CA RO: loi nhuan 15 phut cua BA ma con lai ngay truoc khoanh khac do, doi dau
     sao cho duong = cung chieu bat loi voi vi the. Cao = ca thi truong di; thap/am =
     cu nhoi rieng le cua mot ma.

Nhan: toi moc vu trang D+1 14:05, gia da HOI ve phia co loi chua?

NGUONG CAM KET TRUOC: dac trung phai lam ty le hoi lech >= 10 diem phan tram, voi khoang
tin cay 95% bootstrap THEO NGAY khong chua 0. Duoi nguong -> dong huong.

    python scratch/sweep_signature.py
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
RNG = np.random.default_rng(42)


def boot_day(df, mask_a, mask_b, n=4000):
    """Chenh ty le hoi giua hai nhom, bootstrap theo NGAY."""
    days = df["ngay"].unique()
    out = []
    for _ in range(n):
        pick = RNG.choice(days, size=len(days), replace=True)
        s = df[df["ngay"].isin(pick)]
        # lay lai theo tan suat: dung merge de nhan ban ngay duoc chon nhieu lan
        cnt = pd.Series(pick).value_counts()
        w = s["ngay"].map(cnt).astype(float)
        a = s[mask_a(s)]
        b = s[mask_b(s)]
        wa, wb = w[a.index], w[b.index]
        if wa.sum() < 20 or wb.sum() < 20:
            continue
        ra = np.average(a["hoi"].to_numpy(), weights=wa.to_numpy())
        rb = np.average(b["hoi"].to_numpy(), weights=wb.to_numpy())
        out.append((ra - rb) * 100)
    return np.array(out)


def main() -> int:
    from futures.basket import SWING_TF_PARAM
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

    # chuoi close 1 phut theo gio ET cho ca 4 ma, de do dong thoi
    CL = {}
    for k in dfs:
        idx = dfs[k].index.tz_convert("America/New_York").tz_localize(None)
        s = pd.Series(dfs[k]["close"].to_numpy(), index=idx)
        CL[k] = s[~s.index.duplicated(keep="last")]

    rows = []
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
        for t in tr:
            d0 = pd.Timestamp(t["day"]).normalize()
            hit = sig.get(d0)
            if hit is None:
                continue
            stp0 = float(hit[1]["initial_stop"])
            ent = pd.Timestamp(t["entry_time"])
            if ent.tzinfo is not None:
                ent = ent.tz_localize(None)
            arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=ARM)
            LONG = t["direction"] == "LONG"

            cross_at = None
            cur = d0
            while cur <= arm.normalize() and cross_at is None:
                dts = ts.get(cur)
                if dts is not None and len(dts):
                    naive = dts.tz_localize(None) if dts.tz is not None else dts
                    arr = np.asarray(naive)
                    m = (arr > np.datetime64(ent)) & (arr < np.datetime64(arm))
                    if m.any():
                        w = np.where(m)[0]
                        c = (np.where(hl[cur][1][w] <= stp0)[0] if LONG
                             else np.where(hl[cur][0][w] >= stp0)[0])
                        if len(c):
                            cross_at = pd.Timestamp(naive[w[c[0]]])
                cur = cur + pd.Timedelta(days=1)
            if cross_at is None:
                continue

            d1 = arm.normalize()
            dts = ts.get(d1)
            if dts is None or not len(dts):
                continue
            naive = dts.tz_localize(None) if dts.tz is not None else dts
            j = int(np.searchsorted(np.asarray(naive), np.datetime64(arm)))
            if j >= len(naive):
                continue
            op_arm = float(hl[d1][2][j])
            past = (op_arm < stp0) if LONG else (op_arm > stp0)

            # dong thoi ca ro: loi nhuan 15 phut cua 3 ma con lai, doi dau theo bat loi
            others = []
            for k2 in dfs:
                if k2 == k:
                    continue
                s = CL[k2]
                try:
                    p1 = float(s.asof(cross_at))
                    p0 = float(s.asof(cross_at - pd.Timedelta(minutes=15)))
                except Exception:
                    continue
                if not (np.isfinite(p0) and np.isfinite(p1)) or p0 <= 0:
                    continue
                r = (p1 / p0 - 1.0)
                others.append(-r if LONG else r)     # duong = cung chieu bat loi
            if len(others) < 2:
                continue

            rows.append(dict(ngay=str(d0.date()), inst=k, gio=cross_at.hour,
                             dong_thoi=float(np.mean(others)) * 10000,   # bps
                             gio_con_lai=(arm - cross_at).total_seconds() / 3600.0,
                             hoi=0 if past else 1))
        print("  {} xong".format(k), flush=True)

    R = pd.DataFrame(rows)
    print("\n" + "=" * 92)
    print("SU KIEN: lan dau gia cat qua muc stop trong quang tran")
    print("=" * 92)
    print("  {} su kien tren {} ngay khac nhau | ty le HOI chung {:.1f}%"
          .format(len(R), R.ngay.nunique(), R.hoi.mean() * 100))

    print("\n=== 1. THEO GIO TRONG NGAY (ET) ===")
    R["khung"] = pd.cut(R.gio, [-1, 3, 8, 9, 11, 15, 24],
                        labels=["00-03 dem", "04-08 chau Au", "09 mo cua My",
                                "10-11", "12-15 phien My", "16-23 toi"])
    print("  {:<16} {:>6} {:>9} {:>14}".format("khung gio", "n", "% HOI", "gio con lai tv"))
    for b in R.khung.cat.categories:
        s = R[R.khung == b]
        if len(s) < 20:
            continue
        print("  {:<16} {:>6} {:>8.1f}% {:>13.1f}".format(b, len(s), s.hoi.mean() * 100,
                                                          s.gio_con_lai.median()))

    print("\n=== 2. THEO DONG THOI CA RO (bps, 15 phut, 3 ma con lai) ===")
    q = R.dong_thoi.quantile([.2, .4, .6, .8]).to_list()
    R["db"] = pd.cut(R.dong_thoi, [-1e9] + q + [1e9],
                     labels=["Q1 nguoc lai", "Q2", "Q3", "Q4", "Q5 ca ro cung di"])
    print("  {:<18} {:>6} {:>9} {:>14}".format("nhom", "n", "% HOI", "gio con lai tv"))
    for b in R.db.cat.categories:
        s = R[R.db == b]
        print("  {:<18} {:>6} {:>8.1f}% {:>13.1f}".format(b, len(s), s.hoi.mean() * 100,
                                                          s.gio_con_lai.median()))

    print("\n=== 3. KIEM CO DIEU KIEN TREN THOI GIAN CON LAI ===")
    R["tb"] = pd.cut(R.gio_con_lai, [-1, 12, 18, 24, 100],
                     labels=["<12h", "12-18h", "18-24h", ">24h"])
    print("  {:<18} {:<10} {:>6} {:>9}".format("dong thoi", "gio con lai", "n", "% HOI"))
    for b in R.db.cat.categories:
        for tb in R.tb.cat.categories:
            s = R[(R.db == b) & (R.tb == tb)]
            if len(s) < 25:
                continue
            print("  {:<18} {:<10} {:>6} {:>8.1f}%".format(b, tb, len(s), s.hoi.mean() * 100))

    print("\n=== 4. PHIEU QUYET DINH — bootstrap THEO NGAY ===")
    lo_hi = R.db.cat.categories
    d = boot_day(R, lambda s: s.db == lo_hi[0], lambda s: s.db == lo_hi[-1])
    if len(d):
        print("  chenh ty le HOI: [nhom nguoc lai] tru [nhom ca ro cung di]")
        print("    diem uoc luong {:+.1f} diem pt | KTC 95% [{:+.1f}, {:+.1f}] | n bootstrap {}"
              .format(np.mean(d), np.percentile(d, 2.5), np.percentile(d, 97.5), len(d)))
        ok = abs(np.mean(d)) >= 10 and (np.percentile(d, 2.5) > 0 or np.percentile(d, 97.5) < 0)
        print("    NGUONG CAM KET TRUOC (>=10 diem pt va KTC khong chua 0): {}"
              .format("DAT" if ok else "KHONG DAT"))
    dn = boot_day(R, lambda s: s.khung == "00-03 dem", lambda s: s.khung == "12-15 phien My")
    if len(dn):
        print("\n  chenh ty le HOI: [quet luc 00-03 dem] tru [quet luc 12-15 phien My]")
        print("    diem uoc luong {:+.1f} diem pt | KTC 95% [{:+.1f}, {:+.1f}]"
              .format(np.mean(dn), np.percentile(dn, 2.5), np.percentile(dn, 97.5)))
        ok2 = abs(np.mean(dn)) >= 10 and (np.percentile(dn, 2.5) > 0 or np.percentile(dn, 97.5) < 0)
        print("    NGUONG CAM KET TRUOC: {}".format("DAT" if ok2 else "KHONG DAT"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
