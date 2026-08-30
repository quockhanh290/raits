"""Read-only extraction of scheduler jobs and their operational details."""
from __future__ import annotations

import copy
import json
import datetime as dt
import re
import threading
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from monitor.backend.schedule_status import is_clean_exit, is_debt_exit
from monitor.backend.session_event_reader import read_session_events

LOCAL_TZ = ZoneInfo("America/Edmonton")
ET = ZoneInfo("America/New_York")
_LINE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<level>\S+)\s+(?P<logger>\S+)\s+(?:-|—)\s+(?P<message>.*)$"
)
_JOB = re.compile(r"^\[(?P<job_id>[A-Z0-9_]+)]\s+(?P<detail>.*)$")
# The scheduler launches every child as `<python> -m <package>.<entry>`. Match that shape,
# not the bare word "python": traceback frames quote the interpreter's install path too.
#
# `monitor.` is here because the scheduler stopped launching only global_index entries on
# 2026-08-15, when the nightly broker-statement pull and P&L rebuild were attached after
# the session report. Anchored on global_index alone, those two would run every evening
# and appear in this journal as nothing at all -- a job whose success AND failure are both
# invisible, on the page built to show whether jobs ran.
_LAUNCH = re.compile(r"-m\s+(?:global_index|monitor)\.")
# A refused broker connection dumps ~30 traceback frames. Keep enough to name the exception,
# not enough to bury the card.
_MAX_CHILD_DIAGNOSTICS = 12
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


#: Stage 5ZD. The Track 1 STRATEGY slots, and only these, may carry signal diagnostics.
#: Safety, max-hold, stop-repair, audit, pre-flight and the SPY refresh are operations health;
#: a stop-repair row reading "NO SIGNAL" would be a category error a reader cannot undo.
TRACK1_STRATEGY_PREFIXES: tuple = ("TRACK1_CALM_", "TRACK1_STRESS_", "TRACK1_SWING_",
                                   "TRACK1_NKD_")
TRACK1_STRATEGY_SLOT = "track1_strategy_slot"


def is_track1_strategy_job(job_id: str) -> bool:
    return str(job_id).startswith(TRACK1_STRATEGY_PREFIXES)


#: Stage 5ZZU. Track 1's maintenance jobs, each an explicit stream of its own.
#:
#: They were distinguishable from legacy already — the comment below has kept TRACK1_ ahead of
#: the legacy prefixes since it was written — but distinguishable is not the same as typed, and
#: they all landed in `other` together. `other` is a bucket, and two lanes were reading it as a
#: stream, in opposite directions:
#:
#:   the journal lane   grouped every catch-all job into ONE stream, so any of them completing
#:                      closed any other that had failed. Measured on 2026-08-27: a stop-repair
#:                      sweep closed two failed SPY refreshes (Stage 5ZZT), and the same fixture
#:                      shows an audit closing a failed stop-repair sweep and vice versa.
#:   the issue lane     fell back to the job ID, so each sweep was alone. A Track 1 sweep that
#:                      failed at 06:20 could never be closed by the identical sweep at 08:20,
#:                      while its legacy counterpart — which has a real type — always could.
#:                      One is a false all-clear, the other is an alarm that never clears.
#:
#: A real type answers both at once, and it is a STRUCTURED value rather than a substring test
#: at each call site: three lanes read it and none of them has to know the id spelling.
TRACK1_SAFETY_STOP_REPAIR = "track1_safety_stop_repair"
TRACK1_SAFETY_MAX_HOLD = "track1_safety_max_hold"
TRACK1_WINDOW_AUDIT = "track1_window_audit"

#: The maintenance types, for the readers that need to ask "is this a Track 1 upkeep job?"
#: without listing them again and drifting from this one.
TRACK1_MAINTENANCE_TYPES: frozenset = frozenset({
    TRACK1_SAFETY_STOP_REPAIR, TRACK1_SAFETY_MAX_HOLD, TRACK1_WINDOW_AUDIT})


#: Stage 5ZZY. The stream a job may be RECOVERED by, which is finer than its type.
#:
#: Every Track 1 strategy slot shares one type, and that is right for every reader that asks
#: "is this a strategy slot" — the chip, the scheduler-owned list, the panel. It is wrong for
#: recovery. Measured before this was written: a failed TRACK1_CALM_DECIDE_0932 was reported
#: `lifecycle_status: recovered` by a completed TRACK1_STRESS_1035 an hour later. Different
#: sleeves are different processes against different instruments; one finishing says nothing
#: about the other having failed.
#:
#: The incidents lane in `schedule_status` already keyed on the slot id and was never wrong
#: here — this is the journal and issue lanes catching up with it, which is the same split
#: Stage 5ZZU made for the maintenance jobs one layer down.
#:
#: Both Calm phases land in the same stream on purpose: DECIDE at 09:32 and OBSERVE at 10:02
#: are two phases of one sleeve's day, and the later one covering the earlier is a real
#: recovery rather than a coincidence.
def recovery_stream(job: dict) -> str:
    job_type = job.get("job_type") or ""
    if job_type != TRACK1_STRATEGY_SLOT:
        return job_type
    job_id = str(job.get("job_id") or "").upper()
    for prefix in TRACK1_STRATEGY_PREFIXES:
        if job_id.startswith(prefix):
            return f"{TRACK1_STRATEGY_SLOT}:{prefix.rstrip('_').lower()}"
    return job_type


def _job_type(job_id: str) -> str:
    # Checked BEFORE the legacy prefixes: TRACK1_STOP_REPAIR_* would otherwise be typed as a
    # stop_repair job, and the two routes' safety jobs must stay distinguishable.
    if is_track1_strategy_job(job_id):
        return TRACK1_STRATEGY_SLOT
    # Stage 5ZZU, and for the same reason — ahead of the legacy prefixes, never sharing them.
    # Both spellings of the max-hold id are accepted: the slot table declares
    # `track1_maxhold_exit` and the log label that reaches this reader is TRACK1_MAX_HOLD_EXIT.
    # Matching only one of them would type the job on some days and not others.
    if job_id.startswith("TRACK1_STOP_REPAIR"):
        return TRACK1_SAFETY_STOP_REPAIR
    if job_id.startswith(("TRACK1_MAX_HOLD", "TRACK1_MAXHOLD")):
        return TRACK1_SAFETY_MAX_HOLD
    if job_id.startswith("TRACK1_AUDIT"):
        return TRACK1_WINDOW_AUDIT
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
    # Stage 5ZF. Typed rather than left in the `other` bucket. It was already VISIBLE there —
    # a failure produced a row — but the impact read "the job emitted an unclassified error",
    # which is true of anything and tells an operator nothing. This job's failure has one
    # specific, next-morning consequence and the reader can state it.
    # Stage 5ZZT. The retry rungs join the SAME stream as the 16:20 run, which is what makes
    # `later_same_stream` below express the ladder correctly: a rung that missed and a later
    # rung that completed is a recovery, and that is precisely what a ladder is for.
    #
    # Before this they fell into `other`, and the cost was not merely unhelpful wording.
    # Measured on 2026-08-27, when all three rungs failed: both retries were reported
    # `lifecycle_status: recovered`, recovered_at 22:20:14 — which was TRACK1_STOP_REPAIR_1820,
    # a stop-repair sweep. An unrelated job closed a failed data refresh, because `other` is a
    # catch-all and a catch-all is not a stream.
    if job_id.startswith("SPY_REFRESH_PM"):
        return "spy_refresh_pm"
    # A separate stream on purpose. It runs at 00:45 and asks for the PREVIOUS TRADING DAY,
    # not for today's close, so a success here does not answer the question the evening ladder
    # asked. Folding it in would let it mark an evening rung recovered for the wrong reason.
    if job_id == "SPY_LAST_CHANCE_PRE_NKD":
        return "spy_last_chance_pre_nkd"
    # Stage 5ZZZ-AC. A THIRD stream, separate from both of the above on purpose. It runs on
    # Sunday evening and asks for the day the next overnight window will demand. Folding it
    # into `spy_refresh_pm` would let a Sunday success mark a Friday rung recovered, which is
    # the same fault Stage 5ZZT fixed when a stop-repair sweep was closing failed refreshes.
    # Folding it into `spy_last_chance_pre_nkd` would be subtler and still wrong: they ask the
    # same question, but a Sunday failure that the Monday job then fixes is a real recovery
    # story worth seeing as two events, not one.
    if job_id == "SPY_WEEKEND_PRE_NKD_CHECK":
        return "spy_weekend_pre_nkd_check"
    if job_id == "SESSION_REPORT":
        return "session_report"
    # The two nightly evidence jobs. Typed rather than left as "other" so the journal can
    # say what their failure costs -- which is not a halted trade, it is a paper P&L that
    # no longer reconciles against the broker's own numbers.
    if job_id == "FLEX_PULL":
        return "flex_pull"
    if job_id == "PAPER_PNL":
        return "paper_pnl"
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
        "status": "running", "reason": None, "launch_count": 1, "failed_runs": 0,
        "diagnostics": [], "diagnostics_omitted": 0, "events": [],
    }


# Two processes racing the same slot launch within the same second. Slots are five minutes
# apart, so anything beyond this is a different run, not a duplicate of the one in hand.
_CONCURRENT_LAUNCH_SECONDS = 120


def _is_concurrent_relaunch(current: dict[str, Any] | None, timestamp: str) -> bool:
    if current is None or current["ended_at"] is not None:
        return False
    started, now = _parse_iso(current["started_at"]), _parse_iso(timestamp)
    if started is None or now is None:
        return False
    return 0 <= (now - started).total_seconds() <= _CONCURRENT_LAUNCH_SECONDS


def _duplicate_reason(job: dict[str, Any]) -> str:
    return f"duplicate launch: {job['failed_runs']} of {job['launch_count']} runs failed"


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
            if recovery_stream(candidate) == recovery_stream(job)
            and candidate["status"] in {"completed", "completed_with_debt"}
            and not any("dump_state" in item.lower() for item in candidate.get("diagnostics", []))
        ), None)

        # Mọi job chưa hoàn tất phải khai báo lifecycle. Trước đây chỉ nhánh
        # missed + stop_repair làm việc này, nên job nkd_night/live_day failed rơi
        # về None — và frontend đọc None là "chưa recover", nên Job Journal hiện
        # OPEN vĩnh viễn cho những slot mà schedule_status và open_issue_reader
        # đều đã kết luận là đã phục hồi. Ba lane, ba câu trả lời khác nhau.
        if job["status"] in {"failed", "missed"}:
            job["lifecycle_status"] = "recovered" if later_same_stream else "open"
            job["recovered_at"] = (
                (later_same_stream.get("ended_at") or later_same_stream.get("started_at"))
                if later_same_stream else None
            )

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
                # lifecycle_status / recovered_at đã được đặt ở trên cho mọi job
                # failed|missed; ở đây chỉ còn phần diễn giải riêng của stop_repair.
                if later_same_stream:
                    job["impact"] = (
                        "The scheduled stop-repair inspection did not run at this slot; "
                        f"inspection resumed when {later_same_stream['job_id']} completed."
                    )
                    job["action"] = "No immediate action. The missed slot remains in daily history; review only if a later sweep fails or broker protection is not reconciled."
                else:
                    job["impact"] = "The scheduled stop-repair inspection did not run; protection was not rechecked by this slot."
                    job["action"] = "Review current broker positions and working stops, then check scheduler health before the next slot."
            elif job["job_type"] == "spy_refresh_pm":
                # The missed case matters more than the failed one here: the machine sleeping
                # through 16:20 is the observed failure mode, 33 stall events across 16 days.
                #
                # Stage 5ZZT split this in two. The ladder exists so that one rung can be lost
                # without costing anything, and the language above was written when 16:20 was
                # the only rung there was. Saying "tomorrow's slots will be refused" about a
                # rung a later rung already covered is a false alarm, and the stop-repair
                # branch immediately above has drawn this distinction since it was written.
                if later_same_stream:
                    job["impact"] = (
                        "This rung of the post-close SPY ladder did not run; the series was "
                        f"brought up to date when {later_same_stream['job_id']} completed."
                    )
                    job["action"] = (
                        "No immediate action. Review only if the whole ladder starts missing, "
                        "which would point at the machine being asleep rather than at the data."
                    )
                else:
                    job["impact"] = (
                        "The post-close SPY refresh did not run, so the daily series is still "
                        "a day short and tomorrow's Track 1 slots will meet a freshness "
                        "refusal."
                    )
                    job["action"] = (
                        "Rerun the SPY daily update before the next session, and check whether "
                        "the machine was asleep at the scheduled time."
                    )
            elif job["job_type"] == "spy_weekend_pre_nkd_check":
                job["impact"] = (
                    "The Sunday early look at the daily series did not run. Nothing else "
                    "checks it until 00:45 Monday, which is 25 minutes before the overnight "
                    "window — too late to fix anything by hand."
                )
                job["action"] = (
                    "Check the daily series covers the previous trading day now, while there "
                    "is still an evening to act in, rather than waiting for the 00:45 job."
                )
            elif job["job_type"] == "spy_last_chance_pre_nkd":
                job["impact"] = (
                    "The last look at the daily series before the overnight window did not "
                    "run. Nothing after it checks the series before the sleeves do, and on a "
                    "Monday the evening ladder last ran thirty-one hours earlier."
                )
                job["action"] = (
                    "Confirm the daily series covers the previous trading day before the "
                    "01:10 window, and check whether the machine was asleep at 00:45."
                )
            elif job["job_type"] == TRACK1_SAFETY_STOP_REPAIR:
                # Stage 5ZZU. The same shape as the legacy stop-repair branch above, because it
                # is the same operation on the other route's book — and for the same reason, a
                # later sweep of THIS route is what closes it.
                if later_same_stream:
                    job["impact"] = (
                        "The Track 1 stop-repair sweep did not run at this slot; the Track 1 "
                        f"book was rechecked when {later_same_stream['job_id']} completed."
                    )
                    job["action"] = (
                        "No immediate action. The missed slot stays in daily history; review "
                        "only if later sweeps also fail."
                    )
                else:
                    job["impact"] = (
                        "The Track 1 stop-repair sweep did not run, so protective stops on the "
                        "Track 1 book were not rechecked at this slot."
                    )
                    job["action"] = (
                        "Confirm the Track 1 book still has its protective stops, then check "
                        "scheduler health before the next sweep."
                    )
            elif job["job_type"] == TRACK1_SAFETY_MAX_HOLD:
                job["impact"] = (
                    "The Track 1 max-hold exit check did not run, so a position past its "
                    "maximum hold would not have been closed at this slot."
                )
                job["action"] = (
                    "Check the Track 1 book for positions past their max hold, then confirm "
                    "the next scheduled check runs."
                )
            elif job["job_type"] == TRACK1_WINDOW_AUDIT:
                # Nothing about the broker here on purpose. This job reads the route's own
                # evidence records; a miss costs a gap in that evidence, not a trading risk.
                job["impact"] = (
                    "The window audit did not run, so no evidence record was written for that "
                    "window. Nothing is at risk in the book; the shadow record has a gap, and "
                    "the paper-evidence gate reads that record."
                )
                job["action"] = (
                    "Rerun the audit for the affected window if the evidence record is needed, "
                    "and check scheduler health before the next audit."
                )
            elif job["job_type"] in {"live_day", "nkd_night"}:
                job["impact"] = "The scheduled decision run did not execute; this slot produced no decision or runner-state update."
                job["action"] = "Check scheduler health and confirm the next expected decision slot runs."
            else:
                job["impact"] = "The scheduled job did not run; its intended check or output is absent for this slot."
                job["action"] = "Review scheduler health and confirm the next expected run."
        elif (job["status"] == "failed" and job["job_type"] == "spy_refresh_pm"
                and later_same_stream):
            # Stage 5ZZT. A rung that failed and was caught by a later one. Measured on
            # 2026-08-27 this was not hypothetical: 16:20, 16:45 and 17:15 all failed, and the
            # 00:45 last look the next morning is what actually brought the series up to date.
            job["impact"] = (
                "This rung of the post-close SPY ladder failed; the series was brought up to "
                f"date when {later_same_stream['job_id']} completed."
            )
            job["action"] = (
                "No immediate action. Review the diagnostics if rungs keep failing, since the "
                "ladder is then running on its last rung."
            )
        elif job["status"] == "failed" and job["job_type"] == "spy_last_chance_pre_nkd":
            job["impact"] = (
                "The last look at the daily series before the overnight window failed. If the "
                "evening ladder also failed, nothing has refreshed the series since the "
                "previous session and the overnight sleeves will meet a freshness refusal."
            )
            job["action"] = (
                "Check whether the evening ladder succeeded. If it did not, rerun the SPY "
                "daily update before the 01:10 window."
            )
        elif job["status"] == "failed" and job["job_type"] == "spy_refresh_pm":
            # Not a trading incident today, and a blocking one tomorrow. The 13:45 pre-flight
            # runs BEFORE the close and can never bring today's daily bar, so this 16:20 job
            # is the only thing that puts it in the series. Without it the file is a day
            # short, and every Track 1 slot the next morning meets a freshness gate that
            # refuses — which is a whole window lost, not a warning.
            job["impact"] = (
                "The daily SPY series was not refreshed after the close, so it is still a day "
                "short. Nothing is at risk right now; tomorrow's Track 1 slots will be refused "
                "by the freshness gate until the missing close is present."
            )
            job["action"] = (
                "Rerun the SPY daily update before the next session and confirm the series "
                "reaches today's close."
            )
        elif job["status"] == "failed" and job["job_type"] == TRACK1_SAFETY_STOP_REPAIR:
            job["impact"] = (
                "The Track 1 stop-repair sweep failed, so protective stops on the Track 1 book "
                "were not confirmed at this slot."
            )
            job["action"] = (
                "Review the diagnostics below and confirm the Track 1 book still has its "
                "protective stops."
            )
        elif job["status"] == "failed" and job["job_type"] == TRACK1_SAFETY_MAX_HOLD:
            job["impact"] = (
                "The Track 1 max-hold exit check failed, so a position past its maximum hold "
                "may still be open."
            )
            job["action"] = (
                "Review the diagnostics below and check the Track 1 book for positions past "
                "their max hold."
            )
        elif job["status"] == "failed" and job["job_type"] == TRACK1_WINDOW_AUDIT:
            job["impact"] = (
                "The window audit failed, so its evidence record is missing or incomplete for "
                "that window. Nothing is at risk in the book; the paper-evidence gate reads "
                "that record and a gap in it delays evidence, it does not create exposure."
            )
            job["action"] = (
                "Review the diagnostics below and rerun the audit for that window if the "
                "evidence record is needed."
            )
        elif job["status"] == "failed" and job["job_type"] == "preflight":
            job["impact"] = "The input gate failed; scheduled Live Day decision slots will be blocked until fresh IBKR and SPY data are confirmed."
            job["action"] = "Fix the failed input update, rerun the required update manually, and confirm both data sources are fresh before Live Day."
        elif job["status"] == "failed" and job["job_type"] in {"flex_pull", "paper_pnl"}:
            # Deliberately not phrased as a trading incident. Nothing is halted and no
            # position is at risk -- what is lost is the check that the sleeve ledger
            # still agrees with the money IBKR actually moved. That check reading 0.00
            # while the account was $1,260 out is the whole reason it exists.
            source = ("the broker statement was not pulled" if job["job_type"] == "flex_pull"
                      else "the comparison was not rebuilt")
            job["impact"] = (
                f"Paper P&L is not reconciled against actual Flex P&L: {source}, so the "
                f"dashboard's P&L section still reflects the previous run."
            )
            job["action"] = (
                "No trading action. The Paper Evidence page flags its own P&L as STALE "
                "from the data watermark; rerun python monitor/paper_pnl_compare.py "
                "(after monitor/flex_pull.py if the statement is also behind) to clear it."
            )
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


def _parse(paths: list[Path], day: str, session_events: list[dict[str, Any]],
           root: Path = Path(".")) -> dict[str, Any]:
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
            # Child output, echoed back by the scheduler. It is never a launch, whatever it
            # happens to contain — a traceback frame quotes the Python install path, and the
            # old "python in detail" test read every such frame as a new run of the job.
            if detail.startswith(("stdout:", "stderr:")):
                if current is not None and detail.startswith("stderr:"):
                    line = detail[len("stderr:"):].strip()
                    if line:
                        current["diagnostics"].append(line)
                        # Keep the TAIL, not the head. A traceback says what went wrong on its
                        # last line and how it got there on the ~28 before it; trimming from
                        # the end left twelve frames of ib_insync plumbing and no exception.
                        if len(current["diagnostics"]) > _MAX_CHILD_DIAGNOSTICS:
                            current["diagnostics"].pop(0)
                            current["diagnostics_omitted"] += 1
                continue
            if (_LAUNCH.search(detail) or detail.startswith("SKIPPED")) and "completed OK" not in detail:
                if detail.startswith("SKIPPED"):
                    current = _new_job(job_id, timestamp)
                    jobs.append(current)
                    _finish(current, timestamp, "skipped", "mutex" if "previous" in detail.lower() else "scheduler")
                elif _is_concurrent_relaunch(current, timestamp):
                    # A second process fired the same slot. The log carries no PID, so the two
                    # runs cannot be told apart line by line — but they are one slot, and the
                    # operator needs one card saying it ran twice, not two half-parsed jobs.
                    #
                    # Only genuinely concurrent launches count. Slot ids repeat every night, and
                    # the reader stitches two local-date files together, so a stale `active`
                    # entry would otherwise swallow tonight's run into last night's job.
                    current["launch_count"] += 1
                else:
                    current = _new_job(job_id, timestamp)
                    jobs.append(current)
                    active[job_id] = current
                continue
            # Nhánh debt phải đứng TRƯỚC nhánh sạch: "thoat OK nhung ..." chứa
            # "thoat OK" làm tiền tố, nên kiểm ngược thứ tự sẽ nuốt mất phân loại
            # completed_with_debt của 16/28 job trong một đêm thật.
            if current and is_debt_exit(detail):
                # Deliberately stays in `active`: the diagnostic that explains the debt is
                # logged on the NEXT line and still has to attach to this job. What stops a
                # stale entry from swallowing tomorrow's run of the same slot id is
                # _is_concurrent_relaunch, which refuses any job that already ended.
                _finish(current, timestamp, "completed_with_debt", "child_logged_error")
                continue
            if current and is_clean_exit(detail):
                _finish(current, timestamp, "completed",
                        _duplicate_reason(current) if current["failed_runs"] else None)
                active.pop(job_id, None)
                continue
            if current and "exited with code" in detail.lower():
                current["failed_runs"] += 1
                # Another launch of this slot may still be in flight. Closing on the first
                # non-zero exit is what let a refused duplicate bury a run that worked.
                if current["failed_runs"] < current["launch_count"]:
                    continue
                _finish(current, timestamp, "failed",
                        _duplicate_reason(current) if current["launch_count"] > 1 else detail)
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
        elif "FAIL-SAFE" in upper and "PRE-FLIGHT" in upper:
            # run_scheduler:946 prints this once at startup, inside the banner that lists TZ,
            # port and next run times. It declares the rule; it does not report that the rule
            # fired. Matching on "PRE-FLIGHT" + "SKIP" caught it — the sentence contains both
            # words — and every scheduler restart drew an amber PREFLIGHT SKIP card that read
            # exactly like the day live_day really was blocked.
            #
            # A fail-safe that actually fires never reaches this branch at all: the
            # "[PRE-FLIGHT] ... FAILED" handler above consumes it into a failed PREFLIGHT job
            # that already carries impact and action. So this is a notice, not an incident,
            # and the raw sentence is replaced rather than passed through.
            monitor_events.append({
                "ts": timestamp, "kind": "preflight_policy", "level": "info",
                "title": "Pre-flight fail-safe armed",
                "message": "Startup notice, not an event: if a pre-flight update fails, "
                           "that day's live_day slots are skipped.",
            })
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
    _annotate_signal_diagnostics(jobs, day, root)
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


#: A slot that takes this long has stopped being a five-minute slot. Stated as a constant so
#: the page can say "within budget" rather than printing a number the reader has to judge.
SLOT_RUNTIME_BUDGET_S = 300


def _coverage_rows(day: str, root: Path) -> dict:
    """`{slot_id: coverage row}` for the day. Read-only, and never fatal."""
    try:
        p = root / "global_index" / "track1_runtime" / "window_coverage" / \
            f"window_coverage_{day.replace('-', '')}.jsonl"
        if not p.exists():
            return {}
        out = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("event") == "slot_observed" and r.get("slot_id"):
                out[str(r["slot_id"])] = r
        return out
    except Exception:
        return {}


def _audit_verdicts(day: str, root: Path) -> dict:
    """`{sleeve: verdict}` from the day's audit rows, or `{}` if none has run."""
    try:
        p = root / "global_index" / "track1_runtime" / "audits" / \
            f"track1_audit_{day.replace('-', '')}.jsonl"
        if not p.exists():
            return {}
        out = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("sleeve") and r.get("verdict"):
                out[str(r["sleeve"])] = str(r["verdict"])
        return out
    except Exception:
        return {}


def _et_clock(iso: "str | None") -> str:
    """`HH:MM:SS` in Eastern, or `--` if the stamp is unusable. Never raises."""
    if not iso:
        return "--"
    try:
        t = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return t.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M:%S")
    except Exception:
        return "--"


def _operational(job: dict, signal_row, coverage: dict, audits: dict,
                 data_observation: "dict | None" = None) -> dict:
    """Did the slot RUN correctly — separately from what the strategy then saw.

    Stage 5ZE. Audited first, and none of this was on the page: the expanded panel showed
    started/completed/duration/outcome, an impact and an action, and the job's own event list —
    which is empty for every Track 1 slot, because a shadow slot emits no trade events. So an
    operator could see that a slot ran and for how long, and nothing at all about whether the
    freshness gate passed, whether the live frame was refused, whether the evidence row was
    written, or whether the duration was near its budget.

    Every field here is read from evidence that already exists. Nothing new is computed about
    the strategy, and nothing here can change a decision.
    """
    from global_index import track1_signals as sig

    slot_id = str(job.get("job_id", ""))
    status = str(job.get("status", ""))
    dur = job.get("duration_seconds")
    cov = coverage.get(slot_id)
    lines: list[str] = []

    # 1. did it run at all
    if status == "missed":
        ran = "missed"
        lines.append("The scheduler never started this slot.")
        if job.get("reason"):
            lines.append(str(job["reason"]))
    elif status in ("failed",):
        ran = "failed"
        lines.append("The slot started and exited with an error.")
    elif status == "running":
        ran = "running"
        lines.append("The slot is still running.")
    else:
        ran = "ran"
        # ET, because every schedule constant in this system is written in ET and the raw
        # field is UTC. A panel that printed the stored value would make an operator do the
        # conversion in their head, which is the habit this project has already lost an hour
        # to once today.
        when = _et_clock(job.get("started_at"))
        lines.append(f"Ran at {when} ET" + (f", duration {dur}s." if dur is not None else "."))

    over = bool(dur is not None and float(dur) >= SLOT_RUNTIME_BUDGET_S)
    if dur is not None:
        lines.append(f"Runtime {'OVER' if over else 'within'} the {SLOT_RUNTIME_BUDGET_S}s "
                     f"budget.")

    # 2. did it leave the evidence row the audit counts
    if ran == "ran":
        lines.append("Ledger row written." if cov else
                     "No ledger row for this slot — the audit cannot count it.")

    # 3. the runtime gates, in operator words
    refused = None
    freshness = None
    if signal_row is not None:
        freshness = signal_row.get("freshness_allow")
        if signal_row.get("status") == sig.SLOT_REFUSED:
            refused = str(signal_row.get("reason") or "")
    elif cov is not None:
        if not cov.get("decided"):
            refused = str(cov.get("reason") or "")
        freshness = cov.get("freshness_allow")

    if refused:
        lines.append("Slot refused before strategy evaluation.")
        detail = ""
        if signal_row is not None:
            detail = str(signal_row.get("detail") or "")
        elif cov is not None:
            detail = str(cov.get("detail") or "")
        # The refusal code and its detail are DIFFERENT codes -- `gate_refused` names the
        # gate, `stale` names what it found. Both are mapped; neither is dropped.
        named = sig.label(refused)
        extra = ", ".join(sig.label(c) for c in detail.split(",") if c) if detail else ""
        lines.append(f"Reason: {named}." + (f" ({extra})" if extra else ""))
    elif freshness is not None:
        lines.append("Freshness check passed." if freshness else "Freshness check failed.")
        if ran == "ran" and not refused:
            lines.append("Live frame passed.")

    # 3b. Stage 5ZO — one line proving what data the slot actually looked at.
    #
    # One line, in the Operational block, beside the other runtime facts. Not a new section:
    # the panel already has a health block and a signal chip, and a third heading for a single
    # sentence would cost more attention than it returns. Three shapes, because there are three
    # states an operator would act on differently — observed, refused, and not recorded at all
    # by the version of the slot that ran.
    from global_index import track1_data_observation as dobs

    lines.append(dobs.operator_line(data_observation))

    # 4. what a shadow slot is expected NOT to do, said out loud so its absence is not read
    #    as a fault
    lines.append("No checkpoint or book write expected in shadow.")

    sleeve = _sleeve_of(slot_id)
    verdict = audits.get(sleeve) if sleeve else None
    if verdict:
        lines.append(f"Window audit for {sleeve}: {verdict}.")

    return {
        "ran": ran,
        # Stage 5ZO. `None` means the slot ran under a version that did not write one, which
        # the panel renders as "not recorded by this slot version" — never as a fault.
        "data_observation": data_observation,
        "duration_seconds": dur,
        "over_budget": over,
        "budget_seconds": SLOT_RUNTIME_BUDGET_S,
        "ledger_row": bool(cov),
        "freshness_pass": freshness,
        "refused": bool(refused),
        "refusal_reason": sig.label(refused) if refused else None,
        "audit_verdict": verdict,
        "lines": lines,
    }


def _sleeve_of(slot_id: str) -> str:
    for prefix, sleeve in (("TRACK1_CALM_", "roska4_calm"),
                           ("TRACK1_STRESS_", "roska4_stress"),
                           ("TRACK1_SWING_", "roska4_swing"),
                           ("TRACK1_NKD_", "global_nkd")):
        if slot_id.startswith(prefix):
            return sleeve
    return ""


def _annotate_signal_diagnostics(jobs: list[dict[str, Any]], day: str, root: Path) -> None:
    """Attach one compact signal line to each Track 1 STRATEGY job. Read-only.

    Two rules decide what a job gets, and both are about not lying:

    **Only strategy slots.** Everything else is left completely untouched — no key added, not
    even an empty one. A `signal: null` on a stop-repair row would invite a renderer to print
    "no signal" about a job that has no signals to have.

    **A slot that never ran is MISSED, never NO_SIGNAL.** The journal has no row for it because
    it never wrote one, and inventing a `NO_SIGNAL` here would turn "the machine was asleep"
    into "the strategy looked and declined". On 2026-08-25 the machine slept through the whole
    Calm window, so this is the difference between a true record and a fiction.

    The one-line summary is composed by `track1_signals.one_line`, not here and not in the
    browser: one owner for the phrasing, and a test can assert it.
    """
    from global_index import track1_signals as sig

    strategy = [j for j in jobs if is_track1_strategy_job(j.get("job_id", ""))]
    if not strategy:
        return
    try:
        rows, _invalid = sig.read_day(day.replace("-", ""), root=root)
    except Exception:
        rows = []
    by_slot: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("slot_id"):
            by_slot[str(r["slot_id"])] = r          # last row for a slot wins

    coverage = _coverage_rows(day, root)
    audits = _audit_verdicts(day, root)

    # Stage 5ZO. Read once for the day, not per job: it is one small file and forty lookups
    # of it would be forty reads of the same thing.
    try:
        from global_index import track1_data_observation as _dobs
        _obs_rows, _ = _dobs.read(root=root, day=day)
        obs_by_slot = {str(r.get("slot_id") or ""): r for r in _obs_rows}
    except Exception:                                          # noqa: BLE001
        obs_by_slot = {}

    for job in strategy:
        row = by_slot.get(str(job.get("job_id", "")))
        job["operational"] = _operational(
            job, row, coverage, audits,
            data_observation=obs_by_slot.get(str(job.get("job_id", ""))))
        if row is None:
            # Two different absences, and the JOB's own status is what tells them apart.
            # A slot that never spawned is MISSED — operations health. A slot that ran and
            # left no row is NO DIAGNOSTICS — which is what every slot looked like on the day
            # the journal was introduced, and rendering those as MISSED would have accused
            # the scheduler of failing when it had not.
            ran = str(job.get("status", "")) not in ("missed", "")
            status = sig.SLOT_NO_ROW if ran else sig.SLOT_MISSED
            job["signal"] = {
                "status": status,
                "chip": sig.chip(status),
                "summary": sig.one_line({"status": status}),
                # Both point at the Operational block rather than repeating it. Stage 5ZE:
                # a REFUSED/MISSED row that printed the runtime evidence twice would give the
                # operator two copies to reconcile, and they are never both updated.
                "operator": sig.operator_lines({"status": status}),
                "details": None,
                "debug": None,
            }
            continue

        status = row.get("status")
        job["signal"] = {
            "status": status,
            "chip": sig.chip(status),
            "summary": sig.one_line(row),
            # What the panel renders. Plain English, no field names, no JSON.
            "operator": sig.operator_lines(row),
            "details": {
                "reason": row.get("reason"),
                "rejecting_layer": row.get("rejecting_layer") or None,
                "rejected_by": sig.LAYER_LABELS.get(row.get("rejecting_layer")),
                "raw_candidates": row.get("raw_candidates"),
                "accepted": row.get("accepted"),
                "rejected": row.get("rejected"),
                "orders_enabled": bool(row.get("orders_enabled")),
                "order_attempted": bool(row.get("order_attempted")),
                "candidates": row.get("candidates") or [],
            },
            # Developer material. Shipped so it is not lost, and rendered by NOTHING by
            # default — the panel has no code path that prints it. `rule_checks` is where
            # `breadth_down_count` and the raw JSON thresholds live, and after Stage 5ZD
            # every one of them comes back unmeasured, so rendering them would be thirty
            # rows of UNKNOWN burying the two lines that carry information.
            "debug": {
                "rule_checks": row.get("rule_checks") or [],
                "primary_failure": sig.primary_failure(row.get("rule_checks") or []),
                "params_hash": row.get("params_hash") or None,
                "data_source_identity": row.get("data_source_identity") or None,
                "freshness_allow": row.get("freshness_allow"),
                "detail": row.get("detail"),
            },
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
            cached = _parse(paths, day, events, root)
            _cache.clear()
            _cache[key] = cached
        return copy.deepcopy(cached)
