"""Mutation check for the pre-sleep readiness script. 2026-08-24.

    python scratch/track1_presleep_readiness_mutations_20260824.py

The script's whole job is to be able to say NO. A suite that only ever observes it saying
yes has confirmed nothing. Each mutation below removes one way it can say no, on disk, and
runs the suite in a fresh subprocess -- an in-process pytest.main would keep the already
imported module and never see the edit.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"d:\raits")
TARGET = ROOT / "scratch" / "track1_presleep_readiness_20260824.py"
SUITE = "scratch/test_track1_presleep_readiness_20260824.py"

MUTATIONS = [
    (
        "V1 the verdict can no longer be NOT_READY",
        '''    if any(c["blocks_capture"] for c in checks):
        return NOT_READY
    if any(c["status"] == FAIL for c in checks):
        return NOT_READY''',
        '''    if False:
        return NOT_READY''',
    ),
    (
        "V2 a FAIL that does not block capture is silently downgraded",
        '''    if any(c["status"] == FAIL for c in checks):
        return NOT_READY''',
        '''    if any(c["status"] == FAIL and False for c in checks):
        return NOT_READY''',
    ),
    (
        "V3 WARNING collapses into READY -- the stale backend stops being reported",
        '''    if any(c["status"] == WARN for c in checks):
        return WARNING''',
        '''    if False:
        return WARNING''',
    ),
    (
        "P1 an unreadable process table is reported as 'one is running'",
        '''    if not scan.ok:
        # Three outcomes, not two.''',
        '''    if False:
        # Three outcomes, not two.''',
    ),
    (
        "P2 duplicate schedulers stop being counted",
        '''        elif len(scan.processes) > 1:
            trouble.append(kind + "=" + str(scan.pids))''',
        '''        elif False:
            trouble.append(kind + "=" + str(scan.pids))''',
    ),
    (
        "O1 the order gate stops being checked",
        '''    if t1.get("orders_possible"):
        problems.append("orders_possible=True")''',
        '''    if False:
        problems.append("orders_possible=True")''',
    ),
    (
        "O2 the confirmation file stops being checked",
        '''    if (ROOT / "track1_go_live_confirmation.json").exists():''',
        '''    if False:''',
    ),
    (
        "O3 the approval environment variable stops being checked",
        '''    if os.environ.get("TRACK1_ORDERS_APPROVED"):''',
        '''    if False:''',
    ),
    (
        "D1 a missing evidence directory is treated as present",
        '''        if path.is_dir():''',
        '''        if True:''',
    ),
    (
        "B1 a disconnected broker feed passes",
        '''    if connected and freshness == "fresh":''',
        '''    if True:''',
    ),
    (
        "C1 the pre-start check trusts the backend instead of the code on disk",
        '''    if misclassified:''',
        '''    if False:''',
    ),
    (
        "C2 the environment is left mutated after the check",
        '''    finally:
        if previous is None:
            os.environ.pop("RAITS_TRACK1_ONLY", None)
        else:
            os.environ["RAITS_TRACK1_ONLY"] = previous''',
        '''    finally:
        pass''',
    ),
    (
        "N1 the countdown ignores the trading calendar",
        '''            if start > now and is_trading_day(start.date()):''',
        '''            if start > now:''',
    ),
]


def run():
    return subprocess.run(
        [sys.executable, "-m", "pytest", SUITE, "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, timeout=900)


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
    print("target  " + str(TARGET))
    print("sha256  " + digest + "\n")

    baseline = run()
    assert baseline.returncode == 0, baseline.stdout[-3000:]
    print("baseline (unmutated): " + baseline.stdout.strip().splitlines()[-1] + "\n")

    detected = applicable = 0
    try:
        for label, old, new in MUTATIONS:
            if original.count(old) != 1:
                print("[SKIP    ] " + label)
                print("           anchor appears " + str(original.count(old))
                      + "x, not once -- the mutation would not be faithful")
                continue
            applicable += 1
            TARGET.write_text(original.replace(old, new), encoding="utf-8")
            res = run()
            red = res.returncode != 0
            detected += bool(red)
            tail = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else "?"
            print("[" + ("DETECTED" if red else "MISSED  ") + "] " + label)
            print("           " + tail)
    finally:
        TARGET.write_text(original, encoding="utf-8")

    restored = hashlib.sha256(TARGET.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    print("\nrestored sha256 " + restored
          + ("  MATCH" if restored == digest else "  MISMATCH"))
    assert restored == digest, "the target was NOT restored byte-for-byte"
    print("detected " + str(detected) + "/" + str(applicable))
    return 0 if detected == applicable else 1


if __name__ == "__main__":
    raise SystemExit(main())
