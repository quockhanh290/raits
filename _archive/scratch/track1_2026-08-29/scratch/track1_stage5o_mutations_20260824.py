"""Stage 5O mutation harness — re-arm each safety hazard, confirm the right test reds.

The stage's whole claim is separations: two books, two markers, two locks, two client ids.
Each separation is collapsed one at a time and the matching test must fail. On-disk mutations
(where a guard parses source) are hash-verified restored.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from global_index import track1_slots as ts  # noqa: E402

TEST = "scratch/test_track1_stage5o_route_aware_safety_20260824.py"


def run(node: str) -> int:
    """A FRESH interpreter per run, via subprocess.

    The first version called `pytest.main` in-process, and the four on-disk mutations of
    `run_scheduler.py` all went UNDETECTED: the module was already imported and cached in
    `sys.modules`, so the tests kept exercising the pre-mutation code while the file on disk
    said otherwise. A real regression lives on disk and is loaded by a fresh process — so the
    harness runs one, exactly as an operator's pytest would.
    """
    import subprocess
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "-x", f"{TEST}::{node}"],
                       capture_output=True, text=True, cwd="d:/raits", timeout=600)
    return r.returncode


def run_inproc(node: str) -> int:
    """In-process, for mutations that are THEMSELVES in-process monkeypatches — a fresh
    interpreter would never see them. Disk mutations use `run`; patch mutations use this."""
    return int(pytest.main(["-q", "-p", "no:cacheprovider", "-x", f"{TEST}::{node}"]))


def mutate(label, apply_, revert, node, *, inproc: bool = False) -> dict:
    runner = run_inproc if inproc else run
    baseline = runner(node)
    apply_()
    try:
        mutated = runner(node)
    finally:
        revert()
    restored = runner(node)
    ok = baseline == 0 and mutated != 0 and restored == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: "
          f"baseline={baseline} mutated={mutated} restored={restored}")
    return {"mutation": label, "guard": node, "baseline_exit": baseline,
            "mutated_exit": mutated, "restored_exit": restored, "detected": ok}


def main() -> int:
    results = []
    sched_path = Path("global_index/run_scheduler.py")
    sched_orig = sched_path.read_text(encoding="utf-8")

    # S1 — Track 1 stop repair watches legacy's book again. On DISK, in the registration
    # block, exactly the one-word regression an editor could make.
    s1 = sched_orig.replace(
        '''            _run([sys.executable, "-m", "global_index.run_stop_repair",
                  "--positions-path", _t1r.TRACK1_POSITIONS_PATH,''',
        '''            _run([sys.executable, "-m", "global_index.run_stop_repair",
                  "--positions-path", "live_positions.json",''')
    assert s1 != sched_orig
    results.append(mutate(
        "S1 Track 1 stop repair points at live_positions.json again",
        lambda: sched_path.write_text(s1, encoding="utf-8"),
        lambda: sched_path.write_text(sched_orig, encoding="utf-8"),
        "test_track1_safety_watches_track1s_book_and_only_track1s"))

    # S2 — the Track 1 max-hold records into the SHARED marker file again.
    s2 = sched_orig.replace(
        """            if ok and not dry_run:
                _maxhold_done_t1[_et_today().isoformat()] = True
                _save_maxhold_state_t1()""",
        """            if ok and not dry_run:
                _maxhold_done[_et_today().isoformat()] = True
                _save_maxhold_state()""")
    assert s2 != sched_orig
    results.append(mutate(
        "S2 Track 1 max-hold writes the shared maxhold_state.json again",
        lambda: sched_path.write_text(s2, encoding="utf-8"),
        lambda: sched_path.write_text(sched_orig, encoding="utf-8"),
        "test_the_track1_maxhold_records_into_its_own_file"))

    # S3 — the legacy marker suppresses the Track 1 catch-up: the catch-up consults the
    # legacy dict as well.
    s3 = sched_orig.replace(
        """    if _maxhold_done_t1.get(today):
        log.info("[MAXHOLD_T1] da chay hom nay (%s) — bo qua catch-up", today)
        return""",
        """    if _maxhold_done_t1.get(today) or _maxhold_done.get(today):
        log.info("[MAXHOLD_T1] da chay hom nay (%s) — bo qua catch-up", today)
        return""")
    assert s3 != sched_orig
    results.append(mutate(
        "S3 the legacy marker suppresses the Track 1 catch-up",
        lambda: sched_path.write_text(s3, encoding="utf-8"),
        lambda: sched_path.write_text(sched_orig, encoding="utf-8"),
        "test_legacy_marker_does_not_suppress_the_track1_catchup"))

    # S4 — the route env goes missing from the Track 1 safety children.
    s4 = sched_orig.replace(
        '''                  "--port", str(port)],
                 label=label, dry_run=dry_run, route=_t1r.EVENT_ROUTE_VALUE)

        for _sj in _t1r.track1_safety_jobs():''',
        '''                  "--port", str(port)],
                 label=label, dry_run=dry_run)

        for _sj in _t1r.track1_safety_jobs():''')
    assert s4 != sched_orig
    results.append(mutate(
        "S4 the route env vanishes from the Track 1 safety children",
        lambda: sched_path.write_text(s4, encoding="utf-8"),
        lambda: sched_path.write_text(sched_orig, encoding="utf-8"),
        "test_track1_safety_watches_track1s_book_and_only_track1s"))

    # S5 — the Track 1 safety jobs are simply not registered in track1-only.
    orig_jobs = ts.track1_safety_jobs
    results.append(mutate(
        "S5 the Track 1 safety jobs are absent from track1-only",
        lambda: setattr(ts, "track1_safety_jobs", lambda: ()),
        lambda: setattr(ts, "track1_safety_jobs", orig_jobs),
        "test_track1_safety_exists_only_in_track1_only_mode", inproc=True))

    # S6 — a legacy strategy job survives track1-only (carried forward from 5M-D; the safety
    # stage must not have loosened it).
    orig_cand = ts.legacy_retirement_candidates
    results.append(mutate(
        "S6 a legacy strategy job survives track1-only",
        lambda: setattr(ts, "legacy_retirement_candidates",
                        lambda *a, **k: orig_cand(*a, **k) - {"live_day"}),
        lambda: setattr(ts, "legacy_retirement_candidates", orig_cand),
        "test_no_legacy_strategy_job_in_track1_only", inproc=True))

    # S7 — a hardcoded count returns to the registration block.
    s7 = sched_orig.replace(
        "        for _sj in _t1r.track1_safety_jobs():",
        "        _expected = 11  # == 11 jobs\n"
        "        for _sj in _t1r.track1_safety_jobs():", 1)
    assert s7 != sched_orig
    results.append(mutate(
        "S7 a hardcoded '== 11' count returns to the wiring",
        lambda: sched_path.write_text(s7, encoding="utf-8"),
        lambda: sched_path.write_text(sched_orig, encoding="utf-8"),
        "test_no_hardcoded_job_count_in_the_new_wiring"))

    # S8 — the sweeps stop respecting Track 1's entry windows.
    orig_hours = ts._track1_sweep_hours
    results.append(mutate(
        "S8 a sweep lands inside a Track 1 entry window",
        lambda: setattr(ts, "_track1_sweep_hours",
                        lambda: sorted(set(orig_hours()) | {14})),
        lambda: setattr(ts, "_track1_sweep_hours", orig_hours),
        "test_the_sweep_hours_are_derived_from_track1s_own_windows", inproc=True))

    detected = sum(1 for r in results if r["detected"])
    print(f"\n{detected}/{len(results)} mutations detected")
    ok_restore = sched_path.read_text(encoding="utf-8") == sched_orig
    print("production files restored byte-for-byte:", ok_restore)
    Path("scratch/_stage5o_mutations.json").write_text(
        json.dumps({"mutations": results, "files_restored": ok_restore}, indent=2),
        encoding="utf-8")
    return 0 if detected == len(results) and ok_restore else 1


if __name__ == "__main__":
    raise SystemExit(main())
