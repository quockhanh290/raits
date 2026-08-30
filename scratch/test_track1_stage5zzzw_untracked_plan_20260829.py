"""Stage 5ZZZ-W - the untracked archive plan is safe to apply, and nothing moved.

The plan's whole value is the guarantees it makes about what may be moved. Each one is checked
here against the plan itself, so a later apply stage can be gated on this suite going green.
"""
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PLAN = REPO / "scratch" / "track1_stage5zzzw_untracked_archive_plan_20260829.json"
PROTECTED = {"CANONICAL_DOC", "DECISION_RECORD", "RUNTIME_EVIDENCE", "TEST_ARTIFACT",
             "ACTIVE_SOURCE"}


@pytest.fixture(scope="module")
def plan():
    assert PLAN.exists(), "the plan is missing"
    return json.loads(PLAN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def moves(plan):
    m = [r for r in plan["entries"] if r["action"] == "MOVE_CANDIDATE"]
    assert m, "no move candidates; every loop below would pass on nothing"
    return m


# ═══════════════════════════════════════════════════════════════════════════════════════
# 1. the plan covers what it claims to
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_plan_covers_every_untracked_file(plan):
    untracked = [t for t in subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=REPO,
        capture_output=True, text=True, check=True).stdout.split("\n") if t.strip()]
    planned = {r["path"] for r in plan["entries"]}
    missing = [u for u in untracked if u not in planned and (REPO / u).is_file()]
    assert not missing, f"{len(missing)} untracked file(s) absent from the plan: {missing[:5]}"


def test_every_entry_has_a_classification_action_reason_and_hash(plan):
    allowed_cls = {"CANONICAL_DOC", "DECISION_RECORD", "RUNTIME_EVIDENCE", "STAGE_REPORT",
                   "SUPPORTING_PROOF", "RESEARCH_ONLY", "REJECTED_RESEARCH", "TEST_ARTIFACT",
                   "GENERATED_TEMP", "UNKNOWN_KEEP", "ACTIVE_SOURCE"}
    for r in plan["entries"]:
        assert r["classification"] in allowed_cls, r
        assert r["action"] in ("KEEP", "MOVE_CANDIDATE", "IGNORE_NON_TRACK1"), r
        assert r["reason"], r["path"]
        assert re.fullmatch(r"[0-9a-f]{64}", r["sha256"]), r["path"]
        assert r["tracked"] is False


# ═══════════════════════════════════════════════════════════════════════════════════════
# 2. what may never be a move candidate
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_no_protected_class_is_a_move_candidate(moves):
    bad = [r for r in moves if r["classification"] in PROTECTED]
    assert not bad, [r["path"] for r in bad[:5]]


def test_no_linked_file_is_a_move_candidate(moves):
    bad = [r for r in moves if r["link_update_required"]]
    assert not bad, [r["path"] for r in bad[:5]]


def test_no_active_test_imports_a_move_candidate(moves):
    """The raits_vs_hold failure mode, asserted rather than hoped for."""
    stems = {Path(r["path"]).stem for r in moves if r["path"].endswith(".py")}
    imported = set()
    files = (list((REPO / "scratch").glob("test_*.py"))
             + list((REPO / "tests").rglob("test_*.py"))
             + list((REPO / "monitor").glob("test_*.py")))
    assert files, "no test files found; this check would pass on nothing"
    for t in files:
        for m in re.findall(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)",
                            t.read_text(encoding="utf-8", errors="ignore"), re.M):
            imported.add(m.split(".")[0])
    assert imported, "no imports parsed at all; the regex is broken"
    clash = stems & imported
    assert not clash, f"a test imports these move candidates: {sorted(clash)}"


def test_the_uncommitted_track1_source_is_kept(plan):
    src = [r for r in plan["entries"]
           if r["classification"] == "ACTIVE_SOURCE" and r["is_track1"]]
    assert src, "no Track 1 source classified; the check would pass on nothing"
    for r in src:
        assert r["action"] == "KEEP", r["path"]


# ═══════════════════════════════════════════════════════════════════════════════════════
# 3. the destinations are safe
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_every_destination_is_under_the_repo_archive_convention(moves):
    for r in moves:
        assert r["proposed_archive_path"].startswith("_archive/"), r["path"]


def test_no_destination_collides(moves):
    """A flat archive dir collided on two shadow_*_vault2026.jsonl pairs; one would have
    silently overwritten the other."""
    dests = [r["proposed_archive_path"] for r in moves]
    dupes = {d: c for d, c in Counter(dests).items() if c > 1}
    assert not dupes, dupes


def test_no_destination_exists_yet(moves):
    for r in moves:
        assert not (REPO / r["proposed_archive_path"]).exists(), r["proposed_archive_path"]


# ═══════════════════════════════════════════════════════════════════════════════════════
# 4. nothing moved
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_no_file_was_moved(plan):
    assert plan["files_moved"] == 0
    assert plan["plan_only"] is True


def test_every_planned_source_path_still_exists(plan):
    gone = [r["path"] for r in plan["entries"] if not (REPO / r["path"]).exists()]
    assert not gone, f"{len(gone)} planned path(s) no longer exist: {gone[:5]}"


def test_no_archive_destination_directory_was_created():
    assert not (REPO / "_archive" / "scratch" / "track1_2026-08-29").exists()


# ═══════════════════════════════════════════════════════════════════════════════════════
# 5. the version-control finding is recorded, not quietly dropped
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_uncommitted_route_finding_is_recorded(plan):
    f = plan["FINDING_the_track1_route_is_not_in_version_control"]
    assert f["measured"]["global_index_track1_py_tracked"] == 0
    assert f["measured"]["ever_committed_on_any_branch"] is False
    assert f["not_fixed_here"]


def test_the_finding_matches_what_git_says_right_now():
    """Measured live, so the plan cannot claim a state that has since changed."""
    tracked = subprocess.run(["git", "ls-files", "global_index/"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout
    assert not re.search(r"track1_\w+\.py", tracked), "track1 source is now tracked - update the plan"


def test_the_deliberately_ignored_paths_are_still_ignored():
    """The finding depends on telling 'ignored on purpose' from 'never added'."""
    for p in ("global_index/track1_runtime", "track1_go_live_confirmation.json"):
        r = subprocess.run(["git", "check-ignore", "-q", p], cwd=REPO)
        assert r.returncode == 0, f"{p} is no longer gitignored"


# ═══════════════════════════════════════════════════════════════════════════════════════
# 6. orders remain impossible
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_orders_remain_impossible():
    from global_index import track1_gates as G

    ok, _ = G.may_enable_orders()
    assert ok is False
    assert "PAPER_SHADOW_EVIDENCE" in {b.id for b in G.blocking()}
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
