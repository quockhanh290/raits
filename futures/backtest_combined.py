"""
futures/backtest_combined.py — the DEPLOYED portfolio: swing TF + STRESS_MID
============================================================================
Runs BOTH engines on the rổ-4 basket and pools their P&L into one combined
equity curve — the actual thing that gets deployed. Until now each engine was
validated alone; this shows them together: swing TF (steady, Normal+Stress
year-round) + STRESS_MID (sleeve, Stress only, hibernates calm years).

Reports combined Calmar/PF/MaxDD, per-engine contribution, and per-year (to see
STRESS_MID kick in during stress years like 2022 and sleep in 2023-24).

CAVEAT: pools both engines' trade P&L by day. It does NOT yet simulate
net_exposure rejections or the circuit breaker (those are live-entry guards that
only REDUCE risk; modeling them needs intraday entry-order simulation). So this
is a slight upper bound on risk-adjusted return — conservative direction for the
edge question, but real deployment will occasionally skip a correlated entry.

    python -m futures.backtest_combined --data-dir data\\cache\\futures \\
        --regime-csv spy_daily.csv [--start 2017-01-01] [--end 2024-12-31]
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
import numpy as np
import pandas as pd


def metrics(daily: pd.Series) -> dict:
    if daily.empty:
        return dict(n=0, pnl=0, pf=0, calmar=0, sharpe=0, maxdd=0)
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    ann = daily.sum() / span
    w = daily[daily > 0].sum(); l = -daily[daily < 0].sum()
    return dict(n=int((daily != 0).sum()), pnl=float(daily.sum()),
                pf=float(w/l) if l > 1e-9 else float("inf"),
                calmar=float(ann/dd) if dd > 1e-9 else float("inf"),
                sharpe=float(daily.mean()/daily.std()*np.sqrt(252)) if daily.std() > 1e-9 else 0.0,
                maxdd=dd)


def _daily(trades_by_inst):
    rows = []
    for trs in trades_by_inst.values():
        for r in trs:
            rows.append((pd.Timestamp(r["day"]), r["pnl"]))
    if not rows:
        return pd.Series(dtype=float)
    return pd.DataFrame(rows, columns=["day", "pnl"]).groupby("day")["pnl"].sum().sort_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--slippage-ticks", type=float, default=1.0)
    a = ap.parse_args()

    from futures._validated_core import load_parquet, benchmark_daily, label_regimes
    from futures.basket import BASKET, data_filename
    from futures.swing_tf import SwingTFEngine, costs_for_basket
    from futures.stress_mid import StressMidEngine

    # load basket (optionally clipped to [start, end])
    dfs = {}
    for name, c in BASKET.items():
        df = load_parquet(str(Path(a.data_dir) / data_filename(c)))
        if a.start:
            df = df[df.index >= pd.Timestamp(a.start).tz_localize(df.index.tz)]
        if a.end:
            df = df[df.index <= pd.Timestamp(a.end).tz_localize(df.index.tz)]
        dfs[name] = df
    daily_bench = benchmark_daily(a.regime_csv)
    if a.start:
        daily_bench = daily_bench[daily_bench.index >= pd.Timestamp(a.start)]
    if a.end:
        daily_bench = daily_bench[daily_bench.index <= pd.Timestamp(a.end)]
    labels = label_regimes(daily_bench, a.hmm_train_end, 3, "2022-12-31")
    costs = costs_for_basket(slippage_ticks=a.slippage_ticks)

    tf = SwingTFEngine().backtest_basket(dfs, labels, costs)
    sm = StressMidEngine().backtest_basket(dfs, labels, costs)

    tf_daily, sm_daily = _daily(tf), _daily(sm)
    combined = tf_daily.add(sm_daily, fill_value=0).sort_index()

    print(f"\n{'='*68}\nCOMBINED PORTFOLIO | swing TF + STRESS_MID | rổ 4 | 1 micro each\n{'='*68}")
    span = "all data" if not (a.start or a.end) else f"{a.start or 'start'} → {a.end or 'end'}"
    print(f"Span: {span}\n")

    for label, d in (("swing TF", tf_daily), ("STRESS_MID", sm_daily), ("COMBINED", combined)):
        m = metrics(d)
        print(f"  {label:<11} net ${m['pnl']:>9,.0f} | PF {m['pf']:>4.2f} | "
              f"MaxDD ${m['maxdd']:>7,.0f} | Calmar {m['calmar']:>5.2f} | Sharpe {m['sharpe']:>5.2f}")

    print("\nPer-engine contribution by year (STRESS_MID sleeps in calm years):")
    yrs = sorted(set(combined.index.year))
    print(f"  {'year':<6}{'swing TF':>12}{'STRESS_MID':>13}{'combined':>12}")
    for y in yrs:
        t = tf_daily[tf_daily.index.year == y].sum() if len(tf_daily) else 0
        s = sm_daily[sm_daily.index.year == y].sum() if len(sm_daily) else 0
        print(f"  {y:<6}{t:>12,.0f}{s:>13,.0f}{t+s:>12,.0f}")

    # diversification check: does combined Calmar beat swing-TF-alone?
    cm, tm = metrics(combined), metrics(tf_daily)
    print("\n" + "-"*68)
    verdict = ("STRESS_MID IMPROVES the portfolio (combined Calmar > swing-TF alone)"
               if cm["calmar"] > tm["calmar"] else
               "STRESS_MID does not raise risk-adjusted return (combined Calmar ≤ swing alone) "
               "— it is a hedge/diversifier, value shows mainly in stress years")
    print(f"Combined Calmar {cm['calmar']:.2f} vs swing-TF-alone {tm['calmar']:.2f} → {verdict}")
    print("-"*68 + "\n")


if __name__ == "__main__":
    main()
