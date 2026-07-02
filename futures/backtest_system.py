# HARNESS: documents 2-cluster risk-layer stage (pre cap/priority/NKD). Intentionally
#  uses futures.net_exposure. Live deploy uses global_index/net_exposure_multi + live_decision.
"""
futures/backtest_system.py — FULL SYSTEM backtest (engines + risk layer)
========================================================================
backtest_combined.py pools raw engine P&L. THIS replays the deployed system
day-by-day through the risk layer, so entries the live system would SKIP are
actually skipped here:

  • sizer            → contracts per instrument (1 micro to start)
  • net_exposure     → rejects correlated same-direction entries beyond net cap
  • circuit_breaker  → halts NEW entries when drawdown hits WARN/HALT

Realized P&L marks on exit day; drawdown/halt run on the realized equity curve.
Each open position is assumed to risk ~1% ($500) for the net-exposure count cap
(matches the live sizer's target). Reports the risk layer's IMPACT (entries
rejected / halted) and the system metrics vs the naive pooled combined.

    python -m futures.backtest_system --data-dir data\\cache\\futures \\
        --regime-csv spy_daily.csv [--start ...] [--end ...] [--contracts 1]
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
import numpy as np
import pandas as pd

from futures.basket import BASKET, RISK
from futures.net_exposure import NetExposureGuard, Position
from futures.circuit_breaker import CircuitBreaker


def metrics(daily: pd.Series) -> dict:
    if daily.empty:
        return dict(pnl=0, pf=0, calmar=0, sharpe=0, maxdd=0)
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    ann = daily.sum() / span
    w = daily[daily > 0].sum(); l = -daily[daily < 0].sum()
    return dict(pnl=float(daily.sum()), pf=float(w/l) if l > 1e-9 else float("inf"),
                calmar=float(ann/dd) if dd > 1e-9 else float("inf"),
                sharpe=float(daily.mean()/daily.std()*np.sqrt(252)) if daily.std() > 1e-9 else 0.0,
                maxdd=dd)


def run_system(swing_by_inst, stress_by_inst, account, contracts,
               risk_per_pos=None, net_cap=0.035, gross_cap=0.04, stress_cap=0.025):
    """Chronological replay with the full risk layer. Returns (daily_pnl, stats)."""
    risk_per_pos = risk_per_pos or account * RISK["risk_per_trade_pct"]   # ~$500
    guard = NetExposureGuard(account=account, max_net_pct=net_cap,
                             max_gross_one_side_pct=gross_cap,
                             max_stress_gross_pct=stress_cap)
    breaker = CircuitBreaker(account=account)

    # build entry/exit events keyed by date
    trades = []
    for engine, book in (("swing_tf", swing_by_inst), ("stress_mid", stress_by_inst)):
        for inst, lst in book.items():
            for t in lst:
                trades.append(dict(inst=inst, engine=engine,
                                   entry=pd.Timestamp(t["day"]),
                                   exit=pd.Timestamp(t["exit_day"]),
                                   direction=t["direction"],
                                   pnl=t["pnl"] * contracts))
    if not trades:
        return pd.Series(dtype=float), {}
    days = sorted({t["entry"] for t in trades} | {t["exit"] for t in trades})
    by_entry = {}
    for t in trades:
        by_entry.setdefault(t["entry"], []).append(t)

    open_pos = []          # list of (Position, trade)
    realized = {}          # day -> realized pnl
    equity = account
    n_taken = n_rej_net = n_halt = 0

    for day in days:
        # 1) exits first: multi-day positions whose exit is today
        still = []
        for pos, t in open_pos:
            if t["exit"] == day:
                equity += t["pnl"]
                realized[day] = realized.get(day, 0.0) + t["pnl"]
            else:
                still.append((pos, t))
        open_pos = still

        # 2) circuit breaker on realized equity
        breaker.update(equity)
        cb = breaker.status(equity)

        # 3) entries (gated)
        for t in by_entry.get(day, []):
            if not cb["allow_new_entries"]:
                n_halt += 1
                continue
            pos = Position(t["inst"], t["direction"], contracts, risk_per_pos, t["engine"])
            ok, _ = guard.admits(pos, [p for p, _ in open_pos])
            if not ok:
                n_rej_net += 1
                continue
            n_taken += 1
            if t["exit"] == day:
                # intraday round-trip (STRESS_MID): realize now, do NOT hold overnight
                equity += t["pnl"]
                realized[day] = realized.get(day, 0.0) + t["pnl"]
            else:
                open_pos.append((pos, t))   # multi-day hold (swing TF)

    daily = pd.Series(realized).sort_index()
    stats = dict(taken=n_taken, rejected_net=n_rej_net, halted=n_halt,
                 total_signals=len(trades))
    return daily, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--contracts", type=int, default=1)
    ap.add_argument("--account", type=float, default=RISK["account"])
    ap.add_argument("--net-cap", type=float, default=0.035, help="swing TF net cap")
    ap.add_argument("--gross-cap", type=float, default=0.04, help="swing TF gross one-side cap")
    ap.add_argument("--stress-cap", type=float, default=0.025, help="STRESS_MID sleeve gross cap")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    a = ap.parse_args()

    from futures._validated_core import load_parquet, benchmark_daily, label_regimes
    from futures.basket import data_filename
    from futures.swing_tf import SwingTFEngine, costs_for_basket
    from futures.stress_mid import StressMidEngine

    dfs = {}
    for name, c in BASKET.items():
        df = load_parquet(str(Path(a.data_dir) / data_filename(c)))
        if a.start: df = df[df.index >= pd.Timestamp(a.start).tz_localize(df.index.tz)]
        if a.end:   df = df[df.index <= pd.Timestamp(a.end).tz_localize(df.index.tz)]
        dfs[name] = df
    daily_bench = benchmark_daily(a.regime_csv)
    if a.start: daily_bench = daily_bench[daily_bench.index >= pd.Timestamp(a.start)]
    if a.end:   daily_bench = daily_bench[daily_bench.index <= pd.Timestamp(a.end)]
    labels = label_regimes(daily_bench, a.hmm_train_end, 3, "2022-12-31")  # harness — fit_A reference, not paper path
    costs = costs_for_basket()

    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)
    stress = StressMidEngine().backtest_basket(dfs, labels, costs)

    # naive pooled (no risk layer)
    pooled_rows = [(pd.Timestamp(r["day"]), r["pnl"] * a.contracts)
                   for bk in (swing, stress) for lst in bk.values() for r in lst]
    pooled = pd.DataFrame(pooled_rows, columns=["d", "p"]).groupby("d")["p"].sum().sort_index()

    # full system (with risk layer)
    sys_daily, st = run_system(swing, stress, a.account, a.contracts,
                               net_cap=a.net_cap, gross_cap=a.gross_cap,
                               stress_cap=a.stress_cap)

    print(f"\n{'='*70}\nFULL SYSTEM BACKTEST | 2 engines + risk layer | {a.contracts} micro each\n{'='*70}")
    pm, sm = metrics(pooled), metrics(sys_daily)
    print(f"  naive pooled (no risk layer): net ${pm['pnl']:>9,.0f} | "
          f"Calmar {pm['calmar']:>5.2f} | MaxDD ${pm['maxdd']:>7,.0f} | PF {pm['pf']:.2f}")
    print(f"  FULL SYSTEM  (risk layer on): net ${sm['pnl']:>9,.0f} | "
          f"Calmar {sm['calmar']:>5.2f} | MaxDD ${sm['maxdd']:>7,.0f} | PF {sm['pf']:.2f}")
    print(f"\n  risk-layer impact: {st['taken']}/{st['total_signals']} entries taken | "
          f"{st['rejected_net']} rejected (net cap) | {st['halted']} halted (circuit breaker)")
    print("\nPer-year (full system):")
    for y, g in sys_daily.groupby(sys_daily.index.year):
        print(f"  {y}  net ${g.sum():>9,.0f}")
    print("-"*70 + "\n")


if __name__ == "__main__":
    main()
