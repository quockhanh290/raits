"""Read-time reinterpretation of stored Track 1 shadow-audit rows. Stage 5ZZZ-C.

WHY THIS EXISTS, AND WHY IT IS A SEPARATE MODULE
------------------------------------------------
Stage 5ZZZ-A removed a rule that had been failing every sleeve on every day since the operator
signed the B1 decision: the presence of the confirmation file. The rows it wrote are still on
disk and still say FAIL, and `track1_paper_readiness` keeps the LAST row for each
(scope, sleeve, day) — so on 2026-08-27 a real PASS for `global_nkd`, written when its window
closed, is overwritten by a later sweep whose only reason was the rule that no longer exists.

Two things must both be true, and they pull in opposite directions:

  * the stored evidence must not be edited. It is the record of what the audit said at the
    time, and a project that rewrites its own evidence when the policy changes has no evidence.
  * a reader must be able to see which stored failures were produced by a rule that has since
    been removed, or they will keep reading a FAIL that means nothing.

So this reports, and never writes. Every function here takes records and returns a description.

IT IS DELIBERATELY NOT ON THE GATE'S IMPORT PATH
------------------------------------------------
`track1_gates.shadow_evidence` -> `track1_paper_readiness.gate_measurement` -> `readiness`.
Nothing in that chain imports this module, and a test asserts it. Reinterpreting a stored
failure into a pass is exactly the kind of change that must be an operator's decision with the
reasoning in front of them, not a side effect of a reader someone wrote. The classification is
published so that decision can be made; it does not make it.

WHAT RE-EVALUATION CAN AND CANNOT ANSWER
-----------------------------------------
Re-running `evaluate_sleeve` on a past day answers some questions and cannot answer others, and
the difference is not a matter of taste. The checkpoint check reads `live_positions.track1.json`,
which is a SINGLE LIVE FILE overwritten on every run — measured on 2026-08-28 it carried
`cut_instant: 2026-08-28T10:02`, and there is no dated history of it anywhere in the tree. So
re-judging 2026-08-27 compares that day against today's book and reports `checkpoint_wrong_day`
every single time, for every past day, forever. That verdict is an artefact of when the question
was asked, not a finding about the day.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from global_index import track1_shadow_acceptance as acc

SCHEMA = "track1_audit_reinterpretation/1"

#: Reasons whose PRODUCING RULE has been removed from the code. A stored row carrying one of
#: these was failed by a rule that no longer exists, so the row cannot be read at face value.
#:
#: Not a convenience list: `test_every_stale_reason_is_really_gone_from_the_code` asserts that
#: each one is genuinely no longer appended anywhere in the acceptance module, so an entry that
#: became wrong would fail rather than quietly mislead.
STALE_REASONS: dict = {
    acc.R_CONFIRMATION_FILE: (
        "Stage 5ZZZ-A. The rule failed a shadow day because the B1 confirmation file existed. "
        "That was true when the signature was the last thing between this route and an order; "
        "since Stage 5S and Stage 5ZZK it records a DECISION, and whether an order could be "
        "sent is asked of the gate registry instead. No current code path produces this reason."
    ),
}

#: Reasons a re-evaluation cannot honestly answer for a PAST day, because the evidence they read
#: is a single live artefact with no history. Re-running the audit on such a day will report
#: these whatever happened at the time.
LIVE_ARTEFACT_REASONS: dict = {
    acc.R_CHECKPOINT_WRONG_DAY: (
        f"reads {acc.CHECKPOINT_BOOK_PATH}, a single live file overwritten on every run, so a "
        f"past day is compared against today's cut and always disagrees"
    ),
    acc.R_CHECKPOINT_DAY_UNVERIFIABLE: (
        f"reads {acc.CHECKPOINT_BOOK_PATH}, whose state for a past day cannot be recovered"
    ),
    acc.R_CHECKPOINT_BOOK_DISAGREEMENT: (
        f"compares the checkpoint against {acc.CHECKPOINT_BOOK_PATH} as it is NOW"
    ),
}


def classify_reasons(reasons) -> dict[str, Any]:
    """Split one stored row's reasons into those a reader may still take at face value.

    `solely_stale` is the question that matters for a FAIL row: was this row failed ONLY by a
    rule that has since been removed? If so its verdict says nothing about the day. If not, the
    standing reasons are what it still means, and they are listed rather than summarised.
    """
    reasons = list(reasons or [])
    stale = [r for r in reasons if r in STALE_REASONS]
    standing = [r for r in reasons if r not in STALE_REASONS]
    return {
        "reasons": reasons,
        "stale_reasons": stale,
        "standing_reasons": standing,
        "solely_stale": bool(stale) and not standing,
        "why_stale": {r: STALE_REASONS[r] for r in stale},
    }


def reevaluation_authority(reasons) -> dict[str, Any]:
    """Whether a re-evaluation's reasons can be read as findings about the day it names."""
    reasons = list(reasons or [])
    artefacts = [r for r in reasons if r in LIVE_ARTEFACT_REASONS]
    return {
        "artefact_reasons": artefacts,
        "authoritative": not artefacts,
        "why_not": {r: LIVE_ARTEFACT_REASONS[r] for r in artefacts},
    }


def reinterpret_day(day: str, root: str | Path = ".", *,
                    records: list | None = None) -> dict[str, Any]:
    """Everything known about one stored day, as description. Writes nothing.

    Three answers per sleeve, kept apart on purpose:

        stored          what the audit said at the time, byte for byte from the record
        classification  which of those reasons came from a rule that has since been removed
        reevaluated     what the current code says now, WITH whether that can be trusted
                        for a day this far in the past

    A reader that collapsed those into one verdict would be doing the thing this module exists
    to avoid — and would have to choose between two answers that are each right about a
    different question.
    """
    root = Path(root)
    if records is None:
        # Imported here, not at module scope, and the direction matters: THIS module reads the
        # readiness reader, never the other way round. `track1_gates.shadow_evidence` reaches
        # `track1_paper_readiness` and stops there.
        from global_index import track1_paper_readiness as _pr
        rows = _pr.audit_records(root)
    else:
        rows = records
    mine = [r for r in rows
            if not r.get("__unreadable__")
            and r.get("route") == acc.AUDIT_ROUTE
            and r.get("session_day") == day
            and r.get("scope") == "sleeve"]

    # The same rule `track1_paper_readiness._authoritative` applies: the LAST row for a
    # (sleeve, day) is the one that counts. Restating it here rather than importing it would be
    # a second copy of a rule, so the ordering is taken from the records as read.
    last: dict = {}
    for rec in mine:
        last[rec.get("sleeve")] = rec

    out: dict = {}
    for sleeve, rec in sorted(last.items()):
        stored_reasons = rec.get("reasons") or []
        classification = classify_reasons(stored_reasons)
        try:
            fresh = acc.evaluate_sleeve(day, sleeve, root)
            fresh_reasons = fresh.get("reasons") or []
            reeval = {"verdict": fresh.get("verdict"), "reasons": fresh_reasons,
                      "error": None, **reevaluation_authority(fresh_reasons)}
        except Exception as exc:                                       # noqa: BLE001
            reeval = {"verdict": None, "reasons": [], "artefact_reasons": [],
                      "authoritative": False, "why_not": {},
                      "error": f"{type(exc).__name__}: {exc}"}
        out[sleeve] = {
            "stored": {"verdict": rec.get("verdict"), "reasons": stored_reasons,
                       "rows_for_this_sleeve": sum(1 for r in mine
                                                   if r.get("sleeve") == sleeve)},
            "classification": classification,
            "reevaluated": reeval,
        }
    return {"schema": SCHEMA, "route": acc.AUDIT_ROUTE, "day": day,
            "sleeves": out,
            "note": ("report only — this module never writes, and nothing on "
                     "track1_gates.shadow_evidence's import path reads it")}
