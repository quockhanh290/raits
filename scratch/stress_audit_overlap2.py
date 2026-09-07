"""AUDIT-ONLY, strict version. A swing trade entered on day D is opened in the
14:00-15:55 window, i.e. AFTER the 10:20 stress entry and at/after the stress 14:00
exit. So only swing positions entered STRICTLY BEFORE the stress day can actually be
sitting in the account at 10:20. Recount under that rule."""
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
    sw = [dict(inst=i, d0=pd.Timestamp(t["day"]).normalize(), d1=pd.Timestamp(t["exit_day"]).normalize(),
               dir=t["direction"]) for i, lst in swing.items() for t in lst]
    for variant in ("breadth3", "wide_range3"):
        stress = StressLiquidation1020Engine(variant=variant,
                                             instruments={"MNQ", "MES"}).backtest_basket(dfs, labels, costs)
        st = [dict(inst=i, day=pd.Timestamp(t["day"]).normalize(), dir=t["direction"], pnl=t["pnl"])
              for i, lst in stress.items() for t in lst]
        assert st and sw, "SC FAIL: empty side"
        held = opp = 0; opp_pnl = 0.0
        for s in st:
            m = [w for w in sw if w["inst"] == s["inst"] and w["d0"] < s["day"] <= w["d1"]]
            if m:
                held += 1
                if any(w["dir"] != s["dir"] for w in m):
                    opp += 1; opp_pnl += s["pnl"]
        tot = sum(t["pnl"] for t in st)
        print(f"{which}/{variant}: stress={len(st)} net=${tot:,.0f} | "
              f"swing ALREADY OPEN same symbol at 10:20: {held}/{len(st)} "
              f"({held/len(st):.0%}) | OPPOSITE dir: {opp}/{len(st)} ({opp/len(st):.0%}) "
              f"carrying ${opp_pnl:,.0f} ({opp_pnl/tot*100 if tot else 0:.0f}% of net)")
