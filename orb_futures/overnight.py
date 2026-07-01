"""
orb_futures/overnight.py — Gate 2: OVERNIGHT hold (close → next open)
=====================================================================
Enter at RTH close (15:55 ET), hold overnight, exit at next RTH open (09:31).
Captures the "overnight equity premium" (equities historically earn most of their
return overnight, not intraday). Structurally the MOST uncorrelated with swing TF
(entirely different time-of-day, no intraday overlap) — but edge prior unknown for
index futures, and it carries genuine overnight gap risk (no intraday stop).

Default LONG (classic risk-on overnight). Regime-gated. P&L attributed to entry
day D (the day the position is put on). One position/instrument/night.

    python -m orb_futures.overnight --data-dir data\\cache\\futures \
        --regime-csv spy_daily.csv --cost-mult 2.0 [--allowed Calm,Normal] [--direction LONG]
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from orb_futures._orb_core import (metrics, daily_series, swing_ref_daily,
                                   setup, print_verdict, BASKET)


def overnight_backtest(df, labels, cost, *, allowed=("Calm", "Normal"),
                       direction="LONG"):
    rth = df.between_time("09:30", "15:59")
    g = rth.groupby(rth.index.normalize())
    d_open = g["open"].first()
    d_close = g["close"].last()
    d_open.index = pd.DatetimeIndex(d_open.index).tz_localize(None).normalize()
    d_close.index = pd.DatetimeIndex(d_close.index).tz_localize(None).normalize()
    next_open = d_open.shift(-1)   # exit price = next day's RTH open

    trades = []
    for day in d_close.index:
        if labels.get(day) not in allowed:
            continue
        entry = d_close.get(day); exit_px = next_open.get(day)
        if entry is None or exit_px is None or pd.isna(entry) or pd.isna(exit_px):
            continue
        gross = (exit_px - entry) if direction == "LONG" else (entry - exit_px)
        trades.append(dict(day=day, direction=direction,
                           pnl=gross * cost.point_value - cost.round_turn_cost()))
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--allowed", default="Calm,Normal")
    ap.add_argument("--direction", default="LONG", choices=["LONG", "SHORT"])
    ap.add_argument("--cost-mult", type=float, default=1.0)
    ap.add_argument("--pf-min", type=float, default=1.0)
    ap.add_argument("--corr-max", type=float, default=0.3)
    a = ap.parse_args()
    allowed = tuple(a.allowed.split(","))
    ctx = setup(a.data_dir, a.regime_csv, cost_mult=a.cost_mult)

    print(f"\n{'='*72}\nOVERNIGHT (Gate 2) | Rổ 4 | {a.direction} close→next-open | "
          f"regimes {allowed} | cost×{a.cost_mult:g}\n{'='*72}")
    print(f"{'inst':<6}{'n':>6}{'PF':>7}{'WR':>7}{'net$':>10}{'maxDD$':>9}{'Calmar':>8}")
    print("-" * 72)
    pooled, on_all, sw_all = [], pd.Series(dtype=float), pd.Series(dtype=float)
    for n in BASKET:
        trs = overnight_backtest(ctx["dfs"][n], ctx["labels"], ctx["costs"][n],
                                 allowed=allowed, direction=a.direction)
        pooled += trs
        m = metrics(trs)
        pf = f"{m['pf']:.2f}" if np.isfinite(m['pf']) else "inf"
        cal = f"{m['calmar']:.2f}" if np.isfinite(m['calmar']) else "inf"
        print(f"{n:<6}{m['n']:>6}{pf:>7}{m['wr']*100:>6.0f}%{m['net']:>10,.0f}"
              f"{m['maxdd']:>9,.0f}{cal:>8}")
        on_all = on_all.add(daily_series(trs), fill_value=0)
        sw_all = sw_all.add(swing_ref_daily(ctx["dfs"][n], ctx["labels"], ctx["costs"][n]),
                            fill_value=0)
    print_verdict("overnight", pooled, on_all, sw_all, a.pf_min, a.corr_max)


if __name__ == "__main__":
    main()
