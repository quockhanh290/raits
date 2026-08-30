"""Stage 5ZZZ-AC — the Sunday early look at the SPY daily series.

On Friday 2026-08-28 all three evening rungs ran and the provider still did not return that
day's close. The next automatic look was Monday 00:45, twenty-five minutes before the NKD
window — fifty-five hours of silence, ending in the middle of the night with no time to act.

This job asks the same question on Sunday evening instead. Nothing here calls Polygon, nothing
is spawned, and nothing outside tmp_path is written.
"""
from __future__ import annotations

import datetime as dt
import logging
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "monitor"))

from global_index import run_scheduler as rs               # noqa: E402
from global_index import track1_freshness as fresh         # noqa: E402

JOB = "spy_weekend_pre_nkd_check"
LABEL = "SPY_WEEKEND_PRE_NKD_CHECK"
LAST_CHANCE = "spy_last_chance_pre_nkd"


def _fire(monkeypatch, caplog, *, et_today, series_before, series_after=None, rc=0,
          dry_run=False):
    """Fire the real registered job with the clock, the series reader and the launcher
    replaced. Nothing is spawned and nothing is written."""
    logging.disable(logging.NOTSET)
    seq = iter([series_before, series_after if series_after is not None else series_before])
    monkeypatch.setattr(rs, "_et_today", lambda: pd.Timestamp(et_today).date())
    monkeypatch.setattr(rs, "_spy_series_last_day",
                        lambda csv: next(seq, series_after or series_before))

    calls: list = []

    def _cap(args, label=None, dry_run=None, timeout=None, route=None, rc_out=None):
        calls.append(list(args))
        if rc_out is not None:
            rc_out.append(rc)
        return rc == 0

    monkeypatch.setattr(rs, "_run", _cap)
    sched = rs.make_scheduler(port=7497, dry_run=dry_run, track1_only=True)
    job = {j.id: j for j in sched.get_jobs()}[JOB]
    with caplog.at_level(logging.INFO, logger="run_scheduler"):
        job.func()
    return calls, "\n".join(r.getMessage() for r in caplog.records)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. registered where and when it should be
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_job_is_registered_on_sunday_at_18_00_et():
    sched = rs.make_scheduler(port=7497, dry_run=True, track1_only=True)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert JOB in jobs, sorted(jobs)
    f = {str(x.name): str(x) for x in jobs[JOB].trigger.fields}
    assert f["day_of_week"] == "sun", f
    assert f["hour"] == "18" and f["minute"] == "0", f


def test_the_monday_last_chance_job_is_untouched():
    """The brief is explicit: the 00:45 job stays. This is the guard on that."""
    sched = rs.make_scheduler(port=7497, dry_run=True, track1_only=True)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert LAST_CHANCE in jobs
    f = {str(x.name): str(x) for x in jobs[LAST_CHANCE].trigger.fields}
    assert f["day_of_week"] == "mon-fri" and f["hour"] == "0" and f["minute"] == "45"


def test_it_runs_before_the_sunday_stop_repair_sweep():
    """18:00 then 18:30: one Sunday log, data check first, protection sweep after."""
    sched = rs.make_scheduler(port=7497, dry_run=True, track1_only=True)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert "stop_repair_sun_1830" in jobs
    spy_min = int(str({str(x.name): str(x)
                       for x in jobs[JOB].trigger.fields}["minute"]))
    assert spy_min < 30


def test_the_spy_family_is_now_five_jobs():
    sched = rs.make_scheduler(port=7497, dry_run=True, track1_only=True)
    ids = {j.id for j in sched.get_jobs()}
    assert {"spy_refresh_pm", "spy_refresh_pm_r1", "spy_refresh_pm_r2",
            LAST_CHANCE, JOB} <= ids


# ═══════════════════════════════════════════════════════════════════════════════
# 2. the required day is ASKED FOR, never computed here
# ═══════════════════════════════════════════════════════════════════════════════

def _job_logic_only() -> str:
    """The job's code with every string literal blanked.

    Needed because the honest log messages mention Friday - the RECOVERED line says the day
    "arrived on the weekend after the Friday evening ladder had given up". Scanning raw code
    for the word would flag that, which conflates a sentence with a date calculation. What
    must not appear is arithmetic; what a message says is not arithmetic.
    """
    import ast

    class _Blank(ast.NodeTransformer):
        def visit_Constant(self, node):                      # noqa: N802
            return ast.Constant(value="") if isinstance(node.value, str) else node

    tree = ast.parse(_job_code_without_docstring())
    return ast.unparse(_Blank().visit(tree))


def test_the_job_asks_freshness_and_does_not_restate_the_rule():
    """The required day must be ASKED FOR. A second copy of "which day is needed" drifts
    from the gate that actually refuses, and then this job reports fine about a morning the
    gate is about to stop."""
    logic = _job_logic_only()
    assert "required_daily_close_through" in logic
    low = logic.lower()
    for hand_rolled in ("weekday()", "timedelta(", "friday", "prev_business_day", ".days -"):
        assert hand_rolled not in low, f"the day is being computed by hand: {hand_rolled}"


def test_on_this_sunday_it_asks_for_the_friday(monkeypatch, caplog):
    calls, log = _fire(monkeypatch, caplog, et_today="2026-08-30",
                       series_before="2026-08-27")
    assert "2026-08-28" in log, log


def test_a_holiday_monday_still_gives_the_previous_trading_day():
    """Sunday 2026-09-06: Monday is Labor Day, so the next NKD session is Tuesday and the
    required close is the Friday BEFORE the holiday. No special case in the job - the
    freshness module already knows."""
    need = fresh.required_daily_close_through(pd.Timestamp("2026-09-06"))
    assert str(need.date()) == "2026-09-04"
    from raits.live import trading_calendar as TC
    assert TC.is_trading_day(dt.date(2026, 9, 7)) is False
    assert TC.is_trading_day(dt.date(2026, 9, 8)) is True


def test_the_sunday_and_monday_jobs_agree_on_the_day():
    """They must ask the same question, or the earlier one reports fine about a day the
    later one is about to fail on."""
    for sun, mon in (("2026-08-30", "2026-08-31"), ("2026-09-06", "2026-09-08")):
        assert (fresh.required_daily_close_through(pd.Timestamp(sun))
                == fresh.required_daily_close_through(pd.Timestamp(mon)))


def test_it_uses_et_today_not_the_machine_date():
    code = _job_code_without_docstring()
    assert "_et_today()" in code
    assert "date.today" not in code


# ═══════════════════════════════════════════════════════════════════════════════
# 3. behaviour
# ═══════════════════════════════════════════════════════════════════════════════

def test_already_covered_calls_no_provider(monkeypatch, caplog):
    calls, log = _fire(monkeypatch, caplog, et_today="2026-08-30",
                       series_before="2026-08-28")
    assert calls == [], f"the provider was called although the day was present: {calls}"
    assert "nothing to do" in log


def test_a_series_ahead_of_the_requirement_is_also_nothing_to_do(monkeypatch, caplog):
    calls, log = _fire(monkeypatch, caplog, et_today="2026-08-30",
                       series_before="2026-08-31")
    assert calls == []
    assert "nothing to do" in log


def test_missing_calls_update_spy_csv_with_the_required_flags(monkeypatch, caplog):
    calls, log = _fire(monkeypatch, caplog, et_today="2026-08-30",
                       series_before="2026-08-27", series_after="2026-08-28")
    assert len(calls) == 1, calls
    argv = calls[0]
    assert "global_index.update_spy_csv" in argv
    assert "--verify-strict" in argv
    assert "--require-through" in argv
    assert argv[argv.index("--require-through") + 1] == "2026-08-28"
    assert "--skip-if-covered" in argv


def test_recovery_is_reported_as_a_warning_naming_the_friday_ladder(monkeypatch, caplog):
    calls, log = _fire(monkeypatch, caplog, et_today="2026-08-30",
                       series_before="2026-08-27", series_after="2026-08-28")
    assert "RECOVERED" in log
    assert "2026-08-28" in log
    assert "ladder" in log.lower()


def test_a_continuing_shortfall_is_an_error_that_names_the_manual_command(
        monkeypatch, caplog):
    calls, log = _fire(monkeypatch, caplog, et_today="2026-08-30",
                       series_before="2026-08-27", series_after="2026-08-27", rc=1)
    assert "python -m global_index.update_spy_csv" in log
    assert "--require-through" in log
    assert "2026-08-28" in log          # the required day
    assert "2026-08-27" in log          # the day it actually ends on
    assert "01:10" in log               # the window it stops
    assert "SPY_LAST_CHANCE_PRE_NKD" in log   # the remaining attempt is named


def test_a_provider_failure_stays_fail_closed(monkeypatch, caplog):
    """A failed refresh must not read as success, and must not silently pass."""
    calls, log = _fire(monkeypatch, caplog, et_today="2026-08-30",
                       series_before="2026-08-27", series_after="2026-08-27", rc=2)
    assert "RECOVERED" not in log
    assert "missing" in log.lower()


def test_a_dry_run_invents_no_failure(monkeypatch, caplog):
    calls, log = _fire(monkeypatch, caplog, et_today="2026-08-30",
                       series_before="2026-08-27", dry_run=True)
    assert "dry-run" in log
    assert "RECOVERED" not in log


def _job_code_without_docstring() -> str:
    """The job's executable code, docstring removed.

    A plain source scan matched `preflight_state.json` inside the docstring - which is there
    precisely to say the job does NOT write it. Scanning prose for the absence of a behaviour
    is how a comment gets mistaken for code; this walks the AST and drops the docstring.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(rs.make_scheduler).strip())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "job_spy_weekend_pre_nkd_check":
            body = list(node.body)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body = body[1:]                     # drop the docstring
            return "\n".join(ast.unparse(n) for n in body)
    raise AssertionError("the job was not found in the scheduler source")


def test_it_never_writes_preflight_state():
    code = _job_code_without_docstring()
    assert code, "empty body would pass on nothing"
    assert "preflight_state" not in code
    assert "preflight" not in code.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. the mirror and the journal
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_schedule_mirror_shows_it_on_sunday_at_18_00():
    from monitor.backend import schedule_status as SS

    assert SS.SUNDAY_SPY_PRE_NKD_SLOT == (6, 18, 0)
    slots = SS._scheduled_slots_for(dt.date(2026, 8, 30))
    ids = [s["id"] for s in slots]
    assert LABEL in ids, ids
    at = [s["at"] for s in slots if s["id"] == LABEL][0]
    assert (at.hour, at.minute) == (18, 0)


def test_the_mirror_keeps_it_before_the_sunday_sweep():
    from monitor.backend import schedule_status as SS

    slots = SS._scheduled_slots_for(dt.date(2026, 8, 30))
    order = [s["id"] for s in slots]
    assert order.index(LABEL) < order.index("STOP_REPAIR_SUN_1830")


def test_the_mirror_adds_nothing_on_a_weekday_or_saturday():
    from monitor.backend import schedule_status as SS

    for day in (dt.date(2026, 8, 29), dt.date(2026, 8, 31)):
        assert LABEL not in [s["id"] for s in SS._scheduled_slots_for(day)]


def test_the_journal_gives_it_its_own_job_type():
    from monitor.backend import job_journal_reader as J

    assert J._job_type(LABEL) == "spy_weekend_pre_nkd_check"


def test_its_recovery_stream_is_separate_from_the_other_spy_jobs():
    """The measured fault this guards against: an unrelated job closing a failed refresh.
    Stage 5ZZT found a stop-repair sweep marking SPY rungs `recovered`."""
    from monitor.backend import job_journal_reader as J

    streams = {J._job_type("SPY_REFRESH_PM"), J._job_type("SPY_REFRESH_PM_R1"),
               J._job_type("SPY_LAST_CHANCE_PRE_NKD"), J._job_type(LABEL)}
    assert len(streams) == 3, streams          # ladder | last-chance | weekend
    assert J._job_type(LABEL) not in {J._job_type("SPY_REFRESH_PM"),
                                      J._job_type("SPY_LAST_CHANCE_PRE_NKD")}


def test_ops_status_names_the_sunday_job_while_it_is_still_ahead():
    from monitor.ops import _spy_next_automatic_attempt

    sunday_morning = dt.datetime(2026, 8, 30, 9, 0)
    line = _spy_next_automatic_attempt(sunday_morning)
    assert LABEL in line
    assert "SPY_LAST_CHANCE_PRE_NKD" in line, "the 00:45 job must still be named"
    assert "00:45" in line


def test_ops_status_stops_naming_it_once_it_has_run():
    from monitor.ops import _spy_next_automatic_attempt

    line = _spy_next_automatic_attempt(dt.datetime(2026, 8, 30, 20, 0))
    assert "already run" in line
    assert "SPY_LAST_CHANCE_PRE_NKD" in line


def test_ops_status_on_saturday_names_both_weekend_attempts():
    from monitor.ops import _spy_next_automatic_attempt

    line = _spy_next_automatic_attempt(dt.datetime(2026, 8, 29, 12, 0))
    assert LABEL in line and "SPY_LAST_CHANCE_PRE_NKD" in line


# ═══════════════════════════════════════════════════════════════════════════════
# 5. it cannot trade
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_job_body_imports_no_broker_and_asks_for_no_order():
    import inspect

    src = inspect.getsource(rs.make_scheduler)
    body = src[src.index("def job_spy_weekend_pre_nkd_check"):]
    body = body[:body.index("\n    def ")]
    for banned in ("ib_insync", "IBKRBroker", "--allow-orders", "TRACK1_ORDERS_APPROVED",
                   "place_order", "run_live_day"):
        assert banned not in body, banned


def test_orders_remain_impossible():
    import os

    from global_index import track1_gates as G

    ok, _ = G.may_enable_orders()
    assert ok is False
    assert "PAPER_SHADOW_EVIDENCE" in {b.id for b in G.blocking()}
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not os.environ.get("TRACK1_ORDERS_APPROVED")
