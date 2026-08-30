"""What the route WOULD have ordered, written where nothing can mistake it for an order.

Stage 5ZX. Calm A decides from bars closed by 09:31 and transacts at the 10:00 OPEN — Stage
5ZV measured twenty-nine minutes between the two. That gap is what makes the sleeve tradable,
and it is also what splits its evidence in half:

    DECIDE    ~09:32   the setup, the direction, the size, the stop RULE and its inputs,
                       and an intent. No price, because no price exists yet.
    OBSERVE    10:02   the 10:00 OPEN, read from a bar that has closed, and only then the
                       planned stop LEVEL, which is that open minus 1.5 x ATR.

Why this is not the order journal
---------------------------------
FOUR readers treat the existence of `global_index/track1_runtime/orders/` as proof the route
has acted: `b1_book_repair` refuses to repair the book if it is there, `track1_paper_callsite`
guards the production root against it, `track1_report` reports NOT_PRODUCED while it is absent,
and the operator runbook says to stop and investigate if it appears.

A rehearsal written into that directory would make all four declare a route that traded on a
day it sent nothing — and it would block its own book repair. So a rehearsal gets its own
stream, and this module never learns the order journal's path.

What it may never contain
-------------------------
A fill, a fill time, a realised P&L or a slippage. Shadow sends nothing, so nothing filled.
Those four keys are written EXPLICITLY as null rather than omitted, because an absent key reads
as "this schema does not have that" and a null reads as "this run did not produce one" — and
only the second is true.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

SCHEMA = "track1_shadow_intent/1"

#: The stream. Deliberately not `orders/`, and deliberately not `shadow/`, which already holds
#: per-slot explanations — a reader counting rows there would start counting intents.
SHADOW_INTENT_DIR = "global_index/track1_runtime/shadow_intent"

ROUTE = "track1_candidate"
SLEEVE = "roska4_calm"

DECIDE = "DECIDE"
OBSERVE = "OBSERVE"
PHASES = (DECIDE, OBSERVE)

# ── statuses ────────────────────────────────────────────────────────────────
#: The phase ran and produced what it is for.
RECORDED = "RECORDED"
#: The phase ran and the sleeve did not set up. A real answer, not a failure.
NO_SETUP = "NO_SETUP"
#: The phase could not run. The reason code says why, and it is never a pass.
REFUSED = "REFUSED"
STATUSES = (RECORDED, NO_SETUP, REFUSED)

# ── reason codes ────────────────────────────────────────────────────────────
OK = "ok"
NO_CANDIDATE = "no_candidate"
GATE_REFUSED = "gate_refused"
NO_DECIDE_ROW = "no_decide_row_for_this_day"
NO_REFERENCE = "entry_reference_not_readable"
WRONG_PHASE_FIELD = "wrong_phase_field"

#: Fields a DECIDE row may carry. The stop RULE and its inputs are here; the stop LEVEL is not,
#: because Calm's stop is `entry - 1.5 x ATR` and the entry does not exist yet. Measured with
#: two entries and one ATR, the stop DISTANCE is identical either way and the dollar risk
#: cancels the entry out entirely — so everything about the stop except its level is knowable
#: at 09:31, and that is exactly what this list draws.
BEFORE_ENTRY_FIELDS = ("setup", "instrument", "direction", "qty", "stop_rule", "risk_inputs",
                       "entry_reference_time", "intent")

#: Fields only an OBSERVE row may carry.
AFTER_REFERENCE_FIELDS = ("entry_reference_price", "planned_stop")

#: Written as explicit nulls on every row. See the module docstring.
NEVER_IN_SHADOW = ("fill_price", "fill_time", "realised_pnl", "slippage")


class ShadowIntentRefused(Exception):
    """A row that would misrepresent what happened. Raised rather than written."""


@dataclass(frozen=True)
class IntentRow:
    phase: str
    slot_id: str
    session_date: str
    status: str
    reason_code: str
    data_identity: str = ""
    params_hash: str = ""
    decision_time: str = ""
    observed_time: str = ""
    before_entry: dict = field(default_factory=dict)
    after_reference: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.phase not in PHASES:
            raise ShadowIntentRefused(f"phase {self.phase!r} is not one of {PHASES}")
        if self.status not in STATUSES:
            raise ShadowIntentRefused(f"status {self.status!r} is not one of {STATUSES}")

        stray = sorted(set(self.before_entry) - set(BEFORE_ENTRY_FIELDS))
        if stray:
            raise ShadowIntentRefused(
                f"{stray} are not before-entry fields; before-entry is {BEFORE_ENTRY_FIELDS}")
        stray = sorted(set(self.after_reference) - set(AFTER_REFERENCE_FIELDS))
        if stray:
            raise ShadowIntentRefused(
                f"{stray} are not after-reference fields; after-reference is "
                f"{AFTER_REFERENCE_FIELDS}")

        # The rule this module exists for. A DECIDE row carrying a price is a price nothing
        # could have computed when that row was written.
        if self.phase == DECIDE and self.after_reference:
            raise ShadowIntentRefused(
                f"a {DECIDE} row carries {sorted(self.after_reference)}. Calm's stop is "
                f"entry - 1.5 x ATR and the entry is the 10:00 OPEN, so neither the reference "
                f"price nor the stop LEVEL exists when this row is written")
        # And the other direction: an OBSERVE row that RECORDED must actually carry the two
        # things it exists to add, or it is a row saying nothing.
        if self.phase == OBSERVE and self.status == RECORDED:
            missing = sorted(set(AFTER_REFERENCE_FIELDS) - set(self.after_reference))
            if missing:
                raise ShadowIntentRefused(
                    f"an {OBSERVE} row marked {RECORDED} is missing {missing}")
        if self.status == RECORDED and self.reason_code != OK:
            raise ShadowIntentRefused(
                f"{RECORDED} with reason {self.reason_code!r} — a recorded row has no reason "
                f"to give")
        if self.status != RECORDED and self.reason_code == OK:
            raise ShadowIntentRefused(f"{self.status} must name why, not report {OK!r}")

    def as_dict(self) -> dict:
        row = {"schema_version": SCHEMA, "route": ROUTE, "sleeve": SLEEVE, **asdict(self)}
        # Explicit nulls, always. An absent key says the schema has no such field; a null says
        # this run produced none, and only the second is true here.
        for k in NEVER_IN_SHADOW:
            row[k] = None
        return row


def decide_row(slot_id: str, session_date: str, *, status: str, reason_code: str,
               before_entry: dict | None = None, decision_time: str = "",
               data_identity: str = "", params_hash: str = "") -> IntentRow:
    return IntentRow(phase=DECIDE, slot_id=slot_id, session_date=session_date,
                     status=status, reason_code=reason_code,
                     decision_time=decision_time or _now(),
                     data_identity=data_identity, params_hash=params_hash,
                     before_entry=dict(before_entry or {}))


def observe_row(slot_id: str, session_date: str, *, status: str, reason_code: str,
                after_reference: dict | None = None, before_entry: dict | None = None,
                observed_time: str = "", data_identity: str = "",
                params_hash: str = "") -> IntentRow:
    return IntentRow(phase=OBSERVE, slot_id=slot_id, session_date=session_date,
                     status=status, reason_code=reason_code,
                     observed_time=observed_time or _now(),
                     data_identity=data_identity, params_hash=params_hash,
                     before_entry=dict(before_entry or {}),
                     after_reference=dict(after_reference or {}))


def planned_stop_from(entry_reference_price: float, atr: float, mult: float) -> float:
    """The stop LEVEL, and the only thing in this module that needs the entry.

    Kept here rather than recomputed by a caller so the OBSERVE row cannot be built from a
    different formula than the one the sleeve trades — and it delegates to the sleeve's own
    function rather than restating `entry - mult x atr`.
    """
    from global_index.track1_calm_a import CalmAParams, disaster_stop

    p = CalmAParams()
    if float(mult) != float(p.disaster_stop_atr_mult):
        raise ShadowIntentRefused(
            f"stop multiple {mult} is not the sleeve's {p.disaster_stop_atr_mult}")
    return float(disaster_stop(float(entry_reference_price), float(atr), p))


# ══════════════════════════════════════════════════════════════════════════════
# the stream
# ══════════════════════════════════════════════════════════════════════════════

def calm_params_identity() -> str:
    """A digest of the Calm parameters the intent was decided under. Stage 5ZX.

    Evidence that cannot say which rule produced it is weaker evidence. The signals channel
    has a field for this and it has been EMPTY since it was written — its reader guards on the
    parameters module offering a hash, and that module never has; the real one lives elsewhere
    and takes a whole configuration rather than a sleeve name. Two rows there compare equal
    because both are blank. That is recorded as a finding and deliberately not repaired from
    here, because repairing it changes what those rows contain.

    This stream computes its own, from the parameter object itself, so a later reader comparing
    two intents can tell whether the rule moved between them.
    """
    import dataclasses
    import hashlib

    from global_index.track1_calm_a import CalmAParams

    p = CalmAParams()
    fields = {f.name: repr(getattr(p, f.name)) for f in dataclasses.fields(p)}
    payload = json.dumps({"sleeve": SLEEVE, "fields": fields}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def path_for(root: str | Path = ".", day: str | None = None) -> Path:
    d = (day or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")).replace("-", "")
    return Path(root) / SHADOW_INTENT_DIR / f"shadow_intent_{d}.jsonl"


def append(row: IntentRow, *, root: str | Path = ".", day: str | None = None) -> Path:
    """One row, appended. The only thing this module writes, and never anywhere else."""
    p = path_for(root, day or row.session_date)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row.as_dict(), default=str) + "\n")
    return p


def read_day(root: str | Path = ".", day: str | None = None) -> list:
    p = path_for(root, day)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# what the evidence gate is allowed to conclude
# ══════════════════════════════════════════════════════════════════════════════

#: The day has both phases and they agree. The route WOULD have acted.
DECISION_JUDGEABLE = "decision_judgeable"
#: One phase ran and the other did not. Not a failure of the rule — a gap in the evidence.
INCOMPLETE = "incomplete"
#: No shadow-intent rows at all for a day the sleeve ran. Days before this stage shipped are
#: this, and they are NOT failures: nothing was writing the stream yet.
PRE_SCHEMA = "pre_shadow_intent_schema"
#: The sleeve looked and found nothing. A judgeable day with no trade in it.
NO_SETUP_DAY = "no_setup"

#: What shadow can NEVER conclude, named so a reader can see it is absent by design.
EXECUTION_PROVEN = "execution_proven"


def classify_day(rows: list) -> dict:
    """What a day's rows entitle the gate to say. Never `execution_proven`.

    Absence of rows is `pre_shadow_intent_schema`, not a failure: every Calm day before this
    stage shipped has none, and marking those FAIL would fabricate a bad record out of a
    feature that did not exist yet.
    """
    if not rows:
        return {"label": PRE_SCHEMA, "decide": None, "observe": None,
                "why": "no shadow-intent rows for this day; the stream did not exist yet"}

    decide = [r for r in rows if r.get("phase") == DECIDE]
    observe = [r for r in rows if r.get("phase") == OBSERVE]

    if any(r.get("phase") not in PHASES for r in rows):
        return {"label": INCOMPLETE, "decide": bool(decide), "observe": bool(observe),
                "why": "a row carries a phase this schema does not know"}
    if not decide:
        return {"label": INCOMPLETE, "decide": False, "observe": bool(observe),
                "why": "an OBSERVE row with no DECIDE before it — the decision it observes "
                       "was never recorded, so nothing here says the route would have acted"}
    if all(r.get("status") == NO_SETUP for r in decide):
        return {"label": NO_SETUP_DAY, "decide": True, "observe": bool(observe),
                "why": "the sleeve looked and no setup matched"}
    if any(r.get("status") == REFUSED for r in decide):
        return {"label": INCOMPLETE, "decide": True, "observe": bool(observe),
                "why": "the DECIDE phase refused: "
                       + ", ".join(sorted({r.get("reason_code", "?") for r in decide
                                           if r.get("status") == REFUSED}))}
    if not observe:
        return {"label": INCOMPLETE, "decide": True, "observe": False,
                "why": "the decision was recorded and the 10:00 reference never was"}
    if not any(r.get("status") == RECORDED for r in observe):
        return {"label": INCOMPLETE, "decide": True, "observe": True,
                "why": "the OBSERVE phase ran and recorded no reference: "
                       + ", ".join(sorted({r.get("reason_code", "?") for r in observe}))}
    return {"label": DECISION_JUDGEABLE, "decide": True, "observe": True,
            "why": "the route decided before 10:00 and the 10:00 reference was observed "
                   "afterwards. This says the route WOULD have acted; it says nothing about "
                   "whether an order would have been accepted or where it would have filled."}


def operator_line(verdict: dict) -> str:
    """One plain sentence for the readiness report."""
    return {
        DECISION_JUDGEABLE: "Calm decision evidence present.",
        NO_SETUP_DAY: "Calm decision evidence present — the sleeve found no setup.",
        INCOMPLETE: "Calm decision evidence incomplete.",
        PRE_SCHEMA: "Calm decision evidence missing — this day predates the shadow intent "
                    "stream.",
    }.get(verdict.get("label", ""), "Calm decision evidence could not be established.")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
