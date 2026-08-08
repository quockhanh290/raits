"""
global_index/verify_runner_real.py
ONE-TIME OFFLINE VERIFY: FuturesRunner + MockBroker + REAL signal_fn == deploy_sim fit_C.

Proves the full live path (runner → real signal engines → decide_day) reproduces
deploy_sim fit_C trade-for-trade.  Uses pre-computed trade timelines (O(n) total)
instead of calling desired_position() per day (which would be O(n²) via _SWING_CACHE).

Run from d:\\raits:
    python -m global_index.verify_runner_real ^
        --data-dir data\\cache\\futures ^
        --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet ^
        --regime-csv spy_daily.csv
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                     backtest_swing_tf, daily_atr_series)
from futures.basket import BASKET, REGIME, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from futures.stress_mid import StressMidEngine
from futures.circuit_breaker import CircuitBreaker
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index import specs as gi_specs
from global_index.regime import RegimeLabels
from global_index.net_exposure_multi import MultiClusterGuard
from global_index.signal_layer import (CLUSTER_SWING, CLUSTER_STRESS, CLUSTER_NKD,
                                        ROSKA4_MULT, NKD_MULT,
                                        _asof_naive, to_candidate, diff_desired_vs_held)
from global_index.broker import MockBroker
from global_index.runner import FuturesRunner
from global_index.deploy_sim import replay as deploy_replay

ACCOUNT     = 50_000.0
SLIPPAGE    = 2.0          # matches baseline_fit_c.txt
NKD_INST    = "MNKD"
NKD_EMA     = 10
N_CONTRACTS = 1            # sizing gives n=1 at $50k (baseline_fit_c.txt confirms)


# ── helper: which trade is open at `day_ts`? ────────────────────────────────
def desired_at(trades_sorted: list, day_ts: pd.Timestamp):
    """Return the backtest trade active at day_ts (entry_day <= day < exit_day), else None.
    trades_sorted must be in ascending entry-day order (backtest output already is)."""
    d = day_ts.normalize()
    current = None
    for t in trades_sorted:
        e = pd.Timestamp(t["day"]).normalize()
        if e > d:
            break
        x = pd.Timestamp(t["exit_day"]).normalize()
        if e <= d < x:
            current = t
    return current


def _real_risk(atr_s: pd.Series, mult: float, point_value: float,
               entry_day, n: int) -> float:
    """ATR-based risk$ for one entry — exact same formula as deploy_sim.real_risk."""
    try:
        av = atr_s.asof(pd.Timestamp(entry_day))
    except Exception:
        av = np.nan
    if av is None or (isinstance(av, float) and pd.isna(av)):
        av = float(atr_s.median())
    return n * mult * float(av) * point_value


def main():
    ap = argparse.ArgumentParser(
        description="Verify FuturesRunner + MockBroker + real signal == deploy_sim fit_C")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--nkd-parquet", required=True)
    ap.add_argument("--regime-csv", required=True)
    a = ap.parse_args()

    print("=" * 72)
    print("VERIFY: FuturesRunner + MockBroker + REAL signal == deploy_sim fit_C")
    print(f"  slippage={SLIPPAGE} tick/side | account=${ACCOUNT:,.0f} | n={N_CONTRACTS} micro each")
    print("=" * 72)

    # ── 1. Load bar data ─────────────────────────────────────────────────────
    print("\n[1] Loading bar data...")
    dfs = {n: load_parquet(str(Path(a.data_dir) / data_filename(c)))
           for n, c in BASKET.items()}
    c_nkd = gi_specs.SPECS[NKD_INST]
    ndf = gi_load(a.nkd_parquet)
    ndf.index = ndf.index.tz_convert(c_nkd.session_tz)
    print(f"  Swing: {list(dfs.keys())} | NKD bars: {len(ndf)}")

    # ── 2. HMM fit_C labels ──────────────────────────────────────────────────
    print(f"\n[2] Computing HMM fit_C labels (hmm_fit_end={REGIME['hmm_fit_end']})...")
    bench = benchmark_daily(a.regime_csv)
    swing_labels = label_regimes(bench, "2018-01-01", 3, REGIME["hmm_fit_end"])

    # NKD labels: lag-1 lookahead-safe (NKD JST session leads US close)
    spy_s = pd.Series(swing_labels)
    idx = pd.DatetimeIndex(spy_s.index)
    spy_s.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nkd_labels = RegimeLabels(spy_s.sort_index(), lag_days=1)

    # regime Series for real_signal_fn stress check (tz-naive ET dates)
    sl_s = spy_s.sort_index()

    def _get_regime(day_ts: pd.Timestamp):
        d = pd.Timestamp(day_ts).normalize()
        if d.tzinfo is not None:
            d = d.tz_localize(None)
        try:
            v = sl_s.asof(d)
        except Exception:
            return None
        return str(v) if v is not None and not (isinstance(v, float) and pd.isna(v)) else None

    print(f"  swing_labels: {len(swing_labels)} SPY days")

    # ── 3. Pre-compute backtests (slippage=2) ────────────────────────────────
    print(f"\n[3] Running backtests (slippage={SLIPPAGE} tick/side)...")
    costs_2t = costs_for_basket(slippage_ticks=SLIPPAGE)
    swing_bt  = SwingTFEngine().backtest_basket(dfs, swing_labels, costs_2t)
    ncost_2t  = GIFC(point_value=c_nkd.point_value, tick=c_nkd.tick,
                     commission_rt=c_nkd.commission_rt, slippage_ticks_per_side=SLIPPAGE)
    nkd_bt    = backtest_swing_tf(ndf, nkd_labels, ncost_2t, ema_period=NKD_EMA,
                                   chandelier_atr_mult=NKD_MULT, max_hold_days=5, gap_fill=True)
    stress_bt = StressMidEngine().backtest_basket(dfs, swing_labels, costs_2t)

    n_sw = sum(len(v) for v in swing_bt.values())
    n_st = sum(len(v) for v in stress_bt.values())
    print(f"  swing={n_sw} trades | nkd={len(nkd_bt)} trades | stress={n_st} trades")

    # ── 4. ATR series and point values ───────────────────────────────────────
    atr_swing = {n: daily_atr_series(df) for n, df in dfs.items()}
    atr_nkd   = daily_atr_series(ndf)
    pv = {n: c.point_value for n, c in BASKET.items()}
    pv[NKD_INST] = c_nkd.point_value

    # ── 5. Assemble all_trades for reference replay (same as deploy_sim) ─────
    print("\n[5] Assembling all_trades for reference replay...")
    all_tr = []
    for inst, lst in swing_bt.items():
        for t in lst:
            all_tr.append(dict(inst=inst, cluster=CLUSTER_SWING,
                               entry=pd.Timestamp(t["day"]),
                               exit=pd.Timestamp(t["exit_day"]),
                               direction=t["direction"], pnl1=t["pnl"],
                               _atr=atr_swing[inst], _mult=ROSKA4_MULT, _pv=pv[inst]))
    for inst, lst in stress_bt.items():
        for t in lst:
            all_tr.append(dict(inst=inst, cluster=CLUSTER_STRESS,
                               entry=pd.Timestamp(t["day"]),
                               exit=pd.Timestamp(t["exit_day"]),
                               direction=t["direction"], pnl1=t["pnl"],
                               _atr=atr_swing[inst], _mult=ROSKA4_MULT, _pv=pv[inst]))
    for t in nkd_bt:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = (pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed)
        all_tr.append(dict(inst=NKD_INST, cluster=CLUSTER_NKD,
                           entry=ed, exit=xd,
                           direction=t["direction"], pnl1=t["pnl"],
                           _atr=atr_nkd, _mult=NKD_MULT, _pv=pv[NKD_INST]))

    contracts_by = {n: N_CONTRACTS for n in BASKET}
    contracts_by[NKD_INST] = N_CONTRACTS
    for t in all_tr:
        t["risk_sized"] = _real_risk(t["_atr"], t["_mult"], t["_pv"], t["entry"], N_CONTRACTS)
        t["pnl_sized"]  = t["pnl1"] * N_CONTRACTS

    # ── 6. Reference replay (deploy_sim.replay) ──────────────────────────────
    print("\n[6] Running reference replay (deploy_sim.replay)...")
    guard_ref  = MultiClusterGuard(account=ACCOUNT)
    ref_daily, ref_stats = deploy_replay(all_tr, ACCOUNT, guard_ref, contracts_by, CircuitBreaker)
    ref_net    = float(ref_daily.sum())
    print(f"  ref net P&L:  ${ref_net:>10,.2f}  (expect ~$52,936)")
    print(f"  ref taken:    {ref_stats['taken']}")
    print(f"  ref rejected: {ref_stats['rejected']}")
    print(f"  ref halted:   {ref_stats['halted']}")

    # ── 7. Build ledger + sorted timelines for real_signal_fn ────────────────
    print("\n[7] Building ledger + trade timelines...")
    # ledger: (inst, cluster, entry_day_norm) -> {exit, pnl_sized}
    ledger: dict = {}
    for t in all_tr:
        key = (t["inst"], t["cluster"], pd.Timestamp(t["entry"]).normalize())
        ledger[key] = {"exit": t["exit"], "pnl_sized": t["pnl_sized"]}

    swing_sorted = {inst: sorted(lst, key=lambda t: pd.Timestamp(t["day"]))
                    for inst, lst in swing_bt.items()}
    nkd_sorted   = sorted(nkd_bt, key=lambda t: pd.Timestamp(t["day"]))

    # stress lookup: (day_ts_norm, inst) -> trade  (ET dates only)
    stress_by_day: dict = {}
    for inst, lst in stress_bt.items():
        for t in lst:
            d = pd.Timestamp(t["day"]).normalize()
            stress_by_day[(d, inst)] = t

    # ── 8. Build real_signal_fn closure ──────────────────────────────────────
    def real_signal_fn(day, _bars, held):
        """Mirrors generate_today_signals using pre-computed trade timelines.
        Pre-computed to avoid O(n²) from calling desired_position() per day via _SWING_CACHE."""
        day_ts = pd.Timestamp(day).normalize()
        held_by_key = {(p.inst, p.cluster): p for p in held}
        force_entries: list = []
        desired: dict = {}

        # Swing TF: STATE model — desired_at gives the backtest's open position today
        for inst in dfs:
            key = (inst, CLUSTER_SWING)
            t = desired_at(swing_sorted[inst], day_ts)
            if t is not None:
                new_ed = pd.Timestamp(t["day"]).normalize()
                sig = {"direction": t["direction"],
                       "entry":     float(t.get("entry", 0.0)),
                       "stop":      float(t.get("stop", 0.0)),
                       "entry_day": new_ed}
                cur = held_by_key.get(key)
                # Same-direction re-entry: diff_desired_vs_held only checks direction,
                # not entry_day. A different entry_day means the old trade already closed
                # and a new one began — force-exit the old, force-enter the new.
                if (cur is not None
                        and cur.direction == sig["direction"]
                        and cur.entry_day.normalize() != new_ed):
                    desired[key] = None          # triggers exit of old pos in diff
                    force_entries.append((inst, CLUSTER_SWING, sig))
                elif cur is None:
                    # Only generate entry on the trade's actual entry day.
                    # If new_ed < day_ts the entry was already attempted (and rejected)
                    # on new_ed — the reference never retries, so we don't either.
                    if new_ed == day_ts:
                        desired[key] = sig
                    else:
                        desired[key] = None
                else:
                    desired[key] = sig  # direction flip or hold
            else:
                desired[key] = None

        # NKD: same STATE model, independent cluster
        nkd_key = (NKD_INST, CLUSTER_NKD)
        nt = desired_at(nkd_sorted, day_ts)
        if nt is not None:
            new_ed = pd.Timestamp(nt["day"]).normalize()
            nkd_sig = {"direction": nt["direction"],
                       "entry":     float(nt.get("entry", 0.0)),
                       "stop":      float(nt.get("stop", 0.0)),
                       "entry_day": new_ed}
            cur = held_by_key.get(nkd_key)
            if (cur is not None
                    and cur.direction == nkd_sig["direction"]
                    and cur.entry_day.normalize() != new_ed):
                desired[nkd_key] = None
                force_entries.append((NKD_INST, CLUSTER_NKD, nkd_sig))
            elif cur is None:
                if new_ed == day_ts:
                    desired[nkd_key] = nkd_sig
                else:
                    desired[nkd_key] = None
            else:
                desired[nkd_key] = nkd_sig  # direction flip or hold
        else:
            desired[nkd_key] = None

        # Real diff call (validates signal_layer core logic on each day)
        state_entries, exits = diff_desired_vs_held(desired, held)
        state_entries.extend(force_entries)

        # Build candidates + enrich from ledger (so pnl_sized reaches MockBroker)
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
                cand["exit"]       = ledger[lk]["exit"]
                cand["pnl_sized"]  = ledger[lk]["pnl_sized"]
            candidates.append(cand)

        # STRESS_MID: EVENT model — fires once at 10:15 on Stress days, exits same day
        today_regime = _get_regime(day_ts)
        if today_regime == "Stress":
            held_stress = {(p.inst, p.cluster) for p in held}
            for inst in dfs:
                if (inst, CLUSTER_STRESS) in held_stress:
                    continue
                st = stress_by_day.get((day_ts, inst))
                if st is not None:
                    av   = _asof_naive(atr_swing[inst], day_ts)
                    cand = to_candidate(inst, st["direction"],
                                        float(st.get("entry", 0.0)), 0.0,
                                        CLUSTER_STRESS,
                                        contracts_by.get(inst, N_CONTRACTS), pv[inst],
                                        daily_atr=av, mult=ROSKA4_MULT)
                    cand["exit"]      = day_ts
                    cand["pnl_sized"] = st["pnl"] * N_CONTRACTS
                    candidates.append(cand)

        return candidates, exits

    # ── 9. Run FuturesRunner + MockBroker + real_signal_fn ───────────────────
    print("\n[9] Running FuturesRunner + MockBroker + real_signal_fn...")
    broker = MockBroker(bars_by_inst={}, account=ACCOUNT)
    guard  = MultiClusterGuard(account=ACCOUNT)
    runner = FuturesRunner(broker=broker, guard=guard,
                           contracts_by_inst=contracts_by,
                           signal_fn=real_signal_fn,
                           breaker=CircuitBreaker(account=ACCOUNT))

    days_all = sorted({t["entry"] for t in all_tr} | {t["exit"] for t in all_tr})
    print(f"  Days: {len(days_all)} ({days_all[0].date()} → {days_all[-1].date()})")

    daily, stats = runner.run_history(days_all)
    runner_net = float(daily.sum()) if not daily.empty else 0.0

    # ── 10. Compare and report ────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("RESULTS")
    print("=" * 72)

    pnl_diff = runner_net - ref_net
    pnl_ok   = abs(pnl_diff) < 1.0
    print(f"\nP&L comparison:")
    print(f"  Reference (deploy_sim.replay):    ${ref_net:>10,.2f}")
    print(f"  Runner + real signal:              ${runner_net:>10,.2f}")
    print(f"  Diff:                              ${pnl_diff:>+10.2f}  "
          f"{'PASS' if pnl_ok else 'FAIL'}")

    clusters = [CLUSTER_SWING, CLUSTER_STRESS, CLUSTER_NKD]
    ref_tk = ref_stats["taken"];  run_tk = stats["taken"]
    ref_rj = ref_stats["rejected"]; run_rj = stats["rejected"]

    print(f"\nTaken per cluster:")
    taken_ok = True
    for c in clusters:
        rt, rn = ref_tk.get(c, 0), run_tk.get(c, 0)
        ok = rt == rn; taken_ok &= ok
        print(f"  {c:<20} ref={rt:>5}  runner={rn:>5}  {'PASS' if ok else 'FAIL'}")

    print(f"\nRejected per cluster:")
    rej_ok = True
    for c in clusters:
        rr, rn = ref_rj.get(c, 0), run_rj.get(c, 0)
        ok = rr == rn; rej_ok &= ok
        print(f"  {c:<20} ref={rr:>5}  runner={rn:>5}  {'PASS' if ok else 'FAIL'}")

    halt_ok = ref_stats["halted"] == stats["halted"]
    print(f"\nCircuit breaker halted:  ref={ref_stats['halted']}  "
          f"runner={stats['halted']}  {'PASS' if halt_ok else 'FAIL'}")

    opens    = sum(1 for f in broker.fills if f.action == "OPEN")
    closes   = sum(1 for f in broker.fills if f.action == "CLOSE")
    residual = broker.get_positions()
    beq      = broker.get_equity()
    lc_ok    = opens == closes and len(residual) == 0
    eq_ok    = abs(beq - (ACCOUNT + runner_net)) < 1.0

    # The runner's OWN ledger, which is what the circuit breaker reads. Checking only
    # broker equity left this unexamined, and it was wrong: decide_day added pnl_sized
    # and H4 then added the broker's delta for the same trade, so state.equity carried
    # twice the realised P&L. Nothing caught it because MockBroker's number — the one
    # tested above — was right all along.
    seq      = runner.state.equity
    seq_ok   = abs(seq - (ACCOUNT + runner_net)) < 1.0
    print(f"\nLifecycle:")
    print(f"  OPEN fills:     {opens}")
    print(f"  CLOSE fills:    {closes}  {'PASS' if opens == closes else 'FAIL (OPEN != CLOSE)'}")
    print(f"  Residual pos:   {len(residual)}  {'PASS' if len(residual) == 0 else 'FAIL'}")
    print(f"  Broker equity:  ${beq:,.2f}  (expected ${ACCOUNT + runner_net:,.2f})  "
          f"{'PASS' if eq_ok else 'FAIL'}")
    print(f"  Sleeve ledger:  ${seq:,.2f}  (expected ${ACCOUNT + runner_net:,.2f})  "
          f"{'PASS' if seq_ok else 'FAIL — this is what the breaker reads'}")

    all_pass = (pnl_ok and taken_ok and rej_ok and halt_ok and lc_ok and eq_ok
                and seq_ok)
    print(f"\n{'='*72}")
    print("OVERALL: " + (
        "ALL PASS — runner + MockBroker + real_signal_fn == deploy_sim fit_C"
        if all_pass else "SOME CHECKS FAILED — see above"))
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
