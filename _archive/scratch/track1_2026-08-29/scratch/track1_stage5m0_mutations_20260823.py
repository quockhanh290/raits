"""Stage 5M-0 mutation harness — break each refusal, confirm the right test reds.

The reconstructor's value is entirely in what it declines to write. A test that only checks
the happy path would pass on a version that writes True for every day it sees mentioned. So
each mutation below turns one refusal into an inference, and the matching test must fail.

Nothing touches the operator's state files: every mutation is a monkeypatch on the imported
module, reverted before the next, and every test involved writes only under tmp_path.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

import track1_stage5m0_state_repair_20260823 as rep  # noqa: E402

TEST = "scratch/test_track1_stage5m0_state_repair_20260823.py"


def _guarded():
    return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None)
            for p in (rep.PREFLIGHT_PATH, rep.MAXHOLD_PATH)}


def run(node: str) -> int:
    return int(pytest.main(["-q", "-p", "no:cacheprovider", "-x", f"{TEST}::{node}"]))


def mutate(label: str, apply_, revert, node: str) -> dict:
    baseline = run(node)
    apply_()
    try:
        mutated = run(node)
    finally:
        revert()
    restored = run(node)
    ok = baseline == 0 and mutated != 0 and restored == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: "
          f"baseline={baseline} mutated={mutated} restored={restored}")
    return {"mutation": label, "guard": node, "baseline_exit": baseline,
            "mutated_exit": mutated, "restored_exit": restored, "detected": ok}


def main() -> int:
    before = _guarded()
    results = []

    # N1 — "it launched, so it ran". The inference the 2026-08-13 double-launch makes concrete.
    orig_reconstruct = rep.reconstruct
    results.append(mutate(
        "N1 an unresolved launch counted as a completed run",
        lambda: setattr(rep, "reconstruct",
                        lambda runs, *, record_failures: dict(sorted(
                            {r["day"]: True for r in runs
                             if r["verdict"] in ("ok", "no_outcome_line")}.items())[-rep.KEEP:])),
        lambda: setattr(rep, "reconstruct", orig_reconstruct),
        "test_maxhold_refuses_to_infer_a_day_whose_runs_never_completed"))

    # N2 — a failed run recorded as success. The direction that lets a stale day trade.
    results.append(mutate(
        "N2 a failed pre-flight recorded as True",
        lambda: setattr(rep, "reconstruct",
                        lambda runs, *, record_failures: dict(sorted(
                            {r["day"]: True for r in runs
                             if r["verdict"] in ("ok", "failed")}.items())[-rep.KEEP:])),
        lambda: setattr(rep, "reconstruct", orig_reconstruct),
        "test_a_failed_preflight_is_recorded_false_not_dropped"))

    # N3 — the outcome scan runs past the next launch and borrows its success line.
    orig_scan_pf = rep.scan_preflight

    def _greedy(pattern="scheduler*.log"):
        runs = orig_scan_pf(pattern)
        seen_ok = any(r["verdict"] == "ok" for r in runs)
        return [{**r, "verdict": "ok"} if seen_ok else r for r in runs]

    results.append(mutate(
        "N3 an outcome line borrowed by the previous run",
        lambda: setattr(rep, "scan_preflight", _greedy),
        lambda: setattr(rep, "scan_preflight", orig_scan_pf),
        "test_an_ok_line_belonging_to_the_next_run_is_not_borrowed_by_the_previous"))

    # N4 — the ET conversion replaced by slicing the date off the log line.
    orig_et = rep._et_day
    results.append(mutate(
        "N4 ET session day taken from the raw local stamp",
        lambda: setattr(rep, "_et_day", lambda d, t: d),
        lambda: setattr(rep, "_et_day", orig_et),
        "test_a_local_stamp_after_2200_rolls_into_the_next_et_day"))

    # N5 — pruning dropped, so the repaired file is longer than the writer would produce.
    results.append(mutate(
        "N5 the seven-entry prune removed",
        lambda: setattr(rep, "reconstruct",
                        lambda runs, *, record_failures: {
                            r["day"]: True for r in runs if r["verdict"] == "ok"}),
        lambda: setattr(rep, "reconstruct", orig_reconstruct),
        "test_the_reconstruction_prunes_to_the_same_seven_the_writer_keeps"))

    # N6 — the unattested key carried across instead of dropped. The incident, re-created.
    orig_main = rep.main

    def _merging_main(argv=None):
        rc = orig_main(argv)
        if argv and "--apply" in argv and rc == 0:
            i = argv.index("--preflight-path")
            p = Path(argv[i + 1])
            p.write_text(json.dumps({"2026-08-23": True,
                                     **json.loads(p.read_text(encoding="utf-8"))}),
                         encoding="utf-8")
        return rc

    results.append(mutate(
        "N6 an unattested key preserved through the repair",
        lambda: setattr(rep, "main", _merging_main),
        lambda: setattr(rep, "main", orig_main),
        "test_apply_writes_only_the_targets_it_was_given_and_never_the_real_files"))

    # N7 — dry-run stops being the default.
    def _always_applies(argv=None):
        argv = list(argv or [])
        if "--apply" not in argv:
            argv.append("--apply")
        return orig_main(argv)

    results.append(mutate(
        "N7 the dry-run default writes anyway",
        lambda: setattr(rep, "main", _always_applies),
        lambda: setattr(rep, "main", orig_main),
        "test_the_default_invocation_writes_nothing"))

    # N8 — the "has this file already healed?" guard stops refusing.
    def _no_guard(argv=None):
        argv = list(argv or [])
        if "--expect-current" in argv:
            i = argv.index("--expect-current")
            del argv[i:i + 2]
        return orig_main(argv)

    results.append(mutate(
        "N8 the expect-current guard ignored",
        lambda: setattr(rep, "main", _no_guard),
        lambda: setattr(rep, "main", orig_main),
        "test_apply_refuses_when_the_target_has_changed_since_the_plan"))

    detected = sum(1 for r in results if r["detected"])
    print(f"\n{detected}/{len(results)} mutations detected")

    after = _guarded()
    print("operator state files unchanged through the whole harness:", after == before)
    Path("scratch/_stage5m0_mutations.json").write_text(
        json.dumps({"mutations": results, "guarded_unchanged": after == before}, indent=2),
        encoding="utf-8")
    return 0 if detected == len(results) and after == before else 1


if __name__ == "__main__":
    raise SystemExit(main())
