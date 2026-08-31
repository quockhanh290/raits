"""Stage 5ZZZ-AZ. The gate that holds the route until the last slot has been OBSERVED.

Every sleeve family's last slot fires at :55, which is the moment the window's final bar opens.
The detector reads a bar seconds old, its volume gate refuses it, and no later slot exists to
read it complete -- while the backtest reads the same bar whole. Measured: 13 of 1,223 orders
are signalled on that bar and withholding it costs 12.02% of P&L.

The gate asks for one thing: that a real Normal session's final slot have written down what it
saw. These tests exist because a gate that can only ever say no is the same as no gate.
"""
from __future__ import annotations

import json

import pytest

from global_index import track1_gates as g
from global_index import track1_strategy_diagnostics as sd

MEASURE = "final_bar_divergence_observed"
BLOCKER = "FINAL_BAR_DIVERGENCE_OBSERVED"


def _write(root, day: str, **over) -> None:
    """One recorded block on disk, in the shape the runtime actually writes."""
    block = {
        "schema": sd.SCHEMA,
        "diagnostics_source": sd.RECORDED,
        "sleeve": "roska4_swing",
        "slot_id": "LIVE_DAY_1555",
        "session_date": day,
        "bars_evaluated": 22,
        "last_bar_complete": False,
        "rows": [{"label": "Regime", "value": "Normal", "passed": True}],
        "bar_gate_grid": {"bars": ["15:50", "15:55"],
                          "rows": [{"gate": "regime", "reached": 22, "passed": 22},
                                   {"gate": "volume_resume_surge", "reached": 12,
                                    "passed": 0, "cells": "FFFFFFFFFFFF"}]},
    }
    block.update(over)
    p = sd.path_for(str(root), day)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(block, default=str) + "\n")


@pytest.fixture()
def root(tmp_path):
    return tmp_path


# -- it can say YES -----------------------------------------------------------------------
def test_a_recorded_normal_final_slot_with_a_grid_opens_the_gate(root):
    """Without this the gate could be hardcoded to refuse and every other test would pass."""
    _write(root, "20260901")
    ok, detail = g.MEASUREMENTS[MEASURE](root)
    assert ok is True, detail
    assert "closed=False" in detail
    assert "volume_resume_surge" in detail, detail


def test_the_detail_names_the_session_so_the_reader_can_go_and_look(root):
    _write(root, "20260901")
    _, detail = g.MEASUREMENTS[MEASURE](root)
    assert "roska4_swing" in detail and "LIVE_DAY_1555" in detail and "20260901" in detail


def test_the_night_family_last_slot_counts_too(root):
    _write(root, "20260901", sleeve="global_nkd", slot_id="NKD_NIGHT_0255")
    ok, _ = g.MEASUREMENTS[MEASURE](root)
    assert ok is True


# -- and it says NO for each distinct reason ----------------------------------------------
def test_nothing_on_disk_is_unknown_not_a_pass(root):
    ok, detail = g.MEASUREMENTS[MEASURE](root)
    assert ok is False
    assert "UNKNOWN" in detail, detail


def test_a_calm_session_does_not_count(root):
    """The whole question is what the detector does when the regime lets it look at bars."""
    _write(root, "20260901", rows=[{"label": "Regime", "value": "Calm", "passed": False}])
    ok, detail = g.MEASUREMENTS[MEASURE](root)
    assert ok is False
    assert "UNKNOWN" in detail, detail


def test_a_normal_slot_that_is_not_the_last_one_does_not_count(root):
    """A 15:30 slot sees its newest bar again five minutes later; the final slot never does."""
    _write(root, "20260901", slot_id="LIVE_DAY_1530")
    ok, _ = g.MEASUREMENTS[MEASURE](root)
    assert ok is False


def test_a_final_slot_whose_walk_reported_nothing_is_refused_and_says_so(root):
    """The pre-Stage-AW state: the block exists, the grid is empty, nothing was observed."""
    _write(root, "20260901", bar_gate_grid={"bars": [], "rows": []})
    ok, detail = g.MEASUREMENTS[MEASURE](root)
    assert ok is False
    assert "the walk did not report" in detail, detail
    assert "UNKNOWN" not in detail, "an empty grid is a different answer from no record at all"


def test_an_unanswered_bar_completeness_is_refused(root):
    """None means nobody measured it. A gate must not read that as "the bar was open"."""
    _write(root, "20260901", last_bar_complete=None)
    ok, detail = g.MEASUREMENTS[MEASURE](root)
    assert ok is False
    assert "the walk did not report" in detail, detail


def test_a_reconstructed_block_does_not_count_as_an_observation(root):
    """A replay is computed after the fact and can differ from what the slot decided on."""
    _write(root, "20260901", diagnostics_source="RECONSTRUCTED")
    ok, _ = g.MEASUREMENTS[MEASURE](root)
    assert ok is False


def test_an_unreadable_record_fails_closed(root, monkeypatch):
    """A check that cannot run is not a check that passed."""
    # A record has to EXIST first. Without this the function returns at the missing-directory
    # check and the monkeypatch is never reached -- the first version of this test passed on
    # a code path it never entered.
    _write(root, "20260901")

    def boom(*a, **k):
        raise OSError("disk gone")
    monkeypatch.setattr(sd, "read", boom)
    ok, detail = g.MEASUREMENTS[MEASURE](root)
    assert ok is False
    assert "failing closed" in detail, detail


# -- and it is actually wired into the thing that stops orders ----------------------------
def test_the_blocker_is_registered_and_blocks_orders():
    """Checked at the REGISTRY, not at the function: a measurement nothing consults is inert."""
    b = g.BLOCKERS[BLOCKER]
    assert b.blocks_orders is True
    assert b.status == g.MEASURED_GATE
    assert b.released_by_measurement == MEASURE
    assert b.released_by == (), "no signature may open this -- it is an observation, not a call"


def test_the_gate_is_in_the_blocking_list_right_now():
    """It has to be holding the route today; a gate that is already open guards nothing."""
    assert BLOCKER in [str(getattr(x, "id", x)) for x in g.blocking()]
