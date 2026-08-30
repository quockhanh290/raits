"""The pre-sleep readiness script can say no. 2026-08-24.

Read-only: nothing here starts, stops, connects or writes outside tmp_path.

A readiness check that has never been observed to fail is not a check, it is a banner. The
bulk of this file is therefore not "does it pass right now" -- it is one test per way the
night can go wrong, each requiring the script to reach NOT_READY, plus the two boundaries
that decide whether a problem is NOT_READY or merely WARNING_ONLY.

The distinction being defended
------------------------------
    NOT_READY      the window will not be captured, or an order could be sent
    WARNING_ONLY   the window WILL be captured; the screen will lie about it

Collapsing those into one red light is how an operator learns to ignore the light. The
stale-backend case is the live example: 22 phantom late slots on screen, zero effect on
whether the night's evidence is written.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, r"d:\raits\scratch")

import track1_presleep_readiness_20260824 as rd   # noqa: E402

from monitor import ops                            # noqa: E402
from monitor.backend import schedule_status as ss  # noqa: E402

ET = rd.ET
START_ET = dt.datetime(2026, 8, 24, 4, 32, 24, tzinfo=ET)
BASE = "pythonw.exe -m global_index.run_scheduler --port 4002 --shadow-resume"


@pytest.fixture(autouse=True)
def fresh_checks():
    """The module keeps its findings in a module-level list. Without this, one test's
    failures would leak into the next test's verdict."""
    rd.checks.clear()
    yield
    rd.checks.clear()


class _Scan:
    def __init__(self, processes, ok=True, error=None):
        self.processes = processes
        self.ok = ok
        self.error = error
        self.pids = [p["pid"] for p in processes]


@pytest.fixture
def healthy(monkeypatch, tmp_path):
    """Every input in the state measured on the night this was written, so each test below
    can spoil exactly one of them and nothing else."""
    procs = [{"pid": 33868, "command": BASE + " --track1-only-shadow",
              "started": "2026-08-24 02:32:24", "age_seconds": 8471}]
    monkeypatch.setattr(ops, "scheduler_processes", lambda: procs)
    monkeypatch.setattr(ops, "scan_processes",
                        lambda pattern: _Scan(procs if "scheduler" in pattern.lower()
                                              else [{"pid": 3468}]))
    monkeypatch.setattr(ops, "backend_listener_pids", lambda *a, **k: [3468])
    monkeypatch.setattr(ops, "track1_status", lambda: {
        "blocking": ["B1_broker_account_or_legacy_retirement"], "orders_possible": False})

    schedule = {
        "state_slot_count": 70,
        "expected_next_at": "2026-08-24T14:00:00Z",
        "freshness": "not_expected_yet",
        "unexplained_overdue": [],
        "scheduler_process": {"started_at": ss._iso(START_ET), "pid": 33868,
                              "process_count": 1, "running": True},
    }
    runtime = {"source": "track1_runtime", "route": "track1_candidate",
               "window_coverage": {"present": True}, "slot_timing": {"present": True}}
    broker = {"connected": True, "freshness": "fresh", "age_seconds": 0.6}
    responses = {"/api/v1/schedule-status": schedule,
                 "/api/v1/track1-runtime": runtime,
                 "/api/v1/broker": broker}
    monkeypatch.setattr(rd, "get", lambda path, timeout=10:
                        (responses.get(path), None if path in responses else "no route"))

    root = tmp_path
    (root / "global_index" / "track1_runtime" / "window_coverage").mkdir(parents=True)
    (root / "global_index" / "track1_runtime" / "slot_timing").mkdir(parents=True)
    monkeypatch.setattr(rd, "ROOT", root)
    monkeypatch.setattr(rd, "now_et",
                        lambda: dt.datetime(2026, 8, 24, 6, 53, tzinfo=ET))
    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)
    return {"procs": procs, "schedule": schedule, "runtime": runtime,
            "broker": broker, "responses": responses, "root": root}


def _run(healthy):
    """Every check, in the order main() runs them, without main()'s printing or file write."""
    proc = rd.check_scheduler()
    rd.check_no_duplicates()
    schedule = rd.check_backend()
    rd.check_track1_runtime()
    rd.check_evidence_dirs()
    rd.check_broker()
    rd.check_orders_impossible()
    rd.check_next_window(schedule)
    rd.check_pre_start_classification(proc, schedule)
    return rd.verdict()


def _named(name):
    return next(c for c in rd.checks if c["name"].startswith(name))


# ==============================================================================
# 1. the healthy baseline -- and it must be genuinely clean
# ==============================================================================

def test_a_healthy_session_is_ready(healthy):
    assert _run(healthy) == rd.READY
    assert len(rd.checks) == 11, "one check per requirement, minus the verdict itself"
    assert all(c["status"] == rd.OK for c in rd.checks), \
        [c["name"] for c in rd.checks if c["status"] != rd.OK]


def test_every_check_number_one_through_eleven_is_present(healthy):
    """A verdict computed over a list that quietly lost a check is a verdict about nothing."""
    _run(healthy)
    numbers = sorted(int(c["name"].split("_", 1)[0]) for c in rd.checks)
    assert numbers == list(range(1, 12)), numbers


# ==============================================================================
# 2. NOT_READY -- the night itself is at risk
# ==============================================================================

def test_no_scheduler_is_not_ready(healthy, monkeypatch):
    monkeypatch.setattr(ops, "scheduler_processes", lambda: [])
    monkeypatch.setattr(ops, "scan_processes", lambda pattern: _Scan([]))
    assert _run(healthy) == rd.NOT_READY
    assert _named("1_")["status"] == rd.FAIL


def test_two_schedulers_is_not_ready(healthy, monkeypatch):
    """Every slot fires once per process, and two of them contend for one client id."""
    procs = healthy["procs"] + [dict(healthy["procs"][0], pid=44904)]
    monkeypatch.setattr(ops, "scheduler_processes", lambda: procs)
    monkeypatch.setattr(ops, "scan_processes",
                        lambda pattern: _Scan(procs if "scheduler" in pattern.lower()
                                              else [{"pid": 3468}]))
    assert _run(healthy) == rd.NOT_READY
    assert _named("1_")["status"] == rd.FAIL
    assert _named("9_")["status"] == rd.FAIL


def test_an_unreadable_process_table_is_not_ready(healthy, monkeypatch):
    """Three outcomes, not two. 'Could not ask' must never be reported as 'one is running' --
    that is the exact shape of the failure that let a second scheduler start."""
    monkeypatch.setattr(ops, "scan_processes",
                        lambda pattern: _Scan([], ok=False, error="CIM query failed"))
    assert _run(healthy) == rd.NOT_READY
    assert "unknown" in _named("1_")["detail"].lower()


def test_the_transitional_flag_is_not_ready(healthy, monkeypatch):
    """--track1-shadow still registers the 45 legacy strategy jobs."""
    procs = [dict(healthy["procs"][0], command=BASE + " --track1-shadow")]
    monkeypatch.setattr(ops, "scheduler_processes", lambda: procs)
    monkeypatch.setattr(ops, "scan_processes",
                        lambda pattern: _Scan(procs if "scheduler" in pattern.lower()
                                              else [{"pid": 3468}]))
    assert _run(healthy) == rd.NOT_READY
    assert "TRANSITIONAL" in _named("2_")["detail"]


def test_a_missing_evidence_directory_is_not_ready(healthy):
    """The ledger refuses when its directory is absent, so every slot would hard-refuse and
    the night would leave no trace at all -- the worst outcome, because it looks quiet."""
    (healthy["root"] / "global_index" / "track1_runtime" / "slot_timing").rmdir()
    assert _run(healthy) == rd.NOT_READY
    assert _named("6_")["status"] == rd.FAIL


def test_a_file_where_a_directory_belongs_is_not_ready(healthy):
    cov = healthy["root"] / "global_index" / "track1_runtime" / "window_coverage"
    cov.rmdir()
    cov.write_text("not a directory", encoding="utf-8")
    assert _run(healthy) == rd.NOT_READY
    assert "NOT a directory" in _named("5_")["detail"]


def test_a_disconnected_broker_is_not_ready(healthy):
    healthy["broker"].update(connected=False, freshness="stale", age_seconds=9000)
    assert _run(healthy) == rd.NOT_READY
    assert _named("7_")["status"] == rd.FAIL


def test_orders_becoming_possible_is_not_ready(healthy, monkeypatch):
    """The one FAIL that is not about observation. If the gate has opened, the route can
    trade unattended, and no amount of green elsewhere makes that acceptable."""
    monkeypatch.setattr(ops, "track1_status",
                        lambda: {"blocking": [], "orders_possible": True})
    assert _run(healthy) == rd.NOT_READY
    assert "orders_possible=True" in _named("8_")["detail"]
    assert "B1 is no longer in the blocking list" in _named("8_")["detail"]


def test_a_confirmation_file_is_not_ready(healthy, monkeypatch):
    (healthy["root"] / "track1_go_live_confirmation.json").write_text("{}", encoding="utf-8")
    assert _run(healthy) == rd.NOT_READY
    assert "confirmation" in _named("8_")["detail"]


def test_the_approval_env_var_is_not_ready(healthy, monkeypatch):
    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")
    assert _run(healthy) == rd.NOT_READY
    assert "TRACK1_ORDERS_APPROVED" in _named("8_")["detail"]


def test_the_wrong_backend_slot_table_is_not_ready(healthy):
    """115 is the transitional number. A backend serving it against a track1-only scheduler
    invents 45 slots and manufactures an incident for each, every day."""
    healthy["schedule"]["state_slot_count"] = 115
    assert _run(healthy) == rd.NOT_READY
    assert "TRANSITIONAL" in _named("3_")["detail"]


def test_an_unreachable_backend_is_not_ready(healthy, monkeypatch):
    monkeypatch.setattr(rd, "get", lambda path, timeout=10: (None, "connection refused"))
    assert _run(healthy) == rd.NOT_READY
    assert _named("3_")["status"] == rd.FAIL
    assert _named("4_")["status"] == rd.FAIL


# ==============================================================================
# 3. WARNING_ONLY -- the view is wrong, the night is not
# ==============================================================================

def test_a_stale_backend_is_warning_not_not_ready(healthy):
    """The live case. The backend process predates the classification fix, so it still calls
    22 pre-start NKD slots late. The scheduler writes the night's evidence either way."""
    healthy["schedule"]["freshness"] = "late"
    healthy["schedule"]["unexplained_overdue"] = [
        {"slot_id": "TRACK1_NKD_0" + str(110 + i), "state": "not_observed"} for i in range(22)]

    assert _run(healthy) == rd.WARNING
    check = _named("11_")
    assert check["status"] == rd.WARN
    assert check["blocks_capture"] is False
    assert "restart --backend" in check["detail"]
    assert "only the screen is wrong" in check["detail"]


def test_a_connected_but_stale_feed_is_warning(healthy):
    healthy["broker"].update(connected=True, freshness="stale", age_seconds=400)
    assert _run(healthy) == rd.WARNING
    assert _named("7_")["status"] == rd.WARN


def test_one_warning_does_not_downgrade_a_fail(healthy):
    """Severity must not be decided by whichever check ran last."""
    healthy["broker"].update(connected=True, freshness="stale")
    healthy["schedule"]["state_slot_count"] = 45
    assert _run(healthy) == rd.NOT_READY


# ==============================================================================
# 4. the pre-start rule, as the script applies it
# ==============================================================================

def test_the_pre_start_check_fails_when_the_disk_code_is_wrong(healthy, monkeypatch):
    """If the classifier itself regressed, no restart would help and the check must say so
    rather than blaming the backend."""
    monkeypatch.setattr(ss, "_evidence",
                        lambda slot, root, lines=None, started=None:
                        {"state": "not_observed", "reason": "unknown", "severity": "watch"})
    assert _run(healthy) == rd.NOT_READY
    assert _named("11_")["status"] == rd.FAIL
    assert "code on disk" in _named("11_")["detail"] or "still classified" in _named("11_")["detail"]


def test_no_published_start_instant_fails_rather_than_guessing(healthy):
    healthy["schedule"]["scheduler_process"] = {"started_at": None}
    assert _run(healthy) == rd.NOT_READY
    assert _named("11_")["status"] == rd.FAIL


def test_the_environment_is_restored_after_the_check(healthy, monkeypatch):
    """The check sets RAITS_TRACK1_ONLY to ask the module a question. Leaving it set would
    silently change the mode of anything else this shell runs afterwards."""
    monkeypatch.delenv("RAITS_TRACK1_ONLY", raising=False)
    _run(healthy)
    import os
    assert "RAITS_TRACK1_ONLY" not in os.environ

    monkeypatch.setenv("RAITS_TRACK1_ONLY", "original")
    rd.checks.clear()
    _run(healthy)
    assert os.environ["RAITS_TRACK1_ONLY"] == "original"


# ==============================================================================
# 5. the countdown
# ==============================================================================

def test_the_next_window_skips_a_non_session_day(healthy, monkeypatch):
    """'In 3h' over a holiday is a wrong number, not a rounding error -- and it is the number
    an operator would set an alarm by."""
    import raits.live.trading_calendar as cal
    real = cal.is_trading_day
    monkeypatch.setattr(cal, "is_trading_day",
                        lambda d: False if d == dt.date(2026, 8, 25) else real(d))
    _run(healthy)
    detail = _named("10_")["detail"]
    assert "Tue 2026-08-25" not in detail, "counted down to a day the calendar closed"
    assert "NKD" in detail


def test_the_countdown_names_the_overnight_window_explicitly(healthy):
    """The next window is Calm at 10:00; the one the operator is asleep for is NKD. Reporting
    only the nearest would answer a question nobody asked before bed."""
    _run(healthy)
    detail = _named("10_")["detail"]
    assert "overnight NKD 01:10-02:55 ET" in detail
    assert "roska4_calm" in detail


# ==============================================================================
# 6. no side effects
# ==============================================================================

def test_the_script_writes_nothing_into_the_repo(healthy, tmp_path):
    """Beyond its own JSON summary under scratch/. Checked by source, because a run that
    happened to write nothing today proves nothing about tomorrow's run."""
    src = Path(r"d:\raits\scratch\track1_presleep_readiness_20260824.py").read_text(
        encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    for forbidden in ("subprocess", "taskkill", "ib_insync", "placeOrder",
                      "STOP_TRADING", "start_scheduler", "start_backend", "os.remove",
                      "rmtree", "unlink"):
        assert forbidden not in code, forbidden
    assert code.count("write_text") == 1, "only the JSON summary may be written"


def test_the_summary_json_is_readable_and_names_its_verdict():
    path = Path(r"d:\raits\scratch\track1_presleep_readiness_20260824.json")
    if not path.exists():
        pytest.skip("script has not been run yet")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["verdict"] in (rd.READY, rd.WARNING, rd.NOT_READY)
    assert len(payload["checks"]) == 11
