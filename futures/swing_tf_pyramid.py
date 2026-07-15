"""
futures/swing_tf_pyramid.py — pyramiding VARIANT of the validated swing-TF engine
=================================================================================
RESEARCH VARIANT — TÁCH khỏi production. KHÔNG import bởi runner / paper / vault.
Đo edge của việc scale-in (pyramiding) một vị thế swing trend-follow đang thắng,
dưới WFO IS-only, GIỮ tổng risk cố định.

Xây TRÊN engine CAUSAL đã validate (futures/_validated_core):
  - Reuse _swing_cache / atr14 / TrendFollowStrategy — đúng code path causal
    (post-2026-07-10 look-ahead fix) + MAX_HOLD-09:30. KHÔNG dùng root
    swing_tf_harness (bản dirty/look-ahead).
  - max_units=1 rút gọn CHÍNH XÁC về _validated_core.backtest_swing_tf. GATE
    (reconcile trong pyramid_wfo.py) phải PASS trade-for-trade TRƯỚC khi sweep.

NĂM QUYẾT ĐỊNH DESIGN ĐÃ CHỐT (không đổi thầm — mỗi cái giữ sweep công bằng/causal):
  #1 ENGINE  : causal _validated_core (KHÔNG root swing_tf_harness dirty).
  #2 RISK    : total-risk-constant. 1% chia đều cho max_units unit dự kiến →
               mỗi unit mang trọng số w = 1/max_units contract. Pyramid đầy
               (mọi unit fill) = cùng gross risk với baseline 1-unit.
  #3 ADD-FILL: causal, như resting order. Unit k trigger tại
               entry ± (k-1)*0.5*N. Fill TẠI level; nếu bar GAP QUA level trên
               time-break thật (isg) → fill tại OPEN của bar (xấu hơn), KHÔNG bao
               giờ fill giá lý tưởng. Mirror kỷ luật chandelier stop.
  #4 STOP    : MỘT chandelier chung, keyed off pos["extreme"] (ratchet, chỉ
               tighten) — GIỮ NGUYÊN baseline. Add KHÔNG dịch stop. VWAP chỉ dùng
               cho P&L accounting (average entry), KHÔNG làm stop level.
  #5 PARAMS  : ema=30 / mult=2.5 freeze (isolate max_units). N = daily ATR14 tại
               entry day gốc, FIXED (không recompute mỗi add). Không add sau 60%
               max_hold (day 3/5).

GHI CHÚ về N: N = daily ATR14 as-of ngày entry (cùng daily ATR mà chandelier dùng)
— chọn vì vị thế là swing NHIỀU NGÀY, spacing theo đơn vị daily-ATR mới có nghĩa.
Đây là diễn giải của "N=ATR14 tại original entry"; flag để review.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

ADD_SPACING_N = 0.5          # unit k trigger tại entry ± (k-1)*0.5*N
NO_ADD_AFTER_FRAC = 0.6      # không add sau 60% max_hold (day 3/5)


def backtest_swing_tf_pyramid(df, labels, cost, *, ema_period=30,
                              chandelier_atr_mult=2.5, max_hold_days=5,
                              max_units=1, entry_days=None, gap_fill=True,
                              return_open=False):
    """Variant pyramid của _validated_core.backtest_swing_tf.

    max_units=1  → CHÍNH XÁC baseline causal (add block bị bỏ, w=1).
    max_units>1  → thêm tối đa (max_units-1) unit theo design #2/#3/#5.

    P&L (design #2, weight w=1/max_units mỗi unit):
        pnl = w * n_filled * ((exit - avg_entry) * PV - round_turn_cost)   [LONG]
        pnl = w * n_filled * ((avg_entry - exit) * PV - round_turn_cost)   [SHORT]
    → max_units=1: w=1, n=1, avg=entry → pnl = (exit-entry)*PV - cost = baseline.
    """
    from raits.strategies.trend_follow import TrendFollowStrategy
    from futures._validated_core import _swing_cache, atr14, ET
    s = TrendFollowStrategy({**TrendFollowStrategy().config, "ema_period": ema_period,
                             "chandelier_atr_mult": chandelier_atr_mult})
    allowed = set(s.config["allowed_regimes"])
    c = _swing_cache(df)
    datr, days, hl, b5, ts = c["datr"], c["days"], c["hl"], c["b5"], c.get("ts", {})
    mult = chandelier_atr_mult
    w = 1.0 / max_units                       # design #2: total-risk-constant
    add_cutoff = max_hold_days * NO_ADD_AFTER_FRAC
    PV = cost.point_value
    rt = cost.round_turn_cost()
    trades = []
    pos = None

    def _record(p, exit_px, exit_day, reason, hold, exit_time):
        entries = p["unit_entries"]
        n = len(entries)
        avg = sum(entries) / n                        # VWAP accounting (design #4)
        pts = (exit_px - avg) if p["dir"] == "LONG" else (avg - exit_px)
        pnl = w * n * (pts * PV - rt)                 # design #2
        trades.append(dict(day=p["entry_day"].date(), exit_day=exit_day,
                           regime=p["regime"], direction=p["dir"],
                           entry=round(avg, 2), exit=round(exit_px, 2),
                           points=round(pts, 2), pnl=round(pnl, 2),
                           hold_days=hold, reason=reason, units=n,
                           entry_time=p.get("entry_time"), exit_time=exit_time))

    for day in days:
        exit_ts_today = None
        if pos is not None:
            hold = (day - pos["entry_day"]).days
            if hold >= max_hold_days:
                # MAX_HOLD exit at 09:30 ET — verbatim từ _validated_core.
                _day_ts = ts.get(day)
                if _day_ts is not None and len(_day_ts):
                    _930    = day + pd.Timedelta(hours=9, minutes=30)
                    _tz_str = str(_day_ts.tzinfo) if _day_ts.tzinfo is not None else ""
                    _is_et  = _tz_str in ("", "America/New_York", "US/Eastern")
                    if _is_et:
                        if _day_ts.tzinfo is not None:
                            _930_cmp = _930.tz_localize(ET)
                        else:
                            _930_cmp = _930
                        _idx = int(_day_ts.searchsorted(_930_cmp))
                        if _idx >= len(hl[day][2]):
                            _idx = 0
                    else:
                        _idx = 0
                    op          = float(hl[day][2][_idx])
                    exit_bar_ts = _day_ts[_idx]
                else:
                    op          = float(hl[day][2][0])
                    exit_bar_ts = None
                _record(pos, op, day.date(), "MAX_HOLD", hold, exit_bar_ts)
                pos = None
                exit_ts_today = exit_bar_ts
            else:
                high, low, opn, isg = hl[day]
                da = float(datr.asof(day)) if len(datr) else np.nan
                if not np.isnan(da) and da > 0 and len(high):
                    if pos["dir"] == "LONG":
                        run_full = np.maximum.accumulate(np.maximum(high, pos["extreme"]))
                        run_prev = np.concatenate(([pos["extreme"]], run_full[:-1]))
                        stop_prev = np.maximum.accumulate(np.maximum(run_prev - mult * da, pos["stop"]))
                        hit = np.where(low <= stop_prev)[0]
                    else:
                        run_full = np.minimum.accumulate(np.minimum(low, pos["extreme"]))
                        run_prev = np.concatenate(([pos["extreme"]], run_full[:-1]))
                        stop_prev = np.minimum.accumulate(np.minimum(run_prev + mult * da, pos["stop"]))
                        hit = np.where(high >= stop_prev)[0]
                    i_stop = int(hit[0]) if len(hit) else None

                    # ── PYRAMID ADDS (design #2/#3/#5) ────────────────────────
                    # Causal: một add chỉ fill nếu trigger bar của nó ĐỨNG TRƯỚC
                    # stop bar trong ngày (i_add < i_stop). Add KHÔNG dịch stop/extreme.
                    if max_units > 1 and hold < add_cutoff \
                            and not np.isnan(pos["N"]) and pos["N"] > 0:
                        while pos["units"] < max_units:
                            k = pos["units"]                  # đã có k unit; kế tiếp là unit k+1
                            off = k * ADD_SPACING_N * pos["N"]
                            if pos["dir"] == "LONG":
                                level = pos["entry"] + off
                                cand = np.where(high >= level)[0]
                            else:
                                level = pos["entry"] - off
                                cand = np.where(low <= level)[0]
                            if not len(cand):
                                break
                            i_add = int(cand[0])
                            if i_stop is not None and i_add >= i_stop:
                                break                          # stop fire trước → dừng add ngày này
                            # gap-through: fill tại OPEN (xấu hơn) chỉ khi break thật + open qua level
                            gapped = gap_fill and bool(isg[i_add]) and (
                                (pos["dir"] == "LONG"  and float(opn[i_add]) > level) or
                                (pos["dir"] == "SHORT" and float(opn[i_add]) < level))
                            fill = float(opn[i_add]) if gapped else level
                            pos["unit_entries"].append(fill)
                            pos["units"] += 1

                    if i_stop is not None:
                        i = i_stop; stp = float(stop_prev[i])
                        gapped = gap_fill and bool(isg[i]) and (
                            (pos["dir"] == "LONG"  and float(opn[i]) < stp) or
                            (pos["dir"] == "SHORT" and float(opn[i]) > stp))
                        if gapped:
                            ex = float(opn[i]); reason = "GAP"
                        else:
                            ex = stp; reason = "CHANDELIER"
                        _ts_exit = ts.get(day)
                        _et = _ts_exit[i] if _ts_exit is not None and i < len(_ts_exit) else None
                        _record(pos, ex, day.date(), reason, hold, _et)
                        pos = None
                        exit_ts_today = _et
                    else:
                        if pos["dir"] == "LONG":
                            pos["stop"] = float(np.maximum(pos["stop"], run_full[-1] - mult * da))
                        else:
                            pos["stop"] = float(np.minimum(pos["stop"], run_full[-1] + mult * da))
                        pos["extreme"] = float(run_full[-1])

        if pos is None:
            reg = labels.get(day)
            if reg in allowed and (entry_days is None or day in entry_days):
                bars5 = b5[day]; win = bars5.between_time("14:00", "15:55")
                if exit_ts_today is not None:
                    win = win[win.index > exit_ts_today]
                    if len(win) < 2:
                        continue
                idx = list(win.index)
                for n in range(1, len(idx)):
                    hist = bars5.loc[:idx[n]]
                    if len(hist) < max(ema_period, 14) + 1:
                        continue
                    ema = s.calculate_ema(hist, ema_period)
                    atr = atr14(hist)
                    avgv = float(win["volume"].iloc[max(0, n - 11):n - 1].mean())
                    if np.isnan(atr) or np.isnan(avgv):
                        continue
                    sig = s.generate_signal(win.loc[idx[n - 1]], win.loc[idx[n]], ema, atr, reg, avgv)
                    if sig:
                        _N = float(datr.asof(day)) if len(datr) else np.nan   # design #5: N fixed
                        pos = dict(dir=sig["direction"], entry=sig["entry_price"],
                                   entry_day=day, regime=reg,
                                   extreme=sig["entry_price"], stop=sig["initial_stop"],
                                   entry_time=idx[n],
                                   units=1, unit_entries=[sig["entry_price"]], N=_N)
                        break
    return (trades, pos) if return_open else trades
