"""Stage 5ZZN — the guard that pushed the operator into the unsafe mode.

The operator signed the B1 decision. `--track1-only-shadow` began REFUSING because of it — the
guard's rule was "the confirmation file exists" and its stated reason was *that file arms the
Track 1 route*. So the scheduler was restarted without any Track 1 flag, which registers 45
legacy entry jobs on the very login the signature had just declared retired.

The sentence behind the guard was true once. It stopped being true when Stage 5S added a
measured evidence gate and Stage 5ZZK gave B1 a measured half: the file no longer arms
anything by itself. The guard now asks the gate registry whether an order is actually
possible, and a second guard — the one that was missing — refuses a start that would register
legacy entry jobs against a signed decision.

Nothing here starts a process, stops one, or touches the production confirmation file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_index import track1_gates as gates                   # noqa: E402
from global_index import track1_slots as t1slots                 # noqa: E402
from monitor import ops                                          # noqa: E402

SIGNED = {"schema_version": 1, "confirmed_by": "kevindo290", "confirmed_at": "2026-08-27",
          "legacy_retired_confirmed": True, "note": "Legacy retired for this paper login."}


@pytest.fixture
def signed(tmp_path, monkeypatch):
    """A signed B1 decision, under tmp_path. The production file is never touched."""
    f = tmp_path / "track1_go_live_confirmation.json"
    f.write_text(json.dumps(SIGNED), encoding="utf-8")
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", f)
    monkeypatch.setattr(gates, "CONFIRMATION_PATH", str(f))
    return f


@pytest.fixture
def unsigned(tmp_path, monkeypatch):
    f = tmp_path / "track1_go_live_confirmation.json"
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", f)
    monkeypatch.setattr(gates, "CONFIRMATION_PATH", str(f))
    return f


def _blocked(monkeypatch, possible=False):
    """Pin what the gate registry says, so these tests do not depend on today's evidence."""
    monkeypatch.setattr(ops, "orders_would_be_possible",
                        lambda: (possible, [] if possible else ["PAPER_SHADOW_EVIDENCE: ..."]))


# ── item 1: nothing changes before a decision is signed ─────────────────────────────────
def test_without_a_confirmation_the_old_shadow_behaviour_is_unchanged(unsigned, monkeypatch):
    _blocked(monkeypatch)
    assert ops.track1_shadow_blockers(track1_only=True) == []
    assert ops.legacy_entry_start_blockers() == []


def test_without_a_confirmation_a_legacy_start_is_not_refused(unsigned):
    assert ops.legacy_entry_start_blockers() == []


def test_the_stop_switch_requirement_for_plain_shadow_still_stands(unsigned, monkeypatch):
    """`--track1-shadow` keeps all 45 legacy entry jobs, so it still needs the kill switch.
    Narrowing the confirmation clause must not have loosened this one."""
    _blocked(monkeypatch)
    monkeypatch.setattr(ops, "LEGACY_STOP_FILE", Path("no-such-stop-file"))
    blockers = ops.track1_shadow_blockers(track1_only=False)
    assert any("STOP_TRADING" in b or "stop" in b.lower() for b in blockers), blockers


# ── item 2: a legacy start is refused once the decision exists ──────────────────────────
def test_a_signed_decision_refuses_a_legacy_start(signed):
    blockers = ops.legacy_entry_start_blockers()
    assert blockers, "a legacy start was allowed against a signed retirement"
    joined = " ".join(blockers)
    assert "legacy_retired_confirmed" in joined
    assert str(ops.legacy_entry_job_count()) in joined
    assert "--track1-only-shadow" in joined, "the refusal must name the mode to use instead"


def test_the_refusal_names_all_four_things_the_operator_needs(signed):
    """Part C.2: the file exists, what B1 says, what the requested mode would do, and the
    mode to use instead."""
    joined = " ".join(ops.legacy_entry_start_blockers()).lower()
    for needed in ("confirmation", "retired for this paper login",
                   "legacy entry job", "--track1-only-shadow"):
        assert needed in joined, needed


def test_a_confirmation_that_does_not_validate_asserts_nothing(tmp_path, monkeypatch):
    """A file that grants nothing also claims nothing, so it must not block a legacy start."""
    f = tmp_path / "track1_go_live_confirmation.json"
    f.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", f)
    monkeypatch.setattr(gates, "CONFIRMATION_PATH", str(f))
    assert ops.legacy_entry_start_blockers() == []


def test_a_confirmation_without_the_legacy_flag_does_not_block_legacy(tmp_path, monkeypatch):
    f = tmp_path / "track1_go_live_confirmation.json"
    f.write_text(json.dumps({**SIGNED, "legacy_retired_confirmed": False,
                             "separate_account_confirmed": True}), encoding="utf-8")
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", f)
    monkeypatch.setattr(gates, "CONFIRMATION_PATH", str(f))
    assert ops.legacy_entry_start_blockers() == []


# ── item 3: the post-B1 mode is allowed, and is the right shape ─────────────────────────
def test_a_signed_decision_no_longer_blocks_track1_only_shadow(signed, monkeypatch):
    """The regression this whole stage is. It refused, and the refusal is what sent the
    scheduler into the mode that registers legacy entries."""
    _blocked(monkeypatch)
    assert ops.track1_shadow_blockers(track1_only=True) == []


def test_track1_only_shadow_registers_the_right_jobs():
    """Item 3, from the route table the scheduler's own removal step reads."""
    port = ops.DEFAULT_IBKR_PORT
    rc = t1slots.route_classification(port, track1_shadow=True)
    surviving = t1slots.surviving_jobs(port, track1_shadow=True)
    doomed = t1slots.legacy_retirement_candidates(port, track1_shadow=True)
    assert len(rc["track1"]) == 71, rc["track1"]
    assert len(doomed) == 45
    assert not (surviving & doomed), "a legacy entry job survived the retirement set"
    # The scheduler's JOB ids, not the slot-table ids: jobs are registered lowercase
    # (`track1_calm_decide_0932`) while the slot table names them `TRACK1_CALM_DECIDE_0932`.
    # Comparing the two namespaces is comparing different things.
    assert set(rc["track1"]) <= surviving, "a Track 1 job was removed"
    assert rc["safety"], "the safety sweeps must survive to drain the legacy book"


def test_the_two_guards_read_one_table():
    """`legacy_entry_job_count` must come from the same table the scheduler removes from, or
    the number in the refusal and the number actually registered drift apart."""
    assert ops.legacy_entry_job_count() == len(
        t1slots.legacy_retirement_candidates(ops.DEFAULT_IBKR_PORT, track1_shadow=True))


# ── item 4: orders stay impossible ──────────────────────────────────────────────────────
def test_a_signed_decision_with_evidence_still_blocking_keeps_orders_impossible(signed):
    possible, why = ops.orders_would_be_possible()
    assert possible is False
    assert any("PAPER_SHADOW_EVIDENCE" in w for w in why)


def test_shadow_is_refused_when_orders_would_actually_be_possible(signed, monkeypatch):
    """The half of the old guard that was RIGHT, kept. If every blocker is clear, a shadow
    start really is starting something nobody asked for."""
    _blocked(monkeypatch, possible=True)
    blockers = ops.track1_shadow_blockers(track1_only=True)
    assert blockers, "a shadow start was allowed while the route could send orders"
    assert "send orders" in " ".join(blockers)


def test_an_unreadable_gate_registry_fails_closed(signed, monkeypatch):
    """A guard built on a question it could not answer must refuse, not wave through."""
    import global_index.track1_gates as g
    monkeypatch.setattr(g, "may_enable_orders",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("registry down")))
    possible, why = ops.orders_would_be_possible()
    assert possible is True, "an unreadable registry must read as 'possible' so guards refuse"
    assert any("could not be read" in w for w in why)


# ── item 5 / 6: nothing arms anything ───────────────────────────────────────────────────
def test_no_allow_orders_in_any_ops_or_scheduler_path():
    def stripped(path: Path) -> str:
        return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines()
                         if not l.strip().startswith("#"))

    for rel in ("monitor/ops.py", "global_index/run_scheduler.py"):
        assert "--allow-orders" not in stripped(ROOT / rel), rel


def test_no_orders_directory_is_created():
    assert not (ROOT / "global_index" / "track1_runtime" / "orders").exists()


def test_nothing_in_this_stage_sets_the_approval_variable():
    import os
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")
    text = (ROOT / "monitor" / "ops.py").read_text(encoding="utf-8")
    # ops REMOVES it from the child environment; it must never set it.
    assert "environ[TRACK1_ORDERS_ENV] =" not in text
    assert 'env[TRACK1_ORDERS_ENV] = "1"' not in text


# ── item 7: the 5ZZJ alarm passes for the right reason ──────────────────────────────────
def test_the_5zzj_alarm_is_still_the_strict_assertion():
    """It must pass because the mode is compatible, never because the assertion was loosened.
    Pinned by reading the test itself."""
    f = ROOT / "scratch" / "test_track1_stage5zzj_b1_operator_decision_20260827.py"
    text = f.read_text(encoding="utf-8")
    assert "def test_the_running_mode_registers_no_legacy_entry_jobs" in text
    body = text.split("def test_the_running_mode_registers_no_legacy_entry_jobs", 1)[1]
    body = body.split("\ndef ", 1)[0]
    assert "capability != dec.LEGACY_ENTRY_PRESENT" in body, (
        "the alarm's assertion has been weakened")
    assert "skip" not in body.lower(), "the alarm has been turned into a skip"


# ── items 8 / 9: status says which it is ────────────────────────────────────────────────
def _mode(track1_only, mode_known=True, confirmation=True, tmp_path=None, monkeypatch=None):
    return ops._scheduler_mode_compatibility(track1_only, mode_known)


def test_status_reports_incompatible_when_legacy_entries_run_against_a_decision(signed):
    m = ops._scheduler_mode_compatibility(False, True)
    assert m["compatible"] is False
    assert m["legacy_entry_jobs"] == ops.legacy_entry_job_count()
    assert "retired for this login" in m["detail"]


def test_status_reports_compatible_in_the_post_b1_mode(signed):
    m = ops._scheduler_mode_compatibility(True, True)
    assert m["compatible"] is True
    assert "no legacy entry job" in m["detail"]


def test_status_reports_unknown_when_the_mode_cannot_be_read(signed):
    """Three answers, and this is the one that matters: a mode nobody could read is NOT a
    compatible mode, and printing it as one would be the fail-open this route keeps finding."""
    m = ops._scheduler_mode_compatibility(None, False)
    assert m["compatible"] is None
    assert "could not be read" in m["detail"]


def test_status_is_compatible_when_nothing_has_been_signed(unsigned):
    m = ops._scheduler_mode_compatibility(False, True)
    assert m["compatible"] is True
    assert "no B1 decision" in m["detail"]


def test_the_status_line_is_printed_and_names_the_fix():
    text = (ROOT / "monitor" / "ops.py").read_text(encoding="utf-8")
    assert "track1_scheduler_mode=" in text
    assert "MODE CONFLICT" in text
    assert "restart --scheduler --track1-only-shadow" in text


def test_a_registration_line_from_a_dead_process_is_not_called_fresh():
    """Measured on 2026-08-27: status printed `track1_slot_table=fresh registered_slots=71`
    while the running scheduler had been started with no Track 1 flag and had registered none.
    The number was true about a process that had already exited."""
    out = ops.slot_table_freshness({"last_registered_slots": 71,
                                    "last_registered_at_machine_local": "2026-08-27 05:08:33"})
    assert "logged_before_current_process" in out
    if out["logged_before_current_process"]:
        assert out["state"] == "stale_log"
        assert "already exited" in out["detail"]


# ── item 10: the refusal fires before anything is stopped ───────────────────────────────
def test_the_guard_refuses_before_any_process_is_touched(signed, monkeypatch, capsys):
    """`restart --scheduler` stops the running process first. A guard that fired after that
    would leave the operator with no scheduler at all."""
    touched: list = []
    monkeypatch.setattr(ops, "start_scheduler", lambda *a, **k: touched.append("start"))
    monkeypatch.setattr(ops, "ensure_single", lambda *a, **k: touched.append("stop") or True)
    monkeypatch.setattr(ops, "stop_runners", lambda *a, **k: touched.append("stop_runners"))

    args = argparse.Namespace(label="restart", yes=True, track1_only_shadow=False,
                              track1_shadow=False, ibkr_port=4002, no_shadow_resume=False,
                              assume_preflight_ok=False, restart_scheduler=True)
    rc = ops.cmd_up(args)
    assert rc == 2, "a legacy restart was allowed against a signed decision"
    assert touched == [], f"the guard fired after touching {touched}"
    assert "REFUSING" in capsys.readouterr().out


def test_track1_only_shadow_is_not_refused_by_the_new_guard(signed, monkeypatch, capsys):
    """The exempt mode: it is the one that removes the legacy entry jobs."""
    _blocked(monkeypatch)
    started: list = []
    monkeypatch.setattr(ops, "start_scheduler", lambda *a, **k: started.append(1) or 4242)
    monkeypatch.setattr(ops, "ensure_single", lambda *a, **k: True)
    monkeypatch.setattr(ops, "stop_runners", lambda *a, **k: [])
    monkeypatch.setattr(ops, "scan_processes", lambda *a, **k: [])

    monkeypatch.setattr(ops, "start_backend", lambda *a, **k: 4243)
    monkeypatch.setattr(ops, "backend_listener_pids", lambda *a, **k: [])
    args = argparse.Namespace(label="restart", yes=True, track1_only_shadow=True,
                              track1_shadow=False, ibkr_port=4002, api_port=5002,
                              no_shadow_resume=False, assume_preflight_ok=False,
                              restart_scheduler=True, restart_backend=False,
                              no_scheduler=False, no_backend=True)
    ops.cmd_up(args)
    out = capsys.readouterr().out
    assert "REFUSING to start" not in out, out[:600]
    assert started, "the exempt mode never reached the launcher"


def test_plain_track1_shadow_is_not_exempt(signed, monkeypatch, capsys):
    """It adds Track 1's slots and keeps all 45 legacy entry jobs — exactly the collision B1
    exists to prevent — so it is refused like any other legacy start.

    Stage 5ZZO: this pinned the literal source line `if not track1_only:`, which 5ZZO rewrote
    to `if args.restart_scheduler and not track1_only:` when it made the guard fire only where
    a start is actually attempted. A source pin goes stale the first time the code around it
    moves, and it goes red for a reason unrelated to what it is about. Asserted behaviourally
    now: ask for the transitional mode and watch it be refused.
    """
    assert ops.legacy_entry_start_blockers()
    touched: list = []
    monkeypatch.setattr(ops, "start_scheduler", lambda *a, **k: touched.append("start"))
    monkeypatch.setattr(ops, "ensure_single", lambda *a, **k: touched.append("stop") or True)
    monkeypatch.setattr(ops, "stop_runners", lambda *a, **k: [])
    args = argparse.Namespace(label="restart", yes=True, track1_only_shadow=False,
                              track1_shadow=True, ibkr_port=4002, api_port=5002,
                              no_shadow_resume=False, assume_preflight_ok=False,
                              restart_scheduler=True)
    assert ops.cmd_up(args) == 2
    out = capsys.readouterr().out
    assert "track1-shadow: REFUSING to start" in out, out
    assert touched == [], f"the guard fired after touching {touched}"
