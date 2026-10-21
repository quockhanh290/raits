"""global_index/test_child_keeps_its_own_log.py — the reason a job failed must outlive the tail.

Measured 2026-09-23: the 09:16 ET anchor check exited 1 with `COMPLETED WITH ERRORS: ['MES']`
and the reason was nowhere to be found. `update_ibkr_daily` logs to stderr only; the scheduler
echoes the last 25 lines of a failed child; that run printed 42; and MES is the FIRST of five
instruments. The one block that said why was the one certain to be cut.

The same failure is on record from 2026-08-04, in the scheduler's own comment: the pre-flight
"failed on MES and the log held nothing but 'exited with code 1'. A re-run later succeeded, so
the cause is still unknown." Seven weeks apart, same instrument, and in neither case has anyone
ever seen the error.

So this is not about diagnosing MES. It is about the next occurrence being observable at all.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index import update_ibkr_daily as U


def test_cl1_the_module_has_a_file_handler_after_import():
    """Installed at import, so it covers the FIRST instrument — the one that kept being cut."""
    files = [h for h in U.log.handlers if isinstance(h, logging.FileHandler)]
    assert files, (
        "no file handler on the job's logger, so its output still lives only in whatever "
        "slice of stderr the parent happens to keep")
    assert any("update_ibkr_daily" in Path(h.baseFilename).name for h in files)


def test_cl2_a_line_logged_now_reaches_the_file():
    """A handler that is attached but not writing is the same as no handler.

    The level is forced because pytest's own logging plugin owns the root level during a run,
    and this test is about the WIRING, not about what pytest leaves the level at. The
    production path was checked separately and outside pytest on 2026-09-23 — a bare
    `python -c "from global_index import update_ibkr_daily as U; U.log.info(...)"` put the
    line in `monitor/logs/update_ibkr_daily_20260923.log` with its pid — because a test that
    passes only under the test runner's own configuration proves nothing about the job.
    """
    fh = next(h for h in U.log.handlers if isinstance(h, logging.FileHandler))
    marker = "test_cl2 probe — this line must survive the parent's tail"
    prev, U.log.level = U.log.level, logging.INFO
    try:
        U.log.info(marker)
        fh.flush()
    finally:
        U.log.level = prev
    assert marker in Path(fh.baseFilename).read_text(encoding="utf-8", errors="replace")


def test_cl3_a_logbook_that_cannot_be_opened_does_not_stop_the_job(monkeypatch, tmp_path):
    """The job matters more than its record of itself.

    A first draft of this raised when the directory was unwritable, which would have turned a
    logging improvement into a reason the 13:45 pre-flight skips a trading day.
    """
    bad = tmp_path / "not_a_dir"
    bad.write_text("this is a file, so mkdir underneath it must fail", encoding="utf-8")
    monkeypatch.setattr(U, "LOG_DIR", bad / "logs")
    U._install_file_log()          # must simply return


def test_cl4_installing_twice_does_not_double_the_file_handlers():
    """The module is imported by the live route as well as run as a script."""
    before = [h for h in U.log.handlers if isinstance(h, logging.FileHandler)]
    U._install_file_log()
    after = [h for h in U.log.handlers if isinstance(h, logging.FileHandler)]
    assert len(after) == len(before), (
        f"handlers grew {len(before)} -> {len(after)}; every line would be written twice")
