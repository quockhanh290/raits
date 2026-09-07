"""AUDIT-ONLY verification of the 2026-08-21 response pass, on an INDEPENDENT path:
my own lag1 (previous available label, not shift) and StressLiquidation1020Engine directly
rather than build_variant. Checking a pipeline with itself proves nothing."""
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


def lag1(labels):
    s = pd.Series(labels).sort_index()
    s.index = pd.DatetimeIndex(s.index).normalize()
    return {d: s[s.index < d].iloc[-1] for d in s.index if len(s[s.index < d])}


for which in ("vault2026", "floor"):
    argv = list(ARGV[which])
    start, end = arg_from(argv, "--start"), arg_from(argv, "--end")
    dfs = {n: clip(load_parquet(str(Path(arg_from(argv, "--data-dir")) / data_filename(c))), start, end)
           for n, c in BASKET.items()}
    costs = costs_for_basket(slippage_ticks=2.0)
    l0 = label_regimes(benchmark_daily("spy_daily_live.csv"), "2018-01-01", 3,
                       arg_from(argv, "--hmm-fit-end", "2024-12-31"))
    l1 = lag1(l0)
    win = pd.DatetimeIndex(sorted({pd.Timestamp(x).tz_localize(None).normalize()
                                   for x in dfs["MES"].index.normalize().unique()}))
    s0 = [d for d, v in l0.items() if v == "Stress" and d in win]
    s1 = [d for d, v in l1.items() if v == "Stress" and d in win]
    print(f"\n=== {which} ({win.min().date()}..{win.max().date()}, {len(win)} sessions) ===")
    print(f"  Stress days IN WINDOW: lag0={len(s0)}  lag1={len(s1)}  "
          f"only_lag1={len(set(s1)-set(s0))}  only_lag0={len(set(s0)-set(s1))}")
    for lab, name in ((l0, "lag0"), (l1, "lag1")):
        out = StressLiquidation1020Engine(variant="breadth3", instruments={"MNQ", "MES"}).backtest_basket(dfs, lab, costs)
        tr = [(t["day"], i, t["pnl"], t["exit_reason"]) for i, lst in out.items() for t in lst]
        net = sum(t[2] for t in tr)
        print(f"  {name}: trades={len(tr)} net=${net:,.0f}")
        if len(tr) <= 6:
            for t in sorted(tr):
                print(f"      {t[0]} {t[1]} pnl=${t[2]:,.0f} exit={t[3]}")
        if which == "vault2026" and name == "lag1" and tr:
            d = pd.Timestamp(tr[0][0]).normalize()
            print(f"      -> that day's lag0 label={l0.get(d)}  lag1 label={l1.get(d)}"
                  f"  prev-session lag0 label={l0.get(max([x for x in sorted(l0) if x < d]))}")

    if which != "floor":
        continue
    # S2 restated as OPERATIONAL events: how many DAYS would raise a broker conflict?
    sw = [dict(inst=i, d0=pd.Timestamp(t["day"]).normalize(), d1=pd.Timestamp(t["exit_day"]).normalize(), dir=t["direction"])
          for i, lst in SwingTFEngine().backtest_basket(dfs, l0, costs).items() for t in lst]
    for variant in ("breadth3", "wide_range3"):
        out = StressLiquidation1020Engine(variant=variant, instruments={"MNQ", "MES"}).backtest_basket(dfs, l1, costs)
        tr = [dict(day=pd.Timestamp(t["day"]).normalize(), inst=i, pnl=t["pnl"], dir=t["direction"])
              for i, lst in out.items() for t in lst]
        assert tr, "SC FAIL: empty"
        opp = [s for s in tr if any(w["inst"] == s["inst"] and w["d0"] < s["day"] <= w["d1"]
                                    and w["dir"] != s["dir"] for w in sw)]
        gross = sum(abs(s["pnl"]) for s in opp)
        print(f"  S2 {variant}: legs={len(tr)} conflicted_legs={len(opp)} ({len(opp)/len(tr):.0%})"
              f"  distinct CONFLICT DAYS={len({s['day'] for s in opp})}"
              f"  net_on_conflicted=${sum(s['pnl'] for s in opp):,.0f}"
              f"  GROSS_on_conflicted=${gross:,.0f}")
