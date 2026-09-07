"""Stage 5Q-9 Part B — what the sizing basis does to ADMISSIONS. READ-ONLY.

Stage 5Q-8 measured that the two ATR-stop sleeves report risk on two different bases:

    artifact_basis        risk = 2.5 x daily ATR x point_value x qty     (ROSKA4_MULT/NKD_MULT)
    true_stop_distance    risk = |entry - stop| x pv x qty = 2.0 x daily ATR x pv x qty

and that the ratio is exactly 1.25 on all 938 roska4_swing and all 285 global_nkd rows across
the three windows. `roska4_calm` (28/28) and `roska4_stress` (4/4) already carry a real stop
price and their two bases are the same number, which makes them the control arm.

That measured a NUMBER. It did not measure a CONSEQUENCE. The caps are unchanged and are in the
identity hash, but the quantity they gate is 20% smaller on two of four sleeves — and there are
two separate mechanisms by which that can change the book:

  1. a candidate that would have breached a cluster, family or net cap now fits;
  2. `process_instant` sorts same-instant candidates by `entry_priority_key(risk_sized)`, so
     shrinking two sleeves' risk and not the other two can REORDER who is offered a cap first.

This runs the committed candidate stream through the real `Track1Book` twice, changing nothing
but `risk_dollars`, and diffs the decision stream. Nothing here re-implements a gate.

    python scratch/track1_stage5q9_sizing_basis_admission_20260824.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_index import track1_bootstrap as boot           # noqa: E402
from global_index import track1_params as tp                # noqa: E402
from global_index import track1_signal_layer as T           # noqa: E402
from global_index.signal_layer import NKD_MULT, ROSKA4_MULT  # noqa: E402
from global_index.track1_sleeves import load_source          # noqa: E402

WINDOWS = ("floor", "vault2025", "vault2026")

#: The two sleeves whose artifact risk is a MULTIPLE-OF-ATR proxy rather than a stop distance.
PROXY_SLEEVES = ("roska4_swing", "global_nkd")

#: live stop is 2.0 x daily ATR; artifact risk is MULT x daily ATR. Both share the same ATR,
#: point value and qty, so the conversion is exact arithmetic, not an estimate.
LIVE_STOP_MULT = 2.0
SCALE = {"roska4_swing": LIVE_STOP_MULT / ROSKA4_MULT,
         "global_nkd": LIVE_STOP_MULT / NKD_MULT}

OUT = Path(__file__).resolve().parent / "_track1_stage5q9_sizing_basis.json"


def to_true_stop_distance(cands: list) -> list:
    """The same candidates, sized on the true stop distance. Only `risk_dollars` moves."""
    out = []
    for c in cands:
        s = SCALE.get(c.sleeve)
        out.append(c if s is None else replace(c, risk_dollars=float(c.risk_dollars) * s))
    return out


def _instrument(book):
    """Record per-cluster gross/net usage after every commit. Observes; changes nothing.

    "Gross" is `max(long, short) / account`, NOT `(long + short) / account`. That is the
    formula `net_exposure_multi.MultiClusterGuard.admits` and `family_verdict` both use, and
    getting it wrong is not a rounding difference: the first version of this harness summed
    the two sides and reported peak roska4_swing usage of 0.0903 against a 0.050 cap. A usage
    figure that exceeds the cap the guard enforces is impossible by construction, which is
    what caught it — see SC6 below, which now asserts the bound rather than trusting it.
    """
    peaks = {"cluster_gross": {}, "cluster_net": {}, "family_gross": 0.0, "family_net": 0.0}
    original = book.apply

    def apply(ts, decision, **kw):
        d = original(ts, decision, **kw)
        acct = float(book.account)
        fam_l = fam_s = 0.0
        sides = {}
        for p in book.positions():
            ls = sides.setdefault(p.cluster, [0.0, 0.0])
            if p.direction == "LONG":
                ls[0] += p.risk_dollars
            else:
                ls[1] += p.risk_dollars
            if p.cluster in tp.FAMILY_CLUSTERS:
                if p.direction == "LONG":
                    fam_l += p.risk_dollars
                else:
                    fam_s += p.risk_dollars
        for cl, (lo, sh) in sides.items():
            peaks["cluster_gross"][cl] = max(peaks["cluster_gross"].get(cl, 0.0),
                                             max(lo, sh) / acct)
            peaks["cluster_net"][cl] = max(peaks["cluster_net"].get(cl, 0.0),
                                           abs(lo - sh) / acct)
        peaks["family_gross"] = max(peaks["family_gross"], max(fam_l, fam_s) / acct)
        peaks["family_net"] = max(peaks["family_net"], abs(fam_l - fam_s) / acct)
        return d

    book.apply = apply
    return peaks


def check_peaks_within_caps(peaks: dict) -> "tuple[list, list]":
    """`(instrument_failures, observed_net_overshoots)`.

    SC6. A GROSS peak above its cap is impossible: `MultiClusterGuard.admits` tests
    `max(long, short)` of the surviving book plus the proposal, so the book can never hold
    more than the cap after an admission. If this harness reports one, the harness is
    measuring a different quantity from the gate — which is exactly what happened on the
    first attempt, when it summed both sides and reported 0.0903 against a 0.050 cap.

    A NET peak above its cap is NOT an instrument failure, and it is not a breach anyone
    caused. Verified on the floor window: zero admissions and zero forced closes ever left
    roska4_swing net above 0.044. The peak is reached when a SETTLEMENT closes one side and
    the remaining imbalance rises — the cap gates new risk, it is not an invariant of the
    book afterwards, and nothing can un-take a position because another one closed. Recorded
    rather than flagged, so the usage table is read for what it is.
    """
    impossible, overshoot = [], []
    for cl, used in peaks["cluster_gross"].items():
        cap = tp.CAPS[cl][0]
        if used > cap + 1e-9:
            impossible.append(f"{cl} gross {used:.4f} > cap {cap:.4f}")
    if peaks["family_gross"] > tp.FAMILY_GROSS + 1e-9:
        impossible.append(f"family gross {peaks['family_gross']:.4f} > {tp.FAMILY_GROSS:.4f}")
    for cl, used in peaks["cluster_net"].items():
        cap = tp.CAPS[cl][1]
        if cap is not None and used > cap + 1e-9:
            overshoot.append(f"{cl} net {used:.4f} > cap {cap:.4f} (post-settlement)")
    if peaks["family_net"] > tp.FAMILY_NET + 1e-9:
        overshoot.append(f"family net {peaks['family_net']:.4f} > cap {tp.FAMILY_NET:.4f} "
                         f"(post-settlement)")
    return impossible, overshoot


def run_arm(cands: list, window: str) -> dict:
    src = load_source("replay")
    book = boot._fresh_book()
    peaks = _instrument(book)
    tail, decisions = T.run_candidates(cands, book=book,
                                       early_exit_value=src.early_exit_valuer(window))
    return {
        "impossible_peaks": check_peaks_within_caps(peaks)[0],
        "net_overshoot_post_settlement": check_peaks_within_caps(peaks)[1],
        "decisions": {d.candidate.trade_id: d.verdict for d in decisions},
        "n_decisions": len(decisions),
        "counters": dict(book.counters),
        "settlements": len(book.events),
        "booked_pnl": round(float(book.equity) - float(book.account), 2),
        "open_at_end": len(tail),
        "peaks": {"cluster_gross": {k: round(v, 6) for k, v in peaks["cluster_gross"].items()},
                  "cluster_net": {k: round(v, 6) for k, v in peaks["cluster_net"].items()},
                  "family_gross": round(peaks["family_gross"], 6),
                  "family_net": round(peaks["family_net"], 6)},
    }


def main() -> int:
    print("Stage 5Q-9 Part B — sizing basis vs admissions")
    print(f"ROSKA4_MULT={ROSKA4_MULT}  NKD_MULT={NKD_MULT}  live stop mult={LIVE_STOP_MULT}")
    print(f"scale applied to {PROXY_SLEEVES}: {SCALE}")
    print("=" * 78)
    report = {"scale": SCALE, "windows": {}}
    src = load_source("replay")
    failures = []

    for w in WINDOWS:
        base = src.candidates(w)
        alt = to_true_stop_distance(base)

        # ── self-checks, before any conclusion is drawn ──────────────────────────────
        sc = {}
        sc["SC1_same_candidate_count"] = len(base) == len(alt) > 0
        sc["SC2_control_sleeves_unchanged"] = all(
            a.risk_dollars == b.risk_dollars for a, b in zip(base, alt)
            if a.sleeve not in PROXY_SLEEVES)
        ratios = {round(b.risk_dollars / a.risk_dollars, 9)
                  for a, b in zip(base, alt) if a.sleeve in PROXY_SLEEVES and a.risk_dollars}
        sc["SC3_proxy_ratio_is_exactly_0_8"] = ratios == {0.8}
        sc["SC4_the_arms_actually_differ"] = any(
            a.risk_dollars != b.risk_dollars for a, b in zip(base, alt))
        for k, v in sc.items():
            print(f"  [{'PASS' if v else 'FAIL'}] {k}")
            if not v:
                failures.append(f"{w}:{k}")
        if not all(sc.values()):
            print(f"  {w}: self-checks failed — not measuring on a broken instrument")
            report["windows"][w] = {"self_checks": sc, "measured": False}
            continue

        a = run_arm(base, w)
        b = run_arm(alt, w)
        for arm_name, r in (("artifact", a), ("true_stop", b)):
            if r["impossible_peaks"]:
                print(f"  [FAIL] SC6_gross_within_caps({arm_name}): {r['impossible_peaks']}")
                failures.append(f"{w}:SC6_{arm_name}")
            else:
                print(f"  [PASS] SC6_gross_within_caps({arm_name})")
            if r["net_overshoot_post_settlement"]:
                print(f"         note ({arm_name}): {r['net_overshoot_post_settlement']}")
        if not (a["n_decisions"] == b["n_decisions"] > 0):
            failures.append(f"{w}:SC5_decision_stream_nonempty_and_equal_length")

        changed = {k: (a["decisions"][k], b["decisions"].get(k))
                   for k in a["decisions"] if a["decisions"][k] != b["decisions"].get(k)}
        rec = {
            "self_checks": sc, "measured": True,
            "candidates": len(base),
            "artifact_basis": {k: a[k] for k in
                               ("n_decisions", "counters", "settlements", "booked_pnl",
                                "open_at_end", "peaks", "impossible_peaks",
                                "net_overshoot_post_settlement")},
            "true_stop_distance": {k: b[k] for k in
                                   ("n_decisions", "counters", "settlements", "booked_pnl",
                                    "open_at_end", "peaks", "impossible_peaks",
                                "net_overshoot_post_settlement")},
            "changed_admissions": changed,
            "n_changed_admissions": len(changed),
            "pnl_delta": round(b["booked_pnl"] - a["booked_pnl"], 2),
            "settlement_delta": b["settlements"] - a["settlements"],
        }
        report["windows"][w] = rec

        print(f"\n  {w}: {len(base)} candidates")
        for arm, r in (("artifact_basis   ", a), ("true_stop_distance", b)):
            tak = sum(v for k, v in r["counters"].items() if k.startswith("taken:"))
            rej = sum(v for k, v in r["counters"].items() if k.startswith("rejected:"))
            print(f"    {arm}  taken={tak:4d} rejected={rej:3d} settled={r['settlements']:4d} "
                  f"open={r['open_at_end']:3d} booked=${r['booked_pnl']:>12,.2f}")
        print(f"    changed admissions: {len(changed)}   "
              f"P&L delta: ${rec['pnl_delta']:,.2f}   settlements delta: {rec['settlement_delta']}")
        for k, (x, y) in list(changed.items())[:8]:
            print(f"      {k}: {x} -> {y}")
        print(f"    peak cluster gross (artifact): {a['peaks']['cluster_gross']}")
        print(f"    peak cluster gross (true stop): {b['peaks']['cluster_gross']}")
        print(f"    peak family gross {a['peaks']['family_gross']} -> {b['peaks']['family_gross']}"
              f"   net {a['peaks']['family_net']} -> {b['peaks']['family_net']}")

    total_changed = sum(r.get("n_changed_admissions", 0)
                        for r in report["windows"].values() if r.get("measured"))
    total_pnl = round(sum(r.get("pnl_delta", 0.0)
                          for r in report["windows"].values() if r.get("measured")), 2)
    report["total_changed_admissions"] = total_changed
    report["total_pnl_delta"] = total_pnl
    report["self_check_failures"] = failures
    report["verdict"] = ("no_admission_change" if total_changed == 0 and not failures
                         else "admissions_change" if not failures else "instrument_failed")

    print("\n" + "=" * 78)
    print(f"TOTAL changed admissions across three windows: {total_changed}")
    print(f"TOTAL booked P&L delta: ${total_pnl:,.2f}")
    print(f"VERDICT: {report['verdict']}")
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
