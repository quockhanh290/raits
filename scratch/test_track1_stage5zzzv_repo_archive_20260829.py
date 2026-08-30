"""Stage 5ZZZ-V - the archive plan, the history report, and the claim that nothing moved.

The operator chose to archive nothing this stage, so "no file moved" is a claim like any other
and is checked here rather than asserted: every path the plan lists must still be exactly where
the plan says it is, and every link in the canonical docs must resolve.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PLAN = REPO / "scratch" / "track1_stage5zzzv_repo_archive_plan_20260829.json"
HISTORY = REPO / "docs" / "futures" / "TRACK1_BASELINE_HISTORY_2026-08-29.md"
INDEX = REPO / "docs" / "futures" / "TRACK1_BASELINE_INDEX_2026-08-29.md"
PIPELINE = REPO / "docs" / "futures" / "TRACK1_RUNTIME_PIPELINE_2026-08-24.md"


@pytest.fixture(scope="module")
def plan():
    assert PLAN.exists(), "the pre-move plan is missing"
    return json.loads(PLAN.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════════════════
# 1. the plan is well formed
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_plan_parses_and_covers_every_tracked_file(plan):
    tracked = [t for t in subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                                         text=True, check=True).stdout.split("\n") if t.strip()]
    assert plan["tracked_total"] == len(tracked), (plan["tracked_total"], len(tracked))
    assert len(plan["entries"]) == len(tracked)


def test_every_entry_carries_a_classification_and_a_reason(plan):
    allowed = {"ACTIVE_SOURCE", "ACTIVE_TEST", "ACTIVE_DOC", "CANONICAL_DOC", "DECISION_RECORD",
               "RUNTIME_EVIDENCE", "BASELINE_CANONICAL", "BASELINE_REFERENCE_ONLY",
               "RESEARCH_REPORT", "REJECTED_RESEARCH", "SUPPORTING_PROOF", "STAGE_REPORT",
               "TEST_ARTIFACT", "GENERATED_TEMP", "UNKNOWN_KEEP"}
    assert plan["entries"], "empty plan would pass every loop below on nothing"
    for e in plan["entries"]:
        assert e["classification"] in allowed, e
        assert e["reason"], e["path"]
        assert e["action"] in ("KEEP", "DEFERRED_CANDIDATE"), e


def test_a_deferred_candidate_still_carries_its_pre_move_hash(plan):
    """If archiving resumes later, the hashes recorded now are the before-side of the proof."""
    deferred = [e for e in plan["entries"] if e["action"] == "DEFERRED_CANDIDATE"]
    assert deferred, "no deferred candidates recorded"
    for e in deferred:
        assert re.fullmatch(r"[0-9a-f]{64}", e["sha256_before"]), e["path"]
        assert e["proposed_new_path"].startswith("_archive/")


# ═══════════════════════════════════════════════════════════════════════════════════════
# 2. nothing actually moved
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_no_file_was_moved(plan):
    assert plan["operator_decision"]["files_moved"] == 0
    assert plan["proposed_moves"] == 0


def test_every_path_in_the_plan_is_still_where_the_plan_says(plan):
    missing = [e["path"] for e in plan["entries"] if not (REPO / e["path"]).exists()]
    assert not missing, f"{len(missing)} tracked path(s) are gone: {missing[:5]}"


def test_the_hashes_of_the_deferred_candidates_are_unchanged(plan):
    import hashlib

    deferred = [e for e in plan["entries"] if e["action"] == "DEFERRED_CANDIDATE"]
    assert deferred
    for e in deferred:
        now = hashlib.sha256((REPO / e["path"]).read_bytes()).hexdigest()
        assert now == e["sha256_before"], e["path"]


def test_no_new_archive_root_was_created():
    """The operator chose the repo's existing convention, so the brief's roots must not exist."""
    for p in ("docs/archive/track1/2026-08-29", "scratch/archive/track1/2026-08-29",
              "tests/archive/track1/2026-08-29"):
        assert not (REPO / p).exists(), f"a second archive convention was created at {p}"


def test_the_repo_convention_is_the_one_recorded(plan):
    assert plan["archive_root_used"].startswith("_archive/")
    assert (REPO / "docs" / "futures" / "ARCHIVE_LOG.md").exists()


# ═══════════════════════════════════════════════════════════════════════════════════════
# 3. the canonical docs and their links
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_history_report_exists_and_covers_the_required_sections():
    assert HISTORY.exists()
    text = HISTORY.read_text(encoding="utf-8")
    for needle in ("original Track 1 candidate baseline", "shadow isolation",
                   "legacy retirement", "two-phase", "dashboard diagnostics",
                   "same-day problem", "old/effective ema=50", "full grid",
                   "proxies", "parameter translation", "operator override",
                   "Canonical numbers to quote", "before paper activation"):
        assert needle.lower() in text.lower(), needle


def test_the_history_and_index_link_to_each_other_and_the_links_resolve():
    hist = HISTORY.read_text(encoding="utf-8")
    assert "TRACK1_BASELINE_INDEX_2026-08-29.md" in hist
    for md in (HISTORY, INDEX):
        for link in re.findall(r"\]\(([^)]+\.md)\)", md.read_text(encoding="utf-8")):
            if link.startswith("http"):
                continue
            target = (md.parent / link).resolve()
            assert target.exists(), f"{md.name} links to a missing file: {link}"


def test_the_canonical_docs_all_exist():
    for p in (HISTORY, INDEX, PIPELINE, REPO / "TASK.md",
              REPO / "track1_go_live_confirmation.json",
              REPO / "track1_swing_paper_override.json"):
        assert p.exists(), p


# ═══════════════════════════════════════════════════════════════════════════════════════
# 4. what the docs may never say
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_no_canonical_doc_claims_orders_are_possible():
    for md in (HISTORY, INDEX):
        low = md.read_text(encoding="utf-8").lower()
        for forbidden in ("orders_possible: true", "orders_possible = true",
                          "orders are possible", "order activation approved"):
            assert forbidden not in low, (md.name, forbidden)
        assert "orders_possible          False" in md.read_text(encoding="utf-8")


def test_same_day_swing_is_still_marked_not_live_tradable():
    for md in (HISTORY, INDEX):
        text = md.read_text(encoding="utf-8")
        assert "not live-tradable" in text, md.name
        assert "same-day swing is live-tradable" not in text.lower()


def test_the_selected_swing_identity_is_unchanged():
    ov = json.loads((REPO / "track1_swing_paper_override.json").read_text(encoding="utf-8"))
    assert ov["selected_identity"] == "D1_OLD_EFFECTIVE_EMA50"
    assert ov["regime_basis"] == "causal_d1"
    assert ov["parameter_promotion"] is False
    for md in (HISTORY, INDEX):
        assert "old/effective ema=50" in md.read_text(encoding="utf-8"), md.name


def test_the_history_publishes_both_swing_figures():
    """Cluster P&L and marginal add are different questions; publishing one alone invites the
    confusion Stage 5ZZZ-U found in the hand-off."""
    text = HISTORY.read_text(encoding="utf-8")
    for n in ("18,429", "3,906", "464", "17,382", "3,804", "626"):
        assert n in text, n


# ═══════════════════════════════════════════════════════════════════════════════════════
# 5. nothing about the route changed
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_orders_remain_impossible():
    from global_index import track1_gates as G

    ok, _ = G.may_enable_orders()
    assert ok is False
    assert "PAPER_SHADOW_EVIDENCE" in {b.id for b in G.blocking()}
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
