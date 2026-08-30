"""Read-only schedule evidence and schedule-relative runner freshness."""
from __future__ import annotations

import datetime as dt
import os as _os
import re
from contextvars import ContextVar as _ContextVar
import threading
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from global_index.session_report import _is_test_line, _to_et
from raits.live.trading_calendar import is_trading_day

ET = ZoneInfo("America/New_York")

_SCHEDULER_CMD = "global_index.run_scheduler"


def _is_scheduler_cmdline(argv: list[str] | tuple[str, ...] | None) -> bool:
    """True only for a python process launched with `-m global_index.run_scheduler`.

    Substring-matching the module name anywhere on a command line counts the wrong
    things. Measured on the first version: five hits on a host running one scheduler —
    shells grepping for the name, and the measurement script itself, whose own command
    line contained the string. The header would have shown "Scheduler x5 RUNNING", the
    duplicate-scheduler alarm, on a healthy box.
    """
    argv = list(argv or ())
    if len(argv) < 3:
        return False
    if "python" not in Path(argv[0]).name.lower():
        return False
    try:
        return argv[argv.index("-m") + 1] == _SCHEDULER_CMD
    except (ValueError, IndexError):
        return False


def _scan_scheduler_processes() -> list[dict[str, Any]]:
    """Enumerate live schedulers. ~1.8s on Windows — never call this on a request path.

    Read-only, like the rest of this backend: it enumerates, it never signals.
    """
    try:
        import psutil
    except ImportError:
        return []
    found = []
    for proc in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            argv = proc.info.get("cmdline")
        except Exception:
            continue
        if _is_scheduler_cmdline(argv):
            found.append({"pid": proc.info.get("pid"),
                          "started_epoch": proc.info.get("create_time"),
                          "command": " ".join(str(part) for part in (argv or ()))})
    return found


# The cost is process_iter itself, not reading cmdline — filtering by name first was
# measured at 1748ms against 1743ms, i.e. no help. So it gets cached instead.
#
# Shipped without this, /api/v1/schedule-status went from milliseconds to 23 SECONDS:
# the dashboard polls every ~8s and the 1.8s scans piled up. The first read pays for
# itself; after that a stale value is served immediately and refreshed in the
# background, so no request ever waits. Serving stale is right here — a scheduler's age
# does not need eight-second resolution, and a blank header would read as "DOWN".
_PROC_TTL_SECONDS = 60.0
_proc_cache: dict[str, Any] = {"at": 0.0, "value": None, "refreshing": False}
_proc_lock = threading.Lock()


def invalidate_scheduler_cache() -> None:
    """Drop the cached scan. For tests, and for a caller that just restarted things."""
    with _proc_lock:
        _proc_cache.update(at=0.0, value=None, refreshing=False)


def _refresh_scheduler_cache() -> None:
    try:
        scanned = _scan_scheduler_processes()
    except Exception:
        scanned = _proc_cache.get("value") or []
    with _proc_lock:
        _proc_cache.update(at=time.monotonic(), value=scanned, refreshing=False)


def _running_schedulers() -> list[dict[str, Any]]:
    with _proc_lock:
        cached = _proc_cache["value"]
        age = time.monotonic() - _proc_cache["at"]
        if cached is not None and age < _PROC_TTL_SECONDS:
            return cached
        if cached is not None:
            if _proc_cache["refreshing"]:
                return cached
            _proc_cache["refreshing"] = True
            spawn = True
        else:
            spawn = False
    if spawn:
        # Stale but usable: hand it back now, replace it out of band.
        threading.Thread(target=_refresh_scheduler_cache, daemon=True).start()
        return cached
    # Nothing cached at all. Pay once rather than report a false "DOWN".
    _refresh_scheduler_cache()
    with _proc_lock:
        return _proc_cache["value"] or []


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
    # Stage 5Q-5. The daily SPY series cannot contain today's close at 13:45, so a second
    # refresh runs after it. Mirrored here for the same reason every other timed job is: a job
    # the scheduler runs and this table does not know about is a phantom overdue row every day.
    ("SPY_REFRESH_PM", 16, 20),
    # Stage 5ZZT. The rest of the ladder, and the last look before the overnight window. All
    # three were registered by Stages 5ZZC and 5ZZD and never mirrored, so for weeks the panel
    # had no row that could report them late or missing at all — the failure this table's own
    # comment describes, pointing the other way. Times read from run_scheduler.py rather than
    # assumed: a row at the wrong minute is an overdue alarm that never clears.
    ("SPY_REFRESH_PM_R1", 16, 45),
    ("SPY_REFRESH_PM_R2", 17, 15),
    # 00:45, before the 01:10 Nikkei window. It asks a DIFFERENT question from the evening
    # rungs — the previous TRADING day rather than today's close — which is why it is a
    # separate stream below and not a fourth rung.
    ("SPY_LAST_CHANCE_PRE_NKD", 0, 45),
)
# Track 1's shadow slots, mirrored here ONLY when the route is enabled — the scheduler gates
# them behind --track1-shadow and this mirror gates them behind the same fact, read from the
# environment. A slot in one file and not the other is what this module's own comment warns
# about: the dashboard treats an unknown slot id as a stray and manufactures an incident for
# it every day it fires.
#
# Off by default. Off means every number this module produces is what it has always been.
#: Per-request override for the resolved mode. A ContextVar rather than a module global: this
#: backend serves requests on threads, and a plain global would let one request's mode leak into
#: another's answer. Default None means "nobody has decided for this context; read the
#: environment", which is exactly what every existing caller and test already relies on.
_MODE_OVERRIDE: "_ContextVar[bool | None]" = _ContextVar("track1_only_override", default=None)


def track1_shadow_enabled() -> bool:
    return _os.environ.get("RAITS_TRACK1_SHADOW") == "1" or track1_only_enabled()


def track1_only_enabled() -> bool:
    """Track 1-only shadow: the scheduler does not register legacy STRATEGY jobs. Stage 5M-D.

    The mirror has to know, or it manufactures an incident for every legacy slot it expects
    and never sees — 45 a day. That is the failure this module's own comment warns about,
    pointing the other way: a slot in one file and not the other.

    Implies `track1_shadow_enabled`, because the mode registers the Track 1 slots too, and
    two flags that can disagree about that is one flag too many.
    """
    override = _MODE_OVERRIDE.get()
    if override is not None:
        return override
    return _os.environ.get("RAITS_TRACK1_ONLY") == "1"


#: Stage 5ZZW. Which mode the RUNNING SCHEDULER is in, asked of the scheduler.
#:
#: The environment variable above is how `ops.py` tells a backend it starts what mode to answer
#: in, and it propagates the same value to both processes. It is not a fact about the scheduler;
#: it is a fact about how THIS process was launched, and the two come apart the moment a backend
#: is started by hand or outlives a mode change.
#:
#: Measured on 2026-08-28 with the scheduler running `--track1-only-shadow`: `ops.py status` read
#: `track1_mode=track1-only-shadow` from the process table while this module answered `legacy`,
#: because the backend had been started without the variable. Everything downstream followed the
#: wrong answer — `inactive_by_design` came out False, so the legacy snapshot's staleness raised
#: the page-level alarm that Stage 5ZF had already built the suppression for, and the mirror
#: expected 22 legacy slots that this scheduler does not register and reported them overdue.
#:
#: `ops.track1_status` already reads the scheduler's own command line and already distinguishes
#: "could not look" from "not running". This asks it rather than growing a second reader, and
#: keeps its THREE answers: True / False / None. None is UNKNOWN and must never be rendered as
#: legacy — "I could not check" is not "I checked and it is legacy".
def scheduler_track1_mode_status(processes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Route mode from the cached scheduler process scan, without shelling out.

    The realtime dashboard polls this reader. Calling ``monitor.ops.track1_status()`` here
    shells out to PowerShell, which can flash a cmd/PowerShell window on every poll. The
    backend already has a cached psutil scan for scheduler health, so the route mode should
    come from that same cached read.
    """
    rows = _running_schedulers() if processes is None else processes
    out = {
        "scheduler_running": bool(rows),
        "track1_mode_source": "process_table" if rows else "none",
        "track1_mode": "n/a",
        "scheduler_track1_only": None,
        "track1_shadow": None,
        "legacy_entry_jobs": None,
    }
    if not rows:
        return out
    commands = " ".join(str(row.get("command") or "") for row in rows)
    if not commands.strip():
        out["track1_mode_source"] = "unknown"
        return out
    track1_only = "--track1-only-shadow" in commands
    track1_shadow = track1_only or "--track1-shadow" in commands
    out["scheduler_track1_only"] = track1_only
    out["track1_shadow"] = track1_shadow
    out["track1_mode"] = (
        "track1-only-shadow" if track1_only else
        "track1-shadow" if track1_shadow else
        "legacy-only"
    )
    out["legacy_entry_jobs"] = 0 if track1_only else len(STATE_SLOTS)
    return out


def scheduler_track1_only() -> bool | None:
    status = scheduler_track1_mode_status()
    if status.get("track1_mode_source") != "process_table":
        return None
    if status.get("scheduler_running") is not True:
        return None
    return status.get("scheduler_track1_only")


def resolve_track1_only() -> bool | None:
    """The authoritative mode for one payload: an explicit setting first, the scheduler second.

    An explicit value still wins, because a caller that has said which view it wants — a test,
    or `ops` starting a backend deliberately — is stating an intention rather than guessing.
    """
    explicit = _os.environ.get("RAITS_TRACK1_ONLY")
    if explicit is not None:
        return explicit == "1"
    return scheduler_track1_only()


TRACK1_STRESS_WINDOW = ((10, 35), (12, 30))


def _stop_repair_slots() -> tuple:
    """The sweeps, minus any that would land inside an active entry window.

    2 and 14 are the legacy NKD and Ro 4 windows. 12 joins them only when Track 1's Stress
    window is live, and the scheduler makes exactly the same subtraction from exactly the
    same window — see run_scheduler._TRACK1_STRESS_WINDOW.
    """
    skip = {2, 14}
    if track1_shadow_enabled():
        lo, hi = TRACK1_STRESS_WINDOW
        skip |= {h for h in range(0, 24, 2) if lo <= (h, 20) <= hi}
    return tuple((hour, 20) for hour in range(0, 24, 2) if hour not in skip)


STOP_REPAIR_SLOTS = tuple(
    (hour, 20) for hour in range(0, 24, 2)
    if hour not in (2, 14)
)
# (weekday, hour, minute) — Chủ nhật là 6 theo date.weekday(). Phải khớp
# run_scheduler.py: cron day_of_week="sun", hour=18, minute=30.
SUNDAY_REPAIR_SLOT = (6, 18, 30)

#: Stage 5ZZZ-AC. (weekday, hour, minute) — Chủ nhật 18:00 ET, nửa tiếng TRƯỚC sweep 18:30.
#: Hỏi SPY daily cho phiên overnight kế tiếp. Lý do có nó: thứ Sáu 2026-08-28 cả ba nấc thang
#: buổi tối chạy mà provider vẫn không trả về ngày đó, và lượt kiểm tự động kế tiếp là
#: 00:45 thứ Hai — 25 phút trước cửa sổ NKD 01:10. Khoảng hở là 55 tiếng.
SUNDAY_SPY_PRE_NKD_SLOT = (6, 18, 0)
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


def _parse_iso(value: str | None) -> dt.datetime | None:
    """An ISO instant back into an aware datetime, or None when it cannot be read.

    Three outcomes, not two. A start time that fails to parse must NOT become "no start
    time known" silently in a caller that would then compare against it — every caller here
    treats None as "do not apply the rule", which is the safe direction: it can only leave
    a slot reported as it was before, never suppress one.
    """
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ET)


def _slot_id(hour: int, minute: int) -> str:
    if hour < 3:
        return f"NKD_NIGHT_{hour:02d}{minute:02d}"
    return f"LIVE_DAY_{hour:02d}{minute:02d}"


def _track1_state_slots(day: dt.date) -> list[dict[str, Any]]:
    """Track 1's slots as HEALTH slots — or nothing at all when the route is off.

    Until now the Track 1 mirror reached only `_scheduled_slots_for`, which feeds the
    "what runs next" caption. Measured 2026-08-23: flipping RAITS_TRACK1_SHADOW changed
    exactly one field of the whole schedule-status payload, `next_scheduled_job`. The table
    that drives freshness, lateness, evidence rows and incidents stayed at 45 slots either
    way, so a Track 1 slot that failed at 11:05 was invisible to every health signal the
    dashboard has.

    This closes that half. The slots are DERIVED from `track1_slots.TRACK1_SLOTS` — the same
    table the scheduler registers from and the same one `parity_report` compares — so a
    window change moves the scheduler, the mirror and this together rather than leaving two
    of the three to be updated by hand.

    Safe to add only because the scheduler emits a parseable marker for them: the Track 1
    job body calls `_run(..., label=slot_id)` and `_run` logs `[<slot_id>] ...`, which is
    exactly the bracket form `_evidence` scans for. Without that, every Track 1 slot would
    sit at `not_observed` forever and manufacture the fake daily incident this module's own
    comment warns about.

    The allowance is read off the slot's own `kind` rather than written out here. A
    `one_shot` gets the wider grace the legacy final slots get, because a missed 10:00
    cannot be retried at all; a `window` slot gets the ordinary grace, because inside the
    window a missed slot costs nothing.
    """
    if not (track1_shadow_enabled() and is_trading_day(day)):
        return []
    from global_index.track1_slots import TRACK1_SLOTS
    return [{
        "id": s.id,
        "at": dt.datetime.combine(day, dt.time(s.hour, s.minute), tzinfo=ET),
        "allowance_seconds": 15 * 60 if s.kind == "one_shot" else 8 * 60,
    } for s in TRACK1_SLOTS]


def _state_slot_table_size() -> int:
    """How many slots the health table models. Legacy count when the route is off.

    In track1-only mode the legacy strategy slots are NOT counted, for the same reason
    `_pipeline_slots_for` already drops them: the scheduler does not register them, so
    expecting them invents stray slots. Measured 2026-08-24 before this was fixed — a
    perfectly clean Track 1 day reported **32 legacy slots overdue** and drove the rail to
    `late`, because this half of the mirror had been taught about track1-only and the health
    half had not.
    """
    if not track1_shadow_enabled():
        return len(STATE_SLOTS)
    from global_index.track1_slots import TRACK1_SLOTS
    legacy = 0 if track1_only_enabled() else len(STATE_SLOTS)
    return legacy + len(TRACK1_SLOTS)


def _active_windows() -> tuple:
    """ET bands in which a state slot is expected to be firing.

    The two legacy bands, plus one band per Track 1 sleeve when the route is on. Derived
    from the slot table rather than retyped: without this, a Track 1 window would land
    inside a period the dashboard still labels "not expected yet", so a slot could go
    missing at 11:05 and the rail would keep reporting that nothing was due.
    """
    windows = [((1, 10), (2, 55)), ((14, 5), (15, 55))]
    if track1_shadow_enabled():
        from global_index.track1_slots import TRACK1_SLOTS
        by_sleeve: dict = {}
        for s in TRACK1_SLOTS:
            at = (s.hour, s.minute)
            lo, hi = by_sleeve.get(s.sleeve, (at, at))
            by_sleeve[s.sleeve] = (min(lo, at), max(hi, at))
        windows.extend(by_sleeve[name] for name in sorted(by_sleeve))
    return tuple(windows)


def _slots_for(day: dt.date) -> list[dict[str, Any]]:
    if not is_trading_day(day):
        return []
    out = []
    # In track1-only mode the scheduler registers no legacy STRATEGY job, so expecting these
    # invents a stray slot for every one of them. `_pipeline_slots_for` has made this
    # subtraction since Stage 5M-D; the HEALTH table had not, and the two halves of the same
    # mirror disagreed. Measured 2026-08-24 on a clean Track 1 day: 32 legacy slots reported
    # `unexplained_overdue` and the rail read `late` with nothing actually wrong.
    #
    # The fixed pipeline jobs (max-hold, pre-flight) are NOT legacy strategy and are not in
    # this table at all, so nothing operational is lost by the subtraction.
    if not track1_only_enabled():
        for hour, minute in STATE_SLOTS:
            at = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=ET)
            final = (hour, minute) in ((2, 55), (15, 55))
            out.append({
                "id": _slot_id(hour, minute),
                "at": at,
                "allowance_seconds": 15 * 60 if final else 8 * 60,
            })
    # Additive, and only when the route is on. With the flag off this list is empty and
    # every number this function produces is what it has always been.
    out.extend(_track1_state_slots(day))
    return sorted(out, key=lambda item: item["at"])


def _pipeline_slots_for(day: dt.date) -> list[dict[str, Any]]:
    """Decision-producing slots and the gates that directly precede them."""
    if not is_trading_day(day):
        return []
    # The legacy entry slots — R4 14:05-15:55 and the NKD night runs. In Track 1-only mode
    # the scheduler does not register them, so mirroring them would invent 45 stray slots a
    # day. The fixed pipeline jobs below (max-hold, pre-flight) are NOT legacy strategy and
    # stay in both modes.
    slots = [] if track1_only_enabled() else [
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
    } for hour, minute in _stop_repair_slots() if is_trading_day(day))
    if track1_shadow_enabled() and is_trading_day(day):
        from global_index.track1_slots import TRACK1_SLOTS
        slots.extend({
            "id": s.id,
            "at": dt.datetime.combine(day, dt.time(s.hour, s.minute), tzinfo=ET),
        } for s in TRACK1_SLOTS)
    if track1_only_enabled():
        # Stage 5O: Track 1's own safety jobs exist only in track1-only mode, and they come
        # from the SAME table the scheduler registers from, so the two cannot drift. The
        # weekday jobs mirror on trading days; the Sunday-reopen sweep mirrors on Sundays,
        # exactly like the legacy Sunday sweep below.
        from global_index.track1_slots import track1_safety_jobs
        for sj in track1_safety_jobs():
            if sj.day_of_week == "sun":
                if day.weekday() == 6:
                    slots.append({"id": sj.id.upper(),
                                  "at": dt.datetime.combine(day, dt.time(sj.hour, sj.minute),
                                                            tzinfo=ET)})
            elif is_trading_day(day):
                slots.append({"id": sj.id.upper(),
                              "at": dt.datetime.combine(day, dt.time(sj.hour, sj.minute),
                                                        tzinfo=ET)})

        # Stage 5Q: the post-window audit jobs, mirrored from the SAME table the scheduler
        # registers from. Mirrored rather than exempted on purpose — an audit that silently
        # stopped running is the one failure that makes every other reading on this page
        # untrustworthy, and a job with no mirror row cannot be reported overdue at all.
        #
        # These carry TRACK1_ ids, so the pre-start rule below applies to them too: an audit
        # whose instant passed before this scheduler existed reads `not_applicable`, not
        # `late`.
        from global_index.track1_slots import track1_audit_jobs
        for aj in track1_audit_jobs():
            if is_trading_day(day):
                slots.append({"id": aj.id.upper(),
                              "at": dt.datetime.combine(day, dt.time(aj.hour, aj.minute),
                                                        tzinfo=ET)})

    # Chủ nhật KHÔNG phải trading day nên vòng trên bỏ qua nó — nhưng scheduler thật
    # có một sweep lúc 18:30 ET, ngay sau khi CME mở lại, để 6 tiếng rưỡi đầu phiên
    # không trôi qua mà không lượt kiểm bảo vệ nào (run_scheduler.py, day_of_week="sun").
    # Không mirror ở đây thì dashboard coi nó là slot lạ và dựng incident giả mỗi tuần.
    if day.weekday() == SUNDAY_REPAIR_SLOT[0]:
        slots.append({
            "id": "STOP_REPAIR_SUN_1830",
            "at": dt.datetime.combine(day, dt.time(*SUNDAY_REPAIR_SLOT[1:]), tzinfo=ET),
        })
    # Stage 5ZZZ-AC. Cùng lý do như sweep 18:30 ngay trên: scheduler thật có job này
    # (day_of_week="sun"), không mirror thì dashboard coi là slot lạ và dựng incident giả.
    # Nó hỏi SPY daily cho phiên overnight kế tiếp, sớm hơn 00:45 gần bảy tiếng.
    if day.weekday() == SUNDAY_SPY_PRE_NKD_SLOT[0]:
        slots.append({
            "id": "SPY_WEEKEND_PRE_NKD_CHECK",
            "at": dt.datetime.combine(day, dt.time(*SUNDAY_SPY_PRE_NKD_SLOT[1:]), tzinfo=ET),
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


#: A slot id belongs to the Track 1 route. The pre-start rule below is scoped to these on
#: purpose — the same reasoning applies to a legacy slot, but legacy already has its own
#: `interrupted`/`scheduler_restart` handling and a long-tuned alarm surface, and widening
#: this in the same change would risk masking a legacy alarm to fix a Track 1 one.
def _is_track1_slot(slot_id: str) -> bool:
    return str(slot_id or "").upper().startswith("TRACK1_")


def _evidence(
    slot: dict[str, Any],
    root: Path,
    lines: list[str] | None = None,
    scheduler_started: "dt.datetime | None" = None,
) -> dict[str, Any]:
    marker = f"[{slot['id']}]"
    scanned = lines if lines is not None else _scheduler_lines(slot["at"].date(), root)
    matched = [line for line in scanned if marker in line]
    last_index = max((i for i, line in enumerate(scanned) if marker in line), default=-1)
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
    # Đã chạy rồi bị cắt ngang, khác hẳn không hề chạy — và trước đây cả hai cùng rơi
    # vào "not_observed".
    #
    # Đêm 2026-08-18: scheduler khởi động lại lúc 01:10:52 ET, đúng 52 giây sau khi slot
    # 01:10 sinh tiến trình con. Cha chết nên không còn ai sống để ghi dòng kết thúc —
    # dòng đó sẽ KHÔNG BAO GIỜ tới, và slot ấy giữ băng-rôn "attention required" tới nửa
    # đêm dù 01:15 và 01:20 chạy sạch ngay sau.
    #
    # Cách chữa KHÔNG phải là để slot sau che slot trước: một slot không để lại dấu vết
    # nào thì im lặng đó chính là kiểu hỏng hệ này liên tục bị cắn, và
    # test_older_unexplained_slot_cannot_be_hidden_by_newer_slot giữ đúng chỗ đó — bản
    # vá đầu tiên của tôi đi hướng ấy và bị nó chặn lại.
    #
    # Đây là bằng chứng dương, không phải che: slot CÓ dòng khởi chạy, và sau dòng đó
    # log có một lần scheduler khởi động. Nói được vì sao không có dòng kết thúc thì đó
    # là đã giải thích, không phải đã bỏ qua.
    if matched and any("scheduler started" in line.lower() for line in scanned[last_index + 1:]):
        return {**base, "state": "interrupted", "reason": "scheduler_restart",
                "severity": "expected"}

    # A slot whose instant passed BEFORE the scheduler process existed never had anything to
    # run it. Reported as `not_applicable`, not as a missing observation.
    #
    # Measured 2026-08-24: the operator started a track1-only session at 04:32 ET; the NKD
    # window is 01:10-02:55 ET, so all 22 NKD slots had already passed. The dashboard read
    # `freshness: late` with 22 unexplained-overdue rows, for a route that had not been asked
    # to do anything yet. The acceptance audit already reasons this way — a window that closed
    # before the process existed is NOT_ENOUGH_DATA_YET, never a failure — and the dashboard
    # disagreeing with it is how an operator wakes to a "pipeline failed" banner over nothing.
    #
    # Two deliberate limits. It requires NO evidence at all: a slot with log lines is
    # explained by those lines, whatever the clock says. And it is scoped to Track 1 ids, so
    # legacy's alarm surface is untouched by a Track 1 fix.
    if (not matched and scheduler_started is not None and _is_track1_slot(slot["id"])
            and slot["at"] < scheduler_started):
        return {**base, "state": "not_applicable", "reason": "before_scheduler_start",
                "severity": "none",
                "detail": (f"slot instant {_iso(slot['at'])} is before the scheduler started "
                           f"at {_iso(scheduler_started)}; no process existed to run it")}
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


#: Sentinel for "nobody passed a mode, so read the environment" — distinct from `None`, which
#: is a real answer meaning the scheduler could not be read.
_DERIVE_FROM_ENV = object()


def get_schedule_status(
    root: Path,
    observed_at: dt.datetime | None = None,
    now: dt.datetime | None = None,
    track1_only: "bool | None | object" = _DERIVE_FROM_ENV,
) -> dict[str, Any]:
    # Stage 5ZZW. The mode is INJECTED by the caller that knows, and derived from the
    # environment when nobody says.
    #
    # The first version resolved it here, by asking the scheduler directly. That made the live
    # payload right and every test that describes a machine by clearing the environment wrong:
    # twenty-six of them started reading the real process table and answering about whatever
    # happened to be running. A test that is not isolated is worse than no test, because it
    # reports on the wrong system with full confidence — this repo has the scar already, and
    # `ops.py` carries the comment about it.
    #
    # So the seam is the parameter. `app.py` passes the resolved answer, because it serves the
    # live dashboard and the scheduler is the authority there. Anyone calling this directly
    # gets exactly the behaviour they had before.
    #
    # Resolved ONCE per call either way: every slot table, window band and overdue list below
    # asks `track1_only_enabled()`, and a payload whose `route_mode` disagrees with the list it
    # built is worse than either answer on its own.
    _resolved = (track1_only_enabled() if track1_only is _DERIVE_FROM_ENV else track1_only)
    _token = _MODE_OVERRIDE.set(_resolved is True)
    try:
        return _schedule_status_body(root, observed_at, now, _resolved)
    finally:
        _MODE_OVERRIDE.reset(_token)


def _schedule_status_body(
    root: Path,
    observed_at: dt.datetime | None,
    now: dt.datetime | None,
    resolved_track1_only: bool | None,
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
        for (start_h, start_m), (end_h, end_m) in _active_windows()
    )
    log_available = bool(_log_signature(root))
    today_lines = _scheduler_lines(now_et.date(), root) if log_available else []
    _sched_state = scheduler_process_state()
    _started_at = _parse_iso(_sched_state.get("started_at"))
    due_evidence = [
        (_slot, _evidence(_slot, root, today_lines, _started_at)) for _slot in todays_due
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
    # Stage 5ZF. `observed_at` is the LEGACY runner's state snapshot, and in track1-only
    # shadow the legacy strategy jobs are deliberately not registered — 45 of them — so
    # nothing ever writes it. Its age then grows without bound and drove the whole rail to
    # "scheduler attention required" for the entire shadow period.
    #
    # That is an alarm that never turns off, which is the exact defect this module already
    # fixed once with `open_incidents`: an operator learns to ignore a light that is always
    # on, and the next real one is invisible.
    #
    # The staleness is NOT hidden — it is reported under `legacy_runner` below with a reading
    # that says it is expected. What changes is that it no longer decides the ROUTE's health.
    # Every other freshness branch reads the scheduler LOG, which in this mode contains the
    # Track 1 slots, so falling through gives a route-correct answer rather than a legacy one.
    # Stage 5ZZW. From the RESOLVED mode, not from this process's environment. `None` means the
    # scheduler could not be read, and it is carried as its own answer rather than collapsing
    # into "legacy" — the difference between "legacy is running" and "I could not check" is the
    # whole point of the rail line this feeds.
    legacy_inactive_by_design = resolved_track1_only is True
    route_mode_source = (
        "unknown" if resolved_track1_only is None
        else "environment" if _os.environ.get("RAITS_TRACK1_ONLY") is not None
        else "scheduler_process_table")
    if observed_at is not None:
        observed_utc = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=dt.timezone.utc)
        state_age_seconds = max(0.0, round((server_now - observed_utc).total_seconds(), 3))
        if latest is not None:
            stale_against_latest = (
                observed_utc < latest["at"]
                and state_age_seconds > STATE_STALE_ALLOWANCE_SECONDS
                and not legacy_inactive_by_design
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
        "state_slot_count": _state_slot_table_size(),
        "latest_expected_at": _iso(latest["at"]) if latest else None,
        "expected_next_at": _iso(next_slot["at"]) if next_slot else None,
        "next_scheduled_job": _next_job(now_et, _scheduled_slots_for),
        "next_decision_job": _next_job(now_et, _pipeline_slots_for),
        "freshness": freshness,
        "state_age_seconds": state_age_seconds,
        # Named rather than dropped. A reader that stopped mentioning the legacy snapshot
        # would be hiding it, and the point is only that it is not the Track 1 route's health.
        "legacy_runner": {
            "inactive_by_design": legacy_inactive_by_design,
            "state_age_seconds": state_age_seconds,
            "state_stale": bool(
                state_age_seconds is not None
                and state_age_seconds > STATE_STALE_ALLOWANCE_SECONDS),
            "reading": (
                "legacy runner inactive / draining — its state file is stale by design in "
                "track1-only shadow, and does not describe the Track 1 route"
                if legacy_inactive_by_design else
                "legacy runner state, as recorded by the legacy route"),
            "drain_safety_still_scheduled": legacy_inactive_by_design,
        },
        "route_mode": ("track1_only_shadow" if resolved_track1_only is True
                       else "legacy" if resolved_track1_only is False else "unknown"),
        # Where that answer came from, said out loud rather than left to be assumed — the same
        # discipline `ops.py` applies to `track1_mode_source`, and for the same reason: this
        # module gave a confidently wrong answer for days because nobody could see which lane
        # it had read.
        "route_mode_source": route_mode_source,
        "route_mode_known": resolved_track1_only is not None,
        "evidence_available": log_available,
        "evidence": latest_evidence,
        "incidents": incidents,
        "open_incidents": open_incidents,
        "unexplained_overdue": overdue_unexplained,
        # Age of the process, and whether it predates the cron table it is running.
        # Every other field here describes what the scheduler DID; this one describes
        # whether the scheduler on the box is the one the repo currently defines.
        "scheduler_process": _sched_state,
    }
