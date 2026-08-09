"""Bao nhiêu lệnh bị chạm stop NGAY TRONG NGÀY vào lệnh?

Đó chính là tập lệnh mà live và backtest xử lý khác nhau.

`place_stop` đưa STP lên sàn ngay sau khi khớp (GTC, outsideRth), nên từ giây đầu
tiên giá chạm mức chandelier là thoát. `backtest_swing_tf` thì kiểm stop trong khối
`if pos is not None`, chạy TRƯỚC khối vào lệnh trong cùng một vòng lặp ngày — nên vị
thế mở hôm nay mãi hôm sau mới bị xét. Live đang chạy luật thoát chặt hơn bản đã kiểm
định, ở mọi lệnh, và điều đó chưa bao giờ được cân nhắc.

Không sửa `_validated_core.py`. Script chạy đúng engine để lấy trade log, rồi gọi lại
CHÍNH `generate_signal` của engine tại đúng bar vào lệnh để lấy `initial_stop` — mức
mà runner thật sự gửi lên sàn (`stop_price = t["stop"]`, chưa có ratchet).

Tự kiểm: mức tái dựng phải khớp trade log tới từng cent ở cả entry lẫn hướng lệnh.
Lệch một cái là tái dựng sai, và script báo số thay vì lặng lẽ bỏ qua.

    python measure_sameday_stop.py --data-dir data\\cache\\futures --regime-csv spy_daily_live.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_CWD = Path.cwd()
if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))

import numpy as np
import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    a = ap.parse_args()

    from futures.basket import BASKET, SWING_TF_PARAM
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import (_swing_cache, atr14, backtest_swing_tf)
    from raits.strategies.trend_follow import TrendFollowStrategy

    ema_period = SWING_TF_PARAM["ema_period"]
    mult = SWING_TF_PARAM["chandelier_atr_mult"]
    max_hold = SWING_TF_PARAM["max_hold_days"]

    strat = TrendFollowStrategy({**TrendFollowStrategy().config,
                                 "ema_period": ema_period,
                                 "chandelier_atr_mult": mult})

    print(f"\n{'='*78}")
    print("CHẠM STOP NGAY TRONG NGÀY VÀO LỆNH — live (STP tức thì) vs backtest (stop từ hôm sau)")
    print(f"ema={ema_period} mult={mult} max_hold={max_hold}")
    print("=" * 78)

    dfs = load_basket(a.data_dir)
    labels = basket_labels(a.regime_csv)
    costs = costs_for_basket()

    grand = dict(n=0, hit=0, recon_fail=0, bt_pnl=0.0, live_pnl=0.0)
    rows = []

    for name in BASKET:
        df, cost = dfs[name], costs[name]
        trades = backtest_swing_tf(df, labels, cost, ema_period=ema_period,
                                   chandelier_atr_mult=mult, max_hold_days=max_hold)
        from futures._validated_core import daily_atr_series
        datr_s = daily_atr_series(df)
        c = _swing_cache(df)
        b5, ts, hl = c["b5"], c.get("ts", {}), c["hl"]

        SCALES = [0.5, 1.0, 2.0, 4.0, 8.0]
        scale_hits = [0] * len(SCALES)
        hold_hist, reason_hist = {}, {}
        n_profit_side = 0          # đối xứng: cùng khoảng cách, phía có lời
        dists, datrs = [], []
        n_hit = recon_fail = 0
        bt_pnl = live_pnl = 0.0
        first_examples = []

        for t in trades:
            day = pd.Timestamp(t["day"]).normalize()
            et = t.get("entry_time")
            if et is None or day not in b5:
                recon_fail += 1
                continue

            # ── tái dựng initial_stop bằng chính đường vào lệnh của engine ──
            bars5 = b5[day]
            win = bars5.between_time("14:00", "15:55")
            idx = list(win.index)
            et = pd.Timestamp(et)
            if et not in idx:
                recon_fail += 1
                continue
            k = idx.index(et)
            if k < 1:
                recon_fail += 1
                continue
            hist = bars5.loc[:idx[k]]
            ema = strat.calculate_ema(hist, ema_period)
            atr = atr14(hist)
            avgv = float(win["volume"].iloc[max(0, k - 11):k - 1].mean())
            reg = labels.get(day)
            sig = strat.generate_signal(win.loc[idx[k - 1]], win.loc[idx[k]],
                                        ema, atr, reg, avgv)

            # tự kiểm: tái dựng phải trùng trade log, nếu không thì không dùng được
            if (not sig or sig["direction"] != t["direction"]
                    or abs(float(sig["entry_price"]) - float(t["entry"])) > 0.005):
                recon_fail += 1
                continue

            stop0 = float(sig["initial_stop"])
            _d0 = abs(stop0 - float(t["entry"]))

            # ── giá trong NGÀY VÀO LỆNH, sau bar vào, có chạm stop không ──
            high, low, opn, isg = hl[day]
            tstamps = ts.get(day)
            if tstamps is None:
                recon_fail += 1
                continue
            after = np.asarray(tstamps > et)
            if not after.any():
                touched = False
            elif t["direction"] == "LONG":
                touched = bool((low[after] <= stop0).any())
            else:
                touched = bool((high[after] >= stop0).any())

            # tự kiểm: nới stop ra k lần thì tỉ lệ chạm PHẢI giảm đơn điệu.
            # Chỉ đổi mức stop trong phép đo, không đụng backtest — nếu đổi tham số
            # engine thì entry cũng đổi theo và không cô lập được (bài học sweep mult).
            for _ki, _k in enumerate(SCALES):
                _s = (float(t["entry"]) - _k * _d0) if t["direction"] == "LONG"                      else (float(t["entry"]) + _k * _d0)
                if not after.any():
                    continue
                if t["direction"] == "LONG":
                    scale_hits[_ki] += bool((low[after] <= _s).any())
                else:
                    scale_hits[_ki] += bool((high[after] >= _s).any())
            # đối xứng: mức cùng khoảng cách nhưng về phía có lời. Nếu phía này
            # cũng bị chạm với tỉ lệ tương đương thì kết luận đúng là "stop quá hẹp
            # so với biên độ trong ngày", chứ không phải máy đo lệch về một phía.
            _p = (float(t["entry"]) + _d0) if t["direction"] == "LONG"                  else (float(t["entry"]) - _d0)
            if after.any():
                n_profit_side += (bool((high[after] >= _p).any())
                                  if t["direction"] == "LONG"
                                  else bool((low[after] <= _p).any()))
            dists.append(_d0)
            _da = float(datr_s.asof(day)) if len(datr_s) else float("nan")
            if _da == _da:
                datrs.append(_da)

            hold_hist[int(t.get("hold_days") or 0)] = hold_hist.get(int(t.get("hold_days") or 0), 0) + 1
            reason_hist[t.get("reason", "?")] = reason_hist.get(t.get("reason", "?"), 0) + 1

            bt_pnl += float(t["pnl"])
            if touched:
                n_hit += 1
                # live: thoát tại stop ngay hôm đó
                pts = ((stop0 - float(t["entry"])) if t["direction"] == "LONG"
                       else (float(t["entry"]) - stop0))
                live_pnl += pts * cost.point_value - cost.round_turn_cost()
                if len(first_examples) < 3:
                    first_examples.append(
                        f"      {day.date()} {t['direction']:5s} entry={t['entry']:.2f} "
                        f"stop={stop0:.2f} | backtest ${t['pnl']:+.0f} → live ${pts*cost.point_value - cost.round_turn_cost():+.0f}")
            else:
                live_pnl += float(t["pnl"])

        n = len(trades)
        pct = 100.0 * n_hit / n if n else 0.0
        print(f"\n  {name}: {n} lệnh | chạm stop trong ngày vào: {n_hit} ({pct:.1f}%)"
              f" | tái dựng lỗi: {recon_fail}")
        print(f"      backtest ${bt_pnl:+,.0f}   →   live (STP tức thì) ${live_pnl:+,.0f}"
              f"   chênh ${live_pnl - bt_pnl:+,.0f}")
        for line in first_examples:
            print(line)
        _ok = all(scale_hits[i] >= scale_hits[i+1] for i in range(len(SCALES)-1))
        print("      tự kiểm nới stop  " +
              "  ".join(f"×{k:g}:{h}" for k, h in zip(SCALES, scale_hits)) +
              ("   [đơn điệu OK]" if _ok else "   [!! KHÔNG ĐƠN ĐIỆU — phép đo sai]"))
        import statistics as _st
        _md = _st.median(dists) if dists else float("nan")
        _ma = _st.median(datrs) if datrs else float("nan")
        print(f"      đối xứng: chạm phía CÓ LỜI cùng khoảng cách: {n_profit_side}"
              f"  (phía stop: {n_hit})")
        print(f"      khoảng cách stop trung vị {_md:.2f} điểm | ATR ngày trung vị "
              f"{_ma:.2f} | mult×ATR = {mult*_ma:.1f}  → stop hẹp hơn {mult*_ma/_md:.0f} lần")
        print("      hold_days " + " ".join(f"{k}d:{v}" for k, v in sorted(hold_hist.items())))
        print("      lý do thoát " + " ".join(f"{k}:{v}" for k, v in sorted(reason_hist.items())))

        rows.append((name, n, n_hit, recon_fail, bt_pnl, live_pnl))
        grand["n"] += n; grand["hit"] += n_hit; grand["recon_fail"] += recon_fail
        grand["bt_pnl"] += bt_pnl; grand["live_pnl"] += live_pnl

    print(f"\n{'='*78}")
    pct = 100.0 * grand["hit"] / grand["n"] if grand["n"] else 0.0
    print(f"TỔNG: {grand['n']} lệnh | chạm stop trong ngày vào: {grand['hit']} ({pct:.1f}%)"
          f" | tái dựng lỗi: {grand['recon_fail']}")
    print(f"      backtest ${grand['bt_pnl']:+,.0f}   →   live ${grand['live_pnl']:+,.0f}"
          f"   chênh ${grand['live_pnl'] - grand['bt_pnl']:+,.0f}")
    if grand["recon_fail"]:
        print(f"\n  ⚠ {grand['recon_fail']} lệnh không tái dựng được initial_stop — "
              f"số ở trên chỉ tính trên phần tái dựng được, KHÔNG phải toàn bộ.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
