"""
global_index/verify_resume.py — does a resumed replay agree with a full one?

backtest_swing_tf can now be seeded with an open position and told which days
are already accounted for, so the live path could stop replaying 2018-to-today
on every five-minute slot. Before it does, the resumed answer has to be shown
identical to the full one on the data live actually runs against.

That is the gap this closes. The equivalence was established on frozen_sim
2018-2024; production reads data/cache/futures, which carries 2025-2026 and the
region rebuilt during the UTC repair, and MNKD had not been checked at all —
different engine parameters, a Tokyo session clock, and its own regime labels.

What live would do, per instrument:
    datr  = daily_atr_series(full frame)          # history the slice lacks
    pos   = checkpoint from the end of day D
    reply = backtest_swing_tf(frame from D onwards, datr=datr,
                              resume_pos=pos, resume_after_day=D)
The frame starts at D, not D+1: _swing_cache reads each bar's gap flag from its
spacing to the previous bar and forces the frame's first bar to "no gap", so D
is present as a lead-in and resume_after_day keeps it out of the replay.

Compared on the whole position — direction, entry, STOP, entry day — because
the stop is what becomes a live STP order, and on the trades produced after D.

    python -m global_index.verify_resume
    python -m global_index.verify_resume --data-dir data/cache/futures --days 1,2,5,10
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import futures._validated_core as vc
from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                     backtest_swing_tf, daily_atr_series)
from futures.basket import BASKET, REGIME, data_filename
from futures.swing_tf import costs_for_basket
from global_index import specs as gi_specs
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index.regime import RegimeLabels

SWING_KW = dict(ema_period=30, chandelier_atr_mult=2.5, max_hold_days=5)
NKD_KW = dict(ema_period=10, chandelier_atr_mult=2.5, max_hold_days=5, gap_fill=True)


def _pos_id(p):
    """The whole position, stop included — that is the number that reaches IBKR."""
    if p is None:
        return None
    return (p["dir"], round(float(p["entry"]), 4), round(float(p["stop"]), 4),
            str(pd.Timestamp(p["entry_day"]).date()))


def _sessions(df):
    """Session dates labelled exactly as _swing_cache labels them.

    It uses pd.Timestamp(d).tz_localize(None) on the tz-aware group key, which
    keeps the wall time and so keeps the local date. Going through .values
    instead converts to UTC first, and for a Tokyo frame midnight JST is 15:00
    UTC the day before — every MNKD session then comes out labelled one day
    early, while ET frames look fine because their midnight stays inside the
    same UTC date. A checkpoint compared against an off-by-one label reports a
    mismatch that is entirely the comparison's own.
    """
    local = df.index.normalize().tz_localize(None)
    uniq, starts = np.unique(local.values, return_index=True)
    ends = np.append(starts[1:], len(local))
    return pd.DatetimeIndex(uniq), starts, ends


def check(name, df, labels, cost, kw, back_days, out):
    sess, starts, ends = _sessions(df)
    datr = daily_atr_series(df)
    vc._SWING_CACHE.clear()
    trades_full, pos_full = backtest_swing_tf(df, labels, cost, return_open=True, **kw)
    print(f"\n=== {name} — {len(sess):,} phien, {len(trades_full):,} lenh, "
          f"den {sess[-1].date()} ===", flush=True)

    for back in back_days:
        ai = len(sess) - 1 - back
        if ai < 300:
            print(f"  lui {back:>3} phien: BO QUA (khong du lich su)")
            continue
        D = sess[ai]
        vc._SWING_CACHE.clear()
        _, pos_at_D = backtest_swing_tf(df.iloc[:ends[ai]], labels, cost,
                                        return_open=True, **kw)
        vc._SWING_CACHE.clear()
        got, pos_r = backtest_swing_tf(df.iloc[starts[ai]:], labels, cost, datr=datr,
                                       resume_pos=pos_at_D, resume_after_day=D,
                                       return_open=True, **kw)
        want = [t for t in trades_full if pd.Timestamp(t["exit_day"]) > D]
        ok_tr = got == want
        ok_pos = _pos_id(pos_r) == _pos_id(pos_full)
        out.append(ok_tr and ok_pos)
        # A checkpoint with no position open and no trades after it exercises
        # almost nothing — the seeding path is never taken. Say so, so a screen
        # of OKs cannot be mistaken for coverage it does not have.
        carried = "co-vi-the" if pos_at_D is not None else "trong    "
        weight = "" if (pos_at_D is not None or want) else "   (khong kiem duoc gi)"
        print(f"  lui {back:>3} phien (checkpoint {D.date()}, {carried}): "
              f"lenh {len(got):>3}/{len(want):>3} {'OK ' if ok_tr else 'LECH'}  "
              f"vi-the-mo {'OK ' if ok_pos else 'LECH'}{weight}", flush=True)
        if not ok_pos:
            print(f"      day-du = {_pos_id(pos_full)}")
            print(f"      resume = {_pos_id(pos_r)}")
        if not ok_tr:
            sw, sg = {str(t) for t in want}, {str(t) for t in got}
            for d in list(sw ^ sg)[:3]:
                print(f"      LECH: {d}")


def main():
    ap = argparse.ArgumentParser(description="resumed replay == full replay?")
    ap.add_argument("--data-dir", default="data/cache/futures")
    ap.add_argument("--nkd-parquet", default="global_index/data/NKD_continuous_1m_8y.parquet")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--days", default="1,2,3,5,10,20",
                    help="checkpoint at N sessions back from the end")
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--only", default="", help="chi chay cac instrument nay (phay)")
    a = ap.parse_args()
    back_days = [int(x) for x in a.days.split(",") if x.strip()]
    only = {s.strip().upper() for s in a.only.split(",") if s.strip()}

    print("=" * 72)
    print(f"VERIFY RESUME | {a.data_dir} | checkpoint lui {back_days} phien")
    print("=" * 72)

    labels = label_regimes(benchmark_daily(a.regime_csv), "2018-01-01", 3,
                           REGIME["hmm_fit_end"])
    costs = costs_for_basket(slippage_ticks=a.slippage_ticks)
    out = []
    for inst, c in BASKET.items():
        if only and inst not in only:
            continue
        df = load_parquet(str(Path(a.data_dir) / data_filename(c)))
        check(inst, df, labels, costs[inst], SWING_KW, back_days, out)
        del df

    # MNKD: its own engine parameters, Tokyo session clock, lagged SPY labels.
    if only and "MNKD" not in only:
        return _verdict(out)
    cn = gi_specs.SPECS["MNKD"]
    spy = pd.Series(label_regimes(benchmark_daily(a.regime_csv), "2018-01-01", 3,
                                  REGIME["hmm_fit_end"]))
    idx = pd.DatetimeIndex(spy.index)
    spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    ndf = gi_load(a.nkd_parquet)
    ndf.index = ndf.index.tz_convert(cn.session_tz)
    ncost = GIFC(point_value=cn.point_value, tick=cn.tick,
                 commission_rt=cn.commission_rt,
                 slippage_ticks_per_side=a.slippage_ticks)
    check("MNKD", ndf, RegimeLabels(spy.sort_index(), lag_days=1), ncost,
          NKD_KW, back_days, out)

    return _verdict(out)


def _verdict(out):
    print("\n" + "=" * 72)
    print(f"TONG: {sum(out)}/{len(out)} checkpoint khop tuyet doi")
    print("VERDICT: " + ("[PASS] resume == full replay tren du lieu live"
                         if all(out) and out else "[FAIL] xem cac dong LECH o tren"))
    print("=" * 72)
    return 0 if out and all(out) else 1


if __name__ == "__main__":
    sys.exit(main())
