"""AUDIT-ONLY: the reports are produced by scratch/stress_sleeve_validation.build_variant,
but deploy_sim runs futures/stress_liquidation_1020.StressLiquidation1020Engine. Two
parallel implementations of one rule with no reconciliation = the shape that has cost
this project money before. Reconcile them trade-for-trade.

Known textual difference: validation context() uses first_at_or_after(10:20) (falls
through to a later bar), the engine uses between_time('10:20','10:20') (exact bar or no
trade). Measure whether that ever fires."""
from __future__ import annotations
import sys
from pathlib import Path
if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))
import pandas as pd
from futures._validated_core import benchmark_daily, daily_atr_series, label_regimes, load_parquet
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket
from futures.stress_liquidation_1020 import StressLiquidation1020Engine
from scratch.harness import ARGV
from scratch.stress_sleeve_validation import Variant, build_variant, clip, arg_from

for which in ("floor", "vault2025"):
    argv = list(ARGV[which])
    dfs = {n: clip(load_parquet(str(Path(arg_from(argv, "--data-dir")) / data_filename(c))),
                   arg_from(argv, "--start"), arg_from(argv, "--end")) for n, c in BASKET.items()}
    atrs = {n: daily_atr_series(d) for n, d in dfs.items()}
    costs = costs_for_basket(slippage_ticks=2.0)
    labels = label_regimes(benchmark_daily("spy_daily_live.csv"), "2018-01-01", 3,
                           arg_from(argv, "--hmm-fit-end", "2024-12-31"))
    for vname, bvar in (("breadth3", "breadth3_mnq_mes"), ("wide_range3", "wide3_mnq_mes")):
        rep, _ = build_variant(dfs, labels, costs, atrs, Variant(bvar, breadth=vname))
        eng = StressLiquidation1020Engine(variant=vname, instruments={"MNQ", "MES"}).backtest_basket(dfs, labels, costs)
        et = [dict(inst=i, day=pd.Timestamp(t["day"]), pnl=t["pnl"], entry=t["entry"], exit=t["exit"])
              for i, lst in eng.items() for t in lst]
        assert not rep.empty and et, f"SC FAIL: one side empty for {which}/{vname}"
        e = pd.DataFrame(et)
        rk = {(pd.Timestamp(d).normalize(), i): round(float(p), 2)
              for d, i, p in zip(rep.day, rep.inst, rep.pnl)}
        ek = {(pd.Timestamp(d).normalize(), i): round(float(p), 2)
              for d, i, p in zip(e.day, e.inst, e.pnl)}
        only_rep = set(rk) - set(ek); only_eng = set(ek) - set(rk)
        diff = {k: (rk[k], ek[k]) for k in set(rk) & set(ek) if abs(rk[k] - ek[k]) > 0.01}
        print(f"\n{which}/{vname}:")
        print(f"  report harness : n={len(rk)} net=${sum(rk.values()):,.0f}")
        print(f"  deploy engine  : n={len(ek)} net=${sum(ek.values()):,.0f}")
        print(f"  only-in-report={len(only_rep)}  only-in-engine={len(only_eng)}  pnl_mismatches={len(diff)}")
        for k in list(only_rep)[:5]:
            print(f"    only report: {k[0].date()} {k[1]} pnl={rk[k]}")
        for k, (a, b) in list(diff.items())[:5]:
            print(f"    mismatch: {k[0].date()} {k[1]} report={a} engine={b}")

        if vname == "breadth3":
            d = sorted({pd.Timestamp(x).normalize() for x in rep.day})
            print(f"  trade dates n={len(d)} first={d[0].date()} last={d[-1].date()}")
            runs = []
            cur = [d[0]]
            for a, b in zip(d, d[1:]):
                (cur.append(b) if (b - a).days <= 5 else (runs.append(cur), cur := [b]))
            runs.append(cur)
            for r in sorted(runs, key=len, reverse=True)[:6]:
                sub = rep[pd.DatetimeIndex(rep.day).normalize().isin(pd.DatetimeIndex(r))]
                print(f"    episode {r[0].date()}..{r[-1].date()} days={len(r)} "
                      f"trades={len(sub)} net=${sub.pnl.sum():,.0f}")
