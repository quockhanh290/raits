"""Stage 5ZZZ-BH/BI. Calm trades a basket, and the panel showed one of it.

Two defects an operator found by reading the screen, not by a test failing.

  1. `calm_blocks` returned one block per PHASE and built it from `mine[-1]`, so on a day the
     sleeve recorded two setups the second silently replaced the first. Measured 2026-08-31:
     MES and MNQ, both LONG, with different numbers --

         prior_rth_close_bottom_third   MES 0.1555   MNQ 0.1581
         prior_rth_down_close           MES -0.0030  MNQ -0.0044

     -- and the card showed a single stop of 28,837 with no instrument named. MES's own stop,
     7,600, existed nowhere on the page.

  2. The job card read NO SIGNAL for those same slots. The signal ROW is right: Calm records
     what it found as a shadow intent, not a tradable candidate, because at 09:32 the price
     those trades would fill at does not exist. The card was reading one store of two.
"""
from __future__ import annotations

import json

import pytest

from global_index import track1_signals as sig
from global_index import track1_strategy_diagnostics as SD


# -- 1. every instrument survives ---------------------------------------------------------
def _intent(root, day, slot, phase, inst, planned_stop=None):
    from global_index import track1_shadow_intent as si
    be = {"setup": "calm_a", "instrument": inst, "direction": "LONG",
          "intent": "would_send_at_entry_reference_time"}
    row = {"schema": 1, "sleeve": "roska4_calm", "slot_id": slot, "phase": phase,
           "session_date": day, "status": "RECORDED", "reason_code": "ok",
           "before_entry": be}
    if planned_stop is not None:
        row["after_reference"] = {"planned_stop": planned_stop, "instrument": inst}
    p = si.path_for(root, day) if hasattr(si, "path_for") else None
    if p is None:
        pytest.skip("shadow intent store has no path_for to write a fixture into")
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


@pytest.fixture()
def two_instrument_day(tmp_path):
    from global_index import track1_shadow_intent as si
    day = "2026-09-01"
    for inst in ("MES", "MNQ"):
        _intent(tmp_path, day, "TRACK1_CALM_DECIDE_0932", si.DECIDE, inst)
    _intent(tmp_path, day, "TRACK1_CALM_OBSERVE_1002", si.OBSERVE, "MES", planned_stop=7600.2)
    _intent(tmp_path, day, "TRACK1_CALM_OBSERVE_1002", si.OBSERVE, "MNQ", planned_stop=28837.2)
    return tmp_path, day


def test_both_instruments_survive_the_phase_block(two_instrument_day):
    """The defect: `mine[-1]` kept one and dropped the rest without a word."""
    root, day = two_instrument_day
    out = SD.calm_blocks(root, day, now="2026-09-01 11:00")
    for phase in ("decide", "observe"):
        blk = out[phase]
        assert blk["instrument_count"] == 2, (phase, blk.get("instrument_count"))
        assert [i["instrument"] for i in blk["instruments"]] == ["MES", "MNQ"], phase


def test_the_instrument_at_the_top_level_is_named_not_silent(two_instrument_day):
    """One row's values still sit at the top of the block. Which row must be stated."""
    root, day = two_instrument_day
    blk = SD.calm_blocks(root, day, now="2026-09-01 11:00")["decide"]
    assert blk["instrument"] in ("MES", "MNQ")
    assert blk["instrument"] == blk["instruments"][-1]["instrument"], (
        "the top level must name the row it was built from")


def test_each_instrument_keeps_its_own_stop(two_instrument_day):
    """The number that made this visible: one card, one stop, and half the sleeve missing."""
    root, day = two_instrument_day
    blk = SD.calm_blocks(root, day, now="2026-09-01 11:00")["observe"]
    stops = {i["instrument"]: [l["price"] for l in i["price_levels"]] for i in blk["instruments"]}
    assert stops == {"MES": [7600.2], "MNQ": [28837.2]}, stops


def test_a_decide_phase_still_publishes_no_stop(two_instrument_day):
    """Guarded per instrument for the same reason the block is: a planned stop at half past
    nine would be a price nobody computed."""
    root, day = two_instrument_day
    blk = SD.calm_blocks(root, day, now="2026-09-01 11:00")["decide"]
    assert all(i["price_levels"] == [] for i in blk["instruments"])


def test_a_single_instrument_day_is_unchanged(tmp_path):
    """The common case must not grow a list it does not need to be read correctly."""
    from global_index import track1_shadow_intent as si
    day = "2026-09-01"
    _intent(tmp_path, day, "TRACK1_CALM_DECIDE_0932", si.DECIDE, "MES")
    blk = SD.calm_blocks(tmp_path, day, now="2026-09-01 11:00")["decide"]
    assert blk["instrument_count"] == 1
    assert blk["instrument"] == "MES"


# -- 2. the card reads both stores --------------------------------------------------------
def _jobs(root, day, slot, status):
    from monitor.backend import job_journal_reader as J
    jobs = [{"job_id": slot, "id": slot + ":x", "status": "completed",
             "job_type": "track1_strategy"}]
    row = {"slot_id": slot, "sleeve": "roska4_calm", "status": status,
           "raw_candidates": 0, "accepted": 0, "rejected": 0, "reason": "decided",
           "rule_checks": [], "candidates": []}
    return J, jobs, row


def test_a_calm_slot_with_intents_stops_reading_no_signal(tmp_path, monkeypatch):
    """The operator's question: two setups were recorded, why does the card say nothing."""
    from global_index import track1_shadow_intent as si
    from monitor.backend import job_journal_reader as J
    day = "2026-09-01"
    slot = "TRACK1_CALM_DECIDE_0932"
    for inst in ("MES", "MNQ"):
        _intent(tmp_path, day, slot, si.DECIDE, inst)
    jobs = [{"job_id": slot, "status": "completed"}]
    row = {"slot_id": slot, "sleeve": "roska4_calm", "status": sig.NO_SIGNAL,
           "raw_candidates": 0, "accepted": 0, "rejected": 0, "reason": "decided",
           "rule_checks": [], "candidates": []}
    monkeypatch.setattr(sig, "read_day", lambda d, root=None: ([row], []))
    monkeypatch.setattr(J, "is_track1_strategy_job", lambda jid: True)
    J._annotate_signal_diagnostics(jobs, day, tmp_path)
    s = jobs[0]["signal"]
    assert s["status"] == sig.RAW_SIGNAL_FOUND, s
    got = {(i["instrument"], i["direction"]) for i in s["details"]["recorded_intents"]}
    assert got == {("MES", "LONG"), ("MNQ", "LONG")}, got


def test_the_chip_and_the_summary_never_disagree(tmp_path, monkeypatch):
    """The first version corrected the chip and left the summary reading NO SIGNAL, so one
    card carried both words about one slot. Worse than either alone."""
    from global_index import track1_shadow_intent as si
    from monitor.backend import job_journal_reader as J
    day, slot = "2026-09-01", "TRACK1_CALM_DECIDE_0932"
    _intent(tmp_path, day, slot, si.DECIDE, "MES")
    jobs = [{"job_id": slot, "status": "completed"}]
    row = {"slot_id": slot, "sleeve": "roska4_calm", "status": sig.NO_SIGNAL,
           "raw_candidates": 0, "accepted": 0, "rejected": 0, "reason": "decided",
           "rule_checks": [], "candidates": []}
    monkeypatch.setattr(sig, "read_day", lambda d, root=None: ([row], []))
    monkeypatch.setattr(J, "is_track1_strategy_job", lambda jid: True)
    J._annotate_signal_diagnostics(jobs, day, tmp_path)
    s = jobs[0]["signal"]
    assert "NO SIGNAL" not in s["summary"], s["summary"]
    assert s["chip"]["label"] in s["summary"], (s["chip"]["label"], s["summary"])


def test_a_slot_with_no_intent_is_left_alone(tmp_path, monkeypatch):
    """A slot that ran and recorded nothing is NOT a setup. Turning its presence into one is
    the fiction this module refuses everywhere else."""
    from monitor.backend import job_journal_reader as J
    day, slot = "2026-09-01", "TRACK1_CALM_DECIDE_0932"
    jobs = [{"job_id": slot, "status": "completed"}]
    row = {"slot_id": slot, "sleeve": "roska4_calm", "status": sig.NO_SIGNAL,
           "raw_candidates": 0, "accepted": 0, "rejected": 0, "reason": "decided",
           "rule_checks": [], "candidates": []}
    monkeypatch.setattr(sig, "read_day", lambda d, root=None: ([row], []))
    monkeypatch.setattr(J, "is_track1_strategy_job", lambda jid: True)
    J._annotate_signal_diagnostics(jobs, day, tmp_path)
    s = jobs[0]["signal"]
    assert s["status"] == sig.NO_SIGNAL
    assert "recorded_intents" not in s["details"], "an untouched card grew a key"


def test_a_rejected_row_is_never_overwritten(tmp_path, monkeypatch):
    """Only NO_SIGNAL is corrected. A row that names a refusing layer already knows more than
    the intent stream does, and must keep saying it."""
    from global_index import track1_shadow_intent as si
    from monitor.backend import job_journal_reader as J
    day, slot = "2026-09-01", "TRACK1_CALM_DECIDE_0932"
    _intent(tmp_path, day, slot, si.DECIDE, "MES")
    jobs = [{"job_id": slot, "status": "completed"}]
    row = {"slot_id": slot, "sleeve": "roska4_calm", "status": sig.SIGNAL_REJECTED,
           "raw_candidates": 1, "accepted": 0, "rejected": 1, "reason": "capped",
           "rejecting_layer": "cluster_cap", "rule_checks": [], "candidates": []}
    monkeypatch.setattr(sig, "read_day", lambda d, root=None: ([row], []))
    monkeypatch.setattr(J, "is_track1_strategy_job", lambda jid: True)
    J._annotate_signal_diagnostics(jobs, day, tmp_path)
    assert jobs[0]["signal"]["status"] == sig.SIGNAL_REJECTED


def test_a_recorded_row_without_an_intent_is_not_a_setup(tmp_path, monkeypatch):
    """Found by a mutation that should have failed this test and failed a different one.

    A slot can record a row and name no intent -- it ran, it looked, it found nothing. Counting
    the row's PRESENCE as a setup is the same fiction as manufacturing a NO_SIGNAL for a slot
    that never ran, and this module refuses that one by name.
    """
    from monitor.backend import job_journal_reader as J
    day, slot = "2026-09-01", "TRACK1_CALM_DECIDE_0932"
    from global_index import track1_shadow_intent as si
    p = si.path_for(tmp_path, day)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"schema": 1, "sleeve": "roska4_calm", "slot_id": slot,
                             "phase": si.DECIDE, "session_date": day, "status": "RECORDED",
                             "reason_code": "no_setup", "before_entry": {}}) + "\n")
    assert J._recorded_intents(day, tmp_path) == {}, "a row with no intent was counted"

    jobs = [{"job_id": slot, "status": "completed"}]
    row = {"slot_id": slot, "sleeve": "roska4_calm", "status": sig.NO_SIGNAL,
           "raw_candidates": 0, "accepted": 0, "rejected": 0, "reason": "decided",
           "rule_checks": [], "candidates": []}
    monkeypatch.setattr(sig, "read_day", lambda d, root=None: ([row], []))
    monkeypatch.setattr(J, "is_track1_strategy_job", lambda jid: True)
    J._annotate_signal_diagnostics(jobs, day, tmp_path)
    assert jobs[0]["signal"]["status"] == sig.NO_SIGNAL
