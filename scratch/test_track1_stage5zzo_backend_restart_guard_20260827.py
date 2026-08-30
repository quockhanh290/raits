"""Stage 5ZZO — a guard that fired where nothing was starting.

Stage 5ZZN taught `ops` to refuse a scheduler start that would register legacy entry jobs
against a signed B1 decision. The check ran unconditionally, so it also refused
`restart --no-scheduler` — the command whose entire meaning is *leave the scheduler alone and
rebuild the backend* — with the words "this start would register 45 legacy entry job(s)", about
a start nobody had asked for.

That mattered more than a wrong message. It was the only route to a backend restart, and 5ZZN
had just documented that as the way to pick up the new dashboard API route. A guard that fires
where no start happens is not a stricter guard: it teaches an operator to work around it, and
the workaround here was `restart --scheduler` — restarting a live scheduler to rebuild a
read-only backend, which is the more dangerous of the two acts.

The fix is not a relaxation. The guard now fires at each of the two places a scheduler is
actually started, and both are still covered — including the cold-start path in the `else`
branch, which starts in legacy/default mode and which `restart --no-scheduler` reaches when
there is no scheduler to leave alone.

Nothing here starts a process, stops one, or touches the production confirmation file.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_index import track1_gates as gates                   # noqa: E402
from monitor import ops                                          # noqa: E402

SIGNED = {"schema_version": 1, "confirmed_by": "kevindo290", "confirmed_at": "2026-08-27",
          "legacy_retired_confirmed": True, "note": "Legacy retired for this paper login."}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A signed decision and a fully stubbed process world. Nothing real is touched."""
    f = tmp_path / "track1_go_live_confirmation.json"
    f.write_text(json.dumps(SIGNED), encoding="utf-8")
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", f)
    monkeypatch.setattr(gates, "CONFIRMATION_PATH", str(f))

    state = {"calls": [], "running": [3000]}

    def _scan(pattern):
        pids = state["running"] if pattern == ops.SCHEDULER_PATTERN else []
        return ops.ProcessScan(ok=True, processes=[
            ops.RunningProcess(pid=p, command="stub", started="2026-08-27 22:00:00")
            for p in pids])

    monkeypatch.setattr(ops, "scan_processes", _scan)
    monkeypatch.setattr(ops, "scheduler_processes", lambda *a, **k: [
        {"pid": p, "command": "stub --track1-only-shadow",
         "started": "2026-08-27 22:00:00", "age_seconds": 60} for p in state["running"]])
    monkeypatch.setattr(ops, "start_scheduler",
                        lambda *a, **k: state["calls"].append("start_scheduler") or 9001)
    monkeypatch.setattr(ops, "start_backend",
                        lambda *a, **k: state["calls"].append("start_backend") or 9002)
    monkeypatch.setattr(ops, "ensure_single",
                        lambda name, *a, **k: state["calls"].append(f"stop:{name}") or True)
    monkeypatch.setattr(ops, "stop_runners", lambda *a, **k: [])
    monkeypatch.setattr(ops, "backend_listener_pids", lambda *a, **k: [])
    return state


def _run(label, *, restart_scheduler, track1_only=False, track1_shadow=False):
    args = argparse.Namespace(label=label, yes=True, track1_only_shadow=track1_only,
                              track1_shadow=track1_shadow, ibkr_port=4002, api_port=5002,
                              no_shadow_resume=False, assume_preflight_ok=False,
                              restart_scheduler=restart_scheduler)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ops.cmd_up(args)
    return rc, buf.getvalue()


# ── the bug ─────────────────────────────────────────────────────────────────────────────
def test_backend_only_restart_is_not_refused(world):
    """The regression this stage is."""
    rc, out = _run("restart", restart_scheduler=False)
    assert rc == 0, out
    assert "REFUSING to start" not in out, out


def test_backend_only_restart_never_reaches_the_legacy_guard(world, monkeypatch):
    """Asserted at the guard itself, not only by its output: a message that stopped being
    printed for some other reason would pass a text check and prove nothing."""
    asked: list = []
    real = ops.legacy_entry_start_blockers
    monkeypatch.setattr(ops, "legacy_entry_start_blockers",
                        lambda *a, **k: asked.append(1) or real())
    _run("restart", restart_scheduler=False)
    assert asked == [], "the legacy start guard was consulted for a backend-only restart"


def test_backend_only_restart_touches_the_backend_and_not_the_scheduler(world):
    _run("restart", restart_scheduler=False)
    assert "start_scheduler" not in world["calls"], world["calls"]
    assert "start_backend" in world["calls"], world["calls"]
    assert "stop:scheduler" not in world["calls"], world["calls"]


def test_backend_only_restart_leaves_the_running_scheduler_listed(world):
    _, out = _run("restart", restart_scheduler=False)
    assert "3000" in out, "the scheduler it left alone should still be described"


# ── what must stay refused ──────────────────────────────────────────────────────────────
def test_a_default_scheduler_restart_still_refuses(world):
    rc, out = _run("restart", restart_scheduler=True)
    assert rc == 2
    assert "legacy/default: REFUSING to start" in out
    assert world["calls"] == [], f"something was touched before the refusal: {world['calls']}"


def test_a_transitional_shadow_restart_still_refuses(world):
    """`--track1-shadow` keeps all 45 legacy entry jobs. Not exempt."""
    rc, out = _run("restart", restart_scheduler=True, track1_shadow=True)
    assert rc == 2
    assert "track1-shadow: REFUSING to start" in out
    assert world["calls"] == []


def test_up_with_no_scheduler_running_still_refuses(world):
    """The cold-start path. `up` reaches it and starts in legacy/default mode."""
    world["running"] = []
    rc, out = _run("up", restart_scheduler=False)
    assert rc == 2
    assert "legacy/default: REFUSING to start" in out
    assert "start_scheduler" not in world["calls"]


def test_backend_only_restart_with_no_scheduler_running_also_refuses(world):
    """The case the fix must NOT open. `--no-scheduler` means 'leave it alone' — but when
    there is nothing to leave alone the same branch cold-starts one, in legacy/default mode,
    with no Track 1 flag. That is a real legacy start and is refused like any other."""
    world["running"] = []
    rc, out = _run("restart", restart_scheduler=False)
    assert rc == 2, out
    assert "legacy/default: REFUSING to start" in out
    assert "start_scheduler" not in world["calls"]


def test_the_track1_only_restart_remains_allowed(world):
    rc, out = _run("restart", restart_scheduler=True, track1_only=True)
    assert rc == 0, out
    assert "REFUSING to start" not in out
    assert "start_scheduler" in world["calls"]


# ── the shape of the fix ────────────────────────────────────────────────────────────────
def test_the_guard_is_checked_at_both_start_sites():
    """Two places start a scheduler. Both must be covered, or the fix has opened a hole."""
    text = (ROOT / "monitor" / "ops.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    assert body.count("_refuse_legacy_start(") >= 3, (
        "expected one definition and two call sites")
    assert "if args.restart_scheduler and not track1_only:" in body


def test_the_explicit_restart_is_still_guarded_before_anything_is_stopped():
    """5ZZN's property, and the reason the early check was not simply moved: a guard that
    fired after `ensure_single` would leave the operator with no scheduler at all."""
    text = (ROOT / "monitor" / "ops.py").read_text(encoding="utf-8")
    guard = text.index("if args.restart_scheduler and not track1_only:")
    stop = text.index('if not ensure_single("scheduler"', guard - 4000 if guard > 4000 else 0)
    assert guard < text.index('ensure_single("scheduler"', guard), (
        "the guard no longer precedes the stop")


def test_no_confirmation_means_nothing_is_refused(tmp_path, monkeypatch, world):
    absent = tmp_path / "nope.json"
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", absent)
    monkeypatch.setattr(gates, "CONFIRMATION_PATH", str(absent))
    for restart in (True, False):
        rc, out = _run("restart", restart_scheduler=restart)
        assert "REFUSING to start" not in out, (restart, out)


# ── safety ──────────────────────────────────────────────────────────────────────────────
def test_no_allow_orders_and_no_orders_directory():
    def stripped(path: Path) -> str:
        return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines()
                         if not l.strip().startswith("#"))

    assert "--allow-orders" not in stripped(ROOT / "monitor" / "ops.py")
    assert not (ROOT / "global_index" / "track1_runtime" / "orders").exists()


def test_orders_remain_impossible():
    import os
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")
    possible, why = gates.may_enable_orders()
    assert possible is False
    assert any("PAPER_SHADOW_EVIDENCE" in w for w in why)


def test_the_real_confirmation_is_untouched():
    live = ROOT / "track1_go_live_confirmation.json"
    assert live.exists(), "the operator's decision must still be in place"
    conf, errors = gates.load_confirmations(live)
    assert errors == []
    assert conf.get("legacy_retired_confirmed") is True
