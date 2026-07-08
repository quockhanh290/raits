"""
global_index/combined_system.py — NKD + Rổ 4 replayed through the risk layer
=============================================================================
combined.py pools raw P&L. THIS replays day-by-day through the deployed risk
layer, so skipped entries are actually skipped:

  • MultiClusterGuard → per-cluster exposure caps (Rổ-4 swing / Rổ-4 stress /
    NKD), each independent — NKD never crowds out Rổ 4 and vice-versa.
  • CircuitBreaker    → ACCOUNT-LEVEL drawdown halt, COMBINED across all clusters
    (one account; a global risk-off draws every equity cluster down together).

Shows the risk layer's impact (entries taken/rejected per cluster, halts) and
system metrics vs the naive pooled combined. ~1% ($500) risk per position for the
count caps (matches the live sizer target); calibrate in paper.

    python -m global_index.combined_system --data-dir data\\cache\\futures \
        --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet \
        --regime-csv spy_daily.csv [--include-stress] [--start ...] [--end ...]
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
    from global_index import specs as gi_specs
    from global_index.regime import RegimeLabels
    from global_index.net_exposure_multi import MultiClusterGuard, Position, entry_priority_key
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
    from global_index import specs as gi_specs
    from global_index.regime import RegimeLabels
    from global_index.net_exposure_multi import MultiClusterGuard, Position, entry_priority_key


def metrics(daily: pd.Series) -> dict:
    if daily.empty:
        return dict(pnl=0.0, pf=0.0, calmar=0.0, sharpe=0.0, maxdd=0.0)
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    w = daily[daily > 0].sum(); l = -daily[daily < 0].sum()
    return dict(pnl=float(daily.sum()), pf=float(w/l) if l > 1e-9 else float("inf"),
                calmar=float((daily.sum()/span)/dd) if dd > 1e-9 else float("inf"),
                sharpe=float(daily.mean()/daily.std()*np.sqrt(252)) if daily.std() > 1e-9 else 0.0,
                maxdd=dd)


def run_system(all_trades, account, guard, breaker_cls):
    """Chronological replay. all_trades: list of dict(entry, exit, direction, cluster,
    inst, pnl, risk). Returns (daily realized pnl, stats)."""
    breaker = breaker_cls(account=account) if breaker_cls else None
    days = sorted({t["entry"] for t in all_trades} | {t["exit"] for t in all_trades})
    by_entry = {}
    for t in all_trades:
        by_entry.setdefault(t["entry"], []).append(t)

    open_pos = []           # (Position, trade)
    realized = {}
    equity = account
    taken = {c: 0 for c in guard.clusters}
    rej = {c: 0 for c in guard.clusters}
    halt = 0

    for day in days:
        # exits first
        still = []
        for pos, t in open_pos:
            if t["exit"] == day:
                equity += t["pnl"]; realized[day] = realized.get(day, 0.0) + t["pnl"]
            else:
                still.append((pos, t))
        open_pos = still

        allow = True
        if breaker is not None:
            breaker.update(equity)
            allow = breaker.status(equity).get("allow_new_entries", True)

        for t in sorted(by_entry.get(day, []), key=entry_priority_key):
            if not allow:
                halt += 1; continue
            pos = Position(t["inst"], t["direction"], 1, t["risk"], t["cluster"])
            ok, _ = guard.admits(pos, [p for p, _ in open_pos])
            if not ok:
                rej[t["cluster"]] += 1; continue
            taken[t["cluster"]] += 1
            if t["exit"] == day:
                equity += t["pnl"]; realized[day] = realized.get(day, 0.0) + t["pnl"]
            else:
                open_pos.append((pos, t))

    daily = pd.Series(realized).sort_index()
    return daily, dict(taken=taken, rejected=rej, halted=halt, total=len(all_trades))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--nkd-parquet", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--include-stress", action="store_true")
    ap.add_argument("--nkd-instrument", default="MNKD", choices=list(gi_specs.SPECS.keys()))
    ap.add_argument("--nkd-ema", type=int, default=10)
    ap.add_argument("--nkd-mult", type=float, default=2.5)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--account", type=float, default=50_000.0)
    ap.add_argument("--risk-per-pos", type=float, default=500.0)
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end", default="2024-12-31")
    a = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from futures._validated_core import load_parquet, benchmark_daily, label_regimes, backtest_swing_tf
    from futures.basket import BASKET, data_filename
    from futures.swing_tf import SwingTFEngine, costs_for_basket
    try:
        from futures.circuit_breaker import CircuitBreaker
    except Exception:
        CircuitBreaker = None

    def clip(df):
        if a.start: df = df[df.index >= pd.Timestamp(a.start).tz_localize(df.index.tz)]
        if a.end:   df = df[df.index <= pd.Timestamp(a.end).tz_localize(df.index.tz)]
        return df

    # Rổ 4
    dfs = {n: clip(load_parquet(str(Path(a.data_dir) / data_filename(c)))) for n, c in BASKET.items()}
    bench = benchmark_daily(a.regime_csv)
    if a.start: bench = bench[bench.index >= pd.Timestamp(a.start)]
    if a.end:   bench = bench[bench.index <= pd.Timestamp(a.end)]
    labels = label_regimes(bench, a.hmm_train_end, 3, a.hmm_fit_end)
    costs = costs_for_basket()
    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)
    stress = SwingTFEngine and None
    if a.include_stress:
        from futures.stress_mid import StressMidEngine
        stress = StressMidEngine().backtest_basket(dfs, labels, costs)

    # NKD
    c = gi_specs.SPECS[a.nkd_instrument]
    spy = pd.Series(label_regimes(benchmark_daily(a.regime_csv), a.hmm_train_end, 3, a.hmm_fit_end))
    idx = pd.DatetimeIndex(spy.index); spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nlab = RegimeLabels(spy.sort_index(), lag_days=1)
    ndf = gi_load(a.nkd_parquet); ndf.index = ndf.index.tz_convert(c.session_tz); ndf = clip(ndf)
    ncost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt)
    nkd = backtest_swing_tf(ndf, nlab, ncost, ema_period=a.nkd_ema,
                            chandelier_atr_mult=a.nkd_mult, max_hold_days=5, gap_fill=True)

    # assemble trades with cluster tags
    all_tr = []
    for inst, lst in swing.items():
        for t in lst:
            all_tr.append(dict(inst=inst, cluster="roska4_swing", entry=pd.Timestamp(t["day"]),
                               exit=pd.Timestamp(t["exit_day"]), direction=t["direction"],
                               pnl=t["pnl"], risk=a.risk_per_pos))
    if a.include_stress and stress:
        for inst, lst in stress.items():
            for t in lst:
                all_tr.append(dict(inst=inst, cluster="roska4_stress", entry=pd.Timestamp(t["day"]),
                                   exit=pd.Timestamp(t["exit_day"]), direction=t["direction"],
                                   pnl=t["pnl"], risk=a.risk_per_pos))
    for t in nkd:
        all_tr.append(dict(inst=a.nkd_instrument, cluster="global_nkd",
                           entry=pd.Timestamp(t["day"]).tz_localize(None),
                           exit=pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else pd.Timestamp(t["day"]).tz_localize(None),
                           direction=t["direction"], pnl=t["pnl"], risk=a.risk_per_pos))

    # naive pooled
    pooled = pd.DataFrame([(pd.Timestamp(t["entry"]).normalize(), t["pnl"]) for t in all_tr],
                          columns=["d", "p"]).groupby("d")["p"].sum().sort_index()

    guard = MultiClusterGuard(account=a.account)
    sys_daily, st = run_system(all_tr, a.account, guard, CircuitBreaker)

    print(f"\n{'='*70}\nFULL SYSTEM | Rổ 4 {'+ STRESS ' if a.include_stress else ''}+ NKD | "
          f"multi-cluster exposure + account DD\n{'='*70}")
    pm, sm = metrics(pooled), metrics(sys_daily)
    print(f"  naive pooled (no risk layer): net ${pm['pnl']:>9,.0f} | "
          f"Calmar {pm['calmar']:>5.2f} | MaxDD ${pm['maxdd']:>7,.0f} | PF {pm['pf']:.2f}")
    print(f"  FULL SYSTEM  (risk layer on): net ${sm['pnl']:>9,.0f} | "
          f"Calmar {sm['calmar']:>5.2f} | MaxDD ${sm['maxdd']:>7,.0f} | PF {sm['pf']:.2f}")
    print("\n  per-cluster entries taken / rejected:")
    for cl in guard.clusters:
        print(f"    {cl:<14} taken {st['taken'][cl]:>4}  rejected {st['rejected'][cl]:>3}")
    print(f"    circuit-breaker halts: {st['halted']}")
    print("\nPer-year (full system):")
    for y, g in sys_daily.groupby(sys_daily.index.year):
        print(f"  {y}  net ${g.sum():>9,.0f}")
    print("-"*70 + "\n")


if __name__ == "__main__":
    main()
