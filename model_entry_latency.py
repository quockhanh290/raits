"""Độ trễ vào lệnh × độ trễ kích hoạt STP — hai thứ live lệch khỏi backtest, đo cùng nhau.

Bảng trước giả định lệnh khớp ngay tại bar tín hiệu. Không đúng: bar 5 phút phải đóng
(+5), rồi slot mới nhặt được và run_day mới chạy (+L). Đo trên MES 2026-08-07: bar tín
hiệu 14:55–14:59, lệnh gửi 15:10:41 — trễ ~10,7 phút sau khi bar đóng, giá tệ hơn 12 điểm.

Giá vào trượt theo độ trễ; mức stop thì KHÔNG, vì hệ thống tính nó từ bar tín hiệu rồi
gửi nguyên vậy lên sàn. Đó là lý do lệnh MES hôm đó vào ở mức đã vượt qua stop của chính nó.

Dùng lại run_loop đã qua cổng đối chiếu ở model_sameday_stop.py — không dựng vòng lặp mới.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_CWD = Path.cwd()
if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--stop-slip-ticks", type=float, default=1.0)
    ap.add_argument("--latency", type=float, nargs="*", default=[0.0, 5.0, 10.0, 15.0])
    a = ap.parse_args()

    from futures.basket import BASKET, SWING_TF_PARAM
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, backtest_swing_tf, daily_atr_series
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import run_loop

    ema_period = SWING_TF_PARAM["ema_period"]
    mult = SWING_TF_PARAM["chandelier_atr_mult"]
    max_hold = SWING_TF_PARAM["max_hold_days"]
    strat = TrendFollowStrategy({**TrendFollowStrategy().config,
                                 "ema_period": ema_period,
                                 "chandelier_atr_mult": mult})

    dfs = load_basket(a.data_dir)
    labels = basket_labels(a.regime_csv)
    costs = costs_for_basket()
    caches = {}

    print("\n" + "=" * 82)
    print("CỔNG ĐỐI CHIẾU — trễ 0, stop sang ngày ⇒ phải trùng engine từng lệnh")
    print("=" * 82)
    ok = True
    for name in BASKET:
        datr = daily_atr_series(dfs[name])
        caches[name] = _swing_cache(dfs[name], datr)
        eng = backtest_swing_tf(dfs[name], labels, costs[name], ema_period=ema_period,
                                chandelier_atr_mult=mult, max_hold_days=max_hold, datr=datr)
        mine, _ = run_loop(dfs[name], labels, costs[name], strat=strat,
                           ema_period=ema_period, mult=mult, max_hold_days=max_hold,
                           cache=caches[name], same_day_stop=False, stop_slip_ticks=0.0)
        bad = (len(eng) != len(mine)) or any(
            te["day"] != tm["day"] or te["exit_day"] != tm["exit_day"]
            or abs(te["pnl"] - tm["pnl"]) > 0.005 or te["reason"] != tm["reason"]
            for te, tm in zip(eng, mine))
        print(f"  {name}: {len(eng)} lệnh | {'KHỚP' if not bad else 'LỆCH'}")
        ok &= not bad
    if not ok:
        print("\n*** CỔNG KHÔNG ĐẠT — dừng, số sau đó không dùng được ***")
        return 1
    print("  → đạt.\n")

    ARMS = [("STP ngay (0h)", True, 0.0),
            ("STP sau 8h", True, 8.0),
            ("STP sang ngày", False, 0.0)]
    print("=" * 82)
    print(f"P&L theo ĐỘ TRỄ VÀO LỆNH (phút sau khi bar tín hiệu đóng) — trượt STP "
          f"{a.stop_slip_ticks:g} tick")
    print("=" * 82)
    hdr = "  {:<16}".format("kích hoạt STP") + "".join(f"{f'trễ {int(l)}p':>14}" for l in a.latency)
    print(hdr)
    print("  " + "-" * (16 + 14 * len(a.latency)))
    for label, sds, act in ARMS:
        cells = []
        for lat in a.latency:
            tot = 0.0
            for name in BASKET:
                mine, _ = run_loop(dfs[name], labels, costs[name], strat=strat,
                                   ema_period=ema_period, mult=mult,
                                   max_hold_days=max_hold, cache=caches[name],
                                   same_day_stop=sds, stop_slip_ticks=a.stop_slip_ticks,
                                   activate_after_h=act, entry_latency_min=lat)
                tot += sum(t["pnl"] for t in mine)
            cells.append(f"${tot:>+12,.0f}")
        print("  {:<16}".format(label) + "".join(f"{c:>14}" for c in cells))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
