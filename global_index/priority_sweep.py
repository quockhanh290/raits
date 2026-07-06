"""
global_index/priority_sweep.py — does reordering within the cap recover value?
==============================================================================
reject_value showed cap 5% drops MNQ entries worth avg $46 (the BEST entries) by
time-ordering. Question: in an all-correlated burst, if we keep the higher-value
legs instead of whoever-came-first, do we get more — WITHOUT raising the cap (so
DD stays put)?

The trap: ordering by "MNQ is best" uses full-history P&L we've already seen =
overfit. So we ONLY test A-PRIORI rules that don't look at outcomes:
  time            : current behavior (admit in trade order)
  risk-low-first  : admit smallest risk$ first → more independent legs per budget
  risk-high-first : admit largest risk$ first → keeps the high-vol (MNQ-like) legs

If a rule beats time on Calmar at the SAME cap & 1 micro, the gain is structural,
not fitted. (Still in-sample-broad; confirm survivors via WFO/paper before trust.)

    python -m global_index.priority_sweep --data-dir data\\cache\\futures \
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


def metrics(daily: pd.Series) -> dict:
    if daily.empty:
        return dict(pnl=0.0, calmar=0.0, maxdd=0.0, pf=0.0)
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    w = daily[daily > 0].sum(); l = -daily[daily < 0].sum()
    return dict(pnl=float(daily.sum()), calmar=float((daily.sum()/span)/dd) if dd > 1e-9 else float("inf"),
                maxdd=dd, pf=float(w/l) if l > 1e-9 else float("inf"))


def replay(tr, account, guard, breaker, order_key):
    """order_key: function(trade)->sortkey, applied to same-day same-cluster entries
    before admission. None = trade order (time)."""
    days = sorted({t["entry"] for t in tr} | {t["exit"] for t in tr})
    by_entry = {}
    for t in tr:
        by_entry.setdefault(t["entry"], []).append(t)
    open_pos = []; realized = {}; equity = account; cur = None; rej = 0; tk = 0
    for day in days:
        keep = []
        for p, t in open_pos:
            if t["exit"] == day:
                equity += t["pnl"]; realized[day] = realized.get(day, 0.0) + t["pnl"]
            else:
                keep.append((p, t))
        open_pos = keep
        allow = True
        if breaker is not None:
            if cur != day:
                breaker.start_day(equity); cur = day
            breaker.update(equity); allow = breaker.status(equity).get("allow_new_entries", True)
        todays = by_entry.get(day, [])
        if order_key is not None:
            todays = sorted(todays, key=order_key)
        for t in todays:
            if not allow:
                continue
            pos = Position(t["inst"], t["direction"], 1, t["risk"], t["cluster"])
            ok, _ = guard.admits(pos, [p for p, _ in open_pos])
            if ok:
                tk += 1
                if t["exit"] == day:
                    equity += t["pnl"]; realized[day] = realized.get(day, 0.0) + t["pnl"]
                else:
                    open_pos.append((pos, t))
            else:
                rej += 1
    return pd.Series(realized).sort_index(), tk, rej


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

    def make_guard():
        cl = {"roska4_swing": ClusterBudget("roska4_swing", a.gross_cap, a.gross_cap*0.875),
              "roska4_stress": ClusterBudget("roska4_stress", 0.025, None),
              "global_nkd": ClusterBudget("global_nkd", 0.02, 0.02)}
        return MultiClusterGuard(clusters=cl, account=a.account)

    rules = {
        "time (current)":   None,
        "risk-low-first":   lambda t: t["risk"],
        "risk-high-first":  lambda t: -t["risk"],
    }

    print(f"\n{'='*70}\nPRIORITY SWEEP @ cap {a.gross_cap:.0%} | 1 micro | slippage {a.slippage_ticks:g}t")
    print(f"{'='*70}")
    print("a-priori ordering rules only (no P&L peeking) | in-sample-broad — confirm via WFO\n")
    print(f"{'rule':<18}{'net$':>11}{'Calmar':>8}{'MaxDD$':>10}{'taken':>8}{'reject':>8}")
    print("-"*70)
    base = None
    for name, key in rules.items():
        br = CircuitBreaker(account=a.account) if CircuitBreaker else None
        d, tk, rj = replay(tr, a.account, make_guard(), br, key)
        m = metrics(d)
        if base is None:
            base = m["calmar"]
        tag = "" if name.startswith("time") else (f"  (+{m['calmar']-base:.2f})" if m['calmar'] > base
                                                  else f"  ({m['calmar']-base:.2f})")
        print(f"{name:<18}{m['pnl']:>11,.0f}{m['calmar']:>8.2f}{m['maxdd']:>10,.0f}{tk:>8}{rj:>8}{tag}")
    print("-"*70)
    print("read: if a reorder rule beats 'time' on Calmar at SAME cap, the gain is structural")
    print("  (not fitted). Wire it as the live entry-priority. If none beats time, ordering")
    print("  doesn't matter — cap 5% time-order is already efficient; leave it.\n")


if __name__ == "__main__":
    main()
