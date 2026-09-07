"""Stage 5ZZU mutation harness — can the isolation tests turn red?

This stage carries a specific temptation. Every defect it fixes is a job being closed by the
wrong job, so the laziest possible "fix" is to stop closing anything. That would satisfy every
must-not-close test in the suite and be a worse bug than the one it replaced — an issue lane
where nothing ever clears. So M6 and M7 break recovery in the permissive direction and M8 and
M9 break it in the restrictive one, and the suite has to notice both.

Source-level edits in a subprocess, restored afterwards. Nothing under run_scheduler.py or any
other runtime trading file is touched. The restore compares TEXT, not bytes: the repo is CRLF.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(r"d:\raits")
TEST = REPO / "scratch" / "test_track1_stage5zzu_recovery_stream_isolation_20260828.py"
JJ = REPO / "monitor" / "backend" / "job_journal_reader.py"
OI = REPO / "monitor" / "backend" / "open_issue_reader.py"
JS = REPO / "global_index" / "dash" / "realtime" / "realtime.js"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pytest(specs):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
         "-p", "no:randomly", *specs],
        cwd=REPO, capture_output=True, text=True, timeout=1200)


def expect_red(name, edits, specs):
    base = _pytest(specs)
    if base.returncode != 0:
        tail = base.stdout.strip().splitlines()[-1] if base.stdout.strip() else base.stderr[-300:]
        print(f"  [HARNESS BROKEN] {name}: baseline not green — {tail}")
        return False
    originals = {}
    try:
        for path, old, new in edits:
            src = path.read_text(encoding="utf-8")
            originals.setdefault(path, src)
            n = src.count(old)
            if n != 1:
                print(f"  [HARNESS BROKEN] {name}: anchor matched {n}x in {path.name}")
                return False
            path.write_text(src.replace(old, new), encoding="utf-8")
        res = _pytest(specs)
    finally:
        for path, src in originals.items():
            path.write_text(src, encoding="utf-8")
            assert _digest(path.read_text(encoding="utf-8")) == _digest(src), f"restore: {path}"
    last = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""
    ok = res.returncode != 0
    print(f"  {'RED  ' if ok else 'GREEN'}  {name:62s} {last}")
    return ok


N = f"{TEST}::"

MUTATIONS = [
    # ── each type, put back in the catch-all one at a time ────────────────────────────────
    ("M1 the sweeps fall back into the catch-all",
     [(JJ, '    if job_id.startswith("TRACK1_STOP_REPAIR"):\n'
           '        return TRACK1_SAFETY_STOP_REPAIR',
           '    if False:\n        return TRACK1_SAFETY_STOP_REPAIR')],
     [N + "test_no_track1_maintenance_job_is_left_in_the_catch_all",
      N + "test_an_audit_does_not_close_a_failed_sweep",
      N + "test_the_issue_lane_groups_track1_sweeps_together"]),

    ("M2 the audits fall back into the catch-all",
     [(JJ, '    if job_id.startswith("TRACK1_AUDIT"):\n        return TRACK1_WINDOW_AUDIT',
           '    if False:\n        return TRACK1_WINDOW_AUDIT')],
     [N + "test_no_track1_maintenance_job_is_left_in_the_catch_all",
      N + "test_a_sweep_does_not_close_a_failed_audit",
      N + "test_an_audit_failure_talks_about_evidence_and_never_about_the_broker"]),

    ("M3 the max-hold check falls back into the catch-all",
     [(JJ, '    if job_id.startswith(("TRACK1_MAX_HOLD", "TRACK1_MAXHOLD")):\n'
           '        return TRACK1_SAFETY_MAX_HOLD',
           '    if False:\n        return TRACK1_SAFETY_MAX_HOLD')],
     [N + "test_no_track1_maintenance_job_is_left_in_the_catch_all",
      N + "test_an_audit_does_not_close_a_failed_max_hold_check",
      N + "test_both_spellings_of_the_max_hold_id_are_typed"]),

    ("M4 only one spelling of the max-hold id is matched",
     [(JJ, '    if job_id.startswith(("TRACK1_MAX_HOLD", "TRACK1_MAXHOLD")):',
           '    if job_id.startswith("TRACK1_MAXHOLD"):')],
     [N + "test_both_spellings_of_the_max_hold_id_are_typed"]),

    # ── the two routes are collapsed into one stream ──────────────────────────────────────
    ("M5 Track 1 sweeps are typed as legacy sweeps",
     [(JJ, '    if job_id.startswith("TRACK1_STOP_REPAIR"):\n'
           '        return TRACK1_SAFETY_STOP_REPAIR',
           '    if job_id.startswith("TRACK1_STOP_REPAIR"):\n        return "stop_repair"')],
     [N + "test_recovery_matches_on_a_structured_type_not_a_substring",
      N + "test_a_legacy_sweep_does_not_close_a_track1_sweep",
      N + "test_a_track1_sweep_does_not_close_a_legacy_sweep"]),

    # ── the permissive direction: anything closes anything ────────────────────────────────
    ("M6 recovery ignores the stream entirely",
     [(JJ, '            if candidate["job_type"] == job["job_type"]',
           '            if True')],
     [N + "test_an_audit_does_not_close_a_failed_sweep",
      N + "test_a_legacy_sweep_does_not_close_a_track1_sweep"]),

    ("M7 the issue lane stops distinguishing streams",
     [(OI, '    return job["job_type"] if job["job_type"] != "other" else job["job_id"]',
           '    return "any"')],
     [N + "test_the_issue_lane_keeps_sweeps_audits_and_max_hold_apart"]),

    # ── the RESTRICTIVE direction: nothing ever closes ────────────────────────────────────
    ("M8 nothing recovers anything any more (the lazy fix)",
     [(JJ, '            and candidate["status"] in {"completed", "completed_with_debt"}',
           '            and candidate["status"] in set()')],
     [N + "test_a_later_sweep_DOES_close_an_earlier_failed_sweep",
      N + "test_a_later_audit_DOES_close_an_earlier_failed_audit",
      N + "test_the_legacy_sweep_stream_still_recovers_itself"]),

    ("M9 the issue lane goes back to one stream per job id",
     [(OI, '    return job["job_type"] if job["job_type"] != "other" else job["job_id"]',
           '    return job["job_id"]')],
     [N + "test_the_issue_lane_groups_track1_sweeps_together",
      N + "test_the_issue_lane_no_longer_falls_back_to_a_job_id_for_these"]),

    # ── wording ───────────────────────────────────────────────────────────────────────────
    ("M10 the audit is told to reconcile the broker",
     [(JJ, '                    "window. Nothing is at risk in the book; the shadow record has a gap, and "\n'
           '                    "the paper-evidence gate reads that record."',
           '                    "window. Reconcile current broker state before acting."')],
     [N + "test_an_audit_failure_talks_about_evidence_and_never_about_the_broker"]),

    ("M11 the sweep stops naming the Track 1 book",
     [(JJ, '                        "The Track 1 stop-repair sweep did not run, so protective stops on the "\n'
           '                        "Track 1 book were not rechecked at this slot."',
           '                        "The sweep did not run."')],
     [N + "test_a_track1_safety_failure_talks_about_the_track1_book_and_its_stops",
      N + "test_a_sweep_nothing_caught_still_says_the_stops_were_not_rechecked"]),

    # ── the UI ────────────────────────────────────────────────────────────────────────────
    ("M12 the new types lose their scheduler attribution",
     [(JS, "    const SCHEDULER_OWNED = ['stop_repair', 'preflight', 'session_report', 'other',\n"
           "      'track1_safety_stop_repair', 'track1_safety_max_hold', 'track1_window_audit'];",
           "    const SCHEDULER_OWNED = ['stop_repair', 'preflight', 'session_report', 'other'];")],
     [N + "test_the_ui_keeps_these_jobs_attributed_to_the_scheduler"]),

    ("M13 the identifier goes back to being the label",
     [(JS, "        : job.status === 'missed' ? `${jobLabel(job)} slot missed` "
           ": `${jobLabel(job)} failed`;",
           "        : job.status === 'missed' ? `${job.job_id} slot missed` "
           ": `${job.job_id} failed`;")],
     [N + "test_the_ui_labels_jobs_by_type_and_keeps_the_id_for_the_tooltip"]),

    ("M14 an unknown job type renders blank instead of its id",
     [(JS, "    if (!base) return String((job && job.job_id) || 'Unknown job');",
           "    if (!base) return '';")],
     [N + "test_the_ui_falls_back_rather_than_rendering_nothing"]),
]


def main() -> int:
    print(f"Stage 5ZZU mutations — {len(MUTATIONS)} claims\n")
    results = [expect_red(*m) for m in MUTATIONS]
    caught = sum(results)
    print(f"\n{caught}/{len(results)} mutations caught")
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
