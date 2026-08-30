"""Stage 5ZZZ-O — the Swing paper override is a record of SCOPE, and grants nothing.

The danger in writing a decision into a route's trail is that a later reader treats it as
permission. These tests exist so that cannot happen quietly: the gate answers must be identical
whether the record is absent, valid or corrupt, and every field that could be mistaken for
authority is pinned to false.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_gates as G                        # noqa: E402
from global_index import track1_swing_paper_override as SO        # noqa: E402

RECORD = REPO / SO.RECORD_PATH
CANON = REPO / "scratch" / "track1_stage5zzzn_canonical_strategy_baseline_reproduction_20260829.json"


def _valid_payload() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


@pytest.fixture
def tmp_record(tmp_path):
    """A writable copy, so no test ever edits the real record."""
    def _write(payload):
        p = tmp_path / SO.RECORD_PATH
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p
    return _write


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. the record parses only with everything it needs
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_real_record_is_valid():
    ov = SO.load(RECORD)
    assert ov.valid, ov.reason
    assert ov.decision == SO.DECISION
    assert ov.route == SO.ROUTE and ov.sleeve == SO.SLEEVE
    assert ov.regime_basis == "causal_d1"
    assert ov.selected_identity == "D1_OLD_EFFECTIVE_EMA50"
    assert ov.risk_acceptance is True
    assert ov.confirmed_by and ov.confirmed_at


@pytest.mark.parametrize("field", sorted(SO.REQUIRED_FIELDS))
def test_a_missing_required_field_grants_nothing(tmp_record, field):
    p = _valid_payload()
    p.pop(field)
    ov = SO.load(tmp_record(p))
    assert ov.valid is False
    assert field in ov.reason or "missing required fields" in ov.reason


def test_an_absent_record_grants_nothing(tmp_path):
    ov = SO.load(tmp_path / "nothing-here.json")
    assert ov.valid is False and "no override record" in ov.reason


def test_unreadable_json_grants_nothing(tmp_path):
    p = tmp_path / SO.RECORD_PATH
    p.write_text("{not json", encoding="utf-8")
    ov = SO.load(p)
    assert ov.valid is False and "unreadable" in ov.reason


def test_an_unsigned_record_grants_nothing(tmp_record):
    p = _valid_payload()
    p["confirmed_by"] = "   "
    ov = SO.load(tmp_record(p))
    assert ov.valid is False and "unsigned" in ov.reason


@pytest.mark.parametrize("field,bad", [
    ("route", "legacy_roska4"), ("sleeve", "roska4_calm"),
    ("regime_basis", "same_day"), ("selected_identity", "D1_RETUNED_EMA10"),
    ("decision", "PROMOTE_CAUSAL_SWING"), ("decision_type", "something_else"),
    ("schema", "track1_swing_paper_override/2"),
])
def test_a_mismatched_field_grants_nothing(tmp_record, field, bad):
    p = _valid_payload()
    p[field] = bad
    ov = SO.load(tmp_record(p))
    assert ov.valid is False and field in ov.reason


def test_a_record_claiming_a_promotion_is_refused(tmp_record):
    """The one claim these stages declined to make. A record asserting it is not honoured."""
    for field in ("parameter_promotion", "evidence_promotion"):
        p = _valid_payload()
        p[field] = True
        ov = SO.load(tmp_record(p))
        assert ov.valid is False, f"{field}=True was accepted"
        assert field in ov.reason


def test_a_record_without_risk_acceptance_is_refused(tmp_record):
    p = _valid_payload()
    p["risk_acceptance"] = False
    ov = SO.load(tmp_record(p))
    assert ov.valid is False and "risk_acceptance" in ov.reason


def test_dropping_a_caveat_is_refused(tmp_record):
    """An override whose reasons-against have gone missing reads as an endorsement."""
    for drop in SO.REQUIRED_CAVEATS:
        p = _valid_payload()
        p["caveats"] = [c for c in p["caveats"] if c != drop]
        ov = SO.load(tmp_record(p))
        assert ov.valid is False, f"dropping {drop!r} was accepted"
        assert "caveats dropped" in ov.reason


def test_an_expired_record_grants_nothing(tmp_record):
    p = _valid_payload()
    p["expires_at"] = "2026-08-01"
    assert SO.load(tmp_record(p), now="2026-08-29").valid is False
    assert SO.load(tmp_record(p), now="2026-07-01").valid is True


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. it grants nothing — the property the whole stage rests on
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_override_never_claims_authority():
    ov = SO.load(RECORD)
    assert ov.grants_orders is False
    assert ov.satisfies_shadow_evidence is False
    assert ov.is_parameter_promotion is False
    assert ov.is_evidence_promotion is False


def test_the_gates_do_not_import_this_module():
    """Measured before the module existed: the gate source mentioned no swing override at all.
    It must stay that way - a gate that could read this record could be made to honour it."""
    import inspect

    src = inspect.getsource(G)
    for token in ("track1_swing_paper_override", "swing_paper_override", "SWING_TF_PARAM"):
        assert token not in src, token


def test_orders_stay_impossible_with_the_record_present():
    ok, _ = G.may_enable_orders()
    assert ok is False
    assert "PAPER_SHADOW_EVIDENCE" in {b.id for b in G.blocking()}


def test_the_gate_answer_is_identical_with_and_without_the_record(tmp_path):
    """The strongest form available: move the record aside, ask again, put it back."""
    before_ok, _ = G.may_enable_orders()
    before_blocking = sorted(b.id for b in G.blocking())
    assert RECORD.exists()

    stash = tmp_path / "moved.json"
    shutil.move(str(RECORD), str(stash))
    try:
        assert SO.load(RECORD).valid is False
        without_ok, _ = G.may_enable_orders()
        without_blocking = sorted(b.id for b in G.blocking())
    finally:
        shutil.move(str(stash), str(RECORD))

    assert RECORD.exists(), "the record was not restored"
    assert (before_ok, before_blocking) == (without_ok, without_blocking), (
        "the gates changed when the override was removed; it is not inert")
    assert before_ok is False


def test_the_override_does_not_satisfy_shadow_evidence():
    from global_index import track1_paper_readiness as pr

    ready, _detail = pr.gate_measurement(str(REPO))
    assert ready is False
    assert "PAPER_SHADOW_EVIDENCE" in {b.id for b in G.blocking()}


def test_the_override_changes_no_parameter():
    from futures.basket import SWING_TF_PARAM

    assert SWING_TF_PARAM == {"ema_period": 30, "chandelier_atr_mult": 2.5, "max_hold_days": 5}
    src = (REPO / "global_index" / "track1_swing_paper_override.py").read_text(encoding="utf-8")
    for token in ("ema_period =", "SWING_TF_PARAM =", "chandelier_atr_mult ="):
        assert token not in src, token


def test_the_module_never_writes():
    """Same contract `track1_b1_decision` holds itself to: no write path at all."""
    import ast

    tree = ast.parse((REPO / "global_index" / "track1_swing_paper_override.py")
                     .read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            assert name not in {"write_text", "write_bytes", "mkdir", "unlink", "touch",
                                "rename", "dump"}, name
            if name == "open":
                lits = [a.value for a in node.args[1:2] if isinstance(a, ast.Constant)]
                assert not any("w" in str(v) or "a" in str(v) for v in lits), lits


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. paper scope, and agreement with the canonical baseline
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_paper_scope_has_all_four_sleeves_with_swing_as_an_override():
    s = SO.paper_scope(REPO)
    assert set(s["sleeves"]) == {"global_nkd", "roska4_stress", "roska4_calm", "roska4_swing"}
    for name, v in s["sleeves"].items():
        assert v["in_scope"] is True
        assert v["evidence"] == "pending", name
    sw = s["sleeves"]["roska4_swing"]
    assert sw["basis"] == "operator_override"
    assert sw["risk_accepted"] is True
    assert sw["evidence_promoted"] is False and sw["parameter_promoted"] is False
    for other in ("global_nkd", "roska4_stress", "roska4_calm"):
        assert s["sleeves"][other]["basis"] == "in_scope_by_route_design"
    assert s["grants_orders"] is False and s["satisfies_shadow_evidence"] is False


def test_paper_scope_falls_back_to_design_when_the_record_is_gone(tmp_path):
    s = SO.paper_scope(tmp_path)          # no record in an empty directory
    sw = s["sleeves"]["roska4_swing"]
    assert sw["in_scope"] is True
    assert sw["basis"] == "in_scope_by_route_design"
    assert sw["risk_accepted"] is False
    assert sw["override_valid"] is False and sw["override_reason"]


def test_the_record_agrees_with_the_canonical_baseline():
    assert CANON.exists()
    canon = json.loads(CANON.read_text(encoding="utf-8"))
    ov = SO.load(RECORD)
    selected = next(v for v in canon["part_c_variants"] if v["paper_selected"] is True)
    assert selected["effective_params"]["ema_period"] == 50
    assert selected["regime_basis"] == "causal D-1"
    assert ov.selected_identity == "D1_OLD_EFFECTIVE_EMA50"
    assert ov.regime_basis == "causal_d1"
    assert canon["swing_inclusion_is_operator_override"] is True
    assert canon["swing_inclusion_is_evidence_promotion"] is False
    assert ov.baseline_reference.endswith(CANON.name)


def test_same_day_swing_is_still_marked_not_live_tradable():
    canon = json.loads(CANON.read_text(encoding="utf-8"))
    same_day = next(v for v in canon["part_c_variants"] if v["id"] == 1)
    assert same_day["live_tradable"] is False
    assert same_day["paper_selected"] is False


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. the operator can see it
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_readiness_report_shows_the_override_with_its_caveats():
    from global_index import track1_paper_readiness as pr

    text = pr.report(str(REPO))
    assert "SWING PAPER SCOPE" in text
    assert "included by operator risk acceptance" in text
    assert "NOT a parameter promotion" in text
    assert "does not satisfy PAPER_SHADOW_EVIDENCE" in text
    for caveat in SO.REQUIRED_CAVEATS:
        assert caveat in text, caveat


def test_the_override_is_shown_above_the_legacy_b1_block():
    """'Do not bury this under legacy' - asserted by position, not by intention."""
    from global_index import track1_paper_readiness as pr

    text = pr.report(str(REPO))
    i = text.index("SWING PAPER SCOPE")
    j = text.find("B1")
    assert j == -1 or i < j, "the override is rendered below the B1 block"
