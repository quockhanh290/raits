"""Khe hở kích hoạt stop có bền không — tách theo năm và so trên giai đoạn vault.

KHÔNG chạy WFO. WFO là công cụ để CHỌN tham số; ở đây không chọn gì — 09:31 là thứ hệ
thống đang làm sẵn (hệ quả phụ của job MAX_HOLD, không phải mốc được thiết kế). Đưa mốc
kích hoạt vào lưới tìm kiếm sẽ mở rộng không gian và làm tăng nguy cơ overfit, chứ không
xác nhận được gì. Và nếu WFO chọn ra một giờ khác thì ta cũng không đổi — đổi theo đỉnh
backtest chính là curve fitting.

Hai phép kiểm trả lời đúng câu cần hỏi:

  1. TÁCH THEO NĂM — +$46k dồn vào một năm (một sự kiện) hay trải đều (một quy luật)?
  2. GIAI ĐOẠN VAULT (2023-2024, OOS) — so hai luật CỐ ĐỊNH, đã nêu trước, trên dữ liệu
     giữ riêng. Không phải curve fitting: curve fitting là dùng dữ liệu để CHỌN; ở đây
     chỉ kiểm hai quy tắc đã có sẵn.

Kết quả quyết định ta VIẾT gì, không phải ta CHẠY gì:
  - thắng đều + thắng trên vault  → giữ câu mạnh "đừng bịt khe hở, đã đo"
  - dồn một năm, hoặc thua vault  → hạ xuống "khe hở này không gây hại", bỏ số +$46k

    python model_gap_robustness.py --data-dir data\\cache\\futures --regime-csv spy_daily_live.csv
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

VAULT_START, VAULT_END = "2023-01-01", "2024-12-31"


def _year(t):
    return str(t.get("exit_day") or t["day"])[:4]


def _period(t):
    d = str(t.get("exit_day") or t["day"])
    if d < VAULT_START:
        return "IS (truoc 2023)"
    if d <= VAULT_END:
        return "VAULT 2023-24 (OOS)"
    return "sau vault (2025+)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--nkd-parquet",
                    default="global_index/data/NKD_continuous_1m_8y.parquet")
    a = ap.parse_args()

    from futures.basket import SWING_TF_PARAM
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, daily_atr_series
    from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
    from global_index.regime import RegimeLabels, load_spy_regime
    from global_index.specs import SPECS
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import run_loop

    mult, hold = SWING_TF_PARAM["chandelier_atr_mult"], SWING_TF_PARAM["max_hold_days"]

    dfs = load_basket(a.data_dir)
    labels = basket_labels(a.regime_csv)
    costs = costs_for_basket()

    c = SPECS["MNKD"]
    ndf = gi_load(a.nkd_parquet)
    ndf.index = ndf.index.tz_convert(c.session_tz)
    nlab = RegimeLabels(load_spy_regime(a.regime_csv), lag_days=1)
    ncost = GIFC(point_value=c.point_value, tick=c.tick,
                 commission_rt=c.commission_rt, slippage_ticks_per_side=1.0)

    GROUPS = [
        ("Ro 4", dfs, labels, costs, SWING_TF_PARAM["ema_period"], 1.17),
        ("MNKD", {"MNKD": ndf}, nlab, {"MNKD": ncost}, 10, 14.17),
    ]

    for name, frames, labs, cst, ema, live_hour in GROUPS:
        strat = TrendFollowStrategy({**TrendFollowStrategy().config,
                                     "ema_period": ema, "chandelier_atr_mult": mult})
        arms = {}
        for lbl, h in (("engine", None), ("live", live_hour)):
            rows = []
            for k, df in frames.items():
                cache = _swing_cache(df, daily_atr_series(df))
                m, _ = run_loop(df, labs, cst[k], strat=strat, ema_period=ema,
                                mult=mult, max_hold_days=hold, cache=cache,
                                same_day_stop=False, stop_slip_ticks=0.0,
                                stop_active_hour=h)
                rows.extend(m)
            arms[lbl] = rows

        print()
        print("=" * 78)
        print(f"{name} — TACH THEO NAM (engine = ranh gioi ngay, live = 09:31 ET)")
        print("=" * 78)
        by = {k: defaultdict(float) for k in arms}
        for k, rows in arms.items():
            for t in rows:
                by[k][_year(t)] += t["pnl"]
        years = sorted(set(by["engine"]) | set(by["live"]))
        print(f"  {'nam':>6} | {'engine':>11} | {'live':>11} | {'chenh':>11} | live thang?")
        print("  " + "-" * 62)
        wins = 0
        for y in years:
            e, l = by["engine"].get(y, 0.0), by["live"].get(y, 0.0)
            w = l > e
            wins += w
            print(f"  {y:>6} | ${e:>+10,.0f} | ${l:>+10,.0f} | ${l - e:>+10,.0f} | "
                  f"{'CO' if w else '.':>4}")
        print("  " + "-" * 62)
        print(f"  live thang {wins}/{len(years)} nam")

        # phan dong gop lon nhat den tu nam nao
        diffs = sorted(((by['live'].get(y, 0.) - by['engine'].get(y, 0.)), y)
                       for y in years)
        tot = sum(d for d, _ in diffs)
        if tot:
            top = diffs[-1]
            print(f"  nam dong gop lon nhat: {top[1]} = ${top[0]:+,.0f} "
                  f"({100 * top[0] / tot:.0f}% cua tong chenh ${tot:+,.0f})")

        print()
        print(f"  {'giai doan':<22} | {'engine':>11} | {'live':>11} | {'chenh':>11}")
        print("  " + "-" * 62)
        pby = {k: defaultdict(float) for k in arms}
        for k, rows in arms.items():
            for t in rows:
                pby[k][_period(t)] += t["pnl"]
        for per in ("IS (truoc 2023)", "VAULT 2023-24 (OOS)", "sau vault (2025+)"):
            e, l = pby["engine"].get(per, 0.0), pby["live"].get(per, 0.0)
            print(f"  {per:<22} | ${e:>+10,.0f} | ${l:>+10,.0f} | ${l - e:>+10,.0f}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
