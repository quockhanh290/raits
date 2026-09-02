"""Stage 5ZZZ-BZ. The evening ladder called itself finished while a later rung was still due.

`SPY_REFRESH_PM_R2` mapped to `None` in the ladder table, which puts it on the error branch:

    LAST ATTEMPT - the daily series still ends on 2026-08-31, not 2026-09-01. Tomorrow's
    Track 1 slots that run before the 13:45 pre-flight - the overnight NKD window and BOTH
    Calm phases - will refuse on `regime_csv: stale`. Re-run by hand or expect no evidence.

Measured across the scheduler logs:

    2026-08-25  succeeded at the FIRST rung, 16:20 ET
    2026-08-27  16:20 / 16:45 / 17:15 all failed
    2026-08-28  same
    2026-08-31  same -- then RECOVERED at 00:45 ET the next morning
    2026-09-01  same

Four consecutive trading days ended in that ERROR, and on none of them did anything refuse.
Two independent reasons, either of which is enough:

  * `spy_last_chance_pre_nkd` runs at 00:45 ET, twenty-five minutes before the NKD window, and
    fetched the missing day each night. The 2026-08-31 log carries its own word for it:
    "RECOVERED at the last look".
  * The stale guard's SOFT threshold is more than two business days, and HARD is more than
    five. A one-day gap never reaches either.

Confirmed against the provider directly at 00:05 ET on 2026-09-02: the 2026-09-01 close was
absent when R2 ran at 17:15 ET and present a few hours later. The rungs are early; the ladder
is not broken.

So the message was wrong twice over -- there WAS a later attempt, and the consequence it named
could not follow from a one-day gap -- and it filed a scheduler failure into Open Issues every
trading day. An alarm that fires every day when nothing is wrong is one this project has
already written down what happens to.
"""
from __future__ import annotations

import inspect
import re

from global_index import run_scheduler as RS


def _ladder() -> dict:
    """The table as the scheduler builds it, read out of `make_scheduler`'s source.

    It is a local inside the factory, so there is nothing importable to assert against. Parsed
    rather than retyped: a copy here would agree with itself while the scheduler disagreed.
    """
    src = inspect.getsource(RS.make_scheduler)
    m = re.search(r"_SPY_LADDER_NEXT = (\{.*?\})", src, re.S)
    assert m, "the ladder table is gone or renamed"
    return eval(m.group(1))  # noqa: S307 - a literal dict from our own source


def _registered_times() -> dict:
    """Every SPY rung's cron time, from the decorators that register them."""
    src = inspect.getsource(RS.make_scheduler)
    out = {}
    for m in re.finditer(
            r'scheduled_job\("cron"[^)]*?hour=(\d+), minute=(\d+),\s*\n?\s*id="(spy_[a-z_0-9]+)"',
            src, re.S):
        out[m.group(3)] = "%02d:%02d" % (int(m.group(1)), int(m.group(2)))
    assert out, "no SPY rung was found -- the probe is wrong, not the answer"
    return out


def test_the_last_evening_rung_points_at_the_rung_that_actually_lands():
    """The defect, in one entry. `None` puts R2 on the branch that claims there is nothing
    after it and demands a manual re-run."""
    assert _ladder()["SPY_REFRESH_PM_R2"] == "00:45", _ladder()


def test_every_rung_names_a_time_that_a_registered_job_runs_at():
    """A ladder pointing at a time nothing runs is a promise of a rescue that never comes."""
    times = set(_registered_times().values())
    for label, nxt in _ladder().items():
        if nxt is None:
            continue
        assert nxt in times, (label, nxt, sorted(times))


def test_the_last_chance_rung_is_still_registered_before_the_nkd_window():
    """The whole fix rests on it existing and running BEFORE 01:10 ET. If it moves, the entry
    above becomes a lie and this fails rather than the alarm silently going quiet."""
    times = _registered_times()
    assert "spy_last_chance_pre_nkd" in times, times
    assert times["spy_last_chance_pre_nkd"] == "00:45", times
    assert times["spy_last_chance_pre_nkd"] < "01:10", times


def test_the_error_branch_still_exists_for_a_rung_with_no_successor():
    """Silencing the alarm everywhere would be the opposite mistake. A rung that genuinely has
    nothing after it must still say so."""
    src = inspect.getsource(RS.make_scheduler)
    assert "LAST ATTEMPT" in src, "the error branch was removed rather than re-pointed"
    assert "nxt = _SPY_LADDER_NEXT.get(label)" in src, src[:200]


def test_no_rung_claims_a_consequence_the_guard_does_not_have():
    """The message asserted that a one-day gap makes the overnight window refuse. The guard's
    soft threshold is more than two business days and hard is more than five, so it cannot.

    Read from the guard rather than restated, so the day someone tightens it this test is what
    notices.
    """
    from global_index import hmm_stale_guard as G

    doc = (G.__doc__ or "") + (inspect.getsource(G)[:4000])
    soft = re.search(r"SOFT\s*>\s*(\d+)\s*bday", doc)
    hard = re.search(r"HARD\s*>\s*(\d+)\s*bday", doc)
    assert soft and hard, doc[:300]
    assert int(soft.group(1)) >= 2, soft.group(1)
    assert int(hard.group(1)) > int(soft.group(1)), (soft.group(1), hard.group(1))
