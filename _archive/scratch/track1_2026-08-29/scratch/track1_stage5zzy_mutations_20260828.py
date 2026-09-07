"""Stage 5ZZY mutation harness — can the no-shell and sleeve-stream tests turn red?

Two claims to break. That the polled path never reaches the ops reader, which is easy to
reintroduce and invisible in a log. And that recovery is per sleeve, which has a complement:
separating the sleeves must not separate a sleeve from itself, so M7 collapses the streams and
M8 splits them so far apart that a Calm phase cannot recover its own other phase.

Source-level edits in a subprocess, restored afterwards. The restore compares TEXT, not bytes:
the repo is CRLF and read_text/write_text translate on the way through.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(r"d:\raits")
TEST = REPO / "scratch" / "test_track1_stage5zzy_dashboard_poll_no_shell_20260828.py"
SS = REPO / "monitor" / "backend" / "schedule_status.py"
OI = REPO / "monitor" / "backend" / "open_issue_reader.py"
JJ = REPO / "monitor" / "backend" / "job_journal_reader.py"


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
    print(f"  {'RED  ' if ok else 'GREEN'}  {name:60s} {last}")
    return ok


N = f"{TEST}::"

MUTATIONS = [
    # ── the shell-out comes back ──────────────────────────────────────────────────────────
    ("M1 the mode reader calls ops again",
     [(SS, "    rows = _running_schedulers() if processes is None else processes",
           "    from monitor import ops\n"
           "    ops.track1_status()\n"
           "    rows = _running_schedulers() if processes is None else processes")],
     [N + "test_resolve_track1_only_never_calls_ops",
      N + "test_the_mode_helper_never_calls_ops"]),

    ("M2 the retirement reader calls ops again",
     [(OI, "        status = ss.scheduler_track1_mode_status()",
           "        from monitor import ops\n"
           "        ops.track1_status()\n"
           "        status = ss.scheduler_track1_mode_status()")],
     [N + "test_legacy_retirement_never_calls_ops"]),

    # ── the semantics the shell-out used to provide ───────────────────────────────────────
    ("M3 transitional shadow is treated as the safe mode",
     [(SS, '    track1_only = "--track1-only-shadow" in commands',
           '    track1_only = "--track1-shadow" in commands')],
     [N + "test_transitional_shadow_is_not_retirement_compatible",
      N + "test_the_command_line_decides_the_mode"]),

    ("M4 a transitional scheduler reports no legacy entry jobs",
     [(SS, '    out["legacy_entry_jobs"] = 0 if track1_only else len(STATE_SLOTS)',
           '    out["legacy_entry_jobs"] = 0')],
     [N + "test_transitional_shadow_is_not_retirement_compatible",
      N + "test_retirement_follows_the_running_mode"]),

    ("M5 an unreadable command line reports legacy instead of unknown",
     [(SS, '        out["track1_mode_source"] = "unknown"\n        return out',
           '        return out')],
     [N + "test_an_unreadable_command_line_is_unknown_not_legacy"]),

    ("M6 the confirmation is read from the production root whatever it was given",
     [(OI, "def legacy_retirement_state(root: Path | None = None) -> dict[str, Any]:",
           "def legacy_retirement_state(root: Path | None = None) -> dict[str, Any]:\n"
           "    root = None")],
     [N + "test_the_confirmation_is_read_from_the_root_it_was_given",
      N + "test_no_confirmation_means_not_retired"]),

    # ── the sleeve streams, in both directions ────────────────────────────────────────────
    ("M7 every strategy slot shares one recovery stream again",
     [(JJ, "    if job_type != TRACK1_STRATEGY_SLOT:\n        return job_type",
           "    return job_type\n    if job_type != TRACK1_STRATEGY_SLOT:\n        return job_type")],
     [N + "test_a_failed_calm_phase_is_not_recovered_by_a_stress_run",
      N + "test_a_failed_nkd_run_is_not_recovered_by_a_swing_run",
      N + "test_the_issue_lane_agrees_with_the_journal_lane"]),

    ("M8 the stream is split per SLOT, so a sleeve cannot recover itself",
     [(JJ, "            return f\"{TRACK1_STRATEGY_SLOT}:{prefix.rstrip('_').lower()}\"",
           "            return f\"{TRACK1_STRATEGY_SLOT}:{job_id.lower()}\"")],
     [N + "test_both_calm_phases_share_one_stream",
      N + "test_a_sleeve_still_recovers_itself"]),

    ("M9 the issue lane stops agreeing with the journal lane",
     [(OI, "    return _jj.recovery_stream(job)", '    return job["job_type"]')],
     [N + "test_the_issue_lane_agrees_with_the_journal_lane"]),

    ("M10 the finer stream leaks into the job TYPE",
     [(JJ, "def _job_type(job_id: str) -> str:",
           "def _job_type(job_id: str) -> str:\n"
           "    if is_track1_strategy_job(job_id):\n"
           "        return TRACK1_STRATEGY_SLOT + ':leaked'")],
     [N + "test_strategy_slots_are_still_typed_as_strategy_slots"]),
]


def main() -> int:
    print(f"Stage 5ZZY mutations — {len(MUTATIONS)} claims\n")
    results = [expect_red(*m) for m in MUTATIONS]
    caught = sum(results)
    print(f"\n{caught}/{len(results)} mutations caught")
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
