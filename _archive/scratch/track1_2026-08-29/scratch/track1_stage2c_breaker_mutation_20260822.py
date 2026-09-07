"""scratch/track1_stage2c_breaker_mutation_20260822.py — Stage 2C, part 2. Offline.

The vault2026 reproduction proved only that `open_pos` is load-bearing: mutating
`peak_equity`, `equity` and a position's `cluster` changed nothing, because on that window
the circuit breaker never came near a limit and that cap was never binding. A field that is
carried but never read is not proved by a green run.

This exercises the same bootstrap on `floor`, the window whose committed run records
`halted = 2`, and places the cut deliberately: a few sessions BEFORE the deepest drawdown of
the book, so the breaker's peak and the running equity both decide admissions inside the
resumed span. If a mutation still cannot make the comparison go red there, the honest
conclusion is that the field is not load-bearing on any measured window — not that it is
correct.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import pandas as pd  # noqa: E402

import scratch.calm_a_combined_replay_20260822 as calm_a_base  # noqa: E402
import scratch.combined_repaired_replay_20260822 as comb  # noqa: E402
import scratch.track1_stage2c_book_bootstrap_20260822 as s2c  # noqa: E402


def pick_cut(daily: pd.Series, back: int) -> tuple[pd.Timestamp, dict]:
    """Cut a few sessions before the deepest drawdown, so the resumed span contains it."""
    eq = daily.cumsum()
    dd = eq.cummax() - eq
    trough = dd.idxmax()
    idx = list(daily.index)
    i = max(idx.index(trough) - back, 0)
    return idx[i], {"trough": str(trough.date()), "max_dd": float(dd.max()),
                    "cut_index": i, "sessions_before_trough": back}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", default="floor")
    ap.add_argument("--variant", default="production_gate_on")
    ap.add_argument("--back", type=int, default=5)
    ap.add_argument("--only", nargs="+", default=None,
                    help="run only these mutation tags, e.g. M5b M5c")
    ap.add_argument("--cut-instant", default=None,
                    help="explicit intra-day cut, e.g. '2022-01-10 10:35:00-05:00'")
    ap.add_argument("--out", default="scratch/track1_stage2c_breaker_mutation_20260822.json")
    a = ap.parse_args()

    s2c.use_variant(a.which, a.variant)
    pol = comb.POLICIES[0]

    calm_a_base.DATA_CACHE.pop(a.which, None)
    d_full, st_full, end_full, ev_full = s2c.replay(a.which, pol)
    cut, info = pick_cut(d_full, a.back)
    print(f"window={a.which} variant={a.variant} policy={pol.name}", flush=True)
    print(f"  halts in the full run : {st_full['halted']}", flush=True)
    print(f"  deepest drawdown      : ${info['max_dd']:,.0f} at {info['trough']}", flush=True)
    print(f"  cut placed at         : {cut.date()} "
          f"({a.back} sessions before the trough)\n", flush=True)

    if a.cut_instant:
        cut = pd.Timestamp(a.cut_instant)
        print(f"  cut overridden to     : {cut} (intra-day)", flush=True)
    calm_a_base.DATA_CACHE.pop(a.which, None)
    _d, _s, boot, _e = s2c.replay(a.which, pol, stop_after=cut)
    ci = pd.Timestamp(boot["cut_instant"])
    exp = [s2c._ev_key(e) for e in ev_full if pd.Timestamp(e["ts"]) > ci]

    print(f"  cut instant           : {boot['cut_instant']}", flush=True)
    print(f"  carried positions={len(boot['open_pos'])} equity={boot['equity']:,.2f} "
          f"peak={boot['peak_equity']:,.2f} events after cut={len(exp)}", flush=True)
    if not exp or not boot["open_pos"]:
        print("REFUSED: the control would be vacuous — nothing carried or nothing after "
              "the cut.", flush=True)
        return 2

    rows = []
    seqs = {}

    def run(b, tag, must_diverge):
        code = tag.split()[0]
        if a.only and code not in a.only and code != "unmodified":
            return True
        calm_a_base.DATA_CACHE.pop(a.which, None)
        _dr, _sr, _er, ev = s2c.replay(a.which, pol, resume=b)
        got = [s2c._ev_key(e) for e in ev]
        same = got == exp
        ok = (not same) if must_diverge else same
        print(f"  {'PASS' if ok else 'FAIL'}  {tag:44s} "
              f"{'match  ' if same else 'DIVERGE'} {len(got)}/{len(exp)}", flush=True)
        seqs[tag.split()[0]] = got
        rows.append({"mutation": tag, "diverged": not same, "expected_divergence":
                     must_diverge, "ok": ok, "events": len(got), "events_expected": len(exp)})
        return ok

    print("\n  control (must MATCH):", flush=True)
    run(copy.deepcopy(boot), "unmodified bootstrap", must_diverge=False)

    print("  mutations (each must DIVERGE):", flush=True)
    m = copy.deepcopy(boot); m["open_pos"] = []
    run(m, "M1 forget every carried open position", True)
    # One-sided on purpose. Lowering the peak only RELAXES a rule that is not binding, so it
    # cannot go red and asserting that it should would be asserting nothing. It is kept as a
    # documented control, not as a probe.
    m = copy.deepcopy(boot); m["peak_equity"] = float(m["equity"])
    run(m, "M2 peak LOWERED (relaxing — control, must MATCH)", False)
    m = copy.deepcopy(boot); m["peak_equity"] = float(m["equity"]) * 1.20
    run(m, "M2b peak RAISED 20% (drawdown past the hard cap)", True)
    m = copy.deepcopy(boot); m["equity"] = 50000.0
    run(m, "M3 equity reset to the account size", True)
    m = copy.deepcopy(boot); m["open_pos"] = m["open_pos"][:-1]
    run(m, "M4 drop ONE carried position", True)
    m = copy.deepcopy(boot)
    if m["open_pos"]:
        m["open_pos"][0]["cluster"] = "roska4_stress"
    run(m, "M5 one carried position in the wrong cluster", True)
    m = copy.deepcopy(boot); m["day_start_equity"] = float(m["equity"])
    run(m, "M6 day start LOWERED (relaxing — control, must MATCH)", False)
    m = copy.deepcopy(boot); m["day_start_equity"] = float(m["equity"]) / 0.90
    run(m, "M6b day start RAISED (daily loss reads -10%, past -4%)", True)
    # `booked` feeds only the double-settlement counter and no admission decision, so it
    # cannot change the event list. Asserted as a control so the claim stays checked.
    m = copy.deepcopy(boot); m["booked"] = {}
    run(m, "M7 forget settled ids (diagnostic only — must MATCH)", False)
    if boot["open_pos"]:
        m = copy.deepcopy(boot)
        m["open_pos"][0]["risk"] = float(m["open_pos"][0]["risk"]) * 20.0
        run(m, "M5b risk x20, cluster UNCHANGED", True)
        # The isolation. Same inflated risk, different cap bucket. Divergence against the
        # control only shows that risk moved; divergence against M5b is what separates the
        # cluster from the risk it travels with.
        m = copy.deepcopy(boot)
        m["open_pos"][0]["risk"] = float(m["open_pos"][0]["risk"]) * 20.0
        m["open_pos"][0]["cluster"] = "global_nkd"
        run(m, "M5c risk x20, cluster -> global_nkd", True)
        if "M5b" in seqs and "M5c" in seqs:
            iso = seqs["M5b"] != seqs["M5c"]
            print(f"  {'PASS' if iso else 'FAIL'}  "
                  f"{'M5c differs from M5b — cluster is load-bearing' if iso else 'M5c == M5b — cluster NOT isolated'}"
                  f"  ({len(seqs['M5b'])} vs {len(seqs['M5c'])} events)", flush=True)
            rows.append({"mutation": "ISOLATION M5b vs M5c", "diverged": iso,
                         "expected_divergence": True, "ok": iso,
                         "events": len(seqs["M5c"]), "events_expected": len(seqs["M5b"])})

    Path(a.out).write_text(json.dumps(
        {"window": a.which, "variant": a.variant, "policy": pol.name,
         "cut": str(cut.date()), "info": info, "halted": st_full["halted"],
         "bootstrap": boot, "rows": rows}, indent=2, default=str), encoding="utf-8")
    print(f"\n{a.out}", flush=True)
    unproved = [r["mutation"] for r in rows if r["expected_divergence"] and not r["ok"]]
    if unproved:
        print("\nNOT PROVED load-bearing on this window:", flush=True)
        for u in unproved:
            print(f"  - {u}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
