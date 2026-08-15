from __future__ import annotations

import ast
import datetime as dt
import inspect
import json
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
    assert b3_spec.get("max_mismatch_episodes") == 0
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
        '{"c1_spec":{"min_n":2,"max_mean_ticks":2,"scope":"separate","close_scope":"stp_only","use_absolute":true},'
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
        '{"c1_spec":{"min_n":1,"max_mean_ticks":5,"scope":"separate","close_scope":"stp_only","use_absolute":true}}',
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
    source = (DASH / "paper" / "paper.js").read_text(encoding="utf-8")
    assert "AbortSignal.timeout(30000)" in source


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
    assert "Progress toward required entry sample count." in source
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
    source = source.replace(
        "  load();\n  window.setInterval(load, 60000);\n})();",
        "  globalThis.__paperTest = { renderReadinessBlockers, updateCoveragePanel, updateB3Panel, updateSTPPanel, b3MoreInfo, logHygieneDetail };\n})();",
    )
    program = (
        "const vm = require('vm');\n"
        "const elements = new Map();\n"
        "function el(id) { if (!elements.has(id)) elements.set(id, { id, textContent: '', innerHTML: '', className: '', parentElement: { classList: { add(){}, remove(){}, toggle(){} } }, querySelectorAll(){ return []; }, addEventListener(){}, scrollIntoView(){} }); return elements.get(id); }\n"
        "globalThis.document = { getElementById: el };\n"
        "globalThis.window = { setInterval(){} };\n"
        "globalThis.fetch = async () => ({ ok: true, json: async () => ({ payload: {} }) });\n"
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
        lambda port, *, shadow_resume, assume_preflight_ok:
            calls.append(("start_scheduler", port, shadow_resume, assume_preflight_ok)) or 303,
    )
    monkeypatch.setattr(ops, "start_backend", lambda ibkr, api: calls.append(("start_backend", ibkr, api)) or 404)
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
    assert calls == [("taskkill", [555]), ("start_backend", 4002, 5002)]


def test_ops_up_starts_a_scheduler_when_none_is_running(monkeypatch):
    calls = []
    ops = _ops_stub(monkeypatch, calls, schedulers=[], backends=[])
    assert ops.main(["--ibkr-port", "4003", "--api-port", "5003", "up", "--yes"]) == 0
    assert calls == [
        ("start_scheduler", 4003, True, False),
        ("start_backend", 4003, 5003),
    ]


def test_ops_restart_scheduler_stops_every_instance_before_starting_one(monkeypatch):
    calls = []
    ops = _ops_stub(monkeypatch, calls, schedulers=[29340, 35120], backends=[])
    assert ops.main(["restart", "--scheduler", "--yes"]) == 0
    assert calls[0] == ("taskkill", [29340, 35120])
    assert ("start_scheduler", 4002, True, False) in calls


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
    assert "const equity = snap?.equity" in realtime_js
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


def test_favicon_does_not_404():
    """L5: trình duyệt luôn xin favicon. Một 404 thường trực trong console làm lu
    mờ lỗi thật, và console sạch là điều kiện để smoke test tin được."""
    client = app.test_client()
    assert client.get("/favicon.ico").status_code in (200, 204)
