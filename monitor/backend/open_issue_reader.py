"""Build a read-only ledger of unresolved operational issues from retained logs."""
from __future__ import annotations

import copy
import datetime as dt
import re
import threading
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from monitor.backend.job_journal_reader import read_job_journal

LOCAL_TZ = ZoneInfo("America/Edmonton")
ET = ZoneInfo("America/New_York")
_STAMP = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_lock = threading.Lock()
_cache: dict[tuple[tuple[str, int, int], ...], dict[str, Any]] = {}


def _parse_stamp(raw: str) -> dt.datetime | None:
    match = _STAMP.match(raw)
    if not match:
        return None
    return dt.datetime.strptime(match.group("stamp"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)


def _parse_iso(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _stream(job: dict[str, Any]) -> str:
    return job["job_type"] if job["job_type"] != "other" else job["job_id"]


def _issue(*, key: str, status: str, component: str, title: str, problem: str,
           first_seen: str, last_seen: str,
           occurrences: int, impact: str, action: str, resolution: str,
           evidence: str) -> dict[str, Any]:
    return {
        "key": key, "status": status, "component": component,
        "title": title, "problem": problem,
        "first_seen": first_seen, "last_seen": last_seen, "occurrences": occurrences,
        "impact": impact, "action": action, "resolution_evidence": resolution,
        "evidence": evidence,
    }


def _build(paths: list[Path]) -> dict[str, Any]:
    stamped_lines: list[tuple[dt.datetime, str]] = []
    for path in paths:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stamped = _parse_stamp(raw)
            if stamped:
                stamped_lines.append((stamped, raw))
    stamped_lines.sort(key=lambda item: item[0])
    if not stamped_lines:
        return {"source": "scheduler_logs", "coverage": None, "issues": [], "error": "no timestamped scheduler evidence"}

    first_day = stamped_lines[0][0].astimezone(ET).date()
    last_day = max(stamped_lines[-1][0].astimezone(ET).date(), dt.datetime.now(ET).date())
    jobs: list[dict[str, Any]] = []
    monitor_events: list[dict[str, Any]] = []
    day = first_day
    while day <= last_day:
        journal = read_job_journal(day.isoformat(), paths[0].parent)
        jobs.extend(journal.get("jobs", []))
        monitor_events.extend(journal.get("monitor_events", []))
        day += dt.timedelta(days=1)
    jobs = list({job["id"]: job for job in jobs}.values())
    jobs.sort(key=lambda item: item["started_at"])

    issues: list[dict[str, Any]] = []
    g2 = [
        (job, diagnostic) for job in jobs for diagnostic in job.get("diagnostics", [])
        if "G2 HARD" in diagnostic
    ]
    if g2:
        latest_g2 = g2[-1][1]
        age = re.search(r"model (?P<months>\d+) months old \(fit_end=(?P<fit_end>\d{4}-\d{2}-\d{2})\)", latest_g2)
        problem = (
            f"HMM fit ended {age.group('fit_end')} and is {age.group('months')} months old; G2 HARD remains active."
            if age else "The runner continues to emit G2 HARD because the HMM model age exceeds its hard limit."
        )
        issues.append(_issue(
            key="known_debt:model_age", status="known_debt", component="runner",
            title="Model age remains HARD stale", problem=problem,
            first_seen=g2[0][0]["started_at"], last_seen=g2[-1][0].get("ended_at") or g2[-1][0]["started_at"],
            occurrences=len(g2),
            impact="The stale-model guard remains active. The runner continues trading, so this is debt rather than a newly inferred trading halt.",
            action="Keep out of the new-incident lane and complete the separately approved model re-freeze decision.",
            resolution="A later runner observation reports model age OK; absence of another log line is not enough.",
            evidence=g2[-1][1],
        ))

    now = dt.datetime.now(dt.timezone.utc)
    unresolved: list[dict[str, Any]] = []
    for index, job in enumerate(jobs):
        status = job.get("status")
        if status not in {"failed", "missed", "running"}:
            continue
        # MAXHOLD is a legacy catch-up/test tag, not a scheduled execution ID.
        # It has appeared in retained logs during pytest runs and cannot support
        # a production issue without a matching MAX_HOLD_EXIT execution.
        if job["job_id"] == "MAXHOLD":
            continue
        started = _parse_iso(job.get("started_at"))
        if status == "running" and started and (now - started).total_seconds() < 20 * 60:
            continue
        later_recovery = next((
            candidate for candidate in jobs[index + 1:]
            if (_stream(candidate) == _stream(job)
                or (job["job_id"] == "PREFLIGHT" and candidate["job_type"] in {"live_day", "nkd_night"}))
            and candidate.get("status") in {"completed", "completed_with_debt"}
            and not any("dump_state" in item.lower() for item in candidate.get("diagnostics", []))
        ), None)
        if later_recovery:
            continue
        unresolved.append(job)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for job in unresolved:
        grouped.setdefault((_stream(job), job["status"]), []).append(job)

    for (_, _), group in grouped.items():
        job = group[-1]
        status = "unknown" if job["status"] == "running" else "incident"
        diagnostics = [item for item in job.get("diagnostics", []) if "G2 HARD" not in item]
        component = "runner" if diagnostics else "scheduler"
        if job["status"] == "missed" and job["job_type"] == "stop_repair":
            problem = f"The scheduled stop-repair sweep did not run; latest evidence says {job.get('reason') or 'slot missed'}."
        elif diagnostics and "dump_state" in diagnostics[-1]:
            problem = "The runner completed its work but could not publish live_state_data.js for this slot."
        elif diagnostics:
            problem = f"The runner emitted an unresolved error during {job['job_id']}: {diagnostics[-1]}"
        elif job["job_id"] == "SESSION_REPORT" and job["status"] == "failed":
            problem = f"The scheduled session-report process exited unsuccessfully on {len(group)} retained run(s)."
        elif job["status"] == "running":
            problem = f"{job['job_id']} started but has no completion evidence after its expected runtime."
        else:
            problem = f"{job['job_id']} did not complete successfully: {job.get('reason') or 'no failure detail emitted'}."
        issues.append(_issue(
            key=f"job:{_stream(job)}:{job['status']}", status=status, component=component,
            title=f"{job['job_id']} {job['status'].upper()}", problem=problem,
            first_seen=group[0]["started_at"], last_seen=job.get("ended_at") or job["started_at"], occurrences=len(group),
            impact=job.get("impact") or "Operational impact is not classified from retained evidence.",
            action=job.get("action") or "Review the job evidence and current system state.",
            resolution=(
                f"A later {_stream(job)} run completes with clean evidence."
                if job["status"] != "running" else "Completion evidence arrives for this execution."
            ),
            evidence=job.get("reason") or ((job.get("diagnostics") or ["No completion evidence"])[-1]),
        ))

    stalled = [event for event in monitor_events if event.get("kind") == "scheduler_stalled"]
    if stalled:
        latest = stalled[-1]
        latest_at = _parse_iso(latest["ts"])
        heartbeat_recovered = any(
            stamp > latest_at and "[HEARTBEAT] ALIVE" in raw.upper()
            for stamp, raw in stamped_lines if latest_at
        )
        job_recovered = any(
            (_parse_iso(job.get("ended_at")) or _parse_iso(job.get("started_at"))) > latest_at
            and job.get("status") in {"completed", "completed_with_debt"}
            for job in jobs if latest_at
        )
        if not (heartbeat_recovered or job_recovered):
            issues.append(_issue(
                key="incident:scheduler_stalled", status="incident", component="scheduler",
                title="Scheduler heartbeat stalled",
                problem="The scheduler heartbeat stopped advancing and jobs due during that interval may have been missed.",
                first_seen=stalled[0]["ts"], last_seen=latest["ts"], occurrences=len(stalled),
                impact="Jobs due during the stalled interval may not have run.",
                action="Check scheduler process health and confirm the next expected job executes.",
                resolution="A later heartbeat reports alive, or a later scheduled job completes.",
                evidence=latest["message"],
            ))

    priority = {"incident": 0, "unknown": 1, "known_debt": 2}
    issues.sort(key=lambda item: (priority[item["status"]], item["first_seen"]))
    return {
        "source": "scheduler_logs", "observed_at": _iso(stamped_lines[-1][0]),
        "coverage": {"from": first_day.isoformat(), "to": last_day.isoformat()},
        "issues": issues, "error": None,
    }


def read_open_issues(root: Path) -> dict[str, Any]:
    paths = sorted(root.glob("scheduler_*.log"))
    if not paths:
        return {"source": "scheduler_logs", "coverage": None, "issues": [], "error": "scheduler logs not found"}
    signature = tuple((str(path.resolve()), path.stat().st_mtime_ns, path.stat().st_size) for path in paths)
    with _lock:
        cached = _cache.get(signature)
        if cached is None:
            cached = _build(paths)
            _cache.clear()
            _cache[signature] = cached
        return copy.deepcopy(cached)
