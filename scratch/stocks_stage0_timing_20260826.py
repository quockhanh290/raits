"""Where the per-symbol second goes. Read-only, throwaway timing probe."""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from global_index import track1_normal_r4 as NR
from global_index import track1_normal_filters as NF
from scratch import stocks_stage0_data_20260826 as D
from scratch import stocks_stage0_engine_20260826 as E
from scratch import stocks_stage0_regime_20260826 as R

cal = pd.DatetimeIndex([d for d in D.calendar("SPY")
                        if pd.Timestamp("2019-01-02") <= d <= pd.Timestamp("2022-12-30")])
lab = R.labels()
labels_obj = R.LaggedLabels(lab["causal"], lag=1)
params = NR.NormalR4Params(ema_period=50, stop_basis_atr_mult=2.0, chandelier_atr_mult=2.5,
                           max_hold_days=5, ratchet=False, fill_law=NR.FILL_PRODUCTION)
short_days = NF.short_days_from_csv(str(D.SPY_CSV), params.spy_short_filter)

t = time.time(); df = D.load_symbol("AAPL", cal); t_load = time.time() - t
t = time.time(); daily = D.daily_from_5m(df); datr = D.daily_atr_causal(daily); t_daily = time.time() - t
t = time.time(); meas = NF.R4ContextFilter(df, range_max=params.range_max,
                                           vol_max=params.rel_volume_max,
                                           vol_feature=params.vol_feature); t_filt = time.time() - t
t = time.time(); cache = dict(NR._cache_for(df, params)); t_cache = time.time() - t
cache["datr"] = datr
strat = NR._strategy(params)
sf = E._recording_signal_fn(NR.make_signal_fn(strat, params, datr, short_days=short_days,
                                              context=None))
t = time.time(); sigs = NR.scan_signals(strat, cache, labels_obj, params, sf); t_scan = time.time() - t
t = time.time(); tr = NR._replay(strat, labels_obj, E._UnitCost(), params, cache=cache,
                                 signals=sigs, signal_for=sf); t_replay = time.time() - t
E.clear_engine_cache()
print("bars", len(df), "sessions", len(daily), "signals", len(sigs), "trades", len(tr))
for k, v in [("load_parquet_files", t_load), ("daily+atr", t_daily), ("R4ContextFilter", t_filt),
             ("_cache_for", t_cache), ("scan_signals", t_scan), ("_replay", t_replay)]:
    print("  {:22s} {:6.2f}s".format(k, v))
