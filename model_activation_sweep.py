"""Kiểm định tử tế giờ kích hoạt STP: quét nhiều mốc × tách theo năm × kiểm trên vault.

Đo trước cho thấy giờ đặt STP quan trọng (Rổ 4: 01:10 → +$49.885, 09:31 → +$92.666) và
KHÔNG có mốc tối ưu chung — MNKD thì 01:10 lại hơn 09:31. Trước khi coi bất kỳ mốc nào là
đáng đổi sang, phải qua ba cửa:

  1. QUÉT NHIỀU MỐC — một đỉnh nhọn giữa hai thung lũng là nhiễu; một cao nguyên rộng mới
     là cơ chế. Hai điểm không phân biệt được hai thứ đó.
  2. TÁCH THEO NĂM — dồn vào một năm là một sự kiện, không phải quy luật.
  3. VAULT 2023–24 (OOS) — nhưng ở đây phải rất cẩn thận: khi QUÉT là ta đang CHỌN, và
     chọn trên vault thì vault mất giá trị. Nên vault ở bảng này chỉ để ĐỌC, không để
     chọn: chọn mốc theo IS trước, rồi xem mốc đó cư xử ra sao trên vault.

⚠️ Bảng này KHÔNG phải giấy phép đổi giờ. Hệ thống đang chạy 01:10 vì đó là hệ quả của
lịch job, và 01:10 gần trùng luật engine. Đổi sang mốc khác chỉ vì P&L backtest cao hơn
là curve fitting — đúng thứ đã tự cấm từ đầu. Bảng này để BIẾT, và để nếu có đổi thì đổi
với mắt mở.

    python model_activation_sweep.py --data-dir data\\cache\\futures --regime-csv spy_daily_live.csv
"""
from __future__ import annotations

import argparse
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

VAULT_START, VAULT_END = "2023-01-01", "2024-12-31"
HOURS = [None, 1.17, 5.0, 9.52, 16.0, 20.0, 24.0, 36.0, 48.0, 72.0, 10_000.0]
# 10_000 = khong bao gio bat = khong co stop. Quet keo dai vi cuc dai o lan truoc roi
# vao BIEN cua dai (16h) — cuc dai o bien nghia la DAI QUET SAI, khong phai dap an la
# 16h. Va ta biet gioi han cuoi la tham hoa (khong stop: -$46.369, MaxDD $60.138), nen
# duong cong BAT BUOC phai quay dau o dau do. Dinh vi cho quay dau la cau hoi AN TOAN
# (moc hien tai 1,17h cach vuc bao xa), khong phai cau hoi toi uu.

# Do rong stop, CO LAP khoi sizing — xem _widen() trong model_sameday_stop.
WIDTHS = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0]


def _period(t):
    d = str(t.get("exit_day") or t["day"])
    return ("IS" if d < VAULT_START else
            "VAULT" if d <= VAULT_END else "POST")


def _maxdd(trades):
    eq = peak = dd = 0.0
    for t in sorted(trades, key=lambda x: str(x.get("exit_day") or x["day"])):
        eq += t["pnl"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return dd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--nkd-parquet",
                    default="global_index/data/NKD_continuous_1m_8y.parquet")
    a = ap.parse_args()

    from futures.basket import SWING_TF_PARAM
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import (_swing_cache, backtest_swing_tf,
                                         daily_atr_series)
    from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
    from global_index.regime import RegimeLabels, load_spy_regime
    from global_index.specs import SPECS
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache, run_loop

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

    GROUPS = [("Ro 4", dfs, labels, costs, SWING_TF_PARAM["ema_period"]),
              ("MNKD", {"MNKD": ndf}, nlab, {"MNKD": ncost}, 10)]

    for grp in GROUPS:
        name, frames, labs, cst, ema = grp
        strat = TrendFollowStrategy({**TrendFollowStrategy().config,
                                     "ema_period": ema, "chandelier_atr_mult": mult})
        allowed = set(strat.config["allowed_regimes"])
        caches, sigs = {}, {}
        print()
        print("=" * 100)
        print(f"{name} — CONG DOI CHIEU (ranh gioi ngay + cache tin hieu => phai trung engine)")
        print("=" * 100)
        ok = True
        for k, df in frames.items():
            datr = daily_atr_series(df)
            caches[k] = _swing_cache(df, datr)
            sigs[k] = build_sig_cache(caches[k], labs, strat, ema, allowed)
            eng = backtest_swing_tf(df, labs, cst[k], ema_period=ema,
                                    chandelier_atr_mult=mult, max_hold_days=hold,
                                    datr=datr)
            mine, _ = run_loop(df, labs, cst[k], strat=strat, ema_period=ema, mult=mult,
                               max_hold_days=hold, cache=caches[k], same_day_stop=False,
                               stop_slip_ticks=0.0, sig_cache=sigs[k])
            bad = (len(eng) != len(mine)) or any(
                e["day"] != m["day"] or abs(e["pnl"] - m["pnl"]) > 0.005
                or e["reason"] != m["reason"] for e, m in zip(eng, mine))
            print(f"  {k}: {len(eng)} lenh | {'KHOP' if not bad else 'LECH'}")
            ok &= not bad
        if not ok:
            print("\n*** CONG KHONG DAT — cache tin hieu sai, dung ***")
            return 1

        print()
        print(f"  {'kich hoat sau':>14} | {'lenh':>6} | {'P&L':>11} | {'MaxDD':>9} | "
              f"{'IS':>10} | {'VAULT':>10} | {'POST':>10} | {'nam':>5} | "
              f"lo tam khi tran (tv/p95/max) | >2x stop")
        print("  " + "-" * 150)
        base_years = None
        for h in HOURS:
            allt = []
            mae: list = []
            for k, df in frames.items():
                m, _ = run_loop(df, labs, cst[k], strat=strat, ema_period=ema,
                                mult=mult, max_hold_days=hold, cache=caches[k],
                                same_day_stop=False, stop_slip_ticks=0.0,
                                stop_active_hour=h, sig_cache=sigs[k],
                                mae_full=(mae if h is not None else None))
                allt.extend(m)
            per = defaultdict(float)
            yr = defaultdict(float)
            for t in allt:
                per[_period(t)] += t["pnl"]
                yr[str(t.get("exit_day") or t["day"])[:4]] += t["pnl"]
            if base_years is None:
                base_years = dict(yr)
                wins = "-"
            else:
                w = sum(1 for y in base_years if yr.get(y, 0.) > base_years[y])
                wins = f"{w}/{len(base_years)}"
            lbl = "ranh gioi ngay" if h is None else f"{h:.2f}h"
            if len(mae) > 20:
                _m = (f"${st.median(mae):>6,.0f} / ${st.quantiles(mae, n=20)[18]:>7,.0f} "
                      f"/ ${max(mae):>8,.0f}")
                # bao nhieu lan lo tam vuot QUA HAI LAN khoang cach stop — do la muc
                # ma "stop hep giu lo nho" khong con dung trong quang tran
                _big = sum(1 for x in mae if x > 2 * st.median(mae)) if mae else 0
                _bigs = f"{100*_big/len(mae):>5.0f}%"
            else:
                _m, _bigs = "-", "-"
            print(f"  {lbl:>14} | {len(allt):>6} | ${sum(t['pnl'] for t in allt):>+10,.0f} | "
                  f"${_maxdd(allt):>8,.0f} | ${per['IS']:>+9,.0f} | ${per['VAULT']:>+9,.0f} | "
                  f"${per['POST']:>+9,.0f} | {wins:>5} | {_m} | {_bigs}")
        print()
        print(f"  DO RONG STOP (co lap khoi sizing), kich hoat giu nguyen 1.17h")
        print(f"  {'x do rong':>14} | {'lenh':>6} | {'P&L':>11} | {'MaxDD':>9} | "
              f"{'IS':>10} | {'VAULT':>10} | {'POST':>10}")
        print("  " + "-" * 96)
        for w in []:   # bang do rong da chay o lan truoc, bo qua
            allt = []
            for k, df in frames.items():
                m, _ = run_loop(df, labs, cst[k], strat=strat, ema_period=ema,
                                mult=mult, max_hold_days=hold, cache=caches[k],
                                same_day_stop=False, stop_slip_ticks=0.0,
                                stop_active_hour=1.17, sig_cache=sigs[k],
                                stop_width_mult=w)
                allt.extend(m)
            per = defaultdict(float)
            for t in allt:
                per[_period(t)] += t["pnl"]
            print(f"  {w:>13.1f}x | {len(allt):>6} | ${sum(t['pnl'] for t in allt):>+10,.0f} | "
                  f"${_maxdd(allt):>8,.0f} | ${per['IS']:>+9,.0f} | ${per['VAULT']:>+9,.0f} | "
                  f"${per['POST']:>+9,.0f}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
