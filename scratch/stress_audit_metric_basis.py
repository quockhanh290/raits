"""AUDIT-ONLY: the sleeve's Sharpe/Calmar are computed on a series of TRADE DAYS ONLY
(deploy_sim.metrics -> daily.mean()/daily.std()*sqrt(252)). The sleeve trades ~10 days a
year, so sqrt(252) annualises a mean drawn from ~10 observations. Recompute on the
calendar basis the system-level numbers use, and report both."""
from __future__ import annotations
import sys
from pathlib import Path
if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))
import numpy as np, pandas as pd
from futures._validated_core import benchmark_daily, daily_atr_series, label_regimes, load_parquet
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket
from global_index.deploy_sim import metrics
from scratch.harness import ARGV
from scratch.stress_sleeve_validation import Variant, build_variant, clip, arg_from, daily_from_trades

for which in ("floor", "vault2025"):
    argv = list(ARGV[which])
    dfs = {n: clip(load_parquet(str(Path(arg_from(argv, "--data-dir")) / data_filename(c))),
                   arg_from(argv, "--start"), arg_from(argv, "--end")) for n, c in BASKET.items()}
    atrs = {n: daily_atr_series(d) for n, d in dfs.items()}
    labels = label_regimes(benchmark_daily("spy_daily_live.csv"), "2018-01-01", 3,
                           arg_from(argv, "--hmm-fit-end", "2024-12-31"))
    tr, _ = build_variant(dfs, labels, costs_for_basket(slippage_ticks=2.0), atrs,
                          Variant("breadth3_mnq_mes"))
    assert not tr.empty, f"SC FAIL: no trades for {which}"
    sparse = daily_from_trades(tr)
    # calendar basis: every session MES traded in the window, 0 on non-trade days
    sessions = pd.DatetimeIndex(sorted({pd.Timestamp(d).tz_localize(None).normalize()
                                        for d in dfs["MES"].index.normalize().unique()}))
    sessions = sessions[(sessions >= sparse.index.min()) & (sessions <= sparse.index.max())]
    dense = pd.Series(0.0, index=sessions)
    dense.loc[sparse.index] = sparse.values
    assert len(dense) > len(sparse), "SC FAIL: dense series not denser than sparse"
    ms, md = metrics(sparse), metrics(dense)
    print(f"\n{which}: trades={len(tr)}  trade-days={len(sparse)}  calendar sessions={len(dense)}"
          f"  ({len(sparse)/len(dense):.1%} of days active)")
    print(f"  AS REPORTED (trade-days only) : sharpe={ms['sharpe']:>7.2f}  calmar={ms['calmar']:>7.2f}  maxdd=${ms['maxdd']:,.0f}")
    print(f"  CALENDAR basis (system frame) : sharpe={md['sharpe']:>7.2f}  calmar={md['calmar']:>7.2f}  maxdd=${md['maxdd']:,.0f}")
    print(f"  overstatement factor sharpe   : {ms['sharpe']/md['sharpe'] if md['sharpe'] else float('nan'):.1f}x"
          f"   (sqrt(252/trade-days-per-yr) ~ {np.sqrt(len(dense)/len(sparse)):.1f}x)")
