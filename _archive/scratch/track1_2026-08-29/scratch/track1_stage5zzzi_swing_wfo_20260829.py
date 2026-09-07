"""Stage 5ZZZ-I — the pooled Swing WFO, re-run under causal D-1 regime labels.

The procedure is NOT invented here. It is `pooled_swing_wfo.py`, the script `futures/basket.py`
credits for the frozen parameters ("pooled WFO winner, 5/6 folds"), reproduced with its own
grid, its own fold geometry and its own objective:

    grid       ema_period in {10, 20, 30}  x  chandelier_atr_mult in {2.5, 3.0, 3.5}
    max_hold   5, fixed - it was never in the grid and is not added to it here
    objective  Calmar on the TRAIN fold, with a minimum of 10 basket trades
    folds      rolling 18 months train -> 6 months test, stepping 6 months
    pooling    one shared parameter per fold across the whole basket

Only one input changes: the labels object is wrapped in `RegimeLabels(lag_days=1)`.

FAITHFULNESS CHECK, run first and every time: the same code under SAME-DAY labels must return
the parameters the repo already froze - ema 30, mult 2.5. A tuning script that cannot reproduce
the tuning it claims to be redoing is not evidence about anything.

Selection touches the FLOOR region only. 2025 and 2026 are never read here.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import Counter
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import numpy as np
import pandas as pd

GRID = {"ema_period": [10, 20, 30], "chandelier_atr_mult": [2.5, 3.0, 3.5]}
MAX_HOLD = 5
TRAIN_MONTHS, TEST_MONTHS = 18, 6
MIN_TRAIN_TRADES = 10

#: The floor window's own arguments, from the promotion artifact's recorded argv.
FLOOR_DATA_DIR = "data/cache/futures/frozen_sim"
FLOOR_END = "2024-12-31"
FLOOR_HMM_FIT_END = "2022-12-31"
HMM_TRAIN_END = "2018-01-01"
REGIME_CSV = "spy_daily_live.csv"
SLIPPAGE = 2.0


def basket_metrics(trades_by_inst, day_filter=None) -> dict:
    """Verbatim from `pooled_swing_wfo.basket_metrics`; the objective must not drift."""
    rows = []
    for _inst, trs in trades_by_inst.items():
        for r in trs:
            d = pd.Timestamp(r["day"])
            if day_filter is None or d in day_filter:
                rows.append((d, r["pnl"]))
    if not rows:
        return dict(n=0, pnl=0.0, calmar=0.0, sharpe=0.0, pf=0.0, expect=0.0)
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
                pf=float(w / ll) if ll > 1e-9 else float("inf"),
                expect=float(df["pnl"].mean()))


def build(lagged: bool, cfg: dict):
    """Frames, costs and labels for one configuration."""
    from futures._validated_core import benchmark_daily, label_regimes
    from futures.basket import BASKET, data_filename
    from futures.swing_tf import costs_for_basket
    from global_index._core import load_parquet
    from global_index.regime import RegimeLabels

    dfs = {}
    for name, c in BASKET.items():
        df = load_parquet(str(Path(cfg["data_dir"]) / data_filename(c)))
        df = df[df.index <= pd.Timestamp(cfg["end"]).tz_localize(df.index.tz)]
        dfs[name] = df
    bench = benchmark_daily(REGIME_CSV)
    # The original clips the BENCHMARK at the vault boundary too, so the HMM never sees a day
    # the WFO region does not contain. Reproduced rather than assumed.
    bench = bench[bench.index < pd.Timestamp(cfg["end"]) + pd.Timedelta(days=1)]
    raw = label_regimes(bench, HMM_TRAIN_END, 3, cfg["hmm_fit_end"])
    if lagged:
        ser = pd.Series(raw)
        idx = pd.DatetimeIndex(ser.index)
        ser.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
        labels = RegimeLabels(ser.sort_index(), lag_days=1)
    else:
        labels = raw
    return dfs, labels, costs_for_basket(slippage_ticks=cfg["slippage"])


def run_wfo(lagged: bool, cfg: dict) -> dict:
    from futures.swing_tf_harness import backtest_swing_tf

    dfs, labels, costs = build(lagged, cfg)
    grid = [dict(zip(GRID, c)) for c in itertools.product(*GRID.values())]

    # every (instrument, parameter) once; the folds then only slice by day
    F: dict = {n: {} for n in dfs}
    for name, df in dfs.items():
        for p in grid:
            trs = backtest_swing_tf(df, labels, costs[name],
                                    ema_period=p["ema_period"],
                                    chandelier_atr_mult=p["chandelier_atr_mult"],
                                    max_hold_days=MAX_HOLD)
            F[name][(p["ema_period"], p["chandelier_atr_mult"])] = trs
        print(f"    {name}: {sum(len(v) for v in F[name].values())} trades over {len(grid)} params",
              flush=True)

    def trades_for(pk, day_set):
        return {n: [r for r in F[n][pk] if pd.Timestamp(r["day"]) in day_set] for n in F}

    all_days = sorted({pd.Timestamp(r["day"]) for n in F for p in F[n] for r in F[n][p]})
    assert all_days, "no trades at all; the fold loop below would silently do nothing"
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
            pk = (p["ema_period"], p["chandelier_atr_mult"])
            m = basket_metrics(trades_for(pk, tr_set))
            if m["n"] >= MIN_TRAIN_TRADES and m["calmar"] > bc:
                bc, best = m["calmar"], pk
        if best is None:
            continue
        fm = basket_metrics(trades_for(best, te_set))
        chosen.append(best)
        folds.append({"test_from": str(te_lo.date()), "test_to": str(te_hi.date()),
                      "ema": best[0], "mult": best[1], "train_calmar": round(bc, 4),
                      "oos_n": fm["n"], "oos_pnl": round(fm["pnl"], 2),
                      "oos_calmar": round(fm["calmar"], 4)})

    counts = Counter(chosen)
    winner, wins = (counts.most_common(1)[0] if counts else (None, 0))
    return {"lagged": lagged, "config": cfg, "folds": folds, "n_folds": len(folds),
            "selection_counts": {f"ema{k[0]}_mult{k[1]}": v for k, v in counts.items()},
            "winner": {"ema_period": winner[0], "chandelier_atr_mult": winner[1]} if winner else None,
            "winner_fold_share": f"{wins}/{len(folds)}" if folds else "0/0"}


#: The configuration the ORIGINAL tuning ran under, from `pooled_swing_wfo.py`'s own defaults.
#: Reproducing the frozen parameters requires all three of these, and getting any one wrong is
#: how a "retune" ends up comparing against a tuning that never happened.
ORIGINAL = {"data_dir": "data/cache/futures/frozen_sim", "end": "2022-12-31",
            "hmm_fit_end": "2024-12-31", "slippage": 1.0, "label": "original tuning config"}

#: Track 1's own floor window: its recorded argv, two ticks a side, its own HMM fit end.
TRACK1 = {"data_dir": FLOOR_DATA_DIR, "end": FLOOR_END,
          "hmm_fit_end": FLOOR_HMM_FIT_END, "slippage": SLIPPAGE,
          "label": "Track 1 floor config"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("verify", "retune", "both"), default="both")
    a = ap.parse_args()

    dest = Path("scratch/track1_stage5zzzi_swing_wfo_20260829.json")
    out = json.loads(dest.read_text(encoding="utf-8")) if dest.exists() else {}

    if a.stage in ("verify", "both"):
        print("\n" + "=" * 88, flush=True)
        print("FAITHFULNESS CHECK - the ORIGINAL tuning config, same-day labels", flush=True)
        print("must return the repo's frozen ema=30 / mult=2.5", flush=True)
        print("=" * 88, flush=True)
        r = run_wfo(lagged=False, cfg=ORIGINAL)
        exp = {"ema_period": 30, "chandelier_atr_mult": 2.5}
        r["reproduces_frozen_param"] = (r["winner"] == exp)
        out["verify_original_sameday"] = r
        print(f"  folds={r['n_folds']}  winner={r['winner']}  share={r['winner_fold_share']}")
        print(f"  counts={r['selection_counts']}")
        print(f"  REPRODUCES ema30/mult2.5: {r['reproduces_frozen_param']}")
        for f in r["folds"]:
            print(f"    {f['test_from']}->{f['test_to']}  ema={f['ema']},mult={f['mult']}  "
                  f"OOS {f['oos_n']:>3}t  ${f['oos_pnl']:>9,.0f}  Calmar {f['oos_calmar']:>6.2f}")

    if a.stage in ("retune", "both"):
        for lag, tag in ((False, "track1_sameday"), (True, "track1_d1")):
            print("\n" + "=" * 88, flush=True)
            print(f"{'SAME-DAY (control)' if not lag else 'CAUSAL D-1 (retune)'}"
                  f" - Track 1 floor config, selection on the floor region only", flush=True)
            print("=" * 88, flush=True)
            r = run_wfo(lagged=lag, cfg=TRACK1)
            out[tag] = r
            print(f"  folds={r['n_folds']}  winner={r['winner']}  share={r['winner_fold_share']}")
            print(f"  counts={r['selection_counts']}")
            for f in r["folds"]:
                print(f"    {f['test_from']}->{f['test_to']}  ema={f['ema']},mult={f['mult']}  "
                      f"OOS {f['oos_n']:>3}t  ${f['oos_pnl']:>9,.0f}  "
                      f"Calmar {f['oos_calmar']:>6.2f}")

    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\nwrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
