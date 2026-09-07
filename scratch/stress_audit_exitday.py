"""AUDIT-ONLY: re-check same-session exit with matching tz (previous check compared
tz-aware exit_time against tz-naive day and returned an impossible 0/84)."""
from __future__ import annotations
import sys
from pathlib import Path
if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))
import pandas as pd
from futures._validated_core import benchmark_daily, daily_atr_series, label_regimes, load_parquet
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket
from scratch.harness import ARGV
from scratch.stress_sleeve_validation import Variant, build_variant, clip, arg_from

argv = list(ARGV["floor"])
dfs = {n: clip(load_parquet(str(Path(arg_from(argv, "--data-dir")) / data_filename(c))),
               arg_from(argv, "--start"), arg_from(argv, "--end")) for n, c in BASKET.items()}
atrs = {n: daily_atr_series(d) for n, d in dfs.items()}
labels = label_regimes(benchmark_daily("spy_daily_live.csv"), "2018-01-01", 3, "2022-12-31")
tr, _ = build_variant(dfs, labels, costs_for_basket(slippage_ticks=2.0), atrs,
                      Variant("breadth3_mnq_mes"))
assert not tr.empty, "SC FAIL: no trades -> nothing verified"
ex = pd.DatetimeIndex(tr.exit_time)
en = pd.DatetimeIndex(tr.entry_time)
ex_d = ex.tz_localize(None).normalize() if ex.tz is not None else ex.normalize()
en_d = en.tz_localize(None).normalize() if en.tz is not None else en.normalize()
day_d = pd.DatetimeIndex(pd.to_datetime(tr.day)).normalize()
print(f"n={len(tr)}")
print(f"exit date == entry date        : {int((ex_d == en_d).sum())}/{len(tr)}")
print(f"exit date == labelled day      : {int((ex_d == day_d).sum())}/{len(tr)}")
print(f"entry times seen               : {sorted(set(en.time))}")
print(f"exit  time min/max             : {min(ex.time)} .. {max(ex.time)}")
print(f"exits strictly after entry     : {int((ex > en).sum())}/{len(tr)}")
print(f"exit_reason counts             : {tr.exit_reason.value_counts().to_dict()}")
