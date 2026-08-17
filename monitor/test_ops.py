"""Tests for the single-instance guard in monitor/ops.py.

Live 2026-08-13: two run_scheduler processes fired the same MAX_HOLD slot in the same
second. Both asked IBKR for clientId 1, one was refused, and the refusal's traceback then
broke the dashboard's log parser. ops.py already had a duplicate check — it just could not
say "I do not know", so any PowerShell hiccup read as "nothing is running".
"""
from __future__ import annotations

from monitor.ops import ProcessScan, RunningProcess, plan_single_instance


def _proc(pid: int, started: str = "2026-08-13 04:30:22") -> RunningProcess:
    return RunningProcess(pid=pid, command="pythonw -m global_index.run_scheduler", started=started)


def test_restart_replaces_the_scheduler_by_default():
    """`restart` means restart. It used to mean "restart the backend and quietly leave
    the scheduler alone".

    Measured 2026-08-16: ops.log recorded 21 backend restarts across three days and
    exactly three scheduler lines, all on the first day, all refused. The operator ran
    the documented command every time, watched the dashboard come back, and the
    scheduler kept running code from 13/8 — including a cron table with no Sunday sweep
    in it, so the 18:30 ET job simply never existed. The gap it was written to close
    stayed open for a week.

    `up` keeps the old behaviour: it starts a scheduler only when none is running, which
    is what makes it safe to run mid-session.
    """
    from monitor.ops import build_parser

    restart = build_parser().parse_args(["restart"])
    assert restart.restart_scheduler is True, (
        "plain `restart` left the scheduler untouched — the exact silence that hid a "
        "three-day-old scheduler behind 21 successful-looking restarts")

    opted_out = build_parser().parse_args(["restart", "--no-scheduler"])
    assert opted_out.restart_scheduler is False, "must still be possible to opt out"

    up = build_parser().parse_args(["up"])
    assert up.restart_scheduler is False, (
        "`up` must stay safe mid-session: start one only if none is running")


def test_a_stale_scheduler_is_never_reported_silently():
    """When the scheduler is NOT replaced, say so with its age.

    The failure this prevents is not a crash, it is a wrong belief. `restart` printed
    nothing at all about the scheduler, so "backend=started" read as "everything
    restarted". Age is the number that would have exposed it: a scheduler three days old
    on a repo whose cron changed two days ago.
    """
    from monitor.ops import describe_scheduler_state

    line = describe_scheduler_state([
        {"pid": 29340, "started": "2026-08-13 04:30:22", "age_seconds": 309_000},
    ])
    assert "29340" in line, f"the pid must be there to act on: {line}"
    assert "3d" in line or "3 d" in line or "309000" in line, (
        f"the age must be visible, not just the fact that something is running: {line}")
    assert "untouched" in line.lower() or "not restarted" in line.lower(), (
        f"it has to say the scheduler was left alone: {line}")


def test_unknown_scan_refuses_to_start():
    """The whole point. An indeterminate probe must never read as 'nothing is running'."""
    scan = ProcessScan(ok=False, processes=[], error="powershell exited 1")
    decision = plan_single_instance(scan, assume_yes=True)
    assert decision.action == "refuse"
    assert "powershell exited 1" in decision.reason


def test_clean_host_starts():
    decision = plan_single_instance(ProcessScan(ok=True, processes=[], error=None), assume_yes=False)
    assert decision.action == "start"
    assert decision.pids == []


def test_duplicates_with_assume_yes_kill_every_pid():
    scan = ProcessScan(ok=True, processes=[_proc(29340), _proc(35120, "2026-08-13 07:26:55")], error=None)
    decision = plan_single_instance(scan, assume_yes=True)
    assert decision.action == "kill_then_start"
    assert decision.pids == [29340, 35120]


def test_existing_process_without_tty_refuses():
    """Non-interactive runs must not silently kill a live trading scheduler."""
    scan = ProcessScan(ok=True, processes=[_proc(29340)], error=None)
    decision = plan_single_instance(scan, assume_yes=False, confirm=None)
    assert decision.action == "refuse"
    assert "--yes" in decision.reason


def test_declined_confirmation_refuses_and_starts_nothing():
    scan = ProcessScan(ok=True, processes=[_proc(29340)], error=None)
    decision = plan_single_instance(scan, assume_yes=False, confirm=lambda _scan: False)
    assert decision.action == "refuse"
    assert decision.pids == [29340]


def test_accepted_confirmation_kills_then_starts():
    scan = ProcessScan(ok=True, processes=[_proc(29340)], error=None)
    decision = plan_single_instance(scan, assume_yes=False, confirm=lambda _scan: True)
    assert decision.action == "kill_then_start"
    assert decision.pids == [29340]
