"""Stage 5ZZT mutation harness — can the new mirror and typing tests turn red?

Two things this stage claims are easy to claim and hard to hold. That the mirror rows sit at the
minutes the scheduler actually runs, which the parity check cannot see because it compares ids.
And that the ladder is one stream while the last look is its own, which is what keeps a
stop-repair sweep from closing a failed data refresh.

Source-level edits in a subprocess, restored afterwards; `run_scheduler.py` is never touched.
The restore compares TEXT rather than bytes: the repo is CRLF and read_text/write_text
translate on the way through.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(r"d:\raits")
TEST = REPO / "scratch" / "test_track1_stage5zzt_schedule_mirror_spy_ladder_20260828.py"
T_5L = REPO / "scratch" / "test_track1_stage5l_shared_preflight_20260823.py"
SS = REPO / "monitor" / "backend" / "schedule_status.py"
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
    print(f"  {'RED  ' if ok else 'GREEN'}  {name:58s} {last}")
    return ok


N = f"{TEST}::"

MUTATIONS = [
    # ── the rows exist ────────────────────────────────────────────────────────────────────
    ("M1 a mirror row is dropped again",
     [(SS, '    ("SPY_REFRESH_PM_R2", 17, 15),\n', "")],
     [N + "test_the_mirror_holds_every_spy_job_at_the_minute_the_scheduler_runs_it",
      N + "test_parity_holds_in_both_modes",
      f"{T_5L}::test_scheduler_and_mirror_are_still_in_parity"]),

    ("M2 the last look is dropped again",
     [(SS, '    ("SPY_LAST_CHANCE_PRE_NKD", 0, 45),\n', "")],
     [N + "test_the_mirror_holds_every_spy_job_at_the_minute_the_scheduler_runs_it",
      N + "test_parity_holds_in_both_modes"]),

    # ── the rows are at the RIGHT MINUTE, which parity cannot see ─────────────────────────
    ("M3 a row is one hour early (parity still passes)",
     [(SS, '    ("SPY_REFRESH_PM_R1", 16, 45),', '    ("SPY_REFRESH_PM_R1", 15, 45),')],
     [N + "test_the_mirror_holds_every_spy_job_at_the_minute_the_scheduler_runs_it",
      N + "test_no_mirror_row_describes_a_job_the_scheduler_does_not_run"]),

    ("M4 the last look is put at 00:00 instead of 00:45",
     [(SS, '    ("SPY_LAST_CHANCE_PRE_NKD", 0, 45),', '    ("SPY_LAST_CHANCE_PRE_NKD", 0, 0),')],
     [N + "test_the_mirror_holds_every_spy_job_at_the_minute_the_scheduler_runs_it"]),

    # ── the streams ───────────────────────────────────────────────────────────────────────
    ("M5 the retry rungs fall back into the catch-all",
     [(JJ, '    if job_id.startswith("SPY_REFRESH_PM"):', '    if job_id == "SPY_REFRESH_PM":')],
     [N + "test_the_three_refresh_rungs_share_one_stream",
      N + "test_none_of_them_falls_into_the_catch_all",
      N + "test_a_stop_repair_sweep_cannot_recover_a_spy_refresh"]),

    ("M6 the last look is folded into the ladder stream",
     [(JJ, '    if job_id == "SPY_LAST_CHANCE_PRE_NKD":\n        return "spy_last_chance_pre_nkd"',
           '    if job_id == "SPY_LAST_CHANCE_PRE_NKD":\n        return "spy_refresh_pm"')],
     [N + "test_the_last_look_is_its_own_stream",
      N + "test_the_last_look_states_its_own_consequence",
      N + "test_the_last_look_is_not_given_the_ladder_wording"]),

    # ── the language ──────────────────────────────────────────────────────────────────────
    ("M7 a recovered rung is told tomorrow will be refused again",
     [(JJ, "                if later_same_stream:\n"
           "                    job[\"impact\"] = (\n"
           "                        \"This rung of the post-close SPY ladder did not run; the series was \"",
           "                if False:\n"
           "                    job[\"impact\"] = (\n"
           "                        \"This rung of the post-close SPY ladder did not run; the series was \"")],
     [N + "test_a_rung_caught_by_a_later_rung_does_not_claim_tomorrow_is_refused"]),

    ("M8 the softening becomes a blanket, so a total failure reads mild",
     [(JJ, "                if later_same_stream:\n"
           "                    job[\"impact\"] = (\n"
           "                        \"This rung of the post-close SPY ladder did not run; the series was \"",
           "                if True:\n"
           "                    job[\"impact\"] = (\n"
           "                        \"This rung of the post-close SPY ladder did not run; the series was \"")],
     [N + "test_a_ladder_that_failed_entirely_still_says_so"]),

    ("M9 the last look loses the Monday case from its wording",
     [(JJ, '                    "run. Nothing after it checks the series before the sleeves do, and on a "\n'
           '                    "Monday the evening ladder last ran thirty-one hours earlier."',
           '                    "run."')],
     [N + "test_the_last_look_states_its_own_consequence"]),
]


def main() -> int:
    print(f"Stage 5ZZT mutations — {len(MUTATIONS)} claims\n")
    results = [expect_red(*m) for m in MUTATIONS]
    caught = sum(results)
    print(f"\n{caught}/{len(results)} mutations caught")
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
