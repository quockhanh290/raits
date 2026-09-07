"""Breaker mù bao nhiêu, và phơi nhiễm ĐỒNG THỜI toàn danh mục là bao nhiêu.

Hai lỗ hổng của mọi bảng đã đo trước đây:

1. BREAKER MÙ. `_book_realised`: *"Realised only, no mark-to-market"*. Trần DD 15% và
   phanh −4%/ngày đọc equity ĐÃ THỰC HIỆN. Một vị thế lỗ tạm $5.000 đóng góp SỐ 0. Nên
   MaxDD trong mọi bảng trước là MaxDD mà BREAKER NHÌN THẤY, không phải sụt vốn thật.

2. PHƠI NHIỄM ĐỒNG THỜI. MAE đo theo TỪNG LỆNH. Rổ 4 là bốn hợp đồng chỉ số Mỹ tương
   quan cao — một cú sốc vĩ mô đánh cả bốn cùng lúc. Tổng phơi nhiễm không phải max của
   từng cái mà là TỔNG, và tương quan chứ không bù trừ.

Đo hai phiên bản, sự thật nằm giữa:
  - `close`  : mark-to-market tại giá đóng cửa mỗi ngày — cùng một khoảnh khắc thật
  - `worst`  : lấy cực trị trong ngày của TỪNG mã rồi cộng — giả định mọi cái tệ nhất
               rơi cùng lúc. Là chặn trên, không phải kỳ vọng.

Sizing: 1 hợp đồng/mã, đúng như contracts_by_inst của live, nên P&L mỗi hợp đồng CHÍNH LÀ
P&L tài khoản.

    python model_portfolio_exposure.py --data-dir data\\cache\\futures --regime-csv spy_daily_live.csv
"""
from __future__ import annotations

import argparse
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import numpy as np
import pandas as pd

ACCOUNT = 50_000.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--activate", type=float, default=None,
                    help="gio kich hoat stop; None = luat engine hien tai")
    a = ap.parse_args()

    from futures.basket import BASKET, SWING_TF_PARAM
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, daily_atr_series
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache, run_loop

    ema = SWING_TF_PARAM["ema_period"]
    mult = SWING_TF_PARAM["chandelier_atr_mult"]
    hold = SWING_TF_PARAM["max_hold_days"]
    strat = TrendFollowStrategy({**TrendFollowStrategy().config,
                                 "ema_period": ema, "chandelier_atr_mult": mult})
    allowed = set(strat.config["allowed_regimes"])
    dfs = load_basket(a.data_dir)
    labels = basket_labels(a.regime_csv)
    costs = costs_for_basket()

    # mtm[day][inst] = (unreal_close, unreal_worst) ; realised[day] += pnl
    mtm_close: dict = defaultdict(dict)
    mtm_worst: dict = defaultdict(dict)
    realised: dict = defaultdict(float)

    for name, df in dfs.items():
        cache = _swing_cache(df, daily_atr_series(df))
        sig = build_sig_cache(cache, labels, strat, ema, allowed)
        trades, _ = run_loop(df, labels, costs[name], strat=strat, ema_period=ema,
                             mult=mult, max_hold_days=hold, cache=cache,
                             same_day_stop=False, stop_slip_ticks=0.0,
                             stop_active_hour=a.activate, sig_cache=sig)
        pv = costs[name].point_value
        hl = cache["hl"]
        for t in trades:
            d0 = pd.Timestamp(t["day"]).normalize()
            d1 = pd.Timestamp(t.get("exit_day") or t["day"]).normalize()
            realised[d1.date()] += t["pnl"]
            entry, sgn = float(t["entry"]), (1 if t["direction"] == "LONG" else -1)
            for day in cache["days"]:
                # NGAY THOAT KHONG TINH. Vi the da bi dong tai muc stop giua ngay, va
                # khoan do da thanh DA THUC HIEN — breaker NHIN THAY no. Ban dau toi
                # tinh ca ngay d1 va lay cuc tri CA NGAY, tuc cong ca phan gia chay
                # tiep sau khi vi the da dong. Ghi khong.
                #
                # Con lai:
                #   d0            stop CHUA vu trang -> phoi nhiem that, khong chan
                #   d0+1..d1-1    stop da vu trang va vi the SONG SOT -> theo dinh
                #                 nghia gia chua cham stop, nen lo tam bi chan boi
                #                 chinh khoang cach stop (~$25-65/hop dong)
                if not (d0 <= day < d1):
                    continue
                arr = hl.get(day)
                if arr is None or not len(arr[0]):
                    continue
                high, low = arr[0], arr[1]
                # đóng cửa ngày = giá bar cuối; xấp xỉ bằng open bar cuối là sai, dùng
                # trung điểm high/low cuối phiên se lech — lay close that tu 1m bars
                last_close = float(arr[2][-1]) if len(arr[2]) else float(high[-1])
                unreal_c = sgn * (last_close - entry) * pv
                worst_px = float(low.min()) if sgn > 0 else float(high.max())
                unreal_w = sgn * (worst_px - entry) * pv
                mtm_close[day.date()][name] = unreal_c
                mtm_worst[day.date()][name] = min(unreal_w, 0.0)

    days = sorted(set(mtm_close) | set(realised))
    eq_real = 0.0
    peak_real = 0.0
    dd_real = 0.0
    peak_true = 0.0
    dd_true_c = dd_true_w = 0.0
    n_open = defaultdict(int)
    worst_sim_c = worst_sim_w = 0.0
    worst_day_c = worst_day_w = None

    for d in days:
        eq_real += realised.get(d, 0.0)
        peak_real = max(peak_real, eq_real)
        dd_real = max(dd_real, peak_real - eq_real)

        opens = mtm_close.get(d, {})
        n_open[len(opens)] += 1
        sim_c = sum(opens.values())
        sim_w = sum(mtm_worst.get(d, {}).values())
        if sim_c < worst_sim_c:
            worst_sim_c, worst_day_c = sim_c, d
        if sim_w < worst_sim_w:
            worst_sim_w, worst_day_w = sim_w, d

        # sut von THAT = da thuc hien + chua thuc hien
        peak_true = max(peak_true, eq_real + max(sim_c, 0.0))
        dd_true_c = max(dd_true_c, peak_true - (eq_real + sim_c))
        dd_true_w = max(dd_true_w, peak_true - (eq_real + sim_w))

    print()
    print("=" * 86)
    print(f"RO 4 — PHOI NHIEM DONG THOI + BREAKER MU"
          f"{'' if a.activate is None else f'  (kich hoat sau {a.activate}h)'}")
    print("=" * 86)
    print("  (ngay thoat KHONG tinh: khoan do da thanh da-thuc-hien, breaker nhin thay)")
    print(f"  So ma mo dong thoi (so ngay):")
    for k in sorted(n_open):
        print(f"    {k} ma: {n_open[k]:>5} ngay  ({100*n_open[k]/sum(n_open.values()):.0f}%)")

    print()
    print(f"  Phoi nhiem dong thoi te nhat:")
    print(f"    theo gia dong cua (cung mot khoanh khac) : ${worst_sim_c:>10,.0f}  "
          f"({abs(worst_sim_c)/ACCOUNT*100:.1f}% tai khoan)  {worst_day_c}")
    print(f"    theo cuc tri trong ngay (chan tren)      : ${worst_sim_w:>10,.0f}  "
          f"({abs(worst_sim_w)/ACCOUNT*100:.1f}% tai khoan)  {worst_day_w}")

    print()
    print(f"  SUT VON — cai breaker nhin thay vs cai co that:")
    print(f"    breaker nhin thay (chi da thuc hien)     : ${dd_real:>10,.0f}  "
          f"({dd_real/ACCOUNT*100:.1f}%)")
    print(f"    that su (+ chua thuc hien, gia dong cua) : ${dd_true_c:>10,.0f}  "
          f"({dd_true_c/ACCOUNT*100:.1f}%)")
    print(f"    that su (+ chua thuc hien, chan tren)    : ${dd_true_w:>10,.0f}  "
          f"({dd_true_w/ACCOUNT*100:.1f}%)")
    print()
    print(f"    => breaker BO SOT: ${dd_true_c - dd_real:>10,.0f} .. "
          f"${dd_true_w - dd_real:,.0f}")
    print(f"    tran DD cung cua he thong: 15% = ${0.15*ACCOUNT:,.0f}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
