"""
pooled_swing_wfo.py — WFO the swing-TF BASKET as ONE equity curve (read-only)
============================================================================
Per-instrument WFO judges each index alone on small per-fold samples (22-81
trades → noisy Calmar; RTY/YM "fail" may be small-sample noise). The deployable
object is the BASKET. This walk-forwards the basket as a whole:

  - ONE shared param per fold (ema_period, chandelier_atr_mult), chosen on the
    POOLED train equity curve. Fewer DoF than per-instrument params → less
    overfit; tests "does a single trend config work across the basket?"
  - Equal-weight 1-micro each. Basket daily P&L = sum across instruments.
  - OOS test applies the train-chosen shared param to all instruments.
  - Stitched basket OOS → Calmar / PF / 2× cost, the real deployable verdict.

CAVEAT: the indices are correlated (~0.9). Pooling raises per-fold SAMPLE but
not the number of independent market episodes (still ~2017-2022). It validates
the basket as a unit, not as independent bets.

    python pooled_swing_wfo.py --instruments "ES=...:5,NQ=...:2,YM=...:0.5,RTY=...:5" \
        --regime-csv spy_daily.csv --hmm-train-end 2018-01-01 --hmm-fit-end 2024-12-31 \
        --vault-start 2023-01-01 --train-months 18 --test-months 6
"""
from __future__ import annotations
import argparse, itertools, sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path.cwd()))

GRID = {"ema_period": [10, 20, 30], "chandelier_atr_mult": [2.5, 3.0, 3.5]}


def _isfloat(s):
    try:
        float(s); return True
    except ValueError:
        return False


def parse_instrument(spec):
    """NAME=path:point_value[:tick]  → (name, path, point_value, tick).
    Trailing numeric tokens are pv (+optional tick); rest is the path (drive-colon safe)."""
    name, rest = spec.split("=", 1)
    toks = rest.split(":")
    nums = []
    while toks and _isfloat(toks[-1]):
        nums.insert(0, float(toks.pop()))
    path = ":".join(toks)
    pv = nums[0]
    tick = nums[1] if len(nums) > 1 else 0.25
    return name.strip(), path.strip(), pv, tick


def basket_metrics(trades_by_inst, day_filter=None):
    """trades_by_inst: dict inst -> list of trade dicts (day, pnl).
    Basket daily P&L = sum across instruments by entry day. Returns metrics."""
    rows = []
    for inst, trs in trades_by_inst.items():
        for r in trs:
            d = pd.Timestamp(r["day"])
            if day_filter is None or d in day_filter:
                rows.append((d, r["pnl"]))
    if not rows:
        return dict(n=0, pnl=0.0, calmar=0.0, sharpe=0.0, pf=0.0, expect=0.0)
    df = pd.DataFrame(rows, columns=["day", "pnl"])
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    ann = daily.sum() / span
    w = daily[daily > 0].sum(); l = -daily[daily < 0].sum()
    return dict(n=len(df), pnl=float(df["pnl"].sum()),
                calmar=float(ann/dd) if dd > 1e-9 else float("inf"),
                sharpe=float(daily.mean()/daily.std()*np.sqrt(252)) if daily.std() > 1e-9 else 0.0,
                pf=float(w/l) if l > 1e-9 else float("inf"),
                expect=float(df["pnl"].mean()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments", required=True, help="NAME=parquet:pointvalue,...")
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end", default="2024-12-31")
    ap.add_argument("--hmm-components", type=int, default=3)
    ap.add_argument("--vault-start", default="2023-01-01")
    ap.add_argument("--train-months", type=int, default=18)
    ap.add_argument("--test-months", type=int, default=6)
    ap.add_argument("--max-hold-days", type=int, default=5)
    ap.add_argument("--slippage-ticks", type=float, default=1.0,
                    help="slippage per side in ticks (raise to stress-test fills)")
    ap.add_argument("--no-gap-fill", action="store_true",
                    help="disable gap-through modeling (optimistic baseline)")
    a = ap.parse_args()

    import gate2_edge_harness as G
    from swing_tf_harness import backtest_swing_tf

    vault_start = pd.Timestamp(a.vault_start)
    daily_bench = G.benchmark_daily(a.regime_csv)
    daily_bench = daily_bench[daily_bench.index < vault_start]
    labels = G.label_regimes(daily_bench, a.hmm_train_end, a.hmm_components, a.hmm_fit_end)

    print(f"\n{'='*70}\nPOOLED SWING-TF WFO (basket as one) | {a.instruments.count('=')} instruments\n{'='*70}")
    print(f"WFO < {vault_start.date()} | shared param/fold | regime SPY\n")

    # precompute per (inst, param) full-history trades at 1× and 2× cost
    grid = [dict(zip(GRID, c)) for c in itertools.product(*GRID.values())]
    insts = {}
    for spec in a.instruments.split(","):
        name, pq, pv, tick = parse_instrument(spec)
        df = G.load_parquet(pq)
        df = df[df.index < vault_start.tz_localize(df.index.tz)]
        insts[name] = (df, pv, tick)
        print(f"  loaded {name} ({len(df):,} bars, pv={pv}, tick={tick})")

    def full(cost_mult):
        """dict inst -> param-key -> trades, at given cost multiplier."""
        out = {}
        for name, (df, pv, tick) in insts.items():
            base = G.FuturesCost(point_value=pv, tick=tick, slippage_ticks_per_side=a.slippage_ticks)
            cost = (base if cost_mult == 1 else
                    G.FuturesCost(point_value=pv, tick=tick, commission_rt=base.commission_rt*2,
                                  slippage_ticks_per_side=base.slippage_ticks_per_side*2))
            out[name] = {}
            for p in grid:
                trs = backtest_swing_tf(df, labels, cost, ema_period=p["ema_period"],
                                        chandelier_atr_mult=p["chandelier_atr_mult"],
                                        max_hold_days=a.max_hold_days, entry_days=None,
                                        gap_fill=not a.no_gap_fill)
                out[name][(p["ema_period"], p["chandelier_atr_mult"])] = trs
        return out

    print("\n  running swing backtests (grid × instruments × 2 costs)... slow, one-off")
    F1 = full(1); F2 = full(2)

    def trades_for(F, pkey, day_set):
        return {n: [r for r in F[n][pkey] if pd.Timestamp(r["day"]) in day_set] for n in insts}

    # WFO folds
    start = pd.Timestamp(a.hmm_train_end)
    train_len = pd.DateOffset(months=a.train_months); test_len = pd.DateOffset(months=a.test_months)
    all_days = sorted({pd.Timestamp(r["day"]) for n in insts for p in F1[n] for r in F1[n][p]})
    last = all_days[-1]
    tcur = start
    oos1, oos2, fold_rows, chosen = [], [], [], []
    while tcur + train_len + test_len <= last + pd.DateOffset(days=1):
        tr_lo, tr_hi = tcur, tcur + train_len; te_lo, te_hi = tr_hi, tr_hi + test_len
        tr_set = {d for d in all_days if tr_lo <= d < tr_hi}
        te_set = {d for d in all_days if te_lo <= d < te_hi}
        tcur = tcur + test_len
        if len(tr_set) < 8 or not te_set:
            continue
        best, bc = None, -1e9
        for p in grid:
            pk = (p["ema_period"], p["chandelier_atr_mult"])
            m = basket_metrics(trades_for(F1, pk, tr_set))
            if m["n"] >= 10 and m["calmar"] > bc:
                bc, best = m["calmar"], pk
        if best is None:
            continue
        te1 = trades_for(F1, best, te_set); te2 = trades_for(F2, best, te_set)
        fm = basket_metrics(te1)
        for n in insts:
            oos1.extend((n, r) for r in te1[n]); oos2.extend((n, r) for r in te2[n])
        chosen.append(best)
        fold_rows.append((f"{te_lo.date()}→{te_hi.date()}", best, fm["n"], fm["pnl"], fm["calmar"]))

    print(f"\nRolling folds ({len(fold_rows)}):  [train {a.train_months}mo → test {a.test_months}mo, shared param]")
    for lbl, pk, n, pnl, cal in fold_rows:
        print(f"  {lbl}  ema={pk[0]},mult={pk[1]}   OOS {n:>3}t  ${pnl:>8,.0f}  Calmar {cal:>6.2f}")

    def stitch(oos):
        by = {}
        for n, r in oos:
            by.setdefault(n, []).append(r)
        return basket_metrics(by)
    o1, o2 = stitch(oos1), stitch(oos2)
    print(f"\nSTITCHED BASKET OOS (1× cost): {o1['n']}t  ${o1['pnl']:,.0f}  "
          f"Calmar {o1['calmar']:.2f}  Sharpe {o1['sharpe']:.2f}  PF {o1['pf']:.2f}  exp ${o1['expect']:.2f}")
    print(f"STITCHED BASKET OOS (2× cost): {o2['n']}t  ${o2['pnl']:,.0f}  Calmar {o2['calmar']:.2f}")
    cnt = pd.Series([str(c) for c in chosen]).value_counts()
    print("\nShared param across folds:")
    for k, v in cnt.items():
        print(f"  {v}×  {k}")
    print("\n" + "-"*70)
    p1, p2 = o1["calmar"] >= 1.0, o2["pnl"] > 0
    if p1 and p2:
        print(f"VERDICT: [PASS] basket OOS Calmar {o1['calmar']:.2f} ≥ 1.0 and profitable at 2× cost.")
        print("         The basket-as-a-whole is WFO-robust → proceed to pooled vault.")
    else:
        print(f"VERDICT: [FAIL] basket OOS Calmar {o1['calmar']:.2f} / 2× ${o2['pnl']:,.0f}.")
    print("-"*70 + "\n")


if __name__ == "__main__":
    main()
