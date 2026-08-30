"""Stage 5ZZB — the daily refresh reported success and left the series a day short.

The defect is not a missing check. The post-close job already noticed and warned, in exactly the
right words: *"this is only a problem if it is still true tomorrow."* Tomorrow came, the overnight
window ran at ten past one in the morning, and nothing had looked. **The warning named its own
escalation condition and no reader existed for it.**

Alongside that, one thing genuinely was not checked: `--verify-strict` compares regime LABELS —
"1761 label(s) compared through 2024-12-31", by its own output — which is a drift check over
settled history and says nothing about whether last night's close arrived.

Nothing here calls Polygon, and nothing writes outside tmp_path.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "monitor"))

from global_index import track1_freshness as fresh  # noqa: E402
from global_index import update_spy_csv as spy  # noqa: E402


def _csv(tmp_path, last="2026-08-25", name="spy.csv") -> Path:
    """A daily series ending on `last`. Real shape, not a stub: the reader under test parses it."""
    days = pd.bdate_range(end=pd.Timestamp(last), periods=40)
    p = tmp_path / name
    pd.DataFrame({"date": [d.date().isoformat() for d in days],
                  "close": [700.0 + i for i in range(len(days))]}).to_csv(p, index=False)
    return p


# ═══════════════════════════════════════════════════════════════════════════════
# 1-4  coverage is its own answer, with its own states
# ═══════════════════════════════════════════════════════════════════════════════

def test_1_a_series_that_covers_the_required_day_passes(tmp_path):
    c = spy.coverage_status(_csv(tmp_path, "2026-08-26"), "2026-08-26")
    assert c["state"] == spy.COVERAGE_OK
    assert c["last"] == "2026-08-26" and c["required"] == "2026-08-26"


def test_2_a_series_one_day_short_is_named_short_and_not_ok(tmp_path):
    c = spy.coverage_status(_csv(tmp_path, "2026-08-25"), "2026-08-26")
    assert c["state"] == spy.COVERAGE_SHORT
    assert c["last"] == "2026-08-25" and c["required"] == "2026-08-26"
    # the words have to say which day, because "freshness_allow=false" does not
    assert "2026-08-26" in c["detail"] and "2026-08-25" in c["detail"]


def test_3_an_unreadable_series_is_unknown_and_never_ok(tmp_path):
    """Fails closed. "I could not tell" and "it is short" lead to different actions."""
    missing = spy.coverage_status(tmp_path / "does_not_exist.csv", "2026-08-26")
    assert missing["state"] == spy.COVERAGE_UNREADABLE
    assert missing["state"] != spy.COVERAGE_OK

    junk = tmp_path / "junk.csv"
    junk.write_text("this is not a csv with a date column\n", encoding="utf-8")
    assert spy.coverage_status(junk, "2026-08-26")["state"] == spy.COVERAGE_UNREADABLE


def test_4_the_three_states_are_distinct_values(tmp_path):
    """They are read by other code and compared; two of them being equal would be silent."""
    states = {spy.COVERAGE_OK, spy.COVERAGE_SHORT, spy.COVERAGE_UNREADABLE,
              spy.COVERAGE_NOT_ASKED}
    assert len(states) == 4, states


# ═══════════════════════════════════════════════════════════════════════════════
# 5-8  what the command line does, with the provider replaced
# ═══════════════════════════════════════════════════════════════════════════════

def _run_main(monkeypatch, csv_path, *, appended, last_after, require=None, verify=None):
    """`main()` with the update replaced. No network, no production path."""
    from global_index import regime_verify as rv

    def _fake_update(path, api_key, snapshot_dir=None, verify_root=None):
        if last_after is not None:
            df = pd.read_csv(path)
            if str(df["date"].iloc[-1]) != last_after:
                df.loc[len(df)] = [last_after, 999.0]
                df.to_csv(path, index=False)
        v = verify or rv.VerifyResult(status=rv.PASS, code="ok", detail="none changed",
                                      checked_at="now", inputs={})
        return spy.UpdateOutcome(rows_added=appended, verify=v)

    monkeypatch.setattr(spy, "update_spy_csv", _fake_update)
    argv = ["--csv", str(csv_path), "--api-key", "x", "--verify-strict"]
    if require:
        argv += ["--require-through", require]
    return spy.main(argv)


def test_5_a_clean_run_that_lands_the_required_day_exits_zero(tmp_path, monkeypatch):
    c = _csv(tmp_path, "2026-08-25")
    assert _run_main(monkeypatch, c, appended=1, last_after="2026-08-26",
                     require="2026-08-26") == 0


def test_6_a_clean_run_that_leaves_the_series_short_does_NOT_exit_zero(tmp_path, monkeypatch):
    """The whole defect. Nothing failed, the labels verify, and the day is not there."""
    c = _csv(tmp_path, "2026-08-25")
    rc = _run_main(monkeypatch, c, appended=0, last_after=None, require="2026-08-26")
    assert rc == spy.EXIT_COVERAGE_SHORT
    assert rc != 0, "a clean run that supplied nothing reported success"


def test_7_no_new_row_is_not_silent_success(tmp_path, monkeypatch, capsys):
    """`appended == 0` used to print 'already up-to-date' and stop there."""
    c = _csv(tmp_path, "2026-08-25")
    rc = _run_main(monkeypatch, c, appended=0, last_after=None, require="2026-08-26")
    out = capsys.readouterr().out
    assert rc != 0
    assert spy.COVERAGE_SHORT in out
    assert "2026-08-26" in out


def test_8_coverage_and_drift_have_DIFFERENT_exit_codes(tmp_path, monkeypatch):
    """A data-supply gap and a moved history are different problems with different owners."""
    from global_index import regime_verify as rv

    drifted = rv.VerifyResult(status=rv.DRIFT, code="drift", detail="labels moved",
                              checked_at="now", inputs={})
    c = _csv(tmp_path, "2026-08-25")
    assert _run_main(monkeypatch, c, appended=1, last_after="2026-08-26",
                     require="2026-08-26", verify=drifted) == 1
    c2 = _csv(tmp_path, "2026-08-25", name="b.csv")
    assert _run_main(monkeypatch, c2, appended=0, last_after=None,
                     require="2026-08-26") == spy.EXIT_COVERAGE_SHORT
    assert spy.EXIT_COVERAGE_SHORT != 1


def test_9_an_unreadable_series_fails_closed_on_the_command_line(tmp_path, monkeypatch):
    from global_index import regime_verify as rv

    monkeypatch.setattr(spy, "update_spy_csv",
                        lambda *a, **k: spy.UpdateOutcome(
                            rows_added=0,
                            verify=rv.VerifyResult(status=rv.PASS, code="ok", detail="",
                                                   checked_at="now", inputs={})))
    rc = spy.main(["--csv", str(tmp_path / "nope.csv"), "--api-key", "x",
                   "--verify-strict", "--require-through", "2026-08-26"])
    assert rc == spy.EXIT_COVERAGE_SHORT


# ═══════════════════════════════════════════════════════════════════════════════
# 10-12  the freshness gate, which is the thing that actually refuses
# ═══════════════════════════════════════════════════════════════════════════════

def test_10_the_live_shortfall_reproduces_exactly(tmp_path):
    """Session 2026-08-27, series ending 2026-08-25: stale, and the required day is 2026-08-26."""
    c = _csv(tmp_path, "2026-08-25")
    v = fresh.evaluate(now_et=pd.Timestamp("2026-08-27 01:10"), regime_csv=str(c), parquets={})
    assert v.allow is False
    row = next(x for x in v.checks if x.name == "regime_csv")
    assert row.status != "ok"
    assert row.observed == "2026-08-25" and row.required == "2026-08-26"


def test_11_one_more_day_and_the_regime_csv_side_is_satisfied(tmp_path):
    c = _csv(tmp_path, "2026-08-26")
    v = fresh.evaluate(now_et=pd.Timestamp("2026-08-27 01:10"), regime_csv=str(c), parquets={})
    row = next(x for x in v.checks if x.name == "regime_csv")
    assert row.status == "ok", row.detail
    assert row.observed == "2026-08-26"


def test_12_the_required_day_is_the_previous_trading_day_not_today(tmp_path):
    """NKD on D asks for daily context through D-1. Preserved, and pinned."""
    need = fresh.required_daily_close_through(pd.Timestamp("2026-08-27 01:10"))
    assert need.date() == dt.date(2026, 8, 26)
    # and across a weekend it is the Friday, not the Sunday
    mon = fresh.required_daily_close_through(pd.Timestamp("2026-08-31 01:10"))
    assert mon.date().weekday() == 4, mon


# ═══════════════════════════════════════════════════════════════════════════════
# 13-14  the scheduler asks for the day, and only claims success when it arrives
# ═══════════════════════════════════════════════════════════════════════════════

def _refresh_body_source() -> str:
    """The post-close refresh's body, wherever it now lives.

    Stage 5ZZC turned the single 16:20 job into a three-rung ladder sharing one body, so the
    job function is a one-line delegator and the assertions below — which are about what the
    refresh DOES — found an empty shell. The property never belonged to the decorated function;
    it belongs to the code that builds the command. Widened to the shared body, and it now
    covers all three rungs at once rather than only the first.
    """
    import ast

    src = (REPO / "global_index/run_scheduler.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    bodies = [n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name in ("_spy_refresh",
                                                               "job_spy_refresh_pm")]
    assert bodies, "neither the shared refresh body nor the 16:20 job exists any more"
    return " ".join(ast.unparse(n) for n in bodies)


def test_13_the_post_close_job_asks_the_child_for_the_day_it_needs():
    flat = _refresh_body_source()
    assert "--require-through" in flat, \
        "the child is not asked for a day, so its exit code cannot carry the answer"
    assert "--verify-strict" in flat, "the drift check was dropped"


def test_14_the_success_line_is_still_guarded_by_a_coverage_read():
    """It was not always. The comment in the source records the day it printed 'now covers
    <today>' while the series still ended the day before."""
    flat = _refresh_body_source()
    assert "_spy_series_last_day" in flat
    plain = flat.replace("'", "").replace('"', "")
    assert "covered == today" in plain, \
        "the success line no longer depends on reading what the series actually covers"


# ═══════════════════════════════════════════════════════════════════════════════
# 15-17  status says it in words, and does not blame the window that passed
# ═══════════════════════════════════════════════════════════════════════════════

def test_15_status_names_the_missing_day_in_plain_words(tmp_path):
    import ops

    c = _csv(tmp_path, "2026-08-25")
    got = ops.spy_daily_coverage(str(c), now_et=pd.Timestamp("2026-08-27 01:10"))
    assert got["state"] == spy.COVERAGE_SHORT
    assert "SPY daily file is missing 2026-08-26" in got["line"]
    # and it must not be only the machine-readable form
    assert got["line"] != "freshness_allow=false"


def test_16_a_covered_series_says_so_and_nothing_alarming(tmp_path):
    import ops

    c = _csv(tmp_path, "2026-08-26")
    got = ops.spy_daily_coverage(str(c), now_et=pd.Timestamp("2026-08-27 01:10"))
    assert got["state"] == spy.COVERAGE_OK
    assert "missing" not in got["line"]


def test_17_stale_daily_context_is_not_an_operational_slot_failure(tmp_path):
    """The NKD window on 2026-08-27 observed all its slots and decided in every one. The daily
    file being short is a SEPARATE fact about tomorrow's inputs, and rendering it as the window
    having failed would send somebody to inspect a window that worked."""
    import ops

    c = _csv(tmp_path, "2026-08-25")
    got = ops.spy_daily_coverage(str(c), now_et=pd.Timestamp("2026-08-27 01:10"))
    low = got["line"].lower()
    for forbidden in ("slot failed", "window failed", "operational failed", "nkd failed"):
        assert forbidden not in low, got["line"]
    # it names the consequence for the sleeves that run before the pre-flight, which is the
    # actionable part, rather than accusing the window that already passed
    assert "refuse" in low and "13:45" in got["line"]


def test_18_the_coverage_reader_asks_the_gate_for_the_requirement(tmp_path):
    """Not a second copy of "which day is needed". A second copy drifts from the gate that
    actually refuses, and then status and the gate disagree about the same morning."""
    import inspect

    import ops

    src = inspect.getsource(ops.spy_daily_coverage)
    assert "required_daily_close_through" in src, \
        "status restates the requirement instead of asking the module that enforces it"


# ═══════════════════════════════════════════════════════════════════════════════
# 19-21  the phased Calm slots must not decide on stale inputs
# ═══════════════════════════════════════════════════════════════════════════════

def test_19_a_phased_slot_evaluates_freshness_at_all():
    """Stage 5ZX bundled freshness in with the ADMISSION machinery and skipped both for a
    phased slot, on the reasoning that the decide half takes no position. That reasoning does
    not reach freshness: it asks whether the INPUTS are current, which is as live for a half
    that records an intent as for one that books a trade. Measured on 2026-08-27, the phased
    slots returned `freshness_allow=None` while the daily regime file was two sessions stale.
    """
    import ast

    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "observe_live_slot")
    body = ast.unparse(fn)
    i_fresh = body.find("fresh.evaluate")
    i_phase = body.find("_PhaseHalfComplete()")
    assert i_fresh != -1 and i_phase != -1
    assert i_fresh < i_phase,         "the phased half exits before freshness is evaluated, so its inputs are never checked"


def test_20_stale_inputs_make_a_phased_slot_refuse_rather_than_record(monkeypatch, tmp_path):
    """The refusal IS the record. A day whose inputs were stale must leave evidence that they
    were, not an intent that looks exactly like a good one."""
    from global_index import run_live_day_track1 as rl
    from global_index import track1_shadow_intent as si

    class _Refused:
        allow = False
        checks = [type("C", (), {"name": "regime_csv", "status": "stale"})()]

    monkeypatch.setattr(rl.fresh, "evaluate", lambda **kw: _Refused())
    day = "2026-08-21"
    rl._write_shadow_intent(phase="DECIDE", slot_id="TRACK1_CALM_DECIDE_0932",
                            day=pd.Timestamp(day), root=str(tmp_path), decided=False,
                            reason=rl.FRESHNESS_REFUSED, pre_entry=[], joined=None,
                            now_et=pd.Timestamp(f"{day} 09:32"))
    rows = si.read_day(str(tmp_path), day)
    assert rows, "nothing was recorded — this test would pass on silence"
    assert rows[0]["status"] == si.REFUSED
    assert rows[0]["reason_code"] == rl.FRESHNESS_REFUSED
    assert rows[0]["reason_code"] != si.OK


def test_21_a_stale_day_does_not_count_toward_the_evidence_gate(tmp_path):
    """The point of refusing rather than recording: a counter must not reach five clean days
    through days whose inputs nobody would have traded on."""
    from global_index import run_live_day_track1 as rl
    from global_index import track1_paper_readiness as pr
    from global_index import track1_shadow_intent as si

    day = "2026-08-21"
    si.append(si.decide_row("D", day, status=si.REFUSED,
                            reason_code=rl.FRESHNESS_REFUSED), root=tmp_path, day=day)
    assert si.classify_day(si.read_day(str(tmp_path), day))["label"] != si.DECISION_JUDGEABLE
    assert pr.calm_decision_evidence(tmp_path, [day])[day] not in pr._CALM_COUNTS


# ═══════════════════════════════════════════════════════════════════════════════
# mutations
# ═══════════════════════════════════════════════════════════════════════════════

def _must_fail(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except AssertionError:
        return True
    return False


def test_M1_coverage_short_treated_as_success_mutation(tmp_path, monkeypatch):
    """Collapse: a clean run that supplied nothing exits 0 again."""
    monkeypatch.setattr(spy, "coverage_status",
                        lambda p, r: {"state": spy.COVERAGE_OK, "last": None,
                                      "required": str(r), "detail": "mutated"})
    assert _must_fail(test_6_a_clean_run_that_leaves_the_series_short_does_NOT_exit_zero,
                      tmp_path, monkeypatch), \
        "test_6 stayed green while a short series exited zero"


def test_M2_unreadable_read_as_covered_mutation(tmp_path):
    """Collapse: an unreadable series reported as covered."""
    real = spy.coverage_status
    try:
        spy.coverage_status = lambda p, r: {"state": spy.COVERAGE_OK, "last": None,
                                            "required": str(r), "detail": "mutated"}
        assert _must_fail(test_3_an_unreadable_series_is_unknown_and_never_ok, tmp_path), \
            "test_3 stayed green while an unreadable series was called covered"
    finally:
        spy.coverage_status = real


def test_M3_requirement_moved_to_today_mutation(tmp_path):
    """Collapse: the gate starts asking for the SAME day rather than the previous one, which
    would make every overnight sleeve depend on a close that has not happened."""
    real = fresh.required_daily_close_through
    try:
        fresh.required_daily_close_through = lambda now: pd.Timestamp(now).normalize()
        assert _must_fail(test_12_the_required_day_is_the_previous_trading_day_not_today,
                          tmp_path), \
            "test_12 stayed green while the requirement moved to the session's own day"
    finally:
        fresh.required_daily_close_through = real


def test_M4_status_reverts_to_the_machine_readable_form_mutation(tmp_path):
    """Collapse: status says only `freshness_allow=false` again."""
    import ops

    real = ops.spy_daily_coverage
    try:
        ops.spy_daily_coverage = lambda csv="x", now_et=None: {
            "state": spy.COVERAGE_SHORT, "last": None, "required": None,
            "line": "freshness_allow=false"}
        assert _must_fail(test_15_status_names_the_missing_day_in_plain_words, tmp_path), \
            "test_15 stayed green while status went back to a machine-readable flag"
    finally:
        ops.spy_daily_coverage = real


def test_M5_scheduler_stops_asking_for_the_day_mutation(monkeypatch):
    """Collapse: `--require-through` dropped from the child's argv."""
    import ast
    import builtins

    real_read = Path.read_text

    def _stripped(self, *a, **k):
        txt = real_read(self, *a, **k)
        if self.name == "run_scheduler.py":
            return txt.replace('"--require-through", today', '"--verify-strict"')
        return txt

    monkeypatch.setattr(Path, "read_text", _stripped)
    assert builtins is not None
    assert _must_fail(test_13_the_post_close_job_asks_the_child_for_the_day_it_needs), \
        "test_13 stayed green while the child stopped being asked for a day"
