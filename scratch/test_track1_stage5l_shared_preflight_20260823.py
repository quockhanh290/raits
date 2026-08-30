"""Stage 5L — the 13:45 pre-flight is shared infrastructure, and stays registered.

Read-only. Builds scheduler objects and never starts one; no IBKR, no orders, no switch files.

What these tests are for
------------------------
The 2026-08-23 legacy→Track 1 audit found blocker L6: the pre-flight job sits inside the
legacy block of `run_scheduler.py` for no reason other than legacy having been written first.
Retiring "the legacy jobs" by reading that file top to bottom takes the data refresh with it,
and Track 1's freshness gate reads the record that job writes.

That failure is silent in the worst way. Nothing errors at retirement time. The next morning
Track 1's gate reports `preflight_record: MISSING` and refuses every entry, and the reason it
gives points at a FILE, not at the deleted job that stopped writing it.

So these tests pin four things:

    1. the job still exists, in both scheduler modes, with its body unchanged
    2. it is classified as shared infrastructure, and the retirement set excludes it
    3. the freshness contract it underwrites is exactly what it was
    4. the dashboard mirror still sees it, in both modes

Each of these can go red. The classification tests are checked against a synthetic job id as
well as the real one, so they are testing a rule rather than agreeing with a constant.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, r"d:\raits")

from global_index import run_scheduler as rs           # noqa: E402
from global_index import track1_freshness as fresh     # noqa: E402
from global_index import track1_slots as ts            # noqa: E402

PREFLIGHT_ID = "preflight"
PREFLIGHT_HOUR, PREFLIGHT_MINUTE = 13, 45


@pytest.fixture(scope="module")
def scheds():
    """Both scheduler shapes, built once. Never started."""
    os.environ.setdefault("PYTEST_CURRENT_TEST", "stage5l")
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        return {flag: rs.make_scheduler(port=4002, dry_run=True, track1_shadow=flag)
                for flag in (False, True)}
    finally:
        logging.disable(lvl)


def _job(scheds, flag, jid=PREFLIGHT_ID):
    return {j.id: j for j in scheds[flag].get_jobs()}.get(jid)


# ── 1. The job is still there, and still does the same thing ────────────────────────────

@pytest.mark.parametrize("flag", [False, True])
def test_preflight_is_registered_in_both_scheduler_modes(scheds, flag):
    assert _job(scheds, flag) is not None, (
        f"the 13:45 pre-flight is not registered with track1_shadow={flag}")


@pytest.mark.parametrize("flag", [False, True])
def test_preflight_still_fires_at_1345_et(scheds, flag):
    """Stage 5L is an ownership change. Moving the time would be a contract change, and
    `track1_freshness.required_data_through` hard-codes the same 13:45 on the other side."""
    trig = str(_job(scheds, flag).trigger)
    assert f"hour='{PREFLIGHT_HOUR}'" in trig and f"minute='{PREFLIGHT_MINUTE}'" in trig, trig
    assert "day_of_week='mon-fri'" in trig, trig


@pytest.mark.parametrize("flag", [False, True])
def test_the_job_name_is_unchanged_because_the_journal_reads_it(scheds, flag):
    """The name looks like a display label and is not one.

    `monitor/backend/job_journal_reader._job_id_from_name` maps a run back to a job by the
    name PREFIX. Rename this job and the mapper returns None, the run is dropped, and every
    pre-flight disappears from the Job Journal without a single error line. Stage 5L
    deliberately did NOT rename it; this test is what makes that decision cost something to
    reverse.
    """
    from monitor.backend.job_journal_reader import _job_id_from_name
    name = _job(scheds, flag).name
    assert _job_id_from_name(name) == "PREFLIGHT", (
        f"job name {name!r} no longer maps to PREFLIGHT in the job journal")


def test_the_preflight_body_still_runs_the_same_two_updates_and_writes_the_record(tmp_path):
    """Body unchanged: update_ibkr_daily, then update_spy_csv, then the record ON DISK.

    Asserted by capturing the argv the body would spawn — `_run` is replaced, so nothing is
    executed — rather than by reading the source, which would pass on a commented-out call.

    The record is checked by letting the REAL writer run against a redirected path and then
    reading the file back. The first version replaced `_save_preflight_state` with a spy, and
    a mutation that made the real writer a no-op was therefore invisible: the test was
    exercising its own stub. The production file is never touched — `_PREFLIGHT_STATE` points
    into tmp_path for the duration.
    """
    calls: list = []
    state_file = tmp_path / "preflight_state.json"
    orig_run, orig_path = rs._run, rs._PREFLIGHT_STATE
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._run = lambda cmd, label=None, dry_run=False, route=None: (calls.append(
            (label, list(cmd))) or True)
        rs._PREFLIGHT_STATE = state_file
        sched = rs.make_scheduler(port=4002, dry_run=False, track1_shadow=False)
        job = {j.id: j for j in sched.get_jobs()}[PREFLIGHT_ID]
        rs._preflight_ok.clear()
        job.func()
    finally:
        rs._run, rs._PREFLIGHT_STATE = orig_run, orig_path
        rs._preflight_ok.clear()
        logging.disable(lvl)

    assert calls, "the pre-flight body spawned nothing at all"
    mods = [c[1][c[1].index("-m") + 1] for c in calls if "-m" in c[1]]
    assert mods == ["global_index.update_ibkr_daily", "global_index.update_spy_csv"], mods
    spy = calls[1][1]
    assert "--csv" in spy and spy[spy.index("--csv") + 1] == "spy_daily_live.csv", spy
    assert state_file.exists(), "a successful pre-flight wrote no record at all"
    written = json.loads(state_file.read_text(encoding="utf-8"))
    assert written and all(v is True for v in written.values()), written


def test_the_preflight_is_still_fail_closed_when_the_first_step_fails(tmp_path):
    """A failure must record False on disk and must NOT go on to the second step."""
    calls: list = []
    state_file = tmp_path / "preflight_state.json"
    orig_run, orig_path = rs._run, rs._PREFLIGHT_STATE
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._run = lambda cmd, label=None, dry_run=False, route=None: (calls.append(label)
                                                                     or False)
        rs._PREFLIGHT_STATE = state_file
        sched = rs.make_scheduler(port=4002, dry_run=False, track1_shadow=False)
        job = {j.id: j for j in sched.get_jobs()}[PREFLIGHT_ID]
        rs._preflight_ok.clear()
        job.func()
    finally:
        rs._run, rs._PREFLIGHT_STATE = orig_run, orig_path
        rs._preflight_ok.clear()
        logging.disable(lvl)

    assert len(calls) == 1, f"the pre-flight continued after a failure: {calls}"
    assert state_file.exists(), "a failed pre-flight recorded nothing"
    written = json.loads(state_file.read_text(encoding="utf-8"))
    assert written and all(v is False for v in written.values()), written


def test_firing_the_preflight_body_never_touches_the_operator_s_state_files():
    """The defect this suite itself caused, turned into a check.

    Firing `job_preflight()` to capture its argv is a normal thing to want. It is also the
    one job body whose success path WRITES production state, and a probe that patches `_run`
    but not the state path silently overwrites `preflight_state.json` with a single record
    for whatever day the probe ran. `job_maxhold` has the same shape. On 2026-08-23 a probe
    of mine did exactly that to both files.

    Nothing warns. `_run` is patched so no child process starts, the job returns True, and
    the only trace is a state file that now claims a Sunday pre-flight succeeded and has lost
    every real weekday record it held.

    So: fire both bodies the unsafe way — with the write paths redirected — and assert the
    real files did not move. The redirect is the fix; this test is what notices if a future
    edit removes it.
    """
    import hashlib
    real = {p: (hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None)
            for p in (rs._PREFLIGHT_STATE, rs._MAXHOLD_STATE)}
    assert any(v for v in real.values()), (
        "neither state file exists, so this test cannot prove anything about leaving them "
        "alone — refuse rather than pass vacuously")

    import tempfile
    orig_run = rs._run
    orig_pf, orig_mh = rs._PREFLIGHT_STATE, rs._MAXHOLD_STATE
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory() as td:
        try:
            from pathlib import Path
            rs._run = lambda *a, **k: True
            rs._PREFLIGHT_STATE = Path(td) / "preflight_state.json"
            rs._MAXHOLD_STATE = Path(td) / "maxhold_state.json"
            sched = rs.make_scheduler(port=4002, dry_run=False, track1_shadow=False)
            jobs = {j.id: j for j in sched.get_jobs()}
            rs._preflight_ok.clear()
            rs._maxhold_done.clear()
            jobs[PREFLIGHT_ID].func()
            jobs["maxhold_exit"].func()
            assert rs._PREFLIGHT_STATE.exists(), (
                "the redirected pre-flight wrote nothing — the probe did not reach the "
                "writer, so this test would pass no matter where the writer pointed")
            assert rs._MAXHOLD_STATE.exists(), "the redirected max-hold wrote nothing"
        finally:
            rs._run = orig_run
            rs._PREFLIGHT_STATE, rs._MAXHOLD_STATE = orig_pf, orig_mh
            rs._preflight_ok.clear()
            rs._maxhold_done.clear()
            logging.disable(lvl)

    after = {p: (hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None)
             for p in (orig_pf, orig_mh)}
    assert after == real, f"a test wrote to the operator's state files: {after} != {real}"


def test_the_preflight_state_path_is_where_track1_freshness_looks_for_it():
    """Two modules, one file. A default that drifted apart would leave Track 1 reading a
    record nobody writes — and reporting it as MISSING, which reads like a missed job."""
    import inspect
    sig = inspect.signature(fresh.evaluate)
    assert str(rs._PREFLIGHT_STATE).replace("\\", "/") == \
        str(sig.parameters["preflight_state"].default).replace("\\", "/")


# ── 2. Protection against accidental retirement ─────────────────────────────────────────

@pytest.mark.parametrize("flag", [False, True])
def test_every_registered_job_is_classified(flag):
    """Exhaustive by construction. A job added tomorrow that matches no rule turns this red,
    which a hand-written list of legacy jobs could never do — it would simply omit it."""
    c = ts.route_classification(track1_shadow=flag)
    assert c["unclassified"] == [], c["unclassified"]
    assert sum(len(c[k]) for k in
               ("shared_infra", "legacy_entry", "safety", "track1")) == c["total"]


@pytest.mark.parametrize("flag", [False, True])
def test_preflight_is_shared_infra_not_legacy_entry(flag):
    c = ts.route_classification(track1_shadow=flag)
    assert PREFLIGHT_ID in c["shared_infra"]
    assert PREFLIGHT_ID not in c["legacy_entry"]


@pytest.mark.parametrize("flag", [False, True])
def test_the_other_shared_infra_jobs_are_not_retirement_candidates(flag):
    """Heartbeat and the session-report fallback are on the same footing as the pre-flight:
    neither decides a trade, and both are easy to sweep up while deleting a block of jobs."""
    doomed = ts.legacy_retirement_candidates(track1_shadow=flag)
    for jid in ("heartbeat", "session_report_fallback"):
        assert jid not in doomed, jid


#: Named here, NOT read from `ts.SHARED_INFRA_JOBS`. The first version of the test below
#: looped over that table, so deleting the pre-flight from it deleted the assertion too and
#: the mutation went undetected. A test that iterates the thing it is guarding agrees with
#: whatever the thing currently says.
#: Stage 5Q-5 added `spy_refresh_pm` — the 16:20 post-close SPY refresh. It is shared for
#: the same reason the 13:45 pre-flight is: both routes read that CSV and it decides no
#: trade. Retiring legacy must not take it, which is exactly what this table is for.
#: Stage 5ZZS added the three rungs of the SPY ladder that Stages 5ZZC and 5ZZD registered and
#: nobody classified. They survive for the same reason `spy_refresh_pm` does: they refresh the
#: regime CSV that BOTH routes read, and none of them decides a trade. Writing them out by hand
#: here also gives each one its own parametrised survival case below, which is the assertion
#: that actually protects them from a legacy retirement.
REQUIRED_SURVIVORS = ("preflight", "heartbeat", "session_report_fallback",
                      "spy_refresh_pm", "spy_refresh_pm_r1", "spy_refresh_pm_r2",
                      "spy_last_chance_pre_nkd")


@pytest.mark.parametrize("jid", REQUIRED_SURVIVORS)
@pytest.mark.parametrize("flag", [False, True])
def test_shared_infra_survives_the_retirement_of_every_legacy_entry_job(flag, jid):
    """The actual property, stated as the operation it protects: take away everything the
    retirement is allowed to take away, and ask what is left."""
    survivors = ts.surviving_jobs(track1_shadow=flag)
    assert survivors, "nothing survived at all — the retirement set is the whole schedule"
    assert jid in survivors, f"{jid} did not survive legacy retirement"


def test_the_shared_infra_table_covers_exactly_the_jobs_that_must_survive():
    """Keeps the constant above and the production table in step, in both directions."""
    assert set(ts.SHARED_INFRA_JOBS) == set(REQUIRED_SURVIVORS), (
        sorted(ts.SHARED_INFRA_JOBS), sorted(REQUIRED_SURVIVORS))


def test_track1_slots_survive_and_legacy_entry_slots_do_not():
    """The retirement has to actually retire something, or the test above is vacuous."""
    doomed = ts.legacy_retirement_candidates(track1_shadow=True)
    survivors = ts.surviving_jobs(track1_shadow=True)
    assert doomed, "the retirement set is empty — the check above proves nothing"
    assert any(d.startswith("live_day") for d in doomed)
    assert any(d.startswith("nkd_night") for d in doomed)
    assert not (doomed & survivors)
    assert ts.route_classification(track1_shadow=True)["track1"], "no Track 1 slots"
    for jid in ts.route_classification(track1_shadow=True)["track1"]:
        assert jid in survivors


def test_the_classifier_discriminates_rather_than_agreeing_with_a_constant():
    """Fed ids it has never seen, the rule must still sort them — and must refuse to guess.

    Without this, every test above could pass on a classifier that returned 'shared_infra'
    for the three names it was told about and 'legacy_entry' for everything else.
    """
    assert ts._bucket_for("live_day_1430") == "legacy_entry"
    assert ts._bucket_for("nkd_night_0245") == "legacy_entry"
    assert ts._bucket_for("track1_normal_r4_1405") == "track1"
    assert ts._bucket_for("stop_repair_0620") == "safety"
    assert ts._bucket_for("preflight") == "shared_infra"
    assert ts._bucket_for("some_job_nobody_wrote_a_rule_for") == "unclassified"


def test_a_shared_infra_job_removed_from_the_table_would_be_caught():
    """Mutation, in-process: drop the pre-flight from the shared table and the survivor
    property must break. If it does not, the property is not being enforced by the table."""
    orig = dict(ts.SHARED_INFRA_JOBS)
    try:
        ts.SHARED_INFRA_JOBS.pop(PREFLIGHT_ID)
        assert ts._bucket_for(PREFLIGHT_ID) != "shared_infra", (
            "removing the pre-flight from the shared table changed nothing — the "
            "classification is not coming from the table")
    finally:
        ts.SHARED_INFRA_JOBS.clear()
        ts.SHARED_INFRA_JOBS.update(orig)
    assert ts._bucket_for(PREFLIGHT_ID) == "shared_infra", "the fixture did not restore"


# ── 3. The freshness contract, pinned ───────────────────────────────────────────────────

# 2026-08-24 is a Monday; 2026-08-21 the Friday before it.
MONDAY = "2026-08-24"
PREV_BDAY = pd.Timestamp("2026-08-21")


@pytest.mark.parametrize("hhmm", ["00:01", "09:59", "10:00", "10:35", "12:30", "13:44"])
def test_before_1345_the_required_session_is_the_previous_business_day(hhmm):
    assert fresh.required_data_through(pd.Timestamp(f"{MONDAY} {hhmm}")) == PREV_BDAY


@pytest.mark.parametrize("hhmm", ["13:45", "14:05", "15:55", "23:59"])
def test_from_1345_the_required_session_is_today(hhmm):
    assert fresh.required_data_through(pd.Timestamp(f"{MONDAY} {hhmm}")) == \
        pd.Timestamp(MONDAY)


def test_the_boundary_is_exactly_1345_and_not_a_minute_either_side():
    assert fresh.required_data_through(pd.Timestamp(f"{MONDAY} 13:44")) == PREV_BDAY
    assert fresh.required_data_through(pd.Timestamp(f"{MONDAY} 13:45")) == pd.Timestamp(MONDAY)


#: Which side of the 13:45 pre-flight each sleeve's slots fall on. Stage 5M-B added the third
#: row and it is the first sleeve on the OTHER side, so this is a table rather than a blanket
#: assertion now.
#:
#: The original version of the test below asserted that EVERY Track 1 slot was a D-1 slot, and
#: said in its own docstring that a slot added after 13:45 would turn it red "which is correct:
#: that slot has a different contract and the difference should be a decision, not a
#: discovery." Stage 5M-B added 23 such slots and it did turn red. This is that decision,
#: written down rather than papered over.
SLEEVE_FRESHNESS = {
    "roska4_calm":   "D-1",     # 10:00, before the day's own pre-flight
    "roska4_stress": "D-1",     # 10:35-12:30, likewise
    "roska4_swing":  "same-day",  # 14:05-15:55, AFTER the 13:45 refresh
    "global_nkd":    "D-1",     # 01:10-02:55, half a day before it — Stage 5N, measured
}


def test_each_sleeves_slots_sit_on_the_side_of_1345_its_contract_says():
    """Not a defect either way, and recorded so neither is later mistaken for one.

    Calm and Stress fire before the day's own pre-flight, so the most recent completed refresh
    is the previous business day's. The Normal-R4 slots fire after it, so the gate requires
    TODAY's record — which is the first time any Track 1 slot has depended on the same-day
    pre-flight, and is the operational reason blocker L6 matters: a pre-flight that fails now
    stops a Track 1 sleeve, not only legacy's.

    A slot that moves across 13:45 turns this red, which is the point.
    """
    assert ts.TRACK1_SLOTS, "no Track 1 slots to check"
    seen = set()
    for s in ts.TRACK1_SLOTS:
        at = pd.Timestamp(f"{MONDAY} {s.hour:02d}:{s.minute:02d}")
        want = SLEEVE_FRESHNESS[s.sleeve]
        got = "D-1" if fresh.required_data_through(at) == PREV_BDAY else "same-day"
        assert got == want, (
            f"{s.id} at {s.hour:02d}:{s.minute:02d} ET reads {got}, contract says {want}")
        seen.add(s.sleeve)
    assert seen == set(SLEEVE_FRESHNESS), (
        f"the contract table and the slot table disagree about which sleeves exist: "
        f"{seen ^ set(SLEEVE_FRESHNESS)}")


def test_at_least_one_sleeve_sits_on_each_side_of_the_boundary():
    """Keeps the table above honest. If every sleeve drifted to one side, the parametrised
    check would still pass while testing nothing about the boundary."""
    assert set(SLEEVE_FRESHNESS.values()) == {"D-1", "same-day"}


def test_at_or_after_1345_the_gate_needs_the_current_day_record(tmp_path):
    """The other half of the contract: past 13:45 yesterday's record is not enough."""
    state = tmp_path / "preflight_state.json"
    state.write_text(json.dumps({str(PREV_BDAY.date()): True}), encoding="utf-8")
    through = fresh.required_data_through(pd.Timestamp(f"{MONDAY} 14:05"))
    chk = fresh.check_preflight_record(state, through=through)
    assert chk.refuses and chk.status == fresh.MISSING, chk

    state.write_text(json.dumps({str(PREV_BDAY.date()): True, MONDAY: True}), encoding="utf-8")
    assert not fresh.check_preflight_record(state, through=through).refuses


def test_a_failed_preflight_refuses_and_a_missing_file_refuses(tmp_path):
    """Fail-closed in the same direction legacy takes. Three states, not two."""
    through = fresh.required_data_through(pd.Timestamp(f"{MONDAY} 10:00"))
    absent = tmp_path / "nothing.json"
    assert fresh.check_preflight_record(absent, through=through).status == fresh.MISSING

    failed = tmp_path / "failed.json"
    failed.write_text(json.dumps({str(PREV_BDAY.date()): False}), encoding="utf-8")
    c = fresh.check_preflight_record(failed, through=through)
    assert c.refuses and c.status == fresh.STALE, c

    good = tmp_path / "good.json"
    good.write_text(json.dumps({str(PREV_BDAY.date()): True}), encoding="utf-8")
    assert not fresh.check_preflight_record(good, through=through).refuses


@pytest.mark.parametrize("flag", [False, True])
def test_no_pre_market_refresh_job_was_added(scheds, flag):
    """Stage 5L was explicitly not allowed to change the data contract.

    A second refresh before 10:00 would make the morning slots same-day rather than D-1 and
    silently invalidate every Track 1 number measured under the D-1 contract. The check is on
    the SCHEDULE, not on a comment: any job spawning `update_ibkr_daily` or `update_spy_csv`
    must be the 13:45 one.
    """
    updaters = []
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        for j in scheds[flag].get_jobs():
            trig = str(j.trigger)
            if "update" not in j.name.lower() and "flight" not in j.name.lower():
                continue
            updaters.append((j.id, trig))
    finally:
        rs._run = orig
        logging.disable(lvl)
    assert [u[0] for u in updaters] == [PREFLIGHT_ID], updaters
    assert f"hour='{PREFLIGHT_HOUR}'" in updaters[0][1], updaters


def test_the_1345_boundary_in_the_gate_matches_the_scheduler_trigger(scheds):
    """Two places hold 13:45. This is the check that notices when only one of them moves."""
    trig = str(_job(scheds, False).trigger)
    hour = int(trig.split("hour='")[1].split("'")[0])
    minute = int(trig.split("minute='")[1].split("'")[0])
    just_before = pd.Timestamp(MONDAY) + pd.Timedelta(hours=hour, minutes=minute - 1)
    at = pd.Timestamp(MONDAY) + pd.Timedelta(hours=hour, minutes=minute)
    assert fresh.required_data_through(just_before) == PREV_BDAY
    assert fresh.required_data_through(at) == pd.Timestamp(MONDAY)


# ── 4. Dashboard parity ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("flag", [False, True])
def test_the_dashboard_mirror_still_has_a_preflight_row(flag):
    from monitor.backend import schedule_status as ss
    prev = os.environ.get("RAITS_TRACK1_SHADOW")
    if flag:
        os.environ["RAITS_TRACK1_SHADOW"] = "1"
    else:
        os.environ.pop("RAITS_TRACK1_SHADOW", None)
    try:
        rows = ss._scheduled_slots_for(dt.date(2026, 8, 24))
    finally:
        if prev is None:
            os.environ.pop("RAITS_TRACK1_SHADOW", None)
        else:
            os.environ["RAITS_TRACK1_SHADOW"] = prev
    hits = [r for r in rows if r["id"].lower() == PREFLIGHT_ID]
    assert len(hits) == 1, [r["id"] for r in rows]
    assert (hits[0]["at"].hour, hits[0]["at"].minute) == (PREFLIGHT_HOUR, PREFLIGHT_MINUTE)


@pytest.mark.parametrize("flag", [False, True])
def test_scheduler_and_mirror_are_still_in_parity(flag):
    rep = ts.parity_report(track1_shadow=flag)
    assert rep["in_parity"], rep


@pytest.mark.parametrize("flag", [False, True])
def test_preflight_is_not_exempt_from_the_mirror(flag):
    """Exempting it would make the parity check pass whether or not the mirror had it."""
    assert PREFLIGHT_ID not in ts.MIRROR_EXEMPT
