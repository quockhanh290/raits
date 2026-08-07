"""The 09:31 MAX_HOLD exit, when the scheduler came up after it.

APScheduler schedules the NEXT occurrence at startup. A scheduler started at 09:43
does not have a late 09:31 job, it has no 09:31 job at all — no misfire, no error,
nothing logged. That happened on 2026-08-05 and 2026-08-06 and was noticed only by
reading the log for something else.

The exits that job performs are 15% of all trades and average +$398.60, against
-$48.84 for the chandelier exits that make up 79.5% — the edge leaves through this
one job. Missing it pushes the exit to ~14:10 via run_live_day, 4h40 past the 09:30
bar every recorded number was produced under.

A path that fires once a morning and stays silent when it does not is the kind that
rots unnoticed, so each branch is pinned here rather than left to the next reader.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import global_index.run_scheduler as rs

ET = ZoneInfo("America/New_York")


class _Job:
    def __init__(self):
        self.calls = []

    def func(self, label="MAX_HOLD_EXIT"):
        self.calls.append(label)
        return True


class _FailJob(_Job):
    def func(self, label="MAX_HOLD_EXIT"):
        self.calls.append(label)
        return False


class _Sched:
    def __init__(self, job=None):
        self._job = job

    def get_job(self, _id):
        return self._job


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Never touch the real state file, and never inherit a previous test's day."""
    monkeypatch.setattr(rs, "_MAXHOLD_STATE", tmp_path / "maxhold.json")
    rs._maxhold_done.clear()
    yield
    rs._maxhold_done.clear()


def _at(monkeypatch, when: datetime):
    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return when
    monkeypatch.setattr("datetime.datetime", _DT)


def test_runs_when_started_after_0931(monkeypatch):
    """The case that happened twice: up at 09:43, today's slot already gone."""
    _at(monkeypatch, datetime(2026, 8, 10, 9, 43, tzinfo=ET))
    job = _Job()
    rs._catch_up_maxhold(_Sched(job))
    assert job.calls == ["MAX_HOLD_EXIT_CATCHUP"]


def test_silent_before_0931(monkeypatch):
    """Before the slot the cron fires it normally — catching up would double-run."""
    _at(monkeypatch, datetime(2026, 8, 10, 8, 15, tzinfo=ET))
    job = _Job()
    rs._catch_up_maxhold(_Sched(job))
    assert job.calls == []


def test_boundary_0931_runs(monkeypatch):
    """09:31 exactly counts as reached. A cron that has just fired records the day
    and the state check below stops the duplicate; a cron that has not gets covered."""
    _at(monkeypatch, datetime(2026, 8, 10, 9, 31, tzinfo=ET))
    job = _Job()
    rs._catch_up_maxhold(_Sched(job))
    assert job.calls == ["MAX_HOLD_EXIT_CATCHUP"]


def test_skips_when_already_done_today(monkeypatch):
    """Restarting the scheduler three times in an afternoon must not close positions
    three times — the whole reason the day is recorded on disk."""
    _at(monkeypatch, datetime(2026, 8, 10, 14, 0, tzinfo=ET))
    rs._maxhold_done["2026-08-10"] = True
    job = _Job()
    rs._catch_up_maxhold(_Sched(job))
    assert job.calls == []


def test_yesterdays_record_does_not_count(monkeypatch):
    """Keyed by date, so a stale file cannot vouch for a day it does not name."""
    _at(monkeypatch, datetime(2026, 8, 10, 10, 0, tzinfo=ET))
    rs._maxhold_done["2026-08-07"] = True
    job = _Job()
    rs._catch_up_maxhold(_Sched(job))
    assert job.calls == ["MAX_HOLD_EXIT_CATCHUP"]


def test_silent_at_weekend(monkeypatch):
    """2026-08-08 is a Saturday: no session, nothing to exit."""
    _at(monkeypatch, datetime(2026, 8, 8, 11, 0, tzinfo=ET))
    job = _Job()
    rs._catch_up_maxhold(_Sched(job))
    assert job.calls == []


# ── the recording itself lives in the job closure, shared by cron and catch-up ──
#
# The tests above use a stand-in job and so can only check whether the catch-up
# DECIDES to run. Whether a run is recorded is job_maxhold's contract, and the two
# below exercise the real closure — otherwise "failure is not recorded" would pass
# because nothing records anything.

def _real_job(monkeypatch, *, succeeds: bool, dry_run: bool = False):
    monkeypatch.setattr(rs, "_run", lambda *a, **k: succeeds)
    sched = rs.make_scheduler(port=4002, dry_run=dry_run)
    return sched.get_job("maxhold_exit")


def test_success_is_recorded(monkeypatch):
    """Recorded, so restarting the scheduler later the same day does not close
    positions a second time."""
    _at(monkeypatch, datetime(2026, 8, 10, 10, 0, tzinfo=ET))
    job = _real_job(monkeypatch, succeeds=True)
    assert job.func() is True
    assert rs._maxhold_done.get("2026-08-10") is True


def test_failure_is_not_recorded(monkeypatch):
    """A failed run must stay eligible. Recording it would mean the next restart
    skips a job that never closed anything — silence on top of silence."""
    _at(monkeypatch, datetime(2026, 8, 10, 10, 0, tzinfo=ET))
    job = _real_job(monkeypatch, succeeds=False)
    assert job.func() is False
    assert "2026-08-10" not in rs._maxhold_done


def test_dry_run_is_not_recorded(monkeypatch):
    """_run returns True under --dry-run without executing anything. Recording that
    would mark the day done when nothing closed, and the next real scheduler would
    skip the catch-up — a rehearsal disabling the thing it rehearses. Seen for real:
    one --dry-run startup wrote {"2026-08-07": true} before this guard existed."""
    _at(monkeypatch, datetime(2026, 8, 10, 10, 0, tzinfo=ET))
    job = _real_job(monkeypatch, succeeds=True, dry_run=True)
    assert job.func() is True
    assert "2026-08-10" not in rs._maxhold_done


def test_failed_catchup_logs_critical(monkeypatch, caplog):
    """The operator has to learn about it from somewhere."""
    _at(monkeypatch, datetime(2026, 8, 10, 10, 0, tzinfo=ET))
    job = _FailJob()
    with caplog.at_level("CRITICAL"):
        rs._catch_up_maxhold(_Sched(job))
    assert any(r.levelname == "CRITICAL" for r in caplog.records)


def test_missing_job_does_not_raise(monkeypatch):
    """Startup must survive a missing job id. Failing here would stop the whole
    scheduler over one exit, taking the trading day with it."""
    _at(monkeypatch, datetime(2026, 8, 10, 10, 0, tzinfo=ET))
    rs._catch_up_maxhold(_Sched(None))


def test_state_survives_a_restart(tmp_path, monkeypatch):
    """The record has to reach disk — each slot is a fresh process."""
    _at(monkeypatch, datetime(2026, 8, 10, 10, 0, tzinfo=ET))
    rs._maxhold_done["2026-08-10"] = True
    rs._save_maxhold_state()
    rs._maxhold_done.clear()
    rs._load_maxhold_state()
    assert rs._maxhold_done.get("2026-08-10") is True


def test_unreadable_state_reruns(monkeypatch):
    """A torn file reads as 'not run', which re-runs an idempotent job — the safe
    direction. Reading it as done would skip a real exit."""
    _at(monkeypatch, datetime(2026, 8, 10, 10, 0, tzinfo=ET))
    rs._MAXHOLD_STATE.write_text("{ this is not json")
    rs._load_maxhold_state()
    job = _Job()
    rs._catch_up_maxhold(_Sched(job))
    assert job.calls == ["MAX_HOLD_EXIT_CATCHUP"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
