"""Read-only schedule evidence and schedule-relative runner freshness."""
from __future__ import annotations

import datetime as dt
import re
import threading
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from global_index.session_report import _is_test_line, _to_et
from raits.live.trading_calendar import is_trading_day

ET = ZoneInfo("America/New_York")

_SCHEDULER_CMD = "global_index.run_scheduler"


def _running_schedulers() -> list[dict[str, Any]]:
    """Live run_scheduler processes as {pid, started_epoch}. Empty if psutil cannot say.

    Read-only, like the rest of this backend: it enumerates, it never signals.
    """
    try:
        import psutil
    except ImportError:
        return []
    found = []
    for proc in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or ())
        except Exception:
            continue
        if _SCHEDULER_CMD in cmdline:
            found.append({"pid": proc.info.get("pid"),
                          "started_epoch": proc.info.get("create_time")})
    return found


def scheduler_process_state(
    *,
    code_path: Path | None = None,
    processes: list[dict[str, Any]] | None = None,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """How old the running scheduler is, and whether it predates its own source.

    Age on its own says nothing — a scheduler up for three days is healthy if nothing
    changed. The failure on 2026-08-16 needed the comparison: the process started
    13/8 04:30 while its cron table was rewritten 15/8 01:10, so the Sunday sweep
    committed that day did not exist in the running instance. Twenty-one restarts went
    past without anyone noticing, because every signal on screen said "running".

    `stale_code` is None when nothing is running. Nothing running is a different
    problem, and answering False there would assert that the live instance is current.
    """
    import os as _os

    code = Path(code_path) if code_path else (
        Path(__file__).resolve().parents[2] / "global_index" / "run_scheduler.py")
    now = float(now_epoch) if now_epoch is not None else dt.datetime.now().timestamp()
    procs = _running_schedulers() if processes is None else processes

    try:
        code_mtime = _os.path.getmtime(code)
    except OSError:
        code_mtime = None

    if not procs:
        return {"running": False, "pid": None, "started_at": None, "age_seconds": None,
                "code_mtime": _iso_epoch(code_mtime), "stale_code": None,
                "process_count": 0}

    # Oldest wins: with duplicates, the stale one is the dangerous one.
    oldest = min(procs, key=lambda p: p.get("started_epoch") or 0)
    started = oldest.get("started_epoch")
    return {
        "running": True,
        "pid": oldest.get("pid"),
        "started_at": _iso_epoch(started),
        "age_seconds": int(now - started) if started else None,
        "code_mtime": _iso_epoch(code_mtime),
        "stale_code": (bool(started < code_mtime)
                       if started and code_mtime else None),
        "process_count": len(procs),
    }


def _iso_epoch(value: float | None) -> str | None:
    if not value:
        return None
    return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).astimezone(ET).isoformat(timespec="seconds")
_LOG_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\s+(\w+)")

R4_SLOTS = [(14, 5)] + [(14, minute) for minute in range(10, 60, 5)] + [
    (15, minute) for minute in range(0, 60, 5)
]
NKD_SLOTS = [(1, minute) for minute in range(10, 60, 5)] + [
    (2, minute) for minute in range(0, 60, 5)
]
STATE_SLOTS = tuple(NKD_SLOTS + R4_SLOTS)
PIPELINE_FIXED_SLOTS = (
    ("MAX_HOLD_EXIT", 9, 31),
    ("PREFLIGHT", 13, 45),
)
STOP_REPAIR_SLOTS = tuple(
    (hour, 20) for hour in range(0, 24, 2)
    if hour not in (2, 14)
)
# (weekday, hour, minute) — Chủ nhật là 6 theo date.weekday(). Phải khớp
# run_scheduler.py: cron day_of_week="sun", hour=18, minute=30.
SUNDAY_REPAIR_SLOT = (6, 18, 30)
# Bao lâu một snapshot được phép cũ hơn slot due gần nhất trước khi bị gọi là stale.
# Đây là tuổi của CHÍNH snapshot, không phải deadline của slot: slot chạy mỗi 5 phút
# nên "latest_slot + allowance" luôn nằm ở tương lai suốt active window và không bao
# giờ trôi qua — neo vào đó thì một file 90 ngày tuổi vẫn ra "fresh", đúng cái lỗ
# C2 cần bịt. 20 phút ≈ 4 slot liên tiếp không ghi được state: đủ rộng để không báo
# nhầm khi một slot đang chạy, đủ hẹp để dump_state fail âm thầm không lọt.
STATE_STALE_ALLOWANCE_SECONDS = 20 * 60

# Cách scheduler viết một dòng đóng. Hai reader từng giữ hai bộ chuỗi riêng nên
# một dòng "thoat OK" TRẦN được rail coi là executed trong khi Job Journal để job
# kẹt `running` vĩnh viễn — cùng hình dạng lỗi với H1, chỉ ở tầng chuỗi.
# (REALTIME_DASHBOARD_AUDIT.md L7)
CLEAN_EXIT_TOKENS = ("completed ok", "thoat ok")
# Dòng có debt CHỨA token sạch làm tiền tố ("thoat OK nhung ..."), nên nơi nào cần
# phân biệt hai loại thì phải kiểm bộ này TRƯỚC. Nơi nào chỉ cần biết "job đã kết
# thúc chưa" — như _evidence dưới đây — thì cả hai đều là đã kết thúc, và giữ đúng
# như vậy: _annotate_incident_lifecycle dựa vào state == "executed" để phát hiện
# phục hồi, nên loại dòng debt ra khỏi "executed" sẽ làm mất trạng thái recovered.
DEBT_EXIT_TOKENS = ("thoat ok nhung", "exited ok but")


def is_clean_exit(detail: str) -> bool:
    """Dòng báo tiến trình con đã thoát bình thường, kể cả khi có debt kèm theo."""
    return any(token in str(detail).lower() for token in CLEAN_EXIT_TOKENS)


def is_debt_exit(detail: str) -> bool:
    """Thoát bình thường NHƯNG con đã ghi CRITICAL/ERROR."""
    return any(token in str(detail).lower() for token in DEBT_EXIT_TOKENS)


_cache_lock = threading.Lock()
_log_cache: dict[tuple[str, str, tuple[tuple[str, int, int], ...]], list[str]] = {}


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _slot_id(hour: int, minute: int) -> str:
    if hour < 3:
        return f"NKD_NIGHT_{hour:02d}{minute:02d}"
    return f"LIVE_DAY_{hour:02d}{minute:02d}"


def _slots_for(day: dt.date) -> list[dict[str, Any]]:
    if not is_trading_day(day):
        return []
    out = []
    for hour, minute in STATE_SLOTS:
        at = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=ET)
        final = (hour, minute) in ((2, 55), (15, 55))
        out.append({
            "id": _slot_id(hour, minute),
            "at": at,
            "allowance_seconds": 15 * 60 if final else 8 * 60,
        })
    return sorted(out, key=lambda item: item["at"])


def _pipeline_slots_for(day: dt.date) -> list[dict[str, Any]]:
    """Decision-producing slots and the gates that directly precede them."""
    if not is_trading_day(day):
        return []
    slots = [
        {"id": _slot_id(hour, minute), "at": dt.datetime.combine(day, dt.time(hour, minute), tzinfo=ET)}
        for hour, minute in STATE_SLOTS
    ]
    slots.extend({
        "id": job_id,
        "at": dt.datetime.combine(day, dt.time(hour, minute), tzinfo=ET),
    } for job_id, hour, minute in PIPELINE_FIXED_SLOTS)
    return sorted(slots, key=lambda item: item["at"])


def _scheduled_slots_for(day: dt.date) -> list[dict[str, Any]]:
    """Timed operational jobs, excluding heartbeat and dependent session reports."""
    slots = _pipeline_slots_for(day)
    slots.extend({
        "id": f"STOP_REPAIR_{hour:02d}{minute:02d}",
        "at": dt.datetime.combine(day, dt.time(hour, minute), tzinfo=ET),
    } for hour, minute in STOP_REPAIR_SLOTS if is_trading_day(day))
    # Chủ nhật KHÔNG phải trading day nên vòng trên bỏ qua nó — nhưng scheduler thật
    # có một sweep lúc 18:30 ET, ngay sau khi CME mở lại, để 6 tiếng rưỡi đầu phiên
    # không trôi qua mà không lượt kiểm bảo vệ nào (run_scheduler.py, day_of_week="sun").
    # Không mirror ở đây thì dashboard coi nó là slot lạ và dựng incident giả mỗi tuần.
    if day.weekday() == SUNDAY_REPAIR_SLOT[0]:
        slots.append({
            "id": "STOP_REPAIR_SUN_1830",
            "at": dt.datetime.combine(day, dt.time(*SUNDAY_REPAIR_SLOT[1:]), tzinfo=ET),
        })
    return sorted(slots, key=lambda item: item["at"])


def _nearby_slots(now_et: dt.datetime) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for offset in range(-7, 9):
        slots.extend(_slots_for(now_et.date() + dt.timedelta(days=offset)))
    return sorted(slots, key=lambda item: item["at"])


def _next_job(now_et: dt.datetime, slots_for_day) -> dict[str, Any] | None:
    for offset in range(0, 9):
        for slot in slots_for_day(now_et.date() + dt.timedelta(days=offset)):
            if slot["at"] > now_et:
                return {"job_id": slot["id"], "at": _iso(slot["at"])}
    return None


def _log_signature(root: Path) -> tuple[tuple[str, int, int], ...]:
    values = []
    for path in sorted(root.glob("scheduler*.log")):
        try:
            stat = path.stat()
        except OSError:
            continue
        values.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size))
    return tuple(values)


def _scheduler_lines(day: dt.date, root: Path) -> list[str]:
    signature = _log_signature(root)
    key = (str(root.resolve()), day.isoformat(), signature)
    with _cache_lock:
        cached = _log_cache.get(key)
        if cached is not None:
            return list(cached)

    kept: list[tuple[str, str]] = []
    for filename, _mtime, _size in signature:
        path = Path(filename)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            match = _LOG_TS.match(line)
            if not match:
                continue
            et_day, et_time = _to_et(match.group(1), match.group(2))
            if et_day != day.isoformat() or _is_test_line(line, day.isoformat()):
                continue
            kept.append((et_time, line))
    kept.sort(key=lambda item: item[0])
    lines = [line for _time, line in kept]
    with _cache_lock:
        _log_cache.clear()
        _log_cache[key] = list(lines)
    return lines


def _evidence(
    slot: dict[str, Any],
    root: Path,
    lines: list[str] | None = None,
) -> dict[str, Any]:
    marker = f"[{slot['id']}]"
    matched = [
        line for line in (lines if lines is not None else _scheduler_lines(slot["at"].date(), root))
        if marker in line
    ]
    joined = "\n".join(matched).lower()
    base = {
        "state": "not_observed",
        "reason": "unknown",
        "severity": "watch",
        "slot_at": _iso(slot["at"]),
        "slot_id": slot["id"],
        "detail": matched[-1] if matched else None,
    }
    if "skipped" in joined:
        if "previous run_live_day still in flight" in joined:
            reason, severity = "mutex", "expected"
        elif "pre-flight" in joined:
            reason, severity = "preflight", "incident"
        elif "misfire" in joined:
            reason, severity = "misfire", "incident"
        else:
            reason, severity = "unknown", "watch"
        return {**base, "state": "skipped", "reason": reason, "severity": severity}
    if "exited with code" in joined:
        return {**base, "state": "failed", "reason": "exception", "severity": "incident"}
    if is_clean_exit(joined):
        return {**base, "state": "executed", "reason": "none", "severity": "none"}
    return base


def _stream_of(slot_id: str | None) -> str:
    """LIVE_DAY_1415 -> LIVE_DAY. Same grouping run_scheduler uses for its own slot families."""
    return str(slot_id or "").rsplit("_", 1)[0]


def _annotate_incident_lifecycle(incidents: list[dict], due_evidence: list[tuple]) -> None:
    """Mark each incident recovered when a LATER slot of the same sleeve executed cleanly.

    Same-sleeve only: NKD running at 02:30 says nothing about whether the afternoon basket
    is healthy. They are different processes against different instruments.
    """
    for incident in incidents:
        stream = _stream_of(incident["slot_id"])
        recovered_by = None
        for _slot, evidence in due_evidence:
            if (
                evidence["state"] == "executed"
                and _stream_of(evidence["slot_id"]) == stream
                and str(evidence["slot_at"] or "") > str(incident["slot_at"] or "")
            ):
                # First clean slot after the failure, not the most recent one: this names the
                # moment the stream came back, which is what "recovered at" has to mean.
                recovered_by = evidence["slot_id"]
                break
        incident["lifecycle"] = "recovered" if recovered_by else "open"
        incident["recovered_by"] = recovered_by


def get_schedule_status(
    root: Path,
    observed_at: dt.datetime | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    server_now = now or dt.datetime.now(dt.timezone.utc)
    if server_now.tzinfo is None:
        server_now = server_now.replace(tzinfo=dt.timezone.utc)
    now_et = server_now.astimezone(ET)
    slots = _nearby_slots(now_et)
    due = [slot for slot in slots if slot["at"] <= now_et]
    future = [slot for slot in slots if slot["at"] > now_et]
    latest = due[-1] if due else None
    next_slot = future[0] if future else None

    trading_today = is_trading_day(now_et.date())
    todays_slots = _slots_for(now_et.date())
    todays_due = [slot for slot in todays_slots if slot["at"] <= now_et]
    before_first = bool(todays_slots and now_et < todays_slots[0]["at"])
    active_window = any(
        dt.datetime.combine(now_et.date(), dt.time(start_h, start_m), tzinfo=ET)
        <= now_et
        <= dt.datetime.combine(now_et.date(), dt.time(end_h, end_m), tzinfo=ET)
        + dt.timedelta(minutes=15)
        for (start_h, start_m), (end_h, end_m) in (
            ((1, 10), (2, 55)),
            ((14, 5), (15, 55)),
        )
    )
    log_available = bool(_log_signature(root))
    today_lines = _scheduler_lines(now_et.date(), root) if log_available else []
    due_evidence = [
        (_slot, _evidence(_slot, root, today_lines)) for _slot in todays_due
    ]
    latest_evidence = due_evidence[-1][1] if due_evidence else {
        "state": "not_scheduled",
        "reason": "none",
        "severity": "none",
        "slot_at": None,
        "slot_id": None,
        "detail": None,
    }
    overdue_unexplained = [
        evidence for slot, evidence in due_evidence
        if evidence["state"] == "not_observed"
        and now_et > slot["at"] + dt.timedelta(seconds=slot["allowance_seconds"])
    ]
    incidents = [
        evidence for _slot, evidence in due_evidence
        if evidence["state"] == "failed" or evidence["severity"] == "incident"
    ]
    # A failure that a later slot in the same sleeve has already run past is history, not a
    # live alarm. Without this the rail reads "attention required" for the rest of the day
    # over an outage that ended hours ago — and an alarm that never clears is one the
    # operator learns to ignore. The failure itself stays in `incidents`: six lost NKD entry
    # slots are a fact about the night even once the stream is healthy again.
    _annotate_incident_lifecycle(incidents, due_evidence)
    open_incidents = [item for item in incidents if item["lifecycle"] == "open"]

    state_age_seconds = None
    stale_against_latest = False
    if observed_at is not None:
        observed_utc = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=dt.timezone.utc)
        state_age_seconds = max(0.0, round((server_now - observed_utc).total_seconds(), 3))
        if latest is not None:
            stale_against_latest = (
                observed_utc < latest["at"]
                and state_age_seconds > STATE_STALE_ALLOWANCE_SECONDS
            )

    if observed_at is None:
        freshness = "missing"
    elif stale_against_latest:
        # Đặt TRƯỚC mọi nhánh khác: một snapshot bỏ lỡ slot gần nhất không thể
        # được cứu bởi việc "chưa tới giờ slot kế tiếp".
        freshness = "stale"
    elif not trading_today or before_first:
        freshness = "not_expected_yet"
    elif overdue_unexplained:
        freshness = "late"
    elif not active_window:
        freshness = "not_expected_yet"
    elif not log_available:
        freshness = "unknown"
    else:
        state = latest_evidence["state"]
        if next_slot and next_slot["at"].date() == now_et.date():
            freshness = "fresh"
        elif state in ("executed", "failed", "skipped", "not_observed"):
            freshness = "not_expected_yet"
        else:
            freshness = "unknown"

    return {
        "source": "scheduler_log",
        "server_now": _iso(server_now),
        "trading_day": trading_today,
        "active_window": active_window,
        "state_slot_count": len(STATE_SLOTS),
        "latest_expected_at": _iso(latest["at"]) if latest else None,
        "expected_next_at": _iso(next_slot["at"]) if next_slot else None,
        "next_scheduled_job": _next_job(now_et, _scheduled_slots_for),
        "next_decision_job": _next_job(now_et, _pipeline_slots_for),
        "freshness": freshness,
        "state_age_seconds": state_age_seconds,
        "evidence_available": log_available,
        "evidence": latest_evidence,
        "incidents": incidents,
        "open_incidents": open_incidents,
        "unexplained_overdue": overdue_unexplained,
        # Age of the process, and whether it predates the cron table it is running.
        # Every other field here describes what the scheduler DID; this one describes
        # whether the scheduler on the box is the one the repo currently defines.
        "scheduler_process": scheduler_process_state(),
    }
