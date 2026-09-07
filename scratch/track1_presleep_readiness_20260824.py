"""Is the Track 1 shadow session safe to leave running overnight? 2026-08-24.

    python scratch/track1_presleep_readiness_20260824.py

Read-only. Starts nothing, stops nothing, connects to no broker, writes nothing outside
scratch/. The one thing it mutates is its own process environment, and only to ask the
imported module the question the backend's own environment already answers.

What it is for
--------------
The operator is about to sleep. The next thing that happens unattended is the NKD window at
01:10-02:55 ET. Two questions have to be answered before that is a reasonable thing to do:

  1. will the window actually be captured (scheduler up, correct mode, evidence dirs there),
  2. and will the screen tell the truth about it in the morning.

They are different questions with different consequences, so the verdict separates them:

  READY_FOR_NEXT_WINDOW  both hold
  WARNING_ONLY           the window will be captured; something about the VIEW is wrong
  NOT_READY              the window will not be captured, or an order could be sent

That split is the whole point. A stale dashboard is not the same failure as a dead
scheduler, and collapsing them into one red light teaches the operator to ignore the light.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(r"d:\raits")
sys.path.insert(0, str(ROOT))

API = "http://127.0.0.1:5002"
ET = ZoneInfo("America/New_York")

READY = "READY_FOR_NEXT_WINDOW"
WARNING = "WARNING_ONLY"
NOT_READY = "NOT_READY"

OK, WARN, FAIL = "ok", "warn", "fail"

checks: list[dict] = []


def record(name, status, detail, *, blocks_capture=False):
    """One check. `blocks_capture` is what separates NOT_READY from WARNING_ONLY -- it means
    the overnight window itself is at risk, not merely the report about it."""
    checks.append({"name": name, "status": status, "detail": detail,
                   "blocks_capture": bool(blocks_capture and status == FAIL)})
    return checks[-1]


def get(path, timeout=10):
    try:
        with urllib.request.urlopen(API + path, timeout=timeout) as fh:
            return json.load(fh), None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, str(exc)


def now_et() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).astimezone(ET)


# ==============================================================================
# 1-2, 9. the process
# ==============================================================================

def check_scheduler():
    from monitor import ops

    procs = ops.scheduler_processes()
    scan = ops.scan_processes(ops.SCHEDULER_PATTERN)
    if not scan.ok:
        # Three outcomes, not two. "Could not ask" must never be reported as "none running":
        # the anti-duplicate guard in start_scheduler already fails open on exactly this.
        record("1_single_scheduler", FAIL,
               "the process table could not be read (" + str(scan.error) + ") -- this is "
               "'unknown', not 'one'", blocks_capture=True)
        record("2_track1_only_flag", FAIL, "cannot read argv without the process table",
               blocks_capture=True)
        return None

    if len(procs) == 1:
        p = procs[0]
        record("1_single_scheduler", OK,
               "pid " + str(p["pid"]) + ", started " + str(p.get("started"))
               + " local, up " + str(p.get("age_seconds")) + "s")
    elif not procs:
        record("1_single_scheduler", FAIL, "no scheduler is running", blocks_capture=True)
        record("2_track1_only_flag", FAIL, "nothing to inspect", blocks_capture=True)
        return None
    else:
        record("1_single_scheduler", FAIL,
               "pids " + str([q["pid"] for q in procs])
               + " -- every slot fires once PER PROCESS, and two schedulers contending for "
                 "one client id is what broke six entry slots before",
               blocks_capture=True)

    cmd = ops.scheduler_command_lines(procs)
    if "--track1-only-shadow" in cmd:
        record("2_track1_only_flag", OK, "argv carries --track1-only-shadow")
    elif "--track1-shadow" in cmd:
        record("2_track1_only_flag", FAIL,
               "running the TRANSITIONAL mode (--track1-shadow), not track1-only -- the "
               "legacy strategy jobs are still registered", blocks_capture=True)
    else:
        record("2_track1_only_flag", FAIL,
               "no Track 1 flag on argv: " + (cmd.strip() or "<empty>"), blocks_capture=True)
    return procs[0] if procs else None


def check_no_duplicates():
    from monitor import ops

    trouble = []
    for kind, pattern in (("scheduler", ops.SCHEDULER_PATTERN), ("backend", ops.BACKEND_PATTERN)):
        scan = ops.scan_processes(pattern)
        if not scan.ok:
            trouble.append(kind + "=UNKNOWN(" + str(scan.error) + ")")
        elif len(scan.processes) > 1:
            trouble.append(kind + "=" + str(scan.pids))
    listeners = ops.backend_listener_pids()
    if len(listeners) > 1:
        trouble.append("port 5002 listeners=" + str(listeners))
    if trouble:
        record("9_no_duplicates", FAIL, "duplicate or unreadable: " + "; ".join(trouble),
               blocks_capture=True)
    else:
        record("9_no_duplicates", OK,
               "one scheduler, one backend, one listener on 5002 (" + str(listeners) + ")")


# ==============================================================================
# 3-4. the backend
# ==============================================================================

def check_backend():
    payload, err = get("/api/v1/schedule-status")
    if payload is None:
        record("3_backend_slot_table", FAIL,
               "/api/v1/schedule-status unreachable: " + str(err))
        return None
    count = payload.get("state_slot_count")
    if count == 70:
        record("3_backend_slot_table", OK,
               "state_slot_count=70 (1 Calm + 24 Stress + 23 Swing + 22 NKD)")
    elif count == 115:
        record("3_backend_slot_table", FAIL,
               "state_slot_count=115 -- the backend is in TRANSITIONAL mode while the "
               "scheduler is track1-only; it would manufacture an incident for each of the "
               "45 legacy slots the scheduler does not have")
    else:
        record("3_backend_slot_table", FAIL,
               "state_slot_count=" + str(count) + ", expected 70")
    return payload


def check_track1_runtime():
    payload, err = get("/api/v1/track1-runtime")
    if payload is None:
        record("4_track1_runtime_endpoint", FAIL,
               "/api/v1/track1-runtime unreachable: " + str(err))
        return None
    if payload.get("source") != "track1_runtime":
        record("4_track1_runtime_endpoint", FAIL,
               "reachable but source=" + str(payload.get("source")))
        return payload
    record("4_track1_runtime_endpoint", OK,
           "route=" + str(payload.get("route"))
           + ", coverage present=" + str(payload.get("window_coverage", {}).get("present"))
           + ", timing present=" + str(payload.get("slot_timing", {}).get("present")))
    return payload


# ==============================================================================
# 5-6. where the night's evidence will land
# ==============================================================================

def check_evidence_dirs():
    for num, rel in (("5", "global_index/track1_runtime/window_coverage"),
                     ("6", "global_index/track1_runtime/slot_timing")):
        path = ROOT / rel
        label = num + "_" + Path(rel).name
        if path.is_dir():
            existing = sorted(p.name for p in path.glob("*"))
            record(label, OK, str(path) + " exists"
                   + (", holds " + str(len(existing)) + " file(s)" if existing
                      else ", empty (nothing has run yet)"))
        elif path.exists():
            record(label, FAIL, str(path) + " exists but is NOT a directory -- the ledger "
                   "refuses this, and every slot would hard-refuse ledger_not_configured",
                   blocks_capture=True)
        else:
            record(label, FAIL, str(path) + " is missing -- the window has nowhere to write "
                   "its evidence and the night would leave no trace", blocks_capture=True)


# ==============================================================================
# 7. the broker feed
# ==============================================================================

def check_broker():
    broker, err = get("/api/v1/broker")
    if broker is None:
        record("7_broker_feed", FAIL, "/api/v1/broker unreachable: " + str(err),
               blocks_capture=True)
        return
    connected = broker.get("connected")
    freshness = broker.get("freshness")
    age = broker.get("age_seconds")
    detail = ("connected=" + str(connected) + " freshness=" + str(freshness)
              + " age_seconds=" + str(age))
    if connected and freshness == "fresh":
        record("7_broker_feed", OK, detail)
    elif connected:
        record("7_broker_feed", WARN, detail + " -- connected but not fresh")
    else:
        record("7_broker_feed", FAIL,
               detail + " -- a disconnected feed means the NKD slots have no bars to read",
               blocks_capture=True)


# ==============================================================================
# 8. orders must remain impossible
# ==============================================================================

def check_orders_impossible():
    from monitor import ops

    t1 = ops.track1_status()
    problems = []
    blocking = t1.get("blocking") or []
    if "B1_broker_account_or_legacy_retirement" not in blocking:
        problems.append("B1 is no longer in the blocking list: " + str(blocking))
    if t1.get("orders_possible"):
        problems.append("orders_possible=True")
    if (ROOT / "track1_go_live_confirmation.json").exists():
        problems.append("track1_go_live_confirmation.json EXISTS")
    if os.environ.get("TRACK1_ORDERS_APPROVED"):
        problems.append("TRACK1_ORDERS_APPROVED is set in this shell")

    if problems:
        # A FAIL here is not "the view is wrong" -- it is the route being able to trade
        # unattended. It blocks regardless of what the rest of the report says.
        record("8_orders_impossible", FAIL,
               "; ".join(problems) + " -- do NOT leave this running", blocks_capture=True)
    else:
        record("8_orders_impossible", OK,
               "B1 open, orders_possible=False, no confirmation file, "
               "TRACK1_ORDERS_APPROVED unset")


# ==============================================================================
# 10. what is due next
# ==============================================================================

def check_next_window(schedule):
    from raits.live.trading_calendar import is_trading_day

    from global_index.track1_params import WINDOWS_ET

    now = now_et()
    upcoming = []
    for sleeve, (open_s, close_s) in sorted(WINDOWS_ET.items()):
        h, m = (int(x) for x in open_s.split(":"))
        start = now.replace(hour=h, minute=m, second=0, microsecond=0)
        # Roll forward past the window if it has already opened today, and past any day the
        # calendar says is not a session -- "in 3h" over a holiday is a wrong number, not a
        # rounding error, and it is the number the operator would set an alarm by.
        for _ in range(8):
            if start > now and is_trading_day(start.date()):
                break
            start += dt.timedelta(days=1)
        upcoming.append((start, sleeve, open_s, close_s))
    upcoming.sort()
    start, sleeve, open_s, close_s = upcoming[0]
    hours = round((start - now).total_seconds() / 3600.0, 2)

    nkd_start, _, nkd_open, nkd_close = next(u for u in upcoming if u[1] == "global_nkd")
    nkd_in = round((nkd_start - now).total_seconds() / 3600.0, 2)

    expected_next = (schedule or {}).get("expected_next_at")
    detail = ("next window " + sleeve + " " + open_s + "-" + close_s + " ET in " + str(hours)
              + "h (" + start.strftime("%a %Y-%m-%d %H:%M") + " ET); overnight NKD "
              + nkd_open + "-" + nkd_close + " ET in " + str(nkd_in) + "h ("
              + nkd_start.strftime("%a %Y-%m-%d %H:%M") + " ET); backend expected_next_at="
              + str(expected_next))
    if expected_next:
        record("10_next_window_expected", OK, detail)
    else:
        record("10_next_window_expected", WARN,
               detail + " -- the backend names no next slot, so its rail has nothing to "
                        "count down to")


# ==============================================================================
# 11. the false alarm this hardening was written for
# ==============================================================================

def check_pre_start_classification(proc, schedule):
    """Two separate questions, deliberately not merged.

    (a) Does the CODE ON DISK classify a slot that passed before the scheduler existed as
        expected rather than late?
    (b) Does the RUNNING BACKEND say so?

    They can disagree, and on the night this was written they did: the fix landed after the
    backend process started, so the backend still served the old classifier. Reporting only
    (a) would claim the operator's screen is fixed when it is not; reporting only (b) would
    hide that the fix exists and needs nothing but a restart.
    """
    from monitor.backend import schedule_status as ss

    started = ss._parse_iso((schedule or {}).get("scheduler_process", {}).get("started_at"))
    if started is None:
        record("11_pre_start_slots_expected", FAIL,
               "the backend publishes no scheduler start instant, so nothing can be judged "
               "against it")
        return

    # Process-local only, and restored below: `track1_only_enabled()` reads the environment
    # at call time, and this process is not the backend.
    previous = os.environ.get("RAITS_TRACK1_ONLY")
    os.environ["RAITS_TRACK1_ONLY"] = "1"
    try:
        slots = [s for s in ss._slots_for(now_et().date())
                 if s["id"].startswith("TRACK1_NKD_")]
        assert slots, "no NKD slots in the table -- this check would pass on an empty loop"
        misclassified = [
            s["id"] for s in slots
            if s["at"] < started
            and ss._evidence(s, ROOT, [], started)["state"] != "not_applicable"
        ]
        pre_start = [s for s in slots if s["at"] < started]
    finally:
        if previous is None:
            os.environ.pop("RAITS_TRACK1_ONLY", None)
        else:
            os.environ["RAITS_TRACK1_ONLY"] = previous

    live_nkd = [e["slot_id"] for e in (schedule or {}).get("unexplained_overdue", [])
                if "NKD" in str(e.get("slot_id"))]

    if misclassified:
        record("11_pre_start_slots_expected", FAIL,
               str(len(misclassified)) + " of " + str(len(pre_start)) + " pre-start NKD "
               "slots are still classified as late by the code on disk: "
               + str(misclassified[:5]))
        return

    disk = ("code on disk: all " + str(len(pre_start)) + " pre-start NKD slot(s) classify as "
            "not_applicable/before_scheduler_start")
    if not live_nkd:
        record("11_pre_start_slots_expected", OK,
               disk + "; running backend agrees (0 NKD slots in unexplained_overdue)")
    else:
        record("11_pre_start_slots_expected", WARN,
               disk + "; but the RUNNING BACKEND still reports " + str(len(live_nkd))
               + " of them as unexplained_overdue and freshness="
               + str((schedule or {}).get("freshness"))
               + ". The backend process predates the fix. The night's evidence is captured "
                 "by the scheduler and is unaffected -- only the screen is wrong. "
                 "Restart the backend to clear it: python monitor/ops.py restart --backend")


# ==============================================================================
# 12. the verdict
# ==============================================================================

def verdict() -> str:
    if any(c["blocks_capture"] for c in checks):
        return NOT_READY
    if any(c["status"] == FAIL for c in checks):
        return NOT_READY
    if any(c["status"] == WARN for c in checks):
        return WARNING
    return READY


def main() -> int:
    print("=" * 78)
    print("TRACK 1 PRE-SLEEP READINESS -- read-only")
    print("=" * 78)
    print("now ET: " + now_et().isoformat(timespec="seconds"))
    print()

    proc = check_scheduler()
    check_no_duplicates()
    schedule = check_backend()
    check_track1_runtime()
    check_evidence_dirs()
    check_broker()
    check_orders_impossible()
    check_next_window(schedule)
    check_pre_start_classification(proc, schedule)

    for c in sorted(checks, key=lambda c: int(c["name"].split("_", 1)[0])):
        mark = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL"}[c["status"]]
        print("[" + mark + "] " + c["name"])
        print("        " + c["detail"])
    print()

    result = verdict()
    print("VERDICT: " + result)
    if result == READY:
        print("  The next window will be captured and the screen will tell the truth "
              "about it.")
    elif result == WARNING:
        print("  The next window WILL be captured. Something about the view is wrong -- "
              "see the WARN lines.")
    else:
        print("  Do not leave this unattended until the FAIL lines below are resolved:")
        for c in checks:
            if c["status"] == FAIL:
                print("    - " + c["name"] + ": " + c["detail"])

    out = ROOT / "scratch" / "track1_presleep_readiness_20260824.json"
    out.write_text(json.dumps(
        {"now_et": now_et().isoformat(timespec="seconds"), "verdict": result,
         "scheduler_pid": (proc or {}).get("pid"), "checks": checks},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nwrote " + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
