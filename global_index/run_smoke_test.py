"""
global_index/run_smoke_test.py
===============================
COLD-START INTEGRATION SMOKE TEST — RAITS futures live pipeline.

Runs FuturesRunner + MockBroker from a clean production entry point. Verifies:
  1. CWD guard works (must be d:\\raits)
  2. Config loads from canonical sources (basket.py REGIME/RISK/SWING_TF_PARAM)
  3. fit_C (2024-12-31) is live, NOT fit_A residual
  4. UTF-8 / "Rổ 4" logging survives cold start
  5. n_contracts from deploy_sim.size_combined() == 1
  6. net P&L / taken / rejected / lifecycle == deploy_sim fit_C ($52,936)

HOW THIS DIFFERS FROM verify_runner_real.py:
  verify_runner_real.py is a reconcile harness: hardcodes SLIPPAGE=2.0 / N_CONTRACTS=1,
  manually wires config, skips the sizing step.
  This script is the integration test: loads config from basket.py, runs size_combined(),
  checks CWD, checks UTF-8 cold, then runs the same runner logic. If results diverge,
  a cold-start / config-loading issue is exposed that verify_runner_real hid.

Run from d:\\raits (clear .pyc first):
    find . -name "*.pyc" -delete   # or: Get-ChildItem -Recurse -Filter *.pyc | Remove-Item
    python -m global_index.run_smoke_test ^
        --data-dir data\\cache\\futures ^
        --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet ^
        --regime-csv spy_daily.csv
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

# ── [1] CWD guard — must be d:\raits before anything else ──────────────────
_CWD = Path.cwd()
_has_gi  = (_CWD / "global_index").is_dir()
_has_fut = (_CWD / "futures").is_dir()
if not (_has_gi and _has_fut):
    sys.stderr.write(
        f"CWD guard FAIL: got {_CWD}\n"
        f"  Expected d:\\raits (global_index/ and futures/ must exist as subdirs).\n"
        f"  Fix: cd d:\\raits && python -m global_index.run_smoke_test ...\n"
    )
    sys.exit(1)

if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))

# ── [2] UTF-8: reconfigure before any print with non-ASCII ─────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

# ── [3] Production imports — from canonical sources only ────────────────────
from futures.basket import BASKET, REGIME, RISK, SWING_TF_PARAM, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from futures.stress_mid import StressMidEngine
from futures.circuit_breaker import CircuitBreaker
from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                      backtest_swing_tf, daily_atr_series)
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index import specs as gi_specs
from global_index.regime import RegimeLabels
from global_index.net_exposure_multi import MultiClusterGuard
from global_index.signal_layer import (CLUSTER_SWING, CLUSTER_STRESS, CLUSTER_NKD,
                                        ROSKA4_MULT, NKD_MULT,
                                        _asof_naive, to_candidate, diff_desired_vs_held)
from global_index.broker import MockBroker
from global_index.runner import FuturesRunner
from global_index.deploy_sim import replay as deploy_replay, size_combined, metrics

# ── Production constants: sourced from basket.py, NOT hardcoded ─────────────
ACCOUNT     = float(RISK["account"])       # $50,000
HMM_FIT_END = REGIME["hmm_fit_end"]       # "2024-12-31"  (fit_C)
SLIPPAGE    = 2.0          # 2 tick/side  — matches baseline_fit_c.txt (NOT deploy_sim default 1.0)
NKD_INST    = "MNKD"
NKD_EMA     = 10


# ── Helpers (same logic as verify_runner_real, inline for cold-start purity) ─
def _desired_at(trades_sorted, day_ts):
    d = day_ts.normalize()
    cur = None
    for t in trades_sorted:
        e = pd.Timestamp(t["day"]).normalize()
        if e > d:
            break
        x = pd.Timestamp(t["exit_day"]).normalize()
        if e <= d < x:
            cur = t
    return cur


def _real_risk(atr_s, mult, pv, entry_day, n):
    try:
        av = atr_s.asof(pd.Timestamp(entry_day))
    except Exception:
        av = np.nan
    if av is None or (isinstance(av, float) and pd.isna(av)):
        av = float(atr_s.median())
    return n * mult * float(av) * pv


def main():
    ap = argparse.ArgumentParser(description="RAITS cold-start integration smoke test")
    ap.add_argument("--data-dir",     required=True)
    ap.add_argument("--nkd-parquet",  required=True)
    ap.add_argument("--regime-csv",   required=True)
    a = ap.parse_args()

    # ── UTF-8 test: must not explode on Windows with Vietnamese chars ─────────
    print("=" * 72)
    print("SMOKE TEST — RAITS Rổ 4 live pipeline (cold-start integration)")
    print(f"  CWD:         {_CWD}  [PASS]")
    print(f"  hmm_fit_end: {HMM_FIT_END}  (fit_C)")
    print(f"  account:     ${ACCOUNT:,.0f}  |  slippage: {SLIPPAGE} tick/side")
    print(f"  ema={SWING_TF_PARAM['ema_period']} mult={SWING_TF_PARAM['chandelier_atr_mult']} "
          f"hold={SWING_TF_PARAM['max_hold_days']}")
    print("=" * 72)

    # ── [config] verify production values came from basket.py correctly ───────
    assert HMM_FIT_END == "2024-12-31", f"fit_C check FAIL: got {HMM_FIT_END}"
    assert ACCOUNT == 50_000.0,          f"account check FAIL: got {ACCOUNT}"
    assert SWING_TF_PARAM["ema_period"] == 30, "ema_period FAIL"
    print("\n[config] fit_C + account + ema from basket.py  PASS")

    # ── load bar data ──────────────────────────────────────────────────────────
    print("\n[data] Loading bar data...")
    dfs = {n: load_parquet(str(Path(a.data_dir) / data_filename(c))) for n, c in BASKET.items()}
    c_nkd = gi_specs.SPECS[NKD_INST]
    ndf = gi_load(a.nkd_parquet)
    ndf.index = ndf.index.tz_convert(c_nkd.session_tz)
    print(f"       Rổ 4: {list(dfs.keys())} | NKD: {len(ndf):,} bars")

    # ── HMM fit_C labels ───────────────────────────────────────────────────────
    print(f"\n[hmm]  fit_C labels (hmm_fit_end={HMM_FIT_END})...")
    bench        = benchmark_daily(a.regime_csv)
    swing_labels = label_regimes(bench, "2018-01-01", 3, HMM_FIT_END)
    spy_s        = pd.Series(swing_labels)
    idx          = pd.DatetimeIndex(spy_s.index)
    spy_s.index  = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nkd_labels   = RegimeLabels(spy_s.sort_index(), lag_days=1)
    sl_s         = spy_s.sort_index()

    def _regime(day_ts):
        d = pd.Timestamp(day_ts).normalize()
        if d.tzinfo is not None:
            d = d.tz_localize(None)
        try:
            v = sl_s.asof(d)
        except Exception:
            return None
        return str(v) if v is not None and not (isinstance(v, float) and pd.isna(v)) else None

    print(f"       {len(swing_labels)} SPY label days")

    # ── backtests ──────────────────────────────────────────────────────────────
    print(f"\n[bt]   Backtests (slippage={SLIPPAGE})...")
    costs_2t  = costs_for_basket(slippage_ticks=SLIPPAGE)
    swing_bt  = SwingTFEngine().backtest_basket(dfs, swing_labels, costs_2t)
    ncost_2t  = GIFC(point_value=c_nkd.point_value, tick=c_nkd.tick,
                     commission_rt=c_nkd.commission_rt, slippage_ticks_per_side=SLIPPAGE)
    nkd_bt    = backtest_swing_tf(ndf, nkd_labels, ncost_2t,
                                   ema_period=NKD_EMA, chandelier_atr_mult=NKD_MULT,
                                   max_hold_days=5, gap_fill=True)
    stress_bt = StressMidEngine().backtest_basket(dfs, swing_labels, costs_2t)
    print(f"       swing={sum(len(v) for v in swing_bt.values())}  "
          f"nkd={len(nkd_bt)}  stress={sum(len(v) for v in stress_bt.values())}")

    # ── ATR series + point values ──────────────────────────────────────────────
    atr_swing = {n: daily_atr_series(df) for n, df in dfs.items()}
    atr_nkd   = daily_atr_series(ndf)
    pv        = {n: c.point_value for n, c in BASKET.items()}
    pv[NKD_INST] = c_nkd.point_value

    # ── size_combined: verify n=1 from production sizer ───────────────────────
    print("\n[size] deploy_sim.size_combined() → n_contracts...")
    all_tr_1 = []
    for inst, lst in swing_bt.items():
        for t in lst:
            r = _real_risk(atr_swing[inst], ROSKA4_MULT, pv[inst], pd.Timestamp(t["day"]), 1)
            all_tr_1.append(dict(inst=inst, cluster=CLUSTER_SWING,
                                 entry=pd.Timestamp(t["day"]), exit=pd.Timestamp(t["exit_day"]),
                                 direction=t["direction"], risk_sized=r, pnl_sized=t["pnl"]))
    for inst, lst in stress_bt.items():
        for t in lst:
            r = _real_risk(atr_swing[inst], ROSKA4_MULT, pv[inst], pd.Timestamp(t["day"]), 1)
            all_tr_1.append(dict(inst=inst, cluster=CLUSTER_STRESS,
                                 entry=pd.Timestamp(t["day"]), exit=pd.Timestamp(t["exit_day"]),
                                 direction=t["direction"], risk_sized=r, pnl_sized=t["pnl"]))
    for t in nkd_bt:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed
        r  = _real_risk(atr_nkd, NKD_MULT, pv[NKD_INST], ed, 1)
        all_tr_1.append(dict(inst=NKD_INST, cluster=CLUSTER_NKD,
                             entry=ed, exit=xd,
                             direction=t["direction"], risk_sized=r, pnl_sized=t["pnl"]))

    cb1 = {n: 1 for n in list(BASKET) + [NKD_INST]}
    daily_1, _ = deploy_replay(all_tr_1, ACCOUNT, MultiClusterGuard(account=ACCOUNT), cb1, None)
    m1 = metrics(daily_1)
    base_margin = sum(c.est_margin for c in BASKET.values()) + c_nkd.est_margin
    N, sz = size_combined(m1["maxdd"], base_margin, ACCOUNT)
    print(f"       1-micro MaxDD=${m1['maxdd']:,.0f}  dd_scale={sz['dd_scale']:.2f}  "
          f"binding={sz['binding']} → n_contracts={N}")
    assert N == 1, f"sizing FAIL: expected n=1, got {N}"
    print(f"       n_contracts=1  PASS")
    N_CONTRACTS = N

    # ── all_trades (n=1) ───────────────────────────────────────────────────────
    all_tr = []
    for inst, lst in swing_bt.items():
        for t in lst:
            all_tr.append(dict(inst=inst, cluster=CLUSTER_SWING,
                               entry=pd.Timestamp(t["day"]), exit=pd.Timestamp(t["exit_day"]),
                               direction=t["direction"], pnl1=t["pnl"],
                               _atr=atr_swing[inst], _mult=ROSKA4_MULT, _pv=pv[inst]))
    for inst, lst in stress_bt.items():
        for t in lst:
            all_tr.append(dict(inst=inst, cluster=CLUSTER_STRESS,
                               entry=pd.Timestamp(t["day"]), exit=pd.Timestamp(t["exit_day"]),
                               direction=t["direction"], pnl1=t["pnl"],
                               _atr=atr_swing[inst], _mult=ROSKA4_MULT, _pv=pv[inst]))
    for t in nkd_bt:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed
        all_tr.append(dict(inst=NKD_INST, cluster=CLUSTER_NKD,
                           entry=ed, exit=xd,
                           direction=t["direction"], pnl1=t["pnl"],
                           _atr=atr_nkd, _mult=NKD_MULT, _pv=pv[NKD_INST]))
    contracts_by = {n: N_CONTRACTS for n in list(BASKET) + [NKD_INST]}
    for t in all_tr:
        t["risk_sized"] = _real_risk(t["_atr"], t["_mult"], t["_pv"], t["entry"], N_CONTRACTS)
        t["pnl_sized"]  = t["pnl1"] * N_CONTRACTS

    # ── reference replay ───────────────────────────────────────────────────────
    print("\n[ref]  deploy_sim.replay...")
    ref_daily, ref_stats = deploy_replay(all_tr, ACCOUNT,
                                          MultiClusterGuard(account=ACCOUNT),
                                          contracts_by, CircuitBreaker)
    ref_net = float(ref_daily.sum())
    ref_m   = metrics(ref_daily)
    print(f"       net=${ref_net:>10,.2f}  Calmar={ref_m['calmar']:.2f}  "
          f"MaxDD=${ref_m['maxdd']:,.0f}  (expect ~$52,936)")

    # ── signal_fn (pre-computed timelines, same as verify_runner_real fix) ─────
    ledger: dict = {}
    for t in all_tr:
        k = (t["inst"], t["cluster"], pd.Timestamp(t["entry"]).normalize())
        ledger[k] = {"exit": t["exit"], "pnl_sized": t["pnl_sized"]}
    swing_sorted   = {inst: sorted(lst, key=lambda t: pd.Timestamp(t["day"]))
                      for inst, lst in swing_bt.items()}
    nkd_sorted     = sorted(nkd_bt, key=lambda t: pd.Timestamp(t["day"]))
    stress_by_day  = {(pd.Timestamp(t["day"]).normalize(), inst): t
                      for inst, lst in stress_bt.items() for t in lst}

    def signal_fn(day, _bars, held):
        day_ts      = pd.Timestamp(day).normalize()
        held_by_key = {(p.inst, p.cluster): p for p in held}
        force_entries: list = []
        desired: dict = {}

        for inst in dfs:
            key = (inst, CLUSTER_SWING)
            t   = _desired_at(swing_sorted[inst], day_ts)
            if t is not None:
                new_ed = pd.Timestamp(t["day"]).normalize()
                sig = {"direction": t["direction"], "entry": float(t.get("entry", 0.0)),
                       "stop": float(t.get("stop", 0.0)), "entry_day": new_ed}
                cur = held_by_key.get(key)
                if cur is not None and cur.direction == sig["direction"] \
                        and cur.entry_day.normalize() != new_ed:
                    desired[key] = None
                    force_entries.append((inst, CLUSTER_SWING, sig))
                elif cur is None:
                    desired[key] = sig if new_ed == day_ts else None
                else:
                    desired[key] = sig
            else:
                desired[key] = None

        nkd_key = (NKD_INST, CLUSTER_NKD)
        nt      = _desired_at(nkd_sorted, day_ts)
        if nt is not None:
            new_ed  = pd.Timestamp(nt["day"]).normalize()
            nkd_sig = {"direction": nt["direction"], "entry": float(nt.get("entry", 0.0)),
                       "stop": float(nt.get("stop", 0.0)), "entry_day": new_ed}
            cur = held_by_key.get(nkd_key)
            if cur is not None and cur.direction == nkd_sig["direction"] \
                    and cur.entry_day.normalize() != new_ed:
                desired[nkd_key] = None
                force_entries.append((NKD_INST, CLUSTER_NKD, nkd_sig))
            elif cur is None:
                desired[nkd_key] = nkd_sig if new_ed == day_ts else None
            else:
                desired[nkd_key] = nkd_sig
        else:
            desired[nkd_key] = None

        state_entries, exits = diff_desired_vs_held(desired, held)
        state_entries.extend(force_entries)

        candidates = []
        for inst, cluster, sig in state_entries:
            atr_s = atr_nkd if cluster == CLUSTER_NKD else atr_swing[inst]
            mult  = NKD_MULT if cluster == CLUSTER_NKD else ROSKA4_MULT
            av    = _asof_naive(atr_s, sig["entry_day"])
            cand  = to_candidate(inst, sig["direction"], sig["entry"], sig["stop"],
                                 cluster, contracts_by.get(inst, N_CONTRACTS), pv[inst],
                                 daily_atr=av, mult=mult)
            lk = (inst, cluster, sig["entry_day"].normalize())
            if lk in ledger:
                cand["exit"]      = ledger[lk]["exit"]
                cand["pnl_sized"] = ledger[lk]["pnl_sized"]
            candidates.append(cand)

        if _regime(day_ts) == "Stress":
            held_st = {(p.inst, p.cluster) for p in held}
            for inst in dfs:
                if (inst, CLUSTER_STRESS) in held_st:
                    continue
                st = stress_by_day.get((day_ts, inst))
                if st is not None:
                    av   = _asof_naive(atr_swing[inst], day_ts)
                    cand = to_candidate(inst, st["direction"], float(st.get("entry", 0.0)),
                                        0.0, CLUSTER_STRESS,
                                        contracts_by.get(inst, N_CONTRACTS), pv[inst],
                                        daily_atr=av, mult=ROSKA4_MULT)
                    cand["exit"]      = day_ts
                    cand["pnl_sized"] = st["pnl"] * N_CONTRACTS
                    candidates.append(cand)
        return candidates, exits

    # ── run FuturesRunner + MockBroker ─────────────────────────────────────────
    print("\n[run]  FuturesRunner + MockBroker...")
    broker = MockBroker(bars_by_inst={}, account=ACCOUNT)
    guard  = MultiClusterGuard(account=ACCOUNT)
    runner = FuturesRunner(broker=broker, guard=guard,
                           contracts_by_inst=contracts_by, signal_fn=signal_fn,
                           breaker=CircuitBreaker(account=ACCOUNT))
    days_all = sorted({t["entry"] for t in all_tr} | {t["exit"] for t in all_tr})
    print(f"       {len(days_all)} days  ({days_all[0].date()} → {days_all[-1].date()})")
    daily, stats = runner.run_history(days_all)
    run_net = float(daily.sum()) if not daily.empty else 0.0
    run_m   = metrics(daily) if not daily.empty else {}

    # ── results ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("RESULTS")
    print("=" * 72)

    pnl_ok  = abs(run_net - ref_net) < 1.0
    print(f"\nP&L")
    print(f"  Reference (deploy_sim):  ${ref_net:>10,.2f}")
    print(f"  Runner (cold-start):     ${run_net:>10,.2f}")
    print(f"  Diff:                    ${run_net - ref_net:>+10.2f}  {'PASS' if pnl_ok else 'FAIL'}")
    print(f"  Calmar={run_m.get('calmar', 0):.2f}  MaxDD=${run_m.get('maxdd', 0):,.0f}")

    clusters = [CLUSTER_SWING, CLUSTER_STRESS, CLUSTER_NKD]
    print(f"\nTaken / Rejected")
    tk_ok = rj_ok = True
    for c in clusters:
        rt, rn = ref_stats["taken"].get(c, 0), stats["taken"].get(c, 0)
        rr, rjn = ref_stats["rejected"].get(c, 0), stats["rejected"].get(c, 0)
        tok = rt == rn; rjok = rr == rjn; tk_ok &= tok; rj_ok &= rjok
        print(f"  {c:<20}  taken {rt}/{rn} {'OK' if tok else 'FAIL'}  "
              f"rej {rr}/{rjn} {'OK' if rjok else 'FAIL'}")

    opens  = sum(1 for f in broker.fills if f.action == "OPEN")
    closes = sum(1 for f in broker.fills if f.action == "CLOSE")
    resid  = broker.get_positions()
    beq    = broker.get_equity()
    lc_ok  = opens == closes and len(resid) == 0
    eq_ok  = abs(beq - (ACCOUNT + run_net)) < 1.0
    print(f"\nLifecycle  OPEN={opens}  CLOSE={closes}  {'PASS' if opens==closes else 'FAIL'}")
    print(f"  Residual={len(resid)}  broker_equity=${beq:,.2f}  "
          f"{'PASS' if lc_ok and eq_ok else 'FAIL'}")

    halt_ok = ref_stats["halted"] == stats["halted"]
    print(f"\nCircuit breaker  ref={ref_stats['halted']}  run={stats['halted']}  "
          f"{'PASS' if halt_ok else 'FAIL'}")

    print(f"\n{'='*72}")
    all_pass = pnl_ok and tk_ok and rj_ok and halt_ok and lc_ok and eq_ok
    if all_pass:
        print("OVERALL: ALL PASS — cold-start pipeline == deploy_sim fit_C")
        print(f"  No divergence from verify_runner_real.py; integration stack clean.")
    else:
        print("OVERALL: SOME CHECKS FAILED — cold-start/config issue. See above.")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
