"""
global_index/reject_value_diagnostic.py — $ value of rejects, not just count
=============================================================================
Reject COUNT says nothing about quality. A cap dropping 22% of entries that were
all losers is a GOOD cap; dropping 22% winners is a BAD cap. This measures the
backtest P&L of REJECTED vs TAKEN entries, per instrument, so we can tell which:

  rejected avg P&L  <<  taken avg P&L   → cap drops the weak entries → working well
  rejected avg P&L  ≈   taken avg P&L   → cap drops ~randomly by budget/timing →
                                          priority-by-EV could recover value
  rejected avg P&L  >   taken avg P&L   → cap drops the GOOD ones → bad; re-think

CAVEAT (first-order): a rejected entry's P&L is its standalone backtest P&L. If
actually admitted it would consume budget and crowd OUT a later entry, so total
"forgone" here is an UPPER BOUND of what relaxing could recover. The true
counterfactual is cap_sweep (relax cap → see net rise). This shows WHICH entries
are dropped; cap_sweep shows the real total recoverable.

    python -m global_index.reject_value_diagnostic --data-dir data\\cache\\futures \
        --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet --regime-csv spy_daily.csv
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index import specs as gi_specs
from global_index.regime import RegimeLabels
from global_index.net_exposure_multi import MultiClusterGuard, ClusterBudget, Position


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--nkd-parquet", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--gross-cap", type=float, default=0.05)
    ap.add_argument("--nkd-instrument", default="MNKD")
    ap.add_argument("--nkd-ema", type=int, default=10)
    ap.add_argument("--nkd-mult", type=float, default=2.5)
    ap.add_argument("--roska4-mult", type=float, default=2.5)
    ap.add_argument("--account", type=float, default=50_000.0)
    ap.add_argument("--slippage-ticks", type=float, default=1.0)
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end", default="2024-12-31")
    a = ap.parse_args()

    from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                         backtest_swing_tf, daily_atr_series)
    from futures.basket import BASKET, data_filename
    from futures.swing_tf import SwingTFEngine, costs_for_basket
    try:
        from futures.circuit_breaker import CircuitBreaker
    except Exception:
        CircuitBreaker = None

    dfs = {n: load_parquet(str(Path(a.data_dir) / data_filename(c))) for n, c in BASKET.items()}
    atr = {n: daily_atr_series(df) for n, df in dfs.items()}
    pv = {n: c.point_value for n, c in BASKET.items()}
    bench = benchmark_daily(a.regime_csv)
    labels = label_regimes(bench, a.hmm_train_end, 3, a.hmm_fit_end)
    costs = costs_for_basket(slippage_ticks=a.slippage_ticks)
    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)
    from futures.stress_mid import StressMidEngine
    stress = StressMidEngine().backtest_basket(dfs, labels, costs)

    c = gi_specs.SPECS[a.nkd_instrument]
    spy = pd.Series(label_regimes(benchmark_daily(a.regime_csv), a.hmm_train_end, 3, a.hmm_fit_end))
    idx = pd.DatetimeIndex(spy.index); spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nlab = RegimeLabels(spy.sort_index(), lag_days=1)
    ndf = gi_load(a.nkd_parquet); ndf.index = ndf.index.tz_convert(c.session_tz)
    natr = daily_atr_series(ndf)
    ncost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
                 slippage_ticks_per_side=a.slippage_ticks)
    nkd = backtest_swing_tf(ndf, nlab, ncost, ema_period=a.nkd_ema,
                            chandelier_atr_mult=a.nkd_mult, max_hold_days=5, gap_fill=True)

    def rrisk(ser, mult, pvv, ed):
        try:
            av = ser.asof(pd.Timestamp(ed))
        except Exception:
            av = np.nan
        if av is None or pd.isna(av):
            av = float(ser.median())
        return mult * float(av) * pvv

    tr = []
    for inst, lst in swing.items():
        for t in lst:
            ed = pd.Timestamp(t["day"])
            tr.append(dict(inst=inst, cluster="roska4_swing", entry=ed, exit=pd.Timestamp(t["exit_day"]),
                           direction=t["direction"], risk=rrisk(atr[inst], a.roska4_mult, pv[inst], ed),
                           pnl=t["pnl"]))
    for inst, lst in stress.items():
        for t in lst:
            ed = pd.Timestamp(t["day"])
            tr.append(dict(inst=inst, cluster="roska4_stress", entry=ed, exit=pd.Timestamp(t["exit_day"]),
                           direction=t["direction"], risk=rrisk(atr[inst], a.roska4_mult, pv[inst], ed),
                           pnl=t["pnl"]))
    for t in nkd:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = (pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed)
        tr.append(dict(inst=a.nkd_instrument, cluster="global_nkd", entry=ed, exit=xd,
                       direction=t["direction"], risk=rrisk(natr, a.nkd_mult, c.point_value, ed), pnl=t["pnl"]))

    cl = {"roska4_swing": ClusterBudget("roska4_swing", a.gross_cap, a.gross_cap*0.875),
          "roska4_stress": ClusterBudget("roska4_stress", 0.025, None),
          "global_nkd": ClusterBudget("global_nkd", 0.02, 0.02)}
    guard = MultiClusterGuard(clusters=cl, account=a.account)
    breaker = CircuitBreaker(account=a.account) if CircuitBreaker else None

    days = sorted({t["entry"] for t in tr} | {t["exit"] for t in tr})
    by_entry = {}
    for t in tr:
        by_entry.setdefault(t["entry"], []).append(t)

    open_pos = []; equity = a.account; cur = None
    taken_pnl = {}; rej_pnl = {}      # inst -> list of pnl
    for day in days:
        open_pos = [(p, t) for p, t in open_pos if t["exit"] != day]
        allow = True
        if breaker:
            if cur != day:
                breaker.start_day(equity); cur = day
            breaker.update(equity); allow = breaker.status(equity).get("allow_new_entries", True)
        for t in by_entry.get(day, []):
            if not allow:
                continue
            pos = Position(t["inst"], t["direction"], 1, t["risk"], t["cluster"])
            ok, _ = guard.admits(pos, [p for p, _ in open_pos])
            if ok:
                taken_pnl.setdefault(t["inst"], []).append(t["pnl"])
                equity += t["pnl"] if t["exit"] == day else 0
                if t["exit"] != day:
                    open_pos.append((pos, t))
            else:
                rej_pnl.setdefault(t["inst"], []).append(t["pnl"])

    def stats(lst):
        if not lst:
            return (0, 0.0, 0.0, 0.0)
        a_ = np.array(lst)
        return (len(a_), float(a_.sum()), float(a_.mean()), float((a_ > 0).mean()))

    print(f"\n{'='*84}\nREJECT VALUE @ cap {a.gross_cap:.0%} | slippage {a.slippage_ticks:g}t | "
          f"first-order (ignores crowding)\n{'='*84}")
    print(f"{'inst':<8}{'taken_n':>8}{'tk_avg$':>9}{'tk_WR':>7}  |"
          f"{'rej_n':>7}{'rej_sum$':>10}{'rej_avg$':>10}{'rej_WR':>7}  verdict")
    print("-"*84)
    order = ["MES", "MNQ", "MYM", "M2K", a.nkd_instrument]
    tot_rej_sum = 0.0
    for inst in order:
        tn, ts, ta, tw = stats(taken_pnl.get(inst, []))
        rn, rs, ra, rw = stats(rej_pnl.get(inst, []))
        if tn + rn == 0:
            continue
        tot_rej_sum += rs
        if rn == 0:
            v = "no rejects"
        elif ra < ta * 0.5:
            v = "drops WEAK ✓"
        elif ra > ta:
            v = "drops GOOD ✗"
        else:
            v = "~similar (timing)"
        print(f"{inst:<8}{tn:>8}{ta:>9,.0f}{tw*100:>6.0f}%  |{rn:>7}{rs:>10,.0f}{ra:>10,.0f}{rw*100:>6.0f}%  {v}")
    print("-"*84)
    print(f"first-order forgone P&L (sum of rejected entries' standalone P&L): ${tot_rej_sum:,.0f}")
    print("  if ≈0 or negative → cap drops break-even/losing dups → cap is FREE/good.")
    print("  if large positive → cap leaves money on the table → relax (but verify the")
    print("  REAL recoverable amount with cap_sweep, since crowding makes this an upper bound).\n")


if __name__ == "__main__":
    main()
