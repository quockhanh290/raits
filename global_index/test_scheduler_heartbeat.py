"""global_index/test_scheduler_heartbeat.py — the scheduler must notice it stalled

Root cause measured 2026-08-06: threading.Event.wait(timeout) on Windows counts on a
clock that does not advance while the machine sleeps. BlockingScheduler waits ONCE for
the whole span to the next job, so every second asleep pushes that deadline back a
second — long after the machine is awake again.

  Night of 04→05: total sleep 1:27:37 → predicted wake 23:10:00 + 1:27:37 = 00:37:37.
                  APScheduler actually processed jobs at 00:37:22. 15 seconds out.
  Night of 05→06: sleep 2:51:27 + 0:42:21 pushed the 23:10 deadline to 02:43, past the
                  end of the NKD window at 00:55. 0 of 22 slots ran and NOT ONE LINE
                  was logged — no misfire, no error. The process sat there healthy.

Two things follow, and both are tested here.

  A heartbeat caps how long the scheduler can wait, so after a resume it re-evaluates
  within a minute instead of hours.

  The heartbeat measures itself on the WALL clock, which does advance during sleep. A
  gap between beats is the stall, reported as a number. Without it, "waiting quietly"
  and "dead" produce identical logs — which is why this went unnoticed for three nights
  while the night window degraded 22 slots → 4 → 0.
"""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.run_scheduler import (HEARTBEAT_SECS, heartbeat_alive_is_worth_logging,
                                        heartbeat_gap, make_scheduler)

_T0 = dt.datetime(2026, 8, 5, 14, 0, 28, tzinfo=dt.timezone.utc)


# ── stall detection ───────────────────────────────────────────────────────────

def test_hb1_a_beat_on_schedule_is_not_a_stall():
    assert heartbeat_gap(_T0, _T0 + dt.timedelta(seconds=HEARTBEAT_SECS)) is None


def test_hb2_small_jitter_is_not_a_stall():
    """Cron drift and a slow job must not cry wolf, or the real signal gets ignored."""
    assert heartbeat_gap(_T0, _T0 + dt.timedelta(seconds=HEARTBEAT_SECS + 5)) is None


def test_hb3_the_real_stall_is_reported_in_seconds():
    """The 05→06 night: 2h51m of sleep between two beats."""
    gap = heartbeat_gap(_T0, _T0 + dt.timedelta(hours=2, minutes=51, seconds=27))
    assert gap == pytest.approx(10287.0), (
        "a stall must come back as the number of seconds lost, not a boolean"
    )


def test_hb4_first_beat_has_nothing_to_compare_against():
    assert heartbeat_gap(None, _T0) is None


# ── recovery has to be as prompt as detection ─────────────────────────────────

def test_hb9_the_beat_after_a_stall_is_worth_logging():
    """The alarm turns on within a minute; its off switch must not take an hour.

    The beat runs every minute but writes "[HEARTBEAT] alive" at INFO only when the
    minute is 00 — 2880 lines a day is unreadable, so the throttle is right. What the
    throttle also delayed was the one line that says the stall is OVER: the journal
    reader marks recovery on an ALIVE line, so after a stall the dashboard carried a
    critical incident for up to 59 more minutes while the scheduler was demonstrably
    beating again.

    Measured 2026-08-17: stall detected 04:15 ET, healthy from 04:22, earliest possible
    "recovered" 05:00. Driving the real closure at minute 55 produced only a DEBUG line,
    which never reaches the file. An alarm whose off switch lags its on switch by an
    hour is one people learn to ignore.
    """
    assert not heartbeat_alive_is_worth_logging(37, False), (
        "an ordinary healthy beat at a plain minute must stay out of the log — the "
        "throttle exists for a reason and this must not undo it")
    assert heartbeat_alive_is_worth_logging(0, False), (
        "the hourly beat is the existing contract and must survive")
    assert heartbeat_alive_is_worth_logging(37, True), (
        "the first healthy beat after a stall is the line that clears the incident; "
        "withholding it to the next whole hour is what leaves the panel red")


def test_hb10_the_job_tracks_the_stall_and_clears_it(caplog):
    """A predicate nothing calls is H2 again — implemented, wired nowhere.

    Drives the REAL closure the scheduler registered, not a re-implementation, and
    asserts through the flag rather than the clock so it holds at every minute of the
    hour — including :00, where a clock-based assertion would pass for the wrong reason.
    """
    import logging
    from global_index import run_scheduler as rs

    job = _sched().get_job("heartbeat")
    assert job is not None and getattr(job, "func", None) is not None, (
        "no heartbeat job to drive — the locator is broken, not satisfied")

    rs._last_beat["t"] = None
    rs._stall_outstanding["v"] = False

    with caplog.at_level(logging.DEBUG, logger="run_scheduler"):
        job.func()                                   # first beat, nothing to compare
        assert rs._last_beat["t"] is not None, "the job did not record a beat at all"

        rs._last_beat["t"] = rs._last_beat["t"] - dt.timedelta(hours=1)
        caplog.clear()
        job.func()                                   # a sleeping machine looks like this
        assert any("STALLED" in r.getMessage() for r in caplog.records), (
            f"no stall reported, so the rest proves nothing: "
            f"{[r.getMessage()[:40] for r in caplog.records]}")
        assert rs._stall_outstanding["v"] is True, (
            "the stall was reported and immediately forgotten, so the next healthy "
            "beat has no reason to announce itself")

        caplog.clear()
        job.func()                                   # healthy again, whatever the minute
        shown = [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO]
        assert any("alive" in m for m in shown), (
            f"the beat after a stall stayed below INFO, so nothing marks recovery until "
            f"the next whole hour: {shown}")
        assert rs._stall_outstanding["v"] is False, (
            "the flag stayed set, so every later beat would keep announcing a stall "
            "that is already over")


# ── wiring ────────────────────────────────────────────────────────────────────

def _sched():
    return make_scheduler(port=4002, dry_run=True)


def test_hb5_scheduler_registers_the_heartbeat():
    ids = {j.id for j in _sched().get_jobs()}
    assert "heartbeat" in ids, (
        f"without it the scheduler waits ~9h between the last afternoon slot and the "
        f"first night slot, and a sleep in that span silently moves the whole window. "
        f"got {sorted(ids)[:8]}"
    )


def test_hb6_heartbeat_runs_every_day_not_just_weekdays():
    """A stall that starts on Saturday must still be visible on Sunday."""
    job = _sched().get_job("heartbeat")
    assert "mon-fri" not in str(job.trigger), f"trigger={job.trigger}"


def test_hb7_night_slots_tolerate_being_a_little_late():
    """APScheduler's default grace is 1s, so a slot a few seconds late is dropped.

    A slot late by minutes is still useful — diff_desired_vs_held is idempotent, so it
    does what the missed one would have. A slot late by hours is not, and the window
    has moved on; the grace must sit between those.
    """
    job = _sched().get_job("nkd_night_0110")
    assert job.misfire_grace_time is not None and job.misfire_grace_time > 1, (
        f"grace={job.misfire_grace_time} — the default drops every slot that arrives "
        f"even slightly late, which is what silence looked like on 2026-08-05"
    )
    assert job.misfire_grace_time <= 600, (
        f"grace={job.misfire_grace_time} is long enough to fire a slot whose window "
        f"has already closed"
    )


def test_hb8_every_live_day_slot_shares_the_same_grace():
    """One policy, not a split someone has to remember.

    Day slots run the same _live_day_body under the same 5-minute spacing and the same
    idempotency, so a separate rule for them would be arbitrary — and the kind of
    detail that rots.
    """
    sched = _sched()
    slots = [j for j in sched.get_jobs()
             if j.id.startswith("live_day") or j.id.startswith("nkd_night")]
    assert len(slots) >= 40, f"expected the full slot set, got {len(slots)}"

    # A pending job only carries the attributes it was given, so a missing one means
    # "never set" — which is the default 1s, which is the bug.
    graces = {j.id: getattr(j, "misfire_grace_time", None) for j in slots}
    ungraced = [i for i, g in graces.items() if g is None or g <= 1]
    assert not ungraced, (
        f"these slots still drop silently when they arrive late: {sorted(ungraced)}"
    )
    assert len(set(graces.values())) == 1, (
        f"slots disagree on how late is too late: {sorted(set(graces.values()))}"
    )


# ── the heartbeat must not bury what it was added to reveal ──────────────────
#
# APScheduler logs every dispatch at INFO. One beat a minute is 2880 lines a day of
# "Heartbeat 60s ... executed successfully" — measured at 22% of the log within hours
# of switching it on, with slot events sandwiched between them. A log nobody reads is
# the condition that let the original stall run for three nights.


def _rec(msg):
    import logging
    return logging.LogRecord("apscheduler.executors.default", logging.INFO,
                             __file__, 1, msg, None, None)


def test_hb9_heartbeat_dispatch_chatter_is_dropped():
    from global_index.run_scheduler import HeartbeatNoiseFilter

    f = HeartbeatNoiseFilter()
    assert not f.filter(_rec(
        'Job "Heartbeat 60s (trigger: cron[minute=\'*\'], next run at: '
        '2026-08-07 02:25:00 EDT)" executed successfully'))


def test_hb10_real_slot_dispatches_still_get_through():
    """These lines are the record that a slot fired — the thing being protected."""
    from global_index.run_scheduler import HeartbeatNoiseFilter

    f = HeartbeatNoiseFilter()
    assert f.filter(_rec(
        'Running job "NKD night run 02:20 ET (trigger: cron[hour=\'2\', '
        'minute=\'20\'])" (scheduled at 2026-08-07 02:20:00-04:00)'))
    assert f.filter(_rec('[NKD_NIGHT_0220] completed OK'))


def test_hb11_stall_warnings_are_never_filtered():
    """The one message the heartbeat exists to produce."""
    from global_index.run_scheduler import HeartbeatNoiseFilter

    f = HeartbeatNoiseFilter()
    assert f.filter(_rec("[HEARTBEAT] STALLED 10287s (expected ~60s)."))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
