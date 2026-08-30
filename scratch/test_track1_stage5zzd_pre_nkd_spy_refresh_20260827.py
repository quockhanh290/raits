"""Stage 5ZZD — the last look before anything freshness-bound runs.

The evening ladder asks for the day that just closed. This job asks a DIFFERENT question: the day
the sleeves about to run will demand, which at a quarter to one in the morning is the previous
TRADING day. Those two coincide from Tuesday to Friday and do not coincide on a Monday, when the
previous trading day is the Friday and the last evening rung ran thirty-one hours earlier.

Nothing here calls Polygon. Nothing writes outside tmp_path. The production series is read but
never modified.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "monitor"))

from global_index import run_scheduler as rs  # noqa: E402
from global_index import track1_freshness as fresh  # noqa: E402
from global_index import update_spy_csv as spy  # noqa: E402

JOB = "spy_last_chance_pre_nkd"
LABEL = "SPY_LAST_CHANCE_PRE_NKD"


def _fire(monkeypatch, caplog, *, et_today, series_before, series_after=None, rc=0):
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
    sched = rs.make_scheduler(port=7497, dry_run=False, track1_only=True)
    job = {j.id: j for j in sched.get_jobs()}[JOB]
    with caplog.at_level(logging.INFO, logger="run_scheduler"):
        job.func()
    return calls, "\n".join(r.getMessage() for r in caplog.records)


# ═══════════════════════════════════════════════════════════════════════════════
# 1-3  registered, timed, and asking the right question
# ═══════════════════════════════════════════════════════════════════════════════

def test_1_the_job_is_registered_before_the_first_nkd_slot():
    logging.disable(logging.CRITICAL)
    sched = rs.make_scheduler(port=7497, dry_run=True, track1_only=True)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert JOB in jobs, "the last-chance job is not registered"

    f = {x.name: str(x) for x in jobs[JOB].trigger.fields}
    at = (int(f["hour"]), int(f["minute"]))
    assert at == (0, 45), at
    assert "mon" in f["day_of_week"], f["day_of_week"]

    nkd = [(int({x.name: str(x) for x in j.trigger.fields}["hour"]),
            int({x.name: str(x) for x in j.trigger.fields}["minute"]))
           for j in sched.get_jobs() if j.id.startswith("track1_nkd_")]
    assert nkd, "no NKD slots — this test would pass on an empty schedule"
    assert at < min(nkd), f"the last chance fires at {at}, not before the first NKD {min(nkd)}"
    assert (min(nkd)[0] * 60 + min(nkd)[1]) - (at[0] * 60 + at[1]) >= 15, \
        "less than fifteen minutes to fetch, verify and be read"


def test_2_the_ladder_and_the_last_chance_are_four_separate_jobs():
    logging.disable(logging.CRITICAL)
    sched = rs.make_scheduler(port=7497, dry_run=True, track1_only=True)
    ids = {j.id for j in sched.get_jobs()}
    assert {"spy_refresh_pm", "spy_refresh_pm_r1", "spy_refresh_pm_r2", JOB} <= ids


def test_3_the_required_day_is_the_previous_TRADING_day_at_this_hour(monkeypatch, caplog):
    """Tuesday-to-Friday it is yesterday. On a Monday it is the Friday, and that is the whole
    reason this job exists: nothing between Friday 17:15 and Monday 01:10 has ever looked."""
    # Thursday 2026-08-27 -> Wednesday
    calls, out = _fire(monkeypatch, caplog, et_today="2026-08-27", series_before="2026-08-25")
    assert "2026-08-26" in out, out
    assert calls and calls[0][calls[0].index("--require-through") + 1] == "2026-08-26"

    caplog.clear()
    # Monday 2026-08-31 -> the Friday, not the Sunday
    calls, out = _fire(monkeypatch, caplog, et_today="2026-08-31", series_before="2026-08-27")
    assert calls[0][calls[0].index("--require-through") + 1] == "2026-08-28"
    assert pd.Timestamp("2026-08-28").weekday() == 4, "the anchor is not a Friday"


def test_4_a_holiday_is_skipped_the_same_way(monkeypatch, caplog):
    """2026-09-07 is the first Monday of September — Labor Day. The Tuesday after it must ask
    for the Friday before it, not for the holiday."""
    assert pd.Timestamp("2026-09-07").weekday() == 0
    calls, _ = _fire(monkeypatch, caplog, et_today="2026-09-08", series_before="2026-09-01")
    asked = calls[0][calls[0].index("--require-through") + 1]
    assert asked == "2026-09-04", f"asked for {asked}, which is the holiday or the wrong side"


def test_5_the_job_asks_the_gate_rather_than_restating_the_rule():
    import inspect

    src = inspect.getsource(rs.make_scheduler)
    i = src.index("def job_spy_last_chance_pre_nkd")
    body = src[i:i + 4000]
    assert "required_daily_close_through" in body, \
        "the job computes the required day itself; a second copy drifts from the gate that " \
        "actually refuses, and then it reports fine about a morning the gate will stop"
    assert "_et_today" in body, \
        "the job reads the machine's calendar; west of ET the 01:10 slots land on the " \
        "previous local date and it would ask for the wrong session by one day"


# ═══════════════════════════════════════════════════════════════════════════════
# 6-8  the three things it can do
# ═══════════════════════════════════════════════════════════════════════════════

def test_6_it_does_nothing_and_calls_nothing_when_the_day_is_already_there(
        monkeypatch, caplog):
    calls, out = _fire(monkeypatch, caplog, et_today="2026-08-27", series_before="2026-08-26")
    assert calls == [], "it launched a refresh when the day was already in the series"
    assert "nothing to do" in out
    assert "missing" not in out.lower()


def test_7_a_series_ahead_of_the_requirement_is_also_nothing_to_do(monkeypatch, caplog):
    """It must compare, not equal. A file that already has today is not a file that is short."""
    calls, out = _fire(monkeypatch, caplog, et_today="2026-08-27", series_before="2026-08-27")
    assert calls == []
    assert "nothing to do" in out


def test_8_when_the_day_arrives_at_the_last_look_it_says_RECOVERED(monkeypatch, caplog):
    calls, out = _fire(monkeypatch, caplog, et_today="2026-08-27",
                       series_before="2026-08-25", series_after="2026-08-26", rc=0)
    assert calls, "it did not try"
    assert "RECOVERED" in out
    # and it says the evening ladder is running early, because that is the real repair
    assert "17:15" in out


# ═══════════════════════════════════════════════════════════════════════════════
# 9-11  the failure nobody else will catch
# ═══════════════════════════════════════════════════════════════════════════════

def test_9_a_final_shortfall_is_loud_and_names_who_it_stops(monkeypatch, caplog):
    calls, out = _fire(monkeypatch, caplog, et_today="2026-08-27",
                       series_before="2026-08-25", series_after="2026-08-25",
                       rc=spy.EXIT_COVERAGE_SHORT)
    assert calls, "it did not try"
    assert "SPY daily file is missing 2026-08-26" in out
    assert "NKD/Calm freshness-bound slots will refuse unless manually refreshed" in out
    # it must name that nothing else looks, and give the command
    assert "13:45" in out and "update_spy_csv" in out
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errs, "the final shortfall was not logged at ERROR"


def test_10_the_final_failure_reads_differently_from_an_evening_rung(monkeypatch, caplog):
    """Same shortfall, two moments, two reactions. The 17:15 rung says a morning is at risk;
    this one says the morning is lost unless somebody acts now."""
    _, last = _fire(monkeypatch, caplog, et_today="2026-08-27",
                    series_before="2026-08-25", series_after="2026-08-25",
                    rc=spy.EXIT_COVERAGE_SHORT)
    assert LABEL in last
    assert "LAST attempt" in last or "LAST ATTEMPT" in last.upper()

    caplog.clear()
    seq = iter(["2026-08-25", "2026-08-25"])
    monkeypatch.setattr(rs, "_spy_series_last_day", lambda csv: next(seq, "2026-08-25"))
    monkeypatch.setattr(rs, "_run",
                        lambda *a, rc_out=None, **k: (rc_out.append(2) if rc_out is not None
                                                      else None) or False)
    sched = rs.make_scheduler(port=7497, dry_run=False, track1_only=True)
    with caplog.at_level(logging.INFO, logger="run_scheduler"):
        {j.id: j for j in sched.get_jobs()}["spy_refresh_pm_r2"].func()
    evening = "\n".join(r.getMessage() for r in caplog.records)
    assert "SPY_REFRESH_PM_R2" in evening
    assert LABEL not in evening, "the two failures are not told apart by their label"


def test_11_a_dry_run_invents_no_failure(monkeypatch, caplog):
    logging.disable(logging.NOTSET)
    monkeypatch.setattr(rs, "_et_today", lambda: pd.Timestamp("2026-08-27").date())
    monkeypatch.setattr(rs, "_spy_series_last_day", lambda csv: "2026-08-25")
    monkeypatch.setattr(rs, "_run", lambda *a, **k: True)
    sched = rs.make_scheduler(port=7497, dry_run=True, track1_only=True)
    with caplog.at_level(logging.INFO, logger="run_scheduler"):
        {j.id: j for j in sched.get_jobs()}[JOB].func()
    out = "\n".join(r.getMessage() for r in caplog.records)
    assert "dry-run" in out
    assert "missing" not in out.split("dry-run")[-1].lower(), \
        "a command that was never sent produced a shortfall report"


# ═══════════════════════════════════════════════════════════════════════════════
# 12-14  the argv, and what it may never contain
# ═══════════════════════════════════════════════════════════════════════════════

def test_12_the_argv_verifies_and_names_the_day_and_skips_when_covered(monkeypatch, caplog):
    calls, _ = _fire(monkeypatch, caplog, et_today="2026-08-27", series_before="2026-08-25")
    cmd = calls[0]
    assert "--verify-strict" in cmd
    assert "--require-through" in cmd
    assert "--skip-if-covered" in cmd, \
        "without it, a race where the day lands between the check and the run would fail"
    pd.Timestamp(cmd[cmd.index("--require-through") + 1])


def test_13_no_spy_job_and_no_track1_slot_can_ask_for_orders(monkeypatch, caplog):
    calls, _ = _fire(monkeypatch, caplog, et_today="2026-08-27", series_before="2026-08-25")
    for cmd in calls:
        assert "--allow-orders" not in cmd
    from global_index import track1_slots as ts
    assert ts.TRACK1_SLOTS
    for s in ts.TRACK1_SLOTS:
        argv = ["--sleeve", s.sleeve, "--slot-id", s.id, "--bar-provider", "ibkr"] \
            + (["--phase", s.phase] if s.phase else [])
        assert "--allow-orders" not in argv, s.id


def test_14_orders_are_still_impossible():
    from global_index import track1_gates as gates

    possible, blocking = gates.may_enable_orders()
    assert possible is False
    assert blocking, "nothing is blocking, which is not the state this stage should leave"
    assert not Path("global_index/track1_runtime/orders").exists()
    assert not Path("track1_go_live_confirmation.json").exists()


def test_15_the_spy_family_is_five_jobs_in_every_mode():
    """Written as a property from the start, not as a total.

    The equivalent test in the previous stage pinned the schedule's whole size and this stage
    broke it by adding one unrelated job — a pin failing for something it is not about. The
    family is what this is about, so the family is what it counts, and an unrelated job added
    tomorrow leaves it alone.

    Stage 5ZZZ-AC added a FIFTH member, and this one is not unrelated: `spy_weekend_pre_nkd_
    check` runs Sunday 18:00 ET and asks the same question the 00:45 job asks, early enough
    to act on. So the expected set grew by one on purpose, and the count in the name grew
    with it rather than the assertion being loosened to "at least four".
    """
    logging.disable(logging.CRITICAL)
    for name, kw in (("legacy", {}), ("transitional", {"track1_shadow": True}),
                     ("track1_only", {"track1_only": True})):
        ids = {j.id for j in rs.make_scheduler(port=7497, dry_run=True, **kw).get_jobs()}
        family = {i for i in ids if i.startswith("spy_")}
        assert family == {"spy_refresh_pm", "spy_refresh_pm_r1", "spy_refresh_pm_r2",
                          JOB, "spy_weekend_pre_nkd_check"}, f"{name}: {sorted(family)}"


# ═══════════════════════════════════════════════════════════════════════════════
# 16-17  status and dashboard already answer at this hour
# ═══════════════════════════════════════════════════════════════════════════════

def test_16_status_computes_the_same_requirement_at_this_hour(tmp_path, monkeypatch):
    import ops

    got = ops.spy_daily_coverage(str(_series(tmp_path, "2026-08-25")),
                                 now_et=pd.Timestamp("2026-08-27 00:45"))
    assert got["required"] == "2026-08-26"
    assert got["state"] == spy.COVERAGE_SHORT
    assert "SPY daily file is missing 2026-08-26" in got["line"]


def test_17_the_dashboard_keeps_it_apart_from_the_window_verdict(tmp_path, monkeypatch):
    from monitor.backend import track1_runtime_reader as rd

    monkeypatch.setattr(rd, "_today_et", lambda: pd.Timestamp("2026-08-27"))
    _series(tmp_path, "2026-08-25", name="spy_daily_live.csv")
    d = rd._spy_daily(tmp_path)
    assert d["separate_from_slot_status"] is True
    low = d["line"].lower()
    assert "not a slot failure" in low
    for forbidden in ("nkd failed", "window failed", "operational failed"):
        assert forbidden not in low


def _series(tmp_path, last, name="spy.csv") -> Path:
    days = pd.bdate_range(end=pd.Timestamp(last), periods=30)
    p = tmp_path / name
    pd.DataFrame({"date": [d.date().isoformat() for d in days],
                  "close": [700.0 + i for i in range(len(days))]}).to_csv(p, index=False)
    return p


# ═══════════════════════════════════════════════════════════════════════════════
# mutations (M1, M2) and source guards (G1, G2)
#
# The distinction is kept honest rather than flattened. M1 and M2 REPLACE the calendar the job
# reads and demand the matching test go red — that is a mutation. G1 and G2 assert a property of
# the source, because the two branches they protect live inside a closure that cannot be reached
# from outside to be broken. A source guard is weaker: it catches an edit, not a behaviour. It is
# labelled so nobody counts four mutations here.
# ═══════════════════════════════════════════════════════════════════════════════

def _must_fail(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except AssertionError:
        return True
    return False


def test_M1_the_requirement_becomes_the_machine_date_mutation(monkeypatch, caplog):
    """Collapse: the job asks for today's date instead of the previous trading day, so on a
    Monday it demands a session that has not happened and refuses every week."""
    monkeypatch.setattr(fresh, "required_daily_close_through",
                        lambda now: pd.Timestamp(now).normalize())
    assert _must_fail(test_3_the_required_day_is_the_previous_TRADING_day_at_this_hour,
                      monkeypatch, caplog), \
        "test_3 stayed green while the requirement moved to the session's own day"


def test_M2_the_holiday_is_no_longer_skipped_mutation(monkeypatch, caplog):
    monkeypatch.setattr(fresh, "required_daily_close_through",
                        lambda now: pd.Timestamp(now).normalize() - pd.Timedelta(days=1))
    assert _must_fail(test_4_a_holiday_is_skipped_the_same_way, monkeypatch, caplog), \
        "test_4 stayed green while the calendar stopped skipping a holiday"


def test_G1_the_final_shortfall_is_still_logged_at_error(monkeypatch, caplog):
    """SOURCE GUARD, not a mutation. The branch is inside a closure and cannot be replaced from
    here; what can be held is that the loudest message in the chain has not quietly become a
    note. Nothing after this job looks before the sleeves do."""
    import global_index.run_scheduler as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    i = src.index("SPY daily file is missing %s; NKD/Calm")
    before = src[max(0, i - 400):i]
    assert "log.error" in before, \
        "the final shortfall is no longer logged at ERROR — nothing after it looks"


def test_G2_the_no_op_comparison_has_not_changed_shape(monkeypatch, caplog):
    """SOURCE GUARD plus a live baseline. The live half proves a covered night calls nothing;
    the source half catches the comparison being inverted or narrowed to equality, which would
    send a good night to the provider where it can fail."""
    calls, _ = _fire(monkeypatch, caplog, et_today="2026-08-27", series_before="2026-08-26")
    assert calls == [], "baseline is already broken"

    import global_index.run_scheduler as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "if covered == need_s or (covered and covered > need_s):" in src, \
        "the no-op comparison changed shape; a covered night may now reach the provider"
