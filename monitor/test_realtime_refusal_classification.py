from __future__ import annotations

import datetime as dt
from pathlib import Path


def test_order_gate_refusal_is_not_a_scheduler_incident():
    from monitor.backend.schedule_status import _evidence

    slot = {"id": "TRACK1_NKD_0110",
            "at": dt.datetime(2026, 9, 28, 1, 10, tzinfo=dt.timezone.utc)}
    refused = [
        "2026-09-27 23:10:00  INFO     run_scheduler — [TRACK1_NKD_0110] python -m global_index.run_live_day_track1 --allow-orders",
        "2026-09-27 23:10:02  ERROR    run_scheduler — [TRACK1_NKD_0110] exited with code 2",
        "2026-09-27 23:10:02  ERROR    run_scheduler — [TRACK1_NKD_0110] stdout: REFUSED - order sending was requested and is not available:",
        "2026-09-27 23:10:02  ERROR    run_scheduler — [TRACK1_NKD_0110] stdout: Nothing was run. Re-run without --allow-orders for a shadow pass.",
    ]
    evidence = _evidence(slot, Path("."), refused)
    assert evidence["state"] == "skipped"
    assert evidence["reason"] == "order_gate_refused"
    assert evidence["severity"] == "expected"

    crashed = refused[:2] + [
        "2026-09-27 23:10:02  ERROR    run_scheduler — [TRACK1_NKD_0110] stderr: KeyError: 'entry_time'",
    ]
    evidence = _evidence(slot, Path("."), crashed)
    assert evidence["state"] == "failed"
    assert evidence["severity"] == "incident"


def test_order_gate_refusal_does_not_open_a_job_issue(tmp_path):
    from monitor.backend.job_journal_reader import _parse
    from monitor.backend.open_issue_reader import read_open_issues

    log = tmp_path / "scheduler_0928.log"
    log.write_text("\n".join([
        "2026-09-28 01:10:00  INFO     run_scheduler - [TRACK1_NKD_0110] python -m global_index.run_live_day_track1 --allow-orders",
        "2026-09-28 01:10:02  ERROR    run_scheduler - [TRACK1_NKD_0110] exited with code 2",
        "2026-09-28 01:10:02  ERROR    run_scheduler - [TRACK1_NKD_0110] stdout: REFUSED - order sending was requested and is not available:",
        "2026-09-28 01:10:02  ERROR    run_scheduler - [TRACK1_NKD_0110] stdout: Nothing was run. Re-run without --allow-orders for a shadow pass.",
        "2026-09-28 01:15:00  INFO     run_scheduler - [TRACK1_NKD_0115] python -m global_index.run_live_day_track1",
        "2026-09-28 01:15:02  ERROR    run_scheduler - [TRACK1_NKD_0115] exited with code 1",
        "2026-09-28 01:15:02  ERROR    run_scheduler - [TRACK1_NKD_0115] stderr: KeyError: 'entry_time'",
    ]), encoding="utf-8")

    jobs = {job["job_id"]: job for job in _parse([log], "2026-09-28", [], tmp_path)["jobs"]}
    assert jobs["TRACK1_NKD_0110"]["status"] == "skipped"
    assert jobs["TRACK1_NKD_0110"]["reason"] == "order_gate_refused"
    assert jobs["TRACK1_NKD_0115"]["status"] == "failed"

    issues = read_open_issues(tmp_path)["issues"]
    keys = {issue["key"] for issue in issues}
    assert "job:track1_strategy_slot:track1_nkd:skipped" not in keys
    assert "job:track1_strategy_slot:track1_nkd:failed" in keys
