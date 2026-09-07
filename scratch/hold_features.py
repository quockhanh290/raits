"""Dac trung nao du doan duoc GIU HON CAT? (khong phai 'gia co quay ve khong') — CHI DOC.

Nhan dung: C > A, tuc huy stop giu toi tran 5 ngay co hon cat ngay tai gia thi truong khong.
Ty le nen: 47%. Gan nhu tung dong xu.

Dac trung do tai moc vu trang (deu quan sat duoc luc do, khong nhin tuong lai):
  huong (LONG/SHORT)   — chi so co xu huong di len, hai chieu khong doi xung qua 3-4 ngay
  regime               — Calm/Normal/Stress
  do sau tu muc stop   — da biet la KHONG sap xep duoc, giu de doi chung
  lo chua thuc hien    — khoang cach tu GIA VAO, don vi ATR ngay (khac voi do sau tu stop)
  gia so voi MA50 ngay — boi canh xu huong dai han
  bien dong            — ATR ngay / gia
  ma, nam

NGUONG CAM KET TRUOC: dac trung phai doi ty le "nen giu" >= 10 diem pt so voi nen 47%,
KTC 95% bootstrap THEO NGAY khong chua 0. Va vi dang thu NHIEU dac trung tren cung du lieu,
doc them mot cua: hieu ung phai giu dau o ca hai nua thoi gian.

    python scratch/hold_features.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

ARM = 14 + 5 / 60
MAXHOLD = 5
RNG = np.random.default_rng(7)


def boot(df, ma, mb, n=4000):
    days = df["ngay"].unique()
    out = []
    for _ in range(n):
        pick = RNG.choice(days, size=len(days), replace=True)
        cnt = pd.Series(pick).value_counts()
        s = df[df["ngay"].isin(cnt.index)].copy()
        s["w"] = s["ngay"].map(cnt).astype(float)
        a, b = s[ma(s)], s[mb(s)]
        if a["w"].sum() < 20 or b["w"].sum() < 20:
            continue
        out.append((np.average(a["y"], weights=a["w"])
                    - np.average(b["y"], weights=b["w"])) * 100)
    return np.array(out)


def main() -> int:
    from futures.basket import SWING_TF_PARAM, BASKET
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, daily_atr_series
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache, run_loop

    ema = SWING_TF_PARAM["ema_period"]
    mult = SWING_TF_PARAM["chandelier_atr_mult"]
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

    rows = []
    for k in dfs:
        df = dfs[k]
        datr = daily_atr_series(df)
        cache = _swing_cache(df, datr)
        sig = build_sig_cache(cache, labels, strat, ema, set(cfg["allowed_regimes"]))
        tr, _ = run_loop(df, labels, costs[k], strat=strat, ema_period=ema, mult=mult,
                         max_hold_days=MAXHOLD, cache=cache, same_day_stop=False,
                         stop_slip_ticks=0.0, sig_cache=sig, stop_active_hour=ARM,
                         ratchet=False)
        ts, hl = cache.get("ts", {}), cache["hl"]
        pv = BASKET[k].point_value
        rt = costs[k].round_turn_cost()
        idx = df.index.tz_convert("America/New_York").tz_localize(None)
        FO = pd.Series(df["open"].to_numpy(), index=idx)
        FO = FO[~FO.index.duplicated(keep="last")]
        dclose = pd.Series(df["close"].to_numpy(), index=idx).resample("1D").last().dropna()
        ma50 = dclose.rolling(50).mean()

        for t in tr:
            d0 = pd.Timestamp(t["day"]).normalize()
            hit = sig.get(d0)
            if hit is None:
                continue
            stp = float(hit[1]["initial_stop"])
            entry = float(t["entry"])
            LONG = t["direction"] == "LONG"
            arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=ARM)
            d1 = arm.normalize()
            dts = ts.get(d1)
            if dts is None or not len(dts):
                continue
            naive = dts.tz_localize(None) if dts.tz is not None else dts
            j = int(np.searchsorted(np.asarray(naive), np.datetime64(arm)))
            if j >= len(naive):
                continue
            px = float(hl[d1][2][j])
            if not ((px < stp) if LONG else (px > stp)):
                continue
            try:
                da = float(datr.asof(d0))
                m50 = float(ma50.asof(d0))
            except Exception:
                continue
            if not (np.isfinite(da) and da > 0 and np.isfinite(m50) and m50 > 0):
                continue
            t_max = d0 + pd.Timedelta(days=MAXHOLD)
            nxt = FO[FO.index >= t_max]
            if not len(nxt):
                continue
            px_end = float(nxt.iloc[0])
            A = ((px - entry) if LONG else (entry - px)) * pv - rt
            C = ((px_end - entry) if LONG else (entry - px_end)) * pv - rt
            rows.append(dict(
                inst=k, ngay=str(d0.date()), nam=d0.year, huong=t["direction"],
                regime=t["regime"],
                do_sau=((stp - px) if LONG else (px - stp)) / da,
                lo_atr=((entry - px) if LONG else (px - entry)) / da,
                tren_ma50=1 if px > m50 else 0,
                bien_dong=da / px * 100,
                A=A, C=C, y=1 if C > A else 0, chenh=C - A))
        print("  {} xong".format(k), flush=True)

    R = pd.DataFrame(rows)
    R.to_csv("scratch/hold_features.csv", index=False)
    base = R.y.mean() * 100
    print("\n" + "=" * 92)
    print("NHAN = GIU (huy stop, toi tran 5 ngay) HON CAT ngay")
    print("=" * 92)
    print("  {} lenh | {} ngay | ty le nen 'nen giu' = {:.1f}%".format(
        len(R), R.ngay.nunique(), base))

    def show(name, col, groups):
        print("\n=== {} ===".format(name))
        print("  {:<18} {:>6} {:>11} {:>14}".format("nhom", "n", "% nen giu", "chenh tb/lenh"))
        for lab, m in groups:
            s = R[m(R)]
            if len(s) < 25:
                continue
            print("  {:<18} {:>6} {:>10.1f}% {:>13,.0f}"
                  .format(lab, len(s), s.y.mean() * 100, s.chenh.mean()))

    show("1. HUONG", "huong", [("LONG", lambda d: d.huong == "LONG"),
                                ("SHORT", lambda d: d.huong == "SHORT")])
    show("2. REGIME", "regime", [(r, (lambda r_: (lambda d: d.regime == r_))(r))
                                 for r in sorted(R.regime.unique())])
    show("3. GIA SO VOI MA50 NGAY", "tren_ma50",
         [("tren MA50", lambda d: d.tren_ma50 == 1), ("duoi MA50", lambda d: d.tren_ma50 == 0)])
    qq = R.lo_atr.quantile([.33, .66]).to_list()
    show("4. LO CHUA THUC HIEN (ATR ngay)", "lo_atr",
         [("nho", lambda d: d.lo_atr <= qq[0]),
          ("vua", lambda d: (d.lo_atr > qq[0]) & (d.lo_atr <= qq[1])),
          ("lon", lambda d: d.lo_atr > qq[1])])
    qb = R.bien_dong.quantile([.5]).to_list()
    show("5. BIEN DONG", "bien_dong",
         [("thap", lambda d: d.bien_dong <= qb[0]), ("cao", lambda d: d.bien_dong > qb[0])])

    print("\n" + "=" * 92)
    print("PHIEU QUYET DINH — bootstrap THEO NGAY, nguong >=10 diem pt")
    print("=" * 92)
    tests = [("LONG vs SHORT", lambda d: d.huong == "LONG", lambda d: d.huong == "SHORT"),
             ("tren MA50 vs duoi", lambda d: d.tren_ma50 == 1, lambda d: d.tren_ma50 == 0),
             ("lo lon vs lo nho", lambda d: d.lo_atr > qq[1], lambda d: d.lo_atr <= qq[0]),
             ("bien dong cao vs thap", lambda d: d.bien_dong > qb[0],
              lambda d: d.bien_dong <= qb[0])]
    if "Stress" in set(R.regime):
        tests.append(("Stress vs Normal", lambda d: d.regime == "Stress",
                      lambda d: d.regime == "Normal"))
    for nm, ma, mb in tests:
        b = boot(R, ma, mb)
        if not len(b):
            continue
        lo, hi = np.percentile(b, [2.5, 97.5])
        ok = abs(np.mean(b)) >= 10 and (lo > 0 or hi < 0)
        print("  {:<24} {:+6.1f} diem pt | KTC [{:+6.1f},{:+6.1f}] | {}"
              .format(nm, np.mean(b), lo, hi, "DAT" if ok else "khong dat"))

    print("\n=== CUA THU HAI: hieu ung co giu dau o CA HAI NUA thoi gian khong ===")
    mid = R.nam.median()
    for nm, ma, mb in tests:
        a1 = R[(R.nam <= mid) & ma(R)].y.mean() - R[(R.nam <= mid) & mb(R)].y.mean()
        a2 = R[(R.nam > mid) & ma(R)].y.mean() - R[(R.nam > mid) & mb(R)].y.mean()
        print("  {:<24} nua dau {:+5.1f} diem pt | nua sau {:+5.1f} | {}"
              .format(nm, a1 * 100, a2 * 100,
                      "cung dau" if a1 * a2 > 0 else "DOI DAU"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
