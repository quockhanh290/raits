"""Khe hở còn lại: engine xét stop từ ranh giới ngày của nó, live mãi 09:31 ET mới đặt.

Bản vá hoãn STP đã sửa chiều SỚM (live đặt ngay lúc khớp). Còn lại chiều MUỘN, chưa ai đo:

    Rổ 4   engine xét từ D+1 00:00 ET   live có STP D+1 09:31 ET   → khe hở  9,5 tiếng
    MNKD   engine từ 00:00 JST ngày Tokyo kế (= D 11:00 ET)
           live D+1 09:31 ET = 22:31 JST                            → khe hở ~22,5 tiếng

Trong khe hở đó engine coi như có stop, live thì không. Về P&L có lẽ nhỏ — đường cong đã
bão hoà từ mốc 8 giờ. Nhưng con số rủi ro p95 $271/hợp đồng đã báo được tính trên cửa sổ
8 tiếng, KHÔNG phải 9,5 hay 22,5 — nên phơi nhiễm thật lớn hơn.

Đo cả hai: P&L, và mức lỗ tạm sâu nhất suốt TOÀN BỘ quãng trần (từ lúc vào tới lúc STP
lên sàn), không chỉ trong ngày vào lệnh.

CỔNG: stop_active_hour=None phải trùng engine từng lệnh.

    python model_stop_activation_gap.py --data-dir data\\cache\\futures --regime-csv spy_daily_live.csv
"""
from __future__ import annotations

import argparse
import statistics as st
import sys

import pandas as pd
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))


def _maxdd(trades):
    """MaxDD trên đường vốn thô mỗi hợp đồng, gộp mọi mã theo ngày thoát.

    P&L một mình không quyết định được gì ở đây: bỏ stop thì lỗ chỉ còn bị chặn bởi
    MAX_HOLD 5 ngày, nên hai nhánh có thể cùng lãi mà rủi ro khác hẳn. Hệ thống có
    trần DD 15%, nên đây là cột phải nhìn cùng lúc.
    """
    rows = sorted(trades, key=lambda t: str(t.get("exit_day") or t["day"]))
    eq = peak = dd = 0.0
    for t in rows:
        eq += t["pnl"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return dd


def _fmt(mae):
    if len(mae) < 20:
        return "-"
    return (f"${st.median(mae):,.0f} / ${st.quantiles(mae, n=20)[18]:,.0f} / "
            f"${max(mae):,.0f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--nkd-parquet", default="global_index/data/NKD_continuous_1m_8y.parquet")
    a = ap.parse_args()

    from futures.basket import BASKET, SWING_TF_PARAM
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, backtest_swing_tf, daily_atr_series
    from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
    from global_index.regime import RegimeLabels, load_spy_regime
    from global_index.specs import SPECS
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import run_loop

    mult, hold = SWING_TF_PARAM["chandelier_atr_mult"], SWING_TF_PARAM["max_hold_days"]

    # (nhãn, dict-frames, labels, costs, ema, giờ STP lên sàn tính từ ngày vào +1)
    dfs = load_basket(a.data_dir)
    labels = basket_labels(a.regime_csv)
    costs = costs_for_basket()

    c = SPECS["MNKD"]
    ndf = gi_load(a.nkd_parquet)
    ndf.index = ndf.index.tz_convert(c.session_tz)
    nlab = RegimeLabels(load_spy_regime(a.regime_csv), lag_days=1)
    ncost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
                 slippage_ticks_per_side=1.0)

    # MOT moc ET duy nhat, code tu quy doi sang dong ho cua tung khung.
    # Tu quy doi bang tay la cach da tao ra loi 09:31/22:52: 01:10 ET va 14:10 JST
    # LA CUNG MOT KHOANH KHAC, viet thanh hai so roi go vao hai cho thi lech luc nao
    # khong biet.
    #
    # Va gio dat STP khong phai MOT gia tri: binh thuong 01:10 ET (slot dem NKD dau
    # tien dung FuturesRunner -> B4 chay trong __init__); neu slot dem bi bo (khong co
    # ban ghi pre-flight ngay truoc) thi 09:31 ET (job MAX_HOLD). Vao lenh thu Sau thi
    # phai doi thu Hai — slot dem chi chay Mon-Fri. Do mot moc la mo ta mot he thong
    # don gian hon thuc te, nen KEP HAI DAU.
    ET_TIMES = [("01:10 ET  slot dem NKD (thuong)", 1, 10),
                ("09:31 ET  job MAX_HOLD (khi slot dem truot)", 9, 31)]

    def _hours_after_local_midnight(frame_tz, h_et, m_et):
        """01:10 ET la may gio sau nua dem TREN DONG HO CUA KHUNG DO."""
        t = pd.Timestamp("2026-06-15", tz="America/New_York") + pd.Timedelta(hours=h_et,
                                                                             minutes=m_et)
        if frame_tz is None:
            loc = t.tz_convert("America/New_York")
        else:
            loc = t.tz_convert(frame_tz)
        return loc.hour + loc.minute / 60.0

    GROUPS = [
        ("Rổ 4", dfs, labels, costs, SWING_TF_PARAM["ema_period"], None),
        ("MNKD", {"MNKD": ndf}, nlab, {"MNKD": ncost}, 10, c.session_tz),
    ]

    for name, frames, labs, cst, ema, frame_tz in GROUPS:
        strat = TrendFollowStrategy({**TrendFollowStrategy().config,
                                     "ema_period": ema, "chandelier_atr_mult": mult})
        caches = {}
        print()
        print("=" * 84)
        print(f"{name} — CONG DOI CHIEU (stop_active_hour=None phai trung engine)")
        print("=" * 84)
        ok = True
        for k, df in frames.items():
            datr = daily_atr_series(df)
            caches[k] = _swing_cache(df, datr)
            eng = backtest_swing_tf(df, labs, cst[k], ema_period=ema,
                                    chandelier_atr_mult=mult, max_hold_days=hold,
                                    datr=datr)
            mine, _ = run_loop(df, labs, cst[k], strat=strat, ema_period=ema, mult=mult,
                               max_hold_days=hold, cache=caches[k],
                               same_day_stop=False, stop_slip_ticks=0.0)
            bad = (len(eng) != len(mine)) or any(
                e["day"] != m["day"] or abs(e["pnl"] - m["pnl"]) > 0.005
                or e["reason"] != m["reason"] for e, m in zip(eng, mine))
            print(f"  {k}: {len(eng)} lenh | {'KHOP' if not bad else 'LECH'}")
            ok &= not bad
        if not ok:
            print("\n*** CONG KHONG DAT — dung ***")
            return 1

        print()
        print(f"  {'STP len san luc':<46} | {'lenh':>6} | {'P&L':>11} | "
              f"{'MaxDD':>10} | lo tam quang tran (tv/p95/max)")
        print("  " + "-" * 124)
        _arms = [("engine: ranh gioi ngay cua khung", None)]
        for _lbl, _h, _m in ET_TIMES:
            _hr = _hours_after_local_midnight(frame_tz, _h, _m)
            _arms.append((f"live: {_lbl} (={_hr:.2f}h)", _hr))
        _arms.append(("KHONG CO STOP (chi MAX_HOLD 5d)", 10_000.0))
        for lbl, h in _arms:
            tn = 0
            allt: list = []
            mae: list = []
            for k, df in frames.items():
                m, _ = run_loop(df, labs, cst[k], strat=strat, ema_period=ema, mult=mult,
                                max_hold_days=hold, cache=caches[k], same_day_stop=False,
                                stop_slip_ticks=0.0, stop_active_hour=h,
                                mae_full=(mae if h is not None else None))
                tn += len(m)
                allt.extend(m)
            tp = sum(t["pnl"] for t in allt)
            print(f"  {lbl:<46} | {tn:>6} | ${tp:>+10,.0f} | ${_maxdd(allt):>9,.0f} | "
                  f"{_fmt(mae)}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
