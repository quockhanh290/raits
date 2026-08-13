from __future__ import annotations

import ast
import datetime as dt
import inspect
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
        "2026-08-11 12:05:12 INFO global_index.runner - Runner started: loaded 1 position(s) from persisted file\n"
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
    assert gates["b3_reconcile"]["status"] == "PASS"
    assert coverage["fill_quality"]["metrics"]["fills"] == 3
    assert coverage["current_protection"]["status"] == "OBSERVED"
    assert coverage["sample_denominators"]["metrics"]["by_inst"] == {"M2K": 1, "MES": 1, "MYM": 1}
    assert coverage["same_day_multi_day"]["metrics"] == {"multi_day": 1, "same_day": 0, "unknown": 0}


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
        "2026-08-10 05:13:00 INFO global_index.runner - place_stop: accepted orderId=288\n"
        "2026-08-10 05:14:00 ERROR global_index.runner - STP: place_stop FAILED for M2K\n",
        encoding="utf-8",
    )

    payload = read_paper_evidence(tmp_path)["payload"]
    gates = {gate["key"]: gate for gate in payload["gates"]}
    coverage = {item["key"]: item for item in payload["coverage"]}

    assert gates["tws_restart_nights"]["metrics"]["candidate_log_lines"] == 1
    assert gates["tws_restart_nights"]["metrics"]["candidate_days"] == ["2026-08-10"]
    assert gates["stp_verification"]["metrics"]["stp_accepted"] == 1
    assert gates["stp_verification"]["metrics"]["stp_failed"] == 1
    assert coverage["manual_intervention"]["metrics"]["candidate_log_lines"] == 1
    assert coverage["manual_intervention"]["metrics"]["candidate_days"] == ["2026-08-10"]
    assert payload["diagnostics"]["manual_intervention_candidate_lines"] == 1
    assert payload["diagnostics"]["manual_intervention_candidate_days"] == ["2026-08-10"]
    assert payload["diagnostics"]["tws_restart_candidate_lines"] == 1
    assert payload["diagnostics"]["tws_restart_candidate_days"] == ["2026-08-10"]


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
        '"stp_verification":[{"date":"2026-08-10","verified":true,"false_halt":false,"double_stp":false}],'
        '"tws_restart_spec":{"min_nights":1},'
        '"tws_restart_nights":[{"night":"2026-08-10","restart_proven":true,"runner_resumed":true,"broker_verified":true}],'
        '"manual_interventions":[{"ts":"2026-08-10T05:12:00Z","resolution_status":"resolved","post_action_verified":true}],'
        '"roll_slippage":[{"date":"2026-08-10","ticks":1.5}]}',
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
    assert payload["diagnostics"]["paper_inputs_error"] is None


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
        "2026-08-12 02:20:00 INFO run_scheduler - [STOP_REPAIR_0420] python run_stop_repair.py\n"
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
