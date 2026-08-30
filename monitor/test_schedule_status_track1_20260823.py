"""Stage 5AA — Track 1 slots in the dashboard's HEALTH table, and only on the flag.

Before this stage the Track 1 mirror reached only the "what runs next" caption. Measured
2026-08-23: flipping `RAITS_TRACK1_SHADOW` changed exactly ONE field of the entire
schedule-status payload — `next_scheduled_job`. The table that drives freshness, lateness,
evidence rows and incidents stayed at 45 slots either way, so a Track 1 slot that failed at
11:05 was invisible to every health signal the dashboard has.

Two directions have to hold, and both are failure modes this module already documents:

- **flag OFF** — every number is what it has always been. A regression here is a change to
  the live dashboard, and it is the thing this file exists to make impossible.
- **flag ON** — the slots are known. A slot the mirror does NOT know becomes a manufactured
  incident every day it fires; a slot the health table does not know fails in silence.

Read-only against the monitor: these tests parse constructed log text under `tmp_path` and
never start a scheduler, touch a broker, or write a runtime file.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from monitor.backend import schedule_status as ss  # noqa: E402
from global_index.track1_slots import TRACK1_SLOTS  # noqa: E402

MONDAY = dt.date(2026, 8, 24)          # pinned: a verdict that moves with the calendar is
                                       # not a verdict
ET = ss.ET


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.delenv("RAITS_TRACK1_SHADOW", raising=False)
    ss.invalidate_scheduler_cache()
    yield
    ss.invalidate_scheduler_cache()


@pytest.fixture(autouse=True)
def _pinned_scheduler_start(monkeypatch):
    """Pin the scheduler's start instant. Stage 5R-1.

    `get_schedule_status` reads the REAL running scheduler's `started_at` and uses it to
    decide whether a slot is judgeable at all: one that fell before the process existed is
    pre-start, not overdue. That is correct production behaviour — it is the same rule the
    Track 1 audit applies — but it made every test in this file depend on when the machine
    was last restarted.

    It went unnoticed because the scheduler had been up since 09:25 ET, which is before every
    slot these tests pin. Restarting at 23:29 ET on 2026-08-24 turned `TRACK1_STRESS_1035`
    from overdue into pre-start and reddened a test that had nothing to do with the change.

    Pinned to 00:05 ET on the fixture's own Monday: before every slot the file uses, so
    laterness is decided by the slot and the clock rather than by the operator's last restart.
    """
    monkeypatch.setattr(ss, "scheduler_process_state", lambda *a, **k: {
        "started_at": f"{MONDAY.isoformat()}T00:05:00-04:00",
        "running": True, "pid": 1, "process_count": 1,
        "age_seconds": 60, "stale_code": False, "code_mtime": None,
    })
    ss.invalidate_scheduler_cache()
    yield
    ss.invalidate_scheduler_cache()


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("RAITS_TRACK1_SHADOW", "1")
    ss.invalidate_scheduler_cache()
    yield
    ss.invalidate_scheduler_cache()


def _utc(h, m):
    """An ET wall-clock instant on the pinned Monday, as UTC (ET is UTC-4 in August)."""
    return dt.datetime(MONDAY.year, MONDAY.month, MONDAY.day, h + 4, m,
                       tzinfo=dt.timezone.utc)


def _log(tmp_path, lines):
    """A scheduler log the reader will actually pick up."""
    p = tmp_path / f"scheduler_{MONDAY:%m%d}.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def _line(hhmm, level, body):
    return f"{MONDAY.isoformat()} {hhmm}:00 {level}     run_scheduler - {body}"


# ── 1. flag OFF: the legacy baseline, unchanged ──────────────────────────────
def test_flag_off_state_table_is_the_legacy_45(flag_off):
    assert ss._state_slot_table_size() == len(ss.STATE_SLOTS) == 45
    assert len(ss._slots_for(MONDAY)) == 45


def test_flag_off_windows_are_the_two_legacy_bands(flag_off):
    assert ss._active_windows() == (((1, 10), (2, 55)), ((14, 5), (15, 55)))


def test_flag_off_no_track1_slot_appears_anywhere(flag_off):
    for fn in (ss._slots_for, ss._pipeline_slots_for, ss._scheduled_slots_for):
        ids = {s["id"] for s in fn(MONDAY)}
        assert not any(i.startswith("TRACK1_") for i in ids), (fn.__name__, sorted(ids))
    assert ss._track1_state_slots(MONDAY) == []


def test_flag_off_payload_is_byte_identical_to_the_pre_change_shape(flag_off, tmp_path):
    """The whole payload, not a field or two. Anything that moved with the flag off is a
    change to the live dashboard."""
    import json
    out = ss.get_schedule_status(tmp_path, observed_at=None, now=_utc(11, 0))
    assert out["state_slot_count"] == 45
    assert out["active_window"] is False          # 11:00 ET is outside both legacy bands
    assert out["incidents"] == [] and out["open_incidents"] == []
    assert not any("TRACK1" in json.dumps(v, default=str) for v in out.values())


# ── 2. flag ON: the slots are in the health table ────────────────────────────
def test_flag_on_state_table_gains_exactly_the_track1_slots(flag_on):
    # The relation is the subject; the totals are derived. `== 70` was a literal that turned
    # red when Stage 5M-B added the 23 Normal-R4 slots — a change this test has no opinion
    # about. What it does have an opinion about is that the flag adds the Track 1 slots and
    # nothing else.
    expected = 45 + len(TRACK1_SLOTS)
    assert ss._state_slot_table_size() == expected
    ids = {s["id"] for s in ss._slots_for(MONDAY)}
    assert {s.id for s in TRACK1_SLOTS} <= ids
    assert len(ids) == expected


def test_flag_on_adds_a_window_band_per_sleeve(flag_on):
    wins = ss._active_windows()
    assert ((1, 10), (2, 55)) in wins and ((14, 5), (15, 55)) in wins
    assert ((9, 32), (10, 2)) in wins, "the Calm DECIDE/OBSERVE band is missing"
    assert ((10, 35), (12, 30)) in wins, "the Stress window band is missing"


def test_flag_on_a_track1_window_is_an_active_window(flag_on, tmp_path):
    """Without this the rail says 'not expected yet' at 11:05 and a missing slot is
    reported as nothing being due."""
    out = ss.get_schedule_status(tmp_path, observed_at=None, now=_utc(11, 5))
    assert out["active_window"] is True


def test_flag_off_the_same_instant_is_not_an_active_window(flag_off, tmp_path):
    out = ss.get_schedule_status(tmp_path, observed_at=None, now=_utc(11, 5))
    assert out["active_window"] is False


def test_the_allowance_follows_the_slot_kind(flag_on):
    by_id = {s["id"]: s for s in ss._track1_state_slots(MONDAY)}
    one_shot = [s for s in TRACK1_SLOTS if s.kind == "one_shot"]
    window = [s for s in TRACK1_SLOTS if s.kind == "window"]
    assert one_shot and window, "need both kinds for this to prove anything"
    assert by_id[one_shot[0].id]["allowance_seconds"] == 15 * 60
    assert by_id[window[0].id]["allowance_seconds"] == 8 * 60


# ── 3. flag ON: the ids are recognised, not treated as strays ────────────────
def test_a_track1_slot_id_groups_by_sleeve(flag_on):
    """`_stream_of` is what decides which later slot can mark an incident recovered.
    Grouping Calm and Stress together would let a Stress run 'recover' a Calm failure."""
    assert ss._stream_of("TRACK1_CALM_1000") == "TRACK1_CALM"
    assert ss._stream_of("TRACK1_STRESS_1035") == "TRACK1_STRESS"
    assert ss._stream_of("TRACK1_STRESS_1230") == "TRACK1_STRESS"
    assert ss._stream_of("TRACK1_CALM_1000") != ss._stream_of("TRACK1_STRESS_1035")


def test_a_clean_track1_slot_reads_as_executed(flag_on, tmp_path):
    root = _log(tmp_path, [
        _line("10:35", "INFO", "[TRACK1_STRESS_1035] python -m global_index.run_live_day_track1"),
        _line("10:36", "INFO", "[TRACK1_STRESS_1035] completed OK"),
    ])
    slot = next(s for s in ss._slots_for(MONDAY) if s["id"] == "TRACK1_STRESS_1035")
    ev = ss._evidence(slot, root)
    assert ev["state"] == "executed", ev
    assert ev["severity"] == "none"


def test_a_failed_track1_slot_reads_as_an_incident(flag_on, tmp_path):
    root = _log(tmp_path, [
        _line("10:35", "INFO", "[TRACK1_STRESS_1035] python -m global_index.run_live_day_track1"),
        _line("10:37", "ERROR", "[TRACK1_STRESS_1035] exited with code 1"),
    ])
    slot = next(s for s in ss._slots_for(MONDAY) if s["id"] == "TRACK1_STRESS_1035")
    ev = ss._evidence(slot, root)
    assert ev["state"] == "failed" and ev["severity"] == "incident", ev


# ── 4. a due Track 1 slot with no evidence becomes overdue ───────────────────
def test_a_due_track1_slot_with_no_closing_line_goes_overdue(flag_on, tmp_path):
    """The whole point: silence on a Track 1 slot must reach the rail."""
    root = _log(tmp_path, [_line("09:31", "INFO", "[MAX_HOLD_EXIT] completed OK")])
    # `observed_at` must be supplied and recent: with None the very first branch answers
    # "missing" before lateness is ever considered, and with a stale snapshot "stale" wins.
    # Neither would prove the Track 1 slot reached the rail.
    out = ss.get_schedule_status(root, observed_at=_utc(11, 29), now=_utc(11, 30))
    overdue = {e["slot_id"] for e in out["unexplained_overdue"]}
    assert "TRACK1_STRESS_1035" in overdue, sorted(overdue)
    assert out["freshness"] == "late", out["freshness"]


def test_flag_off_the_same_silence_produces_no_track1_overdue(flag_off, tmp_path):
    root = _log(tmp_path, [_line("09:31", "INFO", "[MAX_HOLD_EXIT] completed OK")])
    out = ss.get_schedule_status(root, observed_at=None, now=_utc(11, 30))
    assert not any("TRACK1" in e["slot_id"] for e in out["unexplained_overdue"])


def test_a_track1_incident_can_be_recovered_by_a_later_slot_of_the_same_sleeve(flag_on,
                                                                               tmp_path):
    root = _log(tmp_path, [
        _line("10:35", "INFO", "[TRACK1_STRESS_1035] python -m global_index.run_live_day_track1"),
        _line("10:36", "ERROR", "[TRACK1_STRESS_1035] exited with code 1"),
        _line("10:40", "INFO", "[TRACK1_STRESS_1040] python -m global_index.run_live_day_track1"),
        _line("10:41", "INFO", "[TRACK1_STRESS_1040] completed OK"),
    ])
    out = ss.get_schedule_status(root, observed_at=None, now=_utc(11, 0))
    incidents = {i["slot_id"]: i for i in out["incidents"]}
    assert "TRACK1_STRESS_1035" in incidents, sorted(incidents)
    assert incidents["TRACK1_STRESS_1035"]["lifecycle"] == "recovered"
    assert incidents["TRACK1_STRESS_1035"]["recovered_by"] == "TRACK1_STRESS_1040"
    # the failure stays on the record even though the stream came back
    assert not any(i["slot_id"] == "TRACK1_STRESS_1035" for i in out["open_incidents"])


def test_a_calm_failure_is_not_recovered_by_a_stress_run(flag_on, tmp_path):
    """Different sleeves are different processes against different instruments."""
    root = _log(tmp_path, [
        _line("09:32", "INFO", "[TRACK1_CALM_DECIDE_0932] python -m global_index.run_live_day_track1"),
        _line("09:33", "ERROR", "[TRACK1_CALM_DECIDE_0932] exited with code 1"),
        _line("10:35", "INFO", "[TRACK1_STRESS_1035] python -m global_index.run_live_day_track1"),
        _line("10:36", "INFO", "[TRACK1_STRESS_1035] completed OK"),
    ])
    out = ss.get_schedule_status(root, observed_at=None, now=_utc(11, 0))
    calm = next(i for i in out["incidents"] if i["slot_id"] == "TRACK1_CALM_DECIDE_0932")
    assert calm["lifecycle"] == "open"
    assert calm["recovered_by"] is None
    assert any(i["slot_id"] == "TRACK1_CALM_DECIDE_0932" for i in out["open_incidents"])


# ── 5. no fake incidents for slots the mirror DOES know ──────────────────────
def test_a_full_clean_track1_day_raises_no_incident(flag_on, tmp_path):
    lines = [_line("09:31", "INFO", "[MAX_HOLD_EXIT] completed OK")]
    for s in TRACK1_SLOTS:
        hhmm = f"{s.hour:02d}:{s.minute:02d}"
        lines.append(_line(hhmm, "INFO", f"[{s.id}] python -m global_index.run_live_day_track1"))
        lines.append(_line(hhmm, "INFO", f"[{s.id}] completed OK"))
    root = _log(tmp_path, lines)
    out = ss.get_schedule_status(root, observed_at=None, now=_utc(12, 45))
    t1_incidents = [i for i in out["incidents"] if str(i["slot_id"]).startswith("TRACK1_")]
    assert t1_incidents == [], t1_incidents
    t1_overdue = [e for e in out["unexplained_overdue"]
                  if str(e["slot_id"]).startswith("TRACK1_")]
    assert t1_overdue == [], t1_overdue


# ── 6. stop-repair 12:20 stays as Stage 5 specified ──────────────────────────
def test_stop_repair_1220_is_excluded_in_track1_shadow_mode(flag_on):
    hours = {h for h, m in ss._stop_repair_slots()}
    assert 12 not in hours, "12:20 would land inside the Stress entry window"
    assert 2 not in hours and 14 not in hours, "the legacy exclusions must still hold"
    assert "STOP_REPAIR_1220" not in {s["id"] for s in ss._scheduled_slots_for(MONDAY)}


def test_stop_repair_1220_is_present_with_the_flag_off(flag_off):
    assert 12 in {h for h, m in ss._stop_repair_slots()}
    assert "STOP_REPAIR_1220" in {s["id"] for s in ss._scheduled_slots_for(MONDAY)}


# ── 7. unknown non-Track1 slots behave exactly as before ─────────────────────
@pytest.mark.parametrize("fixture", ["flag_off", "flag_on"])
def test_an_unknown_slot_id_is_still_not_modelled(fixture, request, tmp_path):
    """A stray id in the log must not become a slot in either mode — the mirror models
    what the scheduler registers, and inventing rows for unknown ids is the failure this
    module was built to avoid."""
    request.getfixturevalue(fixture)
    root = _log(tmp_path, [_line("10:05", "INFO", "[SOMETHING_ELSE_1005] completed OK")])
    ids = {s["id"] for s in ss._slots_for(MONDAY)}
    assert "SOMETHING_ELSE_1005" not in ids
    out = ss.get_schedule_status(root, observed_at=None, now=_utc(11, 0))
    assert not any(i["slot_id"] == "SOMETHING_ELSE_1005" for i in out["incidents"])


# ── 8. parity with the scheduler is preserved ────────────────────────────────
def test_the_scheduled_mirror_is_unchanged_by_this_stage(flag_on):
    """This stage touched the HEALTH table, not the scheduled-job mirror. Adding Track 1
    twice would double-count them in the parity comparison."""
    ids = [s["id"] for s in ss._scheduled_slots_for(MONDAY)]
    assert len(ids) == len(set(ids)), "a slot id is mirrored twice"
    t1 = [i for i in ids if i.startswith("TRACK1_")]
    # Derived, not pinned — see the note in the state-table test above.
    assert len(t1) == len(TRACK1_SLOTS)
    assert t1, "no Track 1 slots are mirrored at all"


def test_parity_report_still_true_with_the_flag_on():
    """Reads the scheduler itself; never starts it. `parity_report` flips BOTH sides of
    the gate at once, which is the point of asking."""
    from global_index import track1_slots as slots
    r = slots.parity_report(track1_shadow=True)
    assert r["in_parity"], (r["only_in_scheduler"], r["only_in_dashboard_mirror"])


def test_parity_report_still_true_with_the_flag_off():
    from global_index import track1_slots as slots
    r = slots.parity_report(track1_shadow=False)
    assert r["in_parity"], (r["only_in_scheduler"], r["only_in_dashboard_mirror"])


# ── Stage 5AB: track1-only must not expect the legacy slots ─────────────────
#
# `_pipeline_slots_for` has dropped the 45 legacy strategy slots in track1-only mode since
# Stage 5M-D; the HEALTH table had not, so the two halves of one mirror disagreed. Measured
# 2026-08-24 before the fix: a perfectly clean Track 1 day reported 32 legacy slots
# `unexplained_overdue` and drove the rail to `late` with nothing actually wrong.

@pytest.fixture
def only_on(monkeypatch):
    monkeypatch.setenv("RAITS_TRACK1_ONLY", "1")
    monkeypatch.setenv("RAITS_TRACK1_SHADOW", "1")
    ss.invalidate_scheduler_cache()
    yield
    ss.invalidate_scheduler_cache()


def _clean_track1_log(tmp_path, upto_hour=15):
    lines = []
    for s in TRACK1_SLOTS:
        if s.hour < upto_hour:
            hhmm = f"{s.hour:02d}:{s.minute:02d}"
            lines.append(_line(hhmm, "INFO", f"[{s.id}] python -m global_index.run_live_day_track1"))
            lines.append(_line(hhmm, "INFO", f"[{s.id}] completed OK"))
    return _log(tmp_path, lines)


def test_track1_only_health_table_drops_the_legacy_strategy_slots(only_on):
    ids = {s["id"] for s in ss._slots_for(MONDAY)}
    assert not any(i.startswith(("LIVE_DAY_", "NKD_NIGHT_")) for i in ids), sorted(ids)[:6]
    assert ids == {s.id for s in TRACK1_SLOTS}
    assert ss._state_slot_table_size() == len(TRACK1_SLOTS)


def test_track1_shadow_transitional_still_expects_both(flag_on):
    """Transitional mode runs BOTH routes, so dropping legacy there would blind the half
    that is still trading."""
    ids = {s["id"] for s in ss._slots_for(MONDAY)}
    assert any(i.startswith(("LIVE_DAY_", "NKD_NIGHT_")) for i in ids)
    assert {s.id for s in TRACK1_SLOTS} <= ids
    assert ss._state_slot_table_size() == len(ss.STATE_SLOTS) + len(TRACK1_SLOTS)


def test_a_clean_track1_only_day_raises_no_phantom_legacy_overdue(only_on, tmp_path):
    """The measured defect, as a test. 32 phantom rows before the fix, 0 after."""
    root = _clean_track1_log(tmp_path)
    now = _utc(15, 0)
    out = ss.get_schedule_status(root, observed_at=now - dt.timedelta(minutes=1), now=now)
    overdue = [e["slot_id"] for e in out["unexplained_overdue"]]
    legacy = [i for i in overdue if i.startswith(("LIVE_DAY_", "NKD_NIGHT_"))]
    assert legacy == [], legacy[:6]
    assert overdue == [], overdue[:6]
    assert out["freshness"] == "fresh", out["freshness"]
    assert out["state_slot_count"] == len(TRACK1_SLOTS)


def test_track1_only_still_reports_a_real_track1_failure(only_on, tmp_path):
    """Dropping the legacy rows must not also drop the Track 1 ones — that would trade a
    noisy dashboard for a silent one."""
    lines = [_line("09:32", "INFO", "[TRACK1_CALM_DECIDE_0932] python -m global_index.run_live_day_track1"),
             _line("09:33", "ERROR", "[TRACK1_CALM_DECIDE_0932] exited with code 1")]
    root = _log(tmp_path, lines)
    now = _utc(11, 0)
    out = ss.get_schedule_status(root, observed_at=now - dt.timedelta(minutes=1), now=now)
    ids = {i["slot_id"] for i in out["incidents"]}
    assert "TRACK1_CALM_DECIDE_0932" in ids, sorted(ids)


def test_legacy_mode_is_untouched_by_the_track1_only_subtraction(flag_off):
    ids = {s["id"] for s in ss._slots_for(MONDAY)}
    assert len(ids) == 45
    assert all(i.startswith(("LIVE_DAY_", "NKD_NIGHT_")) for i in ids)
    assert ss._state_slot_table_size() == 45


# ── 9. this stage touched nothing it was not allowed to ──────────────────────
FORBIDDEN = (
    "global_index/run_live_day_track1.py",
    "global_index/track1_explain.py",
    "global_index/track1_freshness.py",
    "global_index/track1_signal_layer.py",
    "global_index/run_scheduler.py",
    "global_index/track1_slots.py",
)


def test_schedule_status_imports_nothing_from_the_track1_route():
    """The health table may read the SLOT TABLE and nothing else. Importing the route
    entry point would drag a broker-capable module into the read-only backend."""
    import ast
    src = (_ROOT / "monitor" / "backend" / "schedule_status.py").read_text(encoding="utf-8")
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    assert names, "parsed no imports at all"
    assert "global_index.run_live_day_track1" not in names
    assert "global_index.track1_explain" not in names
    assert not any(n.startswith("ib_insync") for n in names)
    # the one Track 1 module it may read
    assert "global_index.track1_slots" in names


def test_no_explanation_endpoint_or_drawer_was_added():
    """Stage 5AA is health slots only. An endpoint or a UI reference here would be a
    wiring nobody reviewed."""
    import re
    app = (_ROOT / "monitor" / "backend" / "app.py").read_text(encoding="utf-8")
    assert "explanation" not in app.lower()
    assert "track1_explain" not in app
    for js in (_ROOT / "global_index" / "dash").rglob("*.js"):
        assert "explain_id" not in js.read_text(encoding="utf-8", errors="replace"), js
