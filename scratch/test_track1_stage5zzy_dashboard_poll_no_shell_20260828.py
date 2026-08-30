"""Stage 5ZZY — a polled endpoint must not open a console.

Stage 5ZZW made the backend ask the SCHEDULER which mode it is in rather than trusting its own
environment. That was right, and it reached for `monitor.ops.track1_status()` to do it — which
runs `powershell.exe`. Measured: one call spawns two PowerShell processes and costs 2.84s. On a
page polling every eight seconds that is a window flashing on the desktop several times a minute,
and Stage 5ZZX's log filters could never have hidden it, because the noise was not in the log.

The backend already had the answer. `_scan_scheduler_processes()` enumerates with psutil, keeps
each scheduler's command line, and is cached behind a 60-second TTL with a background refresh —
its own docstring says "never call this on a request path", which is exactly the discipline the
ops reader does not have.

So the mode now comes from that cached scan. These tests hold the two halves that matter: the hot
path never reaches `ops`, and the safety semantics are unchanged.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from monitor.backend import open_issue_reader as oi          # noqa: E402
from monitor.backend import job_journal_reader as jj         # noqa: E402
from monitor.backend import schedule_status as ss            # noqa: E402


def _rows(command):
    return [{"pid": 4242, "started_epoch": 0.0, "command": command}]


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. the hot path does not reach ops, and does not shell out
# ══════════════════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def ops_is_a_landmine(monkeypatch):
    """Any call into the ops reader from a request path is a failure, so make it one."""
    import monitor.ops as ops

    def boom(*a, **k):
        raise AssertionError("a polled path called monitor.ops — it shells out to PowerShell")

    for name in ("track1_status", "scheduler_processes", "scheduler_scan", "_run"):
        if hasattr(ops, name):
            monkeypatch.setattr(ops, name, boom)
    return ops


def test_resolve_track1_only_never_calls_ops(ops_is_a_landmine, monkeypatch):
    monkeypatch.delenv("RAITS_TRACK1_ONLY", raising=False)
    monkeypatch.setattr(ss, "_running_schedulers",
                        lambda: _rows("python run_scheduler.py --track1-only-shadow"))
    for _ in range(5):
        assert ss.resolve_track1_only() is True


def test_the_mode_helper_never_calls_ops(ops_is_a_landmine, monkeypatch):
    monkeypatch.setattr(ss, "_running_schedulers",
                        lambda: _rows("python run_scheduler.py --track1-only-shadow"))
    for _ in range(5):
        out = ss.scheduler_track1_mode_status()
        assert out["track1_mode"] == "track1-only-shadow"


def test_legacy_retirement_never_calls_ops(ops_is_a_landmine, monkeypatch, tmp_path):
    (tmp_path / "track1_go_live_confirmation.json").write_text(json.dumps({
        "schema_version": 1, "confirmed_by": "op", "confirmed_at": "2026-08-27",
        "legacy_retired_confirmed": True, "note": "fixture"}), encoding="utf-8")
    monkeypatch.setattr(ss, "_running_schedulers",
                        lambda: _rows("python run_scheduler.py --track1-only-shadow"))
    state = oi.legacy_retirement_state(tmp_path)
    assert state["retired"] is True, state


def test_no_polled_endpoint_spawns_a_subprocess(monkeypatch):
    """The measurement the stage exists for, made against the real app.

    `subprocess.run` is replaced with something that records and refuses. A self-check runs
    first, because a spy that sees nothing because it was never installed reports a clean bill
    of health for a process shelling out constantly.
    """
    from monitor.backend.app import app

    seen = []
    real = subprocess.run

    def spy(*a, **k):
        seen.append(str(a[0] if a else k.get("args"))[:80])
        return real(*a, **k)

    monkeypatch.setattr(subprocess, "run", spy)
    subprocess.run([sys.executable, "-c", "pass"], capture_output=True)
    assert len(seen) == 1, "the spy is not installed — this test would pass on anything"
    seen.clear()

    client = app.test_client()
    client.get("/api/v1/schedule-status")        # warm the psutil cache once
    seen.clear()
    for _ in range(3):
        for endpoint in ("/api/v1/schedule-status", "/api/v1/open-issues",
                         "/api/v1/runner-state", "/api/v1/track1-runtime"):
            assert client.get(endpoint).status_code == 200
    assert seen == [], seen


def test_the_backend_never_imports_ops_at_module_level():
    """A lazy import inside a function is a seam a test can patch and a reader can find. At
    module level it is a dependency the whole backend carries whether or not it is used."""
    for name in ("schedule_status.py", "open_issue_reader.py"):
        src = (REPO / "monitor" / "backend" / name).read_text(encoding="utf-8")
        for line in src.splitlines():
            if line.startswith(("import ", "from ")) and "monitor.ops" in line:
                pytest.fail(f"{name} imports ops at module level: {line}")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. the semantics the shell-out used to provide
# ══════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("command,mode,only,jobs", [
    ("python run_scheduler.py --track1-only-shadow", "track1-only-shadow", True, 0),
    ("python run_scheduler.py --track1-shadow", "track1-shadow", False, None),
    ("python run_scheduler.py", "legacy-only", False, None),
])
def test_the_command_line_decides_the_mode(command, mode, only, jobs):
    out = ss.scheduler_track1_mode_status(_rows(command))
    assert out["track1_mode"] == mode
    assert out["scheduler_track1_only"] is only
    assert out["track1_mode_source"] == "process_table"
    if jobs == 0:
        assert out["legacy_entry_jobs"] == 0
    else:
        assert out["legacy_entry_jobs"] > 0, (
            "a mode that still registers legacy entries must not report zero of them")


def test_transitional_shadow_is_not_retirement_compatible():
    """`--track1-shadow` adds Track 1's slots and leaves the legacy entry slots running, so it
    is not the mode the B1 decision describes. It shares a prefix with the safe mode, which is
    exactly why this is asserted rather than assumed."""
    out = ss.scheduler_track1_mode_status(_rows("python run_scheduler.py --track1-shadow"))
    assert out["scheduler_track1_only"] is False
    assert out["legacy_entry_jobs"] != 0


def test_an_unreadable_command_line_is_unknown_not_legacy(monkeypatch):
    out = ss.scheduler_track1_mode_status([{"pid": 1, "command": ""}])
    assert out["track1_mode_source"] == "unknown"
    assert out["scheduler_track1_only"] is None
    monkeypatch.setattr(ss, "_running_schedulers", lambda: [{"pid": 1, "command": ""}])
    monkeypatch.delenv("RAITS_TRACK1_ONLY", raising=False)
    assert ss.resolve_track1_only() is None


def test_no_scheduler_at_all_is_unknown_not_legacy(monkeypatch):
    out = ss.scheduler_track1_mode_status([])
    assert out["scheduler_running"] is False
    assert out["scheduler_track1_only"] is None
    monkeypatch.setattr(ss, "_running_schedulers", lambda: [])
    monkeypatch.delenv("RAITS_TRACK1_ONLY", raising=False)
    assert ss.resolve_track1_only() is None


def test_an_explicit_setting_still_wins(monkeypatch):
    monkeypatch.setattr(ss, "_running_schedulers",
                        lambda: _rows("python run_scheduler.py --track1-only-shadow"))
    monkeypatch.setenv("RAITS_TRACK1_ONLY", "0")
    assert ss.resolve_track1_only() is False


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. retirement still needs all three facts, and fails toward showing too much
# ══════════════════════════════════════════════════════════════════════════════════════════

def _conf(root, signed=True):
    (root / "track1_go_live_confirmation.json").write_text(json.dumps({
        "schema_version": 1, "confirmed_by": "op", "confirmed_at": "2026-08-27",
        "legacy_retired_confirmed": signed, "note": "fixture"}), encoding="utf-8")
    return root


@pytest.mark.parametrize("command,expected", [
    ("python run_scheduler.py --track1-only-shadow", True),
    ("python run_scheduler.py --track1-shadow", False),
    ("python run_scheduler.py", False),
])
def test_retirement_follows_the_running_mode(monkeypatch, tmp_path, command, expected):
    _conf(tmp_path)
    monkeypatch.setattr(ss, "_running_schedulers", lambda: _rows(command))
    assert oi.legacy_retirement_state(tmp_path)["retired"] is expected


def test_no_confirmation_means_not_retired(monkeypatch, tmp_path):
    monkeypatch.setattr(ss, "_running_schedulers",
                        lambda: _rows("python run_scheduler.py --track1-only-shadow"))
    assert oi.legacy_retirement_state(tmp_path)["retired"] is False


def test_an_unreadable_scheduler_means_not_retired(monkeypatch, tmp_path):
    _conf(tmp_path)
    monkeypatch.setattr(ss, "_running_schedulers", lambda: [])
    assert oi.legacy_retirement_state(tmp_path)["retired"] is False


def test_the_confirmation_is_read_from_the_root_it_was_given(monkeypatch, tmp_path):
    """A test handing in a tmp_path must not be answered from the production file — that is how
    a suite comes to pass because of the machine it runs on."""
    monkeypatch.setattr(ss, "_running_schedulers",
                        lambda: _rows("python run_scheduler.py --track1-only-shadow"))
    assert oi.legacy_retirement_state(tmp_path)["retired"] is False
    _conf(tmp_path)
    assert oi.legacy_retirement_state(tmp_path)["retired"] is True


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. Calm — the slot ids, and who may recover whom
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_calm_slot_ids_are_the_two_phases():
    from global_index import track1_slots as t1
    calm = sorted(s.id.upper() for s in t1.TRACK1_SLOTS if s.sleeve == "roska4_calm")
    assert calm == ["TRACK1_CALM_DECIDE_0932", "TRACK1_CALM_OBSERVE_1002"], calm


def test_the_old_single_calm_slot_is_not_scheduled_anywhere(monkeypatch):
    import datetime as dt
    from global_index import track1_slots as t1
    assert "TRACK1_CALM_1000" not in {s.id.upper() for s in t1.TRACK1_SLOTS}
    monkeypatch.setenv("RAITS_TRACK1_ONLY", "1")
    mirrored = {s["id"].upper() for s in ss._scheduled_slots_for(dt.date(2026, 8, 28))}
    assert "TRACK1_CALM_1000" not in mirrored
    assert {"TRACK1_CALM_DECIDE_0932", "TRACK1_CALM_OBSERVE_1002"} <= mirrored


def _job(job_id, status, started):
    return {"job_id": job_id, "job_type": jj._job_type(job_id), "status": status,
            "started_at": started, "ended_at": started, "diagnostics": [],
            "impact": None, "action": None, "reason": None}


def _recovered(first, second):
    jobs = [_job(first[0], first[1], "2026-08-28T13:32:00Z"),
            _job(second, "completed", "2026-08-28T14:35:00Z")]
    jj._annotate_impact_and_action(jobs)
    return jobs[0]["lifecycle_status"] == "recovered"


def test_a_failed_calm_phase_is_not_recovered_by_a_stress_run():
    """Measured before the fix: a completed TRACK1_STRESS_1035 marked a failed
    TRACK1_CALM_DECIDE_0932 as recovered an hour later. Different sleeves are different
    processes against different instruments."""
    assert not _recovered(("TRACK1_CALM_DECIDE_0932", "failed"), "TRACK1_STRESS_1035")


def test_a_failed_nkd_run_is_not_recovered_by_a_swing_run():
    assert not _recovered(("TRACK1_NKD_0110", "failed"), "TRACK1_SWING_1405")


def test_both_calm_phases_share_one_stream():
    """DECIDE at 09:32 and OBSERVE at 10:02 are two phases of one sleeve's day, so the later
    one covering the earlier IS a recovery. The complement of the test above: separating the
    sleeves must not separate a sleeve from itself."""
    assert _recovered(("TRACK1_CALM_DECIDE_0932", "failed"), "TRACK1_CALM_OBSERVE_1002")
    assert (jj.recovery_stream(_job("TRACK1_CALM_DECIDE_0932", "failed", "x"))
            == jj.recovery_stream(_job("TRACK1_CALM_OBSERVE_1002", "completed", "x")))


def test_a_sleeve_still_recovers_itself():
    assert _recovered(("TRACK1_SWING_1405", "failed"), "TRACK1_SWING_1410")


def test_the_issue_lane_agrees_with_the_journal_lane():
    """Two lanes that disagree about who may close whom is how this project got a stop-repair
    sweep closing a failed data refresh."""
    calm = _job("TRACK1_CALM_DECIDE_0932", "failed", "x")
    stress = _job("TRACK1_STRESS_1035", "completed", "x")
    observe = _job("TRACK1_CALM_OBSERVE_1002", "completed", "x")
    assert oi._stream(calm) != oi._stream(stress)
    assert oi._stream(calm) == oi._stream(observe)


def test_strategy_slots_are_still_typed_as_strategy_slots():
    """The finer stream is for RECOVERY only. Everything that asks "is this a strategy slot" —
    the chip, the scheduler-owned list, the panel — must still get the same answer."""
    for jid in ("TRACK1_CALM_DECIDE_0932", "TRACK1_STRESS_1035", "TRACK1_SWING_1405"):
        assert jj._job_type(jid) == jj.TRACK1_STRATEGY_SLOT
        assert jj.is_track1_strategy_job(jid) is True


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. gates
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_orders_remain_impossible():
    from global_index import track1_gates as G
    allowed, reasons = G.may_enable_orders()
    assert allowed is False
    assert "PAPER_SHADOW_EVIDENCE" in [r.split(":")[0] for r in reasons]


def test_this_stage_created_no_order_artefacts():
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not (REPO / "global_index" / "live_positions.track1.json").exists()
