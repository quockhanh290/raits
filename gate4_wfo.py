"""
gate4_wfo.py — RAITS × MES Gate 4: walk-forward optimization + cost stress
==========================================================================
STANDALONE, READ-ONLY. For ONE winner (trend_follow or stress_mid):

  1. Reserve a VAULT slice (last N months) — NEVER touched here (saved for Gate 5).
  2. Rolling walk-forward over the rest: train window → test window, roll forward.
       per fold: grid-search params on TRAIN (pick best by Calmar),
                 apply that param to the immediately-following TEST window.
  3. Stitch all OOS test-fold trades → honest out-of-sample metrics.
  4. Cost stress: recompute the stitched OOS result at 2× costs.
  5. Report pass/fail + the most robust param (carry to Gate 5).

No look-ahead: params are chosen only on train data; HMM regimes are fit once on
a pre-WFO window and predicted forward (expanding), matching Gates 2–3.

Reuses gate2_edge_harness (load_parquet, daily_close_series, label_regimes,
resample_5m, adapters, FuturesCost) — engine untouched.

Usage
-----
    python gate4_wfo.py --parquet ES_7y.parquet --strategy trend_follow \\
        --hmm-train-end 2020-01-01 --vault-start 2024-01-01
    python gate4_wfo.py --parquet ES_7y.parquet --strategy stress_mid \\
        --hmm-train-end 2020-01-01 --vault-start 2024-01-01
"""
from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.cwd()))

# Pre-registered small grids (Bonferroni discipline — keep them small)
GRIDS = {
    "trend_follow": {"ema_period": [10, 20, 30], "chandelier_atr_mult": [2.5, 3.0, 3.5]},
    "stress_mid":   {"target_rr": [1.5, 2.0, 2.5], "max_stop_pct": [0.010, 0.015, 0.020]},
}
PASS_CALMAR = 1.0          # OOS Calmar gate


def metrics(trades, equity_ref: float = 50_000.0) -> dict:
    """Calmar / Sharpe / PF / expectancy from a trade list (day, pnl)."""
    if not trades:
        return {"n": 0, "pnl": 0.0, "calmar": 0.0, "sharpe": 0.0, "pf": 0.0, "expect": 0.0}
    df = pd.DataFrame({"day": [pd.Timestamp(t.day).normalize() for t in trades],
                       "pnl": [t.pnl for t in trades]})
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    peak = eq.cummax()
    max_dd = float((peak - eq).max())                 # $ drawdown
    span_yrs = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    ann = daily.sum() / span_yrs
    calmar = (ann / max_dd) if max_dd > 1e-9 else float("inf")
    sharpe = (daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 1e-9 else 0.0
    wins = daily[daily > 0].sum(); losses = abs(daily[daily < 0].sum())
    pf = (wins / losses) if losses > 1e-9 else float("inf")
    return {"n": len(trades), "pnl": float(daily.sum()), "calmar": float(calmar),
            "sharpe": float(sharpe), "pf": float(pf),
            "expect": float(np.mean([t.pnl for t in trades]))}


def main():
    ap = argparse.ArgumentParser(description="Gate 4: WFO + cost stress (read-only).")
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--strategy", choices=list(GRIDS), required=True)
    ap.add_argument("--hmm-train-end", default="2020-01-01")
    ap.add_argument("--hmm-fit-end", default=None,
                    help="fit HMM on a FIXED diverse window up to this date (incl. stress "
                         "periods), decoupled from WFO train_end — fixes unstable Stress labeling")
    ap.add_argument("--vault-start", default="2024-01-01", help="everything >= this is RESERVED")
    ap.add_argument("--train-months", type=int, default=18)
    ap.add_argument("--test-months", type=int, default=6)
    ap.add_argument("--hmm-components", type=int, default=3)
    ap.add_argument("--regime-csv", default=None,
                    help="SPY daily CSV (date,close) for instrument-agnostic regime labeling")
    ap.add_argument("--point-value", type=float, default=5.0)
    ap.add_argument("--swing", action="store_true",
                    help="TREND_FOLLOW only: hold across days (chandelier daily-ATR trail, "
                         "force-close at --max-hold-days) instead of intraday close")
    ap.add_argument("--max-hold-days", type=int, default=5)
    a = ap.parse_args()

    import gate2_edge_harness as G

    print(f"\n{'='*68}\nGATE 4 WFO | {a.strategy} | {Path(a.parquet).name}\n{'='*68}")
    df = G.load_parquet(a.parquet)
    vault_start = pd.Timestamp(a.vault_start)
    # hard cut: nothing at/after vault_start enters WFO
    df_wfo = df[df.index < vault_start.tz_localize(df.index.tz)]
    print(f"WFO data: {df_wfo.index[0].date()} → {df_wfo.index[-1].date()} "
          f"(vault {vault_start.date()}+ reserved, untouched)")

    if a.regime_csv:
        daily = G.benchmark_daily(a.regime_csv)
        daily = daily[daily.index < vault_start]
        print("Regime source: SPY benchmark (instrument-agnostic)")
    else:
        daily = G.daily_close_series(df_wfo)
    labels = G.label_regimes(daily, a.hmm_train_end, a.hmm_components, a.hmm_fit_end)
    cost = G.FuturesCost(point_value=a.point_value)
    cost2x = G.FuturesCost(point_value=a.point_value, commission_rt=cost.commission_rt * 2,
                           slippage_ticks_per_side=cost.slippage_ticks_per_side * 2)

    # pre-group days → 5m frames once (both winners are 5m)
    allowed = G.ADAPTERS[a.strategy]().allowed
    days_5m = {}
    for day, g in df_wfo.groupby(df_wfo.index.normalize()):
        key = pd.Timestamp(day).tz_localize(None).normalize()
        if labels.get(key) in allowed:
            days_5m[key] = G.resample_5m(g)
    test_dates = sorted(days_5m.keys())
    print(f"Tradeable {a.strategy} days (in allowed regime): {len(test_dates)}")

    _swing_full = {}
    def run_param(params, date_subset, cost_obj=cost):
        if a.swing:
            from swing_tf_harness import backtest_swing_tf
            import types
            pk = (params["ema_period"], params["chandelier_atr_mult"], id(cost_obj))
            if pk not in _swing_full:
                _swing_full[pk] = backtest_swing_tf(
                    df_wfo, labels, cost_obj,
                    ema_period=params["ema_period"],
                    chandelier_atr_mult=params["chandelier_atr_mult"],
                    max_hold_days=a.max_hold_days, entry_days=None)  # full history once
            want = {pd.Timestamp(d).date() for d in date_subset}
            return [types.SimpleNamespace(day=r["day"], pnl=r["pnl"])
                    for r in _swing_full[pk] if r["day"] in want]
        adapter = G.ADAPTERS[a.strategy](params)
        out = []
        for d in date_subset:
            out.extend(adapter.run_day(days_5m[d], labels[d], cost_obj))
        return out

    # rolling folds
    grid = [dict(zip(GRIDS[a.strategy], combo))
            for combo in itertools.product(*GRIDS[a.strategy].values())]
    start = pd.Timestamp(a.hmm_train_end)
    train_len = pd.DateOffset(months=a.train_months)
    test_len = pd.DateOffset(months=a.test_months)
    oos_trades, fold_rows, chosen = [], [], []
    tcur = start
    last = pd.Timestamp(test_dates[-1])
    while tcur + train_len + test_len <= last + pd.DateOffset(days=1):
        tr_lo, tr_hi = tcur, tcur + train_len
        te_lo, te_hi = tr_hi, tr_hi + test_len
        tr_days = [d for d in test_dates if tr_lo <= pd.Timestamp(d) < tr_hi]
        te_days = [d for d in test_dates if te_lo <= pd.Timestamp(d) < te_hi]
        tcur = tcur + test_len
        if len(tr_days) < 8 or not te_days:
            continue
        # grid-search on TRAIN by Calmar
        best, best_c = None, -1e9
        for p in grid:
            m = metrics(run_param(p, tr_days))
            if m["n"] >= 5 and m["calmar"] > best_c:
                best_c, best = m["calmar"], p
        if best is None:
            continue
        te_tr = run_param(best, te_days)          # apply to TEST (OOS)
        oos_trades.extend(te_tr)
        chosen.append(tuple(best.items()))
        fm = metrics(te_tr)
        fold_rows.append((f"{te_lo.date()}→{te_hi.date()}", best, fm["n"], fm["pnl"], fm["calmar"]))

    # report folds
    print(f"\nRolling folds ({len(fold_rows)}):  [train {a.train_months}mo → test {a.test_months}mo]")
    for lbl, p, n, pnl, cal in fold_rows:
        ps = ",".join(f"{k}={v}" for k, v in p.items())
        print(f"  {lbl}  {ps:<34} OOS {n:>3}t  ${pnl:>8,.0f}  Calmar {cal:>5.2f}")

    # stitched OOS
    o1 = metrics(oos_trades)
    print(f"\nSTITCHED OOS (1× cost): {o1['n']}t  ${o1['pnl']:,.0f}  "
          f"Calmar {o1['calmar']:.2f}  Sharpe {o1['sharpe']:.2f}  PF {o1['pf']:.2f}  exp ${o1['expect']:.2f}")

    # cost stress 2x: recompute pnl on same trades by re-running with cost2x
    # (re-run the chosen-per-fold params at 2x cost)
    oos_2x = []
    tcur = start
    while tcur + train_len + test_len <= last + pd.DateOffset(days=1):
        tr_hi = tcur + train_len; te_lo, te_hi = tr_hi, tr_hi + test_len
        tr_days = [d for d in test_dates if tcur <= pd.Timestamp(d) < tr_hi]
        te_days = [d for d in test_dates if te_lo <= pd.Timestamp(d) < te_hi]
        tcur = tcur + test_len
        if len(tr_days) < 8 or not te_days:
            continue
        best, best_c = None, -1e9
        for p in grid:
            m = metrics(run_param(p, tr_days))
            if m["n"] >= 5 and m["calmar"] > best_c:
                best_c, best = m["calmar"], p
        if best is None:
            continue
        oos_2x.extend(run_param(best, te_days, cost2x))
    o2 = metrics(oos_2x)
    print(f"STITCHED OOS (2× cost): {o2['n']}t  ${o2['pnl']:,.0f}  Calmar {o2['calmar']:.2f}")

    # param stability + recommended frozen param
    print("\nParam selection across folds:")
    cnt = pd.Series([str(dict(c)) for c in chosen]).value_counts()
    for k, v in cnt.items():
        print(f"  {v}×  {k}")

    # verdict
    print("\n" + "-" * 68)
    p1 = o1["calmar"] >= PASS_CALMAR
    p2 = o2["pnl"] > 0
    if p1 and p2:
        print(f"VERDICT: [PASS] OOS Calmar {o1['calmar']:.2f} ≥ {PASS_CALMAR} and profitable at 2× cost.")
        print(f"         Most-robust param for Gate 5: {cnt.index[0]}")
    else:
        fails = []
        if not p1: fails.append(f"OOS Calmar {o1['calmar']:.2f} < {PASS_CALMAR}")
        if not p2: fails.append(f"dies at 2× cost (${o2['pnl']:,.0f})")
        print(f"VERDICT: [FAIL] {', '.join(fails)}.")
        print("         Do NOT proceed to vault; the edge is not robust OOS.")
    print("-" * 68 + "\n")


if __name__ == "__main__":
    main()
