"""monitor/test_arming_path.py — the launcher may arm Track 1, and only when told to.

Operator decision 2026-09-23: run paper orders inside the session rather than by hand. That
reverses a rule written on 2026-08-27 and worth restating before it is changed, because the
reason it existed does not disappear with it:

    "Removed from the CHILD, whatever the launching shell happens to carry. This is the second
     of the two factors that arm Track 1, and a launcher must never be the thing that supplies
     it."

What that rule bought was this: a scheduler that came back on its own — after a reboot, after a
logon task, after an ops restart nobody was watching — could not be carrying order approval. A
machine that restarts itself is a thing this project now has, built the same morning.

So the rule goes, and the property it protected is kept by other means: the launcher supplies
approval ONLY on an explicit flag, and ONLY when the gate registry already says orders are
possible. Two factors, still two; the launcher can now be one of them, and cannot be both.

The first test is the one that has to keep passing for years: with no flag, nothing changed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monitor import ops

ENV = ops.TRACK1_ORDERS_ENV


def test_ap1_without_the_flag_the_child_still_gets_NO_approval(monkeypatch):
    """The default, and the whole of the old rule. An operator who exports the variable into
    the wrong shell still cannot leak it into a scheduler."""
    monkeypatch.setenv(ENV, "1")                       # the launching shell carries it
    env = ops._env(track1_shadow=True, track1_only=True)
    assert ENV not in env, (
        "the launching shell's approval reached the child without anyone asking for it — "
        "exactly what the 2026-08-27 rule was written to stop")


def test_ap2_with_the_flag_the_child_gets_approval(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    env = ops._env(track1_shadow=True, track1_only=True, allow_orders=True)
    assert env.get(ENV) == "1"


def test_ap3_the_flag_is_refused_while_the_registry_says_no(monkeypatch):
    """The launcher may be ONE factor. It may never be both.

    `orders_would_be_possible` reads the gate registry, which reads the signed confirmation
    file and the measurements behind each blocker. If that says no, a flag on a command line
    does not get to overrule it — that is the half of the old rule that stays.
    """
    monkeypatch.setattr(ops, "orders_would_be_possible",
                        lambda: (False, ["PAPER_SHADOW_EVIDENCE: 4 FAIL day(s)"]))
    ok, why = ops.arming_refusal(allow_orders=True)
    assert ok is False
    assert "PAPER_SHADOW_EVIDENCE" in " ".join(why)


def test_ap4_the_flag_is_allowed_once_the_registry_says_yes(monkeypatch):
    monkeypatch.setattr(ops, "orders_would_be_possible", lambda: (True, []))
    ok, _why = ops.arming_refusal(allow_orders=True)
    assert ok is True


def test_ap5_no_flag_is_never_refused(monkeypatch):
    """A shut gate must not stop an ordinary shadow start — that would make every restart
    depend on evidence the shadow route is there to collect."""
    monkeypatch.setattr(ops, "orders_would_be_possible",
                        lambda: (False, ["PAPER_SHADOW_EVIDENCE: 4 FAIL day(s)"]))
    ok, _why = ops.arming_refusal(allow_orders=False)
    assert ok is True


def test_ap6_the_scheduler_child_is_told_too(monkeypatch):
    """The environment alone does not reach a SLOT: each slot is its own process, spawned by
    the scheduler with an argv the scheduler builds. If the flag stops at the scheduler, every
    slot still runs unarmed and the whole change is a banner with nothing behind it."""
    seen = {}

    def _fake_popen(args, **kw):
        seen["args"] = list(args)
        seen["env"] = kw.get("env") or {}
        raise RuntimeError("stop here — argv is all this test needs")

    monkeypatch.setattr(ops.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(ops, "scheduler_processes", lambda: [])
    with pytest.raises(RuntimeError):
        ops.start_scheduler(4002, shadow_resume=False, assume_preflight_ok=False,
                            track1_shadow=True, track1_only=True, allow_orders=True)
    assert "--allow-orders" in seen["args"], (
        f"the scheduler was not told, so no slot it spawns can be armed: {seen['args']}")
    assert seen["env"].get(ENV) == "1"


def test_ap7_an_explicit_arm_is_not_an_unasked_for_shadow_start(monkeypatch, tmp_path):
    """The guard that refuses a shadow start while orders are possible must read the request.

    Its own docstring records what happens when it has no answer for one: on 2026-08-27 it
    refused `--track1-only-shadow`, the operator restarted into plain legacy instead, and 45
    legacy entry jobs were registered on the login the signature had just declared retired.
    "The guard pushed the operator out of the only safe mode and into the unsafe one."

    `--allow-orders` IS the resolved intent, so the refusal has nothing left to protect.
    """
    conf = tmp_path / "track1_go_live_confirmation.json"
    conf.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", conf)
    monkeypatch.setattr(ops, "orders_would_be_possible", lambda: (True, []))

    assert ops.track1_shadow_blockers(track1_only=True), (
        "without the flag the guard must still refuse — that is the behaviour being kept")
    assert ops.track1_shadow_blockers(track1_only=True, allow_orders=True) == [], (
        "an explicitly armed start was refused as an unasked-for shadow start, which is the "
        "exact shape that drove an operator into legacy mode once already")


def test_ap8_status_reports_the_SCHEDULERS_arming_not_the_shells(monkeypatch):
    """Measured the night orders were first armed, and it nearly caused a wrong call.

    The scheduler's argv carried `--allow-orders`, the route WAS armed, and `ops status`
    printed `track1_orders_approved=False` — because that field reads the environment of the
    process running `ops status`, which is whatever shell the operator typed in. One line, read
    at 23:10, saying the opposite of the truth.

    The scheduler is what spawns slots, so the scheduler is what the question is about.
    """
    monkeypatch.setattr(ops, "scheduler_processes", lambda: [
        {"pid": 1480, "command": "pythonw -m global_index.run_scheduler --port 4002 "
                                 "--shadow-resume --track1-only-shadow --allow-orders"}])
    monkeypatch.delenv(ENV, raising=False)          # the shell knows nothing
    t = ops.track1_status()
    assert t["scheduler_armed"] is True, (
        "status says the scheduler is not armed while its own argv says it is")
    assert t["orders_env_present"] is False, "the shell field must keep answering about the shell"


def test_ap9_an_unarmed_scheduler_reports_unarmed(monkeypatch):
    monkeypatch.setattr(ops, "scheduler_processes", lambda: [
        {"pid": 1480, "command": "pythonw -m global_index.run_scheduler --port 4002 "
                                 "--track1-only-shadow"}])
    assert ops.track1_status()["scheduler_armed"] is False


def test_ap10_a_backend_only_restart_is_not_refused_by_a_start_guard(monkeypatch):
    """`restart --no-scheduler` starts no scheduler, so a refusal about starting one is about a
    start nobody asked for.

    Measured 2026-09-24, minutes after orders became possible: `ops restart --no-scheduler
    --track1-only-shadow` was refused with "this route can send orders. A shadow start must not
    run while that is true" — blocking the documented way to pick up a new API route. Stage 5ZZO
    had already fixed exactly this shape on the legacy branch and written down why.
    """
    seen = {}
    monkeypatch.setattr(ops, "track1_shadow_blockers",
                        lambda **kw: seen.setdefault("asked", True) or ["would refuse"])
    monkeypatch.setattr(ops, "arming_refusal", lambda *, allow_orders: (True, []))
    monkeypatch.setattr(ops, "ensure_single", lambda *a, **k: False)   # stop early, harmlessly

    args = ops.build_parser().parse_args(["restart", "--no-scheduler", "--track1-only-shadow"])
    ops.cmd_up(args)
    assert "asked" not in seen, (
        "the shadow START guard was consulted for a restart that starts no scheduler")
