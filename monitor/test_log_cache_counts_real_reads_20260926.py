# -*- coding: utf-8 -*-
"""The log memoisation is proved by counting file reads, not by watching the cache grow.

This replaces what test_a_file_that_did_not_change_is_not_read_again was trying to do. That
test detects a re-read by asking whether the cache GAINED an entry. After a warm-up it never
gains one, so its assertion is true whether the memoisation works or not. Measured 2026-09-26,
with a repaired stub signature and the scan entered seventy-four times in both runs:

    with the cache      the detector reported nothing
    cache neutralised   the detector reported nothing, and every file was parsed again

So repairing that test's signature would produce a test that passes in both worlds. The cost it
was written to protect is real -- twenty-five seconds a page load, thirteen of them regex over
lines parsed identically the previous twenty times -- which is why it is worth a test that can
actually fail.

What this file does instead: counts calls to the read that actually costs, and asserts the
second pass performs none of them. The second test neutralises the memoisation and asserts the
count goes UP, so the first test's ability to fail is itself pinned and cannot rot away.
"""
import pathlib
from pathlib import Path

import pytest

ROOT = Path(".")
DAY = "2026-08-10"


def _second_pass_log_reads(monkeypatch, *, neutralise_cache: bool) -> tuple[list[str], int]:
    """Warm the cache, then count the .log reads a second pass performs."""
    import monitor.backend.paper_evidence_reader as pe

    pe._file_cache.clear()
    pe._log_summary_uncached(ROOT, DAY)        # warm

    entered: list[str] = []
    saved_scan = pe._scan_one_log

    def _counting_scan(path, epoch, *, track1=False):
        entered.append(Path(path).name)
        return saved_scan(path, epoch, track1=track1)
    monkeypatch.setattr(pe, "_scan_one_log", _counting_scan)

    if neutralise_cache:
        class _NoStore(dict):
            def __setitem__(self, key, value):
                pass

            def get(self, key, default=None):
                return default
        monkeypatch.setattr(pe, "_file_cache", _NoStore())

    reads: list[str] = []
    real_read_text = pathlib.Path.read_text

    def _counting_read_text(self, *a, **kw):
        if self.suffix == ".log":
            reads.append(self.name)
        return real_read_text(self, *a, **kw)
    monkeypatch.setattr(pathlib.Path, "read_text", _counting_read_text)

    pe._log_summary_uncached(ROOT, DAY)        # the pass under measurement
    return reads, len(entered)


def test_a_warm_second_pass_reads_no_log_file_from_disk(monkeypatch):
    reads, entered = _second_pass_log_reads(monkeypatch, neutralise_cache=False)

    assert entered, (
        "the scan was never entered, so this measured nothing. Either the day has no logs on "
        "this machine or the walk changed shape")
    assert reads == [], (
        "the memoisation did not hold: the second pass read %d log file(s) from disk, starting "
        "with %r" % (len(reads), reads[:3]))


def test_the_check_above_can_fail__with_the_memoisation_removed_it_reads_again(monkeypatch):
    """Without this, the test above is satisfied by a run that reads nothing under any condition."""
    reads, entered = _second_pass_log_reads(monkeypatch, neutralise_cache=True)

    assert entered, "the scan was never entered, so this measured nothing"
    assert reads, (
        "with the memoisation neutralised the second pass STILL read no log file. That means the "
        "counter above cannot detect a re-read, and the test beside it is proving nothing")
    assert len(reads) == entered, (
        "every entered scan should have re-read its file with the cache gone: %d reads against "
        "%d scans" % (len(reads), entered))
