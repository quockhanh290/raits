"""Stage 5Q mutation harness — break each audit guarantee, confirm the right test reds.

Run:

    python scratch/track1_stage5q_mutations_20260824.py

Nothing here starts a scheduler, restarts a backend, connects to a broker or touches live
state. Production files edited on disk are restored and hash-verified byte-for-byte before
the harness exits, and the harness fails loudly if any restore does not match.

Why the harness exists at all: a guard that has never been observed failing is a banner, not
a guard. Every check below is of the form "remove one way the audit can say no" — because
those are the mutations that leave a suite green and an operator confident.

On-disk mutations re-run pytest in a FRESH subprocess (the 5O lesson: an in-process run keeps
exercising the cached pre-mutation module); in-process mutations use pytest.main, which a
subprocess would never see.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

TEST = "scratch/test_track1_stage5q_post_window_audit_20260824.py"


def run_sub(node: str) -> int:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "-x", f"{TEST}::{node}"],
                       capture_output=True, text=True, cwd="d:/raits", timeout=900)
    return r.returncode


def run_inproc(node: str) -> int:
    return int(pytest.main(["-q", "-p", "no:cacheprovider", "-x", f"{TEST}::{node}"]))


def mutate(label, apply_, revert, node, *, inproc=False) -> dict:
    runner = run_inproc if inproc else run_sub
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
    acc_path = Path("global_index/track1_shadow_acceptance.py")
    acc_orig = acc_path.read_text(encoding="utf-8")
    audit_path = Path("global_index/track1_shadow_audit.py")
    audit_orig = audit_path.read_text(encoding="utf-8")
    slots_path = Path("global_index/track1_slots.py")
    slots_orig = slots_path.read_text(encoding="utf-8")
    reader_path = Path("monitor/backend/track1_runtime_reader.py")
    reader_orig = reader_path.read_text(encoding="utf-8")
    status_path = Path("monitor/backend/schedule_status.py")
    status_orig = status_path.read_text(encoding="utf-8")

    def write(path, text):
        return lambda: path.write_text(text, encoding="utf-8")

    # Q1 — the slot-id check is dropped and only the COUNT is judged. This is the mutation
    # the coverage number cannot catch: the doubled slot keeps the count at 24.
    # Stage 5Q-1 moved this guard into `window_observation`, which is where the id list is
    # now derived. The harness FAILED LOUDLY when the old target string vanished rather than
    # reporting a detection it had not made — which is the only reason this was noticed.
    q1 = acc_orig.replace(
        '        "missing_slot_ids": [s for s in registered if classes[s] == SLOT_UNOBSERVED],',
        '        "missing_slot_ids": [],')
    if q1 == acc_orig:
        raise SystemExit("Q1 mutation did not apply; the slot-id guard moved")
    results.append(mutate(
        "Q1 the audit stops checking slot IDS and trusts the count",
        write(acc_path, q1), write(acc_path, acc_orig),
        "test_a_silent_slot_masked_by_a_doubled_one_fails_on_the_ids"))

    # Q2 — the runtime ceiling is raised past the cadence, so an overrunning day passes.
    q2 = acc_orig.replace("RUNTIME_P95_REQUIRED_S = 300.0",
                          "RUNTIME_P95_REQUIRED_S = 600.0")
    assert q2 != acc_orig
    results.append(mutate(
        "Q2 the p95 ceiling is raised above the slot cadence",
        write(acc_path, q2), write(acc_path, acc_orig),
        "test_p95_at_the_ceiling_fails"))

    # Q3 — the WARN band is removed, so a day between target and ceiling reads clean.
    q3 = acc_orig.replace("RUNTIME_P95_TARGET_S = 240.0",
                          "RUNTIME_P95_TARGET_S = 290.0")
    assert q3 != acc_orig
    results.append(mutate(
        "Q3 the p95 TARGET is moved so a 250s day stops warning",
        write(acc_path, q3), write(acc_path, acc_orig),
        "test_p95_between_the_target_and_the_ceiling_warns_and_does_not_fail"))

    # Q4 — a single stalled slot is averaged away by the p95. The mutation is the honest
    # form of the shortcut somebody would actually take: "the p95 is fine, so the window is
    # fine" — which is exactly what an overrun hides behind.
    q4 = acc_orig.replace("            if stalled:", "            if False:")
    if q4 == acc_orig:                    # the textual form drifted — fail loudly, not silently
        raise SystemExit("Q4 mutation did not apply; the stall check moved")
    results.append(mutate(
        "Q4 a single slot over the ceiling stops being a stall",
        write(acc_path, q4), write(acc_path, acc_orig),
        "test_a_single_slot_over_the_ceiling_fails_even_with_a_healthy_p95"))

    # Q5 — a window that closed BEFORE the scheduler existed becomes a failure. This is the
    # false-incident mutation: the 2026-08-24 NKD case, judged as a broken route.
    q5 = acc_orig.replace(
        "    elif not judgeable or uptime_unknown_blind:\n"
        "        verdict = AUDIT_NOT_ENOUGH_DATA_YET",
        "    elif not judgeable or uptime_unknown_blind:\n"
        "        verdict = AUDIT_FAIL")
    assert q5 != acc_orig
    results.append(mutate(
        "Q5 a window that closed before the scheduler started is called a FAILURE",
        write(acc_path, q5), write(acc_path, acc_orig),
        "test_a_window_that_closed_before_the_scheduler_started_is_pending_not_failed"))

    # Q6 — "no evidence and no readable start time" fails open to a judgeable window. The
    # exact fail-open shape that let a second scheduler start.
    q6 = acc_orig.replace(
        "    uptime_unknown_blind = (judgeable and scheduler_started_et is None\n"
        "                            and not observed_rows and not trows)",
        "    uptime_unknown_blind = False")
    assert q6 != acc_orig
    results.append(mutate(
        "Q6 an unreadable scheduler start is treated as 'the scheduler was up'",
        write(acc_path, q6), write(acc_path, acc_orig),
        "test_a_closed_window_with_no_evidence_and_no_readable_start_is_pending_not_failed"))

    # Q7 — missing telemetry becomes a pass. "No file" as the quickest route to green.
    q7 = acc_orig.replace(
        "        if not durations:\n"
        "            reasons.append(R_NO_TIMING)",
        "        if False:\n"
        "            reasons.append(R_NO_TIMING)")
    assert q7 != acc_orig
    results.append(mutate(
        "Q7 a window with no timing evidence passes",
        write(acc_path, q7), write(acc_path, acc_orig),
        "test_missing_timing_fails_rather_than_passing_quietly"))

    # Q8 — missing explanations pass even when the ledger says candidates were explained.
    q8 = acc_orig.replace(
        "        if expected_expl > 0 and not erows and not erows_all:",
        "        if False and not erows and not erows_all:")
    if q8 == acc_orig:
        raise SystemExit("Q8 mutation did not apply; the explanations guard moved")
    results.append(mutate(
        "Q8 explanations may go missing even when the ledger says some were due",
        write(acc_path, q8), write(acc_path, acc_orig),
        "test_missing_explanations_fail_when_the_ledger_says_some_were_due"))

    # Q9 — the order gate stops being judged on every audit.
    q9 = acc_orig.replace("    order_blocking_fail = bool(reasons)",
                          "    order_blocking_fail = False")
    assert q9 != acc_orig
    results.append(mutate(
        "Q9 an order mark stops failing the audit",
        write(acc_path, q9), write(acc_path, acc_orig),
        "test_an_order_mark_fails_every_sleeve_however_far_the_day_got"))

    # Q10 — the route stamp is dropped from the audit record. Coverage and timing are SHARED
    # files that both routes write; a record that does not name its route is read as judging
    # whichever route the reader had in mind.
    q10 = audit_orig.replace('    rec.setdefault("route", ROUTE)', "    rec.pop(\"route\", None)")
    assert q10 != audit_orig
    results.append(mutate(
        "Q10 the audit record loses its route stamp",
        write(audit_path, q10), write(audit_path, audit_orig),
        "test_every_record_is_route_stamped_and_carries_the_reason_codes"))

    # Q11 — the audit writes into the evidence tree instead of beside it.
    q11 = acc_orig.replace('AUDITS_DIR = "global_index/track1_runtime/audits"',
                           'AUDITS_DIR = "global_index/track1_runtime/window_coverage"')
    assert q11 != acc_orig
    results.append(mutate(
        "Q11 the audit writes into the window-coverage evidence directory",
        write(acc_path, q11), write(acc_path, acc_orig),
        "test_the_audit_writes_only_into_its_own_audit_directory"))

    # Q12 — the dashboard stops distinguishing "no audit has run" from silence. The phrase
    # is the guard: a page that renders an empty string where a verdict belongs reads as
    # "nothing to report", which is how an unjudged route comes to look like a healthy one.
    q12 = reader_orig.replace("this is 'not judged yet', not 'passed'", "all good")
    if q12 == reader_orig:
        raise SystemExit("Q12 mutation did not apply; the reader's absence text moved")
    results.append(mutate(
        "Q12 the dashboard stops saying an audit has not run",
        write(reader_path, q12), write(reader_path, reader_orig),
        "test_the_reader_says_not_run_yet_rather_than_leaving_it_blank"))

    # Q13 — an audit job argv gains an order flag.
    q13 = slots_orig.replace(
        '        argv += ["--latest", "--all"]',
        '        argv += ["--latest", "--all", "--allow-orders"]')
    assert q13 != slots_orig
    results.append(mutate(
        "Q13 an audit job argv gains --allow-orders",
        write(slots_path, q13), write(slots_path, slots_orig),
        "test_the_audit_job_argv_carries_no_order_or_broker_flag"))

    # Q14 — the audit fires before its window can have finished writing.
    q14 = slots_orig.replace("AUDIT_BUFFER_MINUTES = 10", "AUDIT_BUFFER_MINUTES = 1")
    assert q14 != slots_orig
    results.append(mutate(
        "Q14 the audit buffer drops below the slot runtime ceiling",
        write(slots_path, q14), write(slots_path, slots_orig),
        "test_the_audit_jobs_fire_after_their_windows_close_with_a_measured_buffer"))

    # Q15 — the mirror stops knowing about the audit jobs. This is the drift that a rename
    # inside the shared table CANNOT produce (one table, both readers move together), so the
    # faithful mutation has to break the mirror itself. An unmirrored job can never be
    # reported overdue, which means an audit that silently stopped running would leave the
    # operator's screen looking exactly as it does when the audit is healthy.
    q15 = status_orig.replace("        for aj in track1_audit_jobs():",
                              "        for aj in []:")
    if q15 == status_orig:
        raise SystemExit("Q15 mutation did not apply; the mirror's audit loop moved")
    results.append(mutate(
        "Q15 the dashboard mirror stops expecting the audit jobs",
        write(status_path, q15), write(status_path, status_orig),
        "test_the_scheduler_and_the_dashboard_mirror_agree_in_every_mode"))

    # Q16 — the headline roll-up goes back to seeding itself at PASS and skipping the
    # pending records. This is the defect as it actually shipped for one draft and was caught
    # on the LIVE tree: four windows pending, and the last line of the report said PASS.
    q16 = audit_orig.replace(
        "    if not judged:\n"
        "        worst = acc.AUDIT_NOT_ENOUGH_DATA_YET",
        "    if False:\n"
        "        worst = acc.AUDIT_NOT_ENOUGH_DATA_YET")
    if q16 == audit_orig:
        raise SystemExit("Q16 mutation did not apply; the roll-up moved")
    results.append(mutate(
        "Q16 the headline says PASS about a set of records that judged nothing",
        write(audit_path, q16), write(audit_path, audit_orig),
        "test_the_headline_never_says_pass_about_a_set_that_judged_nothing"))

    # ── restores, verified by hash, not by trust ─────────────────────────────
    problems = []
    for path, orig in ((acc_path, acc_orig), (audit_path, audit_orig),
                       (slots_path, slots_orig), (reader_path, reader_orig),
                       (status_path, status_orig)):
        now = path.read_text(encoding="utf-8")
        if hashlib.sha256(now.encode()).hexdigest() != hashlib.sha256(orig.encode()).hexdigest():
            problems.append(str(path))
    detected = sum(1 for r in results if r["detected"])
    print()
    print(f"{detected}/{len(results)} mutations detected")
    print("restores verified byte-for-byte"
          if not problems else f"RESTORE MISMATCH: {problems}")
    Path("scratch/_track1_stage5q_mutations.json").write_text(
        json.dumps({"results": results, "detected": detected, "total": len(results),
                    "restore_mismatch": problems}, indent=2), encoding="utf-8")
    return 0 if detected == len(results) and not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
