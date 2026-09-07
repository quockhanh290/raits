"""Có phân biệt được 16h với 20h/36h bằng dữ liệu không?

Ba điểm cách nhau $17k và $835 trên một bề mặt dao động ±$25k. Câu hỏi không phải "mốc
nào cao nhất" — mắt thường đọc được — mà là **cái cao nhất đó có thật không**.

Ba phép, từ yếu tới mạnh:

1. LẤY MẪU DÀY (10h→40h, bước 2h). Cấu trúc thật cho hình dạng nhất quán; nhiễu cho
   răng cưa.

2. THỨ HẠNG GIỮA CÁC MÃ. Bốn mã là bốn lần lặp gần độc lập. Nếu 16h > 20h ở cả bốn thì
   khó là ngẫu nhiên; nếu 2-2 thì là tung đồng xu.

3. CHỌN-ĐỈNH CÓ TỔNG QUÁT HOÁ KHÔNG — phép quyết định.
   Với mỗi năm Y: chọn h* = mốc tốt nhất trên các năm TRƯỚC Y, rồi đo h* trong năm Y.
   Không dùng để CHỌN giá trị, mà để kiểm tra bản thân VIỆC CHỌN có đáng tin không.

   h* nhảy loạn qua các năm  -> không có đỉnh ổn định, chuyện kết thúc
   h* ổn định + thắng ngoài mẫu -> đỉnh có thật, và chọn được bằng quy trình

So sánh với hai mốc tham chiếu KHÔNG do P&L chọn ra:
   1.17h  = hiện trạng (slot đêm NKD)
   9.52h  = khe kế tiếp trong lịch (job MAX_HOLD) — thực thi được, không cần cron mới

    python model_peak_is_real.py --data-dir data\\cache\\futures --regime-csv spy_daily_live.csv
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

HOURS = [10, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 40]
REF = {"1.17h hien trang": 1.17, "9.52h khe ke tiep": 9.52}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    a = ap.parse_args()

    from futures.basket import SWING_TF_PARAM
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

    caches, sigs = {}, {}
    for k, df in dfs.items():
        caches[k] = _swing_cache(df, daily_atr_series(df))
        sigs[k] = build_sig_cache(caches[k], labels, strat, ema, allowed)

    all_h = sorted(set(HOURS) | set(REF.values()))
    # pnl[h][year] = tong ; pnl_inst[h][inst] = tong
    pnl: dict = {h: defaultdict(float) for h in all_h}
    pnl_inst: dict = {h: defaultdict(float) for h in all_h}
    for h in all_h:
        for k, df in dfs.items():
            m, _ = run_loop(df, labels, costs[k], strat=strat, ema_period=ema,
                            mult=mult, max_hold_days=hold, cache=caches[k],
                            same_day_stop=False, stop_slip_ticks=0.0,
                            stop_active_hour=float(h), sig_cache=sigs[k])
            for t in m:
                y = str(t.get("exit_day") or t["day"])[:4]
                pnl[h][y] += t["pnl"]
                pnl_inst[h][k] += t["pnl"]

    years = sorted({y for h in all_h for y in pnl[h]})

    print()
    print("=" * 96)
    print("1. LAY MAU DAY — P&L theo tung moc")
    print("=" * 96)
    for h in all_h:
        tot = sum(pnl[h].values())
        bar = "#" * max(0, int(tot / 4000))
        print(f"  {h:>6.2f}h | ${tot:>+10,.0f}  {bar}")

    print()
    print("=" * 96)
    print("2. THU HANG GIUA 4 MA — 16h co hon 20h/36h o TUNG ma khong?")
    print("=" * 96)
    for other in (20, 36):
        if 16 not in pnl_inst or other not in pnl_inst:
            continue
        wins = [k for k in dfs if pnl_inst[16][k] > pnl_inst[other][k]]
        print(f"  16h vs {other}h : 16h thang {len(wins)}/4 ma  ({', '.join(wins) or '-'})")
        for k in dfs:
            print(f"      {k:5s} 16h ${pnl_inst[16][k]:>+9,.0f}  vs  "
                  f"{other}h ${pnl_inst[other][k]:>+9,.0f}")

    print()
    print("=" * 96)
    print("3. CHON-DINH CO TONG QUAT HOA KHONG (chon tren nam TRUOC, do o nam SAU)")
    print("=" * 96)
    print(f"  {'nam':>6} | {'h* chon tren qua khu':>20} | {'P&L nam do':>12} | "
          + " | ".join(f"{n:>18}" for n in REF))
    print("  " + "-" * 96)
    picks, sum_pick = [], 0.0
    sum_ref = {n: 0.0 for n in REF}
    for i, y in enumerate(years):
        if i < 2:
            continue
        prev = years[:i]
        hstar = max(HOURS, key=lambda h: sum(pnl[h][p] for p in prev))
        got = pnl[hstar][y]
        picks.append(hstar)
        sum_pick += got
        row = f"  {y:>6} | {hstar:>19}h | ${got:>+11,.0f}"
        for n, hv in REF.items():
            sum_ref[n] += pnl[hv][y]
            row += f" | ${pnl[hv][y]:>+17,.0f}"
        print(row)
    print("  " + "-" * 96)
    row = f"  {'TONG':>6} | {'':>20} | ${sum_pick:>+11,.0f}"
    for n in REF:
        row += f" | ${sum_ref[n]:>+17,.0f}"
    print(row)
    print()
    print(f"  h* qua cac nam: {picks}")
    print(f"  so gia tri khac nhau: {len(set(picks))}/{len(picks)}  "
          f"-> {'ON DINH' if len(set(picks)) <= 2 else 'NHAY LOAN = khong co dinh that'}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
