"""Stage 5ZZT — the SPY refresh ladder is visible to the dashboard, and visible correctly.

The parity check that drove this stage compares slot IDS only. A row added at the wrong minute
passes it and then reports overdue every day forever — the alarm nobody can silence, which is
the failure this project has already paid for. So the first test here derives the expected
times from the scheduler's own decorators and compares them to the mirror, which is the thing
parity cannot do.
"""
from __future__ import annotations

import ast
import datetime as dt
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_slots as t1                    # noqa: E402
from monitor.backend import job_journal_reader as jj           # noqa: E402
from monitor.backend import schedule_status as ss              # noqa: E402

LADDER = ("spy_refresh_pm", "spy_refresh_pm_r1", "spy_refresh_pm_r2")
LAST_LOOK = "spy_last_chance_pre_nkd"
ALL_FOUR = LADDER + (LAST_LOOK,)


def _scheduler_cron() -> dict[str, tuple[int, int, str]]:
    """Every cron job the scheduler declares, as {id: (hour, minute, day_of_week)}.

    Read from the decorators rather than from a list written by hand here: a fixture that
    restates the schedule agrees with itself, and the whole point is to compare two files.
    """
    tree = ast.parse((REPO / "global_index" / "run_scheduler.py").read_text(encoding="utf-8"))
    out: dict[str, tuple[int, int, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            if getattr(dec.func, "attr", "") != "scheduled_job":
                continue
            if not (dec.args and isinstance(dec.args[0], ast.Constant)
                    and dec.args[0].value == "cron"):
                continue
            kw = {k.arg: k.value for k in dec.keywords}
            if not all(k in kw for k in ("id", "hour", "minute")):
                continue
            try:
                out[kw["id"].value] = (kw["hour"].value, kw["minute"].value,
                                       kw.get("day_of_week").value
                                       if kw.get("day_of_week") is not None else "")
            except AttributeError:
                continue          # a computed schedule; not one of ours
    return out


@pytest.fixture(scope="module")
def cron():
    c = _scheduler_cron()
    assert c, "no cron jobs parsed — the fixture is broken, not the scheduler"
    return c


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. the mirror knows the jobs, AT THE RIGHT TIME
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_scheduler_declares_all_four_spy_jobs(cron):
    for jid in ALL_FOUR:
        assert jid in cron, f"{jid} is not registered by the scheduler at all"
        assert cron[jid][2] == "mon-fri", (jid, cron[jid])


def test_the_mirror_holds_every_spy_job_at_the_minute_the_scheduler_runs_it(cron):
    """The check parity cannot make. Parity compares ids; this compares clocks.

    A row at the wrong minute satisfies parity and then reports overdue every single day,
    which is worse than having no row at all: an operator learns to ignore it.
    """
    mirror = {jid: (hour, minute) for jid, hour, minute in ss.PIPELINE_FIXED_SLOTS}
    for jid in ALL_FOUR:
        assert jid.upper() in mirror, f"{jid} has no row in the dashboard mirror"
        assert mirror[jid.upper()] == cron[jid][:2], (
            jid, "mirror", mirror[jid.upper()], "scheduler", cron[jid][:2])


def test_no_mirror_row_describes_a_job_the_scheduler_does_not_run(cron):
    """The other direction, which is how a row becomes a permanent phantom overdue."""
    for jid, hour, minute in ss.PIPELINE_FIXED_SLOTS:
        key = jid.lower()
        if key in cron:
            assert cron[key][:2] == (hour, minute), (jid, cron[key][:2], (hour, minute))


def test_parity_holds_in_both_modes():
    for flag in (False, True):
        r = t1.parity_report(track1_shadow=flag)
        assert r["in_parity"], (flag, r["only_in_scheduler"], r["only_in_dashboard_mirror"])


def test_the_rows_appear_on_a_trading_day_and_at_the_right_instant():
    day = dt.date(2026, 8, 28)          # a Friday, a trading day
    rows = {s["id"]: s["at"] for s in ss._scheduled_slots_for(day)}
    for jid in ALL_FOUR:
        assert jid.upper() in rows, jid
        assert rows[jid.upper()].date() == day
    assert rows["SPY_LAST_CHANCE_PRE_NKD"].hour == 0
    assert rows["SPY_REFRESH_PM_R2"].hour == 17


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. typed, and typed into the RIGHT stream
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_three_refresh_rungs_share_one_stream():
    """So that a rung caught by a later rung reads as a recovery rather than an open failure."""
    for jid in LADDER:
        assert jj._job_type(jid.upper()) == "spy_refresh_pm", jid


def test_the_last_look_is_its_own_stream():
    """It asks for the PREVIOUS TRADING DAY, not for today's close. Folding it into the ladder
    would let a 00:45 success mark an evening rung recovered for a question it never asked."""
    assert jj._job_type(LAST_LOOK.upper()) == "spy_last_chance_pre_nkd"
    assert jj._job_type(LAST_LOOK.upper()) != jj._job_type("SPY_REFRESH_PM")


def test_none_of_them_falls_into_the_catch_all():
    """`other` is not a stream, and `later_same_stream` treats it as one.

    Measured on 2026-08-27, when every rung failed: SPY_REFRESH_PM_R1 and _R2 were reported
    `lifecycle_status: recovered` at 22:20:14 — which was TRACK1_STOP_REPAIR_1820, a stop-repair
    sweep. An unrelated job closed a failed data refresh.
    """
    for jid in ALL_FOUR:
        assert jj._job_type(jid.upper()) != "other", jid


def test_none_of_them_is_a_track1_strategy_slot():
    for jid in ALL_FOUR:
        assert jj.is_track1_strategy_job(jid.upper()) is False, jid
        assert t1._bucket_for(jid) == "shared_infra", jid


def test_the_strategy_slot_count_is_untouched():
    """These are data jobs. Nothing here may change what counts as a Track 1 slot."""
    assert all(not s.id.lower().startswith("spy_") for s in t1.TRACK1_SLOTS)
    assert len(t1.TRACK1_SLOTS) == len({s.id for s in t1.TRACK1_SLOTS})


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. the language an operator reads
# ══════════════════════════════════════════════════════════════════════════════════════════

def _annotated(jobs):
    jj._annotate_impact_and_action(jobs)
    return {j["job_id"]: j for j in jobs}


def _job(job_id, status, started):
    return {"job_id": job_id, "job_type": jj._job_type(job_id), "status": status,
            "started_at": started, "ended_at": started, "diagnostics": [],
            "impact": None, "action": None}


def test_a_rung_caught_by_a_later_rung_does_not_claim_tomorrow_is_refused():
    jobs = [_job("SPY_REFRESH_PM", "missed", "2026-08-27T20:20:00Z"),
            _job("SPY_REFRESH_PM_R1", "completed", "2026-08-27T20:45:00Z")]
    out = _annotated(jobs)
    first = out["SPY_REFRESH_PM"]
    assert first["lifecycle_status"] == "recovered"
    assert "SPY_REFRESH_PM_R1" in first["impact"]
    assert "freshness refusal" not in first["impact"], first["impact"]
    assert "No immediate action" in first["action"]


def test_a_ladder_that_failed_entirely_still_says_so():
    """The softening must not become a blanket. Nothing completed here, so nothing is soft."""
    jobs = [_job("SPY_REFRESH_PM", "missed", "2026-08-27T20:20:00Z"),
            _job("SPY_REFRESH_PM_R1", "failed", "2026-08-27T20:45:00Z"),
            _job("SPY_REFRESH_PM_R2", "failed", "2026-08-27T21:15:00Z")]
    out = _annotated(jobs)
    assert "freshness refusal" in out["SPY_REFRESH_PM"]["impact"]
    for jid in LADDER:
        assert out[jid.upper()]["lifecycle_status"] == "open", jid
        assert out[jid.upper()]["recovered_at"] is None, jid


def test_a_stop_repair_sweep_cannot_recover_a_spy_refresh():
    """The measured 2026-08-27 defect, pinned so it cannot come back."""
    jobs = [_job("SPY_REFRESH_PM_R1", "failed", "2026-08-27T20:45:00Z"),
            _job("TRACK1_STOP_REPAIR_1820", "completed", "2026-08-27T22:20:14Z")]
    out = _annotated(jobs)
    assert out["SPY_REFRESH_PM_R1"]["lifecycle_status"] == "open"
    assert out["SPY_REFRESH_PM_R1"]["recovered_at"] is None


def test_the_last_look_states_its_own_consequence():
    jobs = [_job("SPY_LAST_CHANCE_PRE_NKD", "missed", "2026-08-28T04:45:00Z")]
    out = _annotated(jobs)["SPY_LAST_CHANCE_PRE_NKD"]
    assert "overnight window" in out["impact"], out["impact"]
    assert "Monday" in out["impact"], "the 31-hour gap is the case this job exists for"
    assert "00:45" in out["action"]


def test_the_last_look_is_not_given_the_ladder_wording():
    jobs = [_job("SPY_LAST_CHANCE_PRE_NKD", "missed", "2026-08-28T04:45:00Z")]
    out = _annotated(jobs)["SPY_LAST_CHANCE_PRE_NKD"]
    assert "post-close" not in out["impact"], out["impact"]
    assert "rung" not in out["impact"], out["impact"]


def test_no_spy_job_is_told_to_reconcile_broker_state():
    """What the `other` bucket used to tell an operator about a data refresh: 'reconcile
    current broker state'. These jobs never touch the broker."""
    for jid in ALL_FOUR:
        for status in ("missed", "failed"):
            out = _annotated([_job(jid.upper(), status, "2026-08-27T20:20:00Z")])[jid.upper()]
            assert "broker" not in (out["impact"] or "").lower(), (jid, status, out["impact"])
            assert "unclassified error" not in (out["impact"] or ""), (jid, status)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. nothing here touches a gate
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_orders_remain_impossible_and_the_blocker_is_unchanged():
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
