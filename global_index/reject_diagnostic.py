"""
global_index/reject_diagnostic.py — is the 22% reject benign or biased?
=======================================================================
At cap 5%, 22% of entries are rejected. Two very different causes:
  BENIGN: the 3rd/4th leg of an all-long correlated burst (dropping redundant
          concentrated risk — cap doing its job).
  BIASED: MNQ (real risk $1,386, 2.8× M2K's $520) eats the budget and blocks the
          SMALLER, less-correlated indices (M2K/MYM) — cap penalizing by ATR, not
          by genuine concentration. That would argue for risk-normalized sizing.

This replays cap 5% / 1 micro and reports rejects PER INSTRUMENT, plus what was
open at each reject, so we can see which case it is.

    python -m global_index.reject_diagnostic --data-dir data\\cache\\futures \
        --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet --regime-csv spy_daily.csv
"""
from __future__ import annotations
import argparse, sys
from collections import Counter
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
    ap.add_argument("--hmm-fit-end", default="2022-12-31")
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

    def rrisk(ser, mult, point_value, ed):
        try:
            av = ser.asof(pd.Timestamp(ed))
        except Exception:
            av = np.nan
        if av is None or pd.isna(av):
            av = float(ser.median())
        return mult * float(av) * point_value

    tr = []
    for inst, lst in swing.items():
        for t in lst:
            ed = pd.Timestamp(t["day"])
            tr.append(dict(inst=inst, cluster="roska4_swing", entry=ed, exit=pd.Timestamp(t["exit_day"]),
                           direction=t["direction"], risk=rrisk(atr[inst], a.roska4_mult, pv[inst], ed)))
    for inst, lst in stress.items():
        for t in lst:
            ed = pd.Timestamp(t["day"])
            tr.append(dict(inst=inst, cluster="roska4_stress", entry=ed, exit=pd.Timestamp(t["exit_day"]),
                           direction=t["direction"], risk=rrisk(atr[inst], a.roska4_mult, pv[inst], ed)))
    for t in nkd:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = (pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed)
        tr.append(dict(inst=a.nkd_instrument, cluster="global_nkd", entry=ed, exit=xd,
                       direction=t["direction"], risk=rrisk(natr, a.nkd_mult, c.point_value, ed)))

    cl = {"roska4_swing": ClusterBudget("roska4_swing", a.gross_cap, a.gross_cap*0.875),
          "roska4_stress": ClusterBudget("roska4_stress", 0.025, None),
          "global_nkd": ClusterBudget("global_nkd", 0.02, 0.02)}
    guard = MultiClusterGuard(clusters=cl, account=a.account)
    breaker = CircuitBreaker(account=a.account) if CircuitBreaker else None

    days = sorted({t["entry"] for t in tr} | {t["exit"] for t in tr})
    by_entry = {}
    for t in tr:
        by_entry.setdefault(t["entry"], []).append(t)

    open_pos = []
    taken = Counter(); rej = Counter()
    rej_when_open = Counter()       # (rejected_inst, an-open-inst) co-occurrence
    equity = a.account; cur = None
    for day in days:
        open_pos = [(p, t) for p, t in open_pos if t["exit"] != day]
        for p, t in [(p, t) for p, t in open_pos if t["exit"] == day]:
            equity += 0
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
                taken[t["inst"]] += 1
                if t["exit"] != day:
                    open_pos.append((pos, t))
            else:
                rej[t["inst"]] += 1
                for p2, _ in open_pos:
                    if p2.cluster == t["cluster"]:
                        rej_when_open[p2.instrument] += 1

    print(f"\n{'='*64}\nREJECT DIAGNOSTIC @ gross cap {a.gross_cap:.0%} | 1 micro | slippage {a.slippage_ticks:g}t")
    print(f"{'='*64}")
    print(f"{'instrument':<12}{'taken':>7}{'rejected':>10}{'reject%':>9}{'risk$':>9}")
    print("-"*64)
    med_risk = {inst: float(np.median([t['risk'] for t in tr if t['inst']==inst])) for inst in
                set(t['inst'] for t in tr)}
    order = ["MES", "MNQ", "MYM", "M2K", a.nkd_instrument]
    for inst in order:
        tk, rj = taken[inst], rej[inst]; tot = tk + rj
        if tot == 0:
            continue
        print(f"{inst:<12}{tk:>7}{rj:>10}{rj/tot:>8.0%}{med_risk.get(inst,0):>9,.0f}")
    print("-"*64)
    print("When a Rổ-4 entry was REJECTED, which instrument was already open (top):")
    for inst, n in rej_when_open.most_common(5):
        print(f"  {inst:<6} open during {n} rejects   (risk ${med_risk.get(inst,0):,.0f})")
    print("-"*64)
    print("read: rejects spread evenly across all 4 → benign (concentration trim).")
    print("  rejects dumped on M2K/MYM while MNQ dominates 'open during' → MNQ's high")
    print("  ATR eats the budget and crowds the small indices → risk-normalize sizing.\n")


if __name__ == "__main__":
    main()
