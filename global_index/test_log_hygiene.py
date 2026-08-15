"""The operator's log file: who may write to it, and what it is named.

Two separate bugs, both from attaching a FileHandler at import time.

1. IMPORTING is not RUNNING. The handler went on the ROOT logger, so any process
   that imported run_scheduler redirected the whole application's logging into the
   operator's alert file. The 2026-08-10 pytest run put 1,215 lines into
   scheduler_0810.log — CRITICAL "position is UNPROTECTED", "Roll OPEN FAILED ...
   position is FLAT IN IBKR" — every one from an injected-failure fixture, and not
   one real scheduler line in the file. A log full of fake CRITICALs teaches the
   operator to skim past the real one.

2. The NAME was computed once, at import. The scheduler runs for days, so the
   process started 2026-08-09 wrote 08-10 into scheduler_0809.log. The NKD night
   slots and the 09:31 MAX_HOLD exit were all recorded — under a filename that said
   they belonged to the day before. Looking for last night's slots in last night's
   file found it empty, and "the log is empty" reads exactly like "the window never
   ran", which is the failure the heartbeat exists to catch.
"""
from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from global_index import run_live_day as rld
from global_index import run_scheduler as rs


def _file_handlers(paths_only: bool = True):
    """Every FileHandler currently on the root logger."""
    out = []
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.FileHandler):
            out.append(h.baseFilename if paths_only else h)
    return out


# ── 1. importing must not attach anything ────────────────────────────────────

def test_lh1_importing_scheduler_attaches_no_file_handler():
    """This test file imports run_scheduler at module scope. If the import attached
    a handler, this process would be writing into the operator's log right now."""
    assert not [p for p in _file_handlers() if "scheduler_" in Path(p).name], (
        "importing run_scheduler attached a FileHandler — pytest is writing into "
        "the operator's alert log")


def test_lh2_importing_live_day_attaches_no_file_handler():
    assert not [p for p in _file_handlers() if "live_day_" in Path(p).name], (
        "importing run_live_day attached a FileHandler")


def test_lh3_attaching_is_available_on_purpose():
    """Not attached at import is not the same as gone. main() must still be able to."""
    assert callable(rs.attach_file_log)
    assert callable(rld.attach_file_log)


def test_lh4_main_attaches_it(monkeypatch, tmp_path):
    """The guard is worthless if nobody calls it — that would silently lose the log.

    Stops right after the attach: main() goes on to build a scheduler and block.
    """
    called = {}
    monkeypatch.setattr(rs, "attach_file_log", lambda: called.setdefault("yes", True))
    monkeypatch.setattr(sys, "argv", ["run_scheduler", "--dry-run"])

    class _Stop(Exception):
        pass

    def _boom():
        raise _Stop
    monkeypatch.setattr(rs, "_load_preflight_state", _boom)
    with pytest.raises(_Stop):
        rs.main()
    assert called.get("yes"), "main() no longer attaches the file log"


# ── 2. the name must follow the calendar, not the start date ─────────────────

class _FrozenDate(date):
    _today = date(2026, 8, 9)

    @classmethod
    def today(cls):
        return cls._today


@pytest.fixture
def frozen(monkeypatch):
    _FrozenDate._today = date(2026, 8, 9)
    monkeypatch.setattr(rs, "_date", _FrozenDate)
    return _FrozenDate


def _rec(msg="x"):
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)


def test_lh5_rolls_when_the_day_changes(frozen, tmp_path):
    """The regression itself: 08-10 lines must not land in scheduler_0809.log."""
    h = rs.DailyFileHandler(tmp_path, "scheduler_")
    h.setFormatter(logging.Formatter("%(message)s"))

    h.emit(_rec("dem 08-09"))
    assert Path(h.baseFilename).name == "scheduler_0809.log"

    frozen._today = date(2026, 8, 10)
    h.emit(_rec("night slot + maxhold 08-10"))
    assert Path(h.baseFilename).name == "scheduler_0810.log", (
        "a scheduler started on 08-09 is still writing 08-10 into the 08-09 file")
    h.close()

    assert "dem 08-09" in (tmp_path / "scheduler_0809.log").read_text(encoding="utf-8")
    day2 = (tmp_path / "scheduler_0810.log").read_text(encoding="utf-8")
    assert "night slot + maxhold 08-10" in day2
    assert "dem 08-09" not in day2, "yesterday's lines leaked into today's file"


def test_lh6_same_day_keeps_one_stream(frozen, tmp_path):
    """No reopen churn: rolling must be driven by the date, not by every emit."""
    h = rs.DailyFileHandler(tmp_path, "scheduler_")
    h.setFormatter(logging.Formatter("%(message)s"))
    h.emit(_rec("a"))
    first = h.stream
    h.emit(_rec("b"))
    assert h.stream is first
    h.close()
    assert (tmp_path / "scheduler_0809.log").read_text(encoding="utf-8").count("\n") == 2


def test_lh7_creates_nothing_until_something_is_logged(frozen, tmp_path):
    """delay=True — an import that logs nothing must leave no file behind.

    Without it, every pytest process would drop an empty scheduler_<today>.log into
    the repo root, which is how the noise looked like real activity in the first place.
    """
    rs.DailyFileHandler(tmp_path, "scheduler_")
    assert list(tmp_path.iterdir()) == []


def test_lh8_heartbeat_noise_is_still_filtered(frozen, tmp_path):
    """attach_file_log carries the filter; losing it means 2,880 lines a day."""
    h = rs.DailyFileHandler(tmp_path, "scheduler_")
    h.addFilter(rs.HeartbeatNoiseFilter())
    h.setFormatter(logging.Formatter("%(message)s"))
    assert h.filter(_rec('Running job "Heartbeat 60s ..."')) is False
    assert h.filter(_rec("[HEARTBEAT] alive")) is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ── 9. the pytest guard itself ───────────────────────────────────────────────
#
# lh1/lh2 prove the handler is not attached AT IMPORT. They say nothing about a test
# that reaches attach_file_log() through some other path -- and one did: on 2026-08-10
# pytest wrote 1,215 injected-failure CRITICALs plus a whole mock MES replay into
# scheduler_0810.log, and reading it cold looked like the system had failed badly.
#
# The fix was a PYTEST_CURRENT_TEST guard inside both attach_file_log functions. Nothing
# tested that guard, so removing it would have left all eight tests above green while
# pytest quietly resumed writing into the operator's log. Measured 2026-08-15: no log
# file written after 2026-08-10 carries a test marker, which is the guard working.

def test_lh9_scheduler_refuses_to_attach_under_pytest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_lh9 (call)")
    before = set(_file_handlers(paths_only=True))
    rs.attach_file_log()
    after = set(_file_handlers(paths_only=True))
    assert after == before, "run_scheduler attached a file handler while pytest was running"
    assert not list(tmp_path.glob("scheduler_*.log")), "a production log was created by a test"


def test_lh10_live_day_refuses_to_attach_under_pytest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_lh10 (call)")
    before = set(_file_handlers(paths_only=True))
    rld.attach_file_log()
    after = set(_file_handlers(paths_only=True))
    assert after == before, "run_live_day attached a file handler while pytest was running"
    assert not list(tmp_path.glob("live_day_*.log")), "a production log was created by a test"


def test_lh11_the_guard_is_the_reason_and_not_a_missing_cwd(tmp_path, monkeypatch):
    """Without the env var the same call must attach — otherwise lh9/lh10 would pass
    for the wrong reason and the operator would lose the log entirely."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    root = logging.getLogger()
    added = None
    try:
        rld.attach_file_log()
        added = [h for h in root.handlers
                 if isinstance(h, logging.FileHandler)
                 and "live_day_" in Path(h.baseFilename).name]
        assert added, "attach_file_log did nothing even outside pytest"
    finally:
        for h in added or []:
            root.removeHandler(h)
            h.close()
