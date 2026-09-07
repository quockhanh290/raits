"""Mutation check for the pre-start classification. 2026-08-24.

    python scratch/track1_presleep_mutations_20260824.py

Each mutation removes ONE property of the fix on disk, runs the suite in a FRESH
subprocess (an in-process pytest.main would keep the already-imported module and never see
the edit), and requires the named test to go red. The file is restored and compared
byte-for-byte afterwards.

A test that stays green under a mutation is not testing the thing the mutation removed.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"d:\raits")
TARGET = ROOT / "monitor" / "backend" / "schedule_status.py"
SUITE = "scratch/test_track1_presleep_schedule_status_20260824.py"

MUTATIONS = [
    (
        "M1 the whole pre-start branch is gone",
        '''    if (not matched and scheduler_started is not None and _is_track1_slot(slot["id"])
            and slot["at"] < scheduler_started):''',
        '''    if False:''',
        ["test_nkd_slots_before_scheduler_start_are_not_overdue",
         "test_the_pre_start_slots_are_classified_not_merely_dropped",
         "test_all_twenty_two_nkd_slots_are_covered"],
    ),
    (
        "M2 the boundary is inclusive (<= instead of <)",
        '''and slot["at"] < scheduler_started):''',
        '''and slot["at"] <= scheduler_started):''',
        ["test_a_slot_exactly_at_the_start_instant_is_not_excused"],
    ),
    (
        "M3 the no-evidence guard is dropped -- the clock overrules the log",
        '''    if (not matched and scheduler_started is not None''',
        '''    if (scheduler_started is not None''',
        ["test_evidence_wins_over_the_clock"],
    ),
    (
        "M4 the Track 1 scoping is dropped -- legacy gets excused too",
        '''and _is_track1_slot(slot["id"])\n''',
        '''and True\n''',
        ["test_legacy_slots_are_never_excused_by_this_rule",
         "test_legacy_mode_overdue_count_is_unchanged_by_the_fix"],
    ),
    (
        "M5 an unreadable start time becomes 'no start time' the UNSAFE way",
        '''    except ValueError:\n        return None''',
        '''    except ValueError:\n        return dt.datetime(1970, 1, 1, tzinfo=ET)''',
        ["test_no_known_start_time_means_the_rule_does_not_apply"],
    ),
    (
        "M6 the classifier stops being told the start time at all",
        '''        (_slot, _evidence(_slot, root, today_lines, _started_at)) for _slot in todays_due''',
        '''        (_slot, _evidence(_slot, root, today_lines)) for _slot in todays_due''',
        ["test_nkd_slots_before_scheduler_start_are_not_overdue",
         "test_the_pre_start_slots_are_classified_not_merely_dropped"],
    ),
]


def run(names):
    """The suite in a fresh interpreter, restricted to the tests this mutation should kill."""
    args = [sys.executable, "-m", "pytest", SUITE, "-q", "-p", "no:cacheprovider"]
    for name in names:
        args += ["-k", name] if len(names) == 1 else []
    if len(names) > 1:
        args += ["-k", " or ".join(names)]
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=600)


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
    print(f"target  {TARGET}")
    print(f"sha256  {digest}\n")

    baseline = run([])
    assert "passed" in baseline.stdout, baseline.stdout[-2000:]
    print(f"baseline (unmutated): {baseline.stdout.strip().splitlines()[-1]}\n")

    detected = 0
    try:
        for label, old, new, killers in MUTATIONS:
            if original.count(old) != 1:
                print(f"[SKIP] {label}\n       anchor appears {original.count(old)}x, "
                      f"not once -- the mutation would not be faithful")
                continue
            TARGET.write_text(original.replace(old, new), encoding="utf-8")
            res = run(killers)
            red = res.returncode != 0 and "failed" in res.stdout
            detected += bool(red)
            tail = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else "?"
            print(f"[{'DETECTED' if red else 'MISSED  '}] {label}\n"
                  f"           {tail}")
            if not red:
                print(f"           the tests below stayed green and should not have:\n"
                      f"           {killers}")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    restored = hashlib.sha256(TARGET.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    print(f"\nrestored sha256 {restored}  {'MATCH' if restored == digest else 'MISMATCH'}")
    assert restored == digest, "the target was NOT restored byte-for-byte"

    total = sum(1 for m in MUTATIONS if original.count(m[1]) == 1)
    print(f"detected {detected}/{total}")
    return 0 if detected == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
