"""
global_index/generate_replay_snapshots.py — replay runner through IS history,
capture per-day state, write global_index/replay_snapshots_data.js

Run from D:\\raits:
    python -m global_index.generate_replay_snapshots

Output: global_index/replay_snapshots_data.js  (loaded by dashboard.html as
    window.REPLAY_DATA — no HTTP server needed, open HTML directly)

Live integration (when IBKRBroker ready):
    runner calls dump_state(path) each cycle → writes live_state_data.js
    (same format: window.LIVE_DATA = {meta, snapshots:[one_snap]})
    dashboard.html picks it up automatically — no UI changes needed.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                      backtest_swing_tf, daily_atr_series)
from futures.basket import BASKET, data_filename, RISK
from futures.stress_mid import StressMidEngine
from futures.circuit_breaker import CircuitBreaker
from futures.swing_tf import SwingTFEngine, basket_labels, costs_for_basket
from global_index.net_exposure_multi import MultiClusterGuard, DEFAULT_CLUSTERS
from global_index import specs as gi_specs
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index.regime import RegimeLabels
from global_index.live_decision import decide_day, DecisionState
from global_index.signal_layer import (ROSKA4_MULT, NKD_MULT, _asof_naive,
                                        CLUSTER_SWING, CLUSTER_STRESS, CLUSTER_NKD)
from global_index.deploy_sim import size_combined, metrics, replay

DATA_DIR    = r"D:\raits\data\cache\futures"
REGIME_CSV  = r"D:\raits\spy_daily.csv"
NKD_PAR     = r"D:\raits\global_index\data\NKD_continuous_1m_8y.parquet"
OUT_PATH    = Path(__file__).parent / "replay_snapshots_data.js"
VAULT_START = "2023-01-01"
ACCOUNT     = 50_000.0
SLIPPAGE    = 2.0

def clip(df):
    vs = pd.Timestamp(VAULT_START)
    return df[df.index < (vs.tz_localize(df.index.tz) if df.index.tz else vs)]

print("Loading data…")
dfs    = {n: clip(load_parquet(str(Path(DATA_DIR) / data_filename(c)))) for n, c in BASKET.items()}
atr    = {n: daily_atr_series(df) for n, df in dfs.items()}
pv     = {n: c.point_value for n, c in BASKET.items()}
labels = basket_labels(REGIME_CSV, vault_cut=VAULT_START)
costs  = costs_for_basket(slippage_ticks=SLIPPAGE)

c_spec = gi_specs.SPECS["MNKD"]
ndf    = gi_load(NKD_PAR)
ndf.index = ndf.index.tz_convert(c_spec.session_tz)
ndf    = clip(ndf)

spy_raw = pd.Series(label_regimes(benchmark_daily(REGIME_CSV), "2018-01-01", 3))
spy_idx = pd.DatetimeIndex(spy_raw.index)
spy_raw.index = (spy_idx.tz_localize(None) if spy_idx.tz else spy_idx).normalize()
spy_raw = spy_raw.sort_index()
spy_lagged = spy_raw.shift(1)   # lag_days=1: yesterday's regime for today

nlab  = RegimeLabels(spy_raw, lag_days=1)
ncost = GIFC(point_value=c_spec.point_value, tick=c_spec.tick,
              commission_rt=c_spec.commission_rt, slippage_ticks_per_side=SLIPPAGE)
natr  = daily_atr_series(ndf)

print("Running backtests…")
swing  = SwingTFEngine().backtest_basket(dfs, labels, costs)
stress = StressMidEngine().backtest_basket(dfs, labels, costs)
nkd_t  = backtest_swing_tf(ndf, nlab, ncost, ema_period=10,
                             chandelier_atr_mult=2.5, max_hold_days=5, gap_fill=True)

print(f"Trades: swing={sum(len(v) for v in swing.values())}  "
      f"stress={sum(len(v) for v in stress.values())}  nkd={len(nkd_t)}")

def build_rows(n):
    rows = []
    for inst, lst in swing.items():
        for t in lst:
            ed = pd.Timestamp(t["day"])
            rs = n * ROSKA4_MULT * _asof_naive(atr[inst], ed) * pv[inst]
            rows.append(dict(inst=inst, cluster=CLUSTER_SWING,
                             entry=ed, exit=pd.Timestamp(t["exit_day"]),
                             direction=t["direction"], pnl_sized=t["pnl"] * n, risk_sized=rs))
    for inst, lst in stress.items():
        for t in lst:
            ed = pd.Timestamp(t["day"])
            rs = n * ROSKA4_MULT * _asof_naive(atr[inst], ed) * pv[inst]
            rows.append(dict(inst=inst, cluster=CLUSTER_STRESS,
                             entry=ed, exit=pd.Timestamp(t["exit_day"]),
                             direction=t["direction"], pnl_sized=t["pnl"] * n, risk_sized=rs))
    for t in nkd_t:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed
        rs = n * NKD_MULT * _asof_naive(natr, ed) * c_spec.point_value
        rows.append(dict(inst="MNKD", cluster=CLUSTER_NKD,
                         entry=ed, exit=xd, direction=t["direction"],
                         pnl_sized=t["pnl"] * n, risk_sized=rs))
    return rows

# sizer: n=1 pass → get n_contracts
rows1  = build_rows(1)
guard0 = MultiClusterGuard(account=ACCOUNT)
d1, _  = replay(rows1, ACCOUNT, guard0, {}, CircuitBreaker)
m1     = metrics(d1)
base_margin = sum(BASKET[nm].est_margin for nm in BASKET) + c_spec.est_margin
n_contracts, sz = size_combined(m1["maxdd"], base_margin, ACCOUNT)
cb_map = {nm: n_contracts for nm in BASKET}
cb_map["MNKD"] = n_contracts
print(f"Sizer: n_contracts={n_contracts}  maxdd1=${m1['maxdd']:,.0f}  binding={sz['binding']}")

all_tr = build_rows(n_contracts)
days   = sorted({t["entry"] for t in all_tr} | {t["exit"] for t in all_tr})
by_entry: dict = {}
for t in all_tr:
    by_entry.setdefault(t["entry"], []).append(t)

print(f"Capturing {len(days)} day snapshots…")

guard   = MultiClusterGuard(account=ACCOUNT)
breaker = CircuitBreaker(account=ACCOUNT)
state   = DecisionState(equity=ACCOUNT,
                        taken={c: 0 for c in guard.clusters},
                        rejected={c: 0 for c in guard.clusters},
                        breaker=breaker)

peak_equity    = ACCOUNT
max_dd_dollars = 0.0
snapshots      = []

for day in days:
    dd = decide_day(day, state, by_entry.get(day, []), guard, cb_map)

    peak_equity    = max(peak_equity, state.equity)
    cur_dd_dol     = peak_equity - state.equity
    max_dd_dollars = max(max_dd_dollars, cur_dd_dol)
    dd_pct         = cur_dd_dol / peak_equity if peak_equity > 0 else 0.0

    bs  = state.breaker.status(state.equity)
    exp = guard.state([p.as_position() for p in state.open_positions])

    rv  = spy_lagged.asof(day)
    regime = str(rv) if (rv is not None and not pd.isna(rv)) else "Unknown"

    taken_today    = {cl: 0 for cl in guard.clusters}
    rejected_today = {cl: 0 for cl in guard.clusters}
    for t in dd.entries:
        taken_today[t["cluster"]] = taken_today.get(t["cluster"], 0) + 1
    for t in dd.rejected:
        rejected_today[t["cluster"]] = rejected_today.get(t["cluster"], 0) + 1

    snapshots.append({
        "date": day.strftime("%Y-%m-%d"),
        "equity": round(state.equity, 2),
        "drawdown_pct": round(dd_pct, 6),
        "drawdown_dollars": round(cur_dd_dol, 2),
        "max_dd_dollars": round(max_dd_dollars, 2),
        "breaker_level": bs["level"],
        "regime": regime,
        "open_positions": [
            {"inst": p.inst, "direction": p.direction, "cluster": p.cluster,
             "days_held": max(0, (day - p.entry_day).days),
             "risk_sized": round(p.risk_dollars, 2),
             "entry_day": p.entry_day.strftime("%Y-%m-%d")}
            for p in state.open_positions
        ],
        "cluster_exposure": {
            cl: {"gross_pct": round(v["gross_pct"], 6), "net_pct": round(v["net_pct"], 6)}
            for cl, v in exp.items()
        },
        "decision": {
            "realized_today": round(dd.realized, 2),
            "taken_today": taken_today,
            "rejected_today": rejected_today,
            "halted_today": len(dd.halted),
            "entries": [{"inst": t["inst"], "direction": t["direction"],
                          "cluster": t["cluster"],
                          "risk_sized": round(t.get("risk_sized", 0), 2)}
                         for t in dd.entries],
            "exits": [{"inst": p.inst, "direction": p.direction, "cluster": p.cluster,
                        "pnl": round(p.pnl_sized, 2),
                        "entry_day": p.entry_day.strftime("%Y-%m-%d")}
                       for p in dd.exits],
            "rejected_detail": [{"inst": t["inst"], "direction": t["direction"],
                                   "cluster": t["cluster"]}
                                  for t in dd.rejected]
        }
    })

net_pnl = state.equity - ACCOUNT
print(f"Done — equity=${state.equity:,.2f}  net=${net_pnl:,.2f}  maxdd=${max_dd_dollars:,.2f}")

output = {
    "meta": {
        "account": ACCOUNT,
        "hard_dd_pct": RISK.get("max_drawdown_pct", 0.15),
        "target_dd_pct": RISK.get("target_drawdown_pct", 0.10),
        "daily_loss_pct": 0.04,
        "n_contracts": n_contracts,
        "final_equity": round(state.equity, 2),
        "net_pnl": round(net_pnl, 2),
        "max_dd_dollars": round(max_dd_dollars, 2),
        "max_dd_pct": round(max_dd_dollars / ACCOUNT, 6),
        "total_days": len(snapshots),
        "clusters": {
            cl: {"max_gross_pct": b.max_gross_pct, "max_net_pct": b.max_net_pct}
            for cl, b in DEFAULT_CLUSTERS.items()
        }
    },
    "snapshots": snapshots
}

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write("// Auto-generated by generate_replay_snapshots.py — DO NOT EDIT\n")
    f.write("// Re-run: python -m global_index.generate_replay_snapshots\n")
    f.write("window.REPLAY_DATA = ")
    json.dump(output, f, separators=(",", ":"), ensure_ascii=False)
    f.write(";\n")

kb = OUT_PATH.stat().st_size / 1024
print(f"Saved → {OUT_PATH}  ({kb:.0f} KB,  {len(snapshots)} snapshots)")
print("Open dashboard.html in browser (no server needed)")
