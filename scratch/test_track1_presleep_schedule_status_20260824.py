"""A Track 1 slot that passed before the scheduler existed is not late. 2026-08-24.

Read-only: nothing here starts, stops, connects or writes outside tmp_path.

The false alarm
---------------
The operator started a track1-only session at 04:32 ET. The NKD window is 01:10-02:55 ET,
so all 22 NKD slots had already passed. Measured against the running backend:

    freshness: late
    unexplained_overdue: 22
    TRACK1_NKD_0110 not_observed unknown watch 2026-08-24T05:10:00Z
    ... 21 more

Every one of those slots is "unobserved" for the only reason a slot can be unobserved
without anything being wrong: there was no process to observe it. The acceptance gate
already reasons this way -- a window that closed before the scheduler existed is
NOT_ENOUGH_DATA_YET, never a failure. The dashboard disagreeing with the gate is how an
operator wakes up to a "pipeline late" banner over a route that had not been asked to do
anything yet, and learns to stop reading the banner.

What must NOT change
--------------------
The rule has to be narrow enough that it cannot hide a real miss. Three limits, one test
each below: it needs the slot to have NO evidence, it needs the slot to be strictly before
the start instant, and it is scoped to Track 1 ids so legacy's alarm surface is untouched.
"""
from __future__ import annotations

import datetime as dt
import sys

import pytest

sys.path.insert(0, r"d:\raits")

from monitor.backend import schedule_status as ss   # noqa: E402

ET = ss.ET

# 04:32 ET -- the real start instant of the session this fix was measured against.
START_ET = dt.datetime(2026, 8, 24, 4, 32, 24, tzinfo=ET)
# 09:00 ET: after the NKD window (01:10-02:55) closed, and before the Calm slot (10:00),
# so "today" holds passed Track 1 slots that a start instant can sit on either side of.
NOW_ET = dt.datetime(2026, 8, 24, 9, 0, tzinfo=ET)


@pytest.fixture
def root(tmp_path):
    """A tree whose scheduler log exists but is empty -- so evidence is genuinely absent
    rather than merely unreadable. `log_available` stays True, which is the production
    shape: the log is there, it just holds no line for these slots."""
    (tmp_path / "scheduler.log").write_text("", encoding="utf-8")
    return tmp_path


@pytest.fixture
def track1_only(monkeypatch):
    monkeypatch.setenv("RAITS_TRACK1_ONLY", "1")
    monkeypatch.setattr(ss, "track1_only_enabled", lambda: True)
    monkeypatch.setattr(ss, "track1_shadow_enabled", lambda: True)


def _started(monkeypatch, when):
    """Pin what the process table reports, without touching the real one."""
    state = {
        "running": when is not None,
        "pid": 33868 if when else None,
        "started_at": ss._iso(when) if when else None,
        "age_seconds": 3523.0 if when else None,
        "code_mtime": "2026-08-24T03:23:02-04:00",
        "stale_code": False if when else None,
        "process_count": 1 if when else 0,
    }
    monkeypatch.setattr(ss, "scheduler_process_state", lambda **kw: state)
    return state


def _status(root, now=NOW_ET):
    return ss.get_schedule_status(root, observed_at=now.astimezone(dt.timezone.utc),
                                  now=now.astimezone(dt.timezone.utc))


def _overdue_ids(status):
    return [e["slot_id"] for e in status["unexplained_overdue"]]


# ==============================================================================
# 1. the false alarm itself
# ==============================================================================

def test_nkd_slots_before_scheduler_start_are_not_overdue(root, track1_only, monkeypatch):
    """The whole NKD window passed before 04:32. None of its 22 slots is late."""
    _started(monkeypatch, START_ET)
    status = _status(root)

    nkd = [sid for sid in _overdue_ids(status) if "NKD" in sid]
    assert nkd == [], f"late over a window that predates the process: {nkd}"
    assert status["unexplained_overdue"] == []
    assert status["freshness"] != "late"


def test_the_pre_start_slots_are_classified_not_merely_dropped(root, track1_only, monkeypatch):
    """Vanishing from the overdue list silently would be indistinguishable from the slot
    having run. It must carry a reason a human can read."""
    _started(monkeypatch, START_ET)
    ev = _status(root)["evidence"]

    assert ev["state"] == "not_applicable"
    assert ev["reason"] == "before_scheduler_start"
    assert ev["severity"] == "none"
    assert ev["detail"], "a classification with no detail cannot be checked by an operator"
    assert "before the scheduler started" in ev["detail"]


def test_all_twenty_two_nkd_slots_are_covered(root, track1_only, monkeypatch):
    """Guard against the rule firing on a subset. The loop below is worthless if the scan
    finds nothing, so the count is pinned before it runs."""
    started = ss._parse_iso(_started(monkeypatch, START_ET)["started_at"])
    slots = [s for s in ss._slots_for(NOW_ET.date()) if s["id"].startswith("TRACK1_NKD_")]
    assert len(slots) == 22, f"expected 22 NKD slots, found {len(slots)}"

    for slot in slots:
        ev = ss._evidence(slot, root, [], started)
        assert ev["state"] == "not_applicable", f"{slot['id']} -> {ev['state']}"


# ==============================================================================
# 2. the three limits -- a real miss must still be a real miss
# ==============================================================================

def test_a_track1_slot_after_scheduler_start_is_still_overdue(root, track1_only, monkeypatch):
    """The scheduler starts at 00:30, before the NKD window opens. Now every NKD slot is
    one the running process was asked to fill and did not -- and must read as late."""
    _started(monkeypatch, dt.datetime(2026, 8, 24, 0, 30, tzinfo=ET))
    status = _status(root)

    nkd = [sid for sid in _overdue_ids(status) if "NKD" in sid]
    assert len(nkd) == 22, f"a genuine miss was suppressed: only {len(nkd)} late"
    assert status["freshness"] == "late"
    assert status["evidence"]["state"] == "not_observed"


def test_evidence_wins_over_the_clock(root, track1_only, monkeypatch):
    """A slot with log lines is explained by those lines, whatever the clock says.

    The case that matters is the UNRECOGNISED line -- a marker with no verdict in it. A
    recognised outcome (`exited with code`, a clean exit) returns from an earlier branch and
    could never reach the pre-start rule, so testing with one proves nothing about the rule.
    An unrecognised line falls all the way through, and it is exactly the line that must not
    be excused: something wrote it, so the story "no process existed" is contradicted, and a
    slot that started and never finished must stay on the alarm side.
    """
    started = ss._parse_iso(_started(monkeypatch, START_ET)["started_at"])
    slot = next(s for s in ss._slots_for(NOW_ET.date()) if s["id"] == "TRACK1_NKD_0110")
    assert slot["at"] < started, "fixture broken: this slot must precede the start instant"

    unrecognised = ["2026-08-24 01:10:05 INFO [" + slot["id"] + "] launching"]
    ev = ss._evidence(slot, root, unrecognised, started)
    assert ev["state"] != "not_applicable", (
        "a slot with a log line was excused as 'no process existed to run it', "
        "while the line itself proves one did")
    assert ev["state"] == "not_observed" and ev["severity"] == "watch"

    failed = ["2026-08-24 01:10:05 INFO [" + slot["id"] + "] exited with code 1"]
    ev = ss._evidence(slot, root, failed, started)
    assert ev["state"] == "failed", "a failure before the start instant is still a failure"
    assert ev["severity"] == "incident"


def test_no_known_start_time_means_the_rule_does_not_apply(root, track1_only, monkeypatch):
    """Nothing running, or a start time that will not parse. Both must leave the report
    exactly as it was -- the rule may only ever remove an alarm it can justify."""
    _started(monkeypatch, None)
    assert len(_status(root)["unexplained_overdue"]) == 22

    monkeypatch.setattr(ss, "scheduler_process_state",
                        lambda **kw: {"running": True, "started_at": "not-a-timestamp",
                                      "pid": 1, "process_count": 1, "age_seconds": 1.0,
                                      "code_mtime": None, "stale_code": None})
    assert len(_status(root)["unexplained_overdue"]) == 22
    assert ss._parse_iso("not-a-timestamp") is None
    assert ss._parse_iso(None) is None


def test_a_slot_exactly_at_the_start_instant_is_not_excused(root, track1_only, monkeypatch):
    """Strictly-before, not before-or-equal. A slot due at the very moment the process came
    up had a process; the boundary belongs on the alarm side."""
    slot = next(s for s in ss._slots_for(NOW_ET.date()) if s["id"] == "TRACK1_NKD_0110")
    assert ss._evidence(slot, root, [], slot["at"])["state"] == "not_observed"
    later = slot["at"] + dt.timedelta(seconds=1)
    assert ss._evidence(slot, root, [], later)["state"] == "not_applicable"


# ==============================================================================
# 3. legacy is untouched
# ==============================================================================

def test_legacy_slots_are_never_excused_by_this_rule(root, monkeypatch):
    """Scoped to Track 1 ids on purpose. The same reasoning applies to a legacy slot, but
    widening it here would change a long-tuned alarm surface to fix a Track 1 problem."""
    monkeypatch.setenv("RAITS_TRACK1_ONLY", "")
    monkeypatch.setattr(ss, "track1_only_enabled", lambda: False)
    monkeypatch.setattr(ss, "track1_shadow_enabled", lambda: False)
    started = ss._parse_iso(_started(monkeypatch, START_ET)["started_at"])

    legacy = [s for s in ss._slots_for(NOW_ET.date())
              if s["at"] < started and not ss._is_track1_slot(s["id"])]
    assert legacy, "fixture broken: no legacy slot lies before the start instant"
    for slot in legacy:
        assert ss._evidence(slot, root, [], started)["state"] == "not_observed", slot["id"]


def test_legacy_mode_overdue_count_is_unchanged_by_the_fix(root, monkeypatch):
    """Flags off: the number of late slots must be identical whether or not a start time is
    available to the classifier."""
    monkeypatch.setenv("RAITS_TRACK1_ONLY", "")
    monkeypatch.setattr(ss, "track1_only_enabled", lambda: False)
    monkeypatch.setattr(ss, "track1_shadow_enabled", lambda: False)

    _started(monkeypatch, START_ET)
    with_start = len(_status(root)["unexplained_overdue"])
    _started(monkeypatch, None)
    without_start = len(_status(root)["unexplained_overdue"])

    assert with_start == without_start
    assert with_start > 0, "an equality between two zeros proves nothing"


def test_the_prefix_test_is_the_thing_that_scopes_it():
    assert ss._is_track1_slot("TRACK1_NKD_0110") is True
    assert ss._is_track1_slot("NKD_NIGHT_0110") is False
    assert ss._is_track1_slot("LIVE_DAY_1405") is False
    assert ss._is_track1_slot("") is False
    assert ss._is_track1_slot(None) is False


# ==============================================================================
# 4. the payload the dashboard reads
# ==============================================================================

def test_state_slot_count_is_seventy_in_track1_only(root, track1_only, monkeypatch):
    """70 = 1 Calm + 24 Stress + 23 Swing + 22 NKD. Not 115 (transitional) and not 45
    (legacy) -- a mirror showing either would invent slots the scheduler does not have."""
    _started(monkeypatch, START_ET)
    assert _status(root)["state_slot_count"] == 70
    assert ss._state_slot_table_size() == 70


def test_the_scheduler_process_block_is_still_published(root, track1_only, monkeypatch):
    """The fix reads this block once and reuses it. It must still reach the payload -- the
    dashboard's staleness rail is built on it."""
    state = _started(monkeypatch, START_ET)
    assert _status(root)["scheduler_process"] == state


def test_the_running_backend_answer_is_reported_honestly():
    """Against the live endpoint, not a fixture. This asserts nothing about the fix -- the
    running backend serves whatever code it was started with. It exists so the suite cannot
    be read as proof that the LIVE dashboard is fixed; only a restart does that."""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:5002/api/v1/schedule-status", timeout=10) as fh:
            live = json.load(fh)
    except Exception as exc:                      # noqa: BLE001
        pytest.skip("backend not reachable: " + str(exc))
    assert live["state_slot_count"] == 70, "the running backend is not in track1-only mode"
    print("\nLIVE backend: freshness=" + str(live["freshness"])
          + " unexplained_overdue=" + str(len(live["unexplained_overdue"]))
          + " (non-zero here means the backend predates this fix)")
