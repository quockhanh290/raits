"""On-demand, mtime-cached session reports for the Reports module only."""
from __future__ import annotations

import copy
import re
import threading
from pathlib import Path
from typing import Any

from global_index.session_report import collect_session_report
from monitor.backend.job_journal_reader import read_job_journal
from monitor.backend.runner_event_reader import read_runner_events
from monitor.backend.runner_state_reader import read_runner_state
from monitor.backend.session_event_reader import read_session_events
from monitor.backend.execution_quality_reader import read_execution_quality

_lock = threading.Lock()
_cache: dict[tuple[str, str, tuple[tuple[str, int, int], ...]], dict[str, Any]] = {}


def _signature(root: Path) -> tuple[tuple[str, int, int], ...]:
    values = []
    for pattern in ("scheduler_*.log", "live_day_*.log"):
        for path in sorted(root.glob(pattern)):
            try:
                stat = path.stat()
            except OSError:
                continue
            values.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size))
    positions_path = root / "live_positions.json"
    try:
        stat = positions_path.stat()
        values.append((str(positions_path.resolve()), stat.st_mtime_ns, stat.st_size))
    except OSError:
        pass
    trade_path = root / "trade_log.jsonl"
    try:
        stat = trade_path.stat()
        values.append((str(trade_path.resolve()), stat.st_mtime_ns, stat.st_size))
    except OSError:
        pass
    observed_paths = [root / "global_index" / "live_state_data.js", *sorted((root / "global_index").glob("runner_events_*.jsonl"))]
    for path in observed_paths:
        try:
            stat = path.stat()
            values.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size))
        except OSError:
            pass
    return tuple(values)


def read_report(day: str, root: Path) -> dict[str, Any]:
    key = (str(root.resolve()), day, _signature(root))
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return copy.deepcopy(cached)
    report = collect_session_report(day, root)
    raw_lines = report.get("lines", [])
    # Raw log lines are working material for the collector, not dashboard data.
    # Returning them makes a normal report several megabytes without adding UI evidence.
    report.pop("lines", None)
    journal = read_job_journal(day, root)
    events = read_session_events(day, root)
    execution_quality = read_execution_quality(root, day)
    runner_events = read_runner_events(day, root)
    runner_state = read_runner_state(root / "global_index" / "live_state_data.js")
    snapshots = (runner_state.get("payload") or {}).get("snapshots", [])
    session_snapshot = next((item for item in reversed(snapshots) if item.get("date") == day), None)
    jobs = journal.get("jobs", [])
    session_events = events.get("events", [])
    model_health = next((event for event in reversed(session_events)
                         if event.get("kind") == "hmm_fit_diagnostic"), None)
    status_counts: dict[str, int] = {}
    for job in jobs:
        status = str(job.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
    activity_counts: dict[str, int] = {}
    for event in session_events:
        kind = str(event.get("kind", "unknown"))
        activity_counts[kind] = activity_counts.get(kind, 0) + int(event.get("occurrences", 1))
    incidents = []
    for job in jobs:
        if job.get("status") not in {"failed", "missed"}:
            continue
        recovered = job.get("lifecycle_status") == "recovered" or "Publication resumed at" in str(job.get("impact", ""))
        incidents.append({
            **job, "lifecycle_status": "recovered" if recovered else "open",
            "recovered_at": job.get("recovered_at"),
        })
    monitor_incidents = []
    for event in journal.get("monitor_events", []):
        if event.get("kind") != "scheduler_stalled":
            continue
        later_job = next((job for job in jobs
            if str(job.get("ended_at") or job.get("started_at")) > str(event.get("ts"))
            and job.get("status") in {"completed", "completed_with_debt"}), None)
        heartbeat = next((item for item in journal.get("monitor_events", [])
            if item.get("kind") == "scheduler_recovered" and item.get("stalled_at") == event.get("ts")), None)
        recovered_at = (heartbeat or {}).get("ts") or (later_job or {}).get("ended_at")
        monitor_incidents.append({
            **event, "component": "scheduler", "lifecycle_status": "recovered" if recovered_at else "open",
            "recovered_at": recovered_at,
            "title": "Scheduler heartbeat stalled",
            "impact": "Scheduler timing paused; separately recorded missed slots remain missed.",
            "action": "No immediate action after recovery. Review Windows sleep history if another stall occurs." if recovered_at else "Check scheduler process health and Windows sleep state now.",
        })
    connectivity_incidents = [{
        **event,
        "component": "broker",
        "lifecycle_status": event.get("status", "open"),
        "reason": event.get("problem") or event.get("message"),
    } for event in session_events if event.get("kind") == "connectivity_outage"]
    protection_incidents = [{
        **event,
        "component": event.get("component", "runner"),
        "lifecycle_status": event.get("status", "open"),
        "reason": event.get("problem") or event.get("message"),
    } for event in session_events if event.get("kind") in {
        "stop_repaired", "stop_id_drift", "stop_naked"
    }]
    debt_jobs = [job for job in jobs if job.get("status") == "completed_with_debt"]
    debt_groups: dict[str, dict[str, Any]] = {}
    for job in debt_jobs:
        diagnostic = (job.get("diagnostics") or [job.get("reason") or "Known diagnostic"])[0]
        key_name = "G2_MODEL_AGE" if "G2 HARD" in diagnostic else str(diagnostic)
        group = debt_groups.setdefault(key_name, {
            "key": key_name, "title": "Model age remains HARD stale" if key_name == "G2_MODEL_AGE" else diagnostic,
            "count": 0, "first_at": job.get("started_at"), "last_at": job.get("started_at"),
        })
        group["count"] += 1
        group["last_at"] = job.get("started_at")
    report["daily"] = {
        "jobs": jobs,
        "monitor_events": journal.get("monitor_events", []),
        "runner_events": runner_events.get("events", []),
        "session_events": session_events,
        "model_health": model_health,
        "execution_quality": execution_quality,
        "job_status_counts": status_counts,
        "activity_counts": activity_counts,
        "observed_job_count": len(jobs),
        "incident_count": len(incidents) + len(monitor_incidents) + len(connectivity_incidents) + len(protection_incidents),
        "open_incident_count": sum(item["lifecycle_status"] == "open" for item in incidents + monitor_incidents + connectivity_incidents + protection_incidents),
        "incidents": incidents + monitor_incidents + connectivity_incidents + protection_incidents,
        "known_debt_job_count": len(debt_jobs),
        "known_debt": list(debt_groups.values()),
        "session_snapshot": session_snapshot,
        "regime_evidence": sorted(set(
            match.group(1) for _time, _level, line in raw_lines
            if (match := re.search(r"\bregime=([A-Za-z0-9_-]+)", line))
        )),
        "coverage": {
            "job_error": journal.get("error"),
            "event_error": events.get("error"),
            "job_observed_at": journal.get("observed_at"),
            "event_observed_at": events.get("observed_at"),
            "runner_event_error": runner_events.get("error"),
            "runner_event_started_at": runner_events.get("coverage_started_at"),
            "runner_snapshot_available": session_snapshot is not None,
        },
    }
    with _lock:
        _cache.clear()
        _cache[key] = copy.deepcopy(report)
    return report
