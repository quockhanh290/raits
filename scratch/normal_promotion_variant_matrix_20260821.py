"""
scratch/normal_promotion_variant_matrix_20260821.py - full variant x cap x window
matrix for the Normal promotion audit, built from the regenerated trade dumps.
Scratch / read-only; no engine re-run, no production file touched.

Adds the two things the regeneration pass does not print:

  * the sleeve-level post-hoc row (`R4 posthoc-deleted only`), so regenerated and
    deleted books can be compared at the sleeve level and not only combined;
  * headroom to the 15% circuit-breaker trip, measured the way the breaker measures
    it - drawdown from PEAK EQUITY, not from the starting account. MaxDD% quoted
    against a $50,000 base and the level that actually stops trading are different
    numbers, and only the second one decides whether the book keeps running.

    python scratch/normal_promotion_variant_matrix_20260821.py
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from scratch.normal_promotion_filter_lib_20260821 import R4ContextFilter
from scratch.normal_promotion_regen_audit_20260821 import CAPS
from scratch.normal_sleeve_fill_audit import ACCOUNT, R4, _real_risk
from scratch.normal_sleeve_halt_probe_20260821 import replay_diag

DUMP = "scratch/normal_promotion_trades_{}_20260821.json"
WINDOWS = ["floor", "vault2025", "vault2026"]


def argv_val(argv, key, default=None):
    return argv[argv.index(key) + 1] if key in argv else default


def load_frames(raw: dict) -> dict:
    from futures._validated_core import load_parquet
    from futures.basket import BASKET, data_filename
    from global_index import specs as gi_specs
    from global_index._core import load_parquet as gi_load

    argv = raw["argv"]
    dd = Path(argv_val(argv, "--data-dir"))
    start, end = argv_val(argv, "--start"), argv_val(argv, "--end")

    def clip(df):
        if start:
            df = df[df.index >= pd.Timestamp(start).tz_localize(df.index.tz)]
        if end:
            df = df[df.index <= pd.Timestamp(end).tz_localize(df.index.tz)]
        return df

    frames = {n: clip(load_parquet(str(dd / data_filename(BASKET[n])))) for n in R4}
    nkd = raw["nkd_instrument"]
    c = gi_specs.SPECS[nkd]
    ndf = gi_load(argv_val(argv, "--nkd-parquet"))
    ndf.index = ndf.index.tz_convert(c.session_tz)
    frames[nkd] = clip(ndf)
    return frames


def build_meta(raw: dict, frames: dict) -> dict:
    from futures._validated_core import daily_atr_series
    from futures.basket import BASKET
    from global_index import specs as gi_specs
    nkd = raw["nkd_instrument"]
    meta = {}
    for n, df in frames.items():
        is_nkd = (n == nkd)
        c = gi_specs.SPECS[nkd] if is_nkd else BASKET[n]
        meta[n] = dict(cluster="global_nkd" if is_nkd else "roska4_swing",
                       atr=daily_atr_series(df), mult=2.5, pv=float(c.point_value))
    return meta


def to_trades(rows: list) -> list:
    """Dump stores every field as str; restore only what the replay needs."""
    out = []
    for t in rows:
        d = dict(t)
        d["pnl"] = float(d["pnl"])
        d["entry"] = float(d["entry"])
        d["exit"] = float(d["exit"])
        out.append(d)
    return out


def build_book(inst_trades: dict, meta: dict) -> list:
    book = []
    for inst, lst in inst_trades.items():
        m = meta[inst]
        for t in lst:
            ed = pd.Timestamp(t["day"])
            xd = pd.Timestamp(t["exit_day"]) if t.get("exit_day") else ed
            if ed.tz is not None:
                ed = ed.tz_localize(None)
            if xd.tz is not None:
                xd = xd.tz_localize(None)
            book.append(dict(inst=inst, cluster=m["cluster"], entry=ed, exit=xd,
                             direction=t["direction"], pnl1=float(t["pnl"]),
                             pnl_sized=float(t["pnl"]),
                             risk_sized=_real_risk(m["atr"], m["mult"], m["pv"], ed, 1)))
    return book


def run(inst_trades: dict, meta: dict, cap_name: str) -> dict:
    import global_index.deploy_sim as DS
    from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
    from futures.circuit_breaker import CircuitBreaker
    spec = CAPS[cap_name]
    clusters = {"roska4_swing": ClusterBudget("roska4_swing", *spec["roska4_swing"]),
                "roska4_stress": ClusterBudget("roska4_stress", 0.025, None),
                "global_nkd": ClusterBudget("global_nkd", *spec["global_nkd"])}
    book = build_book(inst_trades, meta)
    if not book:
        return None
    guard = MultiClusterGuard(clusters=clusters, account=ACCOUNT)
    sized, st, diag = replay_diag(book, ACCOUNT, guard, {i: 1 for i in meta},
                                  CircuitBreaker, use_breaker=True)
    m = DS.metrics(sized)
    yrs = max((sized.index[-1] - sized.index[0]).days / 365.25, 0.1) if len(sized) else 1.0
    return dict(net=m["pnl"], pf=m["pf"], sharpe=m["sharpe"], calmar=m["calmar"],
                maxdd=m["maxdd"], maxdd_pct=m["maxdd"] / ACCOUNT,
                ret_yr=m["pnl"] / ACCOUNT / yrs, trades=len(book),
                taken=sum(st["taken"].values()), rejected=sum(st["rejected"].values()),
                halted=st["halted"], halt_days=diag["halt_days"],
                peak_rel_dd=diag["peak_rel_dd"], peak_rel_day=diag["peak_rel_dd_day"],
                headroom_pp=100 * (0.15 - diag["peak_rel_dd"]),
                yearly={int(y): float(g.sum()) for y, g in sized.groupby(sized.index.year)}
                if len(sized) else {})


def selfcheck(inst_trades: dict, meta: dict) -> bool:
    """replay_diag must equal deploy_sim.replay on the default cap. An empty book
    proves nothing, so an empty book fails."""
    import global_index.deploy_sim as DS
    from global_index.net_exposure_multi import MultiClusterGuard
    from futures.circuit_breaker import CircuitBreaker
    book = build_book(inst_trades, meta)
    if not book:
        return False
    cb = {i: 1 for i in meta}
    a, sa = DS.replay(list(book), ACCOUNT, MultiClusterGuard(account=ACCOUNT), cb, CircuitBreaker)
    b, sb, _ = replay_diag(list(book), ACCOUNT, MultiClusterGuard(account=ACCOUNT), cb,
                           CircuitBreaker, use_breaker=True)
    return (len(a) > 0 and a.index.equals(b.index) and float((a - b).abs().max()) < 1e-9
            and sa["halted"] == sb["halted"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="scratch/normal_promotion_variant_matrix_20260821.txt")
    ap.add_argument("--json-out", default="scratch/normal_promotion_variant_matrix_20260821.json")
    a = ap.parse_args()

    report, results = [], {}

    def emit(s=""):
        print(s, flush=True)
        report.append(s)

    emit("=" * 128)
    emit("NORMAL PROMOTION - VARIANT x CAP MATRIX   (scratch / read-only, built from regenerated dumps)")
    emit("=" * 128)
    emit("headroom = percentage points left before the 15% circuit-breaker trip, measured on")
    emit("drawdown from PEAK EQUITY (the breaker's own rule), not on MaxDD as a share of $50,000.")
    emit("")

    for w in WINDOWS:
        p = Path(DUMP.format(w))
        if not p.exists():
            emit("WINDOW {}: dump missing, run the regeneration audit first".format(w))
            continue
        raw = json.loads(p.read_text(encoding="utf-8"))
        nkd = raw["nkd_instrument"]
        frames = load_frames(raw)
        meta = build_meta(raw, frames)

        r4_raw = {n: to_trades(raw["raw"][n]) for n in R4}
        r4_flt = {n: to_trades(raw["filtered"][n]) for n in R4}
        r4_prev = {n: to_trades(raw["filtered_prevbar"][n]) for n in R4}
        nkd_t = {nkd: to_trades(raw["raw"][nkd])}

        r4_post = {}
        post_stats = {}
        for n in R4:
            f = R4ContextFilter(frames[n])
            r4_post[n] = [t for t in r4_raw[n]
                          if t.get("entry_time") not in (None, "None")
                          and f.allow(pd.Timestamp(t["entry_time"]))]
            post_stats[n] = f.stats()
        for k in frames:
            frames[k] = None
        del frames
        gc.collect()

        ok = selfcheck({**r4_raw, **nkd_t}, meta)
        emit("#" * 128)
        emit("WINDOW: " + w)
        emit("#" * 128)
        emit("  [SELF-CHECK] replay == deploy_sim.replay on the default cap: {}".format(
            "PASS" if ok else "FAIL - numbers below are void"))
        emit("")

        variants = [
            ("R4 raw only", r4_raw),
            ("R4 raw + NKD (baseline)", {**r4_raw, **nkd_t}),
            ("R4 posthoc-deleted only", r4_post),
            ("R4 posthoc-deleted + NKD", {**r4_post, **nkd_t}),
            ("R4 filtered only", r4_flt),
            ("R4 filtered + NKD", {**r4_flt, **nkd_t}),
            ("R4 filtered(prevbar) only", r4_prev),
            ("R4 filtered(prevbar) + NKD", {**r4_prev, **nkd_t}),
            ("NKD only", nkd_t),
        ]
        emit("  {:<30} {:<10} {:>10} {:>6} {:>7} {:>7} {:>9} {:>8} {:>7} {:>6} {:>5} {:>5} {:>9}".format(
            "variant", "cap", "net$", "PF", "Sharpe", "Calmar", "MaxDD$", "MaxDD%",
            "trades", "taken", "rej", "halt", "headroom"))
        rows = []
        for label, tr in variants:
            for cap_name in ("current", "strict025"):
                r = run(tr, meta, cap_name)
                if r is None:
                    continue
                r.update(variant=label, cap=cap_name, window=w)
                rows.append(r)
                emit("  {variant:<30} {cap:<10} {net:>10,.0f} {pf:>6.2f} {sharpe:>7.2f} "
                     "{calmar:>7.2f} {maxdd:>9,.0f} {maxdd_pct:>8.1%} {trades:>7} {taken:>6} "
                     "{rejected:>5} {halted:>5} {headroom_pp:>8.1f}p".format(**r))
        emit("")
        emit("  post-hoc gate action on the RAW book (for comparison with the decision-boundary run)")
        emit("  {:<6} {:>8} {:>9} {:>10} {:>9} {:>12}".format(
            "inst", "seen", "passed", "blk range", "blk vol", "blk missing"))
        for n in R4:
            s = post_stats[n]
            emit("  {:<6} {:>8} {:>9} {:>10} {:>9} {:>12}".format(
                n, s["seen"], s["passed"], s["blocked_range"], s["blocked_vol"],
                s["blocked_missing"]))
        emit("")
        results[w] = dict(selfcheck=bool(ok), rows=rows, posthoc_gate=post_stats)
        gc.collect()

    emit("=" * 128)
    emit("CROSS-WINDOW, current cap")
    emit("=" * 128)
    emit("  {:<30} {:>10} {:>7} {:>9} | {:>10} {:>7} {:>9} | {:>10} {:>7} {:>9}".format(
        "variant", "floor$", "Calmar", "headroom", "2025$", "Calmar", "headroom",
        "2026$", "Calmar", "headroom"))
    labels = [v[0] for v in (("R4 raw + NKD (baseline)",), ("R4 posthoc-deleted + NKD",),
                             ("R4 filtered + NKD",), ("R4 filtered(prevbar) + NKD",),
                             ("R4 filtered only",), ("R4 posthoc-deleted only",),
                             ("NKD only",))]
    for lab in labels:
        cells = []
        for w in WINDOWS:
            if w not in results:
                cells.append(None); continue
            r = next((x for x in results[w]["rows"]
                      if x["variant"] == lab and x["cap"] == "current"), None)
            cells.append(r)
        if any(c is None for c in cells):
            continue
        emit("  {:<30} {:>10,.0f} {:>7.2f} {:>8.1f}p | {:>10,.0f} {:>7.2f} {:>8.1f}p | "
             "{:>10,.0f} {:>7.2f} {:>8.1f}p".format(
                 lab, cells[0]["net"], cells[0]["calmar"], cells[0]["headroom_pp"],
                 cells[1]["net"], cells[1]["calmar"], cells[1]["headroom_pp"],
                 cells[2]["net"], cells[2]["calmar"], cells[2]["headroom_pp"]))

    Path(a.out).write_text("\n".join(report) + "\n", encoding="utf-8")
    Path(a.json_out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print("\nwrote " + a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
