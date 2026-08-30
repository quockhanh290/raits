"""Stage 5ZZZ-U - the canonical index says what the artifacts say, and never more.

An index is a description, and this repo's recurring failure is a description drifting away
from the thing it describes. So the numbers in the index are checked AGAINST the canonical
artifact rather than pinned as literals, and the dangerous sentences are checked for absence.
"""
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

INDEX = REPO / "docs" / "futures" / "TRACK1_BASELINE_INDEX_2026-08-29.md"
INVENTORY_MD = REPO / "scratch" / "track1_stage5zzzu_baseline_archive_inventory_20260829.md"
INVENTORY_JSON = REPO / "scratch" / "track1_stage5zzzu_baseline_archive_inventory_20260829.json"
CANON = REPO / "scratch" / "track1_stage5zzzn_canonical_strategy_baseline_reproduction_20260829.json"
OVERRIDE = REPO / "track1_swing_paper_override.json"


@pytest.fixture(scope="module")
def index_text():
    assert INDEX.exists(), f"the canonical index is missing at {INDEX}"
    return INDEX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def canon():
    return json.loads(CANON.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════════════════
# 1. the deliverables exist
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_canonical_index_exists():
    assert INDEX.exists()


def test_the_inventory_exists_in_both_forms():
    assert INVENTORY_MD.exists()
    assert INVENTORY_JSON.exists()
    data = json.loads(INVENTORY_JSON.read_text(encoding="utf-8"))
    assert data["counts"], "the inventory recorded no classifications"
    assert data["file_count"] > 100, data["file_count"]


# ═══════════════════════════════════════════════════════════════════════════════════════
# 2. the numbers match the artifact, rather than being retyped
# ═══════════════════════════════════════════════════════════════════════════════════════

def _money(text):
    return {int(m.replace(",", "")) for m in re.findall(r"\$([\d,]+)", text)}


def test_every_headline_number_in_the_index_comes_from_the_canonical_artifact(index_text, canon):
    """The index may not contain a headline figure the artifact does not support."""
    a = canon["part_a_historical_reference"]["results"]
    b = canon["part_b_live_tradable_selected"]["results"]
    expected = set()
    for res in (a, b):
        for win in ("floor", "vault2025", "vault2026"):
            for pol in ("full_stack", "risk_clean"):
                expected.add(round(res[win][pol]["net"]))
                expected.add(round(res[win][pol]["maxdd"]))
    assert expected, "nothing extracted from the artifact; this would pass on nothing"

    # every net figure the artifact records must appear in the index
    in_index = _money(index_text)
    for win in ("floor", "vault2025", "vault2026"):
        for pol in ("full_stack", "risk_clean"):
            for res in (a, b):
                net = round(res[win][pol]["net"])
                assert net in in_index, f"{net} missing from the index"


def test_the_swing_cluster_and_marginal_figures_are_both_present(index_text, canon):
    """Publishing only one of them is how the two get confused."""
    b = canon["part_b_live_tradable_selected"]["results"]
    nos = [v for v in canon["part_c_variants"]
           if v["name"] == "no-Swing control"][0]["full_stack_net"]
    money = _money(index_text)
    for win in ("floor", "vault2025", "vault2026"):
        cluster = round(abs(b[win]["full_stack"]["swing_pnl"]))
        marginal = round(abs(b[win]["full_stack"]["net"] - nos[win]))
        assert cluster in money, f"Swing cluster P&L {cluster} missing for {win}"
        assert marginal in money, f"Swing marginal {marginal} missing for {win}"


# ═══════════════════════════════════════════════════════════════════════════════════════
# 3. the labels that keep the two baselines apart
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_historical_baseline_is_marked_reference_only(index_text):
    assert "Reference only" in index_text
    assert "not live-tradable" in index_text


def test_the_selected_baseline_is_marked_live_tradable_and_operator_chosen(index_text):
    assert "Live-tradable selected paper baseline" in index_text
    assert "operator risk acceptance" in index_text
    assert "not evidence promotion" in index_text


def test_the_swing_identity_is_causal_d1_old_effective_ema50(index_text):
    assert "causal D-1 old/effective ema=50" in index_text
    ov = json.loads(OVERRIDE.read_text(encoding="utf-8"))
    assert ov["selected_identity"] == "D1_OLD_EFFECTIVE_EMA50"
    assert ov["regime_basis"] == "causal_d1"
    assert "D1_OLD_EFFECTIVE_EMA50" in index_text


def test_no_parameter_promotion_anywhere(index_text):
    ov = json.loads(OVERRIDE.read_text(encoding="utf-8"))
    assert ov["parameter_promotion"] is False
    assert ov["evidence_promotion"] is False
    assert "parameter_promotion   false" in index_text or "parameter_promotion" in index_text
    assert "WFO parameters retained" in index_text


# ═══════════════════════════════════════════════════════════════════════════════════════
# 4. sentences the index must never contain
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_index_never_says_same_day_swing_is_tradable(index_text):
    lowered = index_text.lower()
    for forbidden in ("same-day swing is live-tradable",
                      "same-day swing is tradable",
                      "same day swing is live tradable"):
        assert forbidden not in lowered, forbidden


def test_the_index_never_claims_orders_are_possible(index_text):
    lowered = index_text.lower()
    for forbidden in ("orders_possible: true", "orders_possible = true",
                      "orders_possible          true", "orders are possible",
                      "order activation approved"):
        assert forbidden not in lowered, forbidden
    assert "orders_possible          False" in index_text


def test_the_index_records_the_remaining_blocker(index_text):
    assert "PAPER_SHADOW_EVIDENCE" in index_text
    assert "still blocking" in index_text or "Remaining blocker" in index_text


# ═══════════════════════════════════════════════════════════════════════════════════════
# 5. the superseded / research classes are actually listed
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_index_lists_the_research_and_reference_classes(index_text):
    for cls in ("REFERENCE_ONLY", "RESEARCH_ONLY", "REJECTED_RESEARCH", "SUPPORTING_PROOF",
                "TEST_ARTIFACT", "DECISION_RECORD", "CANONICAL"):
        assert cls in index_text, cls


def test_the_named_superseded_items_are_called_out(index_text):
    for needle in ("5ZZZ-H", "5ZZZ-I", "5ZZZ-L", "5ZZZ-J", "5ZZZ-K", "5ZZZ-M",
                   "SUPERSEDED", "superseded by Stage 5ZZZ-M"):
        assert needle in index_text, needle


def test_the_inventory_classifies_every_file_it_lists():
    data = json.loads(INVENTORY_JSON.read_text(encoding="utf-8"))
    allowed = {"CANONICAL", "DECISION_RECORD", "RUNTIME_EVIDENCE", "REFERENCE_ONLY",
               "RESEARCH_ONLY", "REJECTED_RESEARCH", "SUPERSEDED", "INVALIDATED",
               "TEST_ARTIFACT", "SUPPORTING_PROOF"}
    rows = data["rows"]
    assert rows, "no rows; this test would pass on nothing"
    for r in rows:
        assert r["status"] in allowed, r
        if r["status"] not in ("CANONICAL", "DECISION_RECORD"):
            assert r["why_not_quote_directly"], r["path"]


def test_the_canonical_sources_named_by_the_index_all_exist(index_text):
    named = re.findall(r"`(scratch/[^`]+\.json|scratch/[^`]+\.md|track1_[a-z_]+\.json)`",
                       index_text)
    assert named, "no canonical sources named in the index"
    for n in set(named):
        assert (REPO / n).exists(), f"the index points at a file that does not exist: {n}"


# ═══════════════════════════════════════════════════════════════════════════════════════
# 6. orders remain impossible
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_orders_are_still_impossible():
    from global_index import track1_gates as G

    ok, _ = G.may_enable_orders()
    assert ok is False
    assert "PAPER_SHADOW_EVIDENCE" in {b.id for b in G.blocking()}
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
