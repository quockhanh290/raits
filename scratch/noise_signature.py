"""Co dau hieu nao phan biet CHAM-ROI-HOI voi CHAM-ROI-DI-TIEP khong? — CHI DOC.

Tai moc kiem tra T (gio sau khi vao lenh), voi nhung lenh DANG o ben kia muc stop, ghi:
  - do sau vuot qua muc stop, tinh bang don vi ATR NGAY  (quan sat duoc ngay luc do)
  - bao lau sau khi vao lenh thi cham lan dau
  - regime, huong
Nhan: toi moc vu trang D+1 14:05, gia da HOI ve phia co loi chua?

CANH BAO LY THUYET: neu gia gan nhu buoc ngau nhien thi ty le hoi PHAI giam theo do sau —
do la hinh hoc khuech tan, khong phai tin hieu. Nen bang duoi phai doc kem cot "thoi gian
con lai": cung mot do sau ma con nhieu gio thi de hoi hon. Chi khi nao ty le hoi lech KHOI
quan he do-sau/thoi-gian-con-lai thi moi co thu de khai thac.

    python scratch/noise_signature.py
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
CHECKS = [2.0, 5.0, 10.0]      # gio sau khi vao lenh


def main() -> int:
    from futures.basket import SWING_TF_PARAM, BASKET
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
        idx = df.index.tz_convert("America/New_York").tz_localize(None)
        F = pd.DataFrame({"o": df["open"].to_numpy()}, index=idx)
        F = F[~F.index.duplicated(keep="last")]
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
            try:
                da = float(datr.asof(d0))
            except Exception:
                continue
            if not np.isfinite(da) or da <= 0:
                continue
            # trang thai tai moc vu trang = nhan
            d1 = arm.normalize()
            dts = ts.get(d1)
            if dts is None or not len(dts):
                continue
            naive = dts.tz_localize(None) if dts.tz is not None else dts
            j = int(np.searchsorted(np.asarray(naive), np.datetime64(arm)))
            if j >= len(naive):
                continue
            op_arm = float(hl[d1][2][j])
            past_at_arm = (op_arm < stp0) if LONG else (op_arm > stp0)

            for H in CHECKS:
                tchk = ent + pd.Timedelta(hours=H)
                if tchk >= arm:
                    continue
                seg = F[F.index <= tchk]
                if seg.empty:
                    continue
                px = float(seg["o"].iloc[-1])
                depth = (stp0 - px) if LONG else (px - stp0)
                if depth <= 0:
                    continue          # chua o ben kia muc stop tai moc nay
                rows.append(dict(inst=k, H=H, depth_atr=depth / da,
                                 gio_con_lai=(arm - tchk).total_seconds() / 3600.0,
                                 regime=t["regime"], huong=t["direction"],
                                 khong_hoi=bool(past_at_arm)))
        print("  {} xong".format(k), flush=True)

    R = pd.DataFrame(rows)
    print("\n" + "=" * 92)
    print("TY LE HOI THEO DO SAU (do sau tinh bang ATR NGAY, quan sat tai moc kiem tra)")
    print("=" * 92)
    bins = [0, .05, .1, .2, .35, .6, 10]
    lbl = ["0-0.05", "0.05-0.1", "0.1-0.2", "0.2-0.35", "0.35-0.6", ">0.6"]
    for H in CHECKS:
        S = R[R.H == H]
        if S.empty:
            continue
        S = S.copy()
        S["bucket"] = pd.cut(S.depth_atr, bins=bins, labels=lbl)
        print("\n  --- moc kiem tra: {:.0f} gio sau khi vao lenh "
              "(con {:.1f} gio toi luc vu trang) ---"
              .format(H, S.gio_con_lai.median()))
        print("    {:<10} {:>7} {:>10} {:>12}".format("do sau", "n", "% HOI", "% khong hoi"))
        for b in lbl:
            s = S[S.bucket == b]
            if len(s) < 10:
                continue
            rec = (~s.khong_hoi).mean() * 100
            print("    {:<10} {:>7} {:>9.1f}% {:>11.1f}%".format(b, len(s), rec, 100 - rec))

    print("\n=== THEO REGIME (moc 5 gio) ===")
    S = R[R.H == 5.0]
    for rg in sorted(S.regime.unique()):
        s = S[S.regime == rg]
        print("  {:<8} n={:<5} ty le HOI {:.1f}%".format(rg, len(s), (~s.khong_hoi).mean() * 100))

    print("\n=== THEO HUONG (moc 5 gio) ===")
    for hw in sorted(S.huong.unique()):
        s = S[S.huong == hw]
        print("  {:<6} n={:<5} ty le HOI {:.1f}%".format(hw, len(s), (~s.khong_hoi).mean() * 100))

    print("\n=== DOI CHUNG HINH HOC: do sau chuan hoa theo thoi gian con lai ===")
    print("  (neu chi la khuech tan, ty le hoi se la ham tron cua depth/sqrt(gio con lai))")
    S = R.copy()
    S["z"] = S.depth_atr / np.sqrt(np.maximum(S.gio_con_lai, 0.1) / 24.0)
    zb = [0, .1, .2, .35, .6, 1.0, 10]
    zl = ["0-0.1", "0.1-0.2", "0.2-0.35", "0.35-0.6", "0.6-1.0", ">1.0"]
    S["zb"] = pd.cut(S.z, bins=zb, labels=zl)
    print("    {:<10} {:>7} {:>10}".format("z", "n", "% HOI"))
    for b in zl:
        s = S[S.zb == b]
        if len(s) < 10:
            continue
        print("    {:<10} {:>7} {:>9.1f}%".format(b, len(s), (~s.khong_hoi).mean() * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
