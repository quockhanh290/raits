"""Build a read-only ledger of unresolved operational issues from retained logs."""
from __future__ import annotations

import copy
import datetime as dt
import json
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


def _num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _reconciles(left: Any, right: Any) -> bool:
    a = _num(left)
    b = _num(right)
    return a is not None and b is not None and abs(a - b) < 0.005


def _paper_reconciliation_issues(root: Path, observed_at: str) -> list[dict[str, Any]]:
    path = root / "monitor" / "paper_pnl_compare.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [_issue(
            key="paper:pnl_compare:unreadable", status="incident", component="paper",
            title="Paper P&L compare unreadable",
            problem=f"The paper P&L compare artifact cannot be parsed: {exc}",
            first_seen=observed_at, last_seen=observed_at, occurrences=1,
            impact="Paper dashboard verdicts may be stale or unavailable.",
            action="Regenerate monitor/paper_pnl_compare.json and confirm the dashboard loads fresh evidence.",
            resolution="The artifact parses successfully and contains current reconciliation data.",
            evidence=str(path),
        )]

    issues: list[dict[str, Any]] = []
    pl = data.get("statement_pnl_compare") or {}
    lifecycle = data.get("lifecycle_compare") or {}
    parity = data.get("open_position_parity") or {}
    signal = data.get("signal_compare") or {}
    classified_signal = signal.get("classified") or {}
    entry = data.get("entry_compare") or {}

    lifecycle_unresolved = int(lifecycle.get("unresolved") or 0)
    if lifecycle_unresolved:
        issues.append(_issue(
            key="paper:lifecycle:unresolved", status="incident", component="paper",
            title="Paper lifecycle reconciliation unresolved",
            problem=f"{lifecycle_unresolved} paper/backtest/Flex lifecycle row(s) are unresolved.",
            first_seen=observed_at, last_seen=observed_at, occurrences=lifecycle_unresolved,
            impact="Paper P&L vs backtest/Flex cannot be promoted to PASS while source rows are missing or unclassified.",
            action="Open Paper Dashboard > Trades and resolve the rows marked BREACH/UNRESOLVED.",
            resolution="Lifecycle compare reports unresolved=0 and table totals reconcile to the P&L grid.",
            evidence="monitor/paper_pnl_compare.json lifecycle_compare.unresolved",
        ))

    if not _reconciles(lifecycle.get("paper_minus_backtest_sum"), pl.get("paper_minus_backtest_realized")):
        issues.append(_issue(
            key="paper:pnl:paper_backtest_total_mismatch", status="incident", component="paper",
            title="Paper vs backtest P&L total mismatch",
            problem="Lifecycle Paper-Backtest total does not reconcile to the headline P&L grid.",
            first_seen=observed_at, last_seen=observed_at, occurrences=1,
            impact="The dashboard cannot prove whether Paper-Backtest variance is explained by trade rows.",
            action="Regenerate the compare artifact or inspect Paper Dashboard > Trades footer totals.",
            resolution="Lifecycle Paper-Backtest sum matches statement_pnl_compare.paper_minus_backtest_realized.",
            evidence=f"lifecycle={lifecycle.get('paper_minus_backtest_sum')} grid={pl.get('paper_minus_backtest_realized')}",
        ))

    flex_grid = pl.get("paper_minus_flex_epoch_rebased_realized", pl.get("paper_minus_statement_entry_epoch_realized"))
    if not _reconciles(lifecycle.get("paper_minus_flex_sum"), flex_grid):
        issues.append(_issue(
            key="paper:pnl:paper_flex_total_mismatch", status="incident", component="paper",
            title="Paper vs Flex P&L total mismatch",
            problem="Lifecycle Paper-Flex total does not reconcile to the zero-base Flex headline grid.",
            first_seen=observed_at, last_seen=observed_at, occurrences=1,
            impact="Paper actual cannot be reconciled against the broker source of truth.",
            action="Refresh Flex data and inspect Paper Dashboard > Trades / Source Diff footers.",
            resolution="Lifecycle Paper-Flex sum matches the zero-base Paper-Flex grid value.",
            evidence=f"lifecycle={lifecycle.get('paper_minus_flex_sum')} grid={flex_grid}",
        ))

    open_diff = len(parity.get("paper_only") or []) + len(parity.get("backtest_only") or [])
    if open_diff:
        issues.append(_issue(
            key="paper:open_position_parity:mismatch", status="incident", component="paper",
            title="Paper open-position parity mismatch",
            problem=f"{open_diff} open position row(s) exist on only one side of paper/backtest parity.",
            first_seen=observed_at, last_seen=observed_at, occurrences=open_diff,
            impact="Closed P&L comparisons may look reconciled while current exposure is not aligned.",
            action="Open Paper Dashboard > Decision and reconcile paper-only/backtest-only open positions.",
            resolution="open_position_parity paper_only and backtest_only are both empty.",
            evidence=f"paper_only={len(parity.get('paper_only') or [])} backtest_only={len(parity.get('backtest_only') or [])}",
        ))

    signal_unresolved = int(classified_signal.get("unresolved") or 0)
    entry_unresolved = int(entry.get("unresolved") or 0)
    if signal_unresolved or entry_unresolved:
        issues.append(_issue(
            key="paper:decision_path:unresolved", status="incident", component="paper",
            title="Paper decision-path reconciliation unresolved",
            problem=f"Signal unresolved={signal_unresolved}, entry unresolved={entry_unresolved}.",
            first_seen=observed_at, last_seen=observed_at, occurrences=signal_unresolved + entry_unresolved,
            impact="P&L divergence cannot be attributed cleanly until signal and entry parity are explained.",
            action="Open Paper Dashboard > Decision and resolve signal/entry mismatch rows.",
            resolution="signal_compare.classified.unresolved and entry_compare.unresolved are both zero.",
            evidence="monitor/paper_pnl_compare.json signal_compare / entry_compare",
        ))

    return issues


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
    observed_at = _iso(stamped_lines[-1][0])
    issues.extend(_paper_reconciliation_issues(paths[0].parent, observed_at))
    issues.sort(key=lambda item: (priority[item["status"]], item["first_seen"]))
    return {
        "source": "scheduler_logs", "observed_at": observed_at,
        "coverage": {"from": first_day.isoformat(), "to": last_day.isoformat()},
        "issues": issues, "error": None,
    }


def read_open_issues(root: Path) -> dict[str, Any]:
    paths = sorted(root.glob("scheduler_*.log"))
    if not paths:
        return {"source": "scheduler_logs", "coverage": None, "issues": [], "error": "scheduler logs not found"}
    signature_paths = list(paths)
    paper_compare = root / "monitor" / "paper_pnl_compare.json"
    if paper_compare.exists():
        signature_paths.append(paper_compare)
    signature = tuple((str(path.resolve()), path.stat().st_mtime_ns, path.stat().st_size) for path in signature_paths)
    with _lock:
        cached = _cache.get(signature)
        if cached is None:
            cached = _build(paths)
            _cache.clear()
            _cache[signature] = cached
        return copy.deepcopy(cached)
