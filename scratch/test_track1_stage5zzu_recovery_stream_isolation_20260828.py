"""Stage 5ZZU — a job may only be closed by another job that did the same work.

Stage 5ZZT found a stop-repair sweep closing a failed SPY refresh. Splitting the SPY ladder out
fixed that pair and left the mechanism: Track 1's own maintenance jobs still shared the `other`
bucket, and two lanes read that bucket as a stream in OPPOSITE directions —

    the journal lane   grouped them all, so anything completing closed anything that failed
    the issue lane     fell back to the job id, so a sweep that failed at 06:20 could never be
                       closed by the identical sweep at 08:20

Both are wrong and both are fixed by the same thing: a real type. So the tests come in pairs.
Every "must not close" here has a "must close" beside it, because a change that made nothing
ever recover would satisfy half of this file and be a worse bug than the one it replaced.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_slots as t1                    # noqa: E402
from monitor.backend import job_journal_reader as jj           # noqa: E402
from monitor.backend import open_issue_reader as oi            # noqa: E402

T1_SWEEP = "track1_safety_stop_repair"
T1_MAXHOLD = "track1_safety_max_hold"
T1_AUDIT = "track1_window_audit"


def _job(job_id, status, started, **extra):
    job = {"job_id": job_id, "job_type": jj._job_type(job_id), "status": status,
           "started_at": started, "ended_at": started, "diagnostics": [],
           "impact": None, "action": None, "reason": "slot missed"}
    job.update(extra)
    return job


def _recovery(pairs):
    jobs = [_job(*p) for p in pairs]
    jj._annotate_impact_and_action(jobs)
    return {j["job_id"]: j for j in jobs}


def _closed_by_later(first, second):
    """Did `second` completing close `first`? first=(id, status), second=(id,)."""
    out = _recovery([(first[0], first[1], "2026-08-27T10:20:00Z"),
                     (second, "completed", "2026-08-27T12:20:00Z")])
    return out[first[0]]["lifecycle_status"] == "recovered"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. every maintenance job has a type of its own
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_no_track1_maintenance_job_is_left_in_the_catch_all():
    """Read from the production tables, not from a list restated here."""
    ids = ([j.id.upper() for j in t1.track1_safety_jobs()]
           + [j.id.upper() for j in t1.track1_audit_jobs()])
    assert ids, "the safety/audit tables are empty — the fixture is broken, not the code"
    for jid in ids:
        assert jj._job_type(jid) != "other", jid
        assert jj._job_type(jid) in jj.TRACK1_MAINTENANCE_TYPES, (jid, jj._job_type(jid))


def test_both_spellings_of_the_max_hold_id_are_typed():
    """The slot table declares `track1_maxhold_exit`; the log label that reaches the reader is
    TRACK1_MAX_HOLD_EXIT. Matching one spelling types the job on some days and not others."""
    assert jj._job_type("TRACK1_MAXHOLD_EXIT") == T1_MAXHOLD
    assert jj._job_type("TRACK1_MAX_HOLD_EXIT") == T1_MAXHOLD


def test_the_three_types_are_distinct_from_each_other_and_from_legacy():
    assert len({T1_SWEEP, T1_MAXHOLD, T1_AUDIT}) == 3
    for t in (T1_SWEEP, T1_MAXHOLD, T1_AUDIT):
        assert t not in {"stop_repair", "max_hold", "spy_refresh_pm",
                         "spy_last_chance_pre_nkd", "preflight", "other"}


def test_recovery_matches_on_a_structured_type_not_a_substring():
    """`TRACK1_STOP_REPAIR_0620` contains the string `STOP_REPAIR`. If any lane matched on a
    substring the two routes' sweeps would share a stream, which is the whole thing B1 exists
    to keep apart."""
    assert jj._job_type("TRACK1_STOP_REPAIR_0620") != jj._job_type("STOP_REPAIR_0620")
    assert jj._job_type("TRACK1_MAX_HOLD_EXIT") != jj._job_type("MAX_HOLD_EXIT")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. must NOT close — and, beside each, must close
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_an_audit_does_not_close_a_failed_sweep():
    assert not _closed_by_later(("TRACK1_STOP_REPAIR_0620", "failed"), "TRACK1_AUDIT_DAILY")


def test_a_sweep_does_not_close_a_failed_audit():
    assert not _closed_by_later(("TRACK1_AUDIT_ROSKA4_CALM", "failed"),
                                "TRACK1_STOP_REPAIR_1820")


def test_an_audit_does_not_close_a_failed_max_hold_check():
    assert not _closed_by_later(("TRACK1_MAX_HOLD_EXIT", "failed"), "TRACK1_AUDIT_DAILY")


def test_a_legacy_sweep_does_not_close_a_track1_sweep():
    assert not _closed_by_later(("TRACK1_STOP_REPAIR_0620", "failed"), "STOP_REPAIR_0820")


def test_a_track1_sweep_does_not_close_a_legacy_sweep():
    assert not _closed_by_later(("STOP_REPAIR_0620", "failed"), "TRACK1_STOP_REPAIR_0820")


def test_a_spy_refresh_does_not_close_a_track1_sweep():
    """The 5ZZT pairing, from the other side."""
    assert not _closed_by_later(("TRACK1_STOP_REPAIR_0620", "failed"), "SPY_REFRESH_PM_R1")


def test_a_track1_sweep_does_not_close_a_spy_refresh():
    """The measured 2026-08-27 defect itself: TRACK1_STOP_REPAIR_1820 closed SPY_REFRESH_PM_R1."""
    assert not _closed_by_later(("SPY_REFRESH_PM_R1", "failed"), "TRACK1_STOP_REPAIR_1820")


def test_a_later_sweep_DOES_close_an_earlier_failed_sweep():
    """The complement. Without this the file would be satisfied by a change that made nothing
    ever recover — which is how the issue lane was already broken, in the other direction."""
    assert _closed_by_later(("TRACK1_STOP_REPAIR_0620", "failed"), "TRACK1_STOP_REPAIR_0820")


def test_a_later_audit_DOES_close_an_earlier_failed_audit():
    assert _closed_by_later(("TRACK1_AUDIT_ROSKA4_CALM", "failed"), "TRACK1_AUDIT_DAILY")


def test_the_legacy_sweep_stream_still_recovers_itself():
    """Untouched behaviour, pinned so this stage cannot have quietly changed it."""
    assert _closed_by_later(("STOP_REPAIR_0620", "failed"), "STOP_REPAIR_0820")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. the issue lane, where the failure pointed the other way
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_issue_lane_groups_track1_sweeps_together():
    a = oi._stream(_job("TRACK1_STOP_REPAIR_0620", "failed", "x"))
    b = oi._stream(_job("TRACK1_STOP_REPAIR_0820", "completed", "x"))
    assert a == b == T1_SWEEP


def test_the_issue_lane_keeps_sweeps_audits_and_max_hold_apart():
    streams = {oi._stream(_job(jid, "failed", "x")) for jid in
               ("TRACK1_STOP_REPAIR_0620", "TRACK1_AUDIT_DAILY", "TRACK1_MAX_HOLD_EXIT")}
    assert len(streams) == 3, streams


def test_the_issue_lane_no_longer_falls_back_to_a_job_id_for_these():
    """The fallback is what made every Track 1 sweep its own stream, so an issue opened at
    06:20 could not be closed by the sweep that ran at 08:20 doing the identical check."""
    for jid in ("TRACK1_STOP_REPAIR_0620", "TRACK1_AUDIT_DAILY", "TRACK1_MAX_HOLD_EXIT"):
        assert oi._stream(_job(jid, "failed", "x")) != jid


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. wording that belongs to the job
# ══════════════════════════════════════════════════════════════════════════════════════════

def _worded(job_id, status):
    return _recovery([(job_id, status, "2026-08-27T10:20:00Z")])[job_id]


def test_a_track1_safety_failure_talks_about_the_track1_book_and_its_stops():
    for status in ("failed", "missed"):
        out = _worded("TRACK1_STOP_REPAIR_0620", status)
        assert "Track 1" in out["impact"], (status, out["impact"])
        assert "stop" in out["impact"].lower(), (status, out["impact"])


def test_the_max_hold_check_talks_about_positions_past_their_hold():
    out = _worded("TRACK1_MAX_HOLD_EXIT", "failed")
    assert "max hold" in out["impact"].lower() or "max-hold" in out["impact"].lower()
    assert "Track 1" in out["impact"]


def test_an_audit_failure_talks_about_evidence_and_never_about_the_broker():
    """The `other` wording told an operator to reconcile broker state. This job reads the
    route's own evidence records and never touches the broker."""
    for status in ("failed", "missed"):
        out = _worded("TRACK1_AUDIT_ROSKA4_CALM", status)
        assert "evidence" in out["impact"].lower(), (status, out["impact"])
        assert "broker" not in out["impact"].lower(), (status, out["impact"])
        assert "broker" not in out["action"].lower(), (status, out["action"])


def test_no_track1_maintenance_job_is_told_to_reconcile_the_broker():
    for jid in ("TRACK1_STOP_REPAIR_0620", "TRACK1_AUDIT_DAILY", "TRACK1_MAX_HOLD_EXIT"):
        for status in ("failed", "missed"):
            out = _worded(jid, status)
            assert "unclassified error" not in (out["impact"] or ""), (jid, status)
            assert "reconcile current broker state" not in (out["action"] or ""), (jid, status)


def test_a_recovered_sweep_says_which_sweep_caught_it():
    out = _recovery([("TRACK1_STOP_REPAIR_0620", "missed", "2026-08-27T10:20:00Z"),
                     ("TRACK1_STOP_REPAIR_0820", "completed", "2026-08-27T12:20:00Z")])
    first = out["TRACK1_STOP_REPAIR_0620"]
    assert "TRACK1_STOP_REPAIR_0820" in first["impact"]
    assert "No immediate action" in first["action"]


def test_a_sweep_nothing_caught_still_says_the_stops_were_not_rechecked():
    out = _worded("TRACK1_STOP_REPAIR_0620", "missed")
    assert "not rechecked" in out["impact"], out["impact"]


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. the UI reads the type, and does not print an identifier as a label
# ══════════════════════════════════════════════════════════════════════════════════════════

JS = REPO / "global_index" / "dash" / "realtime" / "realtime.js"


def test_the_ui_keeps_these_jobs_attributed_to_the_scheduler():
    """They reached the scheduler-owned list through `other`. Typing them without naming them
    here would have moved a missed sweep to `runner` — blamed on a runner that never ran."""
    code = JS.read_text(encoding="utf-8")
    block = code.split("const SCHEDULER_OWNED")[1].split("];")[0]
    for t in (T1_SWEEP, T1_MAXHOLD, T1_AUDIT):
        assert t in block, t
    for t in ("stop_repair", "preflight", "session_report", "other"):
        assert f"'{t}'" in block, f"{t} was dropped from the scheduler-owned list"


def test_the_ui_labels_jobs_by_type_and_keeps_the_id_for_the_tooltip():
    code = JS.read_text(encoding="utf-8")
    assert "function jobLabel" in code
    for t in (T1_SWEEP, T1_MAXHOLD, T1_AUDIT):
        assert t in code.split("MV_JOB_NAMES")[1][:1200], t
    assert '<span class="job-name" title="${esc(job.job_id)}">${esc(jobLabel(job))}</span>' in code
    assert "${job.job_id} slot missed" not in code, "an identifier is still a primary label"
    assert "${job.job_id} failed" not in code, "an identifier is still a primary label"


def test_the_ui_falls_back_rather_than_rendering_nothing():
    """A job type this map has not met must read as its id, not as blank."""
    code = JS.read_text(encoding="utf-8")
    fn = code.split("function jobLabel")[1].split("\n  }")[0]
    assert "job.job_id" in fn and "Unknown job" in fn


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6. real data, and the gates
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_real_journal_shows_no_false_recovery_for_these_jobs():
    """Every Track 1 maintenance job in the retained journal completed, so not one of them may
    carry a recovery marker — a marker on a completed job would mean the annotation is firing
    on something other than a failure."""
    for day in ("2026-08-26", "2026-08-27", "2026-08-28"):
        r = jj.read_job_journal(day, REPO)
        jobs = r.get("jobs") if isinstance(r, dict) else r
        maint = [j for j in jobs if j["job_type"] in jj.TRACK1_MAINTENANCE_TYPES]
        assert maint, f"{day}: no Track 1 maintenance jobs found — the fixture proves nothing"
        for j in maint:
            if j["status"] == "completed":
                assert j.get("lifecycle_status") is None, (day, j["job_id"])
                assert j.get("recovered_at") is None, (day, j["job_id"])


def test_orders_remain_impossible():
    from global_index import track1_gates as G
    allowed, reasons = G.may_enable_orders()
    assert allowed is False
    # NOT an equality check on the blocker list. Measured 2026-08-28T11:31:07Z: B1 reopened
    # because the account baseline record passed its 24-hour freshness policy 81 seconds
    # earlier - the gate doing exactly what it is built to do. A test that pins the exact list
    # goes red for the passage of time and says nothing about this stage.
    ids = [r.split(":")[0] for r in reasons]
    assert "PAPER_SHADOW_EVIDENCE" in ids, ids


def test_this_stage_created_no_order_artefacts():
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not (REPO / "global_index" / "live_positions.track1.json").exists()
