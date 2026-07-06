"""
global_index/wfo.py — walk-forward OOS for a global index (NKD), gated vs agnostic
==================================================================================
Settles the gated-vs-regime-agnostic question by OOS, not in-sample net$. Reuses
the EXACT validated engine (futures._validated_core.backtest_swing_tf) and the
SAME WFO logic as pooled_swing_wfo.py (rolling train→test, shared param/fold
chosen on train Calmar, stitched OOS at 1× and 2× cost) — adapted for ONE index
in its local session tz.

Why a wrapper (not pooled_swing_wfo.py directly): that script loads ET and labels
regime in ET. A foreign index needs (a) tz-convert so the 14:00-15:55 window is
the LOCAL power hour, and (b) the lookahead-safe JST→ET regime mapping (or no
regime at all). We change only those two things; the engine + WFO mechanics are
identical → by construction the same test Rổ 4 passed.

    python -m global_index.wfo --parquet global_index/data/NKD_continuous_1m_8y.parquet \
        --instrument MNKD --tz Asia/Tokyo --regime-mode gated --regime-csv spy_daily.csv \
        --vault-start 2023-01-01 --train-months 18 --test-months 6
    # then run again with --regime-mode agnostic and compare stitched OOS Calmar.
"""
from __future__ import annotations
import argparse, itertools, sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from global_index._core import load_parquet, FuturesCost
    from global_index import specs
    from global_index.regime import load_spy_regime, RegimeLabels
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from global_index._core import load_parquet, FuturesCost
    from global_index import specs
    from global_index.regime import load_spy_regime, RegimeLabels

GRID = {"ema_period": [10, 20, 30], "chandelier_atr_mult": [2.5, 3.0, 3.5]}


class AllNormal:
    def get(self, _d, default=None):
        return "Normal"


def inst_metrics(trades, day_set=None):
    rows = [(pd.Timestamp(r["day"]), r["pnl"]) for r in trades
            if day_set is None or pd.Timestamp(r["day"]) in day_set]
    if not rows:
        return dict(n=0, pnl=0.0, calmar=0.0, pf=0.0)
    df = pd.DataFrame(rows, columns=["day", "pnl"])
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    ann = daily.sum() / span
    w = daily[daily > 0].sum(); l = -daily[daily < 0].sum()
    return dict(n=len(df), pnl=float(df["pnl"].sum()),
                calmar=float(ann / dd) if dd > 1e-9 else float("inf"),
                pf=float(w / l) if l > 1e-9 else float("inf"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--instrument", default="MNKD", choices=list(specs.SPECS.keys()))
    ap.add_argument("--tz", default="Asia/Tokyo")
    ap.add_argument("--regime-mode", choices=["gated", "agnostic"], default="gated")
    ap.add_argument("--regime-csv", help="required if --regime-mode gated")
    ap.add_argument("--regime-lag", type=int, default=1)
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end", default="2024-12-31")
    ap.add_argument("--vault-start", default="2023-01-01")
    ap.add_argument("--train-months", type=int, default=18)
    ap.add_argument("--test-months", type=int, default=6)
    ap.add_argument("--max-hold-days", type=int, default=5)
    ap.add_argument("--slippage-ticks", type=float, default=1.0)
    ap.add_argument("--select-cost-mult", type=float, choices=[1.0, 2.0], default=1.0,
                    help="choose fold param on Calmar at this cost (2.0 = realistic "
                         "cost-aware selection for thin micros like MNKD)")
    a = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from futures._validated_core import backtest_swing_tf

    c = specs.SPECS[a.instrument]
    vault_start = pd.Timestamp(a.vault_start)

    if a.regime_mode == "gated":
        if not a.regime_csv:
            ap.error("--regime-mode gated requires --regime-csv")
        spy = load_spy_regime(a.regime_csv, a.hmm_train_end, 3, a.hmm_fit_end)
        spy = spy[spy.index < vault_start]              # never label using vault-era SPY
        labels = RegimeLabels(spy, lag_days=a.regime_lag)
    else:
        labels = AllNormal()

    df = load_parquet(a.parquet)
    df.index = df.index.tz_convert(a.tz)                # window → local power hour
    df = df[df.index < vault_start.tz_localize(a.tz)]   # WFO region only

    print(f"\n{'='*68}\nNKD WFO ({a.regime_mode}) | {a.instrument} pv=${c.point_value} tick={c.tick} "
          f"| tz {a.tz}\n{'='*68}")
    print(f"WFO < {vault_start.date()} | shared param/fold | "
          f"train {a.train_months}mo→test {a.test_months}mo | "
          f"select@{a.select_cost_mult:g}× cost\n")

    grid = [dict(zip(GRID, x)) for x in itertools.product(*GRID.values())]

    def full(cost_mult):
        base = FuturesCost(point_value=c.point_value, tick=c.tick,
                           commission_rt=c.commission_rt, slippage_ticks_per_side=a.slippage_ticks)
        cost = base if cost_mult == 1 else base.stressed(2.0)
        out = {}
        for p in grid:
            trs = backtest_swing_tf(df, labels, cost, ema_period=p["ema_period"],
                                    chandelier_atr_mult=p["chandelier_atr_mult"],
                                    max_hold_days=a.max_hold_days, gap_fill=True)
            out[(p["ema_period"], p["chandelier_atr_mult"])] = trs
        return out

    print("  running grid × 2 costs (one-off, slow)...")
    F1, F2 = full(1), full(2)
    F_sel = F2 if a.select_cost_mult == 2.0 else F1
    print(f"  param selection on Calmar at {a.select_cost_mult:g}× cost")

    all_days = sorted({pd.Timestamp(r["day"]) for p in F1 for r in F1[p]})
    if not all_days:
        print("  no trades — check regime/window. abort."); return
    start = pd.Timestamp(a.hmm_train_end)
    tl = pd.DateOffset(months=a.train_months); te = pd.DateOffset(months=a.test_months)
    last = all_days[-1]; tcur = start
    oos1, oos2, folds, chosen = [], [], [], []
    while tcur + tl + te <= last + pd.DateOffset(days=1):
        tr_lo, tr_hi = tcur, tcur + tl; te_lo, te_hi = tr_hi, tr_hi + te
        tr_set = {d for d in all_days if tr_lo <= d < tr_hi}
        te_set = {d for d in all_days if te_lo <= d < te_hi}
        tcur = tcur + te
        if len(tr_set) < 8 or not te_set:
            continue
        best, bc = None, -1e9
        for p in grid:
            pk = (p["ema_period"], p["chandelier_atr_mult"])
            m = inst_metrics(F_sel[pk], tr_set)
            if m["n"] >= 10 and m["calmar"] > bc:
                bc, best = m["calmar"], pk
        if best is None:
            continue
        fm = inst_metrics(F_sel[best], te_set)
        oos1 += [r for r in F1[best] if pd.Timestamp(r["day"]) in te_set]
        oos2 += [r for r in F2[best] if pd.Timestamp(r["day"]) in te_set]
        chosen.append(best)
        folds.append((f"{te_lo.date()}→{te_hi.date()}", best, fm["n"], fm["pnl"], fm["calmar"]))

    print(f"\nRolling folds ({len(folds)}):")
    for lbl, pk, n, pnl, cal in folds:
        print(f"  {lbl}  ema={pk[0]},mult={pk[1]}   OOS {n:>3}t  ${pnl:>8,.0f}  Calmar {cal:>6.2f}")

    o1, o2 = inst_metrics(oos1), inst_metrics(oos2)
    pos = sum(1 for _, _, _, p, _ in folds if p > 0)
    print(f"\nSTITCHED OOS 1×: {o1['n']}t  ${o1['pnl']:,.0f}  Calmar {o1['calmar']:.2f}  PF {o1['pf']:.2f}")
    print(f"STITCHED OOS 2×: {o2['n']}t  ${o2['pnl']:,.0f}  Calmar {o2['calmar']:.2f}  PF {o2['pf']:.2f}")
    print(f"positive folds: {pos}/{len(folds)}")
    cnt = pd.Series([str(x) for x in chosen]).value_counts()
    print("shared param across folds:", ", ".join(f"{v}×{k}" for k, v in cnt.items()))
    print("-" * 68)
    # same bar as Rổ 4: OOS Calmar ≥ 1.0 AND profitable at 2× cost
    p1, p2 = o1["calmar"] >= 1.0, o2["pnl"] > 0
    verdict = "PASS" if (p1 and p2) else "FAIL"
    print(f"VERDICT [{a.regime_mode}]: {verdict} — OOS Calmar {o1['calmar']:.2f} "
          f"(≥1.0?{'Y' if p1 else 'N'}), 2× net ${o2['pnl']:,.0f} ({'>0' if p2 else '≤0'})")
    print(f"  → run the OTHER --regime-mode and compare: higher OOS Calmar wins, "
          f"NOT higher in-sample net$.\n")


if __name__ == "__main__":
    main()
