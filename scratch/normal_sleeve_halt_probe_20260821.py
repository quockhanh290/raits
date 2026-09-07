"""
scratch/normal_sleeve_halt_probe_20260821.py - follow-up to the Normal sleeve fill
audit. Scratch / read-only; no production code is modified.

The fill audit turned up something the fill question does not explain: in the
2018-2024 floor window the Ro-4-only Normal sleeve books 354 HALTED entries and
earns nothing at all in 2023 and 2024, while the same sleeve with NKD alongside
it halts zero times. This probe answers three things before any verdict is written:

 1. INDEPENDENT ANCHOR. The audit built 'R4 only' by dropping NKD trades from the
    assembled book. deploy_sim has its own --no-nkd path. Feed deploy_sim the SAME
    captured trades and let it do its own assembly, sizing, guard and breaker. If
    the two disagree the audit's subsetting is wrong and its R4-only row is void.
    (The trades are handed back rather than recomputed: re-running the engine a
    second time in one process builds a second set of ~120MB per-frame swing
    caches and the floor window dies on memory.)

 2. WHEN AND WHY THE BREAKER LATCHES. CircuitBreaker.status() returns HALT once
    drawdown from PEAK equity reaches 15%, and once new entries stop the equity
    curve stops moving, so peak never updates and the halt never lifts. Print the
    first halt day, the peak, and the equity at that moment, per variant.

 3. THE SLEEVE'S EDGE SEPARATED FROM THE BREAKER'S ACTION. Re-run every variant
    with the breaker off. The difference is what the halt costs, and it says
    whether NKD is supplying edge or merely supplying an equity cushion that
    keeps the shared account breaker from latching.

    python scratch/normal_sleeve_halt_probe_20260821.py --which floor vault2025 vault2026
"""
from __future__ import annotations

import argparse
import gc
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.harness as H
from scratch.normal_sleeve_fill_audit import (ACCOUNT, R4, _nkd_instrument, _real_risk,
                                              _round_turn, _slip_ticks, correct_trades,
                                              parse_ds, run_window)


def rss_mb() -> float:
    try:
        import psutil, os
        return psutil.Process(os.getpid()).memory_info().rss / 1e6
    except Exception:
        return float("nan")


def free_caches():
    import futures._validated_core as VC
    VC._SWING_CACHE.clear()
    H._CACHE.clear()
    gc.collect()


# ---------------------------------------------------------------------------
# replay with diagnostics -- a copy of deploy_sim.replay that also records when
# the breaker latched. Self-checked against the original below.
# ---------------------------------------------------------------------------
def replay_diag(all_trades, account, guard, contracts_by_inst, breaker_cls,
                use_breaker=True):
    from global_index.net_exposure_multi import entry_priority_key, Position

    breaker = breaker_cls(account=account) if (breaker_cls and use_breaker) else None
    days = sorted({t["entry"] for t in all_trades} | {t["exit"] for t in all_trades})
    by_entry = {}
    for t in all_trades:
        by_entry.setdefault(t["entry"], []).append(t)

    open_pos, realized = [], {}
    equity = account
    taken = {c: 0 for c in guard.clusters}
    rej = {c: 0 for c in guard.clusters}
    halt = 0
    cur_day = None
    diag = dict(first_halt_day=None, first_halt_peak=None, first_halt_equity=None,
                first_halt_level=None, halt_days=0,
                # The breaker trips on drawdown from PEAK EQUITY, not on drawdown as a
                # share of the starting account. Those are different denominators and
                # only the first one decides whether entries stop, so it is the one
                # that says how much headroom a book actually has.
                peak_rel_dd=0.0, peak_rel_dd_day=None, peak_at_worst=account)
    peak_seen = account

    def _mark(d):
        nonlocal peak_seen
        peak_seen = max(peak_seen, equity)
        if peak_seen > 0:
            dd = (peak_seen - equity) / peak_seen
            if dd > diag["peak_rel_dd"]:
                diag["peak_rel_dd"] = float(dd)
                diag["peak_rel_dd_day"] = str(pd.Timestamp(d).date())
                diag["peak_at_worst"] = float(peak_seen)

    for day in days:
        still = []
        for pos, t in open_pos:
            if t["exit"] == day:
                equity += t["pnl_sized"]
                realized[day] = realized.get(day, 0.0) + t["pnl_sized"]
            else:
                still.append((pos, t))
        open_pos = still
        _mark(day)

        allow = True
        if breaker is not None:
            if cur_day is None or day != cur_day:
                breaker.start_day(equity)
                cur_day = day
            breaker.update(equity)
            stt = breaker.status(equity)
            allow = stt.get("allow_new_entries", True)
            if not allow:
                diag["halt_days"] += 1
                if diag["first_halt_day"] is None:
                    diag["first_halt_day"] = str(pd.Timestamp(day).date())
                    diag["first_halt_peak"] = float(breaker.peak_equity)
                    diag["first_halt_equity"] = float(equity)
                    diag["first_halt_level"] = stt.get("level")

        for t in sorted(by_entry.get(day, []), key=entry_priority_key):
            if not allow:
                halt += 1
                continue
            n = contracts_by_inst.get(t["inst"], 1)
            pos = Position(t["inst"], t["direction"], n, t["risk_sized"], t["cluster"])
            ok, _ = guard.admits(pos, [p for p, _ in open_pos])
            if not ok:
                rej[t["cluster"]] += 1
                continue
            taken[t["cluster"]] += 1
            if t["exit"] == day:
                equity += t["pnl_sized"]
                realized[day] = realized.get(day, 0.0) + t["pnl_sized"]
                _mark(day)
            else:
                open_pos.append((pos, t))

    return (pd.Series(realized).sort_index(),
            dict(taken=taken, rejected=rej, halted=halt), diag)


def build_book(inst_trades, meta, n_contracts=1):
    all_tr = []
    for inst, lst in inst_trades.items():
        m = meta[inst]
        for t in lst:
            ed = pd.Timestamp(t["day"])
            xd = pd.Timestamp(t["exit_day"]) if t.get("exit_day") else ed
            if ed.tz is not None:
                ed = ed.tz_localize(None)
            if xd.tz is not None:
                xd = xd.tz_localize(None)
            all_tr.append(dict(inst=inst, cluster=m["cluster"], entry=ed, exit=xd,
                               direction=t["direction"], pnl1=t["pnl"],
                               atr=m["atr"], mult=m["mult"], pv=m["pv"], _atr_entry=ed))
    for t in all_tr:
        n = 1 if t["cluster"] == "global_nkd" else n_contracts
        t["risk_sized"] = _real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], n)
        t["pnl_sized"] = t["pnl1"] * n
    return all_tr


def run_variant(inst_trades, meta, use_breaker=True, account=ACCOUNT):
    import global_index.deploy_sim as DS
    from global_index.net_exposure_multi import MultiClusterGuard
    try:
        from futures.circuit_breaker import CircuitBreaker
    except Exception:
        CircuitBreaker = None
    book = build_book(inst_trades, meta)
    if not book:
        e = pd.Series(dtype=float)
        return e, dict(taken={}, rejected={}, halted=0), dict(), DS.metrics(e)
    contracts_by = {i: 1 for i in meta}
    sized, st, diag = replay_diag(book, account, MultiClusterGuard(account=account),
                                  contracts_by, CircuitBreaker, use_breaker=use_breaker)
    return sized, st, diag, DS.metrics(sized)


def selfcheck_replay(inst_trades, meta, account=ACCOUNT) -> bool:
    """replay_diag(use_breaker=True) must equal deploy_sim.replay exactly."""
    import global_index.deploy_sim as DS
    from global_index.net_exposure_multi import MultiClusterGuard
    from futures.circuit_breaker import CircuitBreaker
    book = build_book(inst_trades, meta)
    if not book:
        return False                      # empty book proves nothing -- fail loudly
    cb = {i: 1 for i in meta}
    a, sa = DS.replay(list(book), account, MultiClusterGuard(account=account), cb, CircuitBreaker)
    b, sb, _ = replay_diag(list(book), account, MultiClusterGuard(account=account), cb,
                           CircuitBreaker, use_breaker=True)
    return (len(a) > 0 and len(a) == len(b) and a.index.equals(b.index)
            and float((a - b).abs().max()) < 1e-9
            and sa["halted"] == sb["halted"] and sa["taken"] == sb["taken"])


# ---------------------------------------------------------------------------
# independent --no-nkd anchor: deploy_sim's OWN code path, fed the same trades
# ---------------------------------------------------------------------------
def deploy_sim_no_nkd(which: str, r4_trades: dict) -> dict:
    """Run deploy_sim --no-nkd end to end, but hand it the already-captured R4
    trade lists instead of recomputing them. Everything downstream -- risk$,
    sizer, MultiClusterGuard, CircuitBreaker, metrics -- is deploy_sim's own."""
    import futures._validated_core as VC
    import futures.stress_mid as SM
    import futures.swing_tf as ST
    import global_index.deploy_sim as DS

    old_swing_cls = ST.SwingTFEngine
    old_stress_cls = SM.StressMidEngine
    old_bt = VC.backtest_swing_tf

    class ReplayEngine:
        def backtest_basket(self, dfs, labels, costs, **kw):
            missing = set(dfs) - set(r4_trades)
            if missing:
                raise AssertionError("no captured trades for " + str(missing))
            return {n: list(r4_trades[n]) for n in dfs}

    class NoStressEngine:
        def backtest_basket(self, dfs, labels, costs):
            return {name: [] for name in dfs}

    def no_nkd_bt(df, labels, cost, **kw):
        return ([], None) if kw.get("return_open") else []

    ST.SwingTFEngine = ReplayEngine
    SM.StressMidEngine = NoStressEngine
    VC.backtest_swing_tf = no_nkd_bt

    argv = [x for x in H.ARGV[which] if x != "--include-stress"] + ["--no-nkd"]
    buf = io.StringIO()
    try:
        old_argv = sys.argv
        sys.argv = ["deploy_sim"] + argv
        try:
            with redirect_stdout(buf):
                DS.main()
        except SystemExit:
            pass
        finally:
            sys.argv = old_argv
    finally:
        ST.SwingTFEngine = old_swing_cls
        SM.StressMidEngine = old_stress_cls
        VC.backtest_swing_tf = old_bt

    out = buf.getvalue()
    m = parse_ds(out)
    for ln in out.splitlines():
        if "circuit-breaker halts" in ln:
            m["halts"] = int(ln.split(":")[-1].strip())
    m["_out"] = out
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--spy-csv", default="spy_daily_live.csv")
    ap.add_argument("--out", default="scratch/normal_sleeve_halt_probe_20260821.txt")
    ap.add_argument("--json-out", default="scratch/normal_sleeve_halt_probe_20260821.json")
    a = ap.parse_args()

    from futures._validated_core import daily_atr_series
    from futures.basket import BASKET
    from global_index import specs as gi_specs

    buf = io.StringIO()

    def emit(s=""):
        print(s, flush=True)
        buf.write(s + "\n")

    emit("=" * 118)
    emit("NORMAL SLEEVE - CIRCUIT-BREAKER / NKD-CUSHION PROBE   (scratch / research only)")
    emit("=" * 118)
    emit("Same Normal config as the fill audit. Question: is Ro4-only's floor-window")
    emit("collapse an edge fact or a latched account breaker, and is NKD supplying edge")
    emit("or an equity cushion that stops the shared breaker latching?")
    emit("")

    results = {}
    for which in a.which:
        emit("#" * 118)
        emit("WINDOW: " + which)
        emit("#" * 118)

        free_caches()
        cap = run_window(which, a.spy_csv)
        argv = cap["argv"]
        nkd = _nkd_instrument(argv)
        slip = _slip_ticks(argv)

        meta, booked, corrected = {}, {}, {}
        for name, d in cap["inst"].items():
            is_nkd = (name == nkd)
            c = gi_specs.SPECS[nkd] if is_nkd else BASKET[name]
            meta[name] = dict(cluster="global_nkd" if is_nkd else "roska4_swing",
                              atr=daily_atr_series(d["df"]), mult=2.5,
                              pv=float(c.point_value))
            booked[name] = d["booked"]
            corrected[name] = correct_trades(d["raw"], d["df"], float(c.point_value),
                                             _round_turn(c, is_nkd, slip))[0]
        # Persist the trade tables. Every later question about this sleeve -- year
        # splits, bootstrap, concentration, a different cap -- can then be answered
        # without a 20-minute engine replay, and answered on the SAME trades these
        # numbers came from rather than on a fresh run that may not be identical.
        dump = Path("scratch/normal_sleeve_trades_{}_20260821.json".format(which))
        dump.write_text(json.dumps(
            {"argv": argv, "nkd_instrument": nkd, "slippage_ticks": slip,
             "booked": {k: [{kk: str(vv) for kk, vv in t.items()} for t in v]
                        for k, v in booked.items()},
             "corrected": {k: [{kk: str(vv) for kk, vv in t.items()} for t in v]
                           for k, v in corrected.items()}},
            indent=1), encoding="utf-8")
        emit("  trade tables written to {}".format(dump))

        # everything needed is extracted; release the frames and their swing caches
        # before deploy_sim loads its own set (floor otherwise dies on memory).
        cap["inst"] = None
        cap["raw"] = None
        cap["booked"] = None
        cap["r4_dfs"] = None
        del cap
        free_caches()
        emit("  rss after releasing frames: {:.0f} MB".format(rss_mb()))

        r4_t = {n: booked[n] for n in R4 if n in booked}
        r4_m = {n: meta[n] for n in R4 if n in meta}
        both_t = dict(r4_t); both_t[nkd] = corrected[nkd]
        both_m = dict(r4_m); both_m[nkd] = meta[nkd]
        nkd_t = {nkd: corrected[nkd]}
        nkd_m = {nkd: meta[nkd]}

        ok1 = selfcheck_replay(both_t, both_m)
        ok2 = selfcheck_replay(r4_t, r4_m)
        emit("  [SELF-CHECK] replay_diag == deploy_sim.replay : {}".format(
            "PASS" if (ok1 and ok2) else "FAIL - stop, numbers below are void"))

        anchor = deploy_sim_no_nkd(which, r4_t)
        free_caches()
        s_r4, st_r4, dg_r4, m_r4 = run_variant(r4_t, r4_m, use_breaker=True)
        ok3 = (abs(m_r4["pnl"] - anchor.get("net", -1e9)) < 1.0
               and abs(m_r4["maxdd"] - anchor.get("maxdd", -1e9)) < 1.0
               and st_r4["halted"] == anchor.get("halts", -1))
        emit("  [SELF-CHECK] 'R4 only' subsetting == deploy_sim --no-nkd : "
             "net ${:,.0f} vs ${:,.0f}, MaxDD ${:,.0f} vs ${:,.0f}, halts {} vs {} -> {}".format(
                 m_r4["pnl"], anchor.get("net", 0), m_r4["maxdd"], anchor.get("maxdd", 0),
                 st_r4["halted"], anchor.get("halts", -1), "PASS" if ok3 else "FAIL"))
        emit("")

        rows = []
        for label, tr, mt in (("R4 only", r4_t, r4_m),
                              ("NKD only (corrected)", nkd_t, nkd_m),
                              ("R4 + NKD (corrected)", both_t, both_m)):
            for bk in (True, False):
                s, st, dg, m = run_variant(tr, mt, use_breaker=bk)
                yrs = (max((s.index[-1] - s.index[0]).days / 365.25, 0.1) if len(s) else 1.0)
                rows.append(dict(label=label, breaker="ON" if bk else "OFF",
                                 net=m["pnl"], pf=m["pf"], sharpe=m["sharpe"],
                                 calmar=m["calmar"], maxdd=m["maxdd"],
                                 maxdd_pct=m["maxdd"] / ACCOUNT,
                                 ret_yr=m["pnl"] / ACCOUNT / yrs,
                                 taken=sum(st["taken"].values()),
                                 rejected=sum(st["rejected"].values()),
                                 halted=st["halted"], **dg,
                                 yearly={int(y): float(g.sum())
                                         for y, g in s.groupby(s.index.year)} if len(s) else {}))

        emit("  {:<22} {:>8} {:>10} {:>6} {:>7} {:>7} {:>9} {:>8} {:>7} {:>6} {:>5} {:>5}".format(
            "variant", "breaker", "net$", "PF", "Sharpe", "Calmar", "MaxDD$", "MaxDD%",
            "ret/yr", "taken", "rej", "halt"))
        for r in rows:
            emit("  {label:<22} {breaker:>8} {net:>10,.0f} {pf:>6.2f} {sharpe:>7.2f} "
                 "{calmar:>7.2f} {maxdd:>9,.0f} {maxdd_pct:>8.1%} {ret_yr:>7.1%} "
                 "{taken:>6} {rejected:>5} {halted:>5}".format(**r))
        emit("")
        emit("  HEADROOM TO THE 15% TRIP (drawdown measured from PEAK EQUITY, the breaker's own rule)")
        emit("  {:<22} {:>8} {:>12} {:>12} {:>12} {:>12}".format(
            "variant", "breaker", "worst dd", "on", "peak then", "headroom"))
        for r in rows:
            emit("  {:<22} {:>8} {:>11.1%} {:>12} {:>12,.0f} {:>11.1f}pp".format(
                r["label"], r["breaker"], r["peak_rel_dd"], str(r["peak_rel_dd_day"]),
                r["peak_at_worst"], 100 * (0.15 - r["peak_rel_dd"])))
        emit("")
        emit("  BREAKER LATCH DETAIL (entries blocked once drawdown-from-peak reaches 15%)")
        for r in rows:
            if r["breaker"] != "ON":
                continue
            if r.get("first_halt_day"):
                emit("    {:<22} first block {}  level {}  peak ${:,.0f}  equity ${:,.0f}  "
                     "dd {:.1%}  blocked on {} days, {} entries".format(
                         r["label"], r["first_halt_day"], r["first_halt_level"],
                         r["first_halt_peak"], r["first_halt_equity"],
                         (r["first_halt_peak"] - r["first_halt_equity"]) / r["first_halt_peak"],
                         r["halt_days"], r["halted"]))
            else:
                emit("    {:<22} never blocked".format(r["label"]))
        emit("")
        years = sorted({y for r in rows for y in r["yearly"]})
        emit("  YEARLY NET$")
        emit("  {:<22} {:>8} {}".format("variant", "breaker",
                                        " ".join("{:>10}".format(y) for y in years)))
        for r in rows:
            emit("  {:<22} {:>8} {}".format(r["label"], r["breaker"], " ".join(
                "{:>10,.0f}".format(r["yearly"].get(y, 0.0)) for y in years)))
        emit("")

        results[which] = dict(rows=rows,
                              anchor_no_nkd={k: v for k, v in anchor.items() if k != "_out"},
                              selfcheck_replay=bool(ok1 and ok2), selfcheck_subset=bool(ok3))
        free_caches()

    Path(a.out).write_text(buf.getvalue(), encoding="utf-8")
    Path(a.json_out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print("\nwrote " + a.out + " and " + a.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
