"""Stage 5ZZZ-L — the full Swing WFO under causal D-1, on the engine that makes the artifacts.

Grid, protocol and promotion thresholds were committed in
`scratch/track1_stage5zzzl_precommit_20260829.md` before this ran.

The engine is `futures._validated_core.backtest_swing_tf`, which is what `SwingTFEngine.backtest`
imports and therefore what generates the promotion artifacts the full-stack replay consumes. The
older `futures.swing_tf_harness.backtest_swing_tf` - used by `pooled_swing_wfo.py` and by Stage
5ZZZ-I - is a different function producing different trades, and tuning on it selects for a
strategy this pipeline does not run.

Selection touches the FLOOR region only. 2025 and 2026 are never read here.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from collections import Counter
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import numpy as np
import pandas as pd

GRID = {"ema_period": [10, 20, 30, 50],
        "chandelier_atr_mult": [2.0, 2.5, 3.0, 3.5],
        "max_hold_days": [3, 5, 10]}
TRAIN_MONTHS, TEST_MONTHS = 18, 6
MIN_TRAIN_TRADES = 10
HMM_TRAIN_END = "2018-01-01"
FLOOR = {"data_dir": "data/cache/futures/frozen_sim", "end": "2024-12-31",
         "hmm_fit_end": "2022-12-31", "slippage": 2.0}


def basket_metrics(trades_by_inst, day_filter=None) -> dict:
    """The objective, unchanged from `pooled_swing_wfo.basket_metrics`."""
    rows = []
    for _inst, trs in trades_by_inst.items():
        for r in trs:
            d = pd.Timestamp(r["day"])
            if day_filter is None or d in day_filter:
                rows.append((d, r["pnl"]))
    if not rows:
        return dict(n=0, pnl=0.0, calmar=0.0, sharpe=0.0, pf=0.0)
    df = pd.DataFrame(rows, columns=["day", "pnl"])
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    ann = daily.sum() / span
    w = daily[daily > 0].sum()
    ll = -daily[daily < 0].sum()
    return dict(n=len(df), pnl=float(df["pnl"].sum()),
                calmar=float(ann / dd) if dd > 1e-9 else float("inf"),
                sharpe=float(daily.mean() / daily.std() * np.sqrt(252))
                if daily.std() > 1e-9 else 0.0,
                pf=float(w / ll) if ll > 1e-9 else float("inf"))


def build():
    from futures._validated_core import benchmark_daily, label_regimes
    from futures.basket import BASKET, data_filename
    from futures.swing_tf import costs_for_basket
    from global_index._core import load_parquet
    from global_index.regime import RegimeLabels

    dfs = {}
    for name, c in BASKET.items():
        df = load_parquet(str(Path(FLOOR["data_dir"]) / data_filename(c)))
        df = df[df.index <= pd.Timestamp(FLOOR["end"]).tz_localize(df.index.tz)]
        dfs[name] = df
    bench = benchmark_daily("spy_daily_live.csv")
    bench = bench[bench.index < pd.Timestamp(FLOOR["end"]) + pd.Timedelta(days=1)]
    raw = label_regimes(bench, HMM_TRAIN_END, 3, FLOOR["hmm_fit_end"])
    ser = pd.Series(raw)
    idx = pd.DatetimeIndex(ser.index)
    ser.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    labels = RegimeLabels(ser.sort_index(), lag_days=1)     # CAUSAL D-1, the only labels used
    return dfs, labels, costs_for_basket(slippage_ticks=FLOOR["slippage"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="scratch/track1_stage5zzzl_full_wfo_20260829.json")
    a = ap.parse_args()

    from futures._validated_core import backtest_swing_tf as ENGINE

    dfs, labels, costs = build()
    grid = [dict(zip(GRID, c)) for c in itertools.product(*GRID.values())]
    print(f"engine: futures._validated_core.backtest_swing_tf")
    print(f"grid:   {len(grid)} combinations  {GRID}", flush=True)

    t0 = time.perf_counter()
    F: dict = {n: {} for n in dfs}
    for name, df in dfs.items():
        for i, p in enumerate(grid, 1):
            key = (p["ema_period"], p["chandelier_atr_mult"], p["max_hold_days"])
            F[name][key] = ENGINE(df, labels, costs[name],
                                  ema_period=p["ema_period"],
                                  chandelier_atr_mult=p["chandelier_atr_mult"],
                                  max_hold_days=p["max_hold_days"])
            if i % 12 == 0:
                print(f"    {name} {i}/{len(grid)}  "
                      f"({time.perf_counter() - t0:,.0f}s)", flush=True)
        print(f"  {name}: done, {sum(len(v) for v in F[name].values()):,} trades "
              f"({time.perf_counter() - t0:,.0f}s)", flush=True)

    def trades_for(pk, day_set):
        # `day_set=None` means every day - the pooled context table asks for that, and the
        # first run of this script crashed there because the filter assumed a set.
        if day_set is None:
            return {n: list(F[n][pk]) for n in F}
        return {n: [r for r in F[n][pk] if pd.Timestamp(r["day"]) in day_set] for n in F}

    all_days = sorted({pd.Timestamp(r["day"]) for n in F for p in F[n] for r in F[n][p]})
    assert all_days, "no trades at all; the fold loop would silently do nothing"
    last = all_days[-1]
    tcur = pd.Timestamp(HMM_TRAIN_END)
    train_len = pd.DateOffset(months=TRAIN_MONTHS)
    test_len = pd.DateOffset(months=TEST_MONTHS)

    folds, chosen = [], []
    while tcur + train_len + test_len <= last + pd.DateOffset(days=1):
        tr_lo, tr_hi = tcur, tcur + train_len
        te_lo, te_hi = tr_hi, tr_hi + test_len
        tr_set = {d for d in all_days if tr_lo <= d < tr_hi}
        te_set = {d for d in all_days if te_lo <= d < te_hi}
        tcur = tcur + test_len
        if len(tr_set) < 8 or not te_set:
            continue
        best, bc = None, -1e9
        for p in grid:
            pk = (p["ema_period"], p["chandelier_atr_mult"], p["max_hold_days"])
            m = basket_metrics(trades_for(pk, tr_set))
            if m["n"] >= MIN_TRAIN_TRADES and m["calmar"] > bc:
                bc, best = m["calmar"], pk
        if best is None:
            continue
        fm = basket_metrics(trades_for(best, te_set))
        chosen.append(best)
        folds.append({"test_from": str(te_lo.date()), "test_to": str(te_hi.date()),
                      "ema": best[0], "mult": best[1], "hold": best[2],
                      "train_calmar": round(bc, 4), "oos_n": fm["n"],
                      "oos_pnl": round(fm["pnl"], 2), "oos_calmar": round(fm["calmar"], 4)})
        print(f"  fold {te_lo.date()}->{te_hi.date()}  ema={best[0]} mult={best[1]} "
              f"hold={best[2]}   OOS {fm['n']:>3}t ${fm['pnl']:>9,.0f} "
              f"Calmar {fm['calmar']:>6.2f}", flush=True)

    counts = Counter(chosen)
    winner, wins = (counts.most_common(1)[0] if counts else (None, 0))

    # the whole-floor table, for context only - selection is the fold vote above
    pooled = []
    for p in grid:
        pk = (p["ema_period"], p["chandelier_atr_mult"], p["max_hold_days"])
        m = basket_metrics(trades_for(pk, None))
        pooled.append({"ema": pk[0], "mult": pk[1], "hold": pk[2],
                       "n": m["n"], "pnl": round(m["pnl"], 2),
                       "calmar": round(m["calmar"], 4), "sharpe": round(m["sharpe"], 4),
                       "pf": round(m["pf"], 4)})
    pooled.sort(key=lambda r: -r["calmar"])

    out = {"engine": "futures._validated_core.backtest_swing_tf",
           "labels": "RegimeLabels(lag_days=1) - causal D-1",
           "grid": GRID, "candidates_evaluated": len(grid),
           "region": "floor only; 2025 and 2026 never read",
           "folds": folds, "n_folds": len(folds),
           "selection_counts": {f"ema{k[0]}_mult{k[1]}_hold{k[2]}": v
                                for k, v in counts.items()},
           "winner": ({"ema_period": winner[0], "chandelier_atr_mult": winner[1],
                       "max_hold_days": winner[2]} if winner else None),
           "winner_fold_share": f"{wins}/{len(folds)}" if folds else "0/0",
           "winner_fold_fraction": round(wins / len(folds), 4) if folds else 0.0,
           "pooled_floor_table": pooled,
           "elapsed_seconds": round(time.perf_counter() - t0, 1)}
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")

    print(f"\n=== {len(grid)} candidates, {len(folds)} folds ===")
    print(f"  winner {out['winner']}  share {out['winner_fold_share']}")
    print(f"  counts {out['selection_counts']}")
    print("\n  top of the pooled floor table (context only, NOT the selection):")
    for r in pooled[:6]:
        print(f"    ema={r['ema']:>2} mult={r['mult']} hold={r['hold']:>2}  n={r['n']:>5} "
              f"pnl {r['pnl']:>11,.0f}  calmar {r['calmar']:>6.2f}  sharpe {r['sharpe']:>5.2f}")
    print("\nwrote", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
