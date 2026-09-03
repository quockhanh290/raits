from __future__ import annotations

import ast
import datetime as dt
import inspect
import json
import os
import re
import types
from pathlib import Path

import pytest

from monitor.backend import ibkr_reader, schedule_status
from monitor.backend.app import app
from monitor.backend.runner_state_reader import read_runner_state
from monitor.backend.runner_event_reader import read_runner_events
from monitor.backend.runner_positions_reader import read_runner_positions
from monitor.backend import report_reader
from monitor.backend.session_event_reader import read_session_events
from monitor.backend.job_journal_reader import read_job_journal
from monitor.backend.open_issue_reader import read_open_issues
from monitor.backend.paper_evidence_reader import read_paper_evidence
from monitor.backend.execution_quality_reader import read_execution_quality


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "monitor" / "backend"
DASH = ROOT / "global_index" / "dash"
ET = schedule_status.ET


def _lines_through(now_et: dt.datetime, *, replace: dict[str, str] | None = None) -> list[str]:
    replace = replace or {}
    lines = []
    for hour, minute in schedule_status.STATE_SLOTS:
        at = dt.datetime.combine(now_et.date(), dt.time(hour, minute), tzinfo=ET)
        if at > now_et:
            continue
        slot_id = schedule_status._slot_id(hour, minute)
        message = replace.get(slot_id, "completed OK")
        if message:
            lines.append(f"2026-08-11 12:00:00 INFO run_scheduler [{slot_id}] {message}")
    return lines


def _patch_logs(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> None:
    monkeypatch.setattr(schedule_status, "_log_signature", lambda _root: (("scheduler.log", 1, 1),))
    monkeypatch.setattr(schedule_status, "_scheduler_lines", lambda _day, _root: list(lines))


def _write_minimal_paper_fixture(root: Path, *, epoch: str = "2026-08-10") -> None:
    global_index = root / "global_index"
    global_index.mkdir(exist_ok=True)
    (global_index / "live_state_data.js").write_text(
        f'window.LIVE_DATA = {{"meta":{{"system_epoch":"{epoch}"}},"snapshots":[{{"date":"{epoch}"}}]}}',
        encoding="utf-8",
    )
    (global_index / "paper_history.json").write_text(
        f'{{"epoch":"{epoch}","account":50000,"days":{{"{epoch}":50000}}}}',
        encoding="utf-8",
    )


def test_state_schedule_has_exactly_45_slots():
    assert len(schedule_status.R4_SLOTS) == 23
    assert len(schedule_status.NKD_SLOTS) == 22
    assert len(schedule_status.STATE_SLOTS) == 45


def test_market_holiday_is_not_expected_yet(tmp_path: Path):
    now = dt.datetime(2026, 4, 3, 12, 0, tzinfo=ET)  # Good Friday
    status = schedule_status.get_schedule_status(tmp_path, observed_at=now - dt.timedelta(hours=12), now=now)
    assert status["trading_day"] is False
    assert status["freshness"] == "not_expected_yet"
    assert status["evidence"]["state"] == "not_scheduled"
    assert status["expected_next_at"].startswith("2026-04-06T05:10:00")


def test_gap_between_windows_is_not_expected_yet(monkeypatch, tmp_path: Path):
    now = dt.datetime(2026, 8, 11, 11, 19, tzinfo=ET)
    lines = _lines_through(now)
    _patch_logs(monkeypatch, lines)
    status = schedule_status.get_schedule_status(tmp_path, observed_at=now - dt.timedelta(hours=8), now=now)
    assert status["active_window"] is False
    assert status["freshness"] == "not_expected_yet"
    assert status["expected_next_at"].endswith("18:05:00Z")
    assert status["next_scheduled_job"]["job_id"] == "STOP_REPAIR_1220"
    assert status["next_scheduled_job"]["at"].endswith("16:20:00Z")
    assert status["next_decision_job"]["job_id"] == "PREFLIGHT"
    assert status["next_decision_job"]["at"].endswith("17:45:00Z")


def test_schedule_separates_operational_jobs_from_decision_pipeline(tmp_path: Path):
    before_maxhold = dt.datetime(2026, 8, 11, 9, 0, tzinfo=ET)
    status = schedule_status.get_schedule_status(tmp_path, now=before_maxhold)
    assert status["next_scheduled_job"]["job_id"] == "MAX_HOLD_EXIT"
    assert status["next_decision_job"]["job_id"] == "MAX_HOLD_EXIT"
    assert status["next_decision_job"]["at"].endswith("13:31:00Z")
    assert any(slot["id"] == "STOP_REPAIR_1020" for slot in schedule_status._scheduled_slots_for(before_maxhold.date()))
    assert all(slot["id"] != "STOP_REPAIR_1020" for slot in schedule_status._pipeline_slots_for(before_maxhold.date()))


def test_failed_slot_is_incident_while_state_remains_fresh(monkeypatch, tmp_path: Path):
    now = dt.datetime(2026, 8, 11, 14, 16, tzinfo=ET)
    lines = _lines_through(now, replace={"LIVE_DAY_1415": "exited with code 1"})
    _patch_logs(monkeypatch, lines)
    status = schedule_status.get_schedule_status(tmp_path, observed_at=now - dt.timedelta(minutes=5), now=now)
    assert status["freshness"] == "fresh"
    assert status["evidence"]["state"] == "failed"
    assert status["evidence"]["severity"] == "incident"
    assert status["incidents"][-1]["slot_id"] == "LIVE_DAY_1415"


def test_incident_recovers_once_a_later_slot_in_the_same_stream_runs(monkeypatch, tmp_path: Path):
    """Live 2026-08-14: IB Gateway restarted itself and refused six NKD slots, then the
    stream ran normally again from 02:30. The rail still read "scheduler attention required"
    hours later, because a bare incident count cannot tell a live outage from one that ended."""
    now = dt.datetime(2026, 8, 11, 14, 31, tzinfo=ET)
    lines = _lines_through(now, replace={"LIVE_DAY_1415": "exited with code 1"})
    _patch_logs(monkeypatch, lines)
    status = schedule_status.get_schedule_status(tmp_path, observed_at=now - dt.timedelta(minutes=1), now=now)
    incident = status["incidents"][-1]
    assert incident["slot_id"] == "LIVE_DAY_1415"
    assert incident["lifecycle"] == "recovered"
    # The FIRST clean slot after the failure is what closes it — 14:20, not the latest one.
    assert incident["recovered_by"] == "LIVE_DAY_1420"
    # The failure stays in the day's record; it just stops driving the live alarm.
    assert status["open_incidents"] == []


def test_incident_stays_open_while_nothing_has_run_since(monkeypatch, tmp_path: Path):
    now = dt.datetime(2026, 8, 11, 14, 16, tzinfo=ET)
    lines = _lines_through(now, replace={"LIVE_DAY_1415": "exited with code 1"})
    _patch_logs(monkeypatch, lines)
    status = schedule_status.get_schedule_status(tmp_path, observed_at=now - dt.timedelta(minutes=5), now=now)
    assert status["incidents"][-1]["lifecycle"] == "open"
    assert status["open_incidents"][-1]["slot_id"] == "LIVE_DAY_1415"


def test_recovery_does_not_cross_streams(monkeypatch, tmp_path: Path):
    """An NKD night slot running is not evidence that the afternoon sleeve recovered."""
    now = dt.datetime(2026, 8, 11, 14, 31, tzinfo=ET)
    lines = _lines_through(now, replace={"LIVE_DAY_1415": "exited with code 1"})
    _patch_logs(monkeypatch, lines)
    status = schedule_status.get_schedule_status(tmp_path, observed_at=now, now=now)
    assert all(item["slot_id"].startswith("LIVE_DAY") for item in status["incidents"])
    assert status["incidents"][-1]["recovered_by"].startswith("LIVE_DAY")


def test_mutex_skip_suppresses_late(monkeypatch, tmp_path: Path):
    now = dt.datetime(2026, 8, 11, 14, 16, tzinfo=ET)
    lines = _lines_through(now, replace={
        "LIVE_DAY_1415": "SKIPPED - previous run_live_day still in flight",
    })
    _patch_logs(monkeypatch, lines)
    status = schedule_status.get_schedule_status(tmp_path, observed_at=now - dt.timedelta(minutes=6), now=now)
    assert status["freshness"] == "fresh"
    assert status["evidence"]["state"] == "skipped"
    assert status["evidence"]["reason"] == "mutex"
    assert status["evidence"]["severity"] == "expected"


def test_older_unexplained_slot_cannot_be_hidden_by_newer_slot(monkeypatch, tmp_path: Path):
    now = dt.datetime(2026, 8, 11, 14, 31, tzinfo=ET)
    lines = _lines_through(now, replace={"LIVE_DAY_1415": ""})
    _patch_logs(monkeypatch, lines)
    status = schedule_status.get_schedule_status(tmp_path, observed_at=now - dt.timedelta(minutes=1), now=now)
    assert status["evidence"]["slot_id"] == "LIVE_DAY_1430"
    assert status["freshness"] == "late"
    assert status["unexplained_overdue"][0]["slot_id"] == "LIVE_DAY_1415"


def test_stale_snapshot_cannot_be_reported_fresh(monkeypatch, tmp_path: Path):
    """C2: `observed_at` từng chỉ được dùng để kiểm tra None. Một
    live_state_data.js 90 ngày tuổi vẫn ra `fresh` trong active window, y hệt
    một file 2 phút tuổi. Đây là đường dẫn 'stale nhìn giống healthy'."""
    now = dt.datetime(2026, 8, 14, 7, 0, tzinfo=dt.timezone.utc)  # 03:00 ET, NKD window
    _patch_logs(monkeypatch, _lines_through(now.astimezone(ET)))

    recent = schedule_status.get_schedule_status(
        tmp_path, observed_at=now - dt.timedelta(minutes=2), now=now)
    ancient = schedule_status.get_schedule_status(
        tmp_path, observed_at=now - dt.timedelta(days=90), now=now)

    assert recent["freshness"] == "fresh"
    assert ancient["freshness"] == "stale"
    assert ancient["state_age_seconds"] > 90 * 86400 - 60


def test_stale_beats_not_expected_yet_outside_the_window(monkeypatch, tmp_path: Path):
    """Ngoài giờ chạy, 'chưa tới lượt' là câu trả lời đúng cho một snapshot mới -
    nhưng không phải cho một snapshot đã bỏ lỡ slot gần nhất."""
    now = dt.datetime(2026, 8, 14, 15, 0, tzinfo=dt.timezone.utc)  # 11:00 ET
    _patch_logs(monkeypatch, _lines_through(now.astimezone(ET)))

    fresh_enough = schedule_status.get_schedule_status(
        tmp_path, observed_at=now - dt.timedelta(minutes=2), now=now)
    ancient = schedule_status.get_schedule_status(
        tmp_path, observed_at=now - dt.timedelta(days=30), now=now)

    assert fresh_enough["freshness"] == "not_expected_yet"
    assert ancient["freshness"] == "stale"


def test_state_age_is_none_when_nothing_was_observed(monkeypatch, tmp_path: Path):
    now = dt.datetime(2026, 8, 14, 15, 0, tzinfo=dt.timezone.utc)
    _patch_logs(monkeypatch, _lines_through(now.astimezone(ET)))
    status = schedule_status.get_schedule_status(tmp_path, observed_at=None, now=now)
    assert status["freshness"] == "missing"
    assert status["state_age_seconds"] is None


def test_runner_state_reader_parses_assignment(tmp_path: Path):
    path = tmp_path / "live_state_data.js"
    path.write_text(
        '// Auto-generated by runner\nwindow.LIVE_DATA = {"meta": {"account": 50000}, "snapshots": []};',
        encoding="utf-8",
    )
    result = read_runner_state(path)
    assert result["source"] == "runner_state"
    assert result["payload"]["meta"]["account"] == 50000
    assert result["freshness"] == "unknown"
    assert result["observed_at"].endswith("Z")


def test_runner_event_reader_keeps_valid_history_and_reports_bad_tail(tmp_path: Path):
    event_log = tmp_path / "global_index" / "runner_events_20260812.jsonl"
    event_log.parent.mkdir()
    event_log.write_text(
        '{"ts":"2026-08-12T05:10:01Z","level":"INFO","category":"STATE","message":"first"}\n'
        '{"ts":"2026-08-12T05:15:01Z","level":"ALERT","category":"GUARD","message":"second"}\n'
        '{"ts":"incomplete"', encoding="utf-8",
    )

    history = read_runner_events("2026-08-12", tmp_path)

    assert [event["message"] for event in history["events"]] == ["first", "second"]
    assert history["coverage_started_at"] == "2026-08-12T05:10:01Z"
    assert history["malformed_lines"] == 1
    assert history["complete"] is False


def test_paper_evidence_uses_durable_artifacts_when_runner_slippage_is_empty(tmp_path: Path):
    global_index = tmp_path / "global_index"
    global_index.mkdir()
    (global_index / "live_state_data.js").write_text(
        'window.LIVE_DATA = {"meta":{"system_epoch":"2026-08-10"},'
        '"snapshots":[{"date":"2026-08-11","slippage":[]}]}',
        encoding="utf-8",
    )
    (global_index / "paper_history.json").write_text(
        '{"epoch":"2026-08-10","account":50000,"days":{"2026-08-10":50100,"2026-08-11":50200}}',
        encoding="utf-8",
    )
    (tmp_path / "trade_log.jsonl").write_text(
        '{"type":"OPEN","inst":"MES","entry_day":"2026-08-10","expected_entry":10,'
        '"fill_price":10.5,"slip":0.5,"contracts":1,"filled_qty":1,"status":"FILLED","regime":"Normal"}\n'
        '{"type":"OPEN","inst":"MYM","entry_day":"2026-08-11","expected_entry":10,'
        '"fill_price":12,"slip":-2,"contracts":1,"filled_qty":1,"status":"FILLED","regime":"Stress"}\n'
        '{"type":"CLOSE","inst":"M2K","entry_day":"2026-08-10","exit_day":"2026-08-11",'
        '"exit_reason":"STP","expected_stop":10,"fill_price":10.2,"slip":0.2,'
        '"contracts":1,"filled_qty":1,"status":"FILLED","regime":"Stress"}\n',
        encoding="utf-8",
    )
    (tmp_path / "slip_stats.json").write_text(
        '{"open_sum":-1.5,"open_n":2,"close_sum":0.2,"close_n":1}',
        encoding="utf-8",
    )
    (tmp_path / "live_day_0811.log").write_text(
        "2026-08-11 12:05:12 INFO run_scheduler - Scheduler started. Ctrl-C to stop.\n"
        "2026-08-11 12:05:13 INFO global_index.runner - B3: broker/file positions match (1 position(s))\n",
        encoding="utf-8",
    )
    (tmp_path / "live_positions.json").write_text(
        '{"positions":[{"inst":"MES","stop_order_id":"42"}]}',
        encoding="utf-8",
    )

    result = read_paper_evidence(tmp_path)
    gates = {gate["key"]: gate for gate in result["payload"]["gates"]}
    coverage = {item["key"]: item for item in result["payload"]["coverage"]}

    assert gates["paper_duration"]["metrics"]["observed"] == 2
    assert gates["regime_coverage"]["status"] == "PASS"
    assert gates["c1_slippage"]["status"] == "SPEC_GAP"
    assert gates["c1_slippage"]["metrics"]["open_n"] == 2
    assert gates["c1_slippage"]["metrics"]["close_n"] == 1
    assert gates["c1_slippage"]["metrics"]["stp_close_n"] == 1
    assert gates["c1_slippage"]["metrics"]["trade_samples"]["total"] == 3
    assert gates["c1_slippage"]["metrics"]["trade_samples"]["rows"][-1]["scope"] == "STP_CLOSE"
    assert gates["c1_slippage"]["metrics"]["trade_samples"]["rows"][-1]["reference_type"] == "expected_stop"
    assert gates["stp_verification"]["metrics"]["trade_details"]["total"] == 2
    assert gates["stp_verification"]["metrics"]["trade_details"]["rows"][0]["scope"] == "OPEN_POSITION"
    assert gates["stp_verification"]["metrics"]["trade_details"]["rows"][-1]["scope"] == "STP_CLOSE"
    assert gates["b3_reconcile"]["status"] == "PASS"
    assert coverage["fill_quality"]["metrics"]["fills"] == 3
    assert coverage["current_protection"]["status"] == "OBSERVED"
    assert coverage["current_protection"]["metrics"]["position_rows"][0]["status"] == "PROTECTED"
    assert coverage["state_persist"]["metrics"]["position_rows"][0]["stop_order_id"] == "42"
    assert coverage["runner_freshness"]["metrics"]["snapshot_rows"][-1]["date"] == "2026-08-11"
    assert coverage["runner_freshness"]["metrics"]["snapshot_rows"][-1]["log_rejected"] == 0
    assert coverage["data_freshness"]["metrics"]["checks"][0]["key"] == "regime_freshness"
    assert coverage["open_incidents"]["metrics"]["issues"] == []
    assert coverage["sample_denominators"]["metrics"]["by_inst"] == {"M2K": 1, "MES": 1, "MYM": 1}
    assert coverage["sample_denominators"]["metrics"]["rows"][0]["scope"] == "instrument"
    assert coverage["same_day_multi_day"]["metrics"]["multi_day"] == 1
    assert coverage["same_day_multi_day"]["metrics"]["same_day"] == 0
    assert coverage["same_day_multi_day"]["metrics"]["unknown"] == 0
    assert coverage["same_day_multi_day"]["metrics"]["rows"][0]["bucket"] == "multi_day"


def test_paper_evidence_log_hygiene_excludes_timestamp_blocks_and_keeps_production_blocks(tmp_path: Path):
    _write_minimal_paper_fixture(tmp_path)
    production_block = [
        "2026-08-10 08:25:13 INFO apscheduler.scheduler - production scheduler heartbeat"
        for _ in range(205)
    ] + [
        "2026-08-10 08:25:13 INFO apscheduler.scheduler - Scheduler started",
        "2026-08-10 08:25:13 INFO run_scheduler - B3: broker/file positions match (2 position(s))",
        # The runner addressing an operator is not an operator having acted. This exact
        # shape ("OPERATOR: ...") is what every B4 NAKED alert ends with, and it was
        # 108 of 128 manual-intervention candidates before the detector was narrowed.
        "2026-08-10 08:25:13 INFO run_scheduler - OPERATOR: normal production note",
        "2026-08-10 08:25:13 INFO run_scheduler - OPERATOR_ACTION: manually closed MES x1",
    ]
    (tmp_path / "scheduler_0810.log").write_text(
        "\n".join([
            "2026-08-10 00:42:35 INFO test - _RecordingMockBroker seeded",
            "2026-08-10 00:42:35 ERROR runner - STP: place_stop FAILED MES LONG @ 5200 cluster=roska4_swing",
            "2026-08-10 00:42:35 INFO runner - B3: 2 mismatch(es) - new entries HALTED until resolved.",
            *production_block,
        ]) + "\n",
        encoding="utf-8",
    )

    payload = read_paper_evidence(tmp_path)["payload"]
    gates = {gate["key"]: gate for gate in payload["gates"]}
    coverage = {item["key"]: item for item in payload["coverage"]}

    hygiene = coverage["log_hygiene"]["metrics"]
    assert hygiene["dropped_test_lines"] == 3
    assert hygiene["excluded_blocks"] == [{
        "path": "scheduler_0810.log",
        "timestamp": "2026-08-10 00:42:35",
        "line_from": 1,
        "line_to": 3,
        "line_count": 3,
        "matched_marker": "_RecordingMockBroker",
    }]
    assert gates["stp_verification"]["metrics"]["stp_failed"] == 0
    assert gates["b3_reconcile"]["metrics"]["episodes"] == 0
    assert gates["b3_reconcile"]["metrics"]["match_episodes"] == 1
    # Exactly one: the OPERATOR_ACTION line. The bare "OPERATOR: ..." note beside it is
    # the runner talking to an operator, and must not be counted as evidence of one.
    assert coverage["manual_intervention"]["metrics"]["candidate_log_lines"] == 1
    rows = coverage["manual_intervention"]["metrics"]["candidate_rows"]
    assert [r for r in rows if "OPERATOR_ACTION" in r["line"]], rows
    assert not [r for r in rows if "normal production note" in r["line"]], rows
    assert payload["summary"]["excluded_blocks"] == hygiene["excluded_blocks"]
    assert payload["summary"]["stp_failed"] == 0


def test_paper_evidence_empty_logs_expose_empty_new_fields_without_false_counts(tmp_path: Path):
    _write_minimal_paper_fixture(tmp_path)

    payload = read_paper_evidence(tmp_path)["payload"]
    gates = {gate["key"]: gate for gate in payload["gates"]}
    coverage = {item["key"]: item for item in payload["coverage"]}

    b3 = gates["b3_reconcile"]["metrics"]
    assert gates["b3_reconcile"]["status"] == "MISSING"
    assert b3["episodes"] == 0
    assert b3["positions_affected"] == 0
    assert b3["first_seen"] is None
    assert b3["last_seen"] is None
    assert b3["raw_line_count"] == 0
    assert b3["raw_mismatch_count"] == 0
    assert b3["cold_starts"] == 0
    assert gates["stp_verification"]["status"] == "MISSING"
    assert gates["stp_verification"]["metrics"]["records"] == []
    assert gates["stp_verification"]["metrics"]["required_sessions"] is None
    assert coverage["log_hygiene"]["metrics"]["excluded_blocks"] == []
    assert payload["summary"]["excluded_blocks"] == []


def _write_stp_verification_fixture(
    root: Path,
    records: list[dict[str, object]],
    *,
    spec: dict[str, object] | None = None,
) -> None:
    _write_minimal_paper_fixture(root)
    monitor = root / "monitor"
    monitor.mkdir(exist_ok=True)
    payload: dict[str, object] = {"stp_verification": records}
    if spec is not None:
        payload["stp_verification_spec"] = spec
    (monitor / "paper_inputs.json").write_text(json.dumps(payload), encoding="utf-8")


def _stp_gate(root: Path) -> dict[str, object]:
    payload = read_paper_evidence(root)["payload"]
    return {gate["key"]: gate for gate in payload["gates"]}["stp_verification"]


def _clean_stp_record(date: str) -> dict[str, object]:
    return {
        "date": date,
        "verified": True,
        "false_halt": False,
        "double_stp": False,
        "evidence": "fixture broker/runner STP proof",
    }


def test_stp_verification_without_spec_is_spec_gap_not_pass(tmp_path: Path):
    _write_stp_verification_fixture(tmp_path, [_clean_stp_record("2026-08-10")])

    gate = _stp_gate(tmp_path)

    assert gate["status"] == "SPEC_GAP"
    assert gate["metrics"]["distinct_sessions"] == 1
    assert gate["metrics"]["required_sessions"] is None


def test_stp_verification_one_clean_session_is_pending_against_required_ten(tmp_path: Path):
    _write_stp_verification_fixture(
        tmp_path,
        [_clean_stp_record("2026-08-10")],
        spec={"min_distinct_sessions": 10},
    )

    gate = _stp_gate(tmp_path)

    assert gate["status"] == "PENDING"
    assert gate["metrics"]["distinct_sessions"] == 1
    assert gate["metrics"]["required_sessions"] == 10


def test_stp_verification_counts_distinct_dates_not_rows(tmp_path: Path):
    records = [_clean_stp_record(f"2026-08-{10 + (idx % 3):02d}") for idx in range(10)]
    _write_stp_verification_fixture(tmp_path, records, spec={"min_distinct_sessions": 10})

    gate = _stp_gate(tmp_path)

    assert gate["status"] == "PENDING"
    assert gate["metrics"]["checks"] == 10
    assert gate["metrics"]["distinct_sessions"] == 3


def test_stp_verification_passes_with_ten_clean_distinct_sessions(tmp_path: Path):
    records = [_clean_stp_record(f"2026-08-{10 + idx:02d}") for idx in range(10)]
    _write_stp_verification_fixture(tmp_path, records, spec={"min_distinct_sessions": 10})

    gate = _stp_gate(tmp_path)

    assert gate["status"] == "PASS"
    assert gate["metrics"]["distinct_sessions"] == 10
    assert gate["metrics"]["required_sessions"] == 10


def test_stp_verification_breaches_on_false_halt_even_with_ten_sessions(tmp_path: Path):
    records = [_clean_stp_record(f"2026-08-{10 + idx:02d}") for idx in range(10)]
    records[4]["false_halt"] = True
    _write_stp_verification_fixture(tmp_path, records, spec={"min_distinct_sessions": 10})

    gate = _stp_gate(tmp_path)

    assert gate["status"] == "BREACH"
    assert gate["metrics"]["false_halts"] == 1
    assert gate["metrics"]["distinct_sessions"] == 10


def test_paper_evidence_single_test_marker_line_is_excluded_without_block(tmp_path: Path):
    _write_minimal_paper_fixture(tmp_path)
    (tmp_path / "scheduler_0810.log").write_text(
        "2026-08-10 00:42:35 INFO test - _RecordingMockBroker seeded\n",
        encoding="utf-8",
    )

    payload = read_paper_evidence(tmp_path)["payload"]
    hygiene = {item["key"]: item for item in payload["coverage"]}["log_hygiene"]["metrics"]

    assert hygiene["dropped_test_lines"] == 1
    assert hygiene["excluded_blocks"] == []
    assert payload["summary"]["excluded_blocks"] == []


def test_paper_evidence_counts_one_cold_start_per_timestamp(tmp_path: Path):
    _write_minimal_paper_fixture(tmp_path)
    (tmp_path / "live_day_0810.log").write_text(
        "2026-08-10 08:25:13 INFO run_scheduler - Scheduler started. Ctrl-C to stop.\n"
        "2026-08-10 08:25:13 INFO apscheduler.scheduler - Scheduler started. Ctrl-C to stop.\n"
        "2026-08-10 08:25:14 INFO run_scheduler - B3: broker/file positions match (1 position(s))\n",
        encoding="utf-8",
    )

    gate = {gate["key"]: gate for gate in read_paper_evidence(tmp_path)["payload"]["gates"]}["b3_reconcile"]

    assert gate["metrics"]["cold_starts"] == 1
    assert gate["status"] == "PASS"


def test_paper_evidence_groups_repeated_b3_mismatch_heartbeats_into_one_episode(tmp_path: Path):
    _write_minimal_paper_fixture(tmp_path)
    start = dt.datetime(2026, 8, 10, 0, 5, 0)
    lines = [
        f"{(start + dt.timedelta(minutes=5 * i)).strftime('%Y-%m-%d %H:%M:%S')} WARN run_scheduler - B3: 2 mismatch(es) - new entries HALTED until resolved."
        for i in range(20)
    ]
    (tmp_path / "live_day_0810.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    gate = {gate["key"]: gate for gate in read_paper_evidence(tmp_path)["payload"]["gates"]}["b3_reconcile"]
    metrics = gate["metrics"]

    assert gate["status"] == "BREACH"
    assert metrics["episodes"] == 1
    assert metrics["mismatches"] == 1
    assert metrics["positions_affected"] == 2
    assert metrics["raw_line_count"] == 20
    assert metrics["raw_mismatch_count"] == 40


# ── Windows tmpdir markers arrive with doubled backslashes ─────────────────────
# The runner logs OSError messages through repr(), so a pytest tmpdir reads
# "...\\Temp\\tmpXXXX\\..." and never matched the "\Temp\tmp" marker. A whole
# mock B3 scenario block survived on that escaping alone and was counted as a
# real mismatch episode.

# ── an unlabelled exit is a measurement gap, not a missing sample ──────────────
# runner.py records exit_reason only on the STP close path (:934); the signal close
# path (:1482) omits it. Reporting that as PENDING told the reviewer to wait for a
# count that can never arrive, because no amount of trading labels a field the
# runner does not write.

def _close_row(inst: str, exit_reason: str | None = None, day: str = "2026-08-10") -> str:
    row = {"type": "CLOSE", "inst": inst, "cluster": "roska4_swing", "direction": "LONG",
           "entry_day": day, "exit_day": day, "fill_price": 100.0, "filled_qty": 1,
           "contracts": 1, "status": "FILLED", "pnl_sized": 10.0}
    if exit_reason is not None:
        row["exit_reason"] = exit_reason
    return json.dumps(row)


def test_exit_paths_report_a_structural_gap_when_no_close_carries_a_reason(tmp_path: Path):
    _write_minimal_paper_fixture(tmp_path)
    (tmp_path / "trade_log.jsonl").write_text(
        "\n".join(_close_row("MES") for _ in range(4)) + "\n", encoding="utf-8")

    gate = {g["key"]: g for g in read_paper_evidence(tmp_path)["payload"]["gates"]}["exit_path_coverage"]

    assert gate["status"] == "STRUCTURAL_GAP", "unlabelled exits must not read as a pending sample"
    assert gate["status"] != "PENDING"
    assert gate["metrics"]["unlabelled_exits"] == 4
    assert gate["metrics"]["labelled_exits"] == 0
    assert gate["metrics"]["instrumentation_gap"] is True
    assert "exit_reason" in gate["evidence"]


def test_exit_paths_stay_pending_when_reasons_exist_but_samples_are_short(tmp_path: Path):
    _write_minimal_paper_fixture(tmp_path)
    (tmp_path / "trade_log.jsonl").write_text(
        _close_row("MES", "STP") + "\n" + _close_row("MYM", "MAX_HOLD") + "\n",
        encoding="utf-8")

    gate = {g["key"]: g for g in read_paper_evidence(tmp_path)["payload"]["gates"]}["exit_path_coverage"]

    # Labelled but below target: this one genuinely does close by waiting.
    assert gate["status"] == "PENDING"
    assert gate["metrics"]["instrumentation_gap"] is False
    assert gate["metrics"]["labelled_exits"] == 2


# ── an enforced rule must never render as "spec missing" ───────────────────────
# H6 moved the Active-rule rails off hardcoded literals and onto metrics.spec.
# b3_reconcile and stp_verification had no spec field, so every rule on those two
# rails read "spec missing" — denying that rules which ARE enforced in code exist
# at all. That is the mirror image of the hardcoding it replaced.

def test_enforced_gate_rules_are_published_as_spec_data(tmp_path: Path):
    _write_minimal_paper_fixture(tmp_path)
    gates = {g["key"]: g for g in read_paper_evidence(tmp_path)["payload"]["gates"]}

    b3_spec = gates["b3_reconcile"]["metrics"].get("spec") or {}
    stp_spec = gates["stp_verification"]["metrics"].get("spec") or {}

    # Exactly the keys the rule rails read; missing any one renders "spec missing".
    # The threshold is on UNCLASSIFIED episodes: a mismatch with a recorded, episode-
    # matched root cause reads EXPLAINED rather than BREACH, so a fixed historical
    # episode stops blocking the epoch forever while anything unexplained still does.
    assert b3_spec.get("max_unclassified_mismatch_episodes") == 0
    assert b3_spec.get("classification_rule")
    assert b3_spec.get("persist_match_required") is True
    assert b3_spec.get("cold_start_reconcile")
    assert b3_spec.get("evidence")
    # These three are enforced by `if false_halts or double_stp or unverified -> BREACH`.
    assert stp_spec.get("max_false_halts") == 0
    assert stp_spec.get("max_double_stp") == 0
    assert stp_spec.get("max_unverified") == 0


def test_rule_rails_state_the_rule_when_spec_exists_and_admit_absence_when_it_does_not():
    script = """
      const esc = v => String(v ?? '');
      const b3Spec = {cold_start_reconcile: 'broker/file positions must match',
                      max_mismatch_episodes: 0, persist_match_required: true,
                      evidence: 'scheduler/live-day logs, grouped into episodes'};
      const stpSpec = {max_false_halts: 0, max_double_stp: 0, max_unverified: 0};
      console.log(JSON.stringify({
        b3WithSpec:   b3RuleRail({spec: b3Spec}),
        b3NoSpec:     b3RuleRail({}),
        stpWithSpec:  stpRuleRail({spec: stpSpec, required_sessions: 10},
                                  {spec: {max_trade_matched_failed: 0}}),
        stpNoSpec:    stpRuleRail({}, {}),
      }));
    """
    out = json.loads(_run_paper_js_helpers(script, helpers=("hasValue", "b3RuleRail", "stpRuleRail")))

    # An enforced rule must be stated, not disclaimed.
    assert "spec missing" not in out["b3WithSpec"], out["b3WithSpec"]
    assert "positions must match" in out["b3WithSpec"]
    assert "spec missing" not in out["stpWithSpec"], out["stpWithSpec"]
    assert "10 distinct sessions" in out["stpWithSpec"]

    # ...but a genuinely absent spec must still be admitted, not back-filled with a
    # hardcoded number. That honesty is the whole point of H6.
    assert "spec missing" in out["b3NoSpec"]
    assert "spec missing" in out["stpNoSpec"]


def test_paper_evidence_drops_test_block_whose_tmpdir_path_is_backslash_escaped(tmp_path: Path):
    _write_minimal_paper_fixture(tmp_path)
    (tmp_path / "live_day_0810.log").write_text(
        "2026-08-10 02:28:21 CRITICAL runner - B3 MISMATCH: file has LONG MES x1 but IBKR shows x0\n"
        "2026-08-10 02:28:21 CRITICAL runner - B3: 1 mismatch(es) - new entries HALTED until resolved.\n"
        "2026-08-10 02:28:21 ERROR runner - B1: state persist failed ([Errno 2] No such file or "
        "directory: 'C:\\\\Users\\\\quock\\\\AppData\\\\Local\\\\Temp\\\\tmpjs8qj72h\\\\positions.tmp')\n"
        "2026-08-10 03:00:00 INFO runner - B3: broker/file positions match (1 position(s))\n",
        encoding="utf-8",
    )

    payload = read_paper_evidence(tmp_path)["payload"]
    gate = {gate["key"]: gate for gate in payload["gates"]}["b3_reconcile"]
    hygiene = {item["key"]: item for item in payload["coverage"]}["log_hygiene"]["metrics"]

    # The escaped tmpdir must still identify the block as test noise.
    assert hygiene["excluded_blocks"], "backslash-escaped tmpdir path was not recognised as a marker"
    assert hygiene["excluded_blocks"][0]["line_count"] == 3
    # ...so the mock scenario must not survive as a real mismatch episode.
    assert gate["metrics"]["episodes"] == 0
    assert gate["metrics"]["mismatches"] == 0


def test_paper_evidence_keeps_production_lines_that_merely_mention_a_path(tmp_path: Path):
    _write_minimal_paper_fixture(tmp_path)
    (tmp_path / "live_day_0810.log").write_text(
        "2026-08-10 02:28:21 CRITICAL runner - B3 MISMATCH: file has LONG MES x1 but IBKR shows x0\n"
        "2026-08-10 02:28:21 CRITICAL runner - B3: 1 mismatch(es) - new entries HALTED until resolved.\n"
        "2026-08-10 02:28:21 INFO runner - state written to D:\\\\raits\\\\global_index\\\\live_positions.json\n",
        encoding="utf-8",
    )

    payload = read_paper_evidence(tmp_path)["payload"]
    gate = {gate["key"]: gate for gate in payload["gates"]}["b3_reconcile"]
    hygiene = {item["key"]: item for item in payload["coverage"]}["log_hygiene"]["metrics"]

    # Collapsing backslashes must not turn an ordinary production path into noise.
    assert hygiene["excluded_blocks"] == []
    assert gate["metrics"]["episodes"] == 1


def test_paper_evidence_counts_candidate_gap_log_lines(tmp_path: Path):
    global_index = tmp_path / "global_index"
    global_index.mkdir()
    (global_index / "live_state_data.js").write_text(
        'window.LIVE_DATA = {"meta":{"system_epoch":"2026-08-10"},"snapshots":[{"date":"2026-08-10"}]}',
        encoding="utf-8",
    )
    (global_index / "paper_history.json").write_text(
        '{"epoch":"2026-08-10","account":50000,"days":{"2026-08-10":50000}}',
        encoding="utf-8",
    )
    (tmp_path / "live_day_0810.log").write_text(
        "2026-08-10 05:10:00 INFO run_live_day - TWS Gateway disconnected before restart\n"
        "2026-08-10 05:12:00 INFO run_live_day - manual override recorded by operator\n"
        "2026-08-10 05:13:00 INFO global_index.runner - STP HOAN: M2K LONG @ 3020.2000 cluster=roska4_swing - dat vao phien sau\n"
        "2026-08-10 05:14:00 INFO global_index.ibkr_broker - place_stop: accepted LONG M2K STP ×1 @ 3020.2000 orderId=288 status=PreSubmitted cluster=roska4_swing\n"
        "2026-08-10 05:15:00 ERROR global_index.runner - STP: place_stop FAILED M2K LONG @ 3020.2000 cluster=roska4_swing - position open without overnight stop protection\n"
        "2026-08-10 05:16:00 INFO global_index.runner - B4: M2K/roska4_swing chua co STP - dang trong cua so hoan CO CHU DICH (vao ngay 2026-08-10). Se dat o lan chay dau tien ngay ke tiep.\n"
        "2026-08-10 05:17:00 WARNING run_live_day -        REJECTED SHORT MNQ (roska4_swing) risk_sized=$3340.54 - roska4_swing gross 8.4% > cap 5.0%\n",
        encoding="utf-8",
    )
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    (monitor / "paper_inputs.json").write_text(
        '{"stp_placement_spec":{"required_continuous_sessions":2,"max_trade_matched_failed":0,'
        '"require_defer_rule":true,"require_system_log":true,"require_ibkr_accept_log":true},'
        '"rejection_coverage_spec":{"required_records":1,"max_unclassified":0,'
        '"require_candidate_identity":true,"require_reason":true,"require_cap_classification":true}}',
        encoding="utf-8",
    )

    payload = read_paper_evidence(tmp_path)["payload"]
    gates = {gate["key"]: gate for gate in payload["gates"]}
    coverage = {item["key"]: item for item in payload["coverage"]}

    assert gates["tws_restart_nights"]["metrics"]["candidate_log_lines"] == 1
    assert gates["tws_restart_nights"]["metrics"]["candidate_days"] == ["2026-08-10"]
    assert gates["stp_verification"]["metrics"]["stp_accepted"] == 1
    assert gates["stp_verification"]["metrics"]["stp_failed"] == 1
    assert gates["stp_verification"]["metrics"]["trade_details"]["total"] == 0
    assert coverage["stp_placement"]["status"] == "BREACH"
    assert coverage["stp_placement"]["metrics"]["accepted"] == 1
    assert coverage["stp_placement"]["metrics"]["failed"] == 1
    assert coverage["stp_placement"]["metrics"]["failed_matched_to_trade"] == 0
    assert coverage["stp_placement"]["metrics"]["failed_unmatched_to_trade"] == 1
    assert coverage["stp_placement"]["metrics"]["required_continuous_sessions"] == 2
    assert coverage["stp_placement"]["metrics"]["continuous_session_streak"] == 0
    assert coverage["stp_placement"]["metrics"]["session_streak"]["sessions"][0]["status"] == "FAIL"
    assert coverage["stp_placement"]["metrics"]["deferred"] == 1
    assert coverage["stp_placement"]["metrics"]["defer_reminders"] == 1
    assert coverage["stp_placement"]["metrics"]["placement_samples"]["total"] == 3
    assert coverage["stp_placement"]["metrics"]["placement_samples"]["rows"][0]["kind"] == "DEFERRED"
    assert coverage["stp_placement"]["metrics"]["placement_samples"]["rows"][1]["order_id"] == "288"
    assert coverage["stp_placement"]["metrics"]["route_reconcile"]["unmatched_failed"][0]["match_status"] == "UNMATCHED_TO_PAPER_OPEN"
    assert "immediate STP after OPEN" in coverage["stp_placement"]["metrics"]["backtest_divergence"]
    assert coverage["rejections"]["status"] == "PASS"
    assert coverage["rejections"]["metrics"]["rejections"] == 1
    assert coverage["rejections"]["metrics"]["cap_blocks"] == 1
    assert coverage["rejections"]["metrics"]["samples"]["rows"][0]["class"] == "cap_gross"
    assert coverage["rejections"]["metrics"]["samples"]["rows"][0]["risk_sized"] == 3340.54
    assert coverage["rejections"]["metrics"]["samples"]["rows"][0]["existing_risk_sized"] == 859.46
    assert coverage["rejections"]["metrics"]["samples"]["rows"][0]["projected_risk_sized"] == 4200.0
    assert coverage["rejections"]["metrics"]["samples"]["rows"][0]["cap_risk_sized"] == 2500.0
    assert coverage["rejections"]["metrics"]["samples"]["rows"][0]["over_cap_risk_sized"] == 1700.0
    assert coverage["runner_freshness"]["metrics"]["snapshot_rows"][-1]["rejected"] == 0
    assert coverage["runner_freshness"]["metrics"]["snapshot_rows"][-1]["log_rejected"] == 1
    assert coverage["manual_intervention"]["metrics"]["candidate_log_lines"] == 1
    assert coverage["manual_intervention"]["metrics"]["candidate_days"] == ["2026-08-10"]
    assert payload["diagnostics"]["manual_intervention_candidate_lines"] == 1
    assert payload["diagnostics"]["manual_intervention_candidate_days"] == ["2026-08-10"]
    assert payload["diagnostics"]["tws_restart_candidate_lines"] == 1
    assert payload["diagnostics"]["tws_restart_candidate_days"] == ["2026-08-10"]


# ── the guard exists to catch a wrong contract, so prove it does ───────────────
# MNKD was routed to IBKR symbol "NKD" (multiplier 5) while specs.py declares the
# micro at 0.50. Every fill executed at ten times the intended size for four days and
# nothing flagged it, because _read_contract_specs iterated BASKET only and MNKD lives
# in SPECS — the guard never asked about the one instrument that was wrong.

def test_contract_spec_guard_breaches_when_ibkr_multiplier_disagrees():
    from monitor.backend.paper_evidence_reader import _contract_spec_guard

    # What IBKR would have returned under the old routing: MNKD resolving to the
    # full-size contract, ten times the multiplier specs.py declares.
    wrong = {
        "MNKD": {"status": "OBSERVED", "point_value": 5.0, "tick": 5.0, "tick_value": 25.0,
                 "local_symbol": "NKDU6", "con_id": 652545722},
    }
    status, evidence, metrics = _contract_spec_guard({"connected": True, "contract_specs": wrong})
    row = {r["inst"]: r for r in metrics["rows"]}["MNKD"]

    assert row["status"] == "BREACH", (
        "a contract whose IBKR multiplier is ten times the local point_value must breach"
    )
    assert row["checks"]["point_value"] is False
    assert status == "BREACH"
    assert "mismatch" in evidence


def test_contract_spec_guard_covers_specs_not_just_basket():
    """The gap that let the defect through: MNKD is in SPECS, not BASKET."""
    from futures.basket import BASKET
    from global_index.specs import SPECS
    from monitor.backend.paper_evidence_reader import _local_contract_specs

    covered = set(_local_contract_specs())
    assert set(BASKET) <= covered
    assert set(SPECS) <= covered, (
        f"instruments absent from the guard cannot be reported as unreconciled: "
        f"{sorted(set(SPECS) - covered)}"
    )

    source = (ROOT / "monitor" / "backend" / "ibkr_reader.py").read_text(encoding="utf-8")
    assert "for inst in BASKET:" not in source, (
        "_read_contract_specs must query SPECS too, or MNKD is never asked about"
    )


def test_contract_specs_do_not_publish_two_meanings_under_one_name():
    """`contract_month` must mean the same thing here as it does in the book.

    IBKR answers lastTradeDateOrContractMonth with a full DATE — measured live
    2026-08-17: 20260918 for the Rổ 4 micros, 20260910 for the Nikkei leg. The runner
    normalises that to YYYYMM before it reaches live_positions.json, so the book says
    202609. This reader published the raw 8-digit value under the SAME key, and the two
    surfaces then disagreed on screen about a value neither of them was wrong about.

    That is the defect Fill.__post_init__ was written to prevent — "the book must not
    carry two spellings of one month" — closed on one producer and left open on the
    other.

    The date is not thrown away: it is the expiry, which is the most useful thing a
    contract-spec row can show, so it keeps its own name.
    """
    from monitor.backend import ibkr_reader

    class _Detail:
        def __init__(self):
            self.contract = types.SimpleNamespace(
                symbol="MES", localSymbol="MESU6", exchange="CME", conId=1,
                multiplier="5", lastTradeDateOrContractMonth="20260918")
            self.minTick = 0.25

    class _IB:
        def reqContractDetails(self, _c):
            return [_Detail()]

    fake_ibi = types.SimpleNamespace(
        Future=lambda *a, **k: types.SimpleNamespace(**k))
    specs = ibkr_reader._read_contract_specs(_IB(), fake_ibi)
    assert specs, "the reader returned nothing — the locator is broken, not satisfied"
    row = next(iter(specs.values()))
    assert row.get("status") == "OBSERVED", f"unexpected row: {row}"

    assert row.get("contract_month") == "202609", (
        f"the dashboard publishes a different spelling of the month than the book, "
        f"under the same key: {row.get('contract_month')!r}")
    assert row.get("last_trade_date") == "20260918", (
        f"the expiry is the useful half of that value and must not be lost: {row}")


def test_paper_evidence_contract_spec_guard_reconciles_ibkr_cache(monkeypatch, tmp_path: Path):
    global_index = tmp_path / "global_index"
    global_index.mkdir()
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    (global_index / "live_state_data.js").write_text(
        'window.LIVE_DATA = {"meta":{"system_epoch":"2026-08-10"},"snapshots":[{"date":"2026-08-10"}]}',
        encoding="utf-8",
    )
    (global_index / "paper_history.json").write_text(
        '{"epoch":"2026-08-10","account":50000,"days":{"2026-08-10":50000}}',
        encoding="utf-8",
    )
    (tmp_path / "trade_log.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "slip_stats.json").write_text("{}", encoding="utf-8")
    (tmp_path / "live_positions.json").write_text('{"positions":[]}', encoding="utf-8")
    (monitor / "paper_inputs.json").write_text("{}", encoding="utf-8")

    specs = {
        "MES": {"status": "OBSERVED", "point_value": 5.0, "tick": 0.25, "tick_value": 1.25},
        "MNQ": {"status": "OBSERVED", "point_value": 2.0, "tick": 0.25, "tick_value": 0.5},
        "MYM": {"status": "OBSERVED", "point_value": 0.5, "tick": 1.0, "tick_value": 0.5},
        "M2K": {"status": "OBSERVED", "point_value": 5.0, "tick": 0.1, "tick_value": 0.5},
        "NKD": {"status": "OBSERVED", "point_value": 5.0, "tick": 5.0, "tick_value": 25.0},
        "MNKD": {"status": "OBSERVED", "point_value": 0.5, "tick": 5.0, "tick_value": 2.5},
    }
    monkeypatch.setattr(ibkr_reader, "get_cache", lambda: {
        "connected": True,
        "last_update": "2026-08-14T00:00:00Z",
        "contract_specs": specs,
    })
    payload = read_paper_evidence(tmp_path)["payload"]
    coverage = {item["key"]: item for item in payload["coverage"]}

    assert coverage["contract_spec_guard"]["status"] == "OBSERVED"
    assert coverage["contract_spec_guard"]["metrics"]["mismatches"] == 0
    assert {row["inst"] for row in coverage["contract_spec_guard"]["metrics"]["rows"]} >= {"MES", "MNQ", "MYM", "M2K", "NKD", "MNKD"}
    assert coverage["contract_spec_guard"]["metrics"]["rows"][0]["checks"]["point_value"] is True

    bad_specs = {**specs, "MES": {**specs["MES"], "point_value": 50.0, "tick_value": 12.5}}
    monkeypatch.setattr(ibkr_reader, "get_cache", lambda: {
        "connected": True,
        "last_update": "2026-08-14T00:00:01Z",
        "contract_specs": bad_specs,
    })
    payload = read_paper_evidence(tmp_path)["payload"]
    coverage = {item["key"]: item for item in payload["coverage"]}

    assert coverage["contract_spec_guard"]["status"] == "BREACH"
    assert coverage["contract_spec_guard"]["metrics"]["mismatches"] == 1


def test_paper_evidence_uses_monitor_paper_inputs_to_unblock_gaps(tmp_path: Path):
    global_index = tmp_path / "global_index"
    global_index.mkdir()
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    (global_index / "live_state_data.js").write_text(
        'window.LIVE_DATA = {"meta":{"system_epoch":"2026-08-10"},"snapshots":[{"date":"2026-08-10"}]}',
        encoding="utf-8",
    )
    (global_index / "paper_history.json").write_text(
        '{"epoch":"2026-08-10","account":50000,"days":{"2026-08-10":50000}}',
        encoding="utf-8",
    )
    (tmp_path / "trade_log.jsonl").write_text(
        '{"type":"OPEN","inst":"MES","entry_day":"2026-08-10","slip":0.25,"regime":"Normal"}\n'
        '{"type":"OPEN","inst":"MES","entry_day":"2026-08-10","slip":0.25,"regime":"Normal"}\n'
        '{"type":"CLOSE","inst":"MES","entry_day":"2026-08-10","exit_day":"2026-08-10",'
        '"exit_reason":"STP","slip":0.25,"regime":"Normal"}\n'
        '{"type":"CLOSE","inst":"MES","entry_day":"2026-08-10","exit_day":"2026-08-10",'
        '"exit_reason":"STP","slip":0.25,"regime":"Normal"}\n',
        encoding="utf-8",
    )
    (monitor / "paper_inputs.json").write_text(
        '{"c1_spec":{"open":{"scope":"by_inst","min_n_per_inst":2,"max_mean_ticks":2},'
        '"stp_close":{"scope":"pooled","min_n":2,"max_mean_ticks":2},'
        '"close_scope":"stp_only","use_absolute":true},'
        '"fill_quality_spec":{"min_fills":4,"max_partial_rate":0,"max_failed_or_cancelled":0,'
        '"require_complete_fields":false,"max_contracts_tested":1,"retest_when_contracts_gt":1},'
        '"stp_verification_spec":{"min_distinct_sessions":10},'
        '"stp_verification":['
        '{"date":"2026-08-10","verified":true,"false_halt":false,"double_stp":false},'
        '{"date":"2026-08-11","verified":true,"false_halt":false,"double_stp":false},'
        '{"date":"2026-08-12","verified":true,"false_halt":false,"double_stp":false},'
        '{"date":"2026-08-13","verified":true,"false_halt":false,"double_stp":false},'
        '{"date":"2026-08-14","verified":true,"false_halt":false,"double_stp":false},'
        '{"date":"2026-08-15","verified":true,"false_halt":false,"double_stp":false},'
        '{"date":"2026-08-16","verified":true,"false_halt":false,"double_stp":false},'
        '{"date":"2026-08-17","verified":true,"false_halt":false,"double_stp":false},'
        '{"date":"2026-08-18","verified":true,"false_halt":false,"double_stp":false},'
        '{"date":"2026-08-19","verified":true,"false_halt":false,"double_stp":false}],'
        '"tws_restart_spec":{"min_nights":1},'
        '"tws_restart_nights":[{"night":"2026-08-10","restart_proven":true,"runner_resumed":true,"broker_verified":true}],'
        '"manual_interventions":[{"ts":"2026-08-10T05:12:00Z","resolution_status":"resolved","post_action_verified":true}],'
        '"roll_slippage":[{"date":"2026-08-10","ticks":1.5}],'
        '"paper_vs_backtest_spec":{"require_base_alignment":true,"require_signal_level_classification":true,'
        '"require_trade_level_classification":true,"require_current_curve":true,'
        '"max_unresolved_signals":0,"max_unresolved_entries":0,"max_unresolved_trades":0,'
        '"max_signal_price_diff":0,"max_signal_risk_diff_when_available":1,'
        '"require_ibkr_ledger_bridge":false},'
        '"paper_vs_backtest":[{"date":"2026-08-10","actual_equity":50012,"expected_equity":50000,'
        '"evidence":"reviewed daily compare"}]}',
        encoding="utf-8",
    )
    (monitor / "paper_pnl_compare.json").write_text(
        '{"convention":{"epoch":"2026-08-10","account":50000,"curve_generated":"2026-08-10",'
        '"actual_equity_source":"system_ledger_realized_only",'
        '"actual_equity_note":"Actual is runner system equity from paper_history/live_state, not IBKR NetLiquidation.",'
        '"formula_account_window":"account + (backtest_curve[date] - backtest_curve[epoch])",'
        '"formula_trade_filter":"account + cumulative pnl for trades with entry_day >= epoch",'
        '"formula_paper_trade_filter":"account + cumulative paper trade_log pnl_sized"},'
        '"pnl_reconcile":{"actual_source":"paper_history.days","actual_semantics":"runner system ledger / sleeve equity, realised-only by design",'
        '"not_ibkr_equity":true,"broker_equity_context":{"value":996280.77,"not_used_for_pnl_compare":true},'
        '"realtime_system_ledger_pnl":12,"realtime_system_ledger_formula":"live_state.meta.final_equity - paper_history.account",'
        '"realtime_final_equity":50012,"realtime_account_base":50000,"paper_closed_trade_realized":12,'
        '"system_ledger_offset_vs_paper_closed_trades":0,'
        '"bridge_note":"system ledger is not broker equity"},'
        '"daily":[{"date":"2026-08-10","actual_equity":50012,"expected_equity_trade_filter":50000,'
        '"actual_equity_source":"system_ledger_realized_only","paper_trade_filter_equity":50012,'
        '"system_ledger_vs_trade_filter":0,"paper_trade_realized_cum":12,"backtest_trade_realized_cum":0,'
        '"expected_equity_account_window":50000,"account_window_diff":12,'
        '"trade_filter_realized_diff":0,"curve_status":"covered"}],'
        '"trade_filter":{"classified":{"counts":{"MATCHED_SAME_DATES":1,"KNOWN_EXIT_TIMING_DRIFT":1},'
        '"unresolved":0,"rows":[{"classification":"MATCHED_SAME_DATES","trade_id":"MES|swing|LONG|2026-08-10",'
        '"inst":"MES","cluster":"swing",'
        '"direction":"LONG","entry_day":"2026-08-10","paper_exit_day":"2026-08-10",'
        '"backtest_exit_day":"2026-08-10","paper_pnl":12,"backtest_pnl":12,"pnl_diff":0,'
        '"reason":"same instrument, cluster, direction, entry day, and exit day"},'
        '{"classification":"KNOWN_EXIT_TIMING_DRIFT","trade_id":"MNKD|global_nkd|LONG|2026-08-10",'
        '"inst":"MNKD","cluster":"global_nkd",'
        '"direction":"LONG","entry_day":"2026-08-10","paper_exit_day":"2026-08-10",'
        '"backtest_exit_day":"2026-08-11","exit_day_delta":-1,"paper_pnl":-110,'
        '"backtest_pnl":-54.34,"pnl_diff":-55.66,'
        '"reason":"same trade identity but paper/live exit day differs"}]}},'
        '"signal_compare":{"classified":{"counts":{"MATCHED_SIGNAL":1},'
        '"unresolved":0,"rows":[{"classification":"MATCHED_SIGNAL","date":"2026-08-10",'
        '"inst":"MES","cluster":"swing","direction":"LONG","action":"OPEN",'
        '"paper_count":1,"backtest_count":1,"reason_code":"MATCHED_DECISION","reason":"same signal",'
        '"price_compare_status":"MATCH","risk_compare_status":"MISSING"}]}},'
        '"entry_compare":{"counts":{"MATCHED_ENTRY":1},"unresolved":0,'
        '"rows":[{"classification":"MATCHED_ENTRY","trade_id":"MES|swing|LONG|2026-08-10",'
        '"date":"2026-08-10","inst":"MES",'
        '"cluster":"swing","direction":"LONG","paper_fill_price":5001,'
        '"paper_expected_entry":5000,"backtest_entry_price":5000,'
        '"broker_statement_price":5001,"broker_verified":true,"reason":"same entry"}]},'
        '"lifecycle_compare":{"counts":{"MATCHED_LIFECYCLE":1},"unresolved":0,'
        '"paper_minus_backtest_sum":0,"paper_minus_flex_sum":0,'
        '"rows":[{"classification":"MATCHED_LIFECYCLE","trade_id":"MES|swing|LONG|2026-08-10",'
        '"inst":"MES","cluster":"swing",'
        '"direction":"LONG","entry_day":"2026-08-10",'
        '"paper":{"status":"CLOSED","entry_price":5001,"exit_day":"2026-08-10","pnl":12},'
        '"backtest":{"status":"CLOSED","entry_price":5000,"exit_day":"2026-08-10","pnl":12},'
        '"flex":{"status":"CLOSED","entry_price":5001,"exit_day":"2026-08-10","pnl":12},'
        '"paper_minus_backtest_pnl":0,"paper_minus_flex_pnl":0,"reason":"same lifecycle"}]},'
        '"signal_path_audit":{"status":"OBSERVED","focus":"fixture","dependency_note":"events depend on held positions"},'
        '"backtest_artifact_audit":{"status":"BREACH","focus":"M2K LONG OPEN on 2026-08-10",'
        '"classification":"REPLAY_SNAPSHOT_STALE_OR_INCONSISTENT_WITH_CURRENT_CHECKPOINT",'
        '"replay_snapshot_has_m2k_entry":false,"current_checkpoint_has_m2k_long":true},'
        '"statement_pnl_compare":{"status":"OBSERVED","source":"monitor/inputs/ibkr_flex/flex.csv",'
        '"epoch":"2026-08-10","actual_system_ledger_semantics":"runner realised trade ledger / sleeve equity, not IBKR NetLiquidation",'
        '"paper_epoch_closed_realized":12,"backtest_epoch_closed_realized":12,"paper_minus_backtest_realized":0,'
        '"flex_epoch_rebased_realized":12,"paper_minus_flex_epoch_rebased_realized":0,'
        '"flex_ledger_aligned_realized":12,"paper_minus_flex_ledger_aligned_realized":0,'
        '"ledger_aligned_minus_system_ledger_pnl":0,'
        '"ledger_alignment_override":{"status":"INACTIVE","scope":"selective","reason":"fixture",'
        '"global_rebase_changed":false,"included_carry_closed":[]},'
        '"raw_statement_entry_epoch_realized":12,"statement_entry_epoch_realized":12,'
        '"paper_minus_statement_entry_epoch_realized":0,'
        '"excluded_pre_epoch_exit_window_realized":272,"excluded_pre_epoch_closed_count":1,'
        '"latest_system_ledger_vs_paper_trade_filter":272,'
        '"ledger_offset_explanation":"MATCH_PRE_EPOCH_CARRY_FILL","paper_flex_bridge":[],'
        '"paper_flex_bridge_diff_sum":0,'
        '"flex_epoch_rebased_closed":[],"flex_epoch_rebased_open_lots":[],"flex_epoch_rebased_ignored_count":0,'
        '"raw_statement_entry_epoch_closed":[],"ledger_offset_matching_carry_closed":[],'
        '"raw_statement_entry_epoch_open_lots":[]},'
        '"ibkr_statement":{"status":"OBSERVED","path":"monitor/inputs/ibkr_flex/flex.csv",'
        '"fills_count":2,"closed_count":1,"open_lot_count":0},'
        '"verdicts":{"trade_master":{"status":"PASS","title":"Trade master reconcile",'
        '"summary":"fixture verdict","facts":["rows 1"],"target":"pnl-tab-trades"},'
        '"timeline":{"status":"PASS","title":"Timeline reconcile","summary":"fixture timeline",'
        '"facts":["paper RECONCILED"],"target":"pnl-tab-timeline"}},'
        '"open_position_parity":{"status":"MATCH","paper_day":"2026-08-10","replay_day":"2026-08-10",'
        '"paper_open_count":0,"replay_open_count":0,"paper_only":[],"backtest_only":[]}}',
        encoding="utf-8",
    )

    payload = read_paper_evidence(tmp_path)["payload"]
    gates = {gate["key"]: gate for gate in payload["gates"]}
    coverage = {item["key"]: item for item in payload["coverage"]}

    assert gates["c1_slippage"]["status"] == "PASS"
    assert gates["stp_verification"]["status"] == "PASS"
    assert gates["tws_restart_nights"]["status"] == "PASS"
    assert coverage["manual_intervention"]["status"] == "OBSERVED"
    assert coverage["roll_slippage"]["status"] == "OBSERVED"
    assert coverage["paper_vs_backtest"]["status"] == "PASS"
    assert coverage["paper_vs_backtest"]["metrics"]["source_kind"] == "paper_inputs"
    assert coverage["paper_vs_backtest"]["metrics"]["latest"]["divergence_pct"] == pytest.approx(0.00024)
    assert coverage["paper_vs_backtest"]["metrics"]["base_audit"]["paper_account_base"] == 50000
    assert coverage["paper_vs_backtest"]["metrics"]["base_audit"]["backtest_reset_to_account"] is True
    assert coverage["paper_vs_backtest"]["metrics"]["contract_specs"]["MNKD"]["point_value"] == 0.5
    assert coverage["paper_vs_backtest"]["metrics"]["timeline"][0]["divergence_side"] == "FLAT"
    assert coverage["fill_quality"]["status"] == "PASS"
    assert coverage["fill_quality"]["metrics"]["status_rules"]
    assert coverage["fill_quality"]["metrics"]["max_contracts_tested"] == 1
    assert "must be retested" in coverage["fill_quality"]["metrics"]["scale_note"]
    assert coverage["fill_quality"]["metrics"]["trade_samples"]["total"] == 4
    assert coverage["fill_quality"]["metrics"]["trade_samples"]["rows"][-1]["type"] == "CLOSE"
    trade_compare = coverage["paper_vs_backtest"]["metrics"]["trade_compare"]
    assert trade_compare["counts"]["KNOWN_EXIT_TIMING_DRIFT"] == 1
    assert trade_compare["unresolved"] == 0
    assert trade_compare["rows"][-1]["classification"] == "KNOWN_EXIT_TIMING_DRIFT"
    assert "trade_id" in trade_compare["rows"][-1]
    assert trade_compare["signal_compare"]["counts"]["MATCHED_SIGNAL"] == 1
    assert trade_compare["signal_compare"]["unresolved"] == 0
    assert trade_compare["entry_compare"]["counts"]["MATCHED_ENTRY"] == 1
    assert trade_compare["entry_compare"]["rows"][0]["broker_verified"] is True
    assert trade_compare["lifecycle_compare"]["counts"]["MATCHED_LIFECYCLE"] == 1
    assert trade_compare["lifecycle_compare"]["paper_minus_backtest_sum"] == 0
    assert trade_compare["lifecycle_compare"]["rows"][0]["flex"]["status"] == "CLOSED"
    assert trade_compare["signal_path_audit"]["status"] == "OBSERVED"
    assert trade_compare["backtest_artifact_audit"]["current_checkpoint_has_m2k_long"] is True
    assert trade_compare["statement_pnl_compare"]["ledger_offset_explanation"] == "MATCH_PRE_EPOCH_CARRY_FILL"
    assert trade_compare["statement_pnl_compare"]["flex_ledger_aligned_realized"] == 12
    assert trade_compare["statement_pnl_compare"]["ledger_alignment_override"]["global_rebase_changed"] is False
    assert trade_compare["ibkr_statement"]["status"] == "OBSERVED"
    assert trade_compare["pnl_reconcile"]["not_ibkr_equity"] is True
    assert trade_compare["pnl_reconcile"]["realtime_system_ledger_pnl"] == 12
    assert trade_compare["open_position_parity"]["status"] == "MATCH"
    assert trade_compare["verdicts"]["trade_master"]["status"] == "PASS"
    assert trade_compare["verdicts"]["timeline"]["target"] == "pnl-tab-timeline"
    assert payload["diagnostics"]["paper_inputs_error"] is None
    assert payload["diagnostics"]["paper_pnl_compare_error"] is None


def test_paper_evidence_does_not_count_actual_only_paper_vs_backtest_as_observed(tmp_path: Path):
    global_index = tmp_path / "global_index"
    global_index.mkdir()
    (global_index / "live_state_data.js").write_text(
        'window.LIVE_DATA = {"meta":{"system_epoch":"2026-08-10"},'
        '"snapshots":[{"date":"2026-08-10","paper_vs_backtest":{'
        '"actual_equity":50228.75,"expected_equity":null,"divergence_pct":null}}]}',
        encoding="utf-8",
    )
    (global_index / "paper_history.json").write_text(
        '{"epoch":"2026-08-10","account":50000,"days":{"2026-08-10":50228.75}}',
        encoding="utf-8",
    )

    payload = read_paper_evidence(tmp_path)["payload"]
    coverage = {item["key"]: item for item in payload["coverage"]}

    assert coverage["paper_vs_backtest"]["status"] == "NEEDS_DECISION"
    assert coverage["paper_vs_backtest"]["metrics"]["source_kind"] == "live_state_incomplete"
    assert "Paper P&L vs backtest source" in {gap["title"] for gap in payload["gaps"]}
    pvb_gap = next(gap for gap in payload["gaps"] if gap["title"] == "Paper P&L vs backtest source")
    assert pvb_gap["type"] == "DATA_GAP"
    assert pvb_gap["target_path"] == "monitor/paper_pnl_compare.json"
    assert pvb_gap["related_key"] == "paper_vs_backtest"
    assert pvb_gap["status"] == "NEEDS_ARTIFACT"
    assert "generated epoch compare artifact" in pvb_gap["purpose"]


def test_paper_evidence_excludes_signal_close_from_c1_slippage(tmp_path: Path):
    global_index = tmp_path / "global_index"
    global_index.mkdir()
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    (global_index / "live_state_data.js").write_text(
        'window.LIVE_DATA = {"meta":{"system_epoch":"2026-08-10"},"snapshots":[{"date":"2026-08-10"}]}',
        encoding="utf-8",
    )
    (global_index / "paper_history.json").write_text(
        '{"epoch":"2026-08-10","account":50000,"days":{"2026-08-10":50000}}',
        encoding="utf-8",
    )
    (tmp_path / "trade_log.jsonl").write_text(
        '{"type":"OPEN","inst":"MES","entry_day":"2026-08-10","slip":0.25,"regime":"Normal"}\n'
        '{"type":"CLOSE","inst":"MES","entry_day":"2026-08-10","exit_day":"2026-08-10",'
        '"expected_stop":7777.0,"fill_price":7753.75,"slip":-23.25,"regime":"Normal"}\n',
        encoding="utf-8",
    )
    (monitor / "paper_inputs.json").write_text(
        '{"c1_spec":{"open":{"scope":"by_inst","min_n_per_inst":1,"max_mean_ticks":5},'
        '"stp_close":{"scope":"pooled","min_n":1,"max_mean_ticks":5},'
        '"close_scope":"stp_only","use_absolute":true}}',
        encoding="utf-8",
    )

    gate = {gate["key"]: gate for gate in read_paper_evidence(tmp_path)["payload"]["gates"]}["c1_slippage"]

    assert gate["metrics"]["open_n"] == 1
    assert gate["metrics"]["stp_close_n"] == 0
    assert gate["metrics"]["signal_close_with_stop_ref"] == 1
    assert gate["metrics"]["trade_samples"]["rows"][-1]["scope"] == "EXCLUDED_CLOSE"
    assert gate["metrics"]["trade_samples"]["rows"][-1]["reference_type"] == "protective_stop_reference"
    assert "signal/market CLOSE excluded 1" in gate["evidence"]


def test_paper_evidence_payload_contract_is_stable(tmp_path: Path):
    global_index = tmp_path / "global_index"
    global_index.mkdir()
    (global_index / "live_state_data.js").write_text(
        'window.LIVE_DATA = {"meta":{"system_epoch":"2026-08-10"},'
        '"snapshots":[{"date":"2026-08-10","paper_vs_backtest":{},'
        '"operational_status":{"positions":{"persist_match":true}}}]}',
        encoding="utf-8",
    )
    (global_index / "paper_history.json").write_text(
        '{"epoch":"2026-08-10","account":50000,"days":{"2026-08-10":50000}}',
        encoding="utf-8",
    )

    payload = read_paper_evidence(tmp_path)["payload"]

    assert {"epoch", "gates", "coverage", "summary", "gaps", "diagnostics"} <= set(payload)
    assert payload["gates"]
    assert payload["coverage"]
    for item in [*payload["gates"], *payload["coverage"]]:
        assert {"key", "title", "status", "evidence", "sources", "metrics"} <= set(item)
        assert isinstance(item["sources"], list)
        for source in item["sources"]:
            assert {"path", "process", "format", "cadence", "retention"} <= set(source)
    assert {"days", "regimes", "exit_paths_complete", "c1_open_mean", "c1_close_mean", "c1_open_n", "c1_close_n"} <= set(payload["summary"])
    assert {"history_error", "trade_log_error", "trade_log_malformed_lines", "slip_stats_error", "dropped_test_log_lines"} <= set(payload["diagnostics"])


def test_paper_dashboard_allows_cold_evidence_scan():
    """The client must outlast the cold scan, not match a particular number.

    This asserted the literal 30000 and so pinned a value that was measured too small:
    the first request after a backend restart rebuilds the evidence cache from ~115MB
    of logs and took 41.7s on 2026-08-15, meaning every first page load reported
    "Paper evidence unavailable" for a backend that was working fine.
    """
    source = (DASH / "paper" / "paper.js").read_text(encoding="utf-8")
    found = re.findall(r"AbortSignal\.timeout\((\d+)\)", source)
    assert found, "the evidence fetch has no timeout at all"
    MEASURED_COLD_SCAN_MS = 41_700
    for value in found:
        assert int(value) > MEASURED_COLD_SCAN_MS, (
            f"timeout {value}ms is below the measured {MEASURED_COLD_SCAN_MS}ms cold scan, "
            f"so the first load after a restart fails every time"
        )


def test_paper_dashboard_exposes_c1_observed_detail():
    source = (DASH / "paper" / "paper.js").read_text(encoding="utf-8")
    css = (DASH / "paper" / "paper.css").read_text(encoding="utf-8")
    html = (DASH / "paper" / "index.html").read_text(encoding="utf-8")

    assert "if (value == null || value === '') return '--';" in source
    assert "function updateC1Progress(gates, summary)" not in source
    assert "function updateC1Panel(gates, summary, coverage)" in source
    assert "sample gate incomplete" in source
    assert "over limit now" in source
    assert "function c1ReasonChip" in source
    assert 'id="c1ProgressTitle"' in html
    assert 'id="c1ProgressStatus"' in html
    assert 'id="c1ProgressBars"' not in html
    assert 'id="coverageProgressTitle"' in html
    assert 'id="coverageProgressStatus"' in html
    assert 'id="coverageActiveSpec"' in html
    assert 'id="coverageMetricGroups"' in html
    assert 'id="c1MetricGroups"' in html
    assert 'id="c1ActiveSpec"' in html
    assert 'id="c1StatusEyebrow"' in html
    assert 'id="readinessBlockers"' in html
    assert 'id="paper-tab-overview"' in html
    assert 'id="paper-tab-gates"' in html
    assert 'id="paper-tab-coverage"' in html
    assert 'id="paper-tab-gaps"' in html
    assert 'id="stpProgressTitle"' in html
    assert 'id="stpProgressStatus"' in html
    assert 'id="stpActiveSpec"' in html
    assert 'id="stpMetricGroups"' in html
    assert 'id="b3ProgressTitle"' in html
    assert 'id="b3ProgressStatus"' in html
    assert 'id="b3ActiveSpec"' in html
    assert 'id="b3MetricGroups"' in html
    assert 'id="twsProgressTitle"' in html
    assert 'id="twsProgressStatus"' in html
    assert 'id="twsActiveSpec"' in html
    assert 'id="twsMetricGroups"' in html
    assert "function c1SampleMetric" in source
    assert "function updateCoveragePanel" in source
    assert "function coverageMoreInfo" in source
    assert "function c1SpecPills" in source
    assert "function c1MoreInfo" in source
    assert "function updateSTPPanel" in source
    assert "function stpMoreInfo" in source
    assert "function stopTradeRows" in source
    assert "function updateB3Panel" in source
    assert "function b3MoreInfo" in source
    assert "function updateTWSPanel" in source
    assert "function coverageRefMetric" in source
    assert "function coverageRefGroup" in source
    assert "function bindCoverageReferenceButtons" in source
    assert "function compositeStatus" in source
    assert "function renderReadinessBlockers" in source
    assert "function blockerCard" in source
    assert "function showPaperTab" in source
    assert "BREACH NOW" not in source
    assert "QUALITY_BREACH" in source
    assert "quality breach (sample pending)" in source
    assert ".quality-breach" in css
    assert "why needed" in source
    assert "to pass / unlock" in source
    assert "Prove runner cold-start state matches broker/file state" in source
    assert "Collect required OPEN/STP samples" in source
    assert "Run 10 continuous clean sessions" in source
    assert "data-coverage-ref" in source
    assert "function twsMoreInfo" in source
    assert "function groupedCoverage" in source
    assert "function pnlCompareDetail" in source
    assert "function pnlCompareRows" not in source
    assert "function signalCompareRows" in source
    assert "function entryCompareRows" in source
    assert "function lifecycleCompareRows" not in source
    assert "function tradeMasterReconcileRows" in source
    assert "function sourceDiffAnalyzerRows" in source
    assert "function tableVerdict" in source
    assert "function backendVerdict" in source
    assert "function renderVerdict" in source
    assert "function brokerIdentity" in source
    assert "function realtimeLedgerBlock" in source
    assert "function pnlCompareTab" in source
    assert "function pnlAuditTab" in source
    assert "function signalPathAuditBlock" in source
    assert "function pnlBaseMetricCards" in source
    assert "function pnlTimeline" in source
    assert "function pnlDailyRows" not in source
    assert "function pnlPurposeBlock" in source
    assert "function overviewVerdictStrip" in source
    assert "function openPositionParityRows" in source
    assert "function renderCoverage" in source
    assert "function fillQualityDetail" in source
    assert "function fillTradeRows" in source
    assert "function fillMetricCards" in source
    assert "function stpPlacementDetail" in source
    assert "function stpPlacementRows" in source
    assert "function stpPlacementMetricCards" in source
    assert "function stpRouteReconcileRows" in source
    assert "function rejectionCoverageDetail" in source
    assert "function rejectionEvidenceRows" in source
    assert "function rejectionMetricCards" in source
    assert "function detailProgress" in source
    assert "detail-metric-readout" in source
    assert "no-progress" in source
    assert "What This Measures" in source
    assert "<th>type</th>" in source
    assert "<th>fill</th>" in source
    assert "<th>ref</th>" in source
    assert "adverse" in source
    assert "favorable" in source
    assert "filled / order" in source
    assert "function fmtPnl" in source
    assert "type-chip" in source
    assert "direction-chip" in source
    assert "data-tooltip" in source
    assert 'title="${esc(description)}"' not in source
    assert "DETAIL PANEL" not in source
    assert "Status Rules" in source
    assert "Fill Trade Details" in source
    assert "Max contracts" in source
    assert "Backtest Divergence" in source
    assert "Placement Evidence" in source
    assert "Route Reconcile" in source
    assert "Rejected Candidate Evidence" in source
    assert "Rejected rows" in source
    assert "<th>reason</th>" in source
    assert "existing risk" in source
    assert "risk before trade enter" in source
    assert "signal risk" in source
    assert "projected risk" in source
    assert "over cap variance" in source
    assert "projected - cap" in source
    assert "B4 reminders" not in source
    assert "immediate STP after OPEN" in source
    assert "roska4_swing" in source
    assert "Metric Definitions" not in source
    assert "Pass Spec" not in source
    assert "Trade-by-trade Reasons" not in source
    assert "Base Audit" not in source
    assert "Divergence Timeline" not in source
    assert "Net P&amp;L Timeline" in source
    assert "Timeline Data Rows" in source
    assert "Signal Compare" in source
    assert "Entry Compare" in source
    assert "function lifecycleCompareRows" not in source
    assert "Source Diff Analyzer" in source
    assert "gross" in source
    assert "model cost" in source
    assert "net+fee" in source
    assert "Component note" in source
    assert "Realtime P&amp;L Source" in source
    assert "audit-m2k-entry" in source
    assert "audit-link" in source
    assert "audit-chip" in source
    assert "audit-log-group" in source
    assert "Signal Path Audit" in source
    assert "paper/backtest/Flex" in source
    assert "Entry Ref Value" in source
    assert "component-ref" in source
    assert "priceUsd" in source
    assert "pnl-diagnostic" not in source
    assert "source-diff-stats" in source
    assert "Avg entry slip" in source
    assert "TOTAL DELTA" in source
    assert "Net P&amp;L Timeline" in source
    assert "pnl-tab-overview" in source
    assert "pnl-tab-trades" in source
    assert "pnl-tab-decision" in source
    assert "Trade Master Reconcile" in source
    assert "Overview Verdicts" in source
    assert "Base aligned" in source
    assert "table-verdict" in source
    assert "pnl-tab-components" not in source
    assert "pnl-tab-rules" not in source
    assert "timeline-readout" in source
    assert "Timeline reconcile" in source
    assert "backendVerdict(compare, 'timeline')" in source
    assert "minimum 10-session span" in source
    assert "Classification" not in source
    assert "contract_spec_guard" in source
    assert "function contractSpecGuardDetail" in source
    assert "contractPointValues" not in source
    assert "m.contract_specs" in source
    assert "compositeStatus(gate.status || 'UNKNOWN', [placement.status, currentProtection?.status])" in source
    assert "evidenceStatus(twsGate, 'tws_restart_nights evidence')" in source
    assert "reconcileStatus(pl.paper_minus_backtest_realized, pl.paper_minus_backtest_realized)" not in source
    assert "paper_flex_bridge_diff_sum ?? pl.paper_minus_flex_epoch_rebased_realized" not in source
    assert 'id="paperDays"' not in html
    assert 'id="regimesSeen"' not in html
    assert 'id="exitCoverage"' not in html
    assert 'id="slippageMean"' not in html
    assert "paperDays" not in source
    assert "regimesSeen" not in source
    assert "exitCoverage" not in source
    assert "slippageMean" not in source
    assert "slippageCount" not in source
    assert "c1SampleCaption" not in source
    assert "closeSlippageMean" not in source
    assert "IBKR ContractDetails" in source
    assert "P&amp;L Compare" in source
    assert "P&amp;L Source Reconcile" not in source
    assert "Backtest Artifact Audit" in source
    assert "function statementPnlCompareBlock" in source
    assert "function flexLedgerOverrideRows" in source
    assert "function backtestArtifactAuditBlock" in source
    assert "Open Position Parity" in source
    assert "function statePersistDetail" in source
    assert "function currentProtectionDetail" in source
    assert "function runnerFreshnessDetail" in source
    assert "Persisted Position Rows" in source
    assert "Protection Rows" in source
    assert "Runner Snapshot Rows" in source
    assert "state-position-table" in source
    assert "runner-snapshot-table" in source
    assert "function dataFreshnessDetail" in source
    assert "function openIncidentsDetail" in source
    assert "Freshness Check Rows" in source
    assert "Open Issue Rows" in source
    assert "data-freshness-table" in source
    assert "open-issue-table" in source
    assert "function manualInterventionDetail" in source
    assert "function rollSlippageDetail" in source
    assert "function sampleDenominatorsDetail" in source
    assert "function sameDayMultiDayDetail" in source
    assert "function logHygieneDetail" in source
    assert "Candidate Log Rows" in source
    assert "Roll Candidate Rows" in source
    assert "Denominator Rows" in source
    assert "Holding Window Rows" in source
    assert "Dropped Noise Samples" in source
    assert "system ledger" in source
    assert "not IBKR NetLiquidation" in source
    assert "Signal compare checks desired decision parity" in source
    assert "Flex ledger-aligned" in source
    assert "Flex zero-base" in source
    assert "Flex - realtime" in source
    assert "Component note" in source
    assert "trade id" in source
    assert "TradeID:" in source
    assert "Flex broker" not in source
    assert "Ledger alignment override" in source
    assert "TOTAL" in source
    assert "RECONCILED" in source
    assert "Difference Reconcile" not in source
    assert "Zero-base Paper vs Flex closed trades" in source
    assert "Flex epoch-rebased closed trades" not in source
    assert "ON PURPOSE" in source
    assert "Curve status controls daily-row freshness" in source
    assert "paper/live path defers a stop/exit after the 14h/EOD decision" in source
    assert "function gapItem" in source
    assert "data-gap-related" in source
    assert "unblocks when" in source
    assert "target_path" in source
    assert "<dt>status</dt>" in source
    assert "<dt>purpose</dt>" in source
    assert "gap-status-" in source
    assert "Observed data" in source
    assert "Cross-reference" in source
    assert "Placement after OPEN" in source
    assert "Composite STP status uses the verification gate plus placement/protection coverage" in source
    assert "Runner freshness proves snapshots are still being projected" in source
    assert "Active spec" in source
    assert "Signal/market closes shown for diagnosis" in source
    assert "Raw cumulative stats" in source
    assert "OPEN is judged per instrument because a pooled tick mean hides a single bad one." in source
    assert "Presented OPEN" in source
    assert "Presented STP" in source
    assert "More info" in source
    assert "raw stats, trades, definition, sources" in source
    assert "Purpose: audit the dashboard math." in source
    assert "c1StatusEyebrow" in source
    assert "Trade details" in source
    assert "tradeRows(samples)" in source
    assert "Slippage definition" in source
    assert "slip ticks = slip points / tick size" in source
    assert "expected_entry -> fill_price" in source
    assert "expected_stop -> fill_price" in source
    assert "evidenceLedger" not in html
    assert "gateRow" not in source
    assert "ledgerSource" not in html
    assert "ledgerSource" not in source
    assert 'id="paperSource"' in html
    assert "paper-live-tabs-v1" in html
    assert "READINESS BLOCKERS" in html
    assert "STOP PROTECTION READINESS" in html
    assert "ledger-detail" not in css
    assert "audit-ledger" not in css
    assert "coverage-panel" in css
    assert "paper-tab-nav" in css
    assert "blocker-card" in css
    assert ".blocker-card dl" in css
    assert ".blocker-card dt" in css
    assert ".panel-purpose" in css
    assert "coverage-group" in css
    assert "gap-related" in css
    assert ".gap-status-warn" in css
    assert "source-limit" in css
    assert "c1-panel" in css
    assert "stp-panel" in css
    assert "b3-panel" in css
    assert "tws-panel" in css
    assert "c1-metric-groups" in css
    assert "c1-active-spec" in css
    assert "c1-more-info" in css
    assert "c1-more-grid" in css
    assert "more-section" in css
    assert "c1-eyebrow.pending" in css
    assert "span.bad" in css
    assert "span.watch" in css
    assert "c1-spec-summary" not in css
    assert "c1-metric.sample" in css
    assert "reference-group" in css
    assert "coverage-ref button" in css
    assert "trade-table" in css
    assert "contract-spec-table" in css
    assert "pnl-compare-table" in css
    assert "pnl-tabs" in css
    assert "component-ref" in css
    assert "pnl-diagnostic" not in css
    assert "source-diff-stats" in css
    assert "polyline.paper" in css
    assert "timeline-readout" in css
    assert "pnl-tab-decision" in css
    assert "trades-panel" in css
    assert "trade-master-table" in css
    assert "overview-verdict-grid" in css
    assert "overview-verdict-card" in css
    assert "secondary-table" in css
    assert "lifecycle-compare-table" in css
    assert "audit-link" in css
    assert "pnl-timeline" in css
    assert "pnl-daily-table" in css
    assert "signal-compare-table" in css
    assert "coverage-master-detail" in css
    assert "coverage-detail" in css
    assert "coverage-item.active" in css
    assert "state-position-table" in css
    assert "runner-snapshot-table" in css
    assert "data-freshness-table" in css
    assert "open-issue-table" in css
    assert "operator-log-table" in css
    assert "sample-denominator-table" in css
    assert "holding-window-table" in css
    assert "detail-list" in css
    assert "detail-metric-grid" in css
    assert "detail-progress" in css
    assert "detail-metric-readout" in css
    assert ".detail-metric.no-progress" in css
    assert "slip-label.bad" in css
    assert "type-chip.open" in css
    assert "direction-chip.short" in css
    assert "pnl-value.ok" in css
    assert ".has-tip::after" in css
    assert ".has-tip.tip-bottom::after" in css
    assert "fill-quality-table table" in css
    assert "stp-placement-table table" in css
    assert "stp-route-table table" in css
    assert "rejection-table table" in css
    assert "divergence-list li.watch" in css
    assert ".detail-list li { padding: 10px 12px;" in css
    assert "fill-result.ok" in css
    assert "definition-block" in css
    assert "detail-note" in css
    assert "STP-VERIFY" in source
    assert "placement failed" in source
    assert "structured check missing" in source
    assert "Stop trade details" in source
    assert "B3 RECONCILE" in html
    assert "Any mismatch episode keeps B3 in breach until classified." in source
    assert "cold-start sessions" in source
    assert "TWS RESTART" in html
    assert "Candidate lines" in source
    assert "tws_restart_spec.min_nights" in source
    assert "COVERAGE PROGRESS" in html
    assert "Regime and exits" in source
    assert "monitor interprets the documented word" in source
    assert "Execution health" in source
    assert "State and protection" in source
    assert "Operator and sample context" in source
    assert "ENGINE DECISION" in source


# ── missing contract point_value must read '--', never a confident $0.00 ────────
# paper.js dropped its hardcoded point-value map in favour of payload contract
# specs. Number(null) is 0 and passes Number.isFinite, so an unreconciled
# instrument (MNKD was absent from the guard entirely) silently rendered
# "$0.00" for every dollar cell instead of "--". This runs the shipped helpers
# rather than asserting on source text, because the defect was arithmetic.

def _run_paper_js_helpers(script: str, helpers: tuple[str, ...] | None = None) -> str:
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available")
    source = (DASH / "paper" / "paper.js").read_text(encoding="utf-8")
    helper_source = []
    for name in (helpers or ("pointValueFor", "priceUsd", "fmtMoney")):
        function_sig = f"  function {name}("
        const_sig = f"  const {name} ="
        if function_sig in source:
            start = source.index(function_sig)
            end = source.index("\n  }\n", start) + len("\n  }\n")
        else:
            start = source.index(const_sig)
            end = source.index(";\n", start) + len(";\n")
        helper_source.append(source[start:end])
    program = "\n".join(helper_source) + "\n" + script
    result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _run_paper_js_probe(script: str) -> str:
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available")
    source = (DASH / "paper" / "paper.js").read_text(encoding="utf-8")
    # Inject the export just inside the closing IIFE rather than string-matching the
    # bootstrap lines. Pinning the exact bootstrap text made every paper.js probe fail
    # the moment the refresh wiring changed, which reads as eight broken behaviours
    # instead of one stale fixture.
    closing = "\n})();"
    assert closing in source, "paper.js no longer ends in a closing IIFE"
    cut = source.rindex(closing)
    source = (
        source[:cut]
        + "\n  globalThis.__paperTest = { renderReadinessBlockers, updateCoveragePanel,"
          " updateB3Panel, updateSTPPanel, b3MoreInfo, logHygieneDetail };"
        + source[cut:]
    )
    program = (
        "const vm = require('vm');\n"
        "const elements = new Map();\n"
        "function el(id) { if (!elements.has(id)) elements.set(id, { id, textContent: '', innerHTML: '', className: '', hidden: false, parentElement: { classList: { add(){}, remove(){}, toggle(){} } }, querySelectorAll(){ return []; }, addEventListener(){}, scrollIntoView(){} }); return elements.get(id); }\n"
        "globalThis.document = { getElementById: el };\n"
        "globalThis.window = { setInterval(){} };\n"
        "globalThis.fetch = async () => ({ ok: true, json: async () => ({ payload: {} }), text: async () => '{\"payload\":{}}' });\n"
        "globalThis.AbortSignal = { timeout(){} };\n"
        f"vm.runInThisContext({json.dumps(source)});\n"
        f"{script}\n"
    )
    result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_price_usd_refuses_to_price_an_unreconciled_contract():
    out = _run_paper_js_helpers(
        "const specs = {M2K: {point_value: 5.0}};"
        "console.log(JSON.stringify({"
        "  known: priceUsd(3022.5, pointValueFor('M2K', specs), 1),"
        "  unknown: priceUsd(3022.5, pointValueFor('MNKD', specs), 1),"
        "  emptySpecs: priceUsd(3022.5, pointValueFor('M2K', {}), 1),"
        "  nullPrice: priceUsd(null, 5.0, 1),"
        "}));"
    )
    values = json.loads(out)
    assert values["known"] == 15112.5
    # A contract the guard has not reconciled must not be priced at all.
    assert values["unknown"] is None
    assert values["emptySpecs"] is None
    assert values["nullPrice"] is None


def test_b3_more_info_renders_missing_episode_metrics_as_unknown_not_zero():
    out = _run_paper_js_helpers(
        "const gate = {metrics: {}, evidence: '', sources: []};"
        "const html = b3MoreInfo(gate, {metrics: {}}, {metrics: {}});"
        "console.log(JSON.stringify({"
        "  hasMissingEpisodes: html.includes('<dt>mismatch episodes</dt><dd>--</dd>'),"
        "  hasMissingRaw: html.includes('<dt>raw mismatch count</dt><dd>--</dd>'),"
        "  hasFalseZero: html.includes('<dt>mismatch episodes</dt><dd>0</dd>') || html.includes('<dt>raw mismatch count</dt><dd>0</dd>')"
        "}));",
        helpers=("esc", "metricLine", "sourceDetail", "fmtDurationBetween", "b3MoreInfo"),
    )
    values = json.loads(out)
    assert values["hasMissingEpisodes"] is True
    assert values["hasMissingRaw"] is True
    assert values["hasFalseZero"] is False


def test_b3_panel_renders_episode_headline_and_missing_values_without_false_zeroes():
    out = _run_paper_js_probe(
        "const coverage = [];\n"
        "__paperTest.updateB3Panel([{ key: 'b3_reconcile', status: 'BREACH', metrics: { episodes: 1, positions_affected: 2, first_seen: '2026-08-10T00:05:00Z', last_seen: '2026-08-10T09:18:00Z', raw_mismatch_count: 40, raw_line_count: 20, match_episodes: 3, cold_starts: 1 } }], coverage);\n"
        "const episode = { title: elements.get('b3ProgressTitle').textContent, html: elements.get('b3MetricGroups').innerHTML, reason: elements.get('b3ProgressReason').innerHTML };\n"
        "__paperTest.updateB3Panel([{ key: 'b3_reconcile', status: 'MISSING', metrics: {} }], coverage);\n"
        "const missing = { title: elements.get('b3ProgressTitle').textContent, html: elements.get('b3MetricGroups').innerHTML, reason: elements.get('b3ProgressReason').innerHTML };\n"
        "console.log(JSON.stringify({ episode, missing }));"
    )
    values = json.loads(out)
    assert values["episode"]["title"] == "1 episode(s) | 2 position(s) | 9h 13m"
    assert "raw mismatch count" in values["episode"]["html"]
    assert "40" in values["episode"]["html"]
    assert values["missing"]["title"] == "--"
    assert "0/0" not in values["missing"]["html"]
    assert "0/0" not in values["missing"]["reason"]


def test_overview_b3_current_status_uses_gate_evidence_when_mismatches_clear():
    out = _run_paper_js_probe(
        "const gates = [\n"
        "  { key: 'b3_reconcile', status: 'PASS', evidence: '3 match episode(s), 0 mismatch episode(s), 0 mismatch position(s) affected; raw mismatch heartbeat 0 across 0 line(s)', metrics: { episodes: 0, match_episodes: 3 } },\n"
        "  { key: 'paper_duration', status: 'PENDING', evidence: '12 paper day(s) in paper_history.json', metrics: { observed: 12, target: 60 } },\n"
        "  { key: 'regime_coverage', status: 'PENDING', evidence: 'Normal', metrics: { regimes: ['Normal'] } },\n"
        "  { key: 'exit_path_coverage', status: 'PENDING', evidence: 'Chandelier 1 | MAX_HOLD 1 | STP 1', metrics: { exits: { CHANDELIER: 1, MAX_HOLD: 1, STP: 1 }, target_each: 3 } },\n"
        "  { key: 'c1_slippage', status: 'PENDING', evidence: 'C1 pending', metrics: { open_n: 1, stp_close_n: 0, open_mean: 1, spec: { min_n: 100, max_mean_ticks: 5 } } },\n"
        "  { key: 'tws_restart_nights', status: 'PENDING', evidence: '1 / 10 proven TWS restart night(s)', metrics: { restart_nights: 1, required_nights: 10 } },\n"
        "];\n"
        "const coverage = [\n"
        "  { key: 'data_freshness', status: 'PASS', evidence: 'Freshness checks pass', metrics: {} },\n"
        "  { key: 'open_incidents', status: 'PASS', evidence: 'No open issue objects emitted', metrics: {} },\n"
        "  { key: 'stp_placement', status: 'PENDING', evidence: '1 / 10 clean continuous session(s), 0 deferred route(s)', metrics: { continuous_session_streak: 1, required_continuous_sessions: 10 } },\n"
        "];\n"
        "__paperTest.renderReadinessBlockers(gates, coverage, {});\n"
        "console.log(JSON.stringify({ html: elements.get('readinessBlockers').innerHTML }));"
    )
    html = json.loads(out)["html"]
    assert "B3 reconcile" in html
    assert "3 match episode(s), 0 mismatch episode(s)" in html
    assert "remain unclassified" not in html


def test_overview_coverage_sample_passes_when_all_three_coverage_gates_pass():
    out = _run_paper_js_probe(
        "const gates = [\n"
        "  { key: 'b3_reconcile', status: 'PASS', evidence: '0 mismatch episode(s)', metrics: { episodes: 0 } },\n"
        "  { key: 'paper_duration', status: 'PASS', evidence: '61 paper day(s) in paper_history.json', metrics: { observed: 61, target: 60 } },\n"
        "  { key: 'regime_coverage', status: 'PASS', evidence: 'Normal + Stress', metrics: { regimes: ['Normal', 'Stress'] } },\n"
        "  { key: 'exit_path_coverage', status: 'PASS', evidence: 'Chandelier 4 | MAX_HOLD 4 | STP 4', metrics: { exits: { CHANDELIER: 4, MAX_HOLD: 4, STP: 4 }, target_each: 3 } },\n"
        "  { key: 'c1_slippage', status: 'PENDING', evidence: 'C1 pending', metrics: { open_n: 1, stp_close_n: 1, open_mean: 0, spec: { min_n: 100, max_mean_ticks: 5 } } },\n"
        "  { key: 'tws_restart_nights', status: 'PENDING', evidence: '0 / 10 proven TWS restart night(s)', metrics: { restart_nights: 0, required_nights: 10 } },\n"
        "];\n"
        "const coverage = [\n"
        "  { key: 'data_freshness', status: 'PASS', evidence: 'Freshness checks pass', metrics: {} },\n"
        "  { key: 'open_incidents', status: 'PASS', evidence: 'No open issue objects emitted', metrics: {} },\n"
        "  { key: 'stp_placement', status: 'PENDING', evidence: '0 / 10 clean continuous session(s)', metrics: { continuous_session_streak: 0, required_continuous_sessions: 10 } },\n"
        "];\n"
        "__paperTest.renderReadinessBlockers(gates, coverage, {});\n"
        "console.log(JSON.stringify({ html: elements.get('readinessBlockers').innerHTML }));"
    )
    html = json.loads(out)["html"]
    assert '<span>PASS</span><b>Coverage sample</b>' in html
    assert '<span>PENDING</span><b>Coverage sample</b>' not in html


_PNL_COVERAGE_JS = (
    "const coverage = [\n"
    "  { key: 'paper_vs_backtest', status: 'OBSERVED', metrics: {\n"
    "      ledger_adjustment_total: %s,\n"
    "      trade_compare: { statement_pnl_compare: {\n"
    "        paper_epoch_closed_realized: -43.25,\n"
    "        flex_epoch_rebased_realized: -1303.25,\n"
    "        paper_minus_flex_epoch_rebased_realized: 1260.0,\n"
    "        flex_epoch_rebased_closed: [{}, {}, {}, {}],\n"
    "      } } } },\n"
    "];\n"
)


def _pnl_card_html(ledger_total: str) -> str:
    out = _run_paper_js_probe(
        (_PNL_COVERAGE_JS % ledger_total)
        + "__paperTest.renderReadinessBlockers([], coverage, {});\n"
        "console.log(JSON.stringify({ html: elements.get('readinessBlockers').innerHTML }));"
    )
    return json.loads(out)["html"]


def test_overview_publishes_both_epoch_pnl_views_side_by_side():
    """Neither number alone is the epoch result.

    The sleeve ledger answers "did the strategy work"; the Flex statement answers "what
    did the account do". Showing only the ledger hides that real money went 30x further
    down; showing only the broker blames the strategy for a routing defect.
    """
    html = _pnl_card_html("-1260.0")
    assert "<b>Epoch P&amp;L</b>" in html
    assert "strategy -$43.25 / broker -$1,303.25" in html


def test_overview_epoch_pnl_is_observed_not_a_blocker():
    # A threshold on four closed lots is a threshold on noise, and the sample gates
    # already block on that. If this ever renders BREACH/PENDING it has become a
    # go-live blocker with no risk policy behind its number.
    html = _pnl_card_html("-1260.0")
    assert "<span>OBSERVED</span><b>Epoch P&amp;L</b>" in html


def test_overview_epoch_pnl_says_whether_the_gap_is_fully_accounted_for():
    explained = _pnl_card_html("-1260.0")
    assert "fully accounted for by recorded ledger adjustment(s)" in explained
    assert "part of the gap is unexplained" not in explained
    # Same +1260.00 gap, adjustments that only cover part of it: the reviewer must not
    # be told it is explained.
    partial = _pnl_card_html("-400.0")
    assert "part of the gap is unexplained" in partial
    assert "fully accounted for" not in partial


def test_overview_epoch_pnl_reports_missing_rather_than_zero_when_absent():
    out = _run_paper_js_probe(
        "const coverage = [{ key: 'paper_vs_backtest', status: 'MISSING', metrics: {} }];\n"
        "__paperTest.renderReadinessBlockers([], coverage, {});\n"
        "console.log(JSON.stringify({ html: elements.get('readinessBlockers').innerHTML }));"
    )
    html = json.loads(out)["html"]
    assert "<span>MISSING</span><b>Epoch P&amp;L</b>" in html
    assert "strategy -- / broker --" in html
    assert "$0.00" not in html


def _basis_for(lots: list[dict]) -> str | None:
    from monitor.backend.paper_evidence_reader import _flex_reconcile_basis

    return _flex_reconcile_basis({"statement_pnl_compare": {"flex_epoch_rebased_closed": lots}})


def test_flex_reconcile_basis_is_read_from_the_lots_not_hardcoded():
    """This string used to be a hardcoded sentence claiming the Flex money came from
    local point_value. paper_pnl_compare switched to the statement's Proceeds and the
    sentence stayed behind, describing code that no longer existed -- on the one panel
    whose entire job is to report where the money came from."""
    basis = _basis_for([{"pnl_basis": "statement_proceeds"}, {"pnl_basis": "statement_proceeds"}])
    assert "statement Proceeds" in basis
    assert "n=2" in basis
    assert "local point_value" not in basis


def test_flex_reconcile_basis_warns_when_any_lot_falls_back_to_local_point_value():
    # A lot priced from local point_value cancels a multiplier defect on both sides, so
    # paper-minus-Flex cannot see it. Mixing one in must not read as broker-verified.
    basis = _basis_for([{"pnl_basis": "statement_proceeds"}, {"pnl_basis": None}])
    assert "mixed basis" in basis
    assert "unverified against broker money" in basis
    assert "statement Proceeds (" not in basis


def test_flex_reconcile_basis_is_absent_rather_than_asserted_with_no_lots():
    assert _basis_for([]) is None
    from monitor.backend.paper_evidence_reader import _flex_reconcile_basis

    assert _flex_reconcile_basis({}) is None


# Values measured on the single-pass scanner BEFORE it was split per file, on the real
# logs. They are the anchor the refactor is held against: a self-referential comparison
# (per-file merged vs per-file concatenated) would agree by construction and prove
# nothing. Any of these moving means the split changed what the gates see.
# Counters that are a plain sum over files — no episode spans a seam, so splitting the
# scan cannot change them. The b3_* fields are deliberately NOT here: episodes really do
# cross file boundaries and get merged, which is what the next test pins.
_ADDITIVE_LOG_FIELDS = (
    "cold_starts",
    "dropped_test_lines",
    "tws_restart_lines",
    "manual_intervention_lines",
)


def _fake_proc(pid, started_epoch):
    return {"pid": pid, "started_epoch": started_epoch}


def test_scheduler_age_is_reported_next_to_the_code_it_is_running(tmp_path):
    """Age alone does not mean anything; age against the code's mtime does.

    A scheduler up for three days is perfectly healthy if nothing changed. The failure
    on 2026-08-16 was narrower and invisible: the process started 13/8 04:30 and the
    cron table it runs was rewritten 15/8 01:10, so the Sunday sweep committed that day
    did not exist in the running instance. Twenty-one restarts went by without anyone
    seeing it, because everything that was displayed said "running".

    So the dashboard needs the comparison, not the number: is this process older than
    the file it is executing.
    """
    from monitor.backend.schedule_status import scheduler_process_state

    code = tmp_path / "run_scheduler.py"
    code.write_text("# cron", encoding="utf-8")
    os.utime(code, (1_000_000, 1_000_000))

    stale = scheduler_process_state(
        code_path=code, processes=[_fake_proc(29340, 900_000)], now_epoch=1_300_000)
    assert stale["running"] is True and stale["pid"] == 29340
    assert stale["stale_code"] is True, (
        "process started before its own source was last written and nothing said so — "
        f"this is the 2026-08-16 failure: {stale}")
    assert stale["age_seconds"] == 400_000

    fresh = scheduler_process_state(
        code_path=code, processes=[_fake_proc(35448, 1_200_000)], now_epoch=1_300_000)
    assert fresh["stale_code"] is False, (
        f"started after the last edit — must not cry wolf: {fresh}")

    none = scheduler_process_state(code_path=code, processes=[], now_epoch=1_300_000)
    assert none["running"] is False
    assert none["stale_code"] is None, (
        "nothing running is a different problem from running stale code; reporting "
        f"False here would say the running instance is up to date: {none}")


def test_only_a_real_scheduler_counts_as_a_scheduler():
    """Matching the module name anywhere on a command line counts the wrong things.

    Measured right after shipping the first version: the scan returned five pids on a
    box running one scheduler. The extras were shells and python one-liners that merely
    MENTIONED the string — including the measurement script itself, whose own command
    line contained it. The header would have shown "Scheduler x5 RUNNING" in red, which
    is the duplicate-scheduler alarm, on a perfectly healthy host.

    A real one is a python process launched with `-m global_index.run_scheduler`.
    """
    from monitor.backend.schedule_status import _is_scheduler_cmdline

    assert _is_scheduler_cmdline(
        ["pythonw.exe", "-m", "global_index.run_scheduler", "--port", "4002"]) is True

    assert _is_scheduler_cmdline(
        ["bash.exe", "-c", "grep global_index.run_scheduler ops.py"]) is False, (
        "a shell grepping for the name is not a scheduler")
    assert _is_scheduler_cmdline(
        ["python", "-c", "CMD='global_index.run_scheduler'"]) is False, (
        "a one-liner that merely mentions the module is not a scheduler")
    assert _is_scheduler_cmdline(["pythonw.exe", "-m", "monitor.backend.app"]) is False
    assert _is_scheduler_cmdline([]) is False


def test_the_process_scan_is_not_run_on_every_poll(monkeypatch):
    """The dashboard polls this endpoint every ~8s; the scan takes ~1.8s.

    Shipped without a cache, it made /api/v1/schedule-status take 23 SECONDS — polls
    piling on top of each other — and the dashboard became unusable. Measuring the cost
    of a call before putting it on a hot path is the whole lesson here.
    """
    from monitor.backend import schedule_status as ss

    calls = []
    monkeypatch.setattr(ss, "_scan_scheduler_processes",
                        lambda: (calls.append(1), [])[1])
    ss.invalidate_scheduler_cache()

    for _ in range(5):
        ss.scheduler_process_state()

    assert len(calls) == 1, (
        f"the process table was enumerated {len(calls)} times for 5 reads; at ~1.8s a "
        f"scan and a poll every 8s this is what made the page unusable")


def test_track1_mode_does_not_call_ops_on_the_dashboard_poll_path(monkeypatch):
    """Route mode is a dashboard hot path; it must not shell out through ops.py.

    Stage 5ZZW correctly made the scheduler command line authoritative, but asked it through
    ``ops.track1_status()``, which spawns PowerShell. Opening the dashboard then produced a
    visible cmd/PowerShell window on every poll.
    """
    from monitor.backend import schedule_status as ss
    from monitor import ops

    monkeypatch.setattr(ss, "_running_schedulers", lambda: [{
        "pid": 3000,
        "started_epoch": 1_000_000,
        "command": "pythonw.exe -m global_index.run_scheduler --port 4002 --track1-only-shadow",
    }])
    monkeypatch.setattr(ops, "track1_status",
                        lambda: (_ for _ in ()).throw(AssertionError("ops.py shell path used")))

    for _ in range(5):
        assert ss.resolve_track1_only() is True
        mode = ss.scheduler_track1_mode_status()
        assert mode["track1_mode"] == "track1-only-shadow"
        assert mode["legacy_entry_jobs"] == 0


def test_open_issue_retirement_does_not_call_ops_on_the_dashboard_poll_path(monkeypatch,
                                                                            tmp_path):
    from monitor.backend import open_issue_reader as issues
    from monitor.backend import schedule_status as ss
    from monitor import ops

    (tmp_path / "track1_go_live_confirmation.json").write_text(
        '{"schema_version":1,"confirmed_by":"operator","confirmed_at":"2026-08-27T00:00:00Z",'
        '"legacy_retired_confirmed":true,"note":"test"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(ss, "scheduler_track1_mode_status", lambda: {
        "scheduler_running": True,
        "track1_mode_source": "process_table",
        "scheduler_track1_only": True,
        "legacy_entry_jobs": 0,
    })
    monkeypatch.setattr(ops, "track1_status",
                        lambda: (_ for _ in ()).throw(AssertionError("ops.py shell path used")))

    state = issues.legacy_retirement_state(tmp_path)
    assert state["retired"] is True
    assert state["legacy_entry_jobs"] == 0


def test_scheduler_age_reaches_the_payload_and_the_page():
    """A reader nobody calls, or a field nothing renders, is H2 again.

    The runner audit's worst operational finding was a kill switch implemented end to
    end that no caller ever passed. This is the same risk in the monitor: computing the
    scheduler's age correctly is useless if it stops at the API boundary.
    """
    from monitor.backend.schedule_status import get_schedule_status

    payload = get_schedule_status(ROOT)
    assert "scheduler_process" in payload, (
        f"the reader exists but the endpoint does not carry it: {sorted(payload)}")
    for field in ("running", "age_seconds", "stale_code"):
        assert field in payload["scheduler_process"], (
            f"{field} missing from the payload block: {payload['scheduler_process']}")

    page = (ROOT / "global_index" / "dash" / "realtime" / "realtime.js").read_text(
        encoding="utf-8")
    assert "scheduler_process" in page, (
        "nothing in realtime.js reads scheduler_process — the number reaches the API "
        "and dies there, which is exactly how a three-day-old scheduler stayed invisible")


def test_per_file_log_scan_reproduces_the_single_pass_numbers():
    """The fold that turns N per-file partials into one summary must ADD, not replace.

    This used to compare a live scan against a frozen dict captured when the refactor
    landed — cold_starts: 8, dropped_test_lines: 1160, and so on. Those counts come from
    the PRODUCTION logs, which grow, so it measured a moving target against a fixed post.
    It went red on 2026-08-16 for the most ordinary reason available: the scheduler was
    restarted, a required operation, and cold_starts became 9. Nothing was broken. That
    is the "hardcoded literal drifts from what it describes" defect the dashboard audit
    named, in its worst form — red on correct behaviour teaches people to ignore the suite.

    The obvious replacement is a trap, and it was written and thrown away before this
    one: comparing _log_summary_uncached against the sum of _scan_one_log over
    _log_paths. Both sides are the same loop spelled twice and both read the same path
    list, so injecting a duplicate file inflates BOTH and the assertion still holds. It
    is the compare-a-value-with-itself shape. Verified: that version stayed green with a
    file deliberately scanned twice.

    What the split actually introduced is _merge_log_partial, so that is what gets
    tested — on synthetic partials, where the expected answer is known independently of
    any log on disk.
    """
    import monitor.backend.paper_evidence_reader as pe

    summary = pe._blank_log_summary()
    for _ in range(3):
        pe._merge_log_partial(summary, {
            "cold_starts": 2,
            "dropped_test_lines": 10,
            "tws_restart_lines": 1,
            "manual_intervention_lines": 0,
            "tws_restart_days": {"2026-08-10"},
            "_b3_episodes": [{"kind": "match"}],      # underscore: must be ignored
        })

    for field, expected in (("cold_starts", 6), ("dropped_test_lines", 30),
                            ("tws_restart_lines", 3), ("manual_intervention_lines", 0)):
        assert summary[field] == expected, (
            f"{field}: folding three partials gave {summary[field]!r}, expected "
            f"{expected!r} — the merge is replacing instead of accumulating, which "
            f"would silently report only the last file's counts")

    assert summary["tws_restart_days"] == {"2026-08-10"}, (
        f"set fields must union, not overwrite: {summary['tws_restart_days']!r}")
    assert "_b3_episodes" not in summary, (
        "underscore keys are per-file scratch and must not leak into the summary; "
        "episodes are merged separately because they cross file seams")


def test_the_seam_merge_is_load_bearing_not_defensive():
    """Episodes really do cross file boundaries, three times on the current logs.

    Without the merge, 21 per-file episodes would be reported instead of 18 -- and the
    B3 gate breaches on any unclassified MISMATCH episode, so splitting one in two
    invents a reconcile failure that never happened.
    """
    import monitor.backend.paper_evidence_reader as pe

    raw = []
    for path in pe._log_paths(ROOT):
        raw.extend(pe._scan_one_log(path, "2026-08-10").get("_b3_episodes") or [])
    merged = []
    for episode in raw:
        pe._append_b3_episodes(merged, [episode])
    assert len(raw) > len(merged), "the seam merge did nothing; the check has gone stale"
    summary = pe._log_summary_uncached(ROOT, "2026-08-10")
    assert summary["b3_match_episodes"] + summary["b3_mismatch_episodes"] == len(merged)


def test_a_file_that_did_not_change_is_not_read_again():
    """Logs only grow. Re-reading 120MB because one file gained a few kilobytes was the
    entire cost of serving this page: 25s, of which 13s was 8 million regex searches over
    lines parsed identically the previous twenty times."""
    import monitor.backend.paper_evidence_reader as pe

    pe._log_summary_uncached(ROOT, "2026-08-10")
    reads = []
    original = pe._scan_one_log

    def counting(path, epoch):
        before = len(pe._file_cache)
        out = original(path, epoch)
        if len(pe._file_cache) != before:
            reads.append(path.name)
        return out

    pe._scan_one_log = counting
    try:
        pe._log_summary_uncached(ROOT, "2026-08-10")
    finally:
        pe._scan_one_log = original
    assert reads == [], f"re-read unchanged file(s): {reads}"


def test_episodes_are_not_split_at_a_file_boundary():
    # The single-pass version grouped line by line and could carry an episode across
    # files. It cannot in practice -- the walk puts scheduler_* before live_day_* so time
    # jumps backwards there -- but the merge implements the rule rather than assuming it.
    import datetime as dt

    import monitor.backend.paper_evidence_reader as pe

    a = {"kind": "mismatch", "count": 2, "first_seen": "2026-08-10T06:00:00Z",
         "last_seen": "2026-08-10T06:05:00Z", "raw_line_count": 2, "path": "x.log",
         "line_from": 1, "line_to": 9}
    b = {"kind": "mismatch", "count": 2, "first_seen": "2026-08-10T06:20:00Z",
         "last_seen": "2026-08-10T06:25:00Z", "raw_line_count": 3, "path": "y.log",
         "line_from": 1, "line_to": 7}
    acc = []
    pe._append_b3_episodes(acc, [a])
    pe._append_b3_episodes(acc, [b])
    assert len(acc) == 1, "same kind/count within the gap must stay one episode"
    assert acc[0]["raw_line_count"] == 5
    assert acc[0]["last_seen"] == "2026-08-10T06:25:00Z"

    # Beyond the gap it is a separate episode.
    far = {**b, "first_seen": "2026-08-10T09:00:00Z", "last_seen": "2026-08-10T09:02:00Z"}
    acc2 = []
    pe._append_b3_episodes(acc2, [a])
    pe._append_b3_episodes(acc2, [far])
    assert len(acc2) == 2


_C1_SPEC = {
    "open": {"scope": "by_inst", "min_n_per_inst": 20, "max_mean_ticks": 3},
    "stp_close": {"scope": "pooled", "min_n": 30, "max_mean_ticks": 3},
    "close_scope": "stp_only", "use_absolute": True,
}


def _c1(by_inst, *, open_n=None, stp_n=0, stp_mean=None, spec=_C1_SPEC):
    from monitor.backend.paper_evidence_reader import _c1_status

    slip = {
        "open_mean": 0.0, "open_n": open_n if open_n is not None else sum(r["open_n"] for r in by_inst),
        "stp_close_mean": stp_mean, "stp_close_n": stp_n,
        "close_mean": stp_mean, "close_n": stp_n,
        "signal_close_with_stop_ref": 0, "by_inst": by_inst,
    }
    return _c1_status(slip, spec)


def _inst(name, n, mean, tick_value=0.5):
    return {"inst": name, "tick": 0.25, "tick_value": tick_value,
            "open_n": n, "open_mean_ticks": mean, "open_mean_usd": mean * tick_value}


def test_c1_open_is_judged_per_instrument_so_one_bad_symbol_cannot_hide():
    """The pooled mean was the defect, not the tick unit.

    On the five fills that existed, pooled read +9.00 ticks while M2K alone sat at
    +28.00 -- fourteen times the cost the backtest models. Averaging it against MES at
    -4.00 made the basket look merely marginal.
    """
    status, evidence, metrics = _c1([
        _inst("M2K", 25, 28.0), _inst("MES", 25, -0.5, tick_value=1.25),
    ])
    assert metrics["open_breaching_instruments"] == ["M2K"]
    assert status == "QUALITY_BREACH"
    assert "M2K" in evidence


def test_c1_favourable_slippage_still_counts_as_drift():
    # -4 ticks is a better price, not a cheaper one to ignore: the reference the risk
    # sizing is computed from was wrong by four ticks either way.
    status, _, metrics = _c1([_inst("MES", 25, -4.0, tick_value=1.25)])
    assert metrics["open_breaching_instruments"] == ["MES"]
    assert status == "QUALITY_BREACH"


def test_c1_an_instrument_short_of_samples_is_pending_not_passing():
    status, _, metrics = _c1([_inst("MES", 3, 0.5, tick_value=1.25)], stp_n=30, stp_mean=0.0)
    assert metrics["open_instruments_short_of_sample"] == ["MES"]
    assert status == "PENDING", "a mean over three fills is not evidence of clean execution"


def test_c1_reports_an_over_limit_mean_even_on_a_thin_sample():
    # Waiting for a count before mentioning a 28-tick miss would be the pooled mistake
    # in another form: the measurement most likely to matter, withheld.
    status, _, metrics = _c1([_inst("M2K", 1, 28.0)])
    assert status == "QUALITY_BREACH"
    assert metrics["open_breaching_instruments"] == ["M2K"]


def test_c1_passes_only_when_every_instrument_and_the_stp_branch_are_ready():
    status, _, _ = _c1([_inst("MES", 25, 0.5, tick_value=1.25), _inst("MYM", 25, -1.0)],
                       stp_n=30, stp_mean=1.0)
    assert status == "PASS"
    # One thin instrument is enough to hold the gate.
    assert _c1([_inst("MES", 25, 0.5, tick_value=1.25), _inst("MYM", 2, -1.0)],
               stp_n=30, stp_mean=1.0)[0] == "PENDING"
    # So is a thin STP branch.
    assert _c1([_inst("MES", 25, 0.5, tick_value=1.25)], stp_n=5, stp_mean=1.0)[0] == "PENDING"


def test_c1_confidence_interval_is_published_beside_each_mean():
    """A min_n is a guess about dispersion nobody measured; the interval is the measurement."""
    from monitor.backend.paper_evidence_reader import _ci95

    assert _ci95([1.0]) is None, "one sample has no interval"
    tight = _ci95([2.0, 2.1, 1.9, 2.0, 2.05])
    wide = _ci95([2.0, 12.0, -8.0, 2.0, 6.0])
    assert tight is not None and wide is not None
    assert wide > tight * 5, "a scattered sample must report a visibly wider interval"


def test_c1_spec_publishes_why_each_threshold_is_what_it_is():
    payload = read_paper_evidence(ROOT)["payload"]
    spec = ({g["key"]: g for g in payload["gates"]}["c1_slippage"]["metrics"] or {}).get("spec") or {}
    assert spec.get("open", {}).get("why_by_inst"), "no rationale for per-instrument scope"
    assert spec.get("open", {}).get("why_min_n_20"), "no rationale for the OPEN sample count"
    assert spec.get("stp_close", {}).get("why_min_n_30"), "no rationale for the STP count"
    assert spec.get("stp_close", {}).get("stp_share_is_assumed_not_measured"), (
        "the STP share underpinning min_n=30 is an assumption and must say so"
    )
    assert spec.get("max_mean_ticks_rationale", {}).get("why_3_not_5")
    assert spec.get("why_absolute"), "favourable-slippage handling must be stated, not implied"


def _episode(path="live_day_0810.log", line_from=942, line_to=10072):
    return {"path": path, "line_from": line_from, "line_to": line_to,
            "kind": "mismatch", "positions_affected": 2}


def _classify(episodes, classifications):
    from monitor.backend.paper_evidence_reader import _b3_classify

    return _b3_classify(episodes, classifications)


def test_a_b3_classification_only_clears_the_episode_it_names():
    """One note must not absolve every future mismatch.

    A classification carries the episode's identity -- file and line range -- so it can
    only ever cover that one. Without the identity check, writing a single note would
    stop the reconcile gate being a gate at all.
    """
    note = {"id": "mnkd_routing", "episode": _episode()}
    out = _classify([_episode()], [note])
    assert out["classified_count"] == 1 and out["unclassified_count"] == 0

    # A different episode in the same file is a different event.
    later = _classify([_episode(line_from=50000, line_to=50100)], [note])
    assert later["unclassified_count"] == 1, "a note leaked onto an episode it does not name"
    assert later["classified_count"] == 0


def test_a_classified_b3_mismatch_reads_explained_not_passed():
    """The books and the broker genuinely disagreed. That does not un-happen.

    EXPLAINED buys only that a historical episode with a known and fixed cause stops
    blocking the epoch the way an unfixable gate does.
    """
    payload = read_paper_evidence(ROOT)["payload"]
    b3 = {g["key"]: g for g in payload["gates"]}["b3_reconcile"]
    klass = b3["metrics"]["classification"]
    if klass["classified_count"] and not klass["unclassified_count"]:
        assert b3["status"] == "EXPLAINED", f"classified mismatches must not read {b3['status']}"
        assert b3["status"] != "PASS"


def test_a_classification_whose_episode_vanished_is_reported_stale():
    # Logs rotate. A note left pointing at nothing is not reassurance, and counting it
    # as coverage would silently reduce the gate's scope.
    out = _classify([], [{"id": "old", "episode": _episode()}])
    assert len(out["stale_classifications"]) == 1
    assert out["classified_count"] == 0


def test_an_unclassified_b3_mismatch_still_breaches():
    out = _classify([_episode(), _episode(line_from=1, line_to=2)],
                    [{"id": "one", "episode": _episode()}])
    assert out["unclassified_count"] == 1
    assert out["classified_count"] == 1


_THRESHOLD_SPEC = {
    "edge_gate": {
        "arm_after_sessions": 20,
        "quantile": 0.01,
        "bands": [
            {"sessions": 20, "floor_usd": -1920.60},
            {"sessions": 25, "floor_usd": -1962.86},
            {"sessions": 30, "floor_usd": -2082.52},
        ],
    },
    "operational_gate": {"tolerance_usd": 0.01},
}


def _gates(sessions, strategy, *, gap=0.0, adjustments=None, spec=_THRESHOLD_SPEC):
    from monitor.backend.paper_evidence_reader import _pnl_threshold_status

    return _pnl_threshold_status(
        spec,
        {
            "paper_epoch_closed_realized": strategy,
            "flex_epoch_rebased_realized": (strategy - gap) if strategy is not None else None,
            "paper_minus_flex_epoch_rebased_realized": gap,
        },
        sessions,
        adjustments,
    )


def test_edge_gate_stays_silent_until_the_sample_can_carry_a_verdict():
    """53% of healthy 5-session windows in the backtest are negative.

    Blocking on a loss before the arming point would be blocking on noise, so the gate
    must say NOT_ARMED rather than PASS -- an unarmed gate is not evidence of health.
    """
    out = _gates(5, -5000.0)["edge"]
    assert out["status"] == "NOT_ARMED"
    assert out["sessions_to_arm"] == 15
    assert "carries no information" in out["detail"]


def test_edge_gate_blocks_below_the_floor_for_the_epoch_length():
    breached = _gates(20, -1921.0)["edge"]
    assert breached["status"] == "BREACH"
    assert breached["floor_usd"] == -1920.60
    # A dollar the other side of the same floor must not block.
    assert _gates(20, -1920.0)["edge"]["status"] == "PASS"


def test_edge_gate_uses_the_largest_band_at_or_below_the_epoch_length():
    # Between anchors the rule holds the previous, looser floor rather than interpolating
    # onto a number nobody wrote down.
    assert _gates(28, 0.0)["edge"]["active_band"]["sessions"] == 25
    assert _gates(30, 0.0)["edge"]["active_band"]["sessions"] == 30
    assert _gates(999, 0.0)["edge"]["active_band"]["sessions"] == 30, "clamp to the last band"


def test_operational_gate_blocks_any_uncovered_gap_however_small():
    """Not a statistical question: a $1 unexplained gap means the books do not describe
    the account. The MNKD defect was caught by this gate on day one, with no sample."""
    out = _gates(5, -43.25, gap=1.0)["operational"]
    assert out["status"] == "BREACH"
    assert "Size is not the point" in out["detail"]


def test_operational_gate_passes_when_a_recorded_adjustment_covers_the_gap():
    out = _gates(5, -43.25, gap=1260.0, adjustments=-1260.0)["operational"]
    assert out["status"] == "PASS"
    assert out["covered_by_adjustment"] is True
    # A partial adjustment must not clear the whole gap.
    assert _gates(5, -43.25, gap=1260.0, adjustments=-400.0)["operational"]["status"] == "BREACH"


def test_an_unarmed_edge_gate_never_reports_the_epoch_as_passed():
    combined = _gates(5, -43.25, gap=1260.0, adjustments=-1260.0)
    assert combined["edge"]["status"] == "NOT_ARMED"
    assert combined["operational"]["status"] == "PASS"
    assert combined["status"] == "OBSERVED", "one gate passing is not the epoch passing"


def test_a_missing_threshold_spec_is_a_spec_gap_not_a_silent_pass():
    from monitor.backend.paper_evidence_reader import _pnl_threshold_status

    out = _pnl_threshold_status({}, {}, 40, None)
    assert out["status"] == "SPEC_GAP"
    assert "no loss level blocks go-live" in out["detail"]


def test_published_threshold_spec_carries_its_own_provenance_and_limits():
    """A go-live number shown without its derivation is an instruction, not evidence."""
    payload = read_paper_evidence(ROOT)["payload"]
    cov = {c["key"]: c for c in payload["coverage"]}
    assert "pnl_thresholds" in cov, "the approved thresholds have no panel"
    spec = (cov["pnl_thresholds"]["metrics"] or {}).get("spec") or {}
    edge = spec.get("edge_gate") or {}
    frame = spec.get("frame") or {}
    assert edge.get("bands"), "no band table is published"
    assert edge.get("measured_false_block_rate") is not None, "false-block rate not published"
    assert edge.get("measured_power"), "detection power not published"
    assert edge.get("limitation"), "the rule must publish what it cannot catch"
    assert "98430.51" in (frame.get("self_check") or ""), "frame self-check not published"
    assert frame.get("coverage_check"), "must state which clusters trade through the frame"


def test_threshold_frame_states_that_every_cluster_trades_through_it():
    """The bands must be drawn from the system that actually trades, whole.

    This test previously asserted the opposite -- that the frame stopped at 2024-12-31 --
    on the strength of a comment in generate_replay_snapshots.py describing the tail as
    NKD-only. That comment describes the state before its own fix; REGIME_CSV was moved
    to spy_daily_live.csv and the curve regenerated on 2026-08-13, after which all three
    clusters trade to the end. Truncating there dropped 331 sessions of valid recent
    evidence and tightened every band: the 60-session floor read -$1,592 instead of
    -$2,927.

    So the invariant is not a date. It is that the frame carries a checked statement
    about cluster coverage, and that the check is not simply asserted.
    """
    payload = read_paper_evidence(ROOT)["payload"]
    cov = {c["key"]: c for c in payload["coverage"]}
    frame = ((cov["pnl_thresholds"]["metrics"] or {}).get("spec") or {}).get("frame") or {}
    coverage = frame.get("coverage_check") or ""
    assert coverage, "the frame must state which clusters trade through it"
    for cluster in ("roska4_swing", "global_nkd", "roska4_stress"):
        assert cluster in coverage, f"{cluster} coverage is not accounted for in the frame"
    assert frame.get("sessions", 0) > 1700, (
        f"frame has only {frame.get('sessions')} sessions; a truncated frame tightens "
        f"every band against evidence that exists"
    )


def _freshness(compare: dict, root=None) -> dict | None:
    from monitor.backend.paper_evidence_reader import _artifact_freshness

    return _artifact_freshness(root or ROOT, compare)


def test_stale_pnl_artifact_is_reported_rather_than_served_as_current():
    """The dashboard reads monitor/paper_pnl_compare.json instead of computing it.

    On 2026-08-14 the Flex reconcile was switched to broker Proceeds and the panel kept
    serving the previous code's lots -- looking exactly as authoritative as fresh ones,
    with nothing on screen to say otherwise.
    """
    from monitor.paper_pnl_compare import source_signature

    current = source_signature(ROOT)
    assert _freshness({"source_signature": current})["status"] == "CURRENT"

    drifted = {**current, "global_index/statement.py": "deadbeefdeadbeef"}
    stale = _freshness({"source_signature": drifted})
    assert stale["status"] == "STALE"
    assert stale["drifted"] == ["global_index/statement.py"]
    assert "paper_pnl_compare.py" in stale["detail"], "must say how to fix it"


def test_pnl_artifact_reports_stale_when_the_inputs_moved_on():
    """The code hash catches the code moving. It cannot catch the ordinary case.

    New fills arrive, nobody rebuilds, and the panel serves yesterday's P&L looking
    exactly as authoritative as today's — the code has not moved, so the hash matches.
    A nightly job rebuilds this now, but a job that dies is precisely when the warning
    has to fire on its own.
    """
    from monitor.paper_pnl_compare import data_watermark, source_signature

    fresh = {"source_signature": source_signature(ROOT), "data_watermark": data_watermark(ROOT)}
    assert _freshness(fresh)["status"] == "CURRENT"

    behind = {**fresh, "data_watermark": {**fresh["data_watermark"],
                                          "trade_log_last_day": "1999-01-01"}}
    out = _freshness(behind)
    assert out["status"] == "STALE"
    assert any("trade log" in reason for reason in out["behind"])
    assert "paper_pnl_compare.py" in out["detail"], "must say how to fix it"


def test_an_artifact_ahead_of_the_inputs_is_not_called_stale():
    # Only a LATER input is staleness. An artifact built from data that has since been
    # trimmed or rotated is not behind, and warning there teaches the reader to ignore
    # the banner.
    from monitor.paper_pnl_compare import data_watermark, source_signature

    ahead = {"source_signature": source_signature(ROOT),
             "data_watermark": {**data_watermark(ROOT), "trade_log_last_day": "2099-01-01"}}
    assert _freshness(ahead)["status"] == "CURRENT"


def test_watermark_tracks_days_not_row_counts():
    """A trade log gains rows all session without the daily conclusions changing.

    Watermarking on row count would fire on every fill and be switched off; a new
    trading DAY is a day the comparison genuinely has not covered.
    """
    from monitor.paper_pnl_compare import data_watermark

    mark = data_watermark(ROOT)
    assert set(mark) == {"trade_log_last_day", "paper_history_last_day", "flex_statement"}
    assert "rows" not in str(mark), "row counts would cry wolf on every fill"


def test_unstamped_pnl_artifact_is_unknown_not_assumed_fresh():
    # An artifact written before stamping existed cannot be checked. Claiming CURRENT
    # would be the same false reassurance the stamp exists to remove.
    assert _freshness({})["status"] == "UNKNOWN"
    assert _freshness({"source_signature": "not-a-dict"})["status"] == "UNKNOWN"


def test_pnl_source_signature_tracks_the_modules_that_decide_the_money():
    from monitor.paper_pnl_compare import SOURCE_FILES, source_signature

    assert "global_index/statement.py" in SOURCE_FILES, (
        "pair_fifo builds the Flex lots; a change there changes every P&L on the panel"
    )
    assert "monitor/paper_pnl_compare.py" in SOURCE_FILES
    sig = source_signature(ROOT)
    assert all(isinstance(v, str) and len(v) == 16 for v in sig.values())


def test_tws_restart_has_an_evidence_panel_of_its_own():
    """The gate with the largest outstanding requirement had no panel to open.

    Its gap card could not offer a drilldown, and the nearest existing panel is
    runner_freshness -- the target H5 removed for being wrong. Pointing at that again
    would trade one missing button for one misleading one.
    """
    payload = read_paper_evidence(ROOT)["payload"]
    cov = {c["key"]: c for c in payload["coverage"]}
    assert "tws_restart" in cov, "no TWS evidence surface exists"
    metrics = cov["tws_restart"]["metrics"] or {}
    assert "restart_proven" in (metrics.get("what_counts") or ""), (
        "the panel must state what makes a night count, not just show a number"
    )
    assert "context, not proof" in cov["tws_restart"]["evidence"], (
        "connectivity candidate lines must not read as restart evidence"
    )


def test_every_gap_card_can_open_the_panel_it_refers_to():
    payload = read_paper_evidence(ROOT)["payload"]
    keys = {c["key"] for c in payload["coverage"]}
    for gap in payload.get("gaps") or []:
        related = gap.get("related_key")
        assert related, f"gap {gap['title']!r} has no panel to open"
        assert related in keys, (
            f"gap {gap['title']!r} points at {related!r}, which is not a coverage panel"
        )
    assert "runner_freshness" not in {g.get("related_key") for g in payload.get("gaps") or []}, (
        "runner_freshness is the wrong target H5 removed; do not route gaps back to it"
    )


def _run_paper_refresh_probe(payloads: list[str]) -> dict:
    """Drive load() through a scripted sequence of server responses.

    Exports load() and the chip element so the poll's repaint decision can be observed
    directly, rather than inferred from whether some panel changed.
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available")
    source = (DASH / "paper" / "paper.js").read_text(encoding="utf-8")
    cut = source.rindex("\n})();")
    source = source[:cut] + "\n  globalThis.__paperLoad = load;" + source[cut:]
    program = (
        "const vm = require('vm');\n"
        "const elements = new Map();\n"
        "let renders = 0;\n"
        "function el(id) { if (!elements.has(id)) elements.set(id, { id, textContent: '', hidden: true, "
        "set innerHTML(v) { renders += 1; this._h = v; }, get innerHTML() { return this._h || ''; }, "
        "className: '', parentElement: { classList: { add(){}, remove(){}, toggle(){} } }, "
        "querySelectorAll(){ return []; }, addEventListener(){}, scrollIntoView(){} }); return elements.get(id); }\n"
        "globalThis.document = { getElementById: el, querySelectorAll(){ return []; }, querySelector(){ return null; } };\n"
        "globalThis.window = { setInterval(){} };\n"
        f"const bodies = {json.dumps(payloads)};\n"
        "let call = 0;\n"
        "globalThis.fetch = async () => ({ ok: true, text: async () => bodies[Math.min(call++, bodies.length - 1)] });\n"
        "globalThis.AbortSignal = { timeout(){} };\n"
        f"vm.runInThisContext({json.dumps(source)});\n"
        "(async () => {\n"
        # paper.js bootstraps its own load() on evaluation. Let that settle and reset the
        # counters, otherwise its late render lands mid-probe and reads as a poll repaint.
        "  for (let i = 0; i < 5; i += 1) await new Promise(r => setTimeout(r, 0));\n"
        "  call = 0; renders = 0; el('refreshChip').hidden = true;\n"
        "  await globalThis.__paperLoad(true);\n"
        "  const afterFirst = renders;\n"
        "  await globalThis.__paperLoad(false);\n"
        "  const afterPoll = renders;\n"
        "  const chipAfterPoll = el('refreshChip').hidden === false;\n"
        "  await globalThis.__paperLoad(true);\n"
        "  console.log(JSON.stringify({ afterFirst, afterPoll, afterAccept: renders, "
        "chipAfterPoll, chipAfterAccept: el('refreshChip').hidden === false }));\n"
        "})();\n"
    )
    result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip())


_PAPER_PAYLOAD_A = '{"payload": {"gates": [], "coverage": [], "summary": {}}}'
_PAPER_PAYLOAD_B = '{"payload": {"gates": [], "coverage": [], "summary": {"paper_days": 13}}}'


def test_background_poll_does_not_repaint_while_the_reader_is_reading():
    """render() reassigns innerHTML everywhere, closing open <details> and resetting
    scroll. The payload changes a few times a day, so repainting on a 60s timer spends
    the reader's place in a long evidence table to buy freshness that is not there."""
    seen = _run_paper_refresh_probe([_PAPER_PAYLOAD_A, _PAPER_PAYLOAD_B, _PAPER_PAYLOAD_B])
    assert seen["afterFirst"] > 0, "first load must render"
    assert seen["afterPoll"] == seen["afterFirst"], "background poll must not repaint"
    assert seen["chipAfterPoll"], "new evidence must be offered via the refresh chip"
    assert seen["afterAccept"] > seen["afterPoll"], "accepting the chip must repaint"
    assert not seen["chipAfterAccept"], "chip must clear once the reader accepts"


def test_unchanged_payload_does_not_raise_a_refresh_chip():
    # A chip that appears when nothing changed trains the reader to ignore it.
    seen = _run_paper_refresh_probe([_PAPER_PAYLOAD_A, _PAPER_PAYLOAD_A, _PAPER_PAYLOAD_A])
    assert not seen["chipAfterPoll"]
    assert seen["afterPoll"] == seen["afterFirst"]


def test_coverage_rule_bar_reads_duration_and_exit_targets_from_payload():
    out = _run_paper_js_probe(
        "const gates = [\n"
        "  { key: 'paper_duration', status: 'PENDING', evidence: '12 paper day(s) in paper_history.json', metrics: { observed: 12, target: 45 } },\n"
        "  { key: 'regime_coverage', status: 'PASS', evidence: 'Normal + Stress', metrics: { regimes: ['Normal', 'Stress'] } },\n"
        "  { key: 'exit_path_coverage', status: 'PENDING', evidence: 'Chandelier 6 | MAX_HOLD 7 | STP 5', metrics: { exits: { CHANDELIER: 6, MAX_HOLD: 7, STP: 5 }, target_each: 7 } },\n"
        "];\n"
        "__paperTest.updateCoveragePanel(gates, []);\n"
        "console.log(JSON.stringify({ rail: elements.get('coverageActiveSpec').innerHTML, title: elements.get('coverageProgressTitle').textContent }));"
    )
    values = json.loads(out)
    assert "45 days" in values["rail"]
    assert "&gt;= 7" in values["rail"]
    assert "60 days" not in values["rail"]
    assert "&gt;= 3" not in values["rail"]
    assert values["title"] == "days 12/45 | exits 1/3"


def test_coverage_rule_bar_shows_missing_spec_without_fake_progress():
    out = _run_paper_js_probe(
        "const gates = [\n"
        "  { key: 'paper_duration', status: 'PENDING', evidence: '12 paper day(s) in paper_history.json', metrics: { observed: 12 } },\n"
        "  { key: 'regime_coverage', status: 'PASS', evidence: 'Normal + Stress', metrics: { regimes: ['Normal', 'Stress'] } },\n"
        "  { key: 'exit_path_coverage', status: 'PENDING', evidence: 'Chandelier 6 | MAX_HOLD 7 | STP 5', metrics: { exits: { CHANDELIER: 6, MAX_HOLD: 7, STP: 5 } } },\n"
        "];\n"
        "__paperTest.updateCoveragePanel(gates, []);\n"
        "console.log(JSON.stringify({ rail: elements.get('coverageActiveSpec').innerHTML, html: elements.get('coverageMetricGroups').innerHTML, title: elements.get('coverageProgressTitle').textContent }));"
    )
    values = json.loads(out)
    assert "spec missing" in values["rail"]
    assert "60 days" not in values["rail"]
    assert "&gt;= 3" not in values["rail"]
    assert "width:100%" not in values["html"]
    assert values["title"] == "days 12/spec missing | exits missing/3"


def test_stp_panel_renders_session_threshold_from_payload_metrics():
    out = _run_paper_js_probe(
        "const gate = { key: 'stp_verification', status: 'PENDING', metrics: { checks: 1, distinct_sessions: 1, required_sessions: 10, false_halts: 0, double_stp: 0, unverified: 0, records: [{ date: '2026-08-10', verified: true, false_halt: false, double_stp: false, evidence: 'fixture proof order_id=42' }] } };\n"
        "__paperTest.updateSTPPanel([gate], []);\n"
        "console.log(JSON.stringify({ title: elements.get('stpProgressTitle').textContent, rail: elements.get('stpActiveSpec').innerHTML, html: elements.get('stpMetricGroups').innerHTML }));"
    )
    values = json.loads(out)
    assert values["title"] == "sessions 1/10 | accepted missing | matched failed missing"
    assert "10 distinct sessions" in values["rail"]
    assert "<b>1 / 10</b>" in values["html"]
    assert "width:10%" in values["html"]


def test_stp_panel_renders_missing_spec_without_fake_session_progress():
    out = _run_paper_js_probe(
        "const gate = { key: 'stp_verification', status: 'SPEC_GAP', metrics: { checks: 1, distinct_sessions: 1, false_halts: 0, double_stp: 0, unverified: 0, records: [{ date: '2026-08-10', verified: true, false_halt: false, double_stp: false, evidence: 'fixture proof' }] } };\n"
        "__paperTest.updateSTPPanel([gate], []);\n"
        "console.log(JSON.stringify({ title: elements.get('stpProgressTitle').textContent, rail: elements.get('stpActiveSpec').innerHTML, html: elements.get('stpMetricGroups').innerHTML, reason: elements.get('stpProgressReason').innerHTML }));"
    )
    values = json.loads(out)
    assert values["title"] == "spec missing | accepted missing | matched failed missing"
    assert "spec missing" in values["rail"]
    assert "spec missing" in values["html"]
    assert "c1-metric sample" not in values["html"]
    assert "width:100%" not in values["html"]
    assert "sessions 0/" not in values["reason"]


def test_stp_panel_treats_unmatched_failed_placements_as_context_not_breach():
    out = _run_paper_js_probe(
        "const gate = { key: 'stp_verification', status: 'PASS', metrics: { checks: 10, distinct_sessions: 10, required_sessions: 10, false_halts: 0, double_stp: 0, unverified: 0, records: [{ date: '2026-08-10', verified: true, false_halt: false, double_stp: false, evidence: 'fixture proof order_id=42' }] } };\n"
        "const placement = { key: 'stp_placement', status: 'PASS', evidence: '10 / 10 clean continuous session(s), 2 unmatched failed log line(s)', metrics: { accepted: 4, failed: 2, failed_matched_to_trade: 0, failed_unmatched_to_trade: 2, required_continuous_sessions: 10, continuous_session_streak: 10, max_failed: 0, spec: { max_trade_matched_failed: 0 } } };\n"
        "__paperTest.updateSTPPanel([gate], [placement]);\n"
        "console.log(JSON.stringify({ title: elements.get('stpProgressTitle').textContent, rail: elements.get('stpActiveSpec').innerHTML, html: elements.get('stpMetricGroups').innerHTML, reason: elements.get('stpProgressReason').innerHTML, status: elements.get('stpProgressStatus').textContent }));"
    )
    values = json.loads(out)
    assert values["status"] == "PASS"
    assert values["title"] == "sessions 10/10 | accepted 4 | matched failed 0"
    assert "trade-matched failed &lt;= 0" in values["rail"]
    assert "unmatched failed 2 context only" in values["reason"]
    assert "Only failed stop-placement lines matched to a paper trade can breach" in values["html"]
    assert "Unmatched failed stop-placement log lines are context only" in values["html"]
    assert '<article class="c1-metric bad"><span>Failed unmatched to trade</span>' not in values["html"]
    assert '<article class="c1-metric neutral"><span>Failed unmatched to trade</span>' in values["html"]


def test_unpriced_cells_render_as_dashes_not_zero_dollars():
    out = _run_paper_js_helpers(
        "console.log(JSON.stringify({"
        "  unknown: fmtMoney(priceUsd(3022.5, pointValueFor('MNKD', {}), 1)),"
        "  known: fmtMoney(priceUsd(3022.5, pointValueFor('M2K', {MNKD: {}, M2K: {point_value: 5}}), 1)),"
        "}));"
    )
    values = json.loads(out)
    assert values["unknown"] == "--", "missing point_value must not render as a dollar amount"
    assert values["unknown"] != "+$0.00"
    assert values["known"] == "+$15,112.50"


def test_ops_launcher_centralizes_backend_and_scheduler_commands():
    source = (ROOT / "monitor" / "ops.py").read_text(encoding="utf-8")

    assert "monitor/start_backend.py" in source
    assert "global_index.run_scheduler" in source
    assert '"--shadow-resume"' in source
    assert "flask" not in source.lower()
    assert "netstat" in source
    assert "taskkill" in source
    assert "Stop-Process -Name" not in source


def _ops_stub(monkeypatch, calls, *, schedulers, backends):
    """Drive cmd_up without touching a single real process.

    The stub honours the kill: ensure_single re-scans after taskkill on purpose, so a stub
    that kept reporting dead pids would make the guard refuse and hide the real behaviour.
    """
    from monitor import ops

    # Stage 5ZZN. These describe a LEGACY start, and Stage 5ZZN made a legacy start refuse
    # while a signed B1 decision says legacy has retired from this login. That guard is
    # correct and is tested in the 5ZZN suite; here it was reading the real machine's
    # confirmation file, so these process-management tests began failing for a reason that has
    # nothing to do with process management. Pointed at a path that does not exist, which is
    # the pre-B1 world they were written for.
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION",
                        Path("no-such-confirmation-for-this-test.json"))

    live = {"sched": list(schedulers) if schedulers is not None else None,
            "backend": list(backends) if backends is not None else None}

    def fake_scan(pattern):
        found = live["sched"] if pattern == ops.SCHEDULER_PATTERN else live["backend"]
        if found is None:
            return ops.ProcessScan(ok=False, error="probe blew up")
        return ops.ProcessScan(ok=True, processes=[
            ops.RunningProcess(pid=pid, command="stub", started="2026-08-13 04:30:22")
            for pid in found
        ])

    def fake_taskkill(pids):
        calls.append(("taskkill", sorted(pids)))
        for key in ("sched", "backend"):
            if live[key] is not None:
                live[key] = [pid for pid in live[key] if pid not in set(pids)]
        return []

    monkeypatch.setattr(ops, "scan_processes", fake_scan)
    monkeypatch.setattr(ops, "_taskkill", fake_taskkill)
    monkeypatch.setattr(ops, "_ops_log", lambda message: None)
    monkeypatch.setattr(ops, "time", type("_t", (), {"sleep": staticmethod(lambda _s: None)})())
    monkeypatch.setattr(
        ops, "start_scheduler",
        # `track1_shadow`/`track1_only` accepted because the real signature grew them in
        # Stages 5K and 5M-D. A stub narrower than the function it replaces fails as a
        # TypeError raised from inside production code — the same stale-stub family as the
        # stage-4 `_run` lambda — and this suite only trips it on the restart path, which is
        # the first caller to pass them through.
        lambda port, *, shadow_resume, assume_preflight_ok, track1_shadow=False,
               track1_only=False:
            calls.append(("start_scheduler", port, shadow_resume, assume_preflight_ok)) or 303,
    )
    # Same stale-stub trap as start_scheduler above: `start_backend` grew the Track 1 flags
    # on 2026-08-24, and a two-argument stub would fail as a TypeError raised from inside
    # ops.main. The flags are RECORDED, not swallowed, so a test can assert the backend was
    # told what the scheduler was told.
    monkeypatch.setattr(
        ops, "start_backend",
        lambda ibkr, api, *, track1_shadow=False, track1_only=False:
            calls.append(("start_backend", ibkr, api, track1_shadow, track1_only)) or 404)
    monkeypatch.setattr(ops, "wait_backend", lambda port: {"connected": True})
    return ops


def test_ops_up_refuses_when_the_scheduler_is_already_duplicated(monkeypatch):
    """The condition that produced the 2026-08-13 double MAX_HOLD run. Starting a third on
    top of it is the one thing ops.py must never do."""
    calls = []
    ops = _ops_stub(monkeypatch, calls, schedulers=[29340, 35120], backends=[])
    assert ops.main(["up"]) == 2
    assert calls == []


def test_ops_up_refuses_when_it_cannot_tell_what_is_running(monkeypatch):
    calls = []
    ops = _ops_stub(monkeypatch, calls, schedulers=None, backends=[])
    assert ops.main(["up"]) == 2
    assert calls == []


def test_ops_up_leaves_one_healthy_scheduler_alone_and_replaces_the_backend(monkeypatch):
    calls = []
    ops = _ops_stub(monkeypatch, calls, schedulers=[29340], backends=[555])
    assert ops.main(["up", "--yes"]) == 0
    assert calls == [("taskkill", [555]), ("start_backend", 4002, 5002, False, False)]


def test_ops_up_starts_a_scheduler_when_none_is_running(monkeypatch):
    calls = []
    ops = _ops_stub(monkeypatch, calls, schedulers=[], backends=[])
    assert ops.main(["--ibkr-port", "4003", "--api-port", "5003", "up", "--yes"]) == 0
    assert calls == [
        ("start_scheduler", 4003, True, False),
        ("start_backend", 4003, 5003, False, False),
    ]


def test_ops_restart_scheduler_stops_every_instance_before_starting_one(monkeypatch):
    calls = []
    ops = _ops_stub(monkeypatch, calls, schedulers=[29340, 35120], backends=[])
    assert ops.main(["restart", "--scheduler", "--yes"]) == 0
    assert calls[0] == ("taskkill", [29340, 35120])
    assert ("start_scheduler", 4002, True, False) in calls


# ── Stage 5AB: the backend child must be told what the scheduler was told ────
#
# Root cause measured on the live box 2026-08-24: `ops.py status` read
# `track1_mode=track1-only-shadow` off the RUNNING scheduler's command line, while
# `/api/v1/schedule-status` served `state_slot_count=45` and a legacy `next_decision_job`.
# `start_scheduler` passed `_env(track1_shadow=..., track1_only=...)`; `start_backend`
# passed a bare `_env()`. Two children of one `up`, disagreeing about which route runs.

def test_start_backend_carries_track1_only_into_the_child_environment(monkeypatch):
    import monitor.ops as ops
    captured = {}

    class _P:
        pid = 4242

    def _popen(args, **kw):
        captured.update(kw)
        return _P()

    monkeypatch.setattr(ops.subprocess, "Popen", _popen)
    monkeypatch.setattr(ops, "_open_log", lambda name: None)
    ops.start_backend(4002, 5002, track1_shadow=True, track1_only=True)
    env = captured["env"]
    assert env["RAITS_TRACK1_ONLY"] == "1"
    assert env["RAITS_TRACK1_SHADOW"] == "1"
    # the ledger/telemetry homes travel too, or a reader looks in the wrong directory
    assert env["RAITS_WINDOW_LEDGER_DIR"] == str(ops.TRACK1_LEDGER_DIR)
    assert env["RAITS_TELEMETRY_DIR"] == str(ops.TRACK1_TELEMETRY_DIR)
    # widening this must NEVER be able to arm the route
    assert ops.TRACK1_ORDERS_ENV not in env


def test_start_backend_carries_transitional_track1_shadow(monkeypatch):
    import monitor.ops as ops
    captured = {}

    class _P:
        pid = 4242

    monkeypatch.setattr(ops.subprocess, "Popen",
                        lambda args, **kw: (captured.update(kw), _P())[1])
    monkeypatch.setattr(ops, "_open_log", lambda name: None)
    ops.start_backend(4002, 5002, track1_shadow=True)
    env = captured["env"]
    assert env["RAITS_TRACK1_SHADOW"] == "1"
    assert "RAITS_TRACK1_ONLY" not in env


def test_start_backend_default_stays_legacy(monkeypatch):
    """The regression that matters most: an ordinary `ops.py up` must not switch the
    dashboard to a route nobody asked for."""
    import monitor.ops as ops
    captured = {}

    class _P:
        pid = 4242

    monkeypatch.setattr(ops.subprocess, "Popen",
                        lambda args, **kw: (captured.update(kw), _P())[1])
    monkeypatch.setattr(ops, "_open_log", lambda name: None)
    ops.start_backend(4002, 5002)
    env = captured["env"]
    assert "RAITS_TRACK1_ONLY" not in env
    assert "RAITS_TRACK1_SHADOW" not in env


def test_ops_up_track1_only_tells_the_backend_too(monkeypatch):
    """End to end through `main`, not just the helper: the flag has to survive the whole
    dispatch, which is the seam the live defect actually sat in."""
    calls = []
    ops = _ops_stub(monkeypatch, calls, schedulers=[], backends=[])
    monkeypatch.setattr(ops, "track1_shadow_blockers", lambda *, track1_only=False: [])
    rc = ops.main(["up", "--yes", "--track1-only-shadow"])
    assert rc == 0, calls
    backend = [c for c in calls if c[0] == "start_backend"]
    assert backend, calls
    assert backend[0][3] is True and backend[0][4] is True, backend


def test_restart_no_scheduler_reaches_the_backend_without_touching_the_scheduler(monkeypatch):
    """The operator's only safe way to correct a dashboard mirroring the wrong route.

    Until 2026-08-24 this refused: the Track 1 guard fired for any running scheduler, and
    its advice was `restart --scheduler`, i.e. bounce a live scheduler to fix a dashboard.
    That is the more dangerous of the two acts. With `--no-scheduler` the operator has said
    in as many words to leave it alone, and the flag now has a real effect without it.
    """
    calls = []
    ops = _ops_stub(monkeypatch, calls, schedulers=[33868], backends=[555])
    monkeypatch.setattr(ops, "track1_shadow_blockers", lambda *, track1_only=False: [])
    rc = ops.main(["restart", "--no-scheduler", "--yes", "--track1-only-shadow"])
    assert rc == 0, calls
    assert not any(c[0] == "start_scheduler" for c in calls), calls
    backend = [c for c in calls if c[0] == "start_backend"]
    assert backend, calls
    assert backend[0][3] is True and backend[0][4] is True, backend


def test_restart_no_scheduler_also_works_for_transitional_shadow(monkeypatch):
    calls = []
    ops = _ops_stub(monkeypatch, calls, schedulers=[33868], backends=[555])
    monkeypatch.setattr(ops, "track1_shadow_blockers", lambda *, track1_only=False: [])
    assert ops.main(["restart", "--no-scheduler", "--yes", "--track1-shadow"]) == 0
    backend = [c for c in calls if c[0] == "start_backend"]
    assert backend and backend[0][3] is True and backend[0][4] is False, backend


def test_up_still_refuses_the_track1_flag_against_a_running_scheduler(monkeypatch):
    """The refusal must stay for `up`. There the operator did NOT say --no-scheduler, so a
    flag that silently reached only the backend would leave them believing the scheduler
    had been switched too."""
    calls = []
    ops = _ops_stub(monkeypatch, calls, schedulers=[33868], backends=[555])
    monkeypatch.setattr(ops, "track1_shadow_blockers", lambda *, track1_only=False: [])
    assert ops.main(["up", "--yes", "--track1-only-shadow"]) == 2
    assert not any(c[0] == "start_backend" for c in calls), calls


def test_ops_startup_command_is_documented():
    docs = "\n".join([
        (ROOT / "docs" / "futures" / "DAILY_FLOW.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "futures" / "OPERATIONS.md").read_text(encoding="utf-8"),
        (ROOT / "monitor" / "DASHBOARD_PLAN.md").read_text(encoding="utf-8"),
    ])

    assert "python monitor\\ops.py up" in docs
    assert "python monitor\\ops.py restart" in docs
    assert "python monitor\\ops.py status" in docs
    assert "python -m flask --app monitor.backend.app:app run" in docs
    assert "broker truth unavailable" in docs


def test_c1_scope_decision_is_documented():
    docs = "\n".join([
        (ROOT / "monitor" / "DASHBOARD_PLAN.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "futures" / "PAPER_DASHBOARD_INPUT_VERIFY_PLAN.md").read_text(encoding="utf-8"),
    ])
    assert "close_scope=stp_only" in docs
    assert "slip ticks = slip points / tick" in docs
    assert "Signal/market CLOSE rows are excluded from C1" in docs
    assert "Paper P&L vs backtest" in docs


def test_runner_positions_reader_projects_persisted_contracts(tmp_path: Path):
    path = tmp_path / "live_positions.json"
    path.write_text(
        '{"schema_version":1,"positions":[{"inst":"M2K","direction":"LONG",'
        '"contracts":1,"cluster":"swing","entry_day":"2026-08-10 00:00:00",'
        '"entry_price":3025.3,"stop_order_id":"288","ignored":"value"}]}',
        encoding="utf-8",
    )
    result = read_runner_positions(path)
    assert result["source"] == "runner_persisted_positions"
    assert result["payload"]["positions"][0]["contracts"] == 1
    assert "ignored" not in result["payload"]["positions"][0]


def test_report_api_omits_raw_log_lines(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(report_reader, "_signature", lambda _root: ())
    monkeypatch.setattr(report_reader, "collect_session_report", lambda _day, _root: {
        "day": "2026-08-11", "lines": [("12:00", "INFO", "large raw line")], "issues": []
    })
    report = report_reader.read_report("2026-08-11", tmp_path)
    assert "lines" not in report
    assert "execution_quality" in report["daily"]


def test_report_cache_signature_tracks_live_positions(tmp_path: Path):
    positions = tmp_path / "live_positions.json"
    positions.write_text('{"positions": []}', encoding="utf-8")
    before = report_reader._signature(tmp_path)
    positions.write_text('{"positions": [{"inst": "MES"}]}', encoding="utf-8")
    after = report_reader._signature(tmp_path)
    assert before != after


def test_report_cache_signature_tracks_trade_log(tmp_path: Path):
    trades = tmp_path / "trade_log.jsonl"
    trades.write_text('', encoding="utf-8")
    before = report_reader._signature(tmp_path)
    trades.write_text('{"type":"OPEN"}\n', encoding="utf-8")
    after = report_reader._signature(tmp_path)
    assert before != after


def test_backend_routes_are_read_only():
    allowed = {"GET", "HEAD", "OPTIONS"}
    for rule in app.url_map.iter_rules():
        assert set(rule.methods) <= allowed, (rule.rule, rule.methods)


def test_backend_does_not_import_runner_or_write_state():
    banned_calls = {"place_order", "send_order", "cancel_order", "write_text", "write_bytes"}
    for path in BACKEND.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(name.name != "global_index.runner" for name in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module != "global_index.runner"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in banned_calls, (path.name, node.func.attr)


def test_ibkr_reader_default_client_id_is_99():
    assert inspect.signature(ibkr_reader.start).parameters["client_id"].default == 99


def test_execution_quality_keeps_execution_slippage_separate_from_stop_distance(tmp_path: Path):
    (tmp_path / "trade_log.jsonl").write_text(
        '{"type":"OPEN","inst":"MES","cluster":"swing","direction":"LONG",'
        '"contracts":1,"filled_qty":1,"entry_day":"2026-08-12","expected_entry":7000.0,'
        '"fill_price":7000.75,"slip":0.75,"status":"FILLED","ts":"2026-08-12T14:10:00Z"}\n'
        '{"type":"CLOSE","inst":"MES","cluster":"swing","direction":"LONG",'
        '"contracts":1,"filled_qty":1,"entry_day":"2026-08-11","exit_day":"2026-08-12",'
        '"expected_stop":6950.0,"fill_price":7010.0,"slip":-60.0,"status":"FILLED",'
        '"ts":"2026-08-12T14:20:00Z"}\n',
        encoding="utf-8",
    )
    result = read_execution_quality(tmp_path, "2026-08-12")
    opened, signal_close = result["fills"]
    assert opened["reference_type"] == "expected_entry"
    assert opened["signed_slippage_ticks"] == 3.0
    assert opened["exception"] is True
    assert signal_close["reference_type"] == "protective_stop_reference"
    assert signal_close["metric_type"] == "distance_to_stop"
    assert signal_close["signed_slippage_ticks"] is None
    assert signal_close["signed_distance_to_stop_ticks"] == -240.0
    assert result["coverage"]["signal_close_expected_price_missing"] == 1
    assert result["coverage"]["commission_emitted"] == 0
    assert result["coverage"]["route_emitted"] == 0


def test_execution_quality_computes_signed_stop_fill_slippage_and_ignores_torn_line(tmp_path: Path):
    (tmp_path / "trade_log.jsonl").write_text(
        '{"type":"CLOSE","inst":"MNKD","direction":"SHORT","contracts":1,"filled_qty":1,'
        '"entry_day":"2026-08-11","exit_day":"2026-08-12","exit_reason":"STP",'
        '"expected_stop":67000,"fill_price":67015,"status":"FILLED","perm_id":44}\n'
        '{"type":"OPEN"',
        encoding="utf-8",
    )
    result = read_execution_quality(tmp_path, "2026-08-12")
    fill = result["fills"][0]
    assert fill["reference_type"] == "stop_trigger"
    assert fill["signed_slippage_points"] == 15.0
    assert fill["signed_slippage_ticks"] == 3.0
    assert fill["adverse"] is True
    assert result["coverage"]["stable_execution_id_emitted"] == 1
    assert result["coverage"]["malformed_lines"] == 1


def test_static_dashboard_is_served():
    client = app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/realtime").status_code == 200
    assert client.get("/analytics").status_code == 200
    assert client.get("/paper").status_code == 200
    assert client.get("/reports").status_code == 200
    assert client.get("/api/v1/paper-evidence").status_code == 200
    assert client.get("/api/v1/execution-quality").status_code == 200
    assert client.get("/api/v1/execution-quality/2026-08-12").status_code == 200
    assert client.post("/api/v1/broker").status_code == 405


def test_header_clock_declares_four_iana_zones():
    """A mistyped IANA zone makes Intl.DateTimeFormat throw RangeError, and that kills the
    whole header render — not just the clock. Nothing else catches it before a browser."""
    source = (DASH / "realtime" / "realtime.js").read_text(encoding="utf-8")
    for zone in ("America/New_York", "Asia/Tokyo", "Asia/Ho_Chi_Minh", "America/Edmonton"):
        assert zone in source, f"realtime.js no longer declares IANA zone {zone}"

    # The clock markup is generated into the status rail, so its ids live in the script.
    assert 'id="railClockEt"' in source
    assert 'id="railClockZones"' in source

    markup = (DASH / "realtime" / "index.html").read_text(encoding="utf-8")
    assert 'id="journalSchedule"' in markup


def test_session_events_extract_operational_timeline(tmp_path: Path):
    log = tmp_path / "live_day_0811.log"
    log.write_text(
        "2026-08-11 12:05:14 INFO global_index.ibkr_broker - place_stop: accepted SHORT MYM STP ×1 @ 54033.0000 orderId=284 status=PreSubmitted cluster=roska4_swing\n"
        "2026-08-11 12:08:27 INFO global_index.ibkr_broker - send_order: placed CLOSE BUY MYM ×1 cluster=roska4_swing\n"
        "2026-08-11 12:08:27 INFO global_index.ibkr_broker - send_order: FILLED CLOSE MYM ×1 @ 53968.0000 (elapsed=0.3s)\n"
        "2026-08-11 12:08:28 INFO global_index.runner - STP: cancelled GTC stop orderId=284 for closed MYM/roska4_swing\n",
        encoding="utf-8",
    )
    result = read_session_events("2026-08-11", tmp_path)
    assert [event["kind"] for event in result["events"]] == [
        "stop_armed", "market_close_submitted", "market_close_filled", "stop_cancelled_after_close"
    ]
    assert result["events"][0]["ts"].endswith("18:05:14Z")
    assert [event["sequence"] for event in result["events"]] == [0, 1, 2, 3]


def test_session_events_extract_entries_and_dedupe_rejections(tmp_path: Path):
    log = tmp_path / "live_day_0810.log"
    log.write_text(
        "2026-08-10 12:40:56 INFO broker - send_order: placed OPEN SELL MES ×1 cluster=roska4_swing\n"
        "2026-08-10 12:40:56 INFO broker - send_order: FILLED OPEN MES ×1 @ 7773.0000 (elapsed=0.3s)\n"
        "2026-08-10 12:40:58 WARNING run_live_day - REJECTED SHORT MNQ (roska4_swing) risk_sized=$3340.54 â€” roska4_swing gross 8.4% > cap 5.0%\n"
        "2026-08-10 12:50:58 WARNING run_live_day - REJECTED SHORT MNQ (roska4_swing) risk_sized=$3340.54 â€” roska4_swing gross 8.4% > cap 5.0%\n",
        encoding="utf-8",
    )
    events = read_session_events("2026-08-10", tmp_path)["events"]
    assert [event["kind"] for event in events] == [
        "market_open_submitted", "market_open_filled", "entry_rejected"
    ]
    assert events[-1]["occurrences"] == 2
    assert events[-1]["reason"] == "roska4_swing gross 8.4% > cap 5.0%"


def test_session_events_extract_exit_reason_and_pnl(tmp_path: Path):
    (tmp_path / "live_day_0811.log").write_text(
        "2026-08-11 12:08:27 INFO runner - LEDGER: MYM SHORT x1 roska4_swing "
        "53969.0000 → 53968.0000 = +0.50 (signal exit) | sleeve equity 50162.50\n",
        encoding="utf-8",
    )
    event = read_session_events("2026-08-11", tmp_path)["events"][0]
    assert event["kind"] == "trade_exit_decision"
    assert event["exit_reason"] == "signal exit"
    assert event["pnl"] == "+0.50"


def test_session_events_pair_reconcile_problem_with_later_match(tmp_path: Path):
    (tmp_path / "live_day_0810.log").write_text(
        "2026-08-10 00:05:22 CRITICAL global_index.runner - B3 MISMATCH: file has LONG MNKD ×1 but IBKR shows ×0 — investigate before trading; file state will be used\n"
        "2026-08-10 00:05:22 CRITICAL global_index.runner - B3 ORPHAN: IBKR has LONG NKD ×1 with no matching file entry — position opened outside this runner?\n"
        "2026-08-10 00:10:21 CRITICAL global_index.runner - B3 MISMATCH: file has LONG MNKD ×1 but IBKR shows ×0 — investigate before trading; file state will be used\n"
        "2026-08-10 12:05:20 INFO global_index.runner - B3: broker/file positions match (1 position(s))\n",
        encoding="utf-8",
    )
    events = read_session_events("2026-08-10", tmp_path)["events"]
    incident = next(event for event in events if event["kind"] == "broker_reconcile_incident")
    assert incident["status"] == "recovered"
    assert incident["occurrences"] == 3
    assert incident["reconcile_types"] == ["mismatch", "orphan"]
    assert incident["instruments"] == ["MNKD", "NKD"]
    assert incident["recovered_at"].endswith("18:05:20Z")


def test_session_events_extract_runner_stop_replacement(tmp_path: Path):
    (tmp_path / "live_day_0811.log").write_text(
        "2026-08-11 12:05:14 WARNING global_index.runner - B4 REPLACED: MYM/roska4_swing was open with no stop order — re-placed @ 54032.8900 orderId=284\n",
        encoding="utf-8",
    )
    event = read_session_events("2026-08-11", tmp_path)["events"][0]
    assert event["kind"] == "stop_repaired"
    assert event["status"] == "recovered"
    assert event["inst"] == "MYM"
    assert event["order_id"] == "284"
    assert event["price"] == "54032.8900"


def test_session_event_lifecycle_normalization_is_idempotent(tmp_path: Path):
    (tmp_path / "live_day_0811.log").write_text(
        "2026-08-11 00:00:00 INFO runner - B4: MYM/roska4_swing chua co STP trong cua so hoan\n"
        "2026-08-11 12:05:14 INFO broker - place_stop: accepted SHORT MYM STP ×1 @ 54033.0000 orderId=284 status=PreSubmitted cluster=roska4_swing\n"
        "2026-08-11 12:05:14 WARNING runner - B4 REPLACED: MYM/roska4_swing was open with no stop order — re-placed @ 54032.8900 orderId=284\n",
        encoding="utf-8",
    )
    first = read_session_events("2026-08-11", tmp_path)["events"]
    second = read_session_events("2026-08-11", tmp_path)["events"]
    assert first == second
    assert [event["kind"] for event in second] == ["stop_deferred", "stop_armed_after_deferral"]


def test_session_events_collapse_deferred_accept_and_b4_line_into_expected_arming(tmp_path: Path):
    (tmp_path / "live_day_0811.log").write_text(
        "2026-08-11 11:55:00 INFO runner - B4: MYM/roska4_swing chua co STP - dang trong cua so hoan CO CHU DICH\n"
        "2026-08-11 12:05:14 INFO broker - place_stop: accepted SHORT MYM STP Ã—1 @ 54033.0000 orderId=284 status=PreSubmitted cluster=roska4_swing\n"
        "2026-08-11 12:05:14 WARNING runner - B4 REPLACED: MYM/roska4_swing was open with no stop order â€” re-placed @ 54032.8900 orderId=284\n",
        encoding="utf-8",
    )
    events = read_session_events("2026-08-11", tmp_path)["events"]
    assert [event["kind"] for event in events] == ["stop_deferred", "stop_armed_after_deferral"]
    armed = events[-1]
    assert armed["status"] == "info"
    assert armed["accepted_price"] == "54033.0000"
    assert armed["order_id"] == "284"
    assert "No incident" in armed["impact"]


def test_session_events_expose_stop_id_drift_as_open_issue(tmp_path: Path):
    (tmp_path / "live_day_0811.log").write_text(
        "2026-08-11 12:05:14 WARNING runner - B4 STP ID DRIFT: LONG MES x1 (roska4_swing) IS covered at the broker, but the recorded stop_order_id=62 names no working order. Not re-placing.\n",
        encoding="utf-8",
    )
    event = read_session_events("2026-08-11", tmp_path)["events"][0]
    assert event["kind"] == "stop_id_drift"
    assert event["status"] == "open"
    assert event["recorded_order_id"] == "62"
    assert "cancel a ghost ID" in event["impact"]


def test_session_events_mark_naked_stop_recovered_by_later_accepted_stop(tmp_path: Path):
    (tmp_path / "live_day_0811.log").write_text(
        "2026-08-11 12:05:10 CRITICAL runner - B4 NAKED: LONG M2K x1 (roska4_swing) open at IBKR with NO stop order (stop_price=3020.24). No overnight protection.\n"
        "2026-08-11 12:05:15 INFO broker - place_stop: accepted LONG M2K STP Ã—1 @ 3020.2000 orderId=288 status=PreSubmitted cluster=roska4_swing\n",
        encoding="utf-8",
    )
    events = read_session_events("2026-08-11", tmp_path)["events"]
    naked = next(event for event in events if event["kind"] == "stop_naked")
    assert naked["status"] == "recovered"
    assert naked["recovered_at"].endswith("18:05:15Z")


def test_session_events_pair_tws_outage_across_et_local_date_boundary(tmp_path: Path):
    (tmp_path / "live_day_0811.log").write_text(
        "2026-08-11 23:50:29 WARNING broker - IBKR code=1100 reqId=-1: Connectivity between IBKR and Trader Workstation has been lost.\n"
        "2026-08-11 23:50:51 WARNING broker - IBKR code=1102 reqId=-1: Connectivity between IBKR and Trader Workstation has been restored - data maintained.\n",
        encoding="utf-8",
    )
    events = read_session_events("2026-08-12", tmp_path)["events"]
    assert len(events) == 1
    outage = events[0]
    assert outage["kind"] == "connectivity_outage"
    assert outage["service"] == "tws"
    assert outage["status"] == "recovered"
    assert outage["duration_seconds"] == 22
    assert outage["started_at"].endswith("05:50:29Z")
    assert outage["recovered_at"].endswith("05:50:51Z")
    assert outage["down_code"] == "1100"
    assert outage["recovery_code"] == "1102"


def test_session_events_group_repeated_farm_down_codes_into_one_lifecycle(tmp_path: Path):
    (tmp_path / "live_day_0812.log").write_text(
        "2026-08-12 10:00:00 WARNING broker - IBKR code=2103 reqId=-1: Market data farm connection is broken:usfarm\n"
        "2026-08-12 10:00:05 WARNING broker - IBKR code=2103 reqId=-1: Market data farm connection is broken:usfarm\n"
        "2026-08-12 10:00:12 WARNING broker - IBKR code=2104 reqId=-1: Market data farm connection is OK:usfarm\n",
        encoding="utf-8",
    )
    events = read_session_events("2026-08-12", tmp_path)["events"]
    assert len(events) == 1
    outage = events[0]
    assert outage["service"] == "market_data"
    assert outage["status"] == "recovered"
    assert outage["duration_seconds"] == 12
    assert outage["evidence"].count("2103:") == 2


def test_session_events_keep_unrecovered_connectivity_outage_open(tmp_path: Path):
    (tmp_path / "live_day_0812.log").write_text(
        "2026-08-12 10:00:00 WARNING broker - IBKR code=2157 reqId=-1: Sec-def data farm connection is broken:secdefnj\n",
        encoding="utf-8",
    )
    outage = read_session_events("2026-08-12", tmp_path)["events"][0]
    assert outage["kind"] == "connectivity_outage"
    assert outage["service"] == "security_definition"
    assert outage["status"] == "open"
    assert outage["recovered_at"] is None
    assert "no matching IBKR recovery code" in outage["resolution"]


def test_session_events_group_correlated_services_into_one_parent_episode(tmp_path: Path):
    (tmp_path / "live_day_0811.log").write_text(
        "2026-08-11 23:50:25 WARNING broker - IBKR code=2103 reqId=-1: Market data farm connection is broken:usfarm\n"
        "2026-08-11 23:50:25 WARNING broker - IBKR code=2157 reqId=-1: Sec-def data farm connection is broken:secdefnj\n"
        "2026-08-11 23:50:25 WARNING broker - IBKR code=2105 reqId=-1: HMDS data farm connection is broken:ushmds\n"
        "2026-08-11 23:50:29 WARNING broker - IBKR code=1100 reqId=-1: Connectivity between IBKR and Trader Workstation has been lost.\n"
        "2026-08-11 23:50:50 WARNING broker - IBKR code=2158 reqId=-1: Sec-def data farm connection is OK:secdefnj\n"
        "2026-08-11 23:50:51 WARNING broker - IBKR code=2106 reqId=-1: HMDS data farm connection is OK:ushmds\n"
        "2026-08-11 23:50:51 WARNING broker - IBKR code=2104 reqId=-1: Market data farm connection is OK:usfarm\n"
        "2026-08-11 23:50:51 WARNING broker - IBKR code=1102 reqId=-1: Connectivity between IBKR and Trader Workstation has been restored - data maintained.\n",
        encoding="utf-8",
    )
    events = read_session_events("2026-08-12", tmp_path)["events"]
    assert len(events) == 1
    episode = events[0]
    assert episode["service"] == "multiple"
    assert set(episode["affected_services"]) == {
        "tws", "market_data", "historical_data", "security_definition"
    }
    assert episode["status"] == "recovered"
    assert episode["duration_seconds"] == 26
    assert len(episode["services"]) == 4
    assert "1100 -> 1102" in episode["evidence"]


def test_session_events_group_hmm_fit_diagnostics_without_opening_incident(tmp_path: Path):
    (tmp_path / "live_day_0812.log").write_text(
        "2026-08-12 00:00:01 INFO run_live_day - [hmm]  fit_C labels (hmm_fit_end=2024-12-31)...\n"
        "2026-08-12 00:00:02 INFO engine - HMM fit started: 2012 price observations, covariance=diag, n_init=10\n"
        "2026-08-12 00:00:04 WARNING hmmlearn - Model is not converging.  Current: 9945.82 is not greater than 9945.97. Delta is -0.15\n"
        "2026-08-12 00:00:05 INFO engine - Best initialisation: log-prob=9945.43 (out of 10 tries)\n"
        "2026-08-12 00:00:05 INFO engine - HMM Model Summary (version: fit_first)\n"
        "2026-08-12 00:00:05 INFO engine - State 0 (Calm): mean=[0.001002 0.069346] var_trace=0.000690\n"
        "2026-08-12 00:00:05 INFO engine - State 1 (Normal): mean=[0.000539 0.156819] var_trace=0.001742\n"
        "2026-08-12 00:00:05 INFO engine - State 2 (Stress): mean=[-0.001482 0.353277] var_trace=0.038326\n"
        "2026-08-12 00:00:09 INFO run_live_day - 2163 SPY label days\n"
        "2026-08-12 00:05:02 INFO engine - HMM fit started: 2012 price observations, covariance=diag, n_init=10\n"
        "2026-08-12 00:05:05 INFO engine - Best initialisation: log-prob=9946.12 (out of 10 tries)\n"
        "2026-08-12 00:05:05 INFO engine - HMM Model Summary (version: fit_latest)\n",
        encoding="utf-8",
    )
    events = read_session_events("2026-08-12", tmp_path)["events"]
    assert len(events) == 1
    diagnostic = events[0]
    assert diagnostic["kind"] == "hmm_fit_diagnostic"
    assert diagnostic["status"] == "diagnostic"
    assert diagnostic["attempts"] == 2
    assert diagnostic["completed_fits"] == 2
    assert diagnostic["non_convergence_count"] == 1
    assert diagnostic["fit_end"] == "2024-12-31"
    assert diagnostic["model_version"] == "fit_latest"
    assert diagnostic["spy_label_days"] == 2163
    assert [state["label"] for state in diagnostic["states"]] == ["Calm", "Normal", "Stress"]
    assert "no documented decision gate failure" in diagnostic["impact"]
    assert "Fitted states: Calm" in diagnostic["evidence"]


def test_job_journal_groups_events_and_known_debt(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 12:05:00 INFO run_scheduler - [LIVE_DAY_1405] python -m global_index.run_live_day\n"
        "2026-08-11 12:08:34 ERROR run_scheduler - [LIVE_DAY_1405] thoat OK nhung da ghi 1 dong CRITICAL/ERROR - KHONG bo qua:\n"
        "2026-08-11 12:08:34 ERROR run_scheduler - [LIVE_DAY_1405] G2 HARD: model 20 months old\n",
        encoding="utf-8",
    )
    (tmp_path / "live_day_0811.log").write_text(
        "2026-08-11 12:05:14 INFO global_index.ibkr_broker - place_stop: accepted SHORT MYM STP Ã—1 @ 54033.0000 orderId=284 status=PreSubmitted cluster=roska4_swing\n",
        encoding="utf-8",
    )
    result = read_job_journal("2026-08-11", tmp_path)
    job = result["jobs"][0]
    assert job["status"] == "completed_with_debt"
    assert job["duration_seconds"] == 214
    assert job["event_counts"] == {"stop_armed": 1}
    assert job["diagnostics"] == ["G2 HARD: model 20 months old"]


def test_job_journal_builds_sanitized_preflight_lifecycle(tmp_path: Path):
    secret = "do-not-render-this-api-key"
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 11:45:00 INFO run_scheduler - [PRE-FLIGHT] Starting: update_ibkr_daily -> update_spy_csv (2026-08-11)\n"
        "2026-08-11 11:45:00 INFO run_scheduler - [IBKR_UPDATE] python -m global_index.update_ibkr_daily --port 4002\n"
        "2026-08-11 11:47:06 INFO run_scheduler - [IBKR_UPDATE] completed OK\n"
        f"2026-08-11 11:47:06 INFO run_scheduler - [SPY_UPDATE] python -m global_index.update_spy_csv --api-key {secret}\n"
        "2026-08-11 11:47:28 INFO run_scheduler - [SPY_UPDATE] completed OK\n"
        "2026-08-11 11:47:28 INFO run_scheduler - [PRE-FLIGHT] OK - inputs fresh\n",
        encoding="utf-8",
    )
    result = read_job_journal("2026-08-11", tmp_path)
    job = result["jobs"][0]
    assert job["job_id"] == "PREFLIGHT"
    assert job["job_type"] == "preflight"
    assert job["status"] == "completed"
    assert [event["kind"] for event in job["events"]] == [
        "preflight_started", "preflight_ibkr_started", "preflight_ibkr_completed",
        "preflight_spy_started", "preflight_spy_completed", "preflight_passed",
    ]
    assert secret not in str(result)


def test_job_journal_makes_preflight_failure_actionable(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 11:45:00 INFO run_scheduler - [PRE-FLIGHT] Starting: update_ibkr_daily -> update_spy_csv (2026-08-11)\n"
        "2026-08-11 11:45:00 INFO run_scheduler - [IBKR_UPDATE] python -m global_index.update_ibkr_daily --port 4002\n"
        "2026-08-11 11:46:59 ERROR run_scheduler - [IBKR_UPDATE] exited with code 1\n"
        "2026-08-11 11:46:59 ERROR run_scheduler - [PRE-FLIGHT] update_ibkr_daily FAILED - live day skipped\n",
        encoding="utf-8",
    )
    job = read_job_journal("2026-08-11", tmp_path)["jobs"][0]
    assert job["status"] == "failed"
    assert job["reason"] == "ibkr_update_failed"
    assert "Live Day decision slots will be blocked" in job["impact"]
    assert "confirm both data sources are fresh" in job["action"]


def test_duplicate_launch_is_one_job_not_a_wall_of_phantoms(tmp_path: Path):
    """Live 2026-08-13: two scheduler processes fired MAX_HOLD in the same second. One was
    refused by IBKR (clientId 1 already taken) and dumped a traceback; the other did the work.

    Every traceback frame carries a Python install path, and the launch detector only asked
    whether the line contained "python" — so each frame was read as a fresh launch. One slot
    became nine jobs, one of them stuck "running", and the survivor's "completed OK" closed a
    phantom built from a traceback line."""
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 07:31:00 INFO run_scheduler - [MAX_HOLD_EXIT] C:\\Python311\\pythonw.exe -m global_index.run_maxhold_exit --port 4002\n"
        "2026-08-11 07:31:00 INFO run_scheduler - [MAX_HOLD_EXIT] C:\\Python311\\pythonw.exe -m global_index.run_maxhold_exit --port 4002\n"
        "2026-08-11 07:31:05 ERROR run_scheduler - [MAX_HOLD_EXIT] exited with code 1\n"
        # A refused connection dumps ~30 frames. The exception is the LAST line, so a cap that
        # trims from the end keeps only plumbing — the fixture has to be long enough to bite.
        + "".join(
            f"2026-08-11 07:31:05 ERROR run_scheduler - [MAX_HOLD_EXIT] stderr:   "
            f"File \"C:\\Python311\\Lib\\site-packages\\ib_insync\\ib.py\", line {300 + n}, in _run\n"
            for n in range(28)
        )
        + "2026-08-11 07:31:05 ERROR run_scheduler - [MAX_HOLD_EXIT] stderr: TimeoutError\n"
        "2026-08-11 07:31:12 INFO run_scheduler - [MAX_HOLD_EXIT] completed OK\n",
        encoding="utf-8",
    )
    jobs = [job for job in read_job_journal("2026-08-11", tmp_path)["jobs"]
            if job["job_id"] == "MAX_HOLD_EXIT"]
    assert len(jobs) == 1
    job = jobs[0]
    assert job["launch_count"] == 2
    assert job["status"] == "completed"
    assert job["reason"] == "duplicate launch: 1 of 2 runs failed"
    # The exception must survive the cap, and the dropped frames must be counted rather than
    # silently discarded.
    assert job["diagnostics"][-1] == "TimeoutError"
    assert job["diagnostics_omitted"] == 17


def test_same_slot_on_two_days_is_two_jobs(tmp_path: Path):
    """Live 2026-08-14: NKD_NIGHT_0200 runs once per night, and the reader stitches the
    previous local-date file to today's. Yesterday's run ended with "thoat OK nhung", which
    finished the job but left it in `active` — so tonight's launch was folded into it as a
    duplicate and then filtered away with yesterday's date. Eight slots vanished from the
    journal while the scheduler was running them."""
    (tmp_path / "scheduler_0813.log").write_text(
        "2026-08-13 00:00:00 INFO run_scheduler - [NKD_NIGHT_0200] C:\\Python311\\pythonw.exe -m global_index.run_live_day --clusters nkd\n"
        "2026-08-13 00:01:17 ERROR run_scheduler - [NKD_NIGHT_0200] thoat OK nhung da ghi 1 dong CRITICAL/ERROR\n",
        encoding="utf-8",
    )
    (tmp_path / "scheduler_0814.log").write_text(
        "2026-08-14 00:00:00 INFO run_scheduler - [NKD_NIGHT_0200] C:\\Python311\\pythonw.exe -m global_index.run_live_day --clusters nkd\n"
        "2026-08-14 00:01:17 ERROR run_scheduler - [NKD_NIGHT_0200] thoat OK nhung da ghi 1 dong CRITICAL/ERROR\n",
        encoding="utf-8",
    )
    tonight = [job for job in read_job_journal("2026-08-14", tmp_path)["jobs"]
               if job["job_id"] == "NKD_NIGHT_0200"]
    assert len(tonight) == 1
    assert tonight[0]["launch_count"] == 1
    assert tonight[0]["status"] == "completed_with_debt"


def test_single_failed_run_is_still_a_failure(tmp_path: Path):
    """The duplicate handling must not swallow a genuine one-process failure."""
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 07:31:00 INFO run_scheduler - [MAX_HOLD_EXIT] C:\\Python311\\pythonw.exe -m global_index.run_maxhold_exit --port 4002\n"
        "2026-08-11 07:31:05 ERROR run_scheduler - [MAX_HOLD_EXIT] exited with code 1\n"
        "2026-08-11 07:31:05 ERROR run_scheduler - [MAX_HOLD_EXIT] stderr: TimeoutError\n",
        encoding="utf-8",
    )
    jobs = [job for job in read_job_journal("2026-08-11", tmp_path)["jobs"]
            if job["job_id"] == "MAX_HOLD_EXIT"]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["launch_count"] == 1


def test_preflight_banner_is_not_reported_as_a_skip(tmp_path: Path):
    """run_scheduler:946 prints the fail-safe once at startup as a statement of policy. The
    line carries both "Pre-flight" and "skipped", so a keyword match rendered every restart
    as an amber PREFLIGHT SKIP — visually identical to the day the fail-safe really fires."""
    (tmp_path / "scheduler_0811.log").write_text(
        # Stamps are machine-local and the reader re-dates them to ET before filtering by day,
        # so a late-evening stamp lands on the next ET date and drops out of this one.
        "2026-08-11 11:40:41 INFO run_scheduler - Pre-flight fail-safe: update fail -> live_day skipped (no stale-data trades)\n"
        "2026-08-11 11:40:41 INFO run_scheduler - Scheduler started. Ctrl-C to stop.\n",
        encoding="utf-8",
    )
    events = read_job_journal("2026-08-11", tmp_path)["monitor_events"]
    assert [event["kind"] for event in events] == ["preflight_policy", "scheduler_started"]
    policy = events[0]
    assert policy["level"] == "info"
    assert policy["title"] == "Pre-flight fail-safe armed"
    assert policy["message"].startswith("Startup notice, not an event")


def test_real_preflight_failure_stays_a_job_not_a_monitor_notice(tmp_path: Path):
    """A fail-safe that actually fires is already a failed PREFLIGHT job carrying impact and
    action. It must not also appear as a monitor notice: one event, one card. The banner and
    the firing are different objects, and this is what keeps them apart."""
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 11:40:41 INFO run_scheduler - Pre-flight fail-safe: update fail -> live_day skipped (no stale-data trades)\n"
        "2026-08-11 11:46:59 ERROR run_scheduler - [PRE-FLIGHT] update_spy_csv FAILED - "
        "run_live_day WILL BE SKIPPED today (2026-08-11). Check POLYGON_API_KEY.\n",
        encoding="utf-8",
    )
    result = read_job_journal("2026-08-11", tmp_path)
    assert [event["kind"] for event in result["monitor_events"]] == ["preflight_policy"]
    job = result["jobs"][0]
    assert job["job_id"] == "PREFLIGHT"
    assert job["status"] == "failed"
    assert job["diagnostics"] == ["SPY regime data update failed; Live Day gate remains closed."]


def test_job_journal_keeps_stalled_scheduler_standalone(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 20:11:00 WARNING run_scheduler - [HEARTBEAT] STALLED 2280s; jobs were missed\n",
        encoding="utf-8",
    )
    result = read_job_journal("2026-08-11", tmp_path)
    assert result["jobs"] == []
    assert result["monitor_events"][0]["kind"] == "scheduler_stalled"


def test_job_journal_pairs_stall_with_later_alive_heartbeat(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 20:11:00 WARNING run_scheduler - [HEARTBEAT] STALLED 2280s; jobs were missed\n"
        "2026-08-11 21:00:00 INFO run_scheduler - [HEARTBEAT] alive\n",
        encoding="utf-8",
    )
    events = read_job_journal("2026-08-11", tmp_path)["monitor_events"]
    assert [event["kind"] for event in events] == ["scheduler_stalled", "scheduler_recovered"]
    assert events[1]["stalled_at"] == events[0]["ts"]


def test_job_journal_dedupes_scheduler_started(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 07:05:32 INFO run_scheduler - Scheduler started. Ctrl-C to stop.\n"
        "2026-08-11 07:05:32 INFO apscheduler.scheduler - Scheduler started\n",
        encoding="utf-8",
    )
    result = read_job_journal("2026-08-11", tmp_path)
    assert [event["kind"] for event in result["monitor_events"]] == ["scheduler_started"]


def test_job_journal_reads_early_et_jobs_from_previous_local_log(tmp_path: Path):
    (tmp_path / "scheduler_0810.log").write_text(
        "2026-08-10 23:10:00 INFO run_scheduler - [NKD_NIGHT_0110] python -m global_index.run_live_day\n"
        "2026-08-10 23:12:00 INFO run_scheduler - [NKD_NIGHT_0110] completed OK\n",
        encoding="utf-8",
    )
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 00:00:00 INFO run_scheduler - [NKD_NIGHT_0200] python -m global_index.run_live_day\n"
        "2026-08-11 00:02:00 INFO run_scheduler - [NKD_NIGHT_0200] completed OK\n",
        encoding="utf-8",
    )
    result = read_job_journal("2026-08-11", tmp_path)
    assert [job["job_id"] for job in result["jobs"]] == ["NKD_NIGHT_0110", "NKD_NIGHT_0200"]


def test_job_journal_exposes_confirmed_missed_stop_repair(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 22:26:12 WARNING apscheduler.executors.default - "
        "Run time of job \"Stop repair sweep 00:20 ET (trigger: cron[day_of_week='mon-fri', hour='0', minute='20'], "
        "next run at: 2026-08-13 00:20:00 EDT)\" was missed by 0:06:12.465790\n",
        encoding="utf-8",
    )
    result = read_job_journal("2026-08-12", tmp_path)
    job = result["jobs"][0]
    assert job["job_id"] == "STOP_REPAIR_0020"
    assert job["status"] == "missed"
    assert job["started_at"].startswith("2026-08-12T04:20:00")
    assert job["reason"] == "scheduler missed slot by 372s"


def test_missed_stop_repair_lifecycle_recovers_at_later_sweep(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 22:26:12 WARNING apscheduler.executors.default - "
        "Run time of job \"Stop repair sweep 00:20 ET (trigger: cron[hour='0', minute='20'])\" "
        "was missed by 0:06:12.000000\n",
        encoding="utf-8",
    )
    (tmp_path / "scheduler_0812.log").write_text(
        "2026-08-12 02:20:00 INFO run_scheduler - [STOP_REPAIR_0420] C:\\Python311\\pythonw.exe -m global_index.run_stop_repair --port 4002\n"
        "2026-08-12 02:20:10 INFO run_scheduler - [STOP_REPAIR_0420] completed OK\n",
        encoding="utf-8",
    )
    jobs = read_job_journal("2026-08-12", tmp_path)["jobs"]
    missed = next(job for job in jobs if job["job_id"] == "STOP_REPAIR_0020")
    assert missed["status"] == "missed"
    assert missed["lifecycle_status"] == "recovered"
    assert missed["recovered_at"].endswith("08:20:10Z")
    assert "inspection resumed" in missed["impact"]


def test_job_journal_exposes_confirmed_missed_nkd_job(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 00:37:22 WARNING apscheduler.executors.default - "
        "Run time of job \"NKD night run 02:30 ET (trigger: cron[day_of_week='mon-fri'], next run at: x)\" "
        "was missed by 0:07:22.769641\n",
        encoding="utf-8",
    )
    result = read_job_journal("2026-08-11", tmp_path)
    job = result["jobs"][0]
    assert job["job_id"] == "NKD_NIGHT_0230"
    assert job["status"] == "missed"


def test_job_journal_non_g2_diagnostic_overrides_known_debt(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 23:45:00 INFO run_scheduler - [NKD_NIGHT_0145] python -m global_index.run_live_day\n"
        "2026-08-11 23:46:34 ERROR run_scheduler - [NKD_NIGHT_0145] thoat OK nhung da ghi 2 dong CRITICAL/ERROR\n"
        "2026-08-11 23:46:34 ERROR run_scheduler - [NKD_NIGHT_0145] G2 HARD: model 20 months old\n"
        "2026-08-11 23:46:34 ERROR run_scheduler - [NKD_NIGHT_0145] dump_state: failed to write live_state_data.js: Access denied\n",
        encoding="utf-8",
    )
    result = read_job_journal("2026-08-12", tmp_path)
    job = result["jobs"][0]
    assert job["status"] == "failed"
    assert job["reason"] == "child_error"
    assert len(job["diagnostics"]) == 2
    assert "snapshot for this slot was not published" in job["impact"]
    assert "No later successful publication" in job["impact"]
    assert "No trading action" in job["action"]


def test_job_journal_marks_state_publish_failure_recovered_by_later_slot(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 23:45:00 INFO run_scheduler - [NKD_NIGHT_0145] python -m global_index.run_live_day\n"
        "2026-08-11 23:46:34 ERROR run_scheduler - [NKD_NIGHT_0145] dump_state: failed to write live_state_data.js: Access denied\n"
        "2026-08-11 23:50:00 INFO run_scheduler - [NKD_NIGHT_0150] python -m global_index.run_live_day\n"
        "2026-08-11 23:51:00 INFO run_scheduler - [NKD_NIGHT_0150] completed OK\n",
        encoding="utf-8",
    )
    result = read_job_journal("2026-08-12", tmp_path)
    failed = result["jobs"][0]
    assert failed["status"] == "failed"
    assert "Publication resumed at NKD_NIGHT_0150" in failed["impact"]


def test_job_journal_explains_missed_stop_repair_impact(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 22:26:12 WARNING apscheduler.executors.default - "
        "Run time of job \"Stop repair sweep 00:20 ET (trigger: cron, next run at: x)\" "
        "was missed by 0:06:12.465790\n",
        encoding="utf-8",
    )
    job = read_job_journal("2026-08-12", tmp_path)["jobs"][0]
    assert "protection was not rechecked" in job["impact"]
    assert "working stops" in job["action"]


def test_open_issues_include_known_debt_and_unrecovered_job(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 22:26:12 WARNING apscheduler.executors.default - "
        "Run time of job \"Stop repair sweep 00:20 ET (trigger: cron, next run at: x)\" was missed by 0:06:12.000000\n"
        "2026-08-11 23:10:00 INFO run_scheduler - [NKD_NIGHT_0110] python -m global_index.run_live_day\n"
        "2026-08-11 23:12:00 ERROR run_scheduler - [NKD_NIGHT_0110] thoat OK nhung da ghi 2 dong CRITICAL/ERROR\n"
        "2026-08-11 23:12:00 ERROR run_scheduler - [NKD_NIGHT_0110] G2 HARD: model 20 months old\n"
        "2026-08-11 23:12:01 ERROR run_scheduler - [NKD_NIGHT_0110] dump_state: failed to write live_state_data.js\n",
        encoding="utf-8",
    )
    result = read_open_issues(tmp_path)
    keys = {issue["key"] for issue in result["issues"]}
    assert "known_debt:model_age" in keys
    assert "known_debt:child_error_exit_zero" not in keys
    assert "job:nkd_night:failed" in keys
    assert "job:stop_repair:missed" in keys


def _roll_table_ending_in(days: int) -> dict:
    """A roll schedule whose LAST roll date is `days` from today, in ET.

    Built from today rather than written down, so this test cannot expire the way the
    two-clock test did — that one pinned 2026-09-04 and went red on the Nikkei roll
    date, the one day its subject mattered.
    """
    import pandas as pd
    today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    last = today + pd.Timedelta(days=days)
    earlier = last - pd.Timedelta(days=91)
    return {"MES": [(str(earlier.date()), "202609", "202612"),
                    (str(last.date()), "202612", "202703")]}


def test_open_issues_warn_before_the_roll_table_runs_out(tmp_path: Path, monkeypatch):
    """The contract calendar is maintained by hand and nothing watches how much is left.

    When the table runs out, `_current_front_month` does not fail — it keeps returning
    the final month forever, so the system trades a contract that will one day be
    expired and every order starts failing at once, months later, with no warning
    anywhere. Measured: asking for 2028-06-01 today still answers 202703.

    Warns on days remaining rather than on the table being empty, because "empty" only
    becomes true after the last roll has already happened, which is too late to be a
    warning.
    """
    from global_index import ibkr_broker
    from monitor.backend import open_issue_reader

    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 23:10:00 INFO run_scheduler - [NKD_NIGHT_0110] python -m global_index.run_live_day\n",
        encoding="utf-8",
    )

    def keys_for(days: int) -> set[str]:
        monkeypatch.setattr(ibkr_broker, "ROLL_SCHEDULE", _roll_table_ending_in(days))
        open_issue_reader._cache.clear()
        return {issue["key"] for issue in read_open_issues(tmp_path)["issues"]}

    KEY = "roll_schedule:runway"
    # Self-check: the reader must produce SOMETHING here, or both branches below pass
    # for the reason that nothing is being evaluated at all.
    assert read_open_issues(tmp_path)["issues"] is not None

    assert KEY not in keys_for(365), (
        "a table with a year of roll dates left must stay quiet, or the warning is "
        "noise the operator learns to ignore")
    assert KEY in keys_for(10), (
        "ten days from the last scheduled roll and nothing says so; the table is "
        "extended by hand and only a warning can prompt it")

    monkeypatch.setattr(ibkr_broker, "ROLL_SCHEDULE", _roll_table_ending_in(10))
    open_issue_reader._cache.clear()
    issue = next(i for i in read_open_issues(tmp_path)["issues"] if i["key"] == KEY)
    assert "MES" in issue["evidence"], f"the warning must name the instrument: {issue}"
    assert "202703" in issue["evidence"], (
        f"and the month it would be stuck on, which is what an operator has to check "
        f"is still listed: {issue}")


def test_open_issues_say_so_when_the_runway_cannot_be_read(tmp_path: Path, monkeypatch):
    """A check that cannot run must not read as a check that passed.

    The reader imports ROLL_SCHEDULE inside a try. Returning [] on failure means a
    broken import — a bad environment, a renamed table — takes the warning away and
    leaves the panel looking clean, which is the one reading that is certainly wrong.
    Same rule the re-freeze flag already follows: unreadable reports pending.

    Found by a measurement tool of mine that patched the datetime module globally,
    broke pyarrow, and so broke the import this function depends on — the warning went
    silent and the tool reported "no issue" as though that were an answer.
    """
    import builtins
    from monitor.backend import open_issue_reader

    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 23:10:00 INFO run_scheduler - [NKD_NIGHT_0110] python -m global_index.run_live_day\n",
        encoding="utf-8",
    )
    real_import = builtins.__import__

    def blow_up(name, *args, **kwargs):
        if name == "global_index.ibkr_broker":
            raise ImportError("simulated broken environment")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blow_up)
    open_issue_reader._cache.clear()
    issues = open_issue_reader._roll_schedule_runway_issues("2026-08-17T00:00:00Z")

    assert issues, (
        "the roll table could not be read and the panel says nothing at all, which is "
        "indistinguishable from a healthy table")
    issue = issues[0]
    assert issue["status"] == "unknown", (
        f"an unreadable check is not a passing one, and not an incident either: {issue}")
    assert "roll_schedule" in issue["key"], f"unexpected key: {issue}"


def test_open_issues_runway_warning_is_not_frozen_by_the_log_cache(tmp_path: Path, monkeypatch):
    """The runway depends on the DATE; the reader caches on log file signatures.

    Without the date in the cache key the warning is computed once and then frozen: on
    a quiet weekend no log changes, so the day the table crossed the threshold would
    pass without the panel ever recomputing it.
    """
    from global_index import ibkr_broker
    from monitor.backend import open_issue_reader

    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 23:10:00 INFO run_scheduler - [NKD_NIGHT_0110] python -m global_index.run_live_day\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ibkr_broker, "ROLL_SCHEDULE", _roll_table_ending_in(365))
    open_issue_reader._cache.clear()
    quiet = {i["key"] for i in read_open_issues(tmp_path)["issues"]}
    assert "roll_schedule:runway" not in quiet, "precondition: a long table must be quiet"

    # Same files, untouched. Only the schedule moved — which is what a passing day does.
    monkeypatch.setattr(ibkr_broker, "ROLL_SCHEDULE", _roll_table_ending_in(10))
    loud = {i["key"] for i in read_open_issues(tmp_path)["issues"]}
    assert "roll_schedule:runway" in loud, (
        "the cache served a stale answer across a change that no log file records, so "
        "the warning would never fire on a quiet day")


def test_open_issues_do_not_double_count_g2_wrapper_as_exit_zero_debt(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 23:10:00 INFO run_scheduler - [NKD_NIGHT_0110] python -m global_index.run_live_day\n"
        "2026-08-11 23:12:00 ERROR run_scheduler - [NKD_NIGHT_0110] thoat OK nhung da ghi 1 dong CRITICAL/ERROR\n"
        "2026-08-11 23:12:00 ERROR run_scheduler - [NKD_NIGHT_0110] G2 HARD: model 20 months old\n",
        encoding="utf-8",
    )
    issues = read_open_issues(tmp_path)["issues"]
    assert [issue["key"] for issue in issues] == ["known_debt:model_age"]
    assert issues[0]["occurrences"] == 1


def test_open_issues_exclude_legacy_maxhold_noise(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 08:28:25 INFO run_scheduler - [MAXHOLD] python test helper\n"
        "2026-08-11 08:28:26 ERROR run_scheduler - [MAXHOLD] khong tim thay job maxhold_exit\n",
        encoding="utf-8",
    )
    assert read_open_issues(tmp_path)["issues"] == []


def test_open_issues_drop_failure_after_clean_same_stream_recovery(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 23:45:00 INFO run_scheduler - [NKD_NIGHT_0145] python -m global_index.run_live_day\n"
        "2026-08-11 23:46:00 ERROR run_scheduler - [NKD_NIGHT_0145] dump_state: failed to write live_state_data.js: Access denied\n"
        "2026-08-11 23:50:00 INFO run_scheduler - [NKD_NIGHT_0150] python -m global_index.run_live_day\n"
        "2026-08-11 23:51:00 INFO run_scheduler - [NKD_NIGHT_0150] completed OK\n",
        encoding="utf-8",
    )
    assert read_open_issues(tmp_path)["issues"] == []


def test_open_issues_clear_stall_after_later_alive_heartbeat(tmp_path: Path):
    (tmp_path / "scheduler_0812.log").write_text(
        "2026-08-12 03:11:00 WARNING run_scheduler - [HEARTBEAT] STALLED 1380s\n"
        "2026-08-12 04:00:00 INFO run_scheduler - [HEARTBEAT] alive\n",
        encoding="utf-8",
    )
    assert read_open_issues(tmp_path)["issues"] == []


def test_open_issues_keep_stall_without_recovery_evidence(tmp_path: Path):
    (tmp_path / "scheduler_0812.log").write_text(
        "2026-08-12 03:11:00 WARNING run_scheduler - [HEARTBEAT] STALLED 1380s\n",
        encoding="utf-8",
    )
    issues = read_open_issues(tmp_path)["issues"]
    assert [issue["key"] for issue in issues] == ["incident:scheduler_stalled"]


def test_open_issues_group_repeated_unresolved_slots(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 20:25:00 WARNING apscheduler.executors.default - "
        "Run time of job \"Stop repair sweep 22:20 ET (trigger: cron, next run at: x)\" was missed by 0:05:00.000000\n"
        "2026-08-11 22:26:00 WARNING apscheduler.executors.default - "
        "Run time of job \"Stop repair sweep 00:20 ET (trigger: cron, next run at: x)\" was missed by 0:06:00.000000\n",
        encoding="utf-8",
    )
    issues = read_open_issues(tmp_path)["issues"]
    assert len(issues) == 1
    assert issues[0]["key"] == "job:stop_repair:missed"
    assert issues[0]["occurrences"] == 2


def test_open_issue_contract_identifies_component_and_specific_problem(tmp_path: Path):
    (tmp_path / "scheduler_0811.log").write_text(
        "2026-08-11 22:26:00 WARNING apscheduler.executors.default - "
        "Run time of job \"Stop repair sweep 00:20 ET (trigger: cron, next run at: x)\" was missed by 0:06:00.000000\n"
        "2026-08-11 23:10:00 INFO run_scheduler - [NKD_NIGHT_0110] python -m global_index.run_live_day\n"
        "2026-08-11 23:12:00 ERROR run_scheduler - [NKD_NIGHT_0110] G2 HARD: model 20 months old (fit_end=2024-12-31)\n",
        encoding="utf-8",
    )
    issues = {issue["key"]: issue for issue in read_open_issues(tmp_path)["issues"]}
    assert issues["job:stop_repair:missed"]["component"] == "scheduler"
    assert "did not run" in issues["job:stop_repair:missed"]["problem"]
    assert issues["known_debt:model_age"]["component"] == "runner"
    assert "2024-12-31" in issues["known_debt:model_age"]["problem"]


def test_open_issues_include_paper_reconciliation_breaches(tmp_path: Path):
    (tmp_path / "scheduler_0814.log").write_text(
        "2026-08-14 09:00:00 INFO run_scheduler - [HEARTBEAT] alive\n",
        encoding="utf-8",
    )
    monitor_dir = tmp_path / "monitor"
    monitor_dir.mkdir()
    (monitor_dir / "paper_pnl_compare.json").write_text(
        '{"statement_pnl_compare":{"paper_minus_backtest_realized":10,'
        '"paper_minus_flex_epoch_rebased_realized":0},'
        '"lifecycle_compare":{"unresolved":1,"paper_minus_backtest_sum":8,'
        '"paper_minus_flex_sum":2},'
        '"open_position_parity":{"paper_only":[{"inst":"MES"}],"backtest_only":[]},'
        '"signal_compare":{"classified":{"unresolved":1}},'
        '"entry_compare":{"unresolved":0}}',
        encoding="utf-8",
    )
    keys = {issue["key"] for issue in read_open_issues(tmp_path)["issues"]}
    assert "paper:lifecycle:unresolved" in keys
    assert "paper:pnl:paper_backtest_total_mismatch" in keys
    assert "paper:pnl:paper_flex_total_mismatch" in keys
    assert "paper:open_position_parity:mismatch" in keys
    assert "paper:decision_path:unresolved" in keys


def test_frontend_modules_keep_data_boundaries():
    realtime = (DASH / "realtime" / "index.html").read_text(encoding="utf-8")
    realtime_js = (DASH / "realtime" / "realtime.js").read_text(encoding="utf-8")
    realtime_css = (DASH / "realtime" / "realtime.css").read_text(encoding="utf-8")
    paper = (DASH / "paper" / "index.html").read_text(encoding="utf-8")
    reports = (DASH / "reports" / "index.html").read_text(encoding="utf-8")
    analytics = (DASH / "analytics" / "index.html").read_text(encoding="utf-8")

    for source in (realtime, paper, reports):
        assert "replay_snapshots_data.js" not in source
        assert "https://" not in source and "http://" not in source
    assert "replay_snapshots_data.js" in analytics
    assert "/api/v1/reports" not in realtime_js
    assert "decision.entries" in realtime_js
    assert "decision.exits" in realtime_js
    assert "decision.rejected_detail" in realtime_js
    assert "renderDecisions(snap)" in realtime_js
    # P2-A1 đổi `snap` thành `snapshot` trong renderMetrics: khi nguồn runner-state
    # chết thì `snapshot` là null nên số không còn render như đang sống. Ý định của
    # assert này — equity đến từ snapshot chứ không phải nguồn khác — giữ nguyên.
    assert "const equity = snapshot?.equity" in realtime_js
    assert "metricDrawdownFill" in realtime
    assert "metricDrawdownAmount" in realtime
    assert "schedule?.evidence_available" in realtime_js
    assert "Paper Equity" in realtime
    assert "Broker Equity" not in realtime
    assert "performanceBase" in realtime
    assert "performanceNet" in realtime
    assert "performanceCalmar" in realtime
    assert "performanceSharpe" in realtime
    assert "performanceReturn" in realtime
    assert "performanceMaxDd" in realtime
    assert "metricStopsCovered" in realtime
    assert "SPY data" in realtime
    assert "next_scheduled_job" in realtime_js
    assert "next_decision_job" in realtime_js
    assert "latestObservedJob" in realtime_js
    assert "latestDecisionJob" in realtime_js
    assert "nowScheduleFacts" in realtime
    assert 'id="nowMonitorLayout"' in realtime
    assert "renderScheduleFacts()" in realtime_js
    assert "No current incident or telemetry gap observed" not in realtime_js
    assert "monitorClearIndicator" in realtime
    assert "monitorClearIndicator" in realtime_js
    assert "Working orders" in realtime
    assert "system-conclusion" in realtime_js
    assert "fontSelector" in realtime
    assert "raits-dashboard-font" in realtime_js
    assert "--font-ui" in realtime_css
    assert "h1 { font-size: 25px; }" in realtime_css
    assert "h2 { font-size: 21px; }" in realtime_css
    assert "section-body" in realtime
    assert "exitType(exit.exit_reason, 'SIGNAL')" in realtime_js
    assert "/api/v1/session-events/" in realtime_js
    assert "/api/v1/job-journal/" in realtime_js
    assert "/api/v1/open-issues" in realtime_js
    assert "compactIssueMedia" in realtime_js
    assert "selectedIssueKey" in realtime_js
    assert "openIssueDetail" in realtime_js
    assert "issue-mobile-detail" in realtime_js
    assert "selectedMonitorKey" in realtime_js
    assert "nowMonitorDetail" in realtime_js
    assert "/api/v1/runner-positions" in realtime_js
    assert "persistedRunnerFor" in realtime_js
    assert "eventStatus" in realtime_js
    assert "stop_armed_after_deferral" in realtime_js
    assert "Protected / ID drift" in realtime_js
    assert "hasRecordedStopId" in realtime_js
    assert "event-trigger" in realtime_js
    assert "event_history?.events" in realtime_js
    assert "loggedRunnerEvents.length" in realtime_js
    assert "gap:runner-event-log" in realtime_js
    assert "coverage_started_at" in realtime_js
    assert "Runner-state publication failed" in realtime_js
    assert "jobPresentation" in realtime_js
    assert "job-resolution" in realtime_js
    assert "data-jump-event" not in realtime_js
    assert "recoveredAt" in realtime_js
    monitor_block = realtime_js.split("function renderMonitor", 1)[1].split("function monitorDetail", 1)[0]
    assert "state.jobJournal?.jobs" not in monitor_block
    assert "data-job-id" in realtime_js
    assert "data-journal-view" in realtime
    assert "renderEventJournal" in realtime_js
    assert "loggedExitSymbols" in realtime_js
    assert "easternDate(event.ts) === day" in realtime_js


# ── entry time recovered from the runner's own trade log ─────────────────────────
# runner.dump_state hardcodes entry_time=None (global_index/runner.py:2540), so the
# realtime panel captioned every position "entry time not emitted". IBKR cannot close
# the gap: reqPositions carries no timestamp and reqExecutions serves the current day
# only. trade_log.jsonl already holds a ts per fill, forever.

def _trade_log(tmp_path: Path, *records: dict) -> Path:
    import json as _json
    path = tmp_path / "trade_log.jsonl"
    path.write_text("".join(_json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _open_record(**overrides) -> dict:
    record = {"type": "OPEN", "inst": "M2K", "cluster": "roska4_swing",
              "direction": "LONG", "entry_day": "2026-08-10", "fill_price": 3025.3,
              "ts": "2026-08-10T19:10:59.312296+00:00"}
    record.update(overrides)
    return record


def _payload(**overrides) -> dict:
    position = {"inst": "M2K", "cluster": "roska4_swing", "entry_day": "2026-08-10",
                "entry_price": 3025.3, "entry_time": None}
    position.update(overrides)
    return {"snapshots": [{"date": "2026-08-12", "open_positions": [position]}]}


def test_entry_time_recovered_from_trade_log(tmp_path: Path):
    from monitor.backend.entry_time_reader import annotate_open_positions, read_entry_times
    _trade_log(tmp_path, _open_record())
    payload = _payload()
    assert annotate_open_positions(payload, read_entry_times(tmp_path)["entries"]) == 1
    position = payload["snapshots"][0]["open_positions"][0]
    assert position["entry_time"] == "2026-08-10T19:10:59.312296+00:00"
    assert position["entry_time_precision"] == "exact"
    assert position["entry_time_source"] == "trade_log.jsonl"


def test_entry_time_refuses_midnight_placeholder(tmp_path: Path):
    """2026-08-03: send_order misread filled OPENs as cancelled and the records were
    rebuilt from the date alone. Midnight there is a placeholder — showing it as the
    moment of entry would be inventing evidence."""
    from monitor.backend.entry_time_reader import annotate_open_positions, read_entry_times
    _trade_log(tmp_path, _open_record(ts="2026-08-10T00:00:00+00:00"))
    payload = _payload()
    assert annotate_open_positions(payload, read_entry_times(tmp_path)["entries"]) == 0
    position = payload["snapshots"][0]["open_positions"][0]
    assert position["entry_time"] is None
    assert position["entry_time_precision"] == "day_only"


def test_entry_time_refuses_when_fill_price_disagrees(tmp_path: Path):
    """(inst, cluster, entry_day) also matches a different trade opened the same
    session on the same sleeve. A confidently wrong time is worse than none."""
    from monitor.backend.entry_time_reader import annotate_open_positions, read_entry_times
    _trade_log(tmp_path, _open_record(fill_price=2988.0))
    payload = _payload()
    assert annotate_open_positions(payload, read_entry_times(tmp_path)["entries"]) == 0
    position = payload["snapshots"][0]["open_positions"][0]
    assert position["entry_time"] is None
    assert position["entry_time_precision"] == "price_mismatch"


def test_entry_time_marks_missing_record(tmp_path: Path):
    from monitor.backend.entry_time_reader import annotate_open_positions, read_entry_times
    _trade_log(tmp_path, _open_record(entry_day="2026-08-05"))
    payload = _payload()
    assert annotate_open_positions(payload, read_entry_times(tmp_path)["entries"]) == 0
    assert payload["snapshots"][0]["open_positions"][0]["entry_time_precision"] == "no_record"


def test_entry_time_accepts_live_positions_day_spelling(tmp_path: Path):
    """live_positions.json writes "2026-08-10 00:00:00" where the trade log writes
    "2026-08-10". Both must land on the same key."""
    from monitor.backend.entry_time_reader import annotate_open_positions, read_entry_times
    _trade_log(tmp_path, _open_record())
    payload = _payload(entry_day="2026-08-10 00:00:00")
    assert annotate_open_positions(payload, read_entry_times(tmp_path)["entries"]) == 1


def test_entry_time_survives_torn_last_line(tmp_path: Path):
    """The trade log is appended to live, so the final line can be mid-write."""
    from monitor.backend.entry_time_reader import read_entry_times
    import json as _json
    (tmp_path / "trade_log.jsonl").write_text(
        _json.dumps(_open_record()) + "\n" + '{"type": "OPEN", "inst": "MES"', encoding="utf-8")
    assert len(read_entry_times(tmp_path)["entries"]) == 1


def test_entry_time_missing_file_reports_error(tmp_path: Path):
    from monitor.backend.entry_time_reader import read_entry_times
    result = read_entry_times(tmp_path)
    assert result["entries"] == {} and result["error"]


def test_realtime_contract_suite_exists():
    """Lưới an toàn cho C1/C2 phải luôn nằm trong repo, không bị đổi tên đi mất."""
    assert (ROOT / "monitor" / "test_realtime_contract.py").exists()


# ── H1: một sự thật duy nhất về "đã phục hồi chưa" ───────────────────────────
# schedule_status._annotate_incident_lifecycle đánh dấu recovered đúng, và
# open_issue_reader có logic later_recovery riêng cũng đúng. job_journal_reader
# thì chỉ set lifecycle_status cho nhánh missed + stop_repair, nên job failed của
# nkd_night/live_day rơi về None và frontend đọc None là "chưa recover" — Job
# Journal hiện OPEN vĩnh viễn cho slot mà hai reader kia đã biết là đã phục hồi.

# job_journal_reader._LAUNCH chỉ nhận ra một lần chạy khi dòng log chứa
# "-m global_index." — đúng như scheduler thật ghi. Một dòng "bat dau" chung chung
# không sinh ra job nào và test sẽ pass rỗng thay vì kiểm được gì.
_NKD_LAUNCH = "python -m global_index.run_live_day --clusters nkd"
_NKD_FAIL_THEN_RECOVER = (
    f"2026-08-14 01:00:00  INFO     run_scheduler — [NKD_NIGHT_0200] {_NKD_LAUNCH}\n"
    "2026-08-14 01:00:12  ERROR    run_scheduler — [NKD_NIGHT_0200] exited with code 1\n"
    f"2026-08-14 01:30:00  INFO     run_scheduler — [NKD_NIGHT_0230] {_NKD_LAUNCH}\n"
    "2026-08-14 01:30:20  INFO     run_scheduler — [NKD_NIGHT_0230] completed OK\n"
)
_NKD_FAIL_ONLY = (
    f"2026-08-14 01:00:00  INFO     run_scheduler — [NKD_NIGHT_0200] {_NKD_LAUNCH}\n"
    "2026-08-14 01:00:12  ERROR    run_scheduler — [NKD_NIGHT_0200] exited with code 1\n"
)


def test_failed_decision_job_is_marked_recovered_by_a_later_clean_slot(tmp_path: Path):
    (tmp_path / "scheduler_0814.log").write_text(_NKD_FAIL_THEN_RECOVER, encoding="utf-8")
    failed = [job for job in read_job_journal("2026-08-14", tmp_path)["jobs"]
              if job["status"] == "failed"]
    assert failed, "fixture must produce a failed job"
    assert failed[0]["lifecycle_status"] == "recovered"
    assert failed[0]["recovered_at"] is not None


def test_failed_job_stays_open_when_nothing_ran_after(tmp_path: Path):
    (tmp_path / "scheduler_0814.log").write_text(_NKD_FAIL_ONLY, encoding="utf-8")
    failed = [job for job in read_job_journal("2026-08-14", tmp_path)["jobs"]
              if job["status"] == "failed"]
    assert failed, "fixture must produce a failed job"
    assert failed[0]["lifecycle_status"] == "open"
    assert failed[0]["recovered_at"] is None


def test_every_unfinished_job_declares_a_lifecycle(tmp_path: Path):
    """None là chỗ frontend rơi về mặc định 'chưa recover'. Không job failed hay
    missed nào được phép để trống nó."""
    (tmp_path / "scheduler_0814.log").write_text(_NKD_FAIL_THEN_RECOVER, encoding="utf-8")
    jobs = read_job_journal("2026-08-14", tmp_path)["jobs"]
    unfinished = [job for job in jobs if job["status"] in {"failed", "missed"}]
    # Không để test pass rỗng: một fixture không sinh ra job nào sẽ làm vòng lặp
    # dưới không chạy lần nào và test vẫn xanh mà chẳng kiểm được gì.
    assert unfinished, "fixture must produce at least one unfinished job"
    for job in unfinished:
        assert job.get("lifecycle_status") in {"open", "recovered"}, job["job_id"]


# ── M7: coverage phải nói đúng chỗ bằng chứng dừng lại ───────────────────────
# coverage.to = max(dòng log cuối, hôm nay), nên UI luôn quảng cáo "evidence …
# to <hôm nay>" kể cả khi scheduler chết từ nhiều ngày trước — trong khi chính
# tooltip của section dạy người đọc tin vào phạm vi evidence đó.

def test_coverage_reports_where_evidence_actually_ends(tmp_path: Path):
    (tmp_path / "scheduler_0801.log").write_text(
        "2026-08-01 10:00:00  INFO     run_scheduler — [HEARTBEAT] ALIVE\n",
        encoding="utf-8")
    coverage = read_open_issues(tmp_path)["coverage"]
    assert coverage["evidence_ends"] == "2026-08-01"
    assert coverage["stale_days"] >= 1
    # Quét vẫn phải chạy tới hôm nay để bắt slot missed, nên `to` không lùi lại.
    assert coverage["to"] >= coverage["evidence_ends"]


def test_coverage_reports_zero_stale_days_when_evidence_is_current(tmp_path: Path):
    today = dt.datetime.now(ET).date()
    (tmp_path / f"scheduler_{today:%m%d}.log").write_text(
        f"{today.isoformat()} 10:00:00  INFO     run_scheduler — [HEARTBEAT] ALIVE\n",
        encoding="utf-8")
    coverage = read_open_issues(tmp_path)["coverage"]
    assert coverage["evidence_ends"] == today.isoformat()
    assert coverage["stale_days"] == 0


# ── L7: hai reader phải hiểu "job chạy xong" giống nhau ──────────────────────
# schedule_status._evidence nhận cả "completed ok" lẫn "thoat ok". job_journal_reader
# chỉ nhận "completed OK" và "thoat OK nhung", nên một dòng "thoat OK" TRẦN để job
# kẹt `running` vĩnh viễn ở lane journal trong khi rail gọi slot ấy là `executed`.
# Bẫy khi sửa: nhánh "completed OK" đứng TRƯỚC nhánh "thoat OK nhung", nên nếu chỉ
# nới nhánh đầu ra thì "thoat OK nhung ..." sẽ khớp nó trước và mất luôn phân loại
# completed_with_debt. Hai test dưới khoá cả hai chiều.

def _one_slot_log(closing_line: str) -> str:
    launch = "python -m global_index.run_live_day --clusters nkd"
    return (f"2026-08-14 01:00:00  INFO     run_scheduler — [NKD_NIGHT_0200] {launch}\n"
            f"2026-08-14 01:00:20  INFO     run_scheduler — [NKD_NIGHT_0200] {closing_line}\n")


@pytest.mark.parametrize("closing_line", ["completed OK", "thoat OK"])
def test_a_clean_exit_line_completes_the_job_in_either_wording(tmp_path: Path, closing_line):
    (tmp_path / "scheduler_0814.log").write_text(_one_slot_log(closing_line), encoding="utf-8")
    jobs = read_job_journal("2026-08-14", tmp_path)["jobs"]
    assert [job["status"] for job in jobs] == ["completed"], (closing_line, jobs)


def test_the_debt_wording_still_wins_over_the_plain_one(tmp_path: Path):
    """"thoat OK nhung ..." chứa "thoat OK" làm tiền tố. Nếu nhánh hoàn tất sạch
    được kiểm trước, dòng có debt sẽ bị nuốt và 16/28 job của một đêm thật mất
    phân loại completed_with_debt."""
    (tmp_path / "scheduler_0814.log").write_text(
        _one_slot_log("thoat OK nhung da ghi 1 dong CRITICAL/ERROR — KHONG bo qua:"),
        encoding="utf-8")
    jobs = read_job_journal("2026-08-14", tmp_path)["jobs"]
    assert [job["status"] for job in jobs] == ["completed_with_debt"], jobs


@pytest.mark.parametrize("closing_line", ["completed OK", "thoat OK"])
def test_both_readers_agree_a_clean_exit_is_not_an_incident(tmp_path: Path, closing_line):
    (tmp_path / "scheduler_0814.log").write_text(_one_slot_log(closing_line), encoding="utf-8")
    now = dt.datetime(2026, 8, 14, 8, 0, tzinfo=dt.timezone.utc)
    status = schedule_status.get_schedule_status(tmp_path, observed_at=now, now=now)
    jobs = read_job_journal("2026-08-14", tmp_path)["jobs"]
    assert status["incidents"] == [], (closing_line, status["incidents"])
    assert all(job["status"] != "running" for job in jobs), (closing_line, jobs)


def test_sunday_reopen_sweep_is_modelled_like_the_scheduler_runs_it():
    """CME mở lại 18:00 ET Chủ nhật nhưng sweep mon-fri sớm nhất là 00:20 ET thứ
    Hai — 6 tiếng rưỡi thị trường chạy mà không lượt kiểm bảo vệ nào. Scheduler
    có slot Chủ nhật 18:30; dashboard phải mô hình hóa GIỐNG HỆT, nếu không nó
    coi slot đó là lạ và dựng incident giả mỗi tuần."""
    from raits.live.trading_calendar import is_trading_day

    sunday, saturday = dt.date(2026, 8, 16), dt.date(2026, 8, 15)
    assert sunday.weekday() == 6 and not is_trading_day(sunday)
    # Stage 5ZZZ-AC thêm SPY_WEEKEND_PRE_NKD_CHECK lúc 18:00, ngay TRƯỚC sweep 18:30:
    # kiểm dữ liệu trước, quét bảo vệ sau, cùng một log Chủ nhật. Thứ tự là một phần
    # của khẳng định, không chỉ tập hợp.
    assert [slot["id"] for slot in schedule_status._scheduled_slots_for(sunday)] \
        == ["SPY_WEEKEND_PRE_NKD_CHECK", "STOP_REPAIR_SUN_1830"]
    # Thứ Bảy thị trường vẫn đóng: quét lúc đó là quét vào chỗ trống.
    assert schedule_status._scheduled_slots_for(saturday) == []


def test_the_next_job_after_friday_close_is_the_sunday_spy_check():
    """Trước khi có slot Chủ nhật, câu trả lời là 00:20 ET thứ Hai.

    Stage 5ZZZ-AC: giờ câu trả lời sớm hơn nữa — SPY_WEEKEND_PRE_NKD_CHECK 18:00 ET,
    nửa tiếng trước sweep. Đó chính là điểm của nó: sau khi thị trường đóng thứ Sáu,
    thứ ĐẦU TIÊN nhìn lại dữ liệu là job này, không phải 00:45 thứ Hai."""
    now = dt.datetime(2026, 8, 15, 3, 0, tzinfo=ET)
    nxt = schedule_status._next_job(now, schedule_status._scheduled_slots_for)
    assert nxt["job_id"] == "SPY_WEEKEND_PRE_NKD_CHECK"
    assert nxt["at"] == "2026-08-16T22:00:00Z"


def test_favicon_does_not_404():
    """L5: trình duyệt luôn xin favicon. Một 404 thường trực trong console làm lu
    mờ lỗi thật, và console sạch là điều kiện để smoke test tin được."""
    client = app.test_client()
    assert client.get("/favicon.ico").status_code in (200, 204)


def test_a_slot_cut_off_by_a_restart_is_explained_not_silent(monkeypatch, tmp_path: Path):
    """Đêm 2026-08-18, và nó không thể tự hết.

    Scheduler khởi động lại lúc 01:10:52 ET, đúng 52 giây sau khi slot 01:10 sinh tiến
    trình con. Cha chết nên không còn ai sống để ghi dòng kết thúc — dòng đó sẽ KHÔNG
    BAO GIỜ tới, và slot ấy giữ băng-rôn đỏ tới nửa đêm.

    Cách chữa không phải để slot sau che slot trước; bản vá đầu tiên đi hướng đó và bị
    test_older_unexplained_slot_cannot_be_hidden_by_newer_slot chặn lại, đúng như nó
    phải thế. Đây là bằng chứng dương: slot CÓ dòng khởi chạy, và sau dòng đó log có
    một lần scheduler khởi động.
    """
    now = dt.datetime(2026, 8, 18, 1, 21, tzinfo=ET)
    lines = _lines_through(now, replace={"NKD_NIGHT_0110": ""})
    lines.insert(0, "2026-08-18 01:10:00 INFO run_scheduler [NKD_NIGHT_0110] python -m global_index.run_live_day")
    lines.insert(1, "2026-08-18 01:10:52 INFO apscheduler.scheduler Scheduler started")
    _patch_logs(monkeypatch, lines)
    status = schedule_status.get_schedule_status(
        tmp_path, observed_at=now - dt.timedelta(minutes=1), now=now)

    assert [item["slot_id"] for item in status["unexplained_overdue"]] == [], (
        f"slot bi cat ngang van giu bang-ron do: {status['unexplained_overdue']}")
    assert status["freshness"] != "late"


def test_a_slot_that_started_and_vanished_with_no_restart_stays_unexplained(monkeypatch, tmp_path: Path):
    """Nửa còn lại. Không có lần khởi động lại nào thì việc thiếu dòng kết thúc vẫn là
    chưa giải thích được — tiến trình con có thể đã chết âm thầm, và đó là thứ phải báo."""
    now = dt.datetime(2026, 8, 18, 1, 21, tzinfo=ET)
    lines = _lines_through(now, replace={"NKD_NIGHT_0110": ""})
    lines.insert(0, "2026-08-18 01:10:00 INFO run_scheduler [NKD_NIGHT_0110] python -m global_index.run_live_day")
    _patch_logs(monkeypatch, lines)
    status = schedule_status.get_schedule_status(
        tmp_path, observed_at=now - dt.timedelta(minutes=1), now=now)

    assert "NKD_NIGHT_0110" in {item["slot_id"] for item in status["unexplained_overdue"]}, (
        "mot slot bien mat khong ly do da duoc tha")
    assert status["freshness"] == "late"


def test_a_slot_that_left_no_trace_at_all_stays_unexplained(monkeypatch, tmp_path: Path):
    """Im lặng hoàn toàn là kiểu hỏng hệ này liên tục bị cắn — slot 09:31 từng không bắn
    mà không ghi một dòng nào. Một lần khởi động lại ở đâu đó trong log không được phép
    biến nó thành đã giải thích."""
    now = dt.datetime(2026, 8, 18, 1, 21, tzinfo=ET)
    lines = _lines_through(now, replace={"NKD_NIGHT_0110": ""})
    lines.insert(0, "2026-08-18 01:09:00 INFO apscheduler.scheduler Scheduler started")
    _patch_logs(monkeypatch, lines)
    status = schedule_status.get_schedule_status(
        tmp_path, observed_at=now - dt.timedelta(minutes=1), now=now)

    assert "NKD_NIGHT_0110" in {item["slot_id"] for item in status["unexplained_overdue"]}, (
        "mot slot khong he chay da bi coi la bi cat ngang")


# --- Stage 5ZZZ-AF: the realtime page's fetch budget and its first paint -----------------
#
# Measured 2026-08-30, one machine, one warm backend process, same evidence tree:
#
#   runner-state 57-66ms · broker 3ms · schedule-status 41-93ms · open-issues 24-33ms
#   runner-positions 3ms · track1-market-view 13-90ms
#   track1-runtime  0.67-1.68s back to back, and 7.09s / 9.04s / 9.37s / 11.06s on the
#                   first call after an idle gap, because it walks the whole
#                   window_coverage + explanations tree with a cold OS file cache
#
# Two defects came out of that spread, and each test below pins one of them.

MEASURED_TRACK1_RUNTIME_COLD_MS = 11_100


def _realtime_js() -> str:
    return (DASH / "realtime" / "realtime.js").read_text(encoding="utf-8")


def test_the_track1_runtime_fetch_outlasts_its_measured_cold_read():
    """A budget below the measured cold read fails on the one load a person is looking at.

    The page gave all seven endpoints a single 6000ms timeout, and the slowest of them was
    measured at 7.09s, 9.04s, 9.37s and 11.06s after an idle gap. So the panel announced
    "Track 1 runtime endpoint did not answer" about a backend that answered correctly, and
    it announced it on the FIRST poll, which is the only one a person sees on arrival.

    Pinned as a relation to the measurement, not as a literal: the paper dashboard already
    paid for a test that asserted the number instead of the behaviour.
    """
    js = _realtime_js()
    call = re.search(r"fetchJson\('/api/v1/track1-runtime',\s*([A-Za-z0-9_]+)\s*\)", js)
    assert call, "track1-runtime is fetched without a timeout of its own"
    name = call.group(1)
    if name.isdigit():
        budget = int(name)
    else:
        decl = re.search(rf"const\s+{re.escape(name)}\s*=\s*(\d+)", js)
        assert decl, f"the timeout constant {name} is never given a value"
        budget = int(decl.group(1))
    assert budget > MEASURED_TRACK1_RUNTIME_COLD_MS, (
        f"track1-runtime gets {budget}ms but has been measured taking "
        f"{MEASURED_TRACK1_RUNTIME_COLD_MS}ms cold, so the first load fails every time"
    )


def test_the_slowest_endpoint_does_not_gate_the_first_paint():
    """One slow read must not decide when the rest of the page is allowed to appear.

    track1-runtime sat inside the awaited `Promise.allSettled` batch, and `render()` ran
    only after that batch settled. Measured on a fresh load with that endpoint slow: the
    Market View summary read "--" and the Regime block was empty from 0.5s to somewhere
    between 9.06s and 12.05s, while the market-view endpoint that fills BOTH had already
    answered in 41ms. That is the "Market View shows no data even though the API worked"
    report, and it is a frontend ordering defect, not a data one.
    """
    js = _realtime_js()
    batch = re.search(r"const results = await Promise\.allSettled\(\[(.*?)\]\);", js, re.S)
    assert batch, "poll() no longer has the settled batch this test is about"
    assert "/api/v1/track1-market-view" in batch.group(1), (
        "market-view left the batch — this test would then pass without checking anything"
    )
    assert "/api/v1/track1-runtime" not in batch.group(1), (
        "track1-runtime is back inside the awaited batch, so its cold read once again holds "
        "back the first paint of Market View and Regime"
    )


def test_the_track1_panel_separates_not_yet_answered_from_did_not_answer():
    """Polling on its own clock creates a state that did not exist before: no answer YET.

    Before the split, `state.track1` was always set by the time anything rendered, so the
    renderer could treat "falsy" as "failed". Now there is a real moment on every load when
    the request is simply still in flight, and printing "the endpoint did not answer" during
    it is the same false alarm in the opposite direction.
    """
    js = _realtime_js()
    assert "if (!t1 || t1.error) {" not in js, (
        "the renderer still collapses 'not answered yet' into 'did not answer'"
    )
    assert re.search(r"if \(!t1\) \{", js), "there is no 'still reading' branch"
    assert re.search(r"if \(t1\.error\) \{", js), "there is no 'answered with an error' branch"
    assert "Reading the Track 1 evidence tree" in js
    assert "Track 1 runtime endpoint did not answer" in js


def test_only_one_track1_runtime_read_is_in_flight_at_a_time():
    """The budget is longer than the poll interval, so overlap has to be closed explicitly.

    20s budget against an 8s poll means up to three reads of the same evidence tree in
    flight together, and whichever finished last would win — an older payload able to
    overwrite a newer one.
    """
    js = _realtime_js()
    assert "let track1InFlight = false;" in js
    assert re.search(r"if \(track1InFlight\) return;", js)
    # NOT a bare `"track1InFlight = false;" in js`: the DECLARATION one line up satisfies
    # that substring, so deleting the release inside `finally` left the assert green while
    # the guard latched shut forever and the panel stopped refreshing. The release has to be
    # checked where it has to happen — in the finally, so a thrown read still opens the gate.
    released = re.search(r"\}\s*finally\s*\{[^}]*track1InFlight = false;[^}]*\}", js)
    assert released, "the in-flight guard is never released in a finally, so it latches shut"


# --- Stage 5ZZZ-AG: which DAY the market view describes ----------------------------------
#
# The panel described the calendar day unconditionally. On Saturday 2026-08-29 and Sunday
# 2026-08-30 that meant 22 NKD slots labelled "no record was written for this slot" for a
# session that was never scheduled, and a summary line reading "Complete · 22/22 slots
# observed" — Friday's count — printed directly above those 22 empty slots.
#
# The anchor is the last TRADING day, never "the last day that has data". The two agree on a
# weekend and disagree on the one day that matters, which is what the second test is for.

def _mv():
    from monitor.backend import track1_market_view as mv
    return mv


def test_the_market_view_anchors_on_the_last_trading_day_when_the_market_is_shut():
    mv = _mv()
    # 2026-08-29 Sat and 2026-08-30 Sun both fall back to Friday the 28th.
    assert mv._anchor_day("2026-08-29") == "2026-08-28"
    assert mv._anchor_day("2026-08-30") == "2026-08-28"
    # A holiday is a closed day too, and the fallback has to skip it rather than land on it:
    # 2026-09-07 is Labor Day, so Tuesday the 8th looks back past it to Friday the 4th.
    assert mv._anchor_day("2026-09-07") == "2026-09-04"
    assert mv._anchor_day("2026-09-08") == "2026-09-08"
    # An ordinary trading day anchors on itself.
    assert mv._anchor_day("2026-08-28") == "2026-08-28"
    assert mv._anchor_day("2026-08-31") == "2026-08-31"


def test_a_trading_day_with_no_evidence_still_anchors_on_itself():
    """The whole reason the rule is "last trading day" and not "last day with data".

    A Wednesday where the scheduler died has no evidence at all. Anchoring on the last day
    that HAS data would show Tuesday — complete, green, and the outage invisible. The
    calendar decides the anchor and the evidence decides what is drawn on it, so an outage
    shows up as the empty day it is.
    """
    mv = _mv()
    # No root, no ledger, no bars are passed in — the anchor cannot be consulting evidence,
    # because it is not given any. A trading day far enough ahead that nothing can exist for
    # it still comes back as itself.
    assert mv._anchor_day("2026-12-16") == "2026-12-16"     # a Wednesday
    import inspect
    params = list(inspect.signature(mv._anchor_day).parameters)
    assert params == ["today"], (
        f"_anchor_day takes {params}; anything beyond the date is an opening for the "
        f"evidence to decide the anchor, which is the defect this rule exists to prevent"
    )


def test_the_coverage_verdict_is_for_the_day_shown_not_the_last_day_recorded(tmp_path):
    """Two days in one sentence was the reported symptom; this pins the half that lied.

    The ledger holds a COMPLETE Friday. Asked about the Monday after, the panel must not
    hand back Friday's 22/22 — it must say the Monday is unobserved, which is what the
    ledger itself says about a date with no `window_closed` record.
    """
    import global_index.window_ledger as wl
    from global_index.track1_params import WINDOWS_ET

    mv = _mv()
    sleeve = sorted(WINDOWS_ET)[0]
    d = tmp_path / "global_index" / "track1_runtime" / "window_coverage"
    d.mkdir(parents=True)
    exp = wl.expected_slots(sleeve) or 22
    rows = [{"event": wl.SLOT_OBSERVED, "sleeve": sleeve, "date": "2026-08-28"}
            for _ in range(exp)]
    rows.append({"event": wl.WINDOW_CLOSED, "sleeve": sleeve, "date": "2026-08-28",
                 "outcome": wl.COMPLETE, "signal": wl.NO_SIGNAL,
                 "expected_slots": exp, "observed_slots": exp})
    (d / "window_coverage_20260828.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    friday = mv._coverage(tmp_path, "2026-08-28")
    assert friday[sleeve]["outcome"] == wl.COMPLETE
    assert friday[sleeve]["observed_slots"] == exp, "the fixture itself has to be readable"

    monday = mv._coverage(tmp_path, "2026-08-31")
    assert monday[sleeve]["date"] == "2026-08-31"
    assert monday[sleeve]["outcome"] == wl.UNOBSERVED
    assert monday[sleeve]["observed_slots"] == 0, (
        "Friday's count leaked onto Monday — this is the 'Complete · 22/22' printed above "
        "22 empty slots that the stage was opened on"
    )
    assert monday[sleeve]["usable_as_evidence"] is False


def test_the_page_says_when_it_is_showing_a_closed_session():
    """Anchoring on Friday and staying silent about it is the same lie pointed the other way.

    The payload carries `session_is_today`, and the chip strip has to read it: without a
    line saying so, "Complete · no signal" from Friday reads as this morning's verdict.
    """
    js = _realtime_js()
    assert "session_is_today === false" in js, (
        "nothing on the page reacts to the session not being today"
    )
    assert "Closed today" in js
    # And the backend must actually publish the field the page keys off.
    src = (BACKEND / "track1_market_view.py").read_text(encoding="utf-8")
    for field in ('"session_is_today"', '"today_et"', '"session_anchor"',
                  '"session_anchor_reason"'):
        assert field in src, f"{field} is read by the page but never published"


# --- Stage 5ZZZ-AH: recorded evidence beats a replay of it -------------------------------

def test_the_setup_card_prefers_what_the_slot_recorded_over_a_replay(tmp_path, monkeypatch):
    """The replay reads the persisted bar store; the slot read the live provider join.

    They are not the same data, and the block that carries the replay says so in its own
    warning. So a session that HAS a recorded block was being described by a reconstruction
    of itself — the weaker of two available answers, shown as though it were the only one.
    """
    from global_index import track1_strategy_diagnostics as sd

    mv = _mv()
    day, sleeve = "2026-08-31", "global_nkd"
    block = {"schema": sd.SCHEMA, "sleeve": sleeve, "slot_id": "TRACK1_NKD_0255",
             "session_date": day, "diagnostics_source": sd.RECORDED,
             "detector": "track1_normal_r4", "last_bar_ts": "2026-08-31 02:55:00",
             "bars_evaluated": 22, "reconstructed_at": None, "reconstructed_through": None,
             "warning": "", "summary": "recorded by the slot",
             "nearest_failed_condition": None, "price_levels": [], "levels_armed": False,
             "setup": None, "gates": [],
             "rows": [{"label": "Trend filter (EMA 10)", "value": 66600.0,
                       "display_value": "66,600.00", "unit": "price", "threshold": None,
                       "comparator": "", "passed": None, "detail": "", "missing": None}]}
    sd.record(block, root=tmp_path, day=day)

    # If the replay were reached it would raise, so this also proves which path ran.
    def _must_not_run(*a, **k):                      # pragma: no cover - the point is it isn't
        raise AssertionError("the reconstruction ran even though a recorded block exists")
    monkeypatch.setattr(mv, "_normal_r4_reconstruction", _must_not_run)

    out = mv._strategy(tmp_path, sleeve, day, mv.SLEEVES[sleeve])
    assert out["diagnostics_source"] == sd.RECORDED
    assert out["rules"], "the recorded rows did not reach the payload"
    assert out["rules"][0]["value"] == 66600.0
    assert out["rules"][0]["source"] == sd.RECORDED


def test_a_session_with_no_recorded_block_still_falls_back_to_the_replay(tmp_path, monkeypatch):
    """The guard against fixing one blank by creating another.

    Every session before the recording seam landed has no block at all, and those days must
    keep showing the replay rather than going empty.
    """
    mv = _mv()
    sentinel = {"status": "replayed", "rules": [], "diagnostics_source": "reconstructed_today"}
    monkeypatch.setattr(mv, "_normal_r4_reconstruction",
                        lambda root, sleeve, day, spec, out, **k: dict(sentinel))
    out = mv._strategy(tmp_path, "global_nkd", "2026-08-28", mv.SLEEVES["global_nkd"],
                       now="2026-08-28 03:00")
    assert out["status"] == "replayed", "an absent recorded block took the panel blank"


def test_the_page_header_dates_the_track1_session_not_the_legacy_snapshot():
    """The date at the top is the frame every panel under it is read in.

    Measured 2026-08-30: the header read "Aug 24, 2026" — the legacy runner's last snapshot,
    six days old — while Track 1's own last session was 2026-08-28.
    """
    js = _realtime_js()
    assert "sessionDate(snap?.date);" not in js, "the header still dates the legacy snapshot"
    assert "const t1SessionDay = state.marketView?.market_view?.session_date;" in js
    assert "sessionDate(t1SessionDay || snap?.date)" in js, (
        "the legacy date must remain the fallback for a machine with no Track 1 record"
    )
    # The legacy LOG fetches must keep the legacy day: asking for session events on a day the
    # legacy runner never held a session is a request that can only come back empty.
    assert "const sessionDay = latestSnap()?.date;" in js, (
        "the session-events / execution-quality fetches were switched to the Track 1 day; "
        "those logs belong to the legacy runner and only exist on its own days"
    )


# --- Stage 5ZZZ-AJ: the panel must not answer a rule the engine answers differently -------

def test_the_ema_row_states_a_measurement_and_never_a_verdict():
    """It printed a tick mark for a test it was not performing.

    The sleeve's EMA filter is `|pullback_bar.close - ema| / ema <= 0.005` — a PROXIMITY test
    on bar[-2]. The row computed `resume_bar.close - ema > 0` — a SIGN test on bar[-1], which
    is the DIRECTION gate, a different gate one step later in the same function.

    Measured on the real stores, 3,999 bars per sleeve, row answer against engine gate:
    NKD agree 52.7% (says PASSED where the gate refuses 1.9%, says FAILED where it allows
    45.4%); Swing agree 53.8% / 3.1% / 43.1%. The worst bar printed "passed" while sitting
    7.06% from the EMA against a 0.50% threshold.

    Recomputing the real test in the diagnostics module would be a second implementation of a
    rule that trades. So the number stays and the verdict goes.
    """
    from global_index import track1_strategy_diagnostics as sd

    # Inherits the real observer rather than duck-typing it. Stage 5ZZZ-AW gave `rows()` a
    # verdict copied from the slot's own `regime` gate, and a stand-in that only carried a last
    # bar stopped satisfying the contract. Subclassing keeps the contract whole -- with no
    # gates recorded, the Regime row simply has no verdict, which is the honest answer.
    class _Obs(sd.NormalR4Observer):
        first_failed_gate = None
        regime_detail = ""

    obs = _Obs()

    class _Bar:
        def __init__(self, close, volume): self.close, self.volume = close, volume

    # A bar 5% above the EMA: the old row called this "passed"; the engine's gate refuses it.
    obs.last_bar = {"ema": 100.0, "atr": 1.0, "avgv": 10.0, "bar_ts": "2026-08-31 02:55",
                    "regime": "Normal", "resume_bar": _Bar(105.0, 12.0)}
    rows = sd.NormalR4Observer.rows(obs, ema_period=10)
    by_label = {r["label"]: r for r in rows}
    assert "Price vs EMA" not in by_label, "the row still carries the old, wrong name"
    row = by_label.get("Close minus EMA")
    assert row is not None, "the distance row disappeared instead of losing its verdict"
    assert row["value"] == 5.0, "the measurement itself must survive — only the verdict goes"
    assert row["passed"] is None, (
        "the row still publishes a verdict for a test it does not perform"
    )


def test_rules_that_cannot_have_an_entry_verdict_leave_the_lanes(tmp_path):
    """A lane that must stay empty forever is a lane an operator learns to skip.

    Measured across every stored session — 291 slot records, 5 days, three sleeves — not one
    of the 24 declared rules has ever carried a verdict. For twenty-one that is a gap waiting
    on the detector. For these three it is permanent: the window is applied by slicing the
    bars before the detector runs, and the other two govern a position that does not exist at
    entry time.
    """
    from global_index import track1_signals as sig

    mv = _mv()
    assert set(sig.NOT_ENTRY_CONDITIONS) == {"japan_session_window", "max_hold_context",
                                            # Stage 5ZZZ-BG: declared by the
                                            # Stress sleeve, never evaluated.
                                            "no_regime_label_required",
                                             "stop_arm_rule"}
    # Every name classified out has to still BE a declared rule, or the classification is
    # silently doing nothing and the lanes would look correct for the wrong reason.
    declared = {n for s in sig.RULES for n in sig.RULES[s]}
    assert set(sig.NOT_ENTRY_CONDITIONS) <= declared, (
        "a name was classified out of the lanes that no sleeve declares — the two lists drifted"
    )
    for sleeve in ("global_nkd", "roska4_swing"):
        entry = set(sig.entry_rule_names(sleeve))
        assert entry, "a sleeve lost every entry rule"
        assert entry < set(sig.rule_names(sleeve)), "nothing was classified out for this sleeve"
        assert not (entry & set(sig.NOT_ENTRY_CONDITIONS))

    rows = [{"sleeve": "global_nkd", "slot_id": "TRACK1_NKD_0110",
             "rule_checks": [{"rule": n, "threshold": None, "comparator": "", "detail": "",
                              "source": "not_exposed_by_sleeve", "passed": None}
                             for n in sig.rule_names("global_nkd")]}]
    slots = [{"slot_id": "TRACK1_NKD_0110", "time_et": "01:10", "status": "no_signal"}]
    lanes = {L["rule"] for L in mv._rule_lanes(rows, "global_nkd", slots)}
    assert "japan_session_window" not in lanes and "max_hold_context" not in lanes
    # Stage 5ZZZ-AS moved the per-BAR rules to the grid, so `ema10_filter` is no longer the
    # witness that an entry rule survived. `regime_lag_1` is: the detector answers it once per
    # slot, so a lane cell can hold it, and it must not be swept out with the two above.
    assert "regime_lag_1" in lanes, "an entry rule was swept out with them"
    assert "ema10_filter" not in lanes, (
        "a per-bar rule is back in the per-slot lanes; within one slot it is answered once "
        "per bar and the cell has no single value")

    cfg = mv._declared_config(rows, "global_nkd")
    assert {c["rule"] for c in cfg} == {"japan_session_window", "max_hold_context"}, (
        "they left the lanes and were not reported anywhere else — that is deletion, not a move"
    )
    assert all(c["reason"] for c in cfg), "each has to say WHY it carries no verdict"


def test_the_page_draws_the_declared_config():
    """Nó không còn là một HÀNG LANE nữa — muc 4.5 đặt phần này ở cuối hàng legend.

    Điều phải giữ không đổi là ba thứ: nó vẫn được dựng, vẫn đọc `declared_config`, và mỗi
    mục vẫn mang lý do trên hover. Cái cuối là điểm dễ mất nhất khi dời một khối: nếu thay
    bằng một dòng chữ trần thì trang trông giống design hơn mà người đọc mất đường hỏi
    "vì sao cái này không phải điều kiện vào lệnh".
    """
    js = _realtime_js()
    css = (DASH / "realtime-next" / "next.css").read_text(encoding="utf-8")
    assert "function mvDeclaredInline(s)" in js
    assert "${mvLaneLegend(mvDeclaredInline(s))}" in js, "the block is defined but never drawn"
    assert "s.declared_config" in js
    assert "mvDeclaredConfig" not in js, "hàm cũ còn sót lại thì có hai bản để trôi khỏi nhau"
    # Tooltip là cơ chế cố ý, không phải trang trí.
    assert 'data-tooltip="${mvEsc(c.reason)}"' in js
    assert ".mv2-legend-declared" in css, "phần đuôi không có layout và sẽ rơi xuống dòng"


# --- Stage 5ZZZ-AM: the verdict belongs to the BAR, never to the slot --------------------
#
# Measured by cutting the window at every five-minute mark through a real session and
# re-asking the detector: 865 verdicts computed, 80 distinct, and NOT ONE that differed
# between cuts. A bar's answer is fixed when the bar closes.
#
# That is what makes a grid possible. The panel drew one cell per SLOT, and a slot cell has
# no single value: the 14:10 slot has seen one bar, the 15:55 slot twenty-two, and within one
# slot a rule can come back twelve times pass and ten times fail. Which is why every detector
# rule has read "value not published" on all 291 slot records ever written — not for want of
# data, but because the question had no answer.

def _observer_with(events):
    from global_index import track1_strategy_diagnostics as sd
    obs = sd.NormalR4Observer()
    for e in events:
        obs({"kind": "bar_gate", **e})
    return obs


def test_the_grid_is_anchored_on_bars_and_marks_gates_that_never_ran():
    from global_index import track1_strategy_diagnostics as sd

    obs = _observer_with([
        {"gate": "ema", "passed": True, "value": 1, "threshold": 0.005, "bar_ts": "t1"},
        {"gate": "vol", "passed": False, "value": 2, "threshold": 3, "bar_ts": "t1"},
        {"gate": "ema", "passed": False, "value": 9, "threshold": 0.005, "bar_ts": "t2"},
        # t2 never reaches `vol` — the EMA gate returned first. That absence has to READ as
        # an absence, not as a pass and not as a failure.
        {"gate": "ema", "passed": True, "value": 1, "threshold": 0.005, "bar_ts": "t3"},
        {"gate": "vol", "passed": True, "value": 4, "threshold": 3, "bar_ts": "t3"},
    ])
    g = obs.bar_gate_grid()
    assert g["bars"] == ["t1", "t2", "t3"], "the columns are not the bars, in bar order"
    rows = {r["gate"]: r for r in g["rows"]}
    assert rows["ema"]["cells"] == "PFP"
    assert rows["vol"]["cells"] == "F-P", (
        "a gate that never ran on a bar is drawn as though it had — 'did not run' and "
        "'ran and passed' are different facts about the route"
    )
    assert (rows["vol"]["reached"], rows["vol"]["passed"]) == (2, 1)
    assert (rows["ema"]["reached"], rows["ema"]["passed"]) == (3, 2)
    assert rows["ema"]["threshold"] == 0.005, "the row lost the threshold it was measured on"
    # The funnel is the same pass, so the summary and the cells cannot disagree.
    assert rows["vol"]["reached"] == rows["ema"]["passed"], (
        "the funnel does not chain: `reached` on a later gate must equal `passed` on the one "
        "before it, because the gates are ordered and the first refusal returns"
    )


def test_the_persisted_block_never_carries_the_raw_per_bar_events():
    """A slot can produce 154 of them and every slot of every session persists a block.

    This repo already carries one array nobody capped: it reached 360 KB inside a 426 KB
    file, one entry per trading day, and it was found by reading the file rather than by any
    check. Twenty-two characters per rule do not do that.
    """
    from global_index import track1_strategy_diagnostics as sd

    obs = _observer_with([{"gate": "ema", "passed": True, "value": i, "threshold": 1,
                           "bar_ts": f"t{i}"} for i in range(40)])
    block = sd.normal_r4_block(sleeve="global_nkd", slot_id="S", ema_period=10,
                               observer=obs, setup=None, data_identity="d",
                               source=sd.RECORDED)
    assert "bar_gate_grid" in block
    assert "bar_gates" not in block, "the raw event list reached the persisted record"
    assert block["bar_gate_grid"]["rows"][0]["cells"] == "P" * 40
    assert len(json.dumps(block, default=str)) < 8000, "the block is growing without a bound"


def test_the_bar_grid_never_lands_in_the_slot_lanes():
    """Two axes, and merging them is the defect this stage exists to end.

    `rule_lanes` is one cell per SLOT and `bar_grid` is one cell per BAR. A reader who takes
    one for the other is reading a verdict against the wrong instant.
    """
    mv = _mv()
    src = (BACKEND / "track1_market_view.py").read_text(encoding="utf-8")
    assert 'blk["bar_grid"]' in src, "the grid never reaches the payload"
    assert "bar_gate_grid" in src

    # A per-SLOT rule, because a per-bar one no longer produces a lane at all and the
    # assertion below would then be counting cells on an empty list.
    rows = [{"sleeve": "global_nkd", "slot_id": "TRACK1_NKD_0110",
             "rule_checks": [{"rule": "regime_lag_1", "threshold": None, "comparator": "",
                              "detail": "", "source": "not_exposed_by_sleeve",
                              "passed": None}]}]
    slots = [{"slot_id": "TRACK1_NKD_0110", "time_et": "01:10", "status": "no_signal"}]
    lanes = mv._rule_lanes(rows, "global_nkd", slots)
    assert lanes, "the fixture produced no lanes — this test would pass on nothing"
    for lane in lanes:
        assert len(lane["cells"]) == len(slots), (
            "a lane has a cell count that is not the slot count, so something bar-shaped "
            "was written into the slot axis"
        )


def test_the_page_draws_the_bar_grid_apart_from_the_lanes():
    js = _realtime_js()
    css = (DASH / "realtime" / "realtime.css").read_text(encoding="utf-8")
    assert "function mvBarGrid(s)" in js
    # Stage 5ZZZ-AS gave the grid its own tab, so it is drawn through its card wrapper rather
    # than appended to the lanes. The thing being pinned is unchanged: it reaches the page.
    assert "mvBarGridCard(s)" in js, "the grid is built but never drawn"
    assert "function mvBarGridCard(s)" in js
    assert "s.bar_grid" in js
    assert "one cell per bar, not per slot" in js, (
        "nothing on the page tells the reader the grid is on a different axis from the lanes"
    )
    assert ".mv2-bargrid" in css, "the grid has no fence and would read as more lanes"


def test_track1_never_paints_the_page_before_the_batch_has_landed():
    """A race I put there, found by three DOM tests failing on one run and a different one
    on the next.

    `pollTrack1` awaits ONE request; the batch awaits six and then a second round of three
    before it renders. So Track 1 nearly always won on a fresh load and its `render()`
    painted the whole page out of empty state — a status rail with no runner behind it and
    every metric reading "--". The DOM tests wait for that rail and then read a metric, so
    they read the empty pass.

    Nothing is lost by waiting: before the batch lands there is nothing else to draw.
    """
    js = _realtime_js()
    assert "let firstBatchRendered = false;" in js
    assert "if (firstBatchRendered) render();" in js, (
        "pollTrack1 renders unconditionally again — it can repaint the page from empty state"
    )
    # The flag has to be raised by the BATCH, not by Track 1, or it means nothing.
    m = re.search(r"firstBatchRendered = true;\s*\n\s*render\(\);", js)
    assert m, "the flag is never raised where the batch renders"
    # And raised BEFORE that render, so a Track 1 read landing mid-render is not suppressed
    # for a whole extra cycle.
    assert js.index("firstBatchRendered = true;") < js.index(
        "$('fatalBanner').hidden") + js[js.index("$('fatalBanner').hidden"):].index("render();") \
        + js.index("$('fatalBanner').hidden")


def test_the_detail_tabs_survive_a_session_with_bars_but_no_slot_records():
    """The strip gated on the LANES alone, and that stopped being right when the grid became
    a tab of its own.

    Early on a trading day the replay can have scanned bars while no slot has written a record
    yet: per-bar verdicts exist, lanes do not, and the whole strip vanished -- taking the only
    route to those verdicts with it. Found on a live page at 04:25 ET on a Monday, where the
    session anchored on today and today had no records.
    """
    js = _realtime_js()
    assert "const hasGrid" in js and "if (!hasLanes && !hasGrid)" in js, (
        "the tab strip is gated on lanes alone again, so a session with bars and no slot "
        "records has no way to reach its per-bar verdicts"
    )


# --- Stage 5ZZZ-AU: a job that never spawns a child was invisible ------------------------
#
# Measured across every August scheduler log: five bracketed labels had NEVER become a job
# card, because a card was only opened on a line carrying `-m global_index.`. Three of them
# are registered scheduler jobs -- `PREFLIGHT`, the 13:45 gate that decides whether the
# session runs at all; `SPY_WEEKEND_PRE_NKD_CHECK`; and `SPY_LAST_CHANCE_PRE_NKD`, which is
# visible on the days it has work and vanishes on the days it looks and finds the data
# already fresh. `MAXHOLD_T1` carries a CRITICAL about a five-day Track 1 position possibly
# not being closed.
#
# The invisible case was the GOOD one, which is why no failure ever revealed it.

def _journal_from(lines, tmp_path, day="2026-08-31"):
    from monitor.backend import job_journal_reader as jj

    (tmp_path / f"scheduler_{day[5:7]}{day[8:10]}.log").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    return jj.read_job_journal(day, root=tmp_path)


def test_an_in_process_job_gets_a_card_and_that_card_is_closed(tmp_path):
    """One line in, one finished card out.

    A card left open would sit on the operations page reading "running" forever -- an alarm
    with no off switch, which is worse than the silence it replaced.
    """
    d = _journal_from([
        "2026-08-31 00:45:00  INFO     run_scheduler — [SPY_LAST_CHANCE_PRE_NKD] nothing to "
        "do — the daily series covers 2026-08-28",
    ], tmp_path)
    jobs = {j["job_id"]: j for j in d["jobs"]}
    assert "SPY_LAST_CHANCE_PRE_NKD" in jobs, "an in-process job is invisible again"
    job = jobs["SPY_LAST_CHANCE_PRE_NKD"]
    assert job["ended_at"] is not None, "the card never closes and reads as running forever"
    assert job["status"] == "completed"
    assert "nothing to do" in (job["reason"] or "")


def test_a_critical_from_an_in_process_job_is_a_failed_card(tmp_path):
    """`MAXHOLD_T1` logs CRITICAL when the catch-up that closes a five-day Track 1 position
    fails. That must not arrive as a green card, and must not arrive as nothing."""
    d = _journal_from([
        "2026-08-31 09:31:00  CRITICAL  run_scheduler — [MAXHOLD_T1] CATCH-UP THAT BAI",
    ], tmp_path)
    jobs = {j["job_id"]: j for j in d["jobs"]}
    assert "MAXHOLD_T1" in jobs
    assert jobs["MAXHOLD_T1"]["status"] == "failed"


def test_the_heartbeat_is_a_pulse_and_never_a_job(tmp_path):
    """545 lines of the word "alive" across August. Cards for those would bury the page this
    journal exists to keep readable."""
    d = _journal_from([
        f"2026-08-31 {h:02d}:00:00  INFO     run_scheduler — [HEARTBEAT] alive"
        for h in range(6)
    ], tmp_path)
    assert d["jobs"] == [], f"the heartbeat became {len(d['jobs'])} job cards"


def test_every_scheduler_job_can_reach_the_journal():
    """The two-way check, run against the REAL scheduler rather than a list kept here.

    A job added to the scheduler that the journal can never show is the defect this stage
    exists to close, and it is the kind that is only ever found by somebody asking.
    """
    from monitor.backend import job_journal_reader as jj

    src = (ROOT / "global_index" / "run_scheduler.py").read_text(encoding="utf-8")
    registered = {i.upper() for i in re.findall(r'id="([a-z0-9_]+)"', src)}
    assert registered, "no scheduler jobs were found — this test would pass on nothing"
    unreachable = sorted(j for j in registered
                         if j in jj._LIVENESS_LABELS and j != "HEARTBEAT")
    assert not unreachable, (
        f"these registered jobs are classified as a pulse and can never appear: {unreachable}")
    # And the liveness list stays a list of pulses, not a place things get hidden.
    assert jj._LIVENESS_LABELS == frozenset({"HEARTBEAT"}), (
        "something new was excluded from the journal; a label that is not a pulse belongs on "
        "the page, and hiding it here is how a job goes quiet without anyone deciding it should"
    )


def test_a_list_threshold_is_worded_not_repr_printed():
    """Ngưỡng dạng danh sách phải đọc được, không phải repr Python.

    Ca thật, đo trên /realtime phiên 2026-08-31: lane "regime lag 1" in ra
    `needs ['Normal']`. Dấu ngoặc vuông và dấu nháy đơn là cú pháp Python lọt
    thẳng ra bảng vận hành — người trực đọc `['Normal']` không biết đó là một
    trạng thái hay một danh sách rỗng viết sai.

    Nguồn: một detector publish ngưỡng là list (các regime được phép), còn
    `_threshold_display` chỉ có nhánh cho None/dict/bool rồi rơi vào `str(raw)`.
    Docstring của nó nói "scalars và one-key dicts" — list là trường hợp thứ ba
    không ai lường, và nó im lặng.

    Test ghim CÁCH ĐỌC, không ghim một literal: một phần tử đọc thẳng, nhiều
    phần tử nối bằng "or" để câu "needs …" bên cạnh vẫn thành câu tiếng Anh.
    """
    from monitor.backend.track1_market_view import _threshold_display

    assert _threshold_display(["Normal"]) == "Normal"
    assert _threshold_display(["Normal", "Stress"]) == "Normal or Stress"
    assert _threshold_display(["Calm", "Normal", "Stress"]) == "Calm, Normal or Stress"
    assert _threshold_display([]) == ""
    # Không được có cú pháp Python trong bất kỳ đầu ra nào
    for raw in (["Normal"], ["Normal", "Stress"], ("Normal",)):
        rendered = _threshold_display(raw)
        assert "[" not in rendered and "'" not in rendered, rendered


def test_a_python_list_literal_never_reaches_a_display_string():
    """Chuỗi văn xuôi từ detector không được mang cú pháp Python ra bảng.

    Ca thật, đo trên /realtime: hai chỗ in ra
    `regime 'Calm'; this sleeve trades ['Normal']`. Câu này do engine dựng
    (track1_normal_r4: f-string in thẳng `sorted(ALLOWED_REGIMES)`) rồi dashboard
    chuyển nguyên si ra ngoài qua `summary` và `nearest_failed_condition`.

    Chỉ chuẩn hoá LIST LITERAL, cố ý không đụng dấu nháy đơn trong văn xuôi:
    ghép cặp nháy trong "today's own row and tomorrow's" sẽ nuốt mất nửa câu.
    Dấu ngoặc vuông là thứ không thể nhầm; dấu nháy thì có thể.
    """
    from monitor.backend.track1_market_view import _words_for_list_literals as f

    assert f("this sleeve trades ['Normal']") == "this sleeve trades Normal"
    assert f("trades ['Normal', 'Stress']") == "trades Normal or Stress"
    assert f("trades ['Calm', 'Normal', 'Stress']") == "trades Calm, Normal or Stress"
    assert f("regime 'Calm'; this sleeve trades ['Normal']") \
        == "regime 'Calm'; this sleeve trades Normal"
    # văn xuôi có dấu nháy phải nguyên vẹn
    keep = "today's own row and tomorrow's are both read"
    assert f(keep) == keep
    # không có ngoặc vuông thì không đổi gì
    assert f("needs >= 3") == "needs >= 3"
    assert f("") == ""
    assert f(None) is None


def test_no_display_string_anywhere_in_the_payload_carries_a_list_literal():
    """Quét CẢ payload, không vá từng trường.

    Lần đầu tôi chỉ sửa `threshold_display`, và trang vẫn còn hai chỗ; sửa tiếp
    `setup_boundary` thì vẫn còn một chỗ nữa ở `strategy.detail`. Ba lần vá ba
    trường là dấu hiệu đang đuổi theo triệu chứng: bất kỳ detector nào sau này
    nội suy một list vào câu văn cũng sẽ lọt ra y như vậy, và nó sẽ không báo.

    Nên cổng đặt ở CHỖ RA: không một chuỗi nào trong payload được mang cú pháp
    list của Python. Danh sách thật (`threshold: ["Normal"]`) vẫn là danh sách —
    đó là dữ liệu có cấu trúc, không phải chuỗi hiển thị.
    """
    from monitor.backend.track1_market_view import _scrub_list_literals

    payload = {
        "a": "trades ['Normal']",
        "b": {"c": "needs ['Calm', 'Stress']", "d": ["Normal"], "e": 7},
        "f": [{"g": "plain"}, "trades ['A', 'B', 'C']"],
    }
    out = _scrub_list_literals(payload)
    assert out["a"] == "trades Normal"
    assert out["b"]["c"] == "needs Calm or Stress"
    assert out["b"]["d"] == ["Normal"], "danh sách thật phải giữ nguyên kiểu"
    assert out["b"]["e"] == 7
    assert out["f"][1] == "trades A, B or C"

    def walk(o):
        if isinstance(o, str):
            assert "['" not in o and "']" not in o, o
        elif isinstance(o, dict):
            [walk(v) for v in o.values()]
        elif isinstance(o, list):
            [walk(v) for v in o]
    walk(out)


def test_the_hover_reads_the_plot_padding_instead_of_restating_it():
    """Hai bản sao của một quyết định, và bản thứ hai đã trôi.

    `mvBindHover` tính vị trí bằng lề 8/62 trong khi plot vẽ bằng 34/68, nên đường kẻ đứng
    giữa hai cây nến — đo được x=592,6 trên lưới tâm nến 341,9 bước 25,66. Phép kiểm này ở
    tầng CẤU TRÚC chứ không phải hành vi, và có lý do: đường kẻ sai ấy giờ đã bị ẩn, nên
    không còn gì nhìn thấy được để một phép kiểm hành vi bám vào. Thứ còn lại đáng bảo vệ là
    "chỉ có MỘT nơi khai lề".
    """
    js = _realtime_js()
    assert "const MV_PAD = { L: 34, R: 68 };" in js
    assert "padL = MV_PAD.L, padR = MV_PAD.R, padT" in js, "plot không đọc từ hằng chung"
    assert "const W = 1000, padL = MV_PAD.L, padR = MV_PAD.R;" in js, "hover không đọc từ hằng chung"
    # Chart CHUỖI có lề riêng (52/12) và đó là đúng — nó là một plot khác. Điều phải giữ
    # là hai nơi cùng nói về plot GIÁ thì đọc chung một hằng, không phải "không ai được
    # viết số nữa".
    assert "padL = 52" in js, "chart chuỗi mất lề riêng của nó"
