"""Cùng phép đo, cho MNKD — sleeve chưa từng được đo.

Bản sửa hoãn STP áp cho cả MNKD dựa trên lập luận cấu trúc: nó chạy CÙNG
`backtest_swing_tf` nên thừa hưởng cùng ngữ nghĩa "stop chỉ xét từ hôm sau". Lập luận
đúng, nhưng đổi hành vi live của một sleeve mà không có lấy một con số thì không đủ.

Khác Rổ 4 ở ba chỗ, nên độ lớn không suy ra được: ema=10 (không phải 30), đồng hồ phiên
Tokyo (cửa sổ vào lệnh 14:00–15:55 JST), và nhãn chế độ SPY trễ 1 ngày.

Dùng lại run_loop đã qua cổng đối chiếu ở model_sameday_stop.py.
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
    ap.add_argument("--nkd-parquet", default="global_index/data/NKD_continuous_1m_8y.parquet")
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--inst", default="MNKD")
    ap.add_argument("--ema", type=int, default=10)
    ap.add_argument("--mult", type=float, default=2.5)
    ap.add_argument("--max-hold", type=int, default=5)
    ap.add_argument("--stop-slip-ticks", type=float, default=1.0)
    ap.add_argument("--activate-after", type=float, nargs="*", default=[0.0, 1.0, 4.0, 8.0])
    a = ap.parse_args()

    from futures._validated_core import _swing_cache, backtest_swing_tf, daily_atr_series
    from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
    from global_index.regime import RegimeLabels, load_spy_regime
    from global_index.specs import SPECS
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import run_loop

    c = SPECS[a.inst]
    ndf = gi_load(a.nkd_parquet)
    ndf.index = ndf.index.tz_convert(c.session_tz)
    labels = RegimeLabels(load_spy_regime(a.regime_csv), lag_days=1)
    cost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
                slippage_ticks_per_side=1.0)
    strat = TrendFollowStrategy({**TrendFollowStrategy().config,
                                 "ema_period": a.ema, "chandelier_atr_mult": a.mult})
    datr = daily_atr_series(ndf)
    cache = _swing_cache(ndf, datr)

    print("\n" + "=" * 78)
    print(f"CỔNG ĐỐI CHIẾU — {a.inst} ema={a.ema} mult={a.mult} hold={a.max_hold}")
    print("=" * 78)
    eng = backtest_swing_tf(ndf, labels, cost, ema_period=a.ema,
                            chandelier_atr_mult=a.mult, max_hold_days=a.max_hold,
                            datr=datr)
    mine, _ = run_loop(ndf, labels, cost, strat=strat, ema_period=a.ema, mult=a.mult,
                       max_hold_days=a.max_hold, cache=cache, same_day_stop=False,
                       stop_slip_ticks=0.0)
    bad = (len(eng) != len(mine)) or any(
        te["day"] != tm["day"] or te["exit_day"] != tm["exit_day"]
        or abs(te["pnl"] - tm["pnl"]) > 0.005 or te["reason"] != tm["reason"]
        for te, tm in zip(eng, mine))
    print(f"  engine {len(eng)} lệnh | bản chép {len(mine)} | {'KHỚP' if not bad else 'LỆCH'}")
    if bad:
        print("\n*** CỔNG KHÔNG ĐẠT — dừng, số sau đó không dùng được ***")
        return 1

    print("\n" + "=" * 78)
    print(f"{a.inst} — P&L theo độ trễ kích hoạt STP (trượt STP {a.stop_slip_ticks:g} tick)")
    print("=" * 78)
    print(f"  {'kích hoạt sau':>14} | {'số lệnh':>8} | {'P&L':>12} | {'thắng':>6} | {'stop-D0':>8}")
    print("  " + "-" * 60)
    for hrs in a.activate_after:
        m, n_sd = run_loop(ndf, labels, cost, strat=strat, ema_period=a.ema, mult=a.mult,
                           max_hold_days=a.max_hold, cache=cache, same_day_stop=True,
                           stop_slip_ticks=a.stop_slip_ticks, activate_after_h=hrs)
        p = sum(t["pnl"] for t in m)
        w = sum(1 for t in m if t["pnl"] > 0)
        print(f"  {hrs:>12.0f}h | {len(m):>8} | ${p:>+11,.0f} | "
              f"{100.0*w/len(m) if m else 0:>5.0f}% | {n_sd:>8}")
    bp = sum(t["pnl"] for t in eng)
    bw = sum(1 for t in eng if t["pnl"] > 0)
    print(f"  {'sang ngày':>13} | {len(eng):>8} | ${bp:>+11,.0f} | "
          f"{100.0*bw/len(eng):>5.0f}% | {0:>8}   (= backtest hiện tại)")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
