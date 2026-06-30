"""
global_index/hold_vs_entry_diagnostic.py — why is MES "open during" most rejects?
================================================================================
reject_diagnostic showed MES open during 488 rejects (most). Two explanations:
  ENTRY-RACE: MES enters earlier within the shared 14:00-15:55 power hour, grabs
              budget first → others rejected the same day.
  HOLD-TIME:  MES sits in multi-day swing holds longer, so it is simply "open"
              across more days → any new entry on those days sees it. Then the
              reject is correct concentration-trim (adding a 0.9-corr leg while
              MES is mid-trend), not an unfair race.

This classifies, at each reject, whether the same-cluster open positions are
FRESH (entered today) or HOLDING (entered on an earlier day), and reports
hold-time per instrument. If rejects mostly coincide with HOLDING positions →
hold-time story → benign. If FRESH dominates → same-day race → more arbitrary.

    python -m global_index.hold_vs_entry_diagnostic --data-dir data\\cache\\futures \
        --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet --regime-csv spy_daily.csv
"""
from __future__ import annotations
import argparse, sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index import specs as gi_specs
from global_index.regime import RegimeLabels
from global_index.net_exposure_multi import MultiClusterGuard, ClusterBudget, Position


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
    ap.add_argument("--hmm-fit-end", default="2022-12-31")
    a = ap.parse_args()

    from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                         backtest_swing_tf, daily_atr_series)
    from futures.basket import BASKET, data_filename
    from futures.swing_tf import SwingTFEngine, costs_for_basket

    dfs = {n: load_parquet(str(Path(a.data_dir) / data_filename(c))) for n, c in BASKET.items()}
    atr = {n: daily_atr_series(df) for n, df in dfs.items()}
    pv = {n: c.point_value for n, c in BASKET.items()}
    bench = benchmark_daily(a.regime_csv)
    labels = label_regimes(bench, a.hmm_train_end, 3, a.hmm_fit_end)
    costs = costs_for_basket(slippage_ticks=a.slippage_ticks)
    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)

    # check whether trades carry an intraday entry timestamp (for the entry-race test)
    sample = next(iter(swing.values()))[0] if any(swing.values()) else {}
    time_key = next((k for k in ("entry_time", "entry_ts", "entry") if k in sample
                     and not isinstance(sample.get(k), (int, float))), None)

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

    # hold time per instrument
    hold = {}
    for inst, lst in swing.items():
        hd = [(pd.Timestamp(t["exit_day"]) - pd.Timestamp(t["day"])).days for t in lst]
        hold[inst] = np.median(hd) if hd else 0
    nhd = [(pd.Timestamp(t["exit_day"]) - pd.Timestamp(t["day"])).days for t in nkd if t.get("exit_day")]
    hold[a.nkd_instrument] = np.median(nhd) if nhd else 0

    tr = []
    for inst, lst in swing.items():
        for t in lst:
            ed = pd.Timestamp(t["day"])
            tr.append(dict(inst=inst, cluster="roska4_swing", entry=ed, exit=pd.Timestamp(t["exit_day"]),
                           direction=t["direction"], risk=rrisk(atr[inst], a.roska4_mult, pv[inst], ed)))
    for t in nkd:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = (pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed)
        tr.append(dict(inst=a.nkd_instrument, cluster="global_nkd", entry=ed, exit=xd,
                       direction=t["direction"], risk=rrisk(natr, a.nkd_mult, c.point_value, ed)))

    cl = {"roska4_swing": ClusterBudget("roska4_swing", a.gross_cap, a.gross_cap*0.875),
          "global_nkd": ClusterBudget("global_nkd", 0.02, 0.02)}
    guard = MultiClusterGuard(clusters=cl, account=a.account)

    days = sorted({t["entry"] for t in tr} | {t["exit"] for t in tr})
    by_entry = {}
    for t in tr:
        by_entry.setdefault(t["entry"], []).append(t)

    open_pos = []
    fresh_count = 0          # rejects where a same-day (fresh) position held budget
    holding_count = 0        # rejects where a prior-day (holding) position held budget
    rej_total = 0
    for day in days:
        open_pos = [(p, t) for p, t in open_pos if t["exit"] != day]
        for t in by_entry.get(day, []):
            if t["cluster"] not in guard.clusters:
                continue
            pos = Position(t["inst"], t["direction"], 1, t["risk"], t["cluster"])
            same = [(p, tt) for p, tt in open_pos if p.cluster == t["cluster"]]
            ok, _ = guard.admits(pos, [p for p, _ in open_pos])
            if ok:
                if t["exit"] != day:
                    open_pos.append((pos, t))
            else:
                rej_total += 1
                # were the budget-holders fresh-today or holding-from-before?
                any_holding = any(tt["entry"] < day for _, tt in same)
                any_fresh = any(tt["entry"] == day for _, tt in same)
                if any_holding:
                    holding_count += 1
                elif any_fresh:
                    fresh_count += 1

    print(f"\n{'='*60}\nHOLD-TIME vs ENTRY-RACE @ cap {a.gross_cap:.0%} | slippage {a.slippage_ticks:g}t")
    print(f"{'='*60}")
    print("median hold-days per instrument (swing):")
    for inst in ["MES", "MNQ", "MYM", "M2K", a.nkd_instrument]:
        if inst in hold:
            print(f"  {inst:<6} {hold[inst]:.0f} days")
    print(f"\nintraday entry timestamp available? {'yes' if time_key else 'no (cannot test entry-race directly)'}")
    print(f"\nof {rej_total} Rổ-4 rejects:")
    if rej_total:
        print(f"  {holding_count} ({holding_count/rej_total:.0%}) occurred while a HOLDING (prior-day) "
              f"position held budget")
        print(f"  {fresh_count} ({fresh_count/rej_total:.0%}) occurred with only FRESH (same-day) "
              f"positions holding budget")
    print("-"*60)
    print("read: HOLDING-dominant → MES etc. sit in multi-day trends; the reject is")
    print("  correct concentration-trim (adding a 0.9-corr leg mid-trend), NOT a race.")
    print("  FRESH-dominant → same-day ordering decides → more arbitrary.\n")


if __name__ == "__main__":
    main()
