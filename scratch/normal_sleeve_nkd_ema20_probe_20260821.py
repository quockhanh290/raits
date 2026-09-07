"""
Scratch-only recheck of the suspicious nkd_ema20 row.

Runs the same capture/audit path as normal_sleeve_fill_audit, but appends
--nkd-ema 20 to deploy_sim argv. Reports corrected NKD fill, breaker on/off,
halt days, blocked trades, lost-trade PnL, yearly net, and headroom.
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
from scratch.normal_sleeve_fill_audit import (
    ACCOUNT,
    R4,
    _nkd_instrument,
    _real_risk,
    _round_turn,
    _slip_ticks,
    audit_trades,
    correct_trades,
    run_window,
)


def free_caches():
    import futures._validated_core as VC
    VC._SWING_CACHE.clear()
    H._CACHE.clear()
    gc.collect()


def metrics(daily: pd.Series) -> dict:
    import global_index.deploy_sim as DS
    return DS.metrics(daily)


def build_book(inst_trades, meta):
    out = []
    for inst, lst in inst_trades.items():
        m = meta[inst]
        for t in lst:
            ed = pd.Timestamp(t["day"])
            xd = pd.Timestamp(t["exit_day"]) if t.get("exit_day") else ed
            if ed.tz is not None:
                ed = ed.tz_localize(None)
            if xd.tz is not None:
                xd = xd.tz_localize(None)
            out.append(dict(inst=inst, cluster=m["cluster"], entry=ed, exit=xd,
                            direction=t["direction"], pnl1=float(t["pnl"]),
                            atr=m["atr"], mult=m["mult"], pv=m["pv"], _atr_entry=ed))
    for t in out:
        n = 1
        t["risk_sized"] = _real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], n)
        t["pnl_sized"] = t["pnl1"] * n
    return out


def replay_diag(book, use_breaker=True):
    from global_index.net_exposure_multi import MultiClusterGuard, Position, entry_priority_key
    try:
        from futures.circuit_breaker import CircuitBreaker
    except Exception:
        CircuitBreaker = None

    guard = MultiClusterGuard(account=ACCOUNT)
    breaker = CircuitBreaker(account=ACCOUNT) if (CircuitBreaker and use_breaker) else None
    days = sorted({t["entry"] for t in book} | {t["exit"] for t in book})
    by_entry = {}
    for t in book:
        by_entry.setdefault(t["entry"], []).append(t)

    open_pos = []
    realized = {}
    equity = ACCOUNT
    taken = {c: 0 for c in guard.clusters}
    rejected = {c: 0 for c in guard.clusters}
    halted = 0
    halt_days = 0
    lost_pnl = 0.0
    cur_day = None
    first = None
    peak_seen = ACCOUNT
    peak_rel_dd = 0.0
    peak_rel_day = None
    peak_at_worst = ACCOUNT

    for day in days:
        still = []
        for pos, t in open_pos:
            if t["exit"] == day:
                equity += t["pnl_sized"]
                realized[day] = realized.get(day, 0.0) + t["pnl_sized"]
            else:
                still.append((pos, t))
        open_pos = still
        peak_seen = max(peak_seen, equity)
        dd = (peak_seen - equity) / peak_seen if peak_seen > 0 else 0.0
        if dd > peak_rel_dd:
            peak_rel_dd = float(dd)
            peak_rel_day = str(pd.Timestamp(day).date())
            peak_at_worst = float(peak_seen)

        allow = True
        if breaker is not None:
            if cur_day is None or day != cur_day:
                breaker.start_day(equity)
                cur_day = day
            breaker.update(equity)
            stt = breaker.status(equity)
            allow = stt.get("allow_new_entries", True)
            if not allow:
                halt_days += 1
                if first is None:
                    first = dict(day=str(pd.Timestamp(day).date()),
                                 peak=float(breaker.peak_equity),
                                 equity=float(equity),
                                 dd=float(stt["drawdown_pct"]),
                                 level=stt["level"])

        for t in sorted(by_entry.get(day, []), key=entry_priority_key):
            if not allow:
                halted += 1
                lost_pnl += t["pnl_sized"]
                continue
            pos = Position(t["inst"], t["direction"], 1, t["risk_sized"], t["cluster"])
            ok, _ = guard.admits(pos, [p for p, _ in open_pos])
            if not ok:
                rejected[t["cluster"]] += 1
                continue
            taken[t["cluster"]] += 1
            if t["exit"] == day:
                equity += t["pnl_sized"]
                realized[day] = realized.get(day, 0.0) + t["pnl_sized"]
            else:
                open_pos.append((pos, t))

    daily = pd.Series(realized).sort_index()
    m = metrics(daily)
    yrs = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1) if len(daily) else 1.0
    return dict(net=m["pnl"], pf=m["pf"], sharpe=m["sharpe"], calmar=m["calmar"],
                maxdd=m["maxdd"], maxdd_pct=m["maxdd"] / ACCOUNT,
                ret_yr=m["pnl"] / ACCOUNT / yrs,
                trade_count=len(book), taken=sum(taken.values()),
                rejected=sum(rejected.values()), halted_days=halt_days,
                blocked_trades=halted, lost_trade_pnl=lost_pnl,
                peak_rel_dd=peak_rel_dd, peak_rel_day=peak_rel_day,
                safety_margin_15=0.15 - peak_rel_dd, first_halt=first,
                yearly={int(y): float(g.sum()) for y, g in daily.groupby(daily.index.year)} if len(daily) else {})


def capture_ema20(which: str, spy_csv: str) -> dict:
    old = list(H.ARGV[which])
    H.ARGV[which] = old + ["--nkd-ema", "20"]
    try:
        return run_window(which, spy_csv)
    finally:
        H.ARGV[which] = old


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--spy-csv", default="spy_daily_live.csv")
    ap.add_argument("--out", default="scratch/normal_sleeve_nkd_ema20_probe_20260821.txt")
    ap.add_argument("--json-out", default="scratch/normal_sleeve_nkd_ema20_probe_20260821.json")
    args = ap.parse_args()

    from futures._validated_core import daily_atr_series
    from futures.basket import BASKET
    from global_index import specs as gi_specs

    report = []
    results = {}

    def emit(s=""):
        print(s, flush=True)
        report.append(s)

    emit("=" * 112)
    emit("NORMAL SLEEVE - NKD EMA20 RECHECK (scratch / research only)")
    emit("=" * 112)
    emit("Config: base Normal sleeve, but --nkd-ema 20. NKD fills corrected by conservative path law.")
    emit("")

    for which in args.which:
        free_caches()
        cap = capture_ema20(which, args.spy_csv)
        argv = cap["argv"]
        nkd = _nkd_instrument(argv)
        slip = _slip_ticks(argv)
        meta, corrected, audits = {}, {}, {}
        corr_stat = {}
        for name, d in cap["inst"].items():
            is_nkd = name == nkd
            c = gi_specs.SPECS[nkd] if is_nkd else BASKET[name]
            meta[name] = dict(cluster="global_nkd" if is_nkd else "roska4_swing",
                              atr=daily_atr_series(d["df"]), mult=2.5,
                              pv=float(c.point_value))
            rt = _round_turn(c, is_nkd, slip)
            ct, cn, ctot = correct_trades(d["raw"], d["df"], float(c.point_value), rt)
            corrected[name] = ct
            corr_stat[name] = dict(n=cn, dollars=ctot)
            audits[name] = audit_trades(name, ct, d["df"])

        books = {
            "R4 only": ({n: corrected[n] for n in R4 if n in corrected},
                        {n: meta[n] for n in R4 if n in meta}),
            "NKD ema20 corrected": ({nkd: corrected[nkd]}, {nkd: meta[nkd]}),
            "R4 + NKD ema20 corrected": ({**{n: corrected[n] for n in R4 if n in corrected},
                                           nkd: corrected[nkd]}, meta),
        }

        emit("#" * 112)
        emit("WINDOW: " + which)
        emit("#" * 112)
        emit("  deploy_sim original anchor (before NKD path correction): net ${:,.0f} PF {:.2f} Sharpe {:.2f} Calmar {:.2f} MaxDD ${:,.0f}".format(
            cap["ds_metrics"].get("net", 0.0), cap["ds_metrics"].get("pf", 0.0),
            cap["ds_metrics"].get("sharpe", 0.0), cap["ds_metrics"].get("calmar", 0.0),
            cap["ds_metrics"].get("maxdd", 0.0)))
        emit("  corrected fill repricing: " + ", ".join(
            f"{k} {v['n']} / ${v['dollars']:.2f}" for k, v in corr_stat.items() if v["n"]))
        if not any(v["n"] for v in corr_stat.values()):
            emit("  corrected fill repricing: none")
        emit("")
        rows = []
        for label, (tr, mt) in books.items():
            book = build_book(tr, mt)
            for use_breaker in (True, False):
                r = replay_diag(book, use_breaker=use_breaker)
                r.update(variant=label, breaker="ON" if use_breaker else "OFF")
                rows.append(r)
        emit("  {:<27} {:>7} {:>10} {:>5} {:>7} {:>7} {:>8} {:>8} {:>7} {:>6} {:>7} {:>10} {:>9}".format(
            "variant", "breaker", "net$", "PF", "Sharpe", "Calmar", "MaxDD%", "ret/yr",
            "taken", "haltD", "block", "lost pnl", "15% room"))
        for r in rows:
            emit("  {variant:<27} {breaker:>7} {net:>10,.0f} {pf:>5.2f} {sharpe:>7.2f} {calmar:>7.2f} {maxdd_pct:>8.1%} {ret_yr:>8.1%} {taken:>7} {halted_days:>6} {blocked_trades:>7} {lost_trade_pnl:>10,.0f} {safety_margin_15:>8.1%}".format(**r))
        emit("")
        years = sorted({y for r in rows for y in r["yearly"]})
        emit("  YEARLY NET$")
        emit("  {:<27} {:>7} {}".format("variant", "breaker", " ".join(f"{y:>9}" for y in years)))
        for r in rows:
            emit("  {:<27} {:>7} {}".format(r["variant"], r["breaker"],
                                            " ".join("{:>9,.0f}".format(r["yearly"].get(y, 0.0)) for y in years)))
        emit("")
        results[which] = dict(rows=rows, corrected_repricing=corr_stat,
                              audit_corrected={k: {kk: vv for kk, vv in v.items() if kk != "samples"}
                                               for k, v in audits.items()})
        cap["inst"] = None
        free_caches()

    Path(args.out).write_text("\n".join(report) + "\n", encoding="utf-8")
    Path(args.json_out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"\nwrote {args.out} and {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
