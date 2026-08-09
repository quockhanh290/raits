"""Mức stop gửi lên sàn có bằng mức backtest dùng không?

Backtest ratchet: cuối mỗi ngày siết `max(stop, run_full[-1] - mult*ATR)` cho LONG (min
cho SHORT), và TRONG ngày còn siết tiếp qua `stop_prev` tích luỹ. Live thì `stop_price`
chỉ được gán lúc vào lệnh (runner.py:1635) và sau rollover (1093) — không có
`cancel_order` nào phục vụ việc dời stop. Chú thích trong runner nói thẳng: "ratchet
updates are not yet implemented".

Nên live giữ nguyên mức lúc vào lệnh suốt đời lệnh. Vì ratchet chỉ SIẾT CHẶT, stop cố
định của live luôn rộng hơn hoặc bằng — ít bị quét hơn, lệnh chạy lâu hơn. Tốt hay xấu
thì không đoán được, phải đo.

Cả hai nhánh đều dùng luật STP đã sửa (hoãn sang phiên sau), nên khác biệt duy nhất là
ratchet. CỔNG: nhánh ratchet=True phải trùng engine từng lệnh.

    python model_ratchet.py --data-dir data\\cache\\futures --regime-csv spy_daily_live.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    a = ap.parse_args()

    from futures.basket import BASKET, SWING_TF_PARAM
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, backtest_swing_tf, daily_atr_series
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import run_loop

    ema = SWING_TF_PARAM["ema_period"]
    mult = SWING_TF_PARAM["chandelier_atr_mult"]
    hold = SWING_TF_PARAM["max_hold_days"]
    strat = TrendFollowStrategy({**TrendFollowStrategy().config,
                                 "ema_period": ema, "chandelier_atr_mult": mult})
    dfs = load_basket(a.data_dir)
    labels = basket_labels(a.regime_csv)
    costs = costs_for_basket()
    caches = {}

    print()
    print("=" * 78)
    print("CONG DOI CHIEU — ratchet=True, stop sang ngay => phai trung engine")
    print("=" * 78)
    ok = True
    for n in BASKET:
        datr = daily_atr_series(dfs[n])
        caches[n] = _swing_cache(dfs[n], datr)
        eng = backtest_swing_tf(dfs[n], labels, costs[n], ema_period=ema,
                                chandelier_atr_mult=mult, max_hold_days=hold, datr=datr)
        mine, _ = run_loop(dfs[n], labels, costs[n], strat=strat, ema_period=ema,
                           mult=mult, max_hold_days=hold, cache=caches[n],
                           same_day_stop=False, stop_slip_ticks=0.0, ratchet=True)
        bad = (len(eng) != len(mine)) or any(
            e["day"] != m["day"] or abs(e["pnl"] - m["pnl"]) > 0.005
            or e["reason"] != m["reason"] for e, m in zip(eng, mine))
        print(f"  {n}: {len(eng)} lenh | {'KHOP' if not bad else 'LECH'}")
        ok &= not bad
    if not ok:
        print()
        print("*** CONG KHONG DAT — dung ***")
        return 1
    print("  -> dat.")
    print()

    print("=" * 78)
    print("STOP RATCHET (backtest) vs STOP CO DINH O MUC VAO LENH (live)")
    print("=" * 78)
    print(f"  {'nhanh':<40} | {'lenh':>6} | {'P&L':>11} | {'thang':>6} | ly do thoat")
    print("  " + "-" * 92)
    for label, rt in (("backtest: stop ratchet moi ngay", True),
                      ("live: stop co dinh o muc vao lenh", False)):
        tn = tp = tw = 0
        rs = {}
        for n in BASKET:
            m, _ = run_loop(dfs[n], labels, costs[n], strat=strat, ema_period=ema,
                            mult=mult, max_hold_days=hold, cache=caches[n],
                            same_day_stop=False, stop_slip_ticks=0.0, ratchet=rt)
            tn += len(m)
            tp += sum(t["pnl"] for t in m)
            tw += sum(1 for t in m if t["pnl"] > 0)
            for t in m:
                rs[t["reason"]] = rs.get(t["reason"], 0) + 1
        rtxt = "  ".join(f"{k}={v}" for k, v in sorted(rs.items()))
        print(f"  {label:<40} | {tn:>6} | ${tp:>+10,.0f} | "
              f"{100 * tw / tn if tn else 0:>5.0f}% | {rtxt}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
