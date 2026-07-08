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

import pandas as pd

from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                      backtest_swing_tf, daily_atr_series)
from futures.basket import BASKET, data_filename, RISK, REGIME
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
ACCOUNT           = 50_000.0
SLIPPAGE          = 2.0
# IS Calmar reference: deploy_sim 2-tick slippage, full period 2018-2024.
# Update to _final_rm["calmar"] printed at end of run after any engine/data/period change.
_BACKTEST_CALMAR  = 2.3782  # deploy_sim 2-tick IS 2018-2024; confirmed 2026-07-02

print("Loading data…")
dfs    = {n: load_parquet(str(Path(DATA_DIR) / data_filename(c))) for n, c in BASKET.items()}
atr    = {n: daily_atr_series(df) for n, df in dfs.items()}
pv     = {n: c.point_value for n, c in BASKET.items()}
labels = basket_labels(REGIME_CSV)
costs  = costs_for_basket(slippage_ticks=SLIPPAGE)

c_spec = gi_specs.SPECS["MNKD"]
ndf    = gi_load(NKD_PAR)
ndf.index = ndf.index.tz_convert(c_spec.session_tz)

spy_raw = pd.Series(label_regimes(benchmark_daily(REGIME_CSV), "2018-01-01", 3, REGIME["hmm_fit_end"]))
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

def _ts_str(ts):
    """Convert a Timestamp (pd.Timestamp / numpy datetime64 / None) to ISO string."""
    if ts is None:
        return None
    try:
        return pd.Timestamp(ts).isoformat()
    except Exception:
        return None

def build_rows(n):
    rows = []
    for inst, lst in swing.items():
        for t in lst:
            ed = pd.Timestamp(t["day"])
            rs = n * ROSKA4_MULT * _asof_naive(atr[inst], ed) * pv[inst]
            rows.append(dict(inst=inst, cluster=CLUSTER_SWING,
                             entry=ed, exit=pd.Timestamp(t["exit_day"]),
                             direction=t["direction"], pnl_sized=t["pnl"] * n, risk_sized=rs,
                             entry_price=t.get("entry"),
                             exit_price=t.get("exit"),
                             entry_time=_ts_str(t.get("entry_time")),
                             exit_time=_ts_str(t.get("exit_time")),
                             exit_reason=t.get("reason"),
                             entry_regime=t.get("regime"),
                             hold_days=t.get("hold_days")))
    for inst, lst in stress.items():
        for t in lst:
            ed = pd.Timestamp(t["day"])
            rs = n * ROSKA4_MULT * _asof_naive(atr[inst], ed) * pv[inst]
            rows.append(dict(inst=inst, cluster=CLUSTER_STRESS,
                             entry=ed, exit=pd.Timestamp(t["exit_day"]),
                             direction=t["direction"], pnl_sized=t["pnl"] * n, risk_sized=rs,
                             entry_price=t.get("entry"),
                             exit_price=t.get("exit"),
                             entry_time=_ts_str(t.get("entry_time")),
                             exit_time=_ts_str(t.get("exit_time")),
                             exit_reason=t.get("exit_reason"),  # stop/target/eod from Trade.meta
                             entry_regime=t.get("regime"),
                             hold_days=t.get("hold_days")))
    for t in nkd_t:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed
        rs = n * NKD_MULT * _asof_naive(natr, ed) * c_spec.point_value
        rows.append(dict(inst="MNKD", cluster=CLUSTER_NKD,
                         entry=ed, exit=xd, direction=t["direction"],
                         pnl_sized=t["pnl"] * n, risk_sized=rs,
                         entry_price=t.get("entry"),
                         exit_price=t.get("exit"),
                         entry_time=_ts_str(t.get("entry_time")),
                         exit_time=_ts_str(t.get("exit_time")),
                         exit_reason=t.get("reason"),
                         entry_regime=t.get("regime"),
                         hold_days=t.get("hold_days")))
    return rows

# sizer: n=1 pass → get n_contracts
rows1  = build_rows(1)
guard0 = MultiClusterGuard(account=ACCOUNT)
d1, _  = replay(rows1, ACCOUNT, guard0, {}, CircuitBreaker)
m1     = metrics(d1)
base_margin = sum(BASKET[nm].est_margin for nm in BASKET) + c_spec.est_margin
n_contracts, sz = size_combined(m1["maxdd"], base_margin, ACCOUNT)
cb_map = {nm: n_contracts for nm in BASKET}
cb_map["MNKD"] = 1  # NKD fixed n=1: budget 2% = $1,000 only fits 1 MNKD at any n_contracts
print(f"Sizer: n_contracts={n_contracts}  maxdd1=${m1['maxdd']:,.0f}  binding={sz['binding']}")

all_tr = build_rows(n_contracts)
days   = sorted({t["entry"] for t in all_tr} | {t["exit"] for t in all_tr})
by_entry: dict = {}
for t in all_tr:
    by_entry.setdefault(t["entry"], []).append(t)

# Lookup for enriching exit/open-position snapshots: (inst, entry_day) → row dict
trade_detail: dict = {}
for t in all_tr:
    trade_detail[(t["inst"], t["entry"])] = t

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

# ── Analytics helpers (called each snapshot iteration) ────────────────────
import statistics as _stats

def _safe_f(v, nd):
    """Round v to nd digits; return None for inf/nan."""
    if v is None:
        return None
    try:
        if v != v or abs(v) == float("inf"):
            return None
        return round(v, nd)
    except Exception:
        return None

def _cstats(trs):
    pnls = [t["pnl"] for t in trs]
    if not pnls:
        return {"trade_count": 0, "win_rate": None, "avg_win": None,
                "avg_loss": None, "largest_loss": None}
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    return {"trade_count":  len(pnls),
            "win_rate":     round(len(wins) / len(pnls), 4),
            "avg_win":      round(sum(wins)   / len(wins),   2) if wins   else None,
            "avg_loss":     round(sum(losses) / len(losses), 2) if losses else None,
            "largest_loss": round(min(pnls), 2)}

def _hdist(trs):
    holds = [t["hold"] for t in trs if t.get("hold") is not None]
    if not holds:
        return {"median_hold_days": None,
                "distribution": {f"{d}d": 0 for d in range(1, 6)}}
    dist = {}
    for h in holds:
        k = f"{int(h)}d"
        dist[k] = dist.get(k, 0) + 1
    return {"median_hold_days": round(_stats.median(holds), 1),
            "distribution":     {f"{d}d": dist.get(f"{d}d", 0) for d in range(1, 6)}}

def _rmetrics(dr_list, account):
    if len(dr_list) < 2:
        return {"calmar": None, "sharpe": None, "max_dd": None, "total_return": None}
    s = pd.Series({d: v for d, v in dr_list})
    m = metrics(s)
    return {"calmar":       _safe_f(m["calmar"], 4),
            "sharpe":       _safe_f(m["sharpe"], 4),
            "max_dd":       round(m["maxdd"], 2),
            "total_return": round(m["pnl"] / account, 6)}

# ── Analytics accumulators (reset once, updated each day) ─────────────────
_cl_pnl       = {CLUSTER_SWING: 0.0, CLUSTER_STRESS: 0.0, CLUSTER_NKD: 0.0}
_reg_pnl      = {}                           # {regime_str: cumulative_pnl}
_cl_trs       = {CLUSTER_SWING: [], CLUSTER_STRESS: [], CLUSTER_NKD: []}
_daily_realized = []                         # (day, realized) for non-zero days
_prev_bl      = "OK"
_halt_start   = None
_halt_dd_pct  = 0.0
_breaker_events = []

for day in days:
    dd = decide_day(day, state, by_entry.get(day, []), guard, cb_map)

    peak_equity    = max(peak_equity, state.equity)
    cur_dd_dol     = peak_equity - state.equity
    max_dd_dollars = max(max_dd_dollars, cur_dd_dol)
    dd_pct         = cur_dd_dol / peak_equity if peak_equity > 0 else 0.0

    bs  = state.breaker.status(state.equity)

    # ── Update analytics accumulators ─────────────────────────────────────
    for p in dd.exits:
        det = trade_detail.get((p.inst, p.entry_day), {})
        cl  = p.cluster
        _cl_pnl[cl]  = _cl_pnl.get(cl, 0.0) + p.pnl_sized
        reg = det.get("entry_regime") or "Unknown"
        _reg_pnl[reg] = _reg_pnl.get(reg, 0.0) + p.pnl_sized
        _cl_trs[cl].append({"pnl": p.pnl_sized, "hold": det.get("hold_days")})
    for t in dd.entries:
        if t.get("exit") == day:              # same-day close (stress cluster)
            cl  = t["cluster"]
            pnl = t.get("pnl_sized", 0.0)
            _cl_pnl[cl]  = _cl_pnl.get(cl, 0.0) + pnl
            reg = t.get("entry_regime") or "Unknown"
            _reg_pnl[reg] = _reg_pnl.get(reg, 0.0) + pnl
            _cl_trs[cl].append({"pnl": pnl, "hold": t.get("hold_days")})
    if dd.realized != 0.0:
        _daily_realized.append((day, dd.realized))
    cur_bl   = bs["level"]
    in_halt  = cur_bl in ("HALT", "HALT_DAY")
    was_halt = _prev_bl in ("HALT", "HALT_DAY")
    if in_halt and not was_halt:
        _halt_start = day
        _breaker_events.append({"date": day.strftime("%Y-%m-%d"),
                                 "dd_pct_at_halt": round(dd_pct, 4),
                                 "duration_days":  None})
    elif not in_halt and was_halt and _breaker_events:
        _breaker_events[-1]["duration_days"] = (day - _halt_start).days if _halt_start else None
    _prev_bl = cur_bl
    # ──────────────────────────────────────────────────────────────────────

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
            {
                "inst": p.inst, "direction": p.direction, "cluster": p.cluster,
                "days_held": max(0, (day - p.entry_day).days),
                "risk_sized": round(p.risk_dollars, 2),
                "entry_day": p.entry_day.strftime("%Y-%m-%d"),
                "entry_price": trade_detail.get((p.inst, p.entry_day), {}).get("entry_price"),
                "entry_time": trade_detail.get((p.inst, p.entry_day), {}).get("entry_time"),
            }
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
            "entries": [
                {
                    "inst": t["inst"], "direction": t["direction"], "cluster": t["cluster"],
                    "risk_sized": round(t.get("risk_sized", 0), 2),
                    "entry_price": t.get("entry_price"),
                    "entry_time": t.get("entry_time"),
                    "exit_price": t.get("exit_price"),
                    "exit_time": t.get("exit_time"),
                    "exit_reason": t.get("exit_reason"),
                    "hold_days": t.get("hold_days"),
                    "pnl_sized": round(t.get("pnl_sized", 0), 2),
                    "is_same_day": t.get("exit") == day,
                    "exit_day": day.strftime("%Y-%m-%d") if t.get("exit") == day else None,
                }
                for t in dd.entries
            ],
            "exits": [
                {
                    "inst": p.inst, "direction": p.direction, "cluster": p.cluster,
                    "pnl": round(p.pnl_sized, 2),
                    "risk_sized": round(p.risk_dollars, 2),
                    "hold_days": (p.exit_day - p.entry_day).days if p.exit_day and p.entry_day else None,
                    "entry_day": p.entry_day.strftime("%Y-%m-%d"),
                    "entry_price": trade_detail.get((p.inst, p.entry_day), {}).get("entry_price"),
                    "entry_time": trade_detail.get((p.inst, p.entry_day), {}).get("entry_time"),
                    "exit_price": trade_detail.get((p.inst, p.entry_day), {}).get("exit_price"),
                    "exit_time": trade_detail.get((p.inst, p.entry_day), {}).get("exit_time"),
                    "exit_reason": trade_detail.get((p.inst, p.entry_day), {}).get("exit_reason"),
                }
                for p in dd.exits
            ],
            "rejected_detail": dd.rejected_details
        },
        # ── GROUP A: per-day analytics (accumulated up to this day) ──────────
        "per_cluster_pnl":      {cl: round(v, 2) for cl, v in _cl_pnl.items()},
        "regime_attribution":   {k: round(v, 2)  for k, v  in _reg_pnl.items()},
        "cluster_stats":        {cl: _cstats(_cl_trs[cl])  for cl in _cl_trs},
        "holding_distribution": {cl: _hdist(_cl_trs[cl])   for cl in _cl_trs},
        "running_metrics":      _rmetrics(_daily_realized, ACCOUNT),
        # ── GROUP B: paper-trade diagnostics ─────────────────────────────────
        # Populated by runner.dump_state() during live paper trading (not yet written).
        # Null/empty here so dashboard schema is stable before IBKRBroker exists.
        "paper_vs_backtest": {
            "expected_equity": None,   # backtest equity at this date (filled from replay curve)
            "actual_equity":   None,   # broker.get_equity() at end of day
            "divergence_pct":  None,   # (actual - expected) / expected
        },
        "slippage":      [],           # [{inst, expected_price, actual_price, ticks}]
        "fill_quality":  [],           # [{inst, ordered_qty, filled_qty, partial: bool}]
        "signal_timing": [],           # [{inst, signal_generated_at, order_sent_at, fill_confirmed_at}]
        "runner_health": {
            "last_heartbeat":  None,   # ISO timestamp of last successful run_day() call
            "ibkr_connected":  None,   # bool — IB Gateway connection status
            "errors":          [],     # [{ts, msg}] non-fatal errors this cycle
            "missed_cycles":   0,      # consecutive days runner failed to complete
        },
        # ── paper_progress + degradation: null in replay, runner fills when live ─
        "paper_progress": {
            "days_traded":       None,
            "total_trades":      None,
            "regimes_seen":      [],
            "sample_sufficient": None,
        },
        "degradation": {
            "backtest_calmar":   _BACKTEST_CALMAR,
            "paper_calmar":      None,   # runner: metrics(paper_daily_pnl)["calmar"]
            "degradation_pct":   None,   # (backtest - paper) / backtest * 100
            "status":            None,   # "within_range" / "flag" / "red_flag"
        },
    })

# close any breaker event still open at period end
if _breaker_events and _breaker_events[-1]["duration_days"] is None and days:
    _breaker_events[-1]["duration_days"] = (days[-1] - _halt_start).days if _halt_start else 0

net_pnl  = state.equity - ACCOUNT
_final_m = metrics(pd.Series({d: v for d, v in _daily_realized}))
print(f"Done — equity=${state.equity:,.2f}  net=${net_pnl:,.2f}  "
      f"maxdd=${max_dd_dollars:,.2f}  calmar={_final_m['calmar']:.4f}")

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
        },
        "breaker_events":  _breaker_events,
        "backtest_calmar": _BACKTEST_CALMAR,  # IS reference (deploy_sim 2-tick, 2018-2024)
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
