"""Stage 5ZZZ-N — the canonical record must stay unambiguous.

Ten stages produced numbers under four regime bases and five parameter sets, and the single most
expensive mistake in that sequence was a LABEL, not a measurement: an arm called "ema=30" had been
running ema=50 the whole time. These tests pin the distinctions that cost the most to recover, so
the canonical deliverable cannot quietly lose them again.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DOC = REPO / "scratch" / "track1_stage5zzzn_canonical_strategy_baseline_reproduction_20260829.json"
NM = "not_measured"


@pytest.fixture(scope="module")
def rep():
    assert DOC.exists(), f"the deliverable is missing: {DOC}"
    return json.loads(DOC.read_text(encoding="utf-8"))


def _variant(rep, vid):
    return next(v for v in rep["part_c_variants"] if v["id"] == vid)


# ══════════════════════════════════════════════════════════════════════════════════════════
# the two baselines are different things and must never merge
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_json_parses_and_carries_both_sections(rep):
    assert "part_a_historical_reference" in rep
    assert "part_b_live_tradable_selected" in rep
    assert rep["part_a_historical_reference"] is not rep["part_b_live_tradable_selected"]


def test_the_historical_reference_is_marked_not_live_tradable(rep):
    a = rep["part_a_historical_reference"]
    assert a["regime_basis"] == "same-day daily close"
    assert a["live_tradable"] is False
    assert _variant(rep, 1)["live_tradable"] is False
    assert _variant(rep, 1)["decision"] == "reference only"


def test_the_reference_numbers_are_not_labelled_d1(rep):
    """The risk-clean reference row is $64,903 / $13,236 / $8,260. The D-1 risk-clean row is
    $57,289 / $12,419 / $7,077. Mixing them would overstate the paper baseline by ~$7,600."""
    ref = _variant(rep, 1)["risk_clean_net"]
    sel = _variant(rep, 2)["risk_clean_net"]
    assert ref == {"floor": 64903, "vault2025": 13236, "vault2026": 8260}
    assert sel == {"floor": 57289, "vault2025": 12419, "vault2026": 7077}
    assert ref != sel
    assert _variant(rep, 1)["regime_basis"] != _variant(rep, 2)["regime_basis"]


def test_both_baselines_were_reproduced_this_stage(rep):
    assert rep["part_a_historical_reference"]["reproduced"] is True
    assert rep["part_a_historical_reference"]["numbers_matched"] == 30
    assert rep["part_b_live_tradable_selected"]["reproduced"] is True
    assert rep["part_b_live_tradable_selected"]["expected_vs_reproduced"]["all_matched"] is True
    for label in ("TRACK1_REFERENCE_BASELINE_REPRODUCED", "LIVE_TRADABLE_BASELINE_REPRODUCED"):
        assert label in rep["final_labels"]


# ══════════════════════════════════════════════════════════════════════════════════════════
# the selected identity: effective params, both recorded
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_selected_paper_identity_has_effective_ema_50(rep):
    e = rep["part_b_live_tradable_selected"]["effective_params"]
    assert e["effective_ema_period"] == 50
    assert _variant(rep, 2)["effective_params"]["ema_period"] == 50


def test_requested_and_effective_are_both_recorded_and_differ(rep):
    e = rep["part_b_live_tradable_selected"]["effective_params"]
    assert e["asked_ema_period"] == 30
    assert e["effective_ema_period"] == 50
    assert e["ema_was_substituted"] is True
    assert e["requested_differs_from_effective"] is True
    v = _variant(rep, 2)
    assert v["requested_params"]["ema_period"] == 30
    assert v["effective_params"]["ema_period"] == 50


def test_the_selected_arm_is_causal_d1_and_proven(rep):
    b = rep["part_b_live_tradable_selected"]
    assert _variant(rep, 2)["regime_basis"] == "causal D-1"
    p = b["regime_basis_proof"]
    assert p["object"] == "RegimeLabels(lag_days=1)"
    assert p["label_change_sessions_in_floor"] > 100
    assert p["returned_previous_session_label"] == p["label_change_sessions_in_floor"]
    assert p["mismatches"] == 0
    for excluded in ("same-day label", "proxy label", "retuned params", "prevbar promotion"):
        assert excluded in b["excluded_by_construction"]


def test_no_baseline_artifact_was_modified(rep):
    b = rep["part_b_live_tradable_selected"]["baseline_artifacts"]
    assert b["modified"] is False
    assert b["sha256_after_equals_before"] is True


# ══════════════════════════════════════════════════════════════════════════════════════════
# the decision is an override, not a promotion
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_swing_inclusion_is_an_operator_override(rep):
    assert rep["swing_inclusion_is_operator_override"] is True
    assert rep["swing_inclusion_is_evidence_promotion"] is False
    assert "INCLUDE_SWING_IN_PAPER_BY_OPERATOR_OVERRIDE" in rep["final_labels"]
    assert rep["part_e_paper_scope"]["roska4_swing"]["included_by"] == "operator override"


def test_no_parameter_promotion_is_claimed(rep):
    assert rep["any_parameter_promotion_accepted"] is False
    assert "NO_SWING_PARAMETER_PROMOTION" in rep["final_labels"]
    for vid in (3, 5, 6, 7):
        assert _variant(rep, vid)["paper_selected"] is False


def test_the_decision_statement_carries_all_three_clauses(rep):
    s = rep["decision_statement"]
    assert "explicit operator risk acceptance" in s
    assert "causal D-1 old/effective ema=50" in s
    assert "not an evidence-based parameter promotion" in s
    assert "reference-only and not live-tradable" in s


def test_the_failing_thresholds_are_on_the_record(rep):
    """An override is only honest if what it overrides is written next to it."""
    t = rep["part_d_rationale"]["stage_L_thresholds_scored_against_the_selected_arm"]
    assert t["T2_swing_nonnegative_both_oos"].startswith("FAIL")
    assert t["T3_calmar_vs_no_swing"].startswith("FAIL")
    assert "negative in 2026" in rep["answers"]["swing_caveat"]
    assert _variant(rep, 2)["swing_contribution"]["vault2026"] < 0


# ══════════════════════════════════════════════════════════════════════════════════════════
# nothing is stated as ready, and nothing missing is filled in
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_orders_are_never_stated_as_possible(rep):
    assert rep["part_f_safety"]["orders_possible"] is False
    assert rep["part_f_safety"]["order_sent"] is False
    assert rep["part_f_safety"]["TRACK1_ORDERS_APPROVED_set"] is False
    assert rep["part_f_safety"]["orders_dir_present"] is False
    assert rep["part_f_safety"]["confirmation_approves_orders"] is False
    assert "PAPER_SHADOW_EVIDENCE" in rep["part_f_safety"]["blockers"]
    assert rep["part_f_safety"]["paper_shadow_evidence_still_required"] is True
    for label in ("PAPER_NOT_READY", "NO_ORDER_ACTIVATION"):
        assert label in rep["final_labels"]


def test_no_broker_call_and_nothing_restarted(rep):
    s = rep["part_f_safety"]
    assert s["broker_calls"] == 0
    assert s["scheduler_restarted"] is False
    assert s["backend_restarted"] is False
    assert s["runtime_evidence_modified"] is False
    assert s["live_route_params_changed"] is False
    assert s["swing_tf_param_changed"] is False


def test_the_windows_are_labelled_in_sample_oos_and_partial(rep):
    m = rep["window_meta"]
    assert m["floor"]["sample"] == "IN_SAMPLE"
    assert m["vault2025"]["sample"] == "OUT_OF_SAMPLE"
    assert m["vault2026"]["sample"] == "OUT_OF_SAMPLE"
    assert m["vault2026"]["partial"] is True
    assert m["floor"]["partial"] is False


def test_unmeasured_cells_say_so_rather_than_being_filled(rep):
    """The proxy arms have windows that were never run. A zero there would read as a measured
    result, which is the difference between "we looked" and "we could not look"."""
    spy, es = _variant(rep, 6), _variant(rep, 7)
    assert spy["full_stack_net"]["vault2025"] == NM
    assert spy["full_stack_net"]["vault2026"] == NM
    assert spy["full_stack_net"]["floor"] == 45603          # this one WAS measured
    for w in ("floor", "vault2025", "vault2026"):
        assert es["full_stack_net"][w] == NM
        assert es["swing_contribution"][w] == NM
    # and the control's zeros are real zeros, not placeholders
    assert _variant(rep, 8)["swing_contribution"] == {"floor": 0, "vault2025": 0, "vault2026": 0}


def test_every_variant_declares_the_full_set_of_fields(rep):
    need = {"id", "name", "regime_basis", "requested_params", "effective_params",
            "live_tradable", "paper_selected", "full_stack_net", "risk_clean_net",
            "swing_contribution", "decision", "caveat"}
    assert len(rep["part_c_variants"]) == 8
    for v in rep["part_c_variants"]:
        missing = need - set(v)
        assert not missing, (v["id"], missing)


def test_exactly_one_variant_is_selected_for_paper(rep):
    selected = [v for v in rep["part_c_variants"] if v["paper_selected"] is True]
    assert len(selected) == 1
    assert selected[0]["id"] == 2


def test_all_four_sleeves_are_in_scope_with_evidence_pending(rep):
    scope = rep["part_e_paper_scope"]
    for sleeve in ("global_nkd", "roska4_stress", "roska4_calm", "roska4_swing"):
        assert scope[sleeve]["in_scope"] is True
        assert scope[sleeve]["evidence"] == "pending"


# ══════════════════════════════════════════════════════════════════════════════════════════
# and the live state still matches what the document claims
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_document_matches_the_running_system(rep):
    import os

    from global_index import track1_gates as g

    ok, _ = g.may_enable_orders()
    assert ok is False and rep["part_f_safety"]["orders_possible"] is False
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not os.environ.get("TRACK1_ORDERS_APPROVED")
    blocking = {b.id for b in g.blocking()}
    assert "PAPER_SHADOW_EVIDENCE" in blocking


def test_the_frozen_param_is_still_not_what_the_artifacts_run(rep):
    """`SWING_TF_PARAM` says 30; the artifacts run 50. Both remain true, and the document has
    to keep saying so or the next reader repeats Stage 5ZZZ-L."""
    from futures.basket import SWING_TF_PARAM

    assert SWING_TF_PARAM["ema_period"] == 30
    assert rep["part_b_live_tradable_selected"]["effective_params"]["effective_ema_period"] == 50
