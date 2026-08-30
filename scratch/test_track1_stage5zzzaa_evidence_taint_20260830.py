"""Stage 5ZZZ-AA — contaminated runtime rows are quarantined, not deleted and not scored.

The rows this covers were written by a test run that was not output-isolated. They stay on
disk, because append-only evidence is not rewritten; what changes is that readers know not to
believe them. These tests pin both halves: the rows are still there, and they count for
nothing.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_evidence_taint as TAINT      # noqa: E402
from global_index import track1_replay_parity as PARITY      # noqa: E402
from global_index import track1_signals as SIG               # noqa: E402

SIGNALS = REPO / "global_index/track1_runtime/signals/track1_signals_20260829.jsonl"
TAINT_FILE = REPO / "global_index/track1_runtime/evidence_taint/evidence_taint_20260829.jsonl"


def _lines(p):
    return [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# ═══════════════════════════════════════════════════════════════════════════════════════
# 1. the record exists and identifies the rows
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_taint_record_exists_and_is_append_only():
    assert TAINT_FILE.exists()
    recs = [json.loads(l) for l in _lines(TAINT_FILE)]
    assert recs, "empty taint record would make every check below vacuous"
    for r in recs:
        assert r["schema"] == TAINT.SCHEMA
        assert r["append_only"] is True
        assert r["taint_type"] == "TEST_CONTAMINATION"
        assert r["evidence_deleted"] == 0
        assert r["evidence_rows_rewritten"] == 0


def test_the_contaminated_rows_are_matched_by_the_record():
    assert SIGNALS.exists(), "the contaminated evidence file must NOT have been deleted"
    lines = _lines(SIGNALS)
    assert len(lines) == 2, f"expected the 2 known rows, found {len(lines)}"
    for l in lines:
        assert TAINT.is_tainted(l, REPO), "a known contaminated row is not matched"


def test_the_match_is_by_exact_row_hash_not_a_loose_predicate():
    """A predicate could widen to a future legitimate row. A hash cannot."""
    lines = _lines(SIGNALS)
    for l in lines:
        assert TAINT.row_hash(l) == hashlib.sha256(l.encode("utf-8")).hexdigest()
    # a row that merely looks similar is NOT tainted
    similar = json.dumps({"session_date": "2026-08-31", "sleeve": "roska4_swing",
                          "slot_id": "TRACK1_SWING_1405", "mode": "shadow_live"})
    assert not TAINT.is_tainted(similar, REPO), \
        "a different row matching the human-readable predicate was tainted"


def test_a_tainted_row_can_say_why():
    rec = TAINT.taint_for(_lines(SIGNALS)[0], REPO)
    assert rec and rec["taint_id"] == "5ZZZ-AA-20260830-001"
    assert rec["proof_not_live_slot_evidence"], "a taint with no proof is an assertion"
    assert any("SATURDAY" in p.upper() for p in rec["proof_not_live_slot_evidence"])


def test_files_touched_but_unproven_are_recorded_and_NOT_tainted():
    """Marking rows that might be real would be the same falsification in the other
    direction, so the three observation files are named as touched, not tainted."""
    touched = TAINT.touched_files(REPO)
    assert len(touched) == 3
    for f in touched:
        assert "data_observation" in f
        assert not any(TAINT.is_tainted(l, REPO) for l in _lines(REPO / f)), \
            "an unproven row was tainted"


# ═══════════════════════════════════════════════════════════════════════════════════════
# 2. what the readers now do
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_parity_never_scores_a_tainted_row_pass_or_fail():
    r = PARITY.parity(REPO)
    verdicts = {k: v["verdict"] for k, v in r["sleeves"].items()}
    assert verdicts, "no sleeves - would pass on nothing"
    assert PARITY.FAIL not in verdicts.values(), verdicts
    assert PARITY.PASS not in verdicts.values(), verdicts


def test_the_swing_false_fail_is_gone():
    """Before the quarantine this read FAIL, from a slot that never ran."""
    r = PARITY.parity(REPO)
    assert r["sleeves"]["roska4_swing"]["verdict"] == PARITY.NOT_YET, \
        r["sleeves"]["roska4_swing"]["verdict"]


def test_tainted_rows_are_surfaced_not_hidden():
    """An excluded row that is invisible is indistinguishable from a row that never existed."""
    r = PARITY.parity(REPO)
    t = r["tainted_test_evidence"]
    assert t["verdict"] == TAINT.TAINTED == "TAINTED_TEST_EVIDENCE"
    assert t["rows"] == 2
    assert t["excluded_from_parity_and_evidence"] is True
    assert t["never_scored_pass_or_fail"] is True
    assert all(d["taint_id"] for d in t["detail"])


def test_newest_slot_skips_tainted_rows():
    row = PARITY.newest_slot(REPO, "roska4_swing")
    if row is not None:
        assert not row.get("_tainted")
        assert row.get("session_date") != "2026-08-29"


def test_a_clean_row_still_counts():
    """The exclusion must be surgical: untainted rows are still selected normally."""
    rows = [r for r in PARITY.live_rows(REPO) if not r.get("_tainted")]
    assert rows, "every row was tainted - the filter is too wide"
    assert any(r.get("sleeve") == "roska4_swing" for r in rows), \
        "Swing lost all of its clean history"


def test_paper_shadow_evidence_is_unchanged_by_the_contamination():
    from global_index import track1_paper_readiness as PR

    days = PR.day_verdicts()
    assert "2026-08-29" not in days, \
        "the contaminated Saturday entered the judgeable window"
    assert set(days) == {"2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"}


# ═══════════════════════════════════════════════════════════════════════════════════════
# 3. recurrence prevention
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_a_test_cannot_write_the_production_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "x::y")
    monkeypatch.delenv(SIG.ALLOW_TEST_WRITE_ENV, raising=False)
    with pytest.raises(SIG.SignalJournalRefused):
        SIG._refuse_production_write_under_pytest(
            REPO / "global_index/track1_runtime/signals/track1_signals_20261231.jsonl")


def test_the_guard_does_not_break_a_test_writing_to_tmp_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "x::y")
    SIG._refuse_production_write_under_pytest(tmp_path / "signals" / "s.jsonl")


def test_the_guard_does_not_break_the_scheduler(monkeypatch):
    """The scheduler does not run under pytest and must be unaffected."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    SIG._refuse_production_write_under_pytest(
        REPO / "global_index/track1_runtime/signals/track1_signals_20261231.jsonl")


def test_a_deliberate_integration_write_can_opt_in(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "x::y")
    monkeypatch.setenv(SIG.ALLOW_TEST_WRITE_ENV, "1")
    SIG._refuse_production_write_under_pytest(
        REPO / "global_index/track1_runtime/signals/track1_signals_20261231.jsonl")


# ═══════════════════════════════════════════════════════════════════════════════════════
# 4. nothing was destroyed, nothing was armed
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_no_runtime_evidence_was_deleted_or_rewritten():
    assert SIGNALS.exists()
    assert len(_lines(SIGNALS)) == 2, "the contaminated rows were removed - they must remain"
    for f in TAINT.touched_files(REPO):
        assert (REPO / f).exists()


def test_the_taint_record_grants_nothing():
    s = TAINT.summary(REPO)
    assert s["grants_nothing"] is True
    src = (REPO / "global_index/track1_gates.py").read_text(encoding="utf-8")
    assert "track1_evidence_taint" not in src, \
        "the order gate now depends on a taint record"


def test_orders_remain_impossible():
    from global_index import track1_gates as G

    ok, _ = G.may_enable_orders()
    assert ok is False
    assert "PAPER_SHADOW_EVIDENCE" in {b.id for b in G.blocking()}
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not os.environ.get("TRACK1_ORDERS_APPROVED")


def test_the_taint_module_makes_no_broker_or_network_call():
    import ast

    tree = ast.parse((REPO / "global_index/track1_evidence_taint.py").read_text(encoding="utf-8"))
    banned = {"ib_insync", "socket", "requests", "urllib", "subprocess"}
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            names.add((n.module or "").split(".")[0])
    assert not (names & banned), names & banned
