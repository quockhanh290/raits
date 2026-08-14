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
