"""Stage 5ZZZ-BB. The Stress sleeve reports the basket state it already computed.

Stress answers every entry condition in full -- `entry_conditions` is `all()` over the table
`entry_checks` walks, and each row carries a value, a threshold, a comparator and a verdict.
On a day the basket did not set up, `detect_entry_for_slot` computed all of that and threw it
away at `return []`, so the panel printed "value not published" beside four rules the detector
had answered.

The route NOT taken, twice: calling `basket_state` from the live caller. A first attempt used
the wrong arguments; doing it correctly would still be a SECOND evaluation of a rule that
decides. These tests pin the seam instead, and pin that the historical builder never gets one.
"""
from __future__ import annotations

import inspect

import pytest

from global_index import track1_stress_mnq as SM
from global_index import track1_strategy_diagnostics as SD

CHECKS = [
    {"id": "breadth", "label": "Breadth", "value": 2, "threshold": 3,
     "comparator": ">=", "unit": "count", "passed": False, "applicable": True},
    {"id": "gapdown_count", "label": "Gap-down count", "value": 4, "threshold": 2,
     "comparator": ">=", "unit": "count", "passed": True, "applicable": True},
    {"id": "avg_gap", "label": "Basket gap", "value": -0.4, "threshold": None,
     "comparator": "<=", "unit": "pct", "passed": True, "applicable": False},
]


def _state(**over):
    st = {"kind": "basket_state", "day": "2026-08-31", "now": "10:35", "set_up": False,
          "reason": "conditions_not_met", "detail": "Breadth 2 (needs >= 3)",
          "checks": CHECKS, "features": {"breadth": 2}, "first_failed": "breadth"}
    st.update(over)
    return st


def _obs(**over):
    o = SD.StressObserver()
    o(_state(**over))
    return o


# -- the observer keeps what it is told, and only that ------------------------------------
def test_the_observer_keeps_the_basket_state():
    o = _obs()
    assert o.state["reason"] == "conditions_not_met"
    assert len(o.checks) == 3


def test_an_unrelated_event_is_ignored():
    """One channel, and nothing else may write to it."""
    o = _obs()
    o({"kind": "bar", "bar_ts": "x"})
    o({"kind": "gate", "gate": "regime", "passed": False})
    assert o.state["reason"] == "conditions_not_met" and len(o.checks) == 3


# -- rows are COPIED, not recomputed ------------------------------------------------------
def test_every_row_carries_the_detectors_own_verdict():
    """Unlike Normal-R4's rows, each of these IS the condition -- same list `all()` reduces."""
    rows = _obs().rows()
    assert [r["label"] for r in rows] == ["Breadth", "Gap-down count", "Basket gap"]
    assert [r["passed"] for r in rows] == [False, True, None]
    assert rows[0]["threshold"] == 3 and rows[0]["comparator"] == ">="


def test_a_condition_with_no_threshold_reports_and_does_not_vote():
    """`avg_gap_max` is nullable. The detector skips the comparison; the row must not invent
    a verdict, and must not be silently dropped either -- a rule that was not compared is a
    fact about the slot."""
    row = _obs().rows()[2]
    assert row["passed"] is None
    assert row["value"] == -0.4, "the value is still reported"
    assert "does not vote" in (row["detail"] or "")


def test_the_first_refusal_follows_the_detectors_order_not_the_first_one_found():
    """`first_failed` is the detector's answer. A reader that scans for the first False would
    disagree with it the moment the table is reordered."""
    checks = [dict(CHECKS[1], passed=False), dict(CHECKS[0])]
    o = _obs(checks=checks, first_failed="breadth")
    assert o.first_failed["id"] == "breadth", "took the scan order, not the detector's answer"


def test_a_state_with_no_named_refusal_falls_back_to_the_first_failing_check():
    o = _obs(first_failed=None)
    assert o.first_failed["id"] == "breadth"


# -- the block is the same shape every other sleeve publishes -----------------------------
def test_the_block_carries_the_keys_the_panel_reads_from_every_sleeve():
    b = SD.stress_block(sleeve="roska4_stress", slot_id="S1035", observer=_obs(), setups=[])
    for k in ("schema", "diagnostics_source", "sleeve", "slot_id", "detector", "rows",
              "gates", "bar_gate_grid", "nearest_failed_condition", "summary", "setup"):
        assert k in b, k
    assert b["detector"] == "track1_stress_mnq"
    assert b["nearest_failed_condition"]["gate"] == "breadth"


def test_rows_and_gates_stay_in_one_order_so_they_can_pair_by_position():
    """The panel pairs them by index. Pairing by label would break on a repeated display
    string, so the two lists must be built from one list in one order."""
    b = SD.stress_block(sleeve="roska4_stress", slot_id="", observer=_obs(), setups=[])
    assert [g["gate"] for g in b["gates"]] == [c["id"] for c in CHECKS]
    assert len(b["rows"]) == len(b["gates"])


def test_the_summary_says_which_of_the_three_outcomes_happened():
    o = _obs()
    assert "Breadth 2" in SD.stress_block(sleeve="s", slot_id="", observer=o,
                                          setups=[])["summary"]
    up = _obs(set_up=True, reason="", detail="")
    assert "no instrument broke" in SD.stress_block(sleeve="s", slot_id="", observer=up,
                                                    setups=[])["summary"]
    assert "1 entry candidate" in SD.stress_block(sleeve="s", slot_id="", observer=up,
                                                  setups=[object()])["summary"]


# -- the seam cannot decide anything ------------------------------------------------------
def test_the_state_is_reported_on_the_day_it_used_to_be_discarded(monkeypatch):
    """The whole point: a day with no set-up used to return [] and tell nobody why."""
    monkeypatch.setattr(SM, "basket_state",
                        lambda day, bars, prev_close, p: {
                            "set_up": False, "reason": "conditions_not_met",
                            "detail": "Breadth 2 (needs >= 3)", "contexts": {},
                            "features": {"breadth": 2}, "checks": CHECKS,
                            "first_failed": "breadth"})
    o = SD.StressObserver()
    got = SM.detect_entry_for_slot({}, "2026-08-31", bars={}, prev_close={}, observer=o)
    assert got == [], "the decision must be unchanged"
    assert o.state.get("first_failed") == "breadth", "nothing was reported"
    assert len(o.checks) == 3


def test_a_broken_observer_cannot_cost_the_slot_its_answer(monkeypatch):
    """A diagnostics bug must not be the reason a sleeve fails to find its entries."""
    monkeypatch.setattr(SM, "basket_state",
                        lambda day, bars, prev_close, p: {
                            "set_up": False, "reason": "x", "detail": "", "contexts": {},
                            "features": {}, "checks": [], "first_failed": None})

    def boom(_event):
        raise RuntimeError("observer exploded")
    assert SM.detect_entry_for_slot({}, "2026-08-31", bars={}, prev_close={},
                                    observer=boom) == []


def test_the_historical_builder_is_handed_no_observer():
    """Checked at the CALL SITE. `build_trades` must not be able to start reporting."""
    src = inspect.getsource(SM.build_trades)
    assert "detect_entry_for_slot(" in src, "the call this test guards has moved"
    assert "observer" not in src


def test_the_observer_parameter_is_keyword_only_and_defaults_to_none():
    """A positional observer is one argument-order slip away from changing a decision."""
    sig = inspect.signature(SM.detect_entry_for_slot)
    prm = sig.parameters["observer"]
    assert prm.kind is inspect.Parameter.KEYWORD_ONLY
    assert prm.default is None


# -- the panel mapper ---------------------------------------------------------------------
def test_the_panel_maps_a_recorded_block_into_the_fields_the_replay_fills():
    from monitor.backend import track1_market_view as MV

    b = SD.stress_block(sleeve="roska4_stress", slot_id="S1035", observer=_obs(), setups=[])
    out = MV._apply_stress_block({}, b)
    assert [r["id"] for r in out["rules"]] == ["breadth", "gapdown_count", "avg_gap"]
    assert [r["passed"] for r in out["rules"]] == [False, True, True]
    assert out["rules"][2]["source"] == MV.NOT_APPLICABLE, (
        "a condition the detector never compared must not read as one it checked")
    assert out["first_failed"] == "breadth"
    assert out["status"] == "conditions_not_met"


def test_the_panel_prefers_the_recorded_block_over_the_replay():
    """Checked in the SOURCE, because the replay path needs real stores to reach."""
    from monitor.backend import track1_market_view as MV

    src = inspect.getsource(MV._strategy)
    i_rec = src.index('_sd.recorded_for(root, day, sleeve)\n    if recorded')
    i_replay = src.index("from global_index import track1_stress_mnq as SM")
    assert i_rec < i_replay, "the replay would win over the slot's own account"


# -- a value too small for the format must not read as zero -------------------------------
def test_a_value_below_the_formats_precision_does_not_render_as_zero():
    """Stage 5ZZZ-BC. Found by running the seam on the real basket, not by reading the code.

    The rows this module carries are no longer all prices. `avg_gap` is a fraction judged
    against -0.001, and four decimals stripped of trailing zeros renders 1.2e-05 as "0" --
    indistinguishable from a true zero, beside a threshold three decimals up. Measured on
    2026-08-28: the row read "0" while the detector's own sentence in the same block carried
    the full number.
    """
    assert SD._row("g", 1.2e-05, unit="pct")["display_value"] == "1.2e-05"
    assert SD._row("g", -4e-07, unit="pct")["display_value"] != "0"


def test_a_true_zero_still_reads_zero():
    """The other direction. Without this the fix could turn every zero into 0.00e+00."""
    assert SD._row("g", 0.0, unit="pct")["display_value"] == "0"
    assert SD._row("g", 0, unit="count")["display_value"] == "0"


def test_the_unit_marker_survives_the_reformat():
    """A ratio without its `x` is a bare number and the reader loses what it is a ratio of."""
    assert SD._row("g", 0.004, unit="ratio")["display_value"] == "0.004x"
    assert SD._row("g", 1.63, unit="ratio")["display_value"] == "1.63x"


def test_the_formats_that_were_already_right_are_untouched():
    assert SD._row("g", 66440.0, unit="price")["display_value"] == "66,440.00"
    assert SD._row("g", 46, unit="count")["display_value"] == "46"
    assert SD._row("g", None, missing=SD.MISSING_DATA)["display_value"] == "Data unavailable"
