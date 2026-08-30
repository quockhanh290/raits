"""Stage 5ZZZ-C — what actually failed on 2026-08-27, once the stale reason stopped hiding it.

Stage 5ZZZ-A removed a rule that failed every sleeve on every day from the moment the operator
signed the B1 decision. The rows it wrote are still on disk, still saying FAIL, and the readiness
reader keeps the LAST row for each (scope, sleeve, day) — so a real PASS written when a window
closed is overwritten by a later sweep whose only reason was the rule that no longer exists.

This suite holds three things:

  * the classification of those stored rows is honest about which reasons still mean something
  * a re-evaluation is honest about which of ITS reasons it is entitled to make
  * neither of those touches what the order gate consumes

The third is the one that matters most. Reinterpreting a stored failure into a pass is exactly
the kind of change that must be an operator's decision, not a side effect of a reader.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_audit_reinterpretation as ri     # noqa: E402
from global_index import track1_gates as G                       # noqa: E402
from global_index import track1_paper_readiness as pr            # noqa: E402
from global_index import track1_shadow_acceptance as acc         # noqa: E402

DAY = "2026-08-27"
AUDIT_DIR = REPO / "global_index" / "track1_runtime" / "audits"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. the stale reason is genuinely gone, and the registry says so honestly
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_every_stale_reason_is_really_gone_from_the_code():
    """The registry claims these reasons are no longer produced. That claim is checked against
    the acceptance module rather than trusted, so an entry that became wrong fails here instead
    of quietly telling a reader to discount a live finding."""
    src = (REPO / "global_index" / "track1_shadow_acceptance.py").read_text(encoding="utf-8")
    assert ri.STALE_REASONS, "an empty registry would make every check below vacuous"
    for reason_const in ri.STALE_REASONS:
        name = next(n for n in dir(acc) if n.startswith("R_")
                    and getattr(acc, n) == reason_const)
        assert f"reasons.append({name})" not in src, (
            f"{name} is still appended by the acceptance module")


def test_a_reason_that_is_still_produced_is_not_registered_as_stale():
    """The complement. `R_ORDER_MARK` is very much alive, and a registry that swallowed it
    would tell a reader to ignore a record of an order."""
    assert acc.R_ORDER_MARK not in ri.STALE_REASONS
    assert acc.R_ORDER_GATE_NOT_BLOCKING not in ri.STALE_REASONS
    assert acc.R_COVERAGE_INCOMPLETE not in ri.STALE_REASONS


def test_classification_separates_stale_from_standing():
    out = ri.classify_reasons([acc.R_CONFIRMATION_FILE, acc.R_COVERAGE_INCOMPLETE])
    assert out["stale_reasons"] == [acc.R_CONFIRMATION_FILE]
    assert out["standing_reasons"] == [acc.R_COVERAGE_INCOMPLETE]
    assert out["solely_stale"] is False


def test_a_row_failed_only_by_the_removed_rule_is_marked_as_such():
    out = ri.classify_reasons([acc.R_CONFIRMATION_FILE])
    assert out["solely_stale"] is True
    assert out["why_stale"][acc.R_CONFIRMATION_FILE]


def test_a_row_with_no_stale_reason_is_not_marked_stale():
    out = ri.classify_reasons([acc.R_COVERAGE_INCOMPLETE, acc.R_HARD_REFUSAL])
    assert out["solely_stale"] is False
    assert out["stale_reasons"] == []


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. a re-evaluation says what it is entitled to say
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_checkpoint_book_is_a_single_live_file_with_no_history():
    """The fact the whole artefact classification rests on, asserted rather than described.

    `live_positions.track1.json` is rewritten on every run and carries one `cut_instant`. There
    is no dated copy of it anywhere, so a past day's checkpoint state cannot be recovered — and
    re-judging any past day compares it against TODAY's book.
    """
    book = REPO / acc.CHECKPOINT_BOOK_PATH
    assert book.exists()
    data = json.loads(book.read_text(encoding="utf-8"))
    assert "cut_instant" in data
    dated = [p for p in REPO.rglob("live_positions.track1*")
             if p.suffix not in (".bak",) and p != book]
    assert dated == [], f"a dated history exists after all: {dated}"


def test_a_checkpoint_wrong_day_from_a_reevaluation_is_not_authoritative():
    out = ri.reevaluation_authority([acc.R_CHECKPOINT_WRONG_DAY])
    assert out["authoritative"] is False
    assert out["artefact_reasons"] == [acc.R_CHECKPOINT_WRONG_DAY]
    assert out["why_not"][acc.R_CHECKPOINT_WRONG_DAY]


def test_a_reevaluation_without_artefact_reasons_is_authoritative():
    """The complement — otherwise the classifier could dismiss every re-evaluation."""
    out = ri.reevaluation_authority([acc.R_COVERAGE_INCOMPLETE,
                                     acc.R_HARD_REFUSAL])
    assert out["authoritative"] is True
    assert out["artefact_reasons"] == []


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. 2026-08-27, sleeve by sleeve
# ══════════════════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def day():
    return ri.reinterpret_day(DAY, REPO)


def test_calm_and_stress_failed_for_real_and_the_reevaluation_may_say_so(day):
    """The answer the stage exists to give. Both were recorded as failing only for the removed
    rule; both genuinely failed, and the re-evaluation that says so carries no artefact."""
    for sleeve in ("roska4_calm", "roska4_stress"):
        rec = day["sleeves"][sleeve]
        assert rec["classification"]["solely_stale"] is True, sleeve
        assert rec["reevaluated"]["authoritative"] is True, sleeve
        assert rec["reevaluated"]["verdict"] == "FAIL", sleeve
        assert acc.R_COVERAGE_INCOMPLETE in rec["reevaluated"]["reasons"], sleeve
        assert acc.R_HARD_REFUSAL in rec["reevaluated"]["reasons"], sleeve


def test_nkd_and_swing_cannot_be_rejudged_because_of_the_live_book(day):
    for sleeve in ("global_nkd", "roska4_swing"):
        rec = day["sleeves"][sleeve]
        assert rec["reevaluated"]["authoritative"] is False, sleeve
        assert acc.R_CHECKPOINT_WRONG_DAY in rec["reevaluated"]["artefact_reasons"], sleeve


def test_nkd_carries_a_standing_reason_that_is_not_a_failure(day):
    """Its stored row is not solely stale — it also says the window closed before the scheduler
    started, which is a not-judgeable note rather than a fault."""
    rec = day["sleeves"]["global_nkd"]
    assert rec["classification"]["solely_stale"] is False
    assert rec["classification"]["standing_reasons"] == [acc.R_CLOSED_BEFORE_SCHEDULER_START]


def test_the_stored_verdict_is_reported_verbatim_from_the_record(day):
    """The stored half must be the record, not a rendering of it.

    A reader that quietly showed the re-evaluated verdict under the `stored` heading would be
    editing the evidence in the one place a reader trusts it not to be edited - and it would be
    invisible on any day where the two verdicts happen to agree.
    """
    rows = [json.loads(l) for l in
            (AUDIT_DIR / "track1_audit_20260827.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    last = {}
    for r in rows:
        if r.get("scope") == "sleeve":
            last[r["sleeve"]] = r
    assert last, "no sleeve rows found - this check would prove nothing"
    for sleeve, rec in last.items():
        reported = day["sleeves"][sleeve]["stored"]
        assert reported["verdict"] == rec.get("verdict"), sleeve
        assert reported["reasons"] == (rec.get("reasons") or []), sleeve

    # Every sleeve happens to be FAIL on this day, in both the record and the re-evaluation, so
    # the loop above cannot tell a faithful report from one that substituted the re-evaluated
    # verdict. A synthetic record makes the two disagree by construction.
    synthetic = [{"route": acc.AUDIT_ROUTE, "session_day": DAY, "scope": "sleeve",
                  "sleeve": "roska4_calm", "verdict": "PASS",
                  "reasons": ["all_slots_observed_no_action"]}]
    out = ri.reinterpret_day(DAY, REPO, records=synthetic)["sleeves"]["roska4_calm"]
    assert out["stored"]["verdict"] == "PASS", out["stored"]
    assert out["reevaluated"]["verdict"] == "FAIL", (
        "precondition: the re-evaluation disagrees, or this proves nothing")


def test_nkd_had_a_real_pass_earlier_that_day_that_the_stale_row_overwrote():
    """The concrete cost of the removed rule, read straight out of the stored file."""
    rows = [json.loads(l) for l in
            (AUDIT_DIR / "track1_audit_20260827.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    nkd = [r for r in rows if r.get("scope") == "sleeve" and r.get("sleeve") == "global_nkd"]
    assert len(nkd) >= 2, nkd
    assert nkd[0]["verdict"] == "PASS", nkd[0]
    assert acc.R_CONFIRMATION_FILE in (nkd[-1].get("reasons") or []), nkd[-1]


def test_the_day_still_contains_real_failures_so_it_is_not_a_clean_day(day):
    """No amount of reclassification turns 2026-08-27 into a day that went well."""
    genuinely_failed = [s for s, rec in day["sleeves"].items()
                        if rec["reevaluated"]["authoritative"]
                        and rec["reevaluated"]["verdict"] == "FAIL"]
    assert sorted(genuinely_failed) == ["roska4_calm", "roska4_stress"], genuinely_failed


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. it reports, and never writes
# ══════════════════════════════════════════════════════════════════════════════════════════

def _audit_digest():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(AUDIT_DIR.glob("*.jsonl"))}


def test_reinterpretation_does_not_mutate_any_audit_file():
    before = _audit_digest()
    assert before, "no audit files found — this check would prove nothing"
    ri.reinterpret_day(DAY, REPO)
    ri.reinterpret_day("2026-08-26", REPO)
    assert _audit_digest() == before


def test_the_module_contains_no_write_call():
    src = (REPO / "global_index" / "track1_audit_reinterpretation.py").read_text(encoding="utf-8")
    for forbidden in ("write_text(", "open(", ".write(", "mkdir(", "unlink(", "rename("):
        assert forbidden not in src, forbidden


def test_the_order_gate_does_not_read_this_module():
    """The safety property. Reinterpreting a stored failure into a pass has to be an operator's
    decision with the reasoning in front of them, not something a reader does on its way past.

    Checked by import graph, not by reading the docstring that claims it.
    """
    for name in ("track1_gates.py", "track1_paper_readiness.py", "track1_shadow_acceptance.py"):
        src = (REPO / "global_index" / name).read_text(encoding="utf-8")
        assert "track1_audit_reinterpretation" not in src, name


def test_the_gate_still_refuses_and_says_why():
    released, detail = G.shadow_evidence(REPO)
    assert released is False
    assert "no_failing_days" in detail or "judgeable_days" in detail


def test_the_readiness_checks_are_unchanged_by_this_stage():
    """The four that fail today, named. If a later change moves one of them it should be a
    decision, and this is what makes it visible."""
    # Stage 5ZZZ-B: a SUBSET assertion, not an equality. The set was pinned exactly when this
    # was written and the day moved underneath it — `judgeable_days` clears the moment a fifth
    # day lands, which is a thing this project WANTS to happen. What the test is about is that
    # the evidence gate is still refusing and still refusing for measured reasons, and an equal
    # sign made it a tripwire for the passage of time instead.
    failing = {c["name"] for c in pr.readiness(REPO)["checks"] if c["status"] != "ok"}
    assert failing, "the evidence gate stopped refusing; that is a decision, not a test result"
    assert failing <= {"judgeable_days", "no_failing_days", "calm_decision_evidence",
                       "every_sleeve_passed_at_least_once", "evidence_is_recent",
                       "warn_days_within_allowance", "audit_records_readable",
                       "paper_account_baseline"}, failing
    assert "no_failing_days" in failing or "judgeable_days" in failing, failing


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. nothing was armed
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_orders_remain_impossible():
    allowed, reasons = G.may_enable_orders()
    assert allowed is False
    assert "PAPER_SHADOW_EVIDENCE" in [r.split(":")[0] for r in reasons]


def test_no_order_artefacts_and_the_decision_is_intact():
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not (REPO / "global_index" / "live_positions.track1.json").exists()
    conf = REPO / acc.CONFIRMATION_PATH
    assert conf.exists()
    assert (json.loads(conf.read_text(encoding="utf-8")).get("confirmed_by") or "").strip()
