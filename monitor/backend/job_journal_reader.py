"""Read-only extraction of scheduler jobs and their operational details."""
from __future__ import annotations

import copy
import datetime as dt
import re
import threading
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from monitor.backend.session_event_reader import read_session_events

LOCAL_TZ = ZoneInfo("America/Edmonton")
ET = ZoneInfo("America/New_York")
_LINE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<level>\S+)\s+(?P<logger>\S+)\s+(?:-|—)\s+(?P<message>.*)$"
)
_JOB = re.compile(r"^\[(?P<job_id>[A-Z0-9_]+)]\s+(?P<detail>.*)$")
_MISSED_JOB = re.compile(
    r'Run time of job "(?P<name>.+?) \(trigger:.*" '
    r'was missed by (?P<hours>\d+):(?P<minutes>\d{2}):(?P<seconds>[\d.]+)'
)
_lock = threading.Lock()
_cache: dict[tuple[str, int, int], dict[str, Any]] = {}


def _iso(stamp: str) -> str:
    local = dt.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
    return local.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _job_type(job_id: str) -> str:
    if job_id.startswith("LIVE_DAY"):
        return "live_day"
    if job_id.startswith("NKD_NIGHT"):
        return "nkd_night"
    if job_id.startswith("STOP_REPAIR"):
        return "stop_repair"
    if job_id.startswith("MAX_HOLD"):
        return "max_hold"
    if job_id == "PREFLIGHT":
        return "preflight"
    if job_id == "SESSION_REPORT":
        return "session_report"
    return "other"


def _job_id_from_name(name: str) -> str | None:
    timed = re.search(r"(?P<hour>\d{2}):(?P<minute>\d{2}) ET$", name)
    suffix = f"{timed.group('hour')}{timed.group('minute')}" if timed else None
    if name.startswith("Stop repair sweep ") and suffix:
        return f"STOP_REPAIR_{suffix}"
    if name.startswith("NKD night run ") and suffix:
        return f"NKD_NIGHT_{suffix}"
    if (name.startswith("Continuous run ") or name.startswith("Daily run ")) and suffix:
        return f"LIVE_DAY_{suffix}"
    if name.startswith("MAX_HOLD exit"):
        return "MAX_HOLD_EXIT"
    if name.startswith("Pre-flight update"):
        return "PREFLIGHT"
    if name.startswith("Bao cao phien"):
        return "SESSION_REPORT"
    return None


def _new_job(job_id: str, started_at: str) -> dict[str, Any]:
    return {
        "id": f"{job_id}:{started_at}", "job_id": job_id, "job_type": _job_type(job_id),
        "started_at": started_at, "ended_at": None, "duration_seconds": None,
        "status": "running", "reason": None, "diagnostics": [], "events": [],
    }


def _finish(job: dict[str, Any], ended_at: str, status: str, reason: str | None = None) -> None:
    job["ended_at"] = ended_at
    job["status"] = status
    job["reason"] = reason
    started, ended = _parse_iso(job["started_at"]), _parse_iso(ended_at)
    if started and ended:
        job["duration_seconds"] = max(0, round((ended - started).total_seconds()))


def _annotate_impact_and_action(jobs: list[dict[str, Any]]) -> None:
    """Add conservative operator guidance derived only from observed job evidence."""
    ordered = sorted(jobs, key=lambda item: item["started_at"])
    for index, job in enumerate(ordered):
        diagnostics = "\n".join(job.get("diagnostics", [])).lower()
        later_same_stream = next((
            candidate for candidate in ordered[index + 1:]
            if candidate["job_type"] == job["job_type"]
            and candidate["status"] in {"completed", "completed_with_debt"}
            and not any("dump_state" in item.lower() for item in candidate.get("diagnostics", []))
        ), None)

        if "dump_state" in diagnostics or "live_state_data" in diagnostics:
            recovery = (
                f" Publication resumed at {later_same_stream['job_id']}; this incident is recovered."
                if later_same_stream else " No later successful publication is visible in this journal yet."
            )
            job["impact"] = (
                "The runner-state snapshot for this slot was not published; dashboard runner data may "
                f"remain on the previous snapshot.{recovery}"
            )
            job["action"] = (
                "No trading action is indicated by this error. Verify the next runner-state publication; "
                "if it repeats, investigate which process is holding live_state_data.js."
            )
        elif job["status"] == "missed":
            if job["job_type"] == "stop_repair":
                if later_same_stream:
                    job["lifecycle_status"] = "recovered"
                    job["recovered_at"] = later_same_stream.get("ended_at") or later_same_stream.get("started_at")
                    job["impact"] = (
                        "The scheduled stop-repair inspection did not run at this slot; "
                        f"inspection resumed when {later_same_stream['job_id']} completed."
                    )
                    job["action"] = "No immediate action. The missed slot remains in daily history; review only if a later sweep fails or broker protection is not reconciled."
                else:
                    job["lifecycle_status"] = "open"
                    job["impact"] = "The scheduled stop-repair inspection did not run; protection was not rechecked by this slot."
                    job["action"] = "Review current broker positions and working stops, then check scheduler health before the next slot."
            elif job["job_type"] in {"live_day", "nkd_night"}:
                job["impact"] = "The scheduled decision run did not execute; this slot produced no decision or runner-state update."
                job["action"] = "Check scheduler health and confirm the next expected decision slot runs."
            else:
                job["impact"] = "The scheduled job did not run; its intended check or output is absent for this slot."
                job["action"] = "Review scheduler health and confirm the next expected run."
        elif job["status"] == "failed" and job["job_type"] == "preflight":
            job["impact"] = "The input gate failed; scheduled Live Day decision slots will be blocked until fresh IBKR and SPY data are confirmed."
            job["action"] = "Fix the failed input update, rerun the required update manually, and confirm both data sources are fresh before Live Day."
        elif job["status"] == "failed":
            job["impact"] = "The job emitted an unclassified error; completion and operational effects cannot be confirmed from this evidence."
            job["action"] = "Review the diagnostics below and reconcile current broker state before taking operational action."
        elif job["status"] == "completed_with_debt":
            job["impact"] = "The job completed, but a known diagnostic remains active; no new incident is established by this evidence."
            job["action"] = "Keep the diagnostic in the known-debt lane and follow its existing remediation decision."
        elif job["status"] == "skipped":
            job["impact"] = "This slot was skipped with scheduler evidence; no independent run or state publication was expected from it."
            job["action"] = "No action unless the next expected slot is also absent."
        elif job["status"] == "completed":
            job["impact"] = "The job completed; no operational failure is present in the scheduler evidence."
            job["action"] = "No action."
        else:
            job["impact"] = "The job has started, but completion evidence is not available yet."
            job["action"] = "Observe until completion evidence arrives; investigate only if it exceeds its expected runtime."


def _parse(paths: list[Path], day: str, session_events: list[dict[str, Any]]) -> dict[str, Any]:
    jobs: list[dict[str, Any]] = []
    active: dict[str, dict[str, Any]] = {}
    monitor_events: list[dict[str, Any]] = []
    pending_stall_at: str | None = None
    raw_lines: list[str] = []
    for path in paths:
        raw_lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
    for raw in raw_lines:
        line = _LINE.match(raw)
        if not line:
            continue
        stamp, level, message = line.group("stamp"), line.group("level"), line.group("message")
        timestamp = _iso(stamp)
        missed = _MISSED_JOB.search(message)
        if missed:
            lag = dt.timedelta(
                hours=int(missed.group("hours")), minutes=int(missed.group("minutes")),
                seconds=float(missed.group("seconds")),
            )
            job_id = _job_id_from_name(missed.group("name"))
            if job_id is None:
                monitor_events.append({"ts": timestamp, "kind": "scheduler_job_missed", "level": "critical", "message": message})
                continue
            detected = _parse_iso(timestamp)
            detected_et = detected.astimezone(ET)
            timed = re.search(r"(?P<hour>\d{2}):(?P<minute>\d{2}) ET$", missed.group("name"))
            scheduled = (detected_et.replace(
                hour=int(timed.group("hour")), minute=int(timed.group("minute")), second=0, microsecond=0,
            ) if timed else detected_et - lag).astimezone(dt.timezone.utc)
            job = _new_job(job_id, scheduled.isoformat().replace("+00:00", "Z"))
            _finish(job, timestamp, "missed", f"scheduler missed slot by {round(lag.total_seconds())}s")
            jobs.append(job)
            continue

        upper = message.upper()
        if "[PRE-FLIGHT]" in upper and "STARTING:" in upper:
            job = _new_job("PREFLIGHT", timestamp)
            job["events"].append({
                "ts": timestamp, "kind": "preflight_started", "level": "INFO",
                "category": "PREFLIGHT", "message": "Pre-flight input validation started.",
            })
            jobs.append(job)
            active["PREFLIGHT"] = job
            monitor_events.append({
                "ts": timestamp, "kind": "preflight_started", "level": "info",
                "category": "PREFLIGHT", "component": "scheduler",
                "message": "IBKR and SPY input updates started.",
            })
            continue

        preflight = active.get("PREFLIGHT")
        stage = "ibkr" if "[IBKR_UPDATE]" in upper else "spy" if "[SPY_UPDATE]" in upper else None
        if preflight and stage:
            label = "IBKR market data" if stage == "ibkr" else "SPY regime data"
            if "COMPLETED OK" in upper:
                kind = f"preflight_{stage}_completed"
                event = {"ts": timestamp, "kind": kind, "level": "INFO", "category": "PREFLIGHT", "message": f"{label} update completed."}
                preflight["events"].append(event)
                monitor_events.append({**event, "level": "info", "component": "scheduler"})
            elif "EXITED WITH CODE" in upper:
                code = re.search(r"exited with code\s+(\d+)", message, re.IGNORECASE)
                detail = f"{label} update exited with code {code.group(1) if code else 'unknown'}."
                preflight["events"].append({"ts": timestamp, "kind": f"preflight_{stage}_failed", "level": "ERROR", "category": "PREFLIGHT", "message": detail})
                preflight["diagnostics"].append(detail)
                preflight["status"] = "failed"
                preflight["reason"] = f"{stage}_update_failed"
            elif "PYTHON" in upper:
                kind = f"preflight_{stage}_started"
                event = {"ts": timestamp, "kind": kind, "level": "INFO", "category": "PREFLIGHT", "message": f"{label} update started."}
                preflight["events"].append(event)
                monitor_events.append({**event, "level": "info", "component": "scheduler"})
            continue

        if "[PRE-FLIGHT]" in upper and " OK " in f" {upper} ":
            if preflight:
                event = {"ts": timestamp, "kind": "preflight_passed", "level": "INFO", "category": "PREFLIGHT", "message": "IBKR and SPY inputs are fresh; Live Day gate cleared."}
                preflight["events"].append(event)
                monitor_events.append({**event, "level": "info", "component": "scheduler"})
                _finish(preflight, timestamp, "completed")
                active.pop("PREFLIGHT", None)
            continue

        if "[PRE-FLIGHT]" in upper and "FAILED" in upper:
            if preflight is None:
                preflight = _new_job("PREFLIGHT", timestamp)
                jobs.append(preflight)
            failed_stage = "IBKR market data" if "IBKR" in upper else "SPY regime data" if "SPY" in upper else "Input update"
            detail = f"{failed_stage} update failed; Live Day gate remains closed."
            if detail not in preflight["diagnostics"]:
                preflight["diagnostics"].append(detail)
            preflight["events"].append({"ts": timestamp, "kind": "preflight_failed", "level": "ERROR", "category": "PREFLIGHT", "message": detail})
            _finish(preflight, timestamp, "failed", preflight.get("reason") or "input_update_failed")
            active.pop("PREFLIGHT", None)
            continue

        tagged = _JOB.match(message)
        if tagged:
            job_id, detail = tagged.group("job_id"), tagged.group("detail")
            current = active.get(job_id)
            if ("python" in detail.lower() or detail.startswith("SKIPPED")) and "completed OK" not in detail:
                if detail.startswith("SKIPPED"):
                    current = _new_job(job_id, timestamp)
                    jobs.append(current)
                    _finish(current, timestamp, "skipped", "mutex" if "previous" in detail.lower() else "scheduler")
                else:
                    current = _new_job(job_id, timestamp)
                    jobs.append(current)
                    active[job_id] = current
                continue
            if current and "completed OK" in detail:
                _finish(current, timestamp, "completed")
                active.pop(job_id, None)
                continue
            if current and ("thoat OK nhung" in detail or "exited OK but" in detail):
                _finish(current, timestamp, "completed_with_debt", "child_logged_error")
                continue
            if current and "exited with code" in detail.lower():
                _finish(current, timestamp, "failed", detail)
                active.pop(job_id, None)
                continue
            if current and level in {"ERROR", "CRITICAL"}:
                current["diagnostics"].append(detail)
                if "G2 HARD" not in detail:
                    current["status"] = "failed"
                    current["reason"] = "child_error"
                continue

        if "[HEARTBEAT] STALLED" in upper:
            monitor_events.append({"ts": timestamp, "kind": "scheduler_stalled", "level": "critical", "message": message})
            pending_stall_at = timestamp
        elif "[HEARTBEAT] ALIVE" in upper and pending_stall_at:
            monitor_events.append({
                "ts": timestamp, "kind": "scheduler_recovered", "level": "info",
                "message": "Scheduler heartbeat resumed", "stalled_at": pending_stall_at,
            })
            pending_stall_at = None
        elif "PRE-FLIGHT" in upper and "SKIP" in upper:
            monitor_events.append({"ts": timestamp, "kind": "preflight_skip", "level": "warn", "message": message})
        elif "SCHEDULER STARTED" in upper:
            monitor_events.append({"ts": timestamp, "kind": "scheduler_started", "level": "info", "message": "Scheduler started"})

    for job in active.values():
        if job["ended_at"] is None:
            job["reason"] = "no completion evidence"

    jobs = [job for job in jobs if _parse_iso(job["started_at"]).astimezone(ET).date().isoformat() == day]
    monitor_events = [event for event in monitor_events if _parse_iso(event["ts"]).astimezone(ET).date().isoformat() == day]

    for event in session_events:
        event_at = _parse_iso(event.get("ts"))
        if event_at is None:
            continue
        candidates = []
        for job in jobs:
            start = _parse_iso(job["started_at"])
            end = _parse_iso(job["ended_at"]) or (start + dt.timedelta(minutes=15) if start else None)
            if start and end and start <= event_at <= end + dt.timedelta(seconds=2):
                candidates.append(job)
        if candidates:
            candidates[-1]["events"].append(event)

    for job in jobs:
        counts: dict[str, int] = {}
        for event in job["events"]:
            counts[event["kind"]] = counts.get(event["kind"], 0) + 1
        job["event_counts"] = counts
    _annotate_impact_and_action(jobs)
    deduped_monitor: list[dict[str, Any]] = []
    seen_monitor: set[tuple[str, str]] = set()
    for event in monitor_events:
        key = (event["kind"], event["ts"])
        if key not in seen_monitor:
            deduped_monitor.append(event)
            seen_monitor.add(key)
    observed = dt.datetime.fromtimestamp(max(path.stat().st_mtime for path in paths), tz=dt.timezone.utc)
    return {
        "source": "scheduler_log", "day": day,
        "observed_at": observed.isoformat().replace("+00:00", "Z"),
        "jobs": jobs, "monitor_events": deduped_monitor, "error": None,
    }


def read_job_journal(day: str, root: Path) -> dict[str, Any]:
    parsed_day = dt.date.fromisoformat(day)
    # A trading day is Eastern Time while log files roll at midnight in Edmonton.
    # The 01:10-01:55 ET NKD window therefore lives in the prior local-date file.
    candidates = [
        root / f"scheduler_{parsed_day - dt.timedelta(days=1):%m%d}.log",
        root / f"scheduler_{parsed_day:%m%d}.log",
    ]
    paths = [path for path in candidates if path.exists()]
    if not paths:
        return {"source": "scheduler_log", "day": day, "observed_at": None,
                "jobs": [], "monitor_events": [], "error": "scheduler logs not found"}
    signature = tuple((str(path.resolve()), path.stat().st_mtime_ns, path.stat().st_size) for path in paths)
    key = (day, hash(signature), sum(item[2] for item in signature))
    with _lock:
        cached = _cache.get(key)
        if cached is None:
            events = read_session_events(day, root).get("events", [])
            cached = _parse(paths, day, events)
            _cache.clear()
            _cache[key] = cached
        return copy.deepcopy(cached)
