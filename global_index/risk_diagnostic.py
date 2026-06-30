"""
global_index/risk_diagnostic.py — what is the REAL risk$ per position?
======================================================================
deploy_sim revealed exposure caps reject ~64% of Rổ-4 entries under REAL risk$
(vs ~11% under the $500 stub). Either real risk$ >> $500 (so the 3.5%/4% caps,
calibrated for the stub, are now far too tight), or risk is mis-computed. This
prints the real per-position risk$ per instrument so we can see the truth and
re-calibrate caps (or the sizer) on real numbers.

risk$ per micro = chandelier_mult × daily_ATR × point_value  (initial stop $).

    python -m global_index.risk_diagnostic --data-dir data\\cache\\futures \
        --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet --regime-csv spy_daily.csv
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from global_index._core import load_parquet as gi_load
    from global_index import specs as gi_specs
    from global_index.regime import RegimeLabels
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from global_index._core import load_parquet as gi_load
    from global_index import specs as gi_specs
    from global_index.regime import RegimeLabels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--nkd-parquet", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--nkd-instrument", default="MNKD", choices=list(gi_specs.SPECS.keys()))
    ap.add_argument("--nkd-ema", type=int, default=10)
    ap.add_argument("--nkd-mult", type=float, default=2.5)
    ap.add_argument("--roska4-mult", type=float, default=2.5)
    ap.add_argument("--account", type=float, default=50_000.0)
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end", default="2022-12-31")
    a = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                         backtest_swing_tf, daily_atr_series)
    from futures.basket import BASKET, data_filename
    from futures.swing_tf import SwingTFEngine, costs_for_basket

    dfs = {n: load_parquet(str(Path(a.data_dir) / data_filename(c))) for n, c in BASKET.items()}
    bench = benchmark_daily(a.regime_csv)
    labels = label_regimes(bench, a.hmm_train_end, 3, a.hmm_fit_end)
    costs = costs_for_basket()
    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)

    # NKD
    c = gi_specs.SPECS[a.nkd_instrument]
    spy = pd.Series(label_regimes(benchmark_daily(a.regime_csv), a.hmm_train_end, 3, a.hmm_fit_end))
    idx = pd.DatetimeIndex(spy.index); spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nlab = RegimeLabels(spy.sort_index(), lag_days=1)
    ndf = gi_load(a.nkd_parquet); ndf.index = ndf.index.tz_convert(c.session_tz)
    nkd = backtest_swing_tf(ndf, nlab, GIFC_or_cost(c), ema_period=a.nkd_ema,
                            chandelier_atr_mult=a.nkd_mult, max_hold_days=5, gap_fill=True)

    def risk_series(df, trades, mult, pv, tz_naive=False):
        atr = daily_atr_series(df)
        out = []
        for t in trades:
            ed = pd.Timestamp(t["day"])
            if tz_naive and ed.tzinfo is not None:
                ed = ed.tz_localize(None)
            try:
                av = atr.asof(ed)
            except Exception:
                av = np.nan
            if av is None or pd.isna(av):
                continue
            out.append(mult * float(av) * pv)
        return np.array(out)

    print(f"\n{'='*72}\nREAL RISK$ PER MICRO POSITION (chandelier stop × pv) | account ${a.account:,.0f}")
    print(f"{'='*72}")
    print(f"{'instrument':<12}{'n':>6}{'median$':>10}{'mean$':>10}{'p90$':>9}  vs $500 stub")
    print("-"*72)

    cluster_med = {"roska4_swing": [], "global_nkd": []}
    for n, df in dfs.items():
        r = risk_series(df, swing[n], a.roska4_mult, BASKET[n].point_value)
        if len(r) == 0:
            continue
        med = np.median(r)
        cluster_med["roska4_swing"].append((n, med))
        flag = "≈stub" if 400 <= med <= 600 else ("»stub" if med > 600 else "«stub")
        print(f"{n:<12}{len(r):>6}{med:>10,.0f}{r.mean():>10,.0f}{np.percentile(r,90):>9,.0f}  {flag}")

    rn = risk_series(ndf, nkd, a.nkd_mult, c.point_value, tz_naive=True)
    if len(rn):
        med = np.median(rn); cluster_med["global_nkd"].append((a.nkd_instrument, med))
        print(f"{a.nkd_instrument:<12}{len(rn):>6}{med:>10,.0f}{rn.mean():>10,.0f}{np.percentile(rn,90):>9,.0f}  "
              f"{'«stub' if med<400 else '≈stub' if med<=600 else '»stub'}")

    print("\n" + "-"*72)
    print("CAP IMPLICATIONS (real risk$ vs current caps):")
    swing_med_sum = sum(m for _, m in cluster_med["roska4_swing"])
    print(f"  Rổ-4 swing: if all 4 long at 1 micro, gross ≈ ${swing_med_sum:,.0f} "
          f"= {swing_med_sum/a.account:.1%}  (cap gross 4.0% = ${a.account*0.04:,.0f})")
    n_fit = int(a.account*0.04 / (swing_med_sum/max(1,len(cluster_med['roska4_swing'])))) if cluster_med['roska4_swing'] else 0
    print(f"    → cap 4% admits ~{n_fit} of 4 index at 1 micro "
          f"({'TIGHT — bottleneck' if n_fit < 4 else 'ok'})")
    if cluster_med["global_nkd"]:
        nm = cluster_med["global_nkd"][0][1]
        print(f"  NKD: 1 micro risk ${nm:,.0f} = {nm/a.account:.1%}  (cap 2.0% = ${a.account*0.02:,.0f})")
    print("\nread: if Rổ-4 medians »$500 and 4-long gross »4%, the caps were calibrated for")
    print("  the $500 stub and choke real-risk trading. Re-calibrate caps to real risk$,")
    print("  OR cap by NUMBER of positions (risk-normalized) instead of $ absolute.\n")


def GIFC_or_cost(c):
    from global_index._core import FuturesCost
    return FuturesCost(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
                       slippage_ticks_per_side=1.0)


if __name__ == "__main__":
    main()
