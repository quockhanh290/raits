"""
scratch/normal_promotion_regen_audit_20260821.py - regenerate the Normal candidate
from the SIGNAL PATH and audit it. Scratch / read-only; no production file is
written or modified.

Why regenerate instead of filtering the saved trade tables
----------------------------------------------------------
The existing context probes take the corrected trade JSON and delete the rows the
filter rejects. That is not the strategy with a filter on it. Inside the engine a
rejected signal does not empty the day - the 14:00-15:55 scan CONTINUES and may
enter on a later bar - and it also leaves the book flat, which changes what the
following sessions can do, because an open position blocks a new entry. Deleting
rows models neither effect. This script installs the filter where the decision is
actually made, in `TrendFollowStrategy.generate_signal`, and lets the engine run.

Both are produced here so the difference can be measured rather than assumed.

Engine gap-through fix
----------------------
Production does NOT currently contain the fix (`_validated_core.py` still requires
`bool(isg[i])`, i.e. a >15-minute time break, before a stop may fill at the bar
open). The corrected baseline this candidate is measured against was produced while
production was temporarily patched, and that patch has been reverted. So the fix is
re-applied here scratch-side, by forcing every bar's gap flag on. The engine's own
`gapped` test still requires the open to be on the adverse side of the stop, so this
cannot turn a favourable open into a gap fill; the equivalence was proven
trade-for-trade in scratch/nsfa_correction_equivalence_20260821.py.

    python scratch/normal_promotion_regen_audit_20260821.py --which floor vault2025 vault2026
"""
from __future__ import annotations

import argparse
import gc
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.harness as H
from scratch.harness import ARM_LIVE, Cfg, patched_engine
from scratch.directional_market_filter_probe import allowed_short_days, feature_frame
from scratch.normal_promotion_filter_lib_20260821 import (FLOOR_RANGE_P90, VOL_LE,
                                                          R4ContextFilter, bars_5m)
from scratch.normal_sleeve_fill_audit import (ACCOUNT, R4, _nkd_instrument, _real_risk,
                                              _round_turn, _slip_ticks, audit_trades,
                                              bar_lookup, parse_ds)

PRICE_EPS = 0.011

# Corrected baseline this candidate must be measured against (engine-fix path,
# current cap). Anchors: deploy_sim's own printed numbers.
BASELINE = {"floor": 33176.0, "vault2025": 6857.0, "vault2026": 6743.0}

CAPS = {
    "current":   {"roska4_swing": (0.050, 0.044), "global_nkd": (0.060, 0.060)},
    "strict025": {"roska4_swing": (0.025, 0.025), "global_nkd": (0.060, 0.060)},
}

# module-global set by the capturing wrapper right before each engine call
_ACTIVE_FILTER = None


def free_caches():
    import futures._validated_core as VC
    VC._SWING_CACHE.clear()
    H._CACHE.clear()
    gc.collect()


def force_all_bars_gappable():
    """Engine-level gap-through fix, applied scratch-side."""
    import futures._validated_core as VC
    orig = VC._swing_cache

    def patched(df, datr=None):
        c = orig(df, datr)
        if not c.get("_all_gap"):
            for day, (high, low, opn, isg) in list(c["hl"].items()):
                c["hl"][day] = (high, low, opn, np.ones(len(isg), dtype=bool))
            c["_all_gap"] = True
        return c

    VC._swing_cache = patched
    return orig


# ---------------------------------------------------------------------------
# one engine run
# ---------------------------------------------------------------------------
def run_engine(which: str, spy_csv: str, *, apply_filter: bool,
               vol_feature: str = "rvol_slot20", vol_max: float = VOL_LE,
               range_max: float = FLOOR_RANGE_P90) -> dict:
    global _ACTIVE_FILTER
    import futures._validated_core as VC
    import futures.stress_mid as SM
    import futures.swing_tf as ST
    import global_index.deploy_sim as DS
    import raits.strategies.trend_follow as tf

    cap = dict(r4_dfs={}, trades={}, dfs={}, filters={})
    stat = {"n": 0, "tot": 0.0}
    cfg = Cfg(fix_fill=False, arm_hours=ARM_LIVE, ratchet=False, roska4_only=False,
              ema=50, stop_basis=2.0)
    orig_bt, bt_fn = patched_engine(cfg, stat)

    old_allowed = list(tf.DEFAULT_CONFIG["allowed_regimes"])
    old_generate = tf.TrendFollowStrategy.generate_signal
    old_defaults = dict(tf.DEFAULT_CONFIG)
    old_stress_cls = SM.StressMidEngine
    old_swing_cls = ST.SwingTFEngine
    orig_cache = force_all_bars_gappable()

    short_days = allowed_short_days(feature_frame(spy_csv), "below_sma50")

    def gated_generate(self, *a, **kw):
        """SHORT gate (existing Normal config) + R4 context gate at the decision bar."""
        sig = old_generate(self, *a, **kw)
        if not sig:
            return None
        resume_bar = a[1]
        ts = pd.Timestamp(resume_bar.name)
        day = (ts.tz_localize(None) if ts.tz is not None else ts).normalize()
        if sig.get("direction") == "SHORT" and day not in short_days:
            return None
        f = _ACTIVE_FILTER
        if f is not None and not f.allow(ts):
            return None
        return sig

    class PatchedSwingTFEngine:
        def __init__(self):
            self._inner = old_swing_cls(ema_period=30, chandelier_atr_mult=2.5,
                                        max_hold_days=5)

        def backtest_basket(self, dfs, labels, costs, **kw):
            cap["r4_dfs"] = dict(dfs)
            return self._inner.backtest_basket(dfs, labels, costs, **kw)

    class NoStressEngine:
        def backtest_basket(self, dfs, labels, costs):
            return {name: [] for name in dfs}

    def capturing_bt(df, labels, cost, **kw):
        global _ACTIVE_FILTER
        if kw.get("return_open") or kw.get("resume_pos") is not None:
            return bt_fn(df, labels, cost, **kw)
        name = {id(d): n for n, d in cap["r4_dfs"].items()}.get(id(df))
        is_r4 = name is not None
        if apply_filter and is_r4:
            f = cap["filters"].get(id(df))
            if f is None:
                f = R4ContextFilter(df, range_max=range_max, vol_max=vol_max,
                                    vol_feature=vol_feature)
                cap["filters"][id(df)] = f
            _ACTIVE_FILTER = f
        else:
            _ACTIVE_FILTER = None
        try:
            tr = bt_fn(df, labels, cost, **kw)
        finally:
            _ACTIVE_FILTER = None
        key = name or "__NKD__"
        cap["trades"][key] = [dict(t) for t in tr]
        cap["dfs"][key] = df
        return tr

    VC.backtest_swing_tf = capturing_bt
    tf.DEFAULT_CONFIG["allowed_regimes"] = ["Normal"]
    tf.TrendFollowStrategy.generate_signal = gated_generate
    ST.SwingTFEngine = PatchedSwingTFEngine
    SM.StressMidEngine = NoStressEngine

    argv = [x for x in H.ARGV[which] if x != "--include-stress"]
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
        _ACTIVE_FILTER = None
        VC.backtest_swing_tf = orig_bt
        VC._swing_cache = orig_cache
        tf.DEFAULT_CONFIG.clear()
        tf.DEFAULT_CONFIG.update(old_defaults)
        tf.DEFAULT_CONFIG["allowed_regimes"] = old_allowed
        tf.TrendFollowStrategy.generate_signal = old_generate
        SM.StressMidEngine = old_stress_cls
        ST.SwingTFEngine = old_swing_cls

    nkd = _nkd_instrument(argv)
    if "__NKD__" in cap["trades"]:
        cap["trades"][nkd] = cap["trades"].pop("__NKD__")
        cap["dfs"][nkd] = cap["dfs"].pop("__NKD__")
    cap["argv"] = argv
    cap["nkd"] = nkd
    cap["ds_metrics"] = parse_ds(buf.getvalue())
    cap["filter_stats"] = {n: cap["filters"][id(cap["dfs"][n])].stats()
                           for n in R4 if n in cap["dfs"]
                           and id(cap["dfs"][n]) in cap["filters"]}
    return cap


# ---------------------------------------------------------------------------
# entry-bar audit (5m aggregation aware)
# ---------------------------------------------------------------------------
def entry_bar_audit(trades: list, df: pd.DataFrame) -> dict:
    at, window, _dh, _dl = bar_lookup(df)
    res = dict(n=len(trades), outside_entry_bar_1m=0, outside_entry_bar_5m=0,
               entry_not_5m_close=0, missing_entry_bar=0)
    for t in trades:
        et = t.get("entry_time")
        px = float(t["entry"])
        if et is None:
            res["missing_entry_bar"] += 1
            continue
        b1 = at(et)
        if b1 is None:
            res["missing_entry_bar"] += 1
        elif px < b1["l"] - PRICE_EPS or px > b1["h"] + PRICE_EPS:
            res["outside_entry_bar_1m"] += 1
        w = window(et, 5)
        if w is None:
            res["missing_entry_bar"] += 1
            continue
        if px < w["l"] - PRICE_EPS or px > w["h"] + PRICE_EPS:
            res["outside_entry_bar_5m"] += 1
        if abs(w["c"] - px) > PRICE_EPS:
            res["entry_not_5m_close"] += 1
    return res


# ---------------------------------------------------------------------------
# portfolio replay through deploy_sim's own risk layer, with a cap override
# ---------------------------------------------------------------------------
def assemble(inst_trades: dict, meta: dict, cap_name: str, account=ACCOUNT):
    import global_index.deploy_sim as DS
    from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
    try:
        from futures.circuit_breaker import CircuitBreaker
    except Exception:
        CircuitBreaker = None

    spec = CAPS[cap_name]
    clusters = {"roska4_swing": ClusterBudget("roska4_swing", *spec["roska4_swing"]),
                "roska4_stress": ClusterBudget("roska4_stress", 0.025, None),
                "global_nkd": ClusterBudget("global_nkd", *spec["global_nkd"])}

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
                               direction=t["direction"], pnl1=t["pnl"], atr=m["atr"],
                               mult=m["mult"], pv=m["pv"], _atr_entry=ed))
    if not all_tr:
        e = pd.Series(dtype=float)
        return e, dict(taken={}, rejected={}, halted=0), DS.metrics(e)
    for t in all_tr:
        t["risk_sized"] = _real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], 1)
        t["pnl_sized"] = t["pnl1"]
    contracts_by = {i: 1 for i in meta}
    guard = MultiClusterGuard(clusters=clusters, account=account)
    sized, st = DS.replay(all_tr, account, guard, contracts_by, CircuitBreaker)
    return sized, st, DS.metrics(sized)


def row(label, cap_name, sized, st, m, ntr, audit, account=ACCOUNT):
    yrs = max((sized.index[-1] - sized.index[0]).days / 365.25, 0.1) if len(sized) else 1.0
    return dict(variant=label, cap=cap_name, net=m["pnl"], pf=m["pf"], sharpe=m["sharpe"],
                calmar=m["calmar"], maxdd=m["maxdd"], maxdd_pct=m["maxdd"] / account,
                ret_yr=m["pnl"] / account / yrs, trades=ntr,
                taken=sum(st["taken"].values()) if st["taken"] else 0,
                rejected=sum(st["rejected"].values()) if st["rejected"] else 0,
                halted=st["halted"],
                yearly=({int(y): float(g.sum()) for y, g in sized.groupby(sized.index.year)}
                        if len(sized) else {}),
                **audit)


def merge_audit(auds):
    keys = ("outside_exit_bar", "outside_exit_day", "signal_after_entry",
            "same_or_before_bar_exit", "outside_entry_bar_5m", "outside_entry_bar_1m")
    return {k: sum(a.get(k, 0) for a in auds) for k in keys}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--spy-csv", default="spy_daily_live.csv")
    ap.add_argument("--out", default="scratch/normal_promotion_regen_audit_20260821.txt")
    ap.add_argument("--json-out", default="scratch/normal_promotion_regen_audit_20260821.json")
    a = ap.parse_args()

    from futures._validated_core import daily_atr_series
    from futures.basket import BASKET
    from global_index import specs as gi_specs

    report, results = [], {}

    def emit(s=""):
        print(s, flush=True)
        report.append(s)

    emit("=" * 124)
    emit("NORMAL PROMOTION AUDIT - REGENERATED FROM THE SIGNAL PATH   (scratch / read-only)")
    emit("=" * 124)
    emit("Engine gap-through fix applied scratch-side (production does NOT contain it).")
    emit("R4 filter range_p90 <= {:.6f} AND rvol <= {:g}, installed inside generate_signal.".format(
        FLOOR_RANGE_P90, VOL_LE))
    emit("NKD is never filtered. Stress disabled. 1 micro, $50,000, 2 ticks/side.")
    emit("")

    for which in a.which:
        emit("#" * 124)
        emit("WINDOW: " + which)
        emit("#" * 124)

        runs = {}
        for tag, kw in (("raw", dict(apply_filter=False)),
                        ("filtered", dict(apply_filter=True, vol_feature="rvol_slot20")),
                        ("filtered_prevbar", dict(apply_filter=True,
                                                  vol_feature="rvol_prevbar"))):
            free_caches()
            runs[tag] = run_engine(which, a.spy_csv, **kw)
            emit("  engine run '{}' done ({} R4 + NKD trade lists)".format(
                tag, len(runs[tag]["trades"])))
        free_caches()

        nkd = runs["raw"]["nkd"]
        slip = _slip_ticks(runs["raw"]["argv"])
        meta = {}
        for name, df in runs["raw"]["dfs"].items():
            is_nkd = (name == nkd)
            c = gi_specs.SPECS[nkd] if is_nkd else BASKET[name]
            meta[name] = dict(cluster="global_nkd" if is_nkd else "roska4_swing",
                              atr=daily_atr_series(df), mult=2.5, pv=float(c.point_value))

        # ---- anchor: the unfiltered engine-fix run must reproduce the baseline ----
        dsm = runs["raw"]["ds_metrics"]
        want = BASELINE[which]
        anchor_ok = abs(dsm.get("net", -1e9) - want) < 1.0
        emit("")
        emit("  [ANCHOR] unfiltered engine-fix run vs stated corrected baseline: "
             "${:,.0f} vs ${:,.0f} -> {}".format(dsm.get("net", 0), want,
                                                 "PASS" if anchor_ok else "FAIL"))
        if not anchor_ok:
            emit("  ANCHOR FAILED - every number below is void.")

        # ---- NKD must be untouched by the filter ----
        nkd_same = (runs["raw"]["trades"][nkd] == runs["filtered"]["trades"][nkd])
        emit("  [SELF-CHECK] NKD trade list identical filtered vs raw: {}".format(
            "PASS" if nkd_same else "FAIL - the filter leaked into NKD"))

        # ---- filter action at the decision boundary ----
        emit("")
        emit("  FILTER ACTION AT THE DECISION BAR (signals seen by the gate, not trades deleted)")
        emit("  {:<6} {:>8} {:>9} {:>9} {:>9} {:>9}".format(
            "inst", "seen", "passed", "blk range", "blk vol", "blk missing"))
        for n in R4:
            s = runs["filtered"]["filter_stats"].get(n)
            if s:
                emit("  {:<6} {:>8} {:>9} {:>9} {:>9} {:>9}".format(
                    n, s["seen"], s["passed"], s["blocked_range"], s["blocked_vol"],
                    s["blocked_missing"]))

        # ---- trade counts: decision-boundary vs post-hoc deletion ----
        emit("")
        emit("  TRADE COUNTS - regenerated vs post-hoc deletion of the same rule")
        emit("  {:<6} {:>8} {:>10} {:>12} {:>10}".format(
            "inst", "raw", "regen", "posthoc-del", "regen-posthoc"))
        posthoc = {}
        for n in R4:
            rawt = runs["raw"]["trades"][n]
            f = R4ContextFilter(runs["raw"]["dfs"][n])
            kept = [t for t in rawt if t.get("entry_time") is not None
                    and f.allow(pd.Timestamp(t["entry_time"]))]
            posthoc[n] = kept
            regen = runs["filtered"]["trades"][n]
            emit("  {:<6} {:>8} {:>10} {:>12} {:>10}".format(
                n, len(rawt), len(regen), len(kept), len(regen) - len(kept)))

        # ---- fill audit on the regenerated books ----
        emit("")
        emit("  FILL AUDIT - regenerated filtered book")
        emit("  {:<6} {:>7} {:>13} {:>13} {:>12} {:>14} {:>18} {:>18}".format(
            "inst", "trades", "out_exit_bar", "out_exit_day", "sig>entry",
            "same_bar_exit", "out_entry_bar_5m", "out_entry_bar_1m"))
        audits = {}
        for n in list(R4) + [nkd]:
            trs = (runs["filtered"]["trades"][n] if n in R4
                   else runs["filtered"]["trades"][nkd])
            df = runs["raw"]["dfs"][n]
            ex = audit_trades(n, trs, df)
            en = entry_bar_audit(trs, df)
            merged = dict(ex)
            merged.update(en)
            audits[n] = merged
            emit("  {:<6} {:>7} {:>13} {:>13} {:>12} {:>14} {:>18} {:>18}".format(
                n, len(trs), ex["outside_exit_bar"], ex["outside_exit_day"],
                ex["signal_after_entry"], ex["same_or_before_bar_exit"],
                en["outside_entry_bar_5m"], en["outside_entry_bar_1m"]))

        gate = all(audits[n]["outside_exit_bar"] == 0 and audits[n]["signal_after_entry"] == 0
                   and audits[n]["same_or_before_bar_exit"] == 0
                   and audits[n]["outside_entry_bar_5m"] == 0
                   for n in audits)
        emit("  FILL GATE (out_exit_bar=0, sig>entry=0, same_bar_exit=0, out_entry_bar_5m=0): "
             + ("PASS" if gate else "FAIL"))
        emit("  note: out_entry_bar_1m counts entries outside the single 1-MINUTE bar labelled")
        emit("        entry_time. The entry is the CLOSE of the 5-minute bar starting there, so")
        emit("        a non-zero count here is the 5m/1m aggregation, not an infeasible fill.")

        # ---- portfolio replay ----
        emit("")
        emit("  PORTFOLIO REPLAY (deploy_sim risk layer, MultiClusterGuard + CircuitBreaker)")
        emit("  {:<28} {:<10} {:>10} {:>6} {:>7} {:>7} {:>9} {:>8} {:>7} {:>6} {:>5} {:>5}".format(
            "variant", "cap", "net$", "PF", "Sharpe", "Calmar", "MaxDD$", "MaxDD%",
            "trades", "taken", "rej", "halt"))
        rows = []
        r4_raw = {n: runs["raw"]["trades"][n] for n in R4}
        r4_flt = {n: runs["filtered"]["trades"][n] for n in R4}
        r4_prev = {n: runs["filtered_prevbar"]["trades"][n] for n in R4}
        r4_post = dict(posthoc)
        nkd_t = {nkd: runs["raw"]["trades"][nkd]}
        variants = [
            ("R4 raw + NKD (baseline)", {**r4_raw, **nkd_t}),
            ("R4 filtered only", r4_flt),
            ("NKD only", nkd_t),
            ("R4 filtered + NKD", {**r4_flt, **nkd_t}),
            ("R4 filtered(prevbar) + NKD", {**r4_prev, **nkd_t}),
            ("R4 posthoc-deleted + NKD", {**r4_post, **nkd_t}),
        ]
        for label, tr in variants:
            for cap_name in ("current", "strict025"):
                sized, st, m = assemble(tr, meta, cap_name)
                au = merge_audit([audits[n] for n in tr if n in audits])
                ntr = sum(len(v) for v in tr.values())
                r = row(label, cap_name, sized, st, m, ntr, au)
                rows.append(r)
                emit("  {variant:<28} {cap:<10} {net:>10,.0f} {pf:>6.2f} {sharpe:>7.2f} "
                     "{calmar:>7.2f} {maxdd:>9,.0f} {maxdd_pct:>8.1%} {trades:>7} "
                     "{taken:>6} {rejected:>5} {halted:>5}".format(**r))

        emit("")
        years = sorted({y for r in rows for y in r["yearly"]})
        emit("  YEARLY NET$ (current cap)")
        emit("  {:<28} {}".format("variant", " ".join("{:>10}".format(y) for y in years)))
        for r in rows:
            if r["cap"] != "current":
                continue
            emit("  {:<28} {}".format(r["variant"], " ".join(
                "{:>10,.0f}".format(r["yearly"].get(y, 0.0)) for y in years)))
        emit("")

        dump = Path("scratch/normal_promotion_trades_{}_20260821.json".format(which))
        dump.write_text(json.dumps(
            {"argv": runs["raw"]["argv"], "nkd_instrument": nkd, "slippage_ticks": slip,
             "raw": {k: [{kk: str(vv) for kk, vv in t.items()} for t in v]
                     for k, v in runs["raw"]["trades"].items()},
             "filtered": {k: [{kk: str(vv) for kk, vv in t.items()} for t in v]
                          for k, v in runs["filtered"]["trades"].items()},
             "filtered_prevbar": {k: [{kk: str(vv) for kk, vv in t.items()} for t in v]
                                  for k, v in runs["filtered_prevbar"]["trades"].items()}},
            indent=1), encoding="utf-8")
        emit("  trade tables written to {}".format(dump))
        emit("")

        results[which] = dict(anchor_ok=bool(anchor_ok), anchor=dsm, nkd_untouched=bool(nkd_same),
                              filter_stats=runs["filtered"]["filter_stats"],
                              fill_gate=bool(gate),
                              audits={k: {kk: vv for kk, vv in v.items() if kk != "samples"}
                                      for k, v in audits.items()},
                              rows=rows,
                              counts={n: dict(raw=len(runs["raw"]["trades"][n]),
                                              regen=len(runs["filtered"]["trades"][n]),
                                              posthoc=len(posthoc[n])) for n in R4})
        for tag in list(runs):
            runs[tag]["dfs"] = None
            runs[tag]["r4_dfs"] = None
            runs[tag]["filters"] = None
        del runs
        free_caches()

    Path(a.out).write_text("\n".join(report) + "\n", encoding="utf-8")
    Path(a.json_out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print("\nwrote " + a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
