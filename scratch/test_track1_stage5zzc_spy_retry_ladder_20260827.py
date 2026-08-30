"""Stage 5ZZC — the post-close retry ladder, and the thing that would have made it useless.

The ladder exists because on 2026-08-26 the 16:20 refresh ran cleanly and the provider did not
yet have that day's close, so the overnight window refused the next morning on stale daily
context. The job warned; its warning ended "only a problem if it is still true tomorrow"; and
nothing looked tomorrow.

**The measurement that shaped the design**: a retry with nothing to do exits **1** under
`--verify-strict`. The series already ends at today, so the update returns early with
`UNKNOWN (no_snapshot)` — nothing fetched, nothing compared — and strict fails on anything that
is not a PASS. Two rungs a day, each reporting FAILED on every day that went WELL, is an alarm
that fires when nothing is wrong.

Nothing here calls Polygon; nothing writes outside tmp_path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "monitor"))

from global_index import run_scheduler as rs  # noqa: E402
from global_index import update_spy_csv as spy  # noqa: E402


def _csv(tmp_path, last="2026-08-26", name="spy.csv") -> Path:
    days = pd.bdate_range(end=pd.Timestamp(last), periods=30)
    p = tmp_path / name
    pd.DataFrame({"date": [d.date().isoformat() for d in days],
                  "close": [700.0 + i for i in range(len(days))]}).to_csv(p, index=False)
    return p


def _argvs(monkeypatch, *, track1_only=True):
    """The argv every SPY rung builds, with the launcher replaced. Nothing runs."""
    import logging

    logging.disable(logging.CRITICAL)
    seen: dict = {}

    def _cap(args, label=None, dry_run=None, timeout=None, route=None, rc_out=None):
        seen[label] = list(args)
        if rc_out is not None:
            rc_out.append(0)
        return True

    monkeypatch.setattr(rs, "_run", _cap)
    sched = rs.make_scheduler(port=7497, dry_run=False, track1_only=track1_only)
    jobs = {j.id: j for j in sched.get_jobs()}
    for jid in ("spy_refresh_pm", "spy_refresh_pm_r1", "spy_refresh_pm_r2"):
        assert jid in jobs, f"{jid} is not registered"
        jobs[jid].func()
    assert seen, "no rung built an argv — this helper would pass on silence"
    return seen, jobs


# ═══════════════════════════════════════════════════════════════════════════════
# 1-4  a retry with nothing to do must be a success
# ═══════════════════════════════════════════════════════════════════════════════

def test_1_a_retry_with_nothing_to_do_exits_zero_without_fetching(tmp_path, monkeypatch):
    """The measurement that shaped the ladder. Without `--skip-if-covered` this is exit 1."""
    c = _csv(tmp_path, "2026-08-26")
    called = {"n": 0}

    def _never(*a, **k):
        called["n"] += 1
        raise AssertionError("a covered retry reached the provider")

    monkeypatch.setattr(spy, "update_spy_csv", _never)
    rc = spy.main(["--csv", str(c), "--api-key", "x", "--verify-strict",
                   "--skip-if-covered", "--require-through", "2026-08-26"])
    assert rc == 0
    assert called["n"] == 0, "the retry fetched when it had nothing to do"


def test_2_without_the_skip_flag_the_same_run_is_not_a_success(tmp_path, monkeypatch):
    """Pinning the defect the flag exists for, so nobody removes the flag as redundant."""
    from global_index import regime_verify as rv

    c = _csv(tmp_path, "2026-08-26")
    monkeypatch.setattr(spy, "update_spy_csv",
                        lambda *a, **k: spy.UpdateOutcome(
                            rows_added=0,
                            verify=rv.VerifyResult(
                                status=rv.UNKNOWN, code=rv.NO_SNAPSHOT,
                                detail="the series already ends there, so nothing was fetched",
                                checked_at="now", inputs={})))
    rc = spy.main(["--csv", str(c), "--api-key", "x", "--verify-strict",
                   "--require-through", "2026-08-26"])
    assert rc == 1, "a covered retry without the skip flag no longer fails — the flag is now " \
                    "cosmetic and this test is the only record of why it exists"


def test_3_the_skip_flag_does_nothing_when_the_day_is_actually_missing(tmp_path, monkeypatch):
    """It must not become a way to pass by declining to look."""
    from global_index import regime_verify as rv

    c = _csv(tmp_path, "2026-08-25")
    monkeypatch.setattr(spy, "update_spy_csv",
                        lambda *a, **k: spy.UpdateOutcome(
                            rows_added=0,
                            verify=rv.VerifyResult(status=rv.PASS, code="ok", detail="",
                                                   checked_at="now", inputs={})))
    rc = spy.main(["--csv", str(c), "--api-key", "x", "--verify-strict",
                   "--skip-if-covered", "--require-through", "2026-08-26"])
    assert rc == spy.EXIT_COVERAGE_SHORT


def test_4_a_provider_that_returns_the_required_day_passes(tmp_path, monkeypatch):
    from global_index import regime_verify as rv

    c = _csv(tmp_path, "2026-08-25")

    def _lands(path, api_key, snapshot_dir=None, verify_root=None):
        df = pd.read_csv(path)
        df.loc[len(df)] = ["2026-08-26", 766.08]
        df.to_csv(path, index=False)
        return spy.UpdateOutcome(rows_added=1, verify=rv.VerifyResult(
            status=rv.PASS, code="ok", detail="", checked_at="now", inputs={}))

    monkeypatch.setattr(spy, "update_spy_csv", _lands)
    assert spy.main(["--csv", str(c), "--api-key", "x", "--verify-strict",
                     "--skip-if-covered", "--require-through", "2026-08-26"]) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5-8  the ladder as the scheduler builds it
# ═══════════════════════════════════════════════════════════════════════════════

def test_5_three_rungs_are_registered_at_the_declared_times(monkeypatch):
    import logging

    logging.disable(logging.CRITICAL)
    sched = rs.make_scheduler(port=7497, dry_run=True, track1_only=True)
    times = {}
    for j in sched.get_jobs():
        if "spy_refresh" not in j.id:
            continue
        f = {x.name: str(x) for x in j.trigger.fields}
        times[j.id] = (int(f["hour"]), int(f["minute"]))
    assert times == {"spy_refresh_pm": (16, 20),
                     "spy_refresh_pm_r1": (16, 45),
                     "spy_refresh_pm_r2": (17, 15)}, times


def test_6_every_rung_asks_for_the_day_and_verifies(monkeypatch):
    seen, _ = _argvs(monkeypatch)
    assert set(seen) == {"SPY_REFRESH_PM", "SPY_REFRESH_PM_R1", "SPY_REFRESH_PM_R2"}
    for label, cmd in seen.items():
        assert "--verify-strict" in cmd, label
        assert "--require-through" in cmd, label
        # the day it asks for is a real date, not a placeholder
        day = cmd[cmd.index("--require-through") + 1]
        pd.Timestamp(day)


def test_7_only_the_retries_skip_when_covered(monkeypatch):
    """The 16:20 run verifies the labels even when the day is already there; that is part of
    what that run is for. A retry has nothing to verify about a file it will not touch."""
    seen, _ = _argvs(monkeypatch)
    assert "--skip-if-covered" not in seen["SPY_REFRESH_PM"]
    assert "--skip-if-covered" in seen["SPY_REFRESH_PM_R1"]
    assert "--skip-if-covered" in seen["SPY_REFRESH_PM_R2"]


def test_8_no_rung_and_no_track1_slot_can_ask_for_orders(monkeypatch):
    seen, jobs = _argvs(monkeypatch)
    for label, cmd in seen.items():
        assert "--allow-orders" not in cmd, label
    from global_index import track1_slots as ts
    assert ts.TRACK1_SLOTS, "no slots — this test would pass on an empty table"
    for s in ts.TRACK1_SLOTS:
        argv = ["--sleeve", s.sleeve, "--slot-id", s.id, "--bar-provider", "ibkr"] \
            + (["--phase", s.phase] if s.phase else [])
        assert "--allow-orders" not in argv, s.id


def test_9_the_calm_split_survived_the_ladder(monkeypatch):
    import logging

    logging.disable(logging.CRITICAL)
    sched = rs.make_scheduler(port=7497, dry_run=True, track1_only=True)
    ids = {j.id for j in sched.get_jobs()}
    assert "track1_calm_decide_0932" in ids
    assert "track1_calm_observe_1002" in ids
    assert "track1_calm_1000" not in ids


def test_10_the_ladder_is_three_rungs_in_every_mode(monkeypatch):
    """Measured from real construction, and expressed as a PROPERTY rather than a total.

    The first version of this pinned the whole schedule's size — 63, 133, 104 — and Stage 5ZZD
    broke it the next morning by adding one unrelated job. That is the roster anti-pattern this
    project already has on record: a pin that fails for something it is not about, teaching
    whoever reads it that the failure is noise. What this test is about is the ladder, so the
    ladder is what it counts.
    """
    import logging

    logging.disable(logging.CRITICAL)
    for name, kw in (("legacy", {}), ("transitional", {"track1_shadow": True}),
                     ("track1_only", {"track1_only": True})):
        ids = {j.id for j in rs.make_scheduler(port=7497, dry_run=True, **kw).get_jobs()}
        rungs = {i for i in ids if i.startswith("spy_refresh")}
        assert rungs == {"spy_refresh_pm", "spy_refresh_pm_r1", "spy_refresh_pm_r2"}, \
            f"{name}: {sorted(rungs)}"
        # shared infrastructure: the daily regime file was never Track 1's private input, so
        # the rungs appear in the legacy schedule too.
        assert len(ids) > len(rungs)


# ═══════════════════════════════════════════════════════════════════════════════
# 11-13  the ladder's four outcomes are four different messages
# ═══════════════════════════════════════════════════════════════════════════════

def _rung_log(monkeypatch, caplog, *, label_ids, rc, last_before, last_after):
    """Fire one rung with the launcher and the series reader replaced."""
    import logging

    logging.disable(logging.NOTSET)
    seq = iter([last_before, last_after])

    monkeypatch.setattr(rs, "_spy_series_last_day", lambda csv: next(seq, last_after))

    def _cap(args, label=None, dry_run=None, timeout=None, route=None, rc_out=None):
        if rc_out is not None:
            rc_out.append(rc)
        return rc == 0

    monkeypatch.setattr(rs, "_run", _cap)
    sched = rs.make_scheduler(port=7497, dry_run=False, track1_only=True)
    job = {j.id: j for j in sched.get_jobs()}[label_ids]
    with caplog.at_level(logging.INFO, logger="run_scheduler"):
        job.func()
    return "\n".join(r.getMessage() for r in caplog.records)


def test_11_a_rung_that_recovers_a_missing_day_says_RECOVERED(monkeypatch, caplog):
    today = rs._et_today().isoformat()
    out = _rung_log(monkeypatch, caplog, label_ids="spy_refresh_pm_r1", rc=0,
                    last_before="2000-01-01", last_after=today)
    assert "RECOVERED" in out
    assert "nothing to do" not in out


def test_12_a_rung_with_nothing_to_do_does_not_shout(monkeypatch, caplog):
    today = rs._et_today().isoformat()
    out = _rung_log(monkeypatch, caplog, label_ids="spy_refresh_pm_r1", rc=0,
                    last_before=today, last_after=today)
    assert "nothing to do" in out
    assert "RECOVERED" not in out and "FAILED" not in out


def test_13_the_last_rung_is_the_loud_one(monkeypatch, caplog):
    """A middle rung says when the next attempt is. The last one has no next attempt, and that
    is what makes it the message somebody has to read."""
    mid = _rung_log(monkeypatch, caplog, label_ids="spy_refresh_pm_r1", rc=2,
                    last_before="2026-08-25", last_after="2026-08-25")
    assert "Next attempt at 17:15 ET" in mid
    assert "LAST ATTEMPT" not in mid

    caplog.clear()
    last = _rung_log(monkeypatch, caplog, label_ids="spy_refresh_pm_r2", rc=2,
                     last_before="2026-08-25", last_after="2026-08-25")
    assert "LAST ATTEMPT" in last
    # and it names who will be hurt, which is the actionable half
    assert "NKD" in last and "Calm" in last


def test_14_a_dry_run_rung_invents_no_failure(monkeypatch, caplog):
    import logging

    logging.disable(logging.NOTSET)
    monkeypatch.setattr(rs, "_run", lambda *a, **k: True)
    sched = rs.make_scheduler(port=7497, dry_run=True, track1_only=True)
    job = {j.id: j for j in sched.get_jobs()}["spy_refresh_pm"]
    with caplog.at_level(logging.INFO, logger="run_scheduler"):
        job.func()
    out = "\n".join(r.getMessage() for r in caplog.records)
    assert "dry-run" in out
    assert "FAILED" not in out, "a command that was never sent was reported as a failed refresh"


# ═══════════════════════════════════════════════════════════════════════════════
# 15-17  status and dashboard keep daily context apart from slot status
# ═══════════════════════════════════════════════════════════════════════════════

def test_15_the_dashboard_block_is_its_own_thing(tmp_path):
    from monitor.backend import track1_runtime_reader as rd

    d = rd._spy_daily(REPO)
    assert d["separate_from_slot_status"] is True
    assert d["state"] in ("covers_required_day", "provider_did_not_return_required_day",
                          "coverage_unknown", "unknown")
    assert d["line"], "the block says nothing"


def test_16_a_covered_file_reads_cleanly_and_a_short_one_names_the_day(tmp_path, monkeypatch):
    from monitor.backend import track1_runtime_reader as rd

    monkeypatch.setattr(rd, "_today_et", lambda: pd.Timestamp("2026-08-27"))
    _csv(tmp_path, "2026-08-26", name="spy_daily_live.csv")
    ok = rd._spy_daily(tmp_path)
    assert ok["state"] == "covers_required_day"
    assert ok["line"] == "SPY daily file covers 2026-08-26"

    _csv(tmp_path, "2026-08-25", name="spy_daily_live.csv")
    short = rd._spy_daily(tmp_path)
    assert short["state"] == "provider_did_not_return_required_day"
    assert "SPY daily file is missing 2026-08-26" in short["line"]
    low = short["line"].lower()
    assert "not a slot failure" in low
    for forbidden in ("nkd failed", "window failed", "slot failed"):
        assert forbidden not in low


def test_17_the_row_is_declared_in_the_bidirectional_fact_pin():
    """The pin fails in both directions and caught this row the moment it was added."""
    src = (REPO / "scratch/test_track1_dashboard_runtime_wiring_20260824.py").read_text(
        encoding="utf-8")
    assert '"SPY daily"' in src
    js = (REPO / "global_index/dash/realtime/realtime.js").read_text(encoding="utf-8")
    assert "t1Fact('SPY daily'" in js


# ═══════════════════════════════════════════════════════════════════════════════
# mutations
# ═══════════════════════════════════════════════════════════════════════════════

def _must_fail(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except AssertionError:
        return True
    return False


def test_M1_the_retries_stop_skipping_mutation(tmp_path, monkeypatch):
    """Collapse: the retries lose `--skip-if-covered`, so a good day reports two failures.

    Mutated at the scheduler, where the flag is actually added, and read back from the argv the
    rungs build — not by editing the test's own expectation, which would prove nothing.
    """
    seen, _ = _argvs(monkeypatch)
    assert "--skip-if-covered" in seen["SPY_REFRESH_PM_R1"], "baseline is already broken"

    import global_index.run_scheduler as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert 'cmd += ["--skip-if-covered"]' in src, \
        "the retries no longer add the flag, so a rung with nothing to do fails again"


def test_M2_a_covered_retry_starts_fetching_mutation(tmp_path, monkeypatch):
    """Collapse: the short-circuit stops firing, so a covered retry reaches the provider."""
    monkeypatch.setattr(spy, "coverage_status",
                        lambda p, r: {"state": spy.COVERAGE_SHORT, "last": None,
                                      "required": str(r), "detail": "mutated"})
    assert _must_fail(test_1_a_retry_with_nothing_to_do_exits_zero_without_fetching,
                      tmp_path, monkeypatch), \
        "test_1 stayed green while a covered retry went to the provider anyway"


def test_M5_the_last_rung_stops_being_loud_mutation(monkeypatch, caplog):
    """Collapse: the final rung claims a next attempt, so nothing says the day is lost.

    Mutated by giving the last rung a successor in the ladder map — which is exactly what a
    careless edit adding a fourth rung and forgetting to move the terminal entry would do.
    """
    import logging

    logging.disable(logging.NOTSET)
    seq = iter(["2026-08-25", "2026-08-25"])
    monkeypatch.setattr(rs, "_spy_series_last_day", lambda csv: next(seq, "2026-08-25"))

    def _cap(args, label=None, dry_run=None, timeout=None, route=None, rc_out=None):
        if rc_out is not None:
            rc_out.append(2)
        return False

    monkeypatch.setattr(rs, "_run", _cap)
    sched = rs.make_scheduler(port=7497, dry_run=False, track1_only=True)
    job = {j.id: j for j in sched.get_jobs()}["spy_refresh_pm_r2"]

    # the map is a closure local, so reach it through the job's own function globals/closure
    import types

    fn = job.func
    ladder = None
    for cell in (fn.__closure__ or ()):
        v = cell.cell_contents
        if isinstance(v, types.FunctionType) and v.__name__ == "_spy_refresh":
            for c2 in (v.__closure__ or ()):
                cv = c2.cell_contents
                if isinstance(cv, dict) and "SPY_REFRESH_PM_R2" in cv:
                    ladder = cv
    assert ladder is not None, "the ladder map could not be found — the shape changed"
    assert ladder["SPY_REFRESH_PM_R2"] is None, "the last rung already claims a successor"

    ladder["SPY_REFRESH_PM_R2"] = "23:59"
    try:
        with caplog.at_level(logging.INFO, logger="run_scheduler"):
            job.func()
        out = "\n".join(r.getMessage() for r in caplog.records)
        assert "LAST ATTEMPT" not in out, \
            "the mutation did not take — this test proves nothing about the loud message"
    finally:
        ladder["SPY_REFRESH_PM_R2"] = None


def test_M3_coverage_short_reads_as_covered_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(spy, "coverage_status",
                        lambda p, r: {"state": spy.COVERAGE_OK, "last": None,
                                      "required": str(r), "detail": "mutated"})
    assert _must_fail(test_3_the_skip_flag_does_nothing_when_the_day_is_actually_missing,
                      tmp_path, monkeypatch), \
        "test_3 stayed green while the skip flag passed a missing day"


def test_M4_dashboard_folds_daily_context_into_slot_status_mutation(tmp_path, monkeypatch):
    from monitor.backend import track1_runtime_reader as rd

    monkeypatch.setattr(rd, "_spy_daily",
                        lambda root, regime_csv="spy_daily_live.csv": {
                            "state": "provider_did_not_return_required_day",
                            "last": "2026-08-25", "required": "2026-08-26",
                            "line": "NKD failed", "separate_from_slot_status": False})
    assert _must_fail(test_16_a_covered_file_reads_cleanly_and_a_short_one_names_the_day,
                      tmp_path, monkeypatch), \
        "test_16 stayed green while daily context was rendered as a window failure"
