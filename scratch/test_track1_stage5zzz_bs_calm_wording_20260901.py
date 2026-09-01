"""Stage 5ZZZ-BS. Two things the Calm cards got wrong, both found by watching a live session.

  1. The gate rows printed raw floats. Measured 2026-09-01: `needs <= 0.3333333333333333`
     beside a reading of `0.8315217391304348` -- sixteen significant digits each, on a panel
     where every other number carries two to four. The row builder has always formatted its
     values; the Calm gates never went through it.

  2. The two cards contradicted each other about the same fact:

         DECIDE    No setup recorded at 09:32 - no_candidate
         OBSERVE   Nothing observed - no_decide_row_for_this_day

     One says the phase ran and found nothing; the other says it never ran. They lead to
     different actions -- "no trade today" versus "something did not run" -- and an operator
     cannot tell which from a page that says both. The live slot writes that code whenever
     DECIDE produced no SETUP, and the summary echoed the code verbatim.

Nothing recorded is edited: the reason code still travels in the payload and the record on
disk is untouched. What changes is the sentence a person reads.
"""
from __future__ import annotations

import json

import pytest

from global_index import track1_shadow_intent as si
from global_index import track1_strategy_diagnostics as SD


# -- 1. one formatter for the whole panel -------------------------------------------------
@pytest.mark.parametrize("value,expected", [
    (0.8315217391304348, "0.8315"),
    (0.3333333333333333, "0.3333"),
    (66175.0, "66,175"),
    (0.0, "0"),
])
def test_a_number_prints_the_way_the_rest_of_the_panel_prints_numbers(value, expected):
    assert SD.format_number(value) == expected


def test_a_value_too_small_for_the_format_does_not_print_as_zero():
    """The same measured case the row builder carries this branch for: a reading of 1.2e-05
    rendered as "0" is indistinguishable from a true zero, beside a threshold three decimals
    further up."""
    assert SD.format_number(1.2e-05) == "1.2e-05"


def test_something_that_is_not_a_number_yields_nothing_rather_than_a_string():
    """So the caller keeps whatever it had. Returning "None" or "nan" would put a word where a
    reader expects a measurement."""
    assert SD.format_number(None) == ""
    assert SD.format_number("Calm") == ""


def _intent(root, day, slot, phase, inst="MES", **extra):
    row = {"schema": 1, "sleeve": "roska4_calm", "slot_id": slot, "phase": phase,
           "session_date": day, "status": "RECORDED", "reason_code": "ok",
           "before_entry": {"setup": "calm_a", "instrument": inst, "direction": "LONG"}}
    row.update(extra)
    p = si.path_for(root, day)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


def _diag(root, day, slot, gates):
    SD.record({"schema": 1, "sleeve": "roska4_calm", "slot_id": slot, "slot_time": "0932",
               "session_date": day, "diagnostics_source": SD.RECORDED,
               "gates": gates, "rows": []}, root=root, day=day)


def test_the_calm_gate_rows_reach_the_page_already_printed(tmp_path):
    """The defect, at the level the page reads. A renderer that formats for itself is a second
    set of rounding rules for one dashboard."""
    day = "2026-09-01"
    _intent(tmp_path, day, "TRACK1_CALM_DECIDE_0932", si.DECIDE)
    _diag(tmp_path, day, "TRACK1_CALM_DECIDE_0932",
          [{"gate": "prior_rth_close_bottom_third", "passed": False,
            "value": 0.8315217391304348, "threshold": 0.3333333333333333, "comparator": "<="}])
    blk = SD.calm_blocks(tmp_path, day, now="2026-09-01 11:00")["decide"]
    g = [x for x in (blk.get("gates") or [])
         if x.get("gate") == "prior_rth_close_bottom_third"][0]
    assert g["display_value"] == "0.8315", g
    assert g["display_threshold"] == "0.3333", g
    assert g["value"] == pytest.approx(0.8315217391304348), "the raw value must survive"


# -- 2. the two cards stop contradicting each other ---------------------------------------
#: The literal the live slot writes, not the constant. A fixture that reads the same constant
#: production compares against agrees with itself no matter what either says -- and it hid a
#: mutation: changing the constant changed what the fixture WROTE too, so the branch still
#: matched and the test stayed green with the fix effectively removed.
STORED_NO_DECIDE_ROW = "no_decide_row_for_this_day"


def _observe_refused(root, day):
    _intent(root, day, "TRACK1_CALM_OBSERVE_1002", si.OBSERVE,
            status="REFUSED", reason_code=STORED_NO_DECIDE_ROW, before_entry={})


def test_the_observe_card_says_the_decide_phase_ran_when_it_did(tmp_path):
    """The measured pair. DECIDE recorded `no_candidate`, OBSERVE said there was no DECIDE
    row, and both cards were on the screen at once."""
    day = "2026-09-01"
    _intent(tmp_path, day, "TRACK1_CALM_DECIDE_0932", si.DECIDE,
            status="NO_SETUP", reason_code="no_candidate", before_entry={})
    _observe_refused(tmp_path, day)
    out = SD.calm_blocks(tmp_path, day, now="2026-09-01 11:00")
    summary = out["observe"]["summary"]
    assert "ran at 09:32" in summary, summary
    assert "no_decide_row_for_this_day" not in summary, summary


def test_a_day_where_decide_really_did_not_run_keeps_the_original_sentence(tmp_path):
    """The other half of the distinction. Softening this one would hide a phase that failed to
    run behind a sentence saying it ran and found nothing -- the same confusion, reversed."""
    day = "2026-09-01"
    _observe_refused(tmp_path, day)
    out = SD.calm_blocks(tmp_path, day, now="2026-09-01 11:00")
    summary = out["observe"]["summary"]
    assert "No DECIDE row" in summary or "no_decide_row_for_this_day" in summary, summary
    assert "ran at 09:32" not in summary, summary


def test_the_recorded_reason_code_still_travels_with_the_block(tmp_path):
    """The sentence is for a person; the code is the record. Rewriting the code to make the
    card read better would edit runtime evidence to fix a display, and the store is the trail
    an audit exists to protect."""
    day = "2026-09-01"
    _intent(tmp_path, day, "TRACK1_CALM_DECIDE_0932", si.DECIDE,
            status="NO_SETUP", reason_code="no_candidate", before_entry={})
    _observe_refused(tmp_path, day)
    blk = SD.calm_blocks(tmp_path, day, now="2026-09-01 11:00")["observe"]
    assert blk["reason_code"] == STORED_NO_DECIDE_ROW, blk
    assert blk["status"] == "REFUSED", blk


def test_a_phase_that_actually_observed_is_untouched(tmp_path):
    """The wording fix must not reach a phase that has something to say."""
    day = "2026-09-01"
    _intent(tmp_path, day, "TRACK1_CALM_DECIDE_0932", si.DECIDE)
    _intent(tmp_path, day, "TRACK1_CALM_OBSERVE_1002", si.OBSERVE,
            after_reference={"planned_stop": 7600.2, "instrument": "MES"})
    blk = SD.calm_blocks(tmp_path, day, now="2026-09-01 11:00")["observe"]
    assert blk["summary"] == "The entry reference was read and the stop evaluated", blk


def test_the_constant_still_matches_what_the_store_holds():
    """The fixture pins the literal, so this is what keeps the two from drifting apart. If the
    vocabulary is ever renamed, this fails here rather than silently making every test above
    describe a code nothing writes."""
    assert si.NO_DECIDE_ROW == STORED_NO_DECIDE_ROW
