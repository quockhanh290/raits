"""AUDIT-ONLY: how often does the Ro 4 swing sleeve hold a position in MNQ/MES on a day
the Stress 10:20 sleeve opens the opposite direction in the SAME symbol?

MultiClusterGuard.admits() checks only the proposed entry's own cluster, so nothing in
the current risk layer can see this. IBKR holds one net position per symbol.
"""
from __future__ import annotations
import sys
from pathlib import Path
if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))
import pandas as pd
from futures._validated_core import benchmark_daily, label_regimes, load_parquet
from futures.basket import BASKET, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from futures.stress_liquidation_1020 import StressLiquidation1020Engine
from scratch.harness import ARGV
from scratch.stress_sleeve_validation import clip, arg_from

for which in ("floor", "vault2025"):
    argv = list(ARGV[which])
    dfs = {n: clip(load_parquet(str(Path(arg_from(argv, "--data-dir")) / data_filename(c))),
                   arg_from(argv, "--start"), arg_from(argv, "--end")) for n, c in BASKET.items()}
    labels = label_regimes(benchmark_daily("spy_daily_live.csv"), "2018-01-01", 3,
                           arg_from(argv, "--hmm-fit-end", "2024-12-31"))
    costs = costs_for_basket(slippage_ticks=2.0)
    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)
    for variant in ("breadth3", "wide_range3"):
        stress = StressLiquidation1020Engine(variant=variant,
                                             instruments={"MNQ", "MES"}).backtest_basket(dfs, labels, costs)
        st = [dict(inst=i, day=pd.Timestamp(t["day"]), dir=t["direction"], pnl=t["pnl"])
              for i, lst in stress.items() for t in lst]
        sw = [dict(inst=i, d0=pd.Timestamp(t["day"]), d1=pd.Timestamp(t["exit_day"]), dir=t["direction"])
              for i, lst in swing.items() for t in lst]
        assert st, f"SC FAIL: no stress trades for {which}/{variant}"
        assert sw, f"SC FAIL: no swing trades for {which}"
        same = opp = 0; opp_pnl = 0.0; opp_rows = []
        for s in st:
            for w in sw:
                if w["inst"] != s["inst"]:
                    continue
                if w["d0"] <= s["day"] <= w["d1"]:
                    same += 1
                    if w["dir"] != s["dir"]:
                        opp += 1; opp_pnl += s["pnl"]
                        opp_rows.append((s["day"].date(), s["inst"], w["dir"], s["dir"], round(s["pnl"], 0)))
                    break
        tot = sum(t["pnl"] for t in st)
        print(f"\n{which}/{variant}: stress_trades={len(st)} net=${tot:,.0f} | swing_trades={len(sw)}")
        print(f"  stress entries on a day swing already holds SAME symbol : {same}/{len(st)}")
        print(f"  of those, swing direction OPPOSITE to stress            : {opp}")
        print(f"  stress PnL riding on those conflicted legs              : ${opp_pnl:,.0f}"
              f"  ({opp_pnl/tot*100 if tot else 0:.0f}% of sleeve net)")
        for r in opp_rows[:12]:
            print(f"    {r[0]} {r[1]}: swing={r[2]} vs stress={r[3]}  stress_pnl=${r[4]:,.0f}")
