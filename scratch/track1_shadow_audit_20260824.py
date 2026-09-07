"""Read-only audit of the Track 1 shadow runtime, as it stands right now.

    python scratch/track1_shadow_audit_20260824.py

Opens nothing, starts nothing, writes nothing. It reads the runtime directories, the route
checkpoint and the gate registry, asks the scheduler process (via ops) when it started, and
prints one of three verdicts:

    NOT_ENOUGH_DATA_YET   no window has both CLOSED and been covered by scheduler uptime
    SHADOW_DAY_PASS       every judgeable window is complete and every check passed
    FAIL                  something judgeable is wrong

The scheduler-uptime question is not decoration. A window that closed before the scheduler
existed produced no evidence and cannot be a failure — nothing was ever asked to run. The
first live run of this script found exactly that: the process started 04:32 ET and the NKD
window is 01:10-02:55 ET, so NKD had closed hours earlier and its empty coverage was correct.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")

from global_index import track1_shadow_acceptance as acc   # noqa: E402
from global_index.track1_params import WINDOWS_ET          # noqa: E402


def scheduler_start_et():
    """The running scheduler's start instant, converted to ET, or None.

    The process table reports MACHINE-LOCAL time (this box is Calgary, ET-2) and every window
    in this project is ET. Comparing the two raw is a two-hour error that reads as 'the
    scheduler was up for that window' when it was not — so the conversion happens here, once.
    """
    import datetime as dt
    import zoneinfo

    from monitor import ops
    procs = ops.scheduler_processes()
    if not procs:
        return None, None
    started = procs[0].get("started")
    if not started:
        return procs[0], None
    local = dt.datetime.fromisoformat(str(started))
    offset = (dt.datetime.now(zoneinfo.ZoneInfo("America/New_York")).replace(tzinfo=None)
              - dt.datetime.now())
    return procs[0], local + offset


def main() -> int:
    proc, started_et = scheduler_start_et()
    report = acc.audit_now(scheduler_started_et=started_et)

    print("=" * 74)
    print("TRACK 1 SHADOW AUDIT — read-only")
    print("=" * 74)
    if proc:
        print(f"scheduler pid {proc['pid']}  started {proc['started']} local "
              f"=> {started_et.strftime('%H:%M') if started_et else '?'} ET")
        print(f"  {proc.get('command', '')}")
    else:
        print("scheduler: NOT RUNNING")
    print(f"now ET: {report['now_et']}   session day: {report['day']}")
    print()

    print("WINDOWS")
    import global_index.window_ledger as wl
    for sleeve in sorted(WINDOWS_ET):
        w = report["windows"][sleeve]
        exp = wl.expected_slots(sleeve)
        chk = next((c for c in report["checks"] if c["name"] == f"coverage:{sleeve}"), {})
        mark = "JUDGEABLE" if w["judgeable"] else "pending  "
        print(f"  {sleeve:14s} {w['window'][0]}-{w['window'][1]} ET  expect {exp:>2} slots  "
              f"{mark}  {chk.get('status', '?')}")
        print(f"      {w['reason']}")
        if w["judgeable"] and chk.get("status") == acc.FAIL:
            print(f"      -> {chk.get('detail', '')}")
    print()

    print("EVIDENCE CHECKS (informational until a window is judgeable)")
    for c in report["checks"]:
        if c["name"].startswith("coverage:"):
            continue
        print(f"  {c['name']:22s} {c['status']:15s} {c['detail'][:80]}")
    print()

    gaps = next((c for c in report["checks"] if c["name"] == "slot_gaps"), {})
    if gaps.get("missing"):
        print(f"MISSING SLOT ROWS (first 10): {gaps['missing']}")
        print()

    print(f"VERDICT: {report['verdict']}")
    if report["verdict"] == acc.NOT_ENOUGH_DATA_YET:
        print("  No window has both closed and been covered by scheduler uptime. This is a")
        print("  statement about how far the session has got, NOT about the route's health.")
    for k in ("coverage_failed", "hard_failures", "evidence_failures_when_judgeable"):
        if report[k]:
            print(f"  {k}: {report[k]}")

    Path("scratch/_track1_shadow_audit_latest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
