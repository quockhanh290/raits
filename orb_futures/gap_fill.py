"""
orb_futures/gap_fill.py — Gate 2: GAP FILL (fade the opening gap)
=================================================================
When today's RTH open gaps from yesterday's RTH close by ≥ threshold (in ATR
units), bet the gap fills: gap-up → SHORT toward prev close; gap-down → LONG.
Mean-reversion → potentially uncorrelated with trend-following swing TF. Has
classic literature, but equity-index gaps don't always fill — edge prior moderate.

Entry = open of the first bar after the OR forms (09:46), so the OR gives a stop.
Stop = OR boundary on the gap side; target = prior RTH close. Intraday exit.

    python -m orb_futures.gap_fill --data-dir data\\cache\\futures \
        --regime-csv spy_daily.csv --cost-mult 2.0 [--min-gap-atr 0.3]
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from orb_futures._orb_core import (opening_range, walk_exit, metrics, daily_series,
                                   swing_ref_daily, setup, print_verdict, BASKET)


def gap_backtest(df, labels, cost, *, or_start="09:31", or_end="09:45",
                 mon_end="15:55", allowed=("Calm", "Normal"), atr=None,
                 min_gap_atr=0.3):
    # prior RTH close per day
    rth = df.between_time("09:30", "15:59")
    g = rth.groupby(rth.index.normalize())
    d_open = g["open"].first()
    d_close = g["close"].last()
    d_open.index = pd.DatetimeIndex(d_open.index).tz_localize(None).normalize()
    d_close.index = pd.DatetimeIndex(d_close.index).tz_localize(None).normalize()
    prev_close = d_close.shift(1)

    trades = []
    for day_raw, d in df.groupby(df.index.normalize()):
        if d.empty:
            continue
        day = pd.Timestamp(day_raw).tz_localize(None).normalize()
        if labels.get(day) not in allowed:
            continue
        pc = prev_close.get(day)
        if pc is None or pd.isna(pc):
            continue
        av = atr.asof(day) if atr is not None else None
        if not av or pd.isna(av):
            continue
        topen = d_open.get(day)
        if topen is None or pd.isna(topen):
            continue
        gap = topen - pc
        if abs(gap) < min_gap_atr * av:
            continue
        or_high, or_low, valid = opening_range(d, or_start, or_end, atr, day)
        if not valid:
            continue
        mon = d.between_time("09:46", mon_end)
        if mon.empty:
            continue
        bars = list(mon.itertuples())
        entry = bars[0].open
        if gap > 0:          # gap up → fade SHORT toward prev close
            direction = "SHORT"; stop = or_high; target = pc
            if stop <= entry or target >= entry:
                continue
        else:                # gap down → fade LONG toward prev close
            direction = "LONG"; stop = or_low; target = pc
            if stop >= entry or target <= entry:
                continue
        exit_px = walk_exit(bars[1:], entry, stop, target, direction)
        gross = (exit_px - entry) if direction == "LONG" else (entry - exit_px)
        trades.append(dict(day=day, direction=direction,
                           pnl=gross * cost.point_value - cost.round_turn_cost()))
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--or-min", type=int, default=15)
    ap.add_argument("--allowed", default="Calm,Normal")
    ap.add_argument("--cost-mult", type=float, default=1.0)
    ap.add_argument("--min-gap-atr", type=float, default=0.3)
    ap.add_argument("--pf-min", type=float, default=1.0)
    ap.add_argument("--corr-max", type=float, default=0.3)
    a = ap.parse_args()
    allowed = tuple(a.allowed.split(","))
    or_end = (pd.Timestamp("09:30") + pd.Timedelta(minutes=a.or_min)).strftime("%H:%M")
    ctx = setup(a.data_dir, a.regime_csv, cost_mult=a.cost_mult)

    print(f"\n{'='*72}\nGAP FILL (Gate 2) | Rổ 4 | gap≥{a.min_gap_atr}×ATR | regimes {allowed} | "
          f"cost×{a.cost_mult:g}\n{'='*72}")
    print(f"{'inst':<6}{'n':>6}{'PF':>7}{'WR':>7}{'net$':>10}{'maxDD$':>9}{'Calmar':>8}")
    print("-" * 72)
    pooled, gap_all, sw_all = [], pd.Series(dtype=float), pd.Series(dtype=float)
    for n in BASKET:
        trs = gap_backtest(ctx["dfs"][n], ctx["labels"], ctx["costs"][n],
                           or_end=or_end, allowed=allowed, atr=ctx["atrs"][n],
                           min_gap_atr=a.min_gap_atr)
        pooled += trs
        m = metrics(trs)
        pf = f"{m['pf']:.2f}" if np.isfinite(m['pf']) else "inf"
        cal = f"{m['calmar']:.2f}" if np.isfinite(m['calmar']) else "inf"
        print(f"{n:<6}{m['n']:>6}{pf:>7}{m['wr']*100:>6.0f}%{m['net']:>10,.0f}"
              f"{m['maxdd']:>9,.0f}{cal:>8}")
        gap_all = gap_all.add(daily_series(trs), fill_value=0)
        sw_all = sw_all.add(swing_ref_daily(ctx["dfs"][n], ctx["labels"], ctx["costs"][n]),
                            fill_value=0)
    print_verdict("gap-fill", pooled, gap_all, sw_all, a.pf_min, a.corr_max)


if __name__ == "__main__":
    main()
