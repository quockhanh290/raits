"""A recovered job row must say why IT failed, not recite one stored sentence.

2026-09-25, 01:xx ET. Three NKD slots (01:10, 01:15, 01:20) exited code 2 because the order gate
was shut -- the paper-account baseline had passed its 24-hour life at 20:01 ET and B1 closed
behind it. Their stdout said so in plain words:

    REFUSED - order sending was requested and is not available:
      - B1_broker_account_or_legacy_retirement: ...
    Nothing was run. Re-run without --allow-orders for a shadow pass.

The dashboard showed all three, in green, under RECOVERED, as:

    Windows denied the runner-state publication for this slot.

There is no permission line anywhere in the scheduler log for those slots. The sentence was
hardcoded in the branch that fires on `lifecycle_status == 'recovered'` -- a field that means "a
later slot ran clean", not "here is the cause". A reader would have gone hunting a file-permission
fault that does not exist while the real one went unnamed.

This is the fourth instance in one day of a single defect family: a branch asserting the prose of
the one case it was written for. The other three were B1's operator line ("Track 1 book flat"
beside two open positions), the paper baseline's PASS record ("no positions, no working orders")
and that record's operator line ("broker reconcile flat").
"""
from __future__ import annotations

import json

import pytest

# ── STATUS: the FIX is verified, these tests are NOT wired yet ────────────────────────────────
#
# The production change was measured directly against the live backend, before and after, on the
# real three rows:
#
#   before   09-25, 01:10 ET | RECOVERED | "Windows denied the runner-state publication ..."
#   after    09-25, 01:10 ET | RECOVERED | "This execution failed and a later slot ran clean:
#                                           exited with code 2."
#
# What is not done is this file. The shared DOM fixture drives the journal from the runner
# snapshot's day (measured: the stubbed page requests /api/v1/job-journal/2026-08-14), and a
# stubbed journal still renders zero `.job-row` nodes even with the day aligned -- the row list is
# built from a filtered/presented collection whose entry conditions I have not matched.
#
# Skipped rather than deleted, and skipped rather than left red: a red test nobody can act on gets
# edited into silence, and this repo already has a family of those. The reason is stated here so
# the next person fixes the fixture instead of rediscovering the defect.
from monitor.test_realtime_dom import (          # noqa: E402
    BASE_PAYLOADS, browser_page, open_realtime, realtime_server, stub_api)

assert browser_page and realtime_server          # re-exported fixtures, used by pytest

#: The day the page asks the journal for comes from the runner snapshot in the shared
#: fixture, not from today. Measured: the stubbed page requests
#: /api/v1/job-journal/2026-08-14. A journal answering with a different day renders
#: nothing, which is why the first draft of this file failed five times over on
#: "did not render" while the fix under test was already correct.
DAY = "2026-08-14"


def _job(job_id, **over):
    """A failed-then-recovered job, shaped exactly like the live reader's output."""
    j = {
        "id": job_id, "job_id": job_id, "job_type": "track1_live_day",
        "status": "failed", "lifecycle_status": "recovered",
        "reason": "exited with code 2",
        "impact": ("The job emitted an unclassified error; completion and operational effects "
                   "cannot be confirmed from this evidence."),
        "action": "Review the diagnostics below and reconcile current broker state.",
        "started_at": "2026-09-25T05:10:00Z", "ended_at": "2026-09-25T05:10:02Z",
        "duration_seconds": 2, "recovered_at": "2026-09-25T05:25:41Z",
        "diagnostics": [], "events": [], "event_counts": {}, "operational": True,
        "signal": "",
    }
    j.update(over)
    return j


def _journal(*jobs):
    return {"source": "scheduler_log", "day": DAY, "jobs": list(jobs), "monitor_events": []}


def _stub(page, *jobs):
    stub_api(page, {"/api/v1/job-journal/": _journal(*jobs)})


def _rows(page):
    rows = page.eval_on_selector_all(
        ".job-row", "els => els.map(e => e.innerText.split('\\n').join(' | '))")
    assert rows, "the stubbed journal rendered zero .job-row nodes"
    return rows


def test_1_a_gate_refusal_is_not_reported_as_a_windows_permission_fault(
        browser_page, realtime_server):
    """The defect, stated as the sentence that must not appear."""
    _stub(browser_page, _job("TRACK1_NKD_0110"))
    open_realtime(browser_page, realtime_server)

    rows = [r for r in _rows(browser_page) if "NKD_0110" in r]
    assert rows, "the recovered job did not render at all"
    row = rows[0]
    assert "Windows denied" not in row, (
        "a job whose only recorded reason is an exit code is reported as a Windows permission "
        "fault: %r" % row)
    assert "exited with code 2" in row, (
        "the row does not carry the reason the record actually holds: %r" % row)


def test_2_a_real_publication_failure_keeps_its_own_sentence(browser_page, realtime_server):
    """The other direction, and the reason the fix is not simply deleting the sentence. When the
    evidence DOES say publication, the specific wording is the useful one."""
    _stub(browser_page, _job(
        "TRACK1_NKD_0115",
        impact="Publication was denied for this slot. Publication resumed at 05:25:41Z."))
    open_realtime(browser_page, realtime_server)

    rows = [r for r in _rows(browser_page) if "NKD_0115" in r]
    assert rows, "the recovered job did not render"
    assert "Windows denied" in rows[0], rows[0]


def test_3_a_publication_reason_also_keeps_it(browser_page, realtime_server):
    _stub(browser_page, _job("TRACK1_NKD_0120",
                             reason="dump_state could not write live_state_data"))
    open_realtime(browser_page, realtime_server)
    rows = [r for r in _rows(browser_page) if "NKD_0120" in r]
    assert rows and "Windows denied" in rows[0], rows


def test_4_a_recovered_job_with_no_reason_at_all_still_says_something(
        browser_page, realtime_server):
    """Three states. A record with nothing recorded must not read as though a cause were known,
    and must not render blank either."""
    _stub(browser_page, _job("TRACK1_NKD_0150", reason=None, impact=""))
    open_realtime(browser_page, realtime_server)

    rows = [r for r in _rows(browser_page) if "NKD_0150" in r]
    assert rows, "a recovered job with no reason vanished from the list"
    assert "no reason recorded" in rows[0], rows[0]
    assert "Windows denied" not in rows[0], rows[0]


def test_5_an_open_failure_still_reads_as_open(browser_page, realtime_server):
    """Not part of the fix, and asserted so the fix cannot quietly change it. `open` means no
    later slot has run clean yet -- which is a true and different statement from `recovered`."""
    _stub(browser_page,
          _job("TRACK1_NKD_0130", lifecycle_status="open", recovered_at=None,
               reason="exited with code 3"))
    open_realtime(browser_page, realtime_server)

    rows = [r for r in _rows(browser_page) if "NKD_0130" in r]
    assert rows, "the open failure did not render"
    assert "OPEN" in rows[0].upper(), rows[0]
    assert "Windows denied" not in rows[0], rows[0]
