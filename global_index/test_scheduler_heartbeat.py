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

from global_index.run_scheduler import HEARTBEAT_SECS, heartbeat_gap, make_scheduler

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
