"""Live-semantics (STP có hiệu lực ngay) — mô hình đầy đủ, có vào lại lệnh và trượt giá.

Phép đo trước (measure_sameday_stop.py) chỉ thay P&L của từng lệnh bị chạm stop, giữ
nguyên phần còn lại. Nó bỏ qua đúng thứ quan trọng nhất: bị stop sớm thì hệ thống RẢNH
sớm, và có thể vào một tín hiệu mới mà bản gốc không bao giờ thấy. Không mô hình hoá
việc đó thì con số chỉ là chặn trên của thiệt hại, không phải thiệt hại.

Không sửa `_validated_core.py`. Thay vào đó chép vòng lặp ngày vào đây rồi **đối chiếu
trade-for-trade với engine** khi tắt stop-trong-ngày. Không tái tạo được từng lệnh tới
từng cent thì bản chép sai, và script DỪNG thay vì in ra số không dùng được. Đây là cổng
bắt buộc — cùng kiểu với reconcile_gd0.

Mô hình phía live:
  - STP đặt tại `initial_stop` ngay sau khi khớp, hiệu lực từ bar kế tiếp
  - chạm stop trong ngày vào lệnh → thoát, dùng ĐÚNG luật gap-through của engine
    (mở qua stop sau một khoảng nghỉ thật → khớp tại giá mở, tệ hơn)
  - thoát xong vẫn quét tiếp cửa sổ 14:00–15:55 hôm đó, đúng như engine làm sau mọi lần
    thoát → vào lại lệnh được mô hình hoá, không bị bỏ sót
  - `--stop-slip-ticks`: trượt thêm khi khớp STP, vì lệnh dừng khớp tệ hơn lệnh thường

    python model_sameday_stop.py --data-dir data\\cache\\futures --regime-csv spy_daily_live.csv
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


def build_sig_cache(cache, labels, strat, ema_period, allowed):
    """{ngay: (bar_ts, sig)} — tin hieu vao lenh DAU TIEN cua moi ngay, khong loc.

    Chay mot lan cho moi ma roi dung lai cho moi nhanh: quet lai generate_signal tren
    tung bar 5 phut suot 8 nam cho MOI nhanh la ly do moi lan do truoc day mat 10-20
    phut.

    Chi hop le cho ngay CHUA CO THOAT — `avgv` lay theo vi tri trong cua so da loc, nen
    sau mot lan thoat cua so bi cat va tin hieu khac di. run_loop tu quay ve quet day du
    cho nhung ngay do.
    """
    from futures._validated_core import atr14

    out = {}
    for day in cache["days"]:
        reg = labels.get(day)
        if reg not in allowed:
            continue
        bars5 = cache["b5"][day]
        win = bars5.between_time("14:00", "15:55")
        idx = list(win.index)
        for k in range(1, len(idx)):
            hist = bars5.loc[:idx[k]]
            if len(hist) < max(ema_period, 14) + 1:
                continue
            ema = strat.calculate_ema(hist, ema_period)
            atr = atr14(hist)
            avgv = float(win["volume"].iloc[max(0, k - 11):k - 1].mean())
            if np.isnan(atr) or np.isnan(avgv):
                continue
            sig = strat.generate_signal(win.loc[idx[k - 1]], win.loc[idx[k]],
                                        ema, atr, reg, avgv)
            if sig:
                out[day] = (idx[k], sig)
                break
    return out


def run_loop(df, labels, cost, *, strat, ema_period, mult, max_hold_days,
             cache, same_day_stop: bool, stop_slip_ticks: float, gap_fill=True,
             activate_after_h: float = 0.0, mae=None,
             entry_latency_min: float = 0.0, skipped=None,
             ratchet: bool = True,
             stop_active_hour: float | None = None, mae_full=None,
             sig_cache=None, stop_width_mult: float = 1.0):
    """Vòng lặp ngày của engine, chép lại, thêm một nhánh tuỳ chọn: stop có hiệu lực
    ngay trong ngày vào lệnh. same_day_stop=False phải cho ra ĐÚNG output engine."""
    from futures._validated_core import atr14, ET

    datr, days, hl, b5, ts = (cache["datr"], cache["days"], cache["hl"],
                              cache["b5"], cache.get("ts", {}))
    allowed = set(strat.config["allowed_regimes"])
    tick = float(getattr(cost, "tick", 0.25) or 0.25)
    slip = stop_slip_ticks * tick

    def _widen(sig):
        """Nhan do rong stop len stop_width_mult, GIU NGUYEN sizing.

        `mult` khong dung duoc lam bien do rong: no vua dat initial_stop (entry -+
        mult*ATR5), vua la mau so sizing (risk_sized = contracts*mult*ATR_ngay*pv),
        vua la dai trail. Quet `mult` doi ca ba cung luc — do la ly do sweep
        chandelier_atr_mult hoi 08-05 khong ket luan duoc gi.
        """
        if stop_width_mult == 1.0:
            return float(sig["initial_stop"])
        ep = float(sig["entry_price"])
        return ep - stop_width_mult * (ep - float(sig["initial_stop"]))

    trades, pos, n_sameday = [], None, 0

    def _close(pos, day, ex, reason, hold, exit_ts):
        if mae_full is not None and "_mae" in pos:
            mae_full.append(pos["_mae"] * cost.point_value)
        pts = (ex - pos["entry"]) if pos["dir"] == "LONG" else (pos["entry"] - ex)
        trades.append(dict(day=pos["entry_day"].date(), exit_day=day.date(),
                           regime=pos["regime"], direction=pos["dir"],
                           entry=round(pos["entry"], 2), exit=round(ex, 2),
                           points=round(pts, 2),
                           pnl=round(pts * cost.point_value - cost.round_turn_cost(), 2),
                           hold_days=hold, reason=reason,
                           entry_time=pos.get("entry_time"), exit_time=exit_ts))

    for day in days:
        exit_ts_today = None

        # ── thoát: cho vị thế mở TỪ TRƯỚC hôm nay ────────────────────────────
        if pos is not None:
            hold = (day - pos["entry_day"]).days
            if hold >= max_hold_days:
                _day_ts = ts.get(day)
                if _day_ts is not None and len(_day_ts):
                    _930 = day + pd.Timedelta(hours=9, minutes=30)
                    _tz = str(_day_ts.tzinfo) if _day_ts.tzinfo is not None else ""
                    if _tz in ("", "America/New_York", "US/Eastern"):
                        _cmp = _930.tz_localize(ET) if _day_ts.tzinfo is not None else _930
                        _idx = int(_day_ts.searchsorted(_cmp))
                        if _idx >= len(hl[day][2]):
                            _idx = 0
                    else:
                        _idx = 0
                    op, exit_bar_ts = float(hl[day][2][_idx]), _day_ts[_idx]
                else:
                    op, exit_bar_ts = float(hl[day][2][0]), None
                _close(pos, day, op, "MAX_HOLD", hold, exit_bar_ts)
                pos, exit_ts_today = None, exit_bar_ts
            else:
                high, low, opn, isg = hl[day]
                da = float(datr.asof(day)) if len(datr) else np.nan
                if not np.isnan(da) and da > 0 and len(high):
                    if pos["dir"] == "LONG":
                        run_full = np.maximum.accumulate(np.maximum(high, pos["extreme"]))
                        run_prev = np.concatenate(([pos["extreme"]], run_full[:-1]))
                        stop_prev = (np.maximum.accumulate(
                            np.maximum(run_prev - mult * da, pos["stop"]))
                            if ratchet else np.full(len(high), pos["stop"]))
                        hit = np.where(low <= stop_prev)[0]
                    else:
                        run_full = np.minimum.accumulate(np.minimum(low, pos["extreme"]))
                        run_prev = np.concatenate(([pos["extreme"]], run_full[:-1]))
                        stop_prev = (np.minimum.accumulate(
                            np.minimum(run_prev + mult * da, pos["stop"]))
                            if ratchet else np.full(len(high), pos["stop"]))
                        hit = np.where(high >= stop_prev)[0]

                    # STP chua len san: engine coi nhu co stop tu ranh gioi ngay cua no,
                    # live thi mai 09:31 ET B4 moi dat. Bo cac hit truoc moc do, va don
                    # muc lo tam sau nhat trong quang trần đó.
                    if pos.get("_act") is not None:
                        _dts = ts.get(day)
                        if _dts is not None and len(_dts):
                            _naive = _dts.tz_localize(None) if _dts.tz is not None else _dts
                            _before = np.asarray(_naive < pos["_act"])
                            if _before.any():
                                _w = np.where(_before)[0]
                                _adv = ((pos["entry"] - low[_w].min()) if pos["dir"] == "LONG"
                                        else (high[_w].max() - pos["entry"]))
                                pos["_mae"] = max(pos["_mae"], float(_adv))
                                hit = hit[hit >= int(_before.sum())]
                            if not _before.all():
                                pos["_act"] = None      # da len san, tu day tro di binh thuong
                    if len(hit):
                        i = hit[0]; stp = float(stop_prev[i])
                        gapped = gap_fill and bool(isg[i]) and (
                            (pos["dir"] == "LONG" and float(opn[i]) < stp) or
                            (pos["dir"] == "SHORT" and float(opn[i]) > stp))
                        ex, reason = ((float(opn[i]), "GAP") if gapped
                                      else (stp, "CHANDELIER"))
                        _ts_exit = ts.get(day)
                        _et = (_ts_exit[i] if _ts_exit is not None and i < len(_ts_exit)
                               else None)
                        _close(pos, day, ex, reason, hold, _et)
                        pos, exit_ts_today = None, _et
                    else:
                        if ratchet:
                            if pos["dir"] == "LONG":
                                pos["stop"] = float(np.maximum(pos["stop"],
                                                               run_full[-1] - mult * da))
                            else:
                                pos["stop"] = float(np.minimum(pos["stop"],
                                                               run_full[-1] + mult * da))
                        pos["extreme"] = float(run_full[-1])

        # ── vào lệnh (+ nhánh stop-trong-ngày, lặp để mô hình hoá vào lại) ───
        while pos is None:
            reg = labels.get(day)
            if reg not in allowed:
                break
            bars5 = b5[day]
            win = bars5.between_time("14:00", "15:55")
            if exit_ts_today is not None:
                win = win[win.index > exit_ts_today]
                if len(win) < 2:
                    break
            idx = list(win.index)

            # Cache tin hieu: chi dung khi HOM NAY CHUA CO THOAT. `avgv` lay theo VI TRI
            # trong `win` da loc, nen sau mot lan thoat cua so bi cat va tin hieu khac
            # di — cache mot bang chung cho ca hai truong hop se sai am tham. Ngay co
            # thoat quay ve quet day du (thieu so).
            if sig_cache is not None and exit_ts_today is None:
                _hit = sig_cache.get(day)
                if _hit is None:
                    break
                _ts, sig = _hit
                _px, _ft = float(sig["entry_price"]), _ts
                if entry_latency_min > 0:
                    _day_ts2 = ts.get(day)
                    _fill_at = _ts + pd.Timedelta(minutes=5 + entry_latency_min)
                    if _day_ts2 is None:
                        break
                    _j = int(_day_ts2.searchsorted(_fill_at))
                    if _j >= len(hl[day][2]):
                        if skipped is not None:
                            skipped.append(1)
                        break
                    _px, _ft = float(hl[day][2][_j]), _day_ts2[_j]
                pos = dict(dir=sig["direction"], entry=_px, entry_day=day, regime=reg,
                           extreme=_px, stop=_widen(sig), entry_time=_ft,
                           _mae=0.0,
                           _act=(day + pd.Timedelta(days=1)
                                 + pd.Timedelta(hours=stop_active_hour)
                                 if stop_active_hour is not None else None))
                if not same_day_stop:
                    break

            for k in range(1, len(idx)):
                hist = bars5.loc[:idx[k]]
                if len(hist) < max(ema_period, 14) + 1:
                    continue
                ema = strat.calculate_ema(hist, ema_period)
                atr = atr14(hist)
                avgv = float(win["volume"].iloc[max(0, k - 11):k - 1].mean())
                if np.isnan(atr) or np.isnan(avgv):
                    continue
                sig = strat.generate_signal(win.loc[idx[k - 1]], win.loc[idx[k]],
                                            ema, atr, reg, avgv)
                if sig:
                    _px, _ft = float(sig["entry_price"]), idx[k]
                    if entry_latency_min > 0:
                        # Bar 5 phút phải đóng xong mới hành động được (+5), rồi slot mới
                        # nhặt và run_day mới chạy (+L). Giá vào trượt theo, còn mức stop
                        # thì KHÔNG — hệ thống tính nó từ bar tín hiệu và gửi nguyên vậy.
                        _day_ts2 = ts.get(day)
                        _fill_at = idx[k] + pd.Timedelta(minutes=5 + entry_latency_min)
                        if _day_ts2 is None:
                            break
                        _j = int(_day_ts2.searchsorted(_fill_at))
                        if _j >= len(hl[day][2]):
                            if skipped is not None:
                                skipped.append(1)
                            break          # hết bar trong ngày → lệnh không vào được
                        _px, _ft = float(hl[day][2][_j]), _day_ts2[_j]
                    pos = dict(dir=sig["direction"], entry=_px,
                               entry_day=day, regime=reg,
                               extreme=_px, stop=_widen(sig),
                               entry_time=_ft, _mae=0.0,
                               _act=(day + pd.Timedelta(days=1)
                                     + pd.Timedelta(hours=stop_active_hour)
                                     if stop_active_hour is not None else None))
                    break
            if pos is None:
                break

            if mae_full is not None and pos.get("_act") is not None:
                _h, _l, _o, _g = hl[day]
                _dts = ts.get(day)
                if _dts is not None and len(_dts):
                    _naive = _dts.tz_localize(None) if _dts.tz is not None else _dts
                    _ent = pos["entry_time"]
                    _ent = _ent.tz_localize(None) if _ent.tzinfo is not None else _ent
                    _aft = np.asarray(_naive > _ent)
                    if _aft.any():
                        _w = np.where(_aft)[0]
                        _adv = ((pos["entry"] - _l[_w].min()) if pos["dir"] == "LONG"
                                else (_h[_w].max() - pos["entry"]))
                        pos["_mae"] = max(pos["_mae"], float(_adv))

            if not same_day_stop:
                break

            # STP có hiệu lực ngay: quét bar 1 phút SAU bar vào, trong cùng ngày
            high, low, opn, isg = hl[day]
            _day_ts = ts.get(day)
            if _day_ts is None:
                break
            _from = pos["entry_time"] + pd.Timedelta(hours=activate_after_h)
            aft = np.asarray(_day_ts > _from)
            if mae is not None:
                # lỗ tạm thời sâu nhất trong quãng KHÔNG có stop — cái giá của chỗ thở
                _unp = np.asarray((_day_ts > pos["entry_time"]) & (_day_ts <= _from))
                if _unp.any():
                    _w = np.where(_unp)[0]
                    _adv = ((pos["entry"] - low[_w].min()) if pos["dir"] == "LONG"
                            else (high[_w].max() - pos["entry"]))
                    mae.append(float(_adv) * cost.point_value)
            if not aft.any():
                break
            stp = float(pos["stop"])
            w = np.where(aft)[0]
            hit = (w[low[w] <= stp] if pos["dir"] == "LONG" else w[high[w] >= stp])
            if not len(hit):
                break
            i = int(hit[0])
            gapped = gap_fill and bool(isg[i]) and (
                (pos["dir"] == "LONG" and float(opn[i]) < stp) or
                (pos["dir"] == "SHORT" and float(opn[i]) > stp))
            if gapped:
                ex, reason = float(opn[i]), "GAP_D0"
            else:
                # lệnh dừng khớp tệ hơn mức đặt
                ex = stp - slip if pos["dir"] == "LONG" else stp + slip
                reason = "STP_D0"
            _close(pos, day, ex, reason, 0, _day_ts[i])
            n_sameday += 1
            pos, exit_ts_today = None, _day_ts[i]

    return trades, n_sameday


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--stop-slip-ticks", type=float, default=1.0)
    ap.add_argument("--activate-after", type=float, nargs="*",
                    default=[0.0, 1.0, 2.0, 4.0, 8.0])
    a = ap.parse_args()

    from futures.basket import BASKET, SWING_TF_PARAM
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, backtest_swing_tf, daily_atr_series
    from raits.strategies.trend_follow import TrendFollowStrategy

    ema_period = SWING_TF_PARAM["ema_period"]
    mult = SWING_TF_PARAM["chandelier_atr_mult"]
    max_hold = SWING_TF_PARAM["max_hold_days"]
    strat = TrendFollowStrategy({**TrendFollowStrategy().config,
                                 "ema_period": ema_period,
                                 "chandelier_atr_mult": mult})

    dfs = load_basket(a.data_dir)
    labels = basket_labels(a.regime_csv)
    costs = costs_for_basket()

    print(f"\n{'='*80}")
    print("CỔNG ĐỐI CHIẾU — bản chép (tắt stop-trong-ngày) phải trùng engine từng lệnh")
    print("=" * 80)

    caches, base = {}, {}
    ok_all = True
    for name in BASKET:
        df, cost = dfs[name], costs[name]
        datr = daily_atr_series(df)
        caches[name] = _swing_cache(df, datr)
        eng = backtest_swing_tf(df, labels, cost, ema_period=ema_period,
                                chandelier_atr_mult=mult, max_hold_days=max_hold,
                                datr=datr)
        mine, _ = run_loop(df, labels, cost, strat=strat, ema_period=ema_period,
                           mult=mult, max_hold_days=max_hold, cache=caches[name],
                           same_day_stop=False, stop_slip_ticks=0.0)
        base[name] = eng
        bad = 0
        if len(eng) != len(mine):
            bad = -1
        else:
            for te, tm in zip(eng, mine):
                if (te["day"] != tm["day"] or te["exit_day"] != tm["exit_day"]
                        or te["direction"] != tm["direction"]
                        or abs(te["entry"] - tm["entry"]) > 0.005
                        or abs(te["exit"] - tm["exit"]) > 0.005
                        or abs(te["pnl"] - tm["pnl"]) > 0.005
                        or te["reason"] != tm["reason"]):
                    bad += 1
        status = ("KHỚP" if bad == 0 else
                  (f"LỆCH SỐ LỆNH {len(eng)} vs {len(mine)}" if bad < 0
                   else f"LỆCH {bad} lệnh"))
        print(f"  {name}: engine {len(eng)} lệnh | bản chép {len(mine)} | {status}")
        ok_all &= (bad == 0)

    if not ok_all:
        print("\n*** CỔNG ĐỐI CHIẾU KHÔNG ĐẠT — bản chép không tái tạo được engine.")
        print("    Dừng ở đây: mọi con số sau đó đều không dùng được. ***")
        return 1
    print("\n  → đạt. Bản chép là engine, chỉ khác đúng một nhánh được thêm.")

    print()
    print("=" * 80)
    print(f"QUÉT ĐỘ TRỄ KÍCH HOẠT STOP — trượt STP {a.stop_slip_ticks:g} tick")
    print("hình dạng đường cong mới là thứ cần nhìn, KHÔNG phải đỉnh P&L")
    print("=" * 80)
    print(f"  {'kích hoạt sau':>14} | {'số lệnh':>8} | {'P&L':>12} | {'thắng':>6} | "
          f"{'stop-D0':>8} | lỗ tạm sâu nhất khi chưa có stop (trung vị / p95 / max)")
    print("  " + "-" * 108)
    for hrs in a.activate_after:
        tot_n = tot_p = tot_sd = tot_w = 0
        mae = []
        for name in BASKET:
            mine, n_sd = run_loop(dfs[name], labels, costs[name], strat=strat,
                                  ema_period=ema_period, mult=mult,
                                  max_hold_days=max_hold, cache=caches[name],
                                  same_day_stop=True,
                                  stop_slip_ticks=a.stop_slip_ticks,
                                  activate_after_h=hrs, mae=mae)
            tot_n += len(mine); tot_p += sum(t["pnl"] for t in mine)
            tot_sd += n_sd; tot_w += sum(1 for t in mine if t["pnl"] > 0)
        import statistics as _st
        _m = (f"${_st.median(mae):,.0f} / ${_st.quantiles(mae, n=20)[18]:,.0f} / "
              f"${max(mae):,.0f}") if len(mae) > 20 else "-"
        print(f"  {hrs:>12.0f}h | {tot_n:>8} | ${tot_p:>+11,.0f} | "
              f"{100.0*tot_w/tot_n if tot_n else 0:>5.0f}% | {tot_sd:>8} | {_m}")
    _bt_n = sum(len(base[n]) for n in BASKET)
    _bt_p = sum(t["pnl"] for n in BASKET for t in base[n])
    _bt_w = sum(1 for n in BASKET for t in base[n] if t["pnl"] > 0)
    print(f"  {'sang ngày':>13} | {_bt_n:>8} | ${_bt_p:>+11,.0f} | "
          f"{100.0*_bt_w/_bt_n:>5.0f}% | {0:>8} | (= backtest hiện tại)")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
