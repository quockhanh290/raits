"""Stage 5ZZX — the backend console says what happened, not what was asked.

Measured on the retained backend log before anything changed, 358,361 lines:

    GET ... 200               337,972   94.3%
    GET ... 3xx                 8,860
    other                       8,036
    WARNING / ERROR             2,806
    "Adding job tentatively"      685    across six distinct days, in bursts
    "slots registered"              2

The reported symptom was "the window looks like jobs are continuously running". The cause is the
first line of that table, not the fifth: a page polling every eight seconds writes ten thousand
successful GETs a day whether the system is healthy or on fire.

The APScheduler lines are not continuous, and the burst dated today at 07:17:13 lands four
minutes BEFORE this backend logged "Starting Flask" at 07:21:12 — they are `ops.py` building a
scheduler object to enumerate it, with its console output going to the same file.

A filter that quietens a console has to be shown to keep everything that could be the first sign
of a problem, so most of this file is about what is NOT dropped.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from monitor.backend import app as backend_app                # noqa: E402


@pytest.fixture(scope="module")
def filters():
    return backend_app._QuietSuccessfulRequests(), backend_app._NoTentativeJobAdds()


def _rec(name, level, msg):
    return logging.LogRecord(name, level, __file__, 1, msg, None, None)


def _access(status, level=logging.INFO):
    return _rec("werkzeug", level,
                f'127.0.0.1 - - [28/Aug/2026 07:00:00] "GET /api/v1/all HTTP/1.1" {status} -')


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. the backend inspects a scheduler; it never starts one
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_only_the_scheduler_main_ever_starts_a_scheduler():
    """`sched.start()` appears exactly once in the tree, and not on any path the backend takes.

    Read from the source rather than asserted from the docstring that claims it: the claim and
    the code are two different things, and this file is the one that makes them agree.
    """
    import ast
    # Parsed, not grepped. The first version searched the TEXT and found a match inside this
    # stage's own docstring in app.py, which explains that `sched.start()` appears exactly once
    # in the tree — a claim ABOUT code, counted AS code. An AST walk cannot be fooled by prose.
    starts = []
    for path in sorted((REPO / "global_index").glob("*.py")) + \
            sorted((REPO / "monitor").rglob("*.py")):
        if "test" in path.name:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "start"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in {"sched", "scheduler"}):
                starts.append(path.relative_to(REPO).as_posix())
    # Stage 5ZZZ-BP. The FILE and the COUNT, not the line.
    #
    # This pinned `run_scheduler.py:1942`, and the line number plays no part in the claim above:
    # what matters is that `sched.start()` exists exactly once and only in the scheduler's own
    # module. Measured 2026-09-01, before any change in this stage, it had already drifted to
    # 2018 -- seventy-six lines of false failure guarding nothing. A pin that breaks whenever
    # somebody inserts a line above it teaches people the test is noise.
    assert starts == ["global_index/run_scheduler.py"], starts


def test_the_mirror_builds_a_scheduler_without_starting_it():
    from global_index import track1_slots as t1
    ids = t1.scheduler_slot_ids(track1_shadow=True, track1_only=True)
    assert ids, "no slot ids came back — the mirror is not reading the scheduler at all"
    assert any(i.startswith("track1_") for i in ids)


def test_a_schedule_status_request_does_not_change_the_scheduler_process():
    """The claim the stage rests on: reading the mirror is inspection, not execution."""
    from monitor import ops
    before = sorted(p.get("pid") for p in ops.scheduler_processes())
    client = backend_app.app.test_client()
    assert client.get("/api/v1/schedule-status").status_code == 200
    after = sorted(p.get("pid") for p in ops.scheduler_processes())
    assert before == after, (before, after)


@pytest.mark.parametrize("endpoint", ["/api/v1/schedule-status", "/api/v1/track1-runtime",
                                      "/api/v1/track1-market-view", "/api/v1/open-issues"])
def test_every_polled_endpoint_answers_200(endpoint):
    assert backend_app.app.test_client().get(endpoint).status_code == 200


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. what is dropped
# ══════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("status", ["200", "204", "301", "302", "304"])
def test_successful_polling_is_not_logged(filters, status):
    quiet, _ = filters
    assert quiet.filter(_access(status)) is False


def test_the_tentative_job_add_is_not_logged(filters):
    _, quiet = filters
    assert quiet.filter(_rec(
        "apscheduler.scheduler", logging.INFO,
        "Adding job tentatively -- it will be properly scheduled when the scheduler starts"
    )) is False


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. what is KEPT — the half that makes the filter safe
# ══════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("status", ["400", "401", "403", "404", "409", "422", "500", "502", "503"])
def test_every_failed_request_is_still_logged(filters, status):
    quiet, _ = filters
    assert quiet.filter(_access(status)) is True


def test_a_warning_survives_even_on_a_successful_request(filters):
    quiet, _ = filters
    assert quiet.filter(_access("200", level=logging.WARNING)) is True
    assert quiet.filter(_access("200", level=logging.ERROR)) is True


def test_a_line_the_filter_cannot_parse_is_kept(filters):
    """An unrecognised line is not a line to throw away. A filter that swallowed what it could
    not read would hide exactly the malformed cases worth seeing."""
    quiet, _ = filters
    assert quiet.filter(_rec("werkzeug", logging.INFO, "something unexpected entirely")) is True


def test_a_real_scheduler_starting_is_still_logged(filters):
    """The one APScheduler line that would mean a scheduler is genuinely running in this
    process. Dropping it along with the chatter would hide the thing the stage is about."""
    _, quiet = filters
    assert quiet.filter(_rec("apscheduler.scheduler", logging.INFO, "Scheduler started")) is True
    assert quiet.filter(_rec("apscheduler.executors.default", logging.INFO,
                             'Running job "job_live_day"')) is True


def test_a_job_that_could_not_be_added_is_still_logged(filters):
    _, quiet = filters
    assert quiet.filter(_rec("apscheduler.scheduler", logging.WARNING,
                             "Adding job tentatively -- but this one is a warning")) is True


def test_the_backend_still_logs_its_own_startup():
    """`logger.info` from the app is not routed through either filter."""
    for name in ("werkzeug", "apscheduler", "apscheduler.scheduler"):
        for f in logging.getLogger(name).filters:
            assert f.filter(_rec("monitor.backend.app", logging.INFO,
                                 "Starting Flask on http://127.0.0.1:5002")) is True


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. the filters are installed, on this process only
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_filters_are_attached_to_both_apscheduler_loggers():
    """A filter on the parent is not consulted for a record made by a child logger, so the line
    would still have been printed with only the parent filtered."""
    for name in ("apscheduler", "apscheduler.scheduler"):
        kinds = [type(f).__name__ for f in logging.getLogger(name).filters]
        assert "_NoTentativeJobAdds" in kinds, (name, kinds)
    kinds = [type(f).__name__ for f in logging.getLogger("werkzeug").filters]
    assert "_QuietSuccessfulRequests" in kinds, kinds


def test_nothing_global_was_disabled():
    """`logging.disable` would silence the scheduler's own log too if this ever ran in that
    process. The quieting is per-logger, and per-process by virtue of living in `app.py`."""
    # Only the global disable is asserted. The root LEVEL is owned by whoever runs the process
    # — pytest sets it to WARNING — and pinning it here would be testing the test runner.
    assert logging.getLogger().manager.disable == 0


def test_the_scheduler_log_file_is_untouched_by_this_stage():
    """The record of work actually done stays complete. A scheduler INFO line in the
    SCHEDULER's log is evidence; the same line in the backend's is an echo."""
    src = (REPO / "monitor" / "backend" / "app.py").read_text(encoding="utf-8")
    assert "logging.disable" not in src
    assert "basicConfig" in src and "level=logging.INFO" in src


def test_orders_remain_impossible():
    from global_index import track1_gates as G
    allowed, reasons = G.may_enable_orders()
    assert allowed is False
    assert "PAPER_SHADOW_EVIDENCE" in [r.split(":")[0] for r in reasons]
