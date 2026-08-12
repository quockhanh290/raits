"""Safety gate for append-only runner telemetry."""
from __future__ import annotations

import json
import os

from global_index.runner import FuturesRunner


def _telemetry_runner(directory):
    runner = object.__new__(FuturesRunner)
    runner._events = []
    runner._event_log_dir = directory
    runner._event_log_disabled = False
    return runner


def test_event_log_appends_valid_json_without_replacing_prior_records(tmp_path):
    first = _telemetry_runner(tmp_path)
    first._emit_event("INFO", "STATE", "first", {"position_count": 1})
    second = _telemetry_runner(tmp_path)
    second._emit_event("ALERT", "GUARD", "second")

    path = next(tmp_path.glob("runner_events_*.jsonl"))
    raw = path.read_bytes()
    records = [json.loads(line) for line in raw.splitlines()]

    assert raw.endswith(b"\n")
    assert [record["message"] for record in records] == ["first", "second"]
    assert records[0]["context"] == {"position_count": 1}


def test_event_log_failure_is_fail_open_and_disables_further_attempts(monkeypatch, tmp_path):
    runner = _telemetry_runner(tmp_path)
    attempts = 0

    def denied(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise PermissionError("denied by test")

    monkeypatch.setattr(os, "open", denied)
    runner._emit_event("CRITICAL", "STATE", "still retained in memory")
    runner._emit_event("INFO", "STATE", "no second filesystem attempt")

    assert attempts == 1
    assert runner._event_log_disabled is True
    assert [event["message"] for event in runner._events] == [
        "still retained in memory", "no second filesystem attempt",
    ]


def test_incomplete_tail_is_not_extended(tmp_path):
    path = tmp_path / "runner_events_20260812.jsonl"
    partial = b'{"ts":"2026-08-12T05:10:00Z"'
    path.write_bytes(partial)
    runner = _telemetry_runner(tmp_path)

    runner._emit_event("INFO", "STATE", "must not concatenate")

    assert path.read_bytes() == partial
    assert runner._event_log_disabled is True
