# -*- coding: utf-8 -*-
"""The Track 1 order gate is asked at EVERY slot, not once when the scheduler starts. 2026-10-08.

The paper-account baseline lives 24 h. It expired at 23:01 local on 10/06 and at 23:35 on 10/07,
both times mid-session, and the scheduler — which had asked the gate once, at startup, while it
was open — kept giving every later slot `--allow-orders`. The child then refused ("Nothing was
run") and recorded nothing: 6 NKD slots on the first night, 16 on the second.

Pinned here against the REAL scheduler (its job closures, argv captured, nothing executed):
  open now      -> the slot gets `--allow-orders`
  closed now    -> the slot runs in shadow (no flag) and the scheduler says so at WARNING
  open again    -> sending resumes without a restart
  no intent     -> a scheduler started without `--allow-orders` never arms, gate open or not
  unreadable    -> treated as closed
"""
import logging
import os

import pytest

from global_index import run_scheduler as rs
from global_index import track1_gates

SLOT = "track1_nkd_0110"
LABEL = SLOT.upper()


@pytest.fixture
def capture(monkeypatch):
    """The real scheduler with `_run` replaced by a recorder. Returns (fire, gate_state)."""
    os.environ.setdefault("PYTEST_CURRENT_TEST", "gate_per_slot")
    state = {"open": True, "raise": False, "calls": 0}

    def may_enable_orders(*a, **k):
        state["calls"] += 1
        if state["raise"]:
            raise RuntimeError("registry unreadable")
        return (True, []) if state["open"] else (False, ["B1_broker_account_or_legacy_retirement: baseline expired"])

    monkeypatch.setattr(track1_gates, "may_enable_orders", may_enable_orders)
    seen = []
    monkeypatch.setattr(rs, "_run", lambda args, label, dry_run=False, timeout=None, route=None:
                        seen.append((label, list(args))) or True)

    def build(allow_orders=True, **kw):
        lvl = logging.getLogger().manager.disable
        logging.disable(logging.CRITICAL)
        try:
            sched = rs.make_scheduler(port=4002, dry_run=True, allow_orders=allow_orders,
                                      track1_only=True, **kw)
        finally:
            logging.disable(lvl)
        job = sched.get_job(SLOT)
        assert job is not None, "the NKD slot is not registered; the harness proves nothing"

        def fire():
            before = len(seen)
            job.func()
            assert len(seen) == before + 1, "the slot did not launch"
            return seen[-1][1]
        return fire

    return build, state


def test_an_open_gate_arms_the_slot(capture):
    build, state = capture
    fire = build()
    assert "--allow-orders" in fire()


def test_a_gate_that_closes_mid_session_downgrades_the_next_slot_to_shadow(capture, caplog):
    build, state = capture
    fire = build()                                  # gate open at startup
    assert "--allow-orders" in fire()
    state["open"] = False                           # the baseline expires
    with caplog.at_level(logging.WARNING, logger=rs.log.name):
        argv = fire()
    assert "--allow-orders" not in argv, "a closed gate must not reach the child as an order request"
    assert "--source" in argv and "live-shadow" in argv, "the slot must still run, in shadow"
    assert any("order gate is closed" in r.getMessage() and LABEL in r.getMessage()
               for r in caplog.records), [r.getMessage() for r in caplog.records]


def test_a_gate_that_opens_mid_session_arms_without_a_restart(capture):
    build, state = capture
    state["open"] = False                           # closed when the scheduler starts
    fire = build()
    assert "--allow-orders" not in fire()
    state["open"] = True                            # a baseline is recorded
    assert "--allow-orders" in fire()


def test_control_no_operator_intent_never_arms_even_with_the_gate_open(capture):
    build, state = capture
    fire = build(allow_orders=False)
    assert "--allow-orders" not in fire()


def test_an_unreadable_registry_is_a_closed_gate(capture):
    build, state = capture
    fire = build()
    state["raise"] = True
    assert "--allow-orders" not in fire()


def test_the_gate_is_asked_at_launch_not_only_at_startup(capture):
    build, state = capture
    fire = build()
    after_startup = state["calls"]
    fire(); fire()
    assert state["calls"] == after_startup + 2, (after_startup, state["calls"])
