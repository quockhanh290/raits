"""global_index/track1_broker_read.py — the broker read side, made tri-state. NEW FILE.

Stage 5X. Pure. No `ib_insync`, no connection, no order, and nothing here writes anything.
It wraps a broker object and answers three questions — what do you hold, what orders are
working, what happened to this one — in a form that can say **"I do not know"**.

Why this exists
---------------
`broker.py` already states the house convention, in `get_working_stops`:

    Returns None only when this broker is offline (test mode), never {} — the caller must
    be able to tell "nothing working" from "cannot say".

Three of the read methods on `IBKRBroker` do not follow it, and each collapses a different
pair of facts into one value:

    get_positions()        an unsettled subscription returns the LAST read with a warning,
                           so "I could not settle" arrives looking like "here is what I hold"
    get_order_status()     `except Exception -> "NOT_FOUND"`, so "I could not ask" arrives
                           looking like "that order does not exist"
    find_execution()       returns None for not-found, for any error, AND for "two executions
                           match and nothing distinguishes them" — three facts, one value

For the legacy route those are deliberate and load-bearing: `runner.py` reads all three and
its B3/B4 logic is built on what they return today. **This module changes none of them.** It
sits above them and re-labels their answers for Track 1, where the same collapse points the
other way: `NOT_FOUND` for a legacy stop means "treat as mismatch", which is conservative,
while `NOT_FOUND` for an entry this route just submitted would read as "it never reached the
broker" — which is the opposite of conservative.

`NoOrderBroker.get_positions()` returns `[]`, which in shadow means "never asked", not "flat".
It is marked `CAN_TESTIFY = False` rather than having its return changed, because several
suites construct it and `[]` is what they expect.

The rule, in one line
---------------------
**An answer this module cannot stand behind is UNKNOWN, and UNKNOWN blocks entries.** It does
not block exits that reduce exposure — a position you cannot account for is a position you
should be allowed to close.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from global_index import track1_order_state as st

#: The two states any read can be in. There is no third: a value is either one this module
#: will stand behind, or it is not.
KNOWN = "known"
UNKNOWN = "unknown"

#: Why an answer could not be trusted. Named so a refusal is a value a test asserts, not a
#: message it has to match.
NO_METHOD = "broker_has_no_such_method"
CANNOT_TESTIFY = "broker_cannot_testify"
READ_RAISED = "broker_read_raised"
AMBIGUOUS = "broker_answer_is_ambiguous"
UNSETTLED = "broker_read_did_not_settle"

#: `get_order_status` returns this string for three different situations, only one of which
#: is "the broker looked and it is not there".
STATUS_NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True)
class Answer:
    """A broker read, with whether it can be relied on kept beside the value.

    `value` is meaningless unless `state == KNOWN`. It is still carried when UNKNOWN so a
    report can show what was seen without anything being allowed to act on it.
    """

    state: str
    value: Any = None
    detail: str = ""

    @property
    def known(self) -> bool:
        return self.state == KNOWN

    @classmethod
    def unknown(cls, reason: str, detail: str = "", value: Any = None) -> "Answer":
        return cls(state=UNKNOWN, value=value, detail=f"{reason}: {detail}" if detail
                   else reason)


# ── what a given broker can honestly be asked ────────────────────────────────────────────

#: The read methods Track 1 wants, and the name each is actually spelled under today.
#:
#: Stage 5W listed `get_executions` as missing. That was measured against the wrong name and
#: is corrected here: `find_execution(order_id, inst)` EXISTS and does the job, and the
#: underlying `reqAllOpenOrders()` call that `get_open_orders` needs is already used at five
#: sites inside `ibkr_broker.py`. The gap was never the API surface.
READ_METHODS: tuple = ("get_positions", "get_open_orders", "get_order_status",
                       "find_execution")


def capability(broker: Any) -> dict:
    """Which reads this broker can answer, and whether it can testify at all. No call made."""
    testifies = bool(getattr(broker, "CAN_TESTIFY", True))
    return {
        "can_testify": testifies,
        "present": sorted(m for m in READ_METHODS if callable(getattr(broker, m, None))),
        "absent": sorted(m for m in READ_METHODS if not callable(getattr(broker, m, None))),
    }


# ── the reader ───────────────────────────────────────────────────────────────────────────

@dataclass
class Track1BrokerReader:
    """Tri-state reads over any broker object. Never writes, never orders, never connects."""

    broker: Any

    def _guard(self, name: str) -> "Answer | None":
        """The two refusals that apply before any call is attempted."""
        if not bool(getattr(self.broker, "CAN_TESTIFY", True)):
            return Answer.unknown(
                CANNOT_TESTIFY,
                f"{type(self.broker).__name__}.{name} answers from nothing; an empty answer "
                f"from a broker that was never connected means 'never asked', not 'flat'")
        if not callable(getattr(self.broker, name, None)):
            return Answer.unknown(NO_METHOD, f"{type(self.broker).__name__}.{name}")
        return None

    # ── what do you hold ────────────────────────────────────────────────
    def positions(self) -> Answer:
        """`Answer` carrying a list of `track1_order_state.Position`.

        An empty list is a real answer — flat is a position — but only from a broker that
        could have said otherwise.
        """
        refusal = self._guard("get_positions")
        if refusal is not None:
            return refusal
        try:
            raw = self.broker.get_positions()
        except Exception as exc:
            return Answer.unknown(READ_RAISED, f"get_positions: {type(exc).__name__}: {exc}")
        if raw is None:
            return Answer.unknown(CANNOT_TESTIFY, "get_positions returned None")
        out = []
        for p in raw:
            try:
                out.append(st.Position(instrument=str(p.inst),
                                       direction=str(p.direction).lower(),
                                       contracts=int(abs(int(p.contracts)))))
            except Exception as exc:
                return Answer.unknown(
                    AMBIGUOUS,
                    f"a position row could not be read ({type(exc).__name__}: {exc}); a book "
                    f"that is partly readable is not a book")
        return Answer(KNOWN, out, f"{len(out)} position(s)")

    # ── what is working ─────────────────────────────────────────────────
    def open_orders(self) -> Answer:
        """`Answer` carrying a list of open-order dicts.

        Following the `get_working_stops` convention exactly: `None` from the broker means
        "cannot say" and becomes UNKNOWN; `[]` means "nothing working" and is KNOWN.
        """
        refusal = self._guard("get_open_orders")
        if refusal is not None:
            return refusal
        try:
            raw = self.broker.get_open_orders()
        except Exception as exc:
            return Answer.unknown(READ_RAISED, f"get_open_orders: {type(exc).__name__}: {exc}")
        if raw is None:
            return Answer.unknown(CANNOT_TESTIFY, "get_open_orders returned None (offline)")
        return Answer(KNOWN, list(raw), f"{len(list(raw))} working order(s)")

    # ── what happened to this one ───────────────────────────────────────
    def order_status(self, order_id: str) -> Answer:
        """`FILLED` / `CANCELLED` / `PENDING` are KNOWN. `NOT_FOUND` is **UNKNOWN**.

        This is the single most important re-labelling in the module. `get_order_status`
        returns `NOT_FOUND` when it looked and found nothing AND when the call threw, and for
        the legacy route that conflation is safe because B3 escalates it. For an entry this
        route just submitted, "not found" would read as "never sent" — and acting on that
        means sending it again.
        """
        refusal = self._guard("get_order_status")
        if refusal is not None:
            return refusal
        if not str(order_id or ""):
            return Answer.unknown(
                AMBIGUOUS,
                "no order id to ask about; broker.Fill carries none, which is why the "
                "client-side idempotency key exists")
        try:
            status = str(self.broker.get_order_status(str(order_id)) or "")
        except Exception as exc:
            return Answer.unknown(READ_RAISED,
                                  f"get_order_status: {type(exc).__name__}: {exc}")
        if status == STATUS_NOT_FOUND or not status:
            return Answer.unknown(
                AMBIGUOUS,
                f"get_order_status returned {status or '(empty)'!r}, which this broker also "
                f"returns when the call failed; it cannot mean 'never sent' here")
        return Answer(KNOWN, status, f"order {order_id} is {status}")

    def execution(self, order_id: str, inst: "str | None" = None) -> Answer:
        """The fill record, or UNKNOWN.

        `find_execution` returns `None` for not-found, for any error, and for "two match and
        nothing distinguishes them". Those cannot be told apart from the outside, so None is
        UNKNOWN here — never "there was no fill".
        """
        refusal = self._guard("find_execution")
        if refusal is not None:
            return refusal
        if not str(order_id or ""):
            return Answer.unknown(AMBIGUOUS, "no order id to look up")
        try:
            found = self.broker.find_execution(str(order_id), inst)
        except Exception as exc:
            return Answer.unknown(READ_RAISED, f"find_execution: {type(exc).__name__}: {exc}")
        if found is None:
            return Answer.unknown(
                AMBIGUOUS,
                "find_execution returned None, which it also returns on error and on two "
                "indistinguishable matches; it cannot mean 'no fill happened'")
        return Answer(KNOWN, found, f"execution for order {order_id}")


# ── resolving one unresolved journal row ─────────────────────────────────────────────────

#: What a SUBMITTED row resolved to. Deliberately the same vocabulary as Stage 5U so a caller
#: never has to translate between two sets of words.
RESOLVED_FILLED = st.FILLED
RESOLVED_PARTIAL = st.PARTIAL
RESOLVED_REJECTED = st.REJECTED
RESOLVED_UNKNOWN = st.UNKNOWN
STILL_WORKING = "still_working"


@dataclass(frozen=True)
class SubmittedVerdict:
    """What the broker could tell us about one order we know we tried to send."""

    resolution: str
    blocks_entries: bool
    reasons: tuple = ()
    detail: str = ""
    evidence: dict = field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        return self.resolution in (RESOLVED_FILLED, RESOLVED_PARTIAL, RESOLVED_REJECTED)


def resolve_submitted(record: Any, reader: Track1BrokerReader, *,
                      order_id: str = "") -> SubmittedVerdict:
    """One journal row left at SUBMITTED, against what the broker will say.

    The order of questions is not arbitrary. Working orders first, because an order still
    on the book is the one case with an unambiguous answer and it settles the row without
    any inference. Executions second. Positions are consulted LAST and never on their own:
    a position that matches proves something was filled, but not that THIS order filled it.

    **REJECTED is only ever returned on a broker statement that says so.** Silence is never
    rejection. The whole reason this function exists is that the underlying methods answer
    silence and failure with the same value.

    Stage 5Y: the broker order id is preferred wherever it exists, and it now usually does —
    the receipt is journalled between placement and the fill poll. The id also settles the
    negative case: a working order whose id differs is NOT ours, and the weaker
    instrument-and-action match is not consulted afterwards. That fallback applies only when
    no id was ever recorded.
    """
    evidence: dict = {}
    inst = str(getattr(record, "instrument", "") or "")
    oid = str(order_id or getattr(record, "order_id", "") or "")

    evidence["identified_by"] = BY_ORDER_ID if oid else BY_INSTRUMENT_ACTION
    working = reader.open_orders()
    evidence["open_orders"] = working.detail
    if working.known:
        mine = [(o, how) for o in working.value
                for hit, how in [_matches(o, record, oid)] if hit]
        if mine:
            evidence["matched_by"] = mine[0][1]
            return SubmittedVerdict(
                STILL_WORKING, True, ("order_still_working",),
                f"{inst}: the order is on the broker's book and has not resolved; entries "
                f"stay blocked until it does", evidence)
        evidence["matched_by"] = NOT_MATCHED

    status = reader.order_status(oid) if oid else Answer.unknown(
        AMBIGUOUS,
        "the journal row carries no order id, so neither id-keyed lookup can be used; this "
        "is the Stage 5X fallback and it is weaker on purpose")
    evidence["order_status"] = status.detail
    if status.known:
        if status.value == "FILLED":
            ex = reader.execution(oid, inst)
            evidence["execution"] = ex.detail
            if ex.known:
                filled = float(ex.value.get("shares", 0) or 0)
                want = float(getattr(record, "filled_qty", 0) or 0) or None
                if want is not None and 0 < filled < want:
                    return SubmittedVerdict(
                        RESOLVED_PARTIAL, True, ("partial_fill",),
                        f"{inst}: {filled:g} of {want:g} filled; a partial position is a "
                        f"position, and the remainder is still unaccounted for", evidence)
                return SubmittedVerdict(
                    RESOLVED_FILLED, False, (),
                    f"{inst}: filled, confirmed by execution record", evidence)
            return SubmittedVerdict(
                RESOLVED_UNKNOWN, True, ("filled_without_execution_record",),
                f"{inst}: the broker says FILLED but will not produce the execution; the "
                f"size and price are unknown and the book cannot be advanced on that",
                evidence)
        if status.value == "CANCELLED":
            return SubmittedVerdict(
                RESOLVED_REJECTED, False, (),
                f"{inst}: the broker states the order was cancelled — this is the only "
                f"path to REJECTED, and it requires a statement", evidence)
        return SubmittedVerdict(
            STILL_WORKING, True, ("order_pending",),
            f"{inst}: the broker says {status.value}", evidence)

    # Nothing conclusive. Positions are read only to say whether exposure exists, never to
    # decide that this order is the reason for it.
    pos = reader.positions()
    evidence["positions"] = pos.detail
    reasons = ["broker_could_not_resolve"]
    if not working.known:
        reasons.append("open_orders_unknown")
    if not status.known:
        reasons.append("order_status_unknown")
    if not pos.known:
        reasons.append("positions_unknown")
    return SubmittedVerdict(
        RESOLVED_UNKNOWN, True, tuple(reasons),
        f"{inst}: the order was submitted and the broker cannot say what became of it. "
        f"Not rejected — unproven. Entries stay blocked; exits that reduce exposure do not.",
        evidence)


#: How a working order was tied to a journal row. Carried in the evidence so a report can say
#: which one answered, because they are not equally strong and Stage 5X's fallback was built
#: when the strong one did not exist.
BY_ORDER_ID = "matched_by_order_id"
BY_INSTRUMENT_ACTION = "matched_by_instrument_and_action"
NOT_MATCHED = "no_working_order_matched"


def _matches(order: Any, record: Any, order_id: str) -> "tuple[bool, str]":
    """Is this working order the one the journal row is about, and how do we know?

    **An id, when both sides have one, is the whole answer — including when it says no.**
    Falling through to instrument-and-action after an id mismatch would let a different order
    on the same contract answer for ours, which is the failure the id was added to remove.
    Stage 5X's fallback is not weaker guessing to be tried afterwards; it is what to do when
    there is nothing better, and Stage 5Y made "nothing better" the uncommon case.
    """
    get = order.get if isinstance(order, dict) else (lambda k, d=None: getattr(order, k, d))
    theirs = str(get("order_id", "") or "")
    if order_id and theirs:
        return (theirs == order_id), BY_ORDER_ID
    if str(get("instrument", "") or "") != str(getattr(record, "instrument", "") or ""):
        return False, NOT_MATCHED
    ra = str(getattr(record, "action", "") or "").upper()
    oa = str(get("action", "") or "").upper()
    # Instrument alone would claim a protective stop working on the same contract.
    return (bool(ra) and ra == oa), BY_INSTRUMENT_ACTION


# ── what the route may still do while unresolved ─────────────────────────────────────────

def exit_allowed(*, verdict_or_resolution: Any, reduces_exposure: bool) -> "tuple[bool, str]":
    """Exits are allowed under UNKNOWN and MISMATCH — but only if they REDUCE exposure.

    Stage 5U said "exits always allowed", which was right about intent and loose about
    wording: under an unresolved book a "close" whose size exceeds what is actually held
    does not reduce exposure, it opens the other side. That is the one thing an unaccounted
    book must not be allowed to do by accident.
    """
    res = getattr(verdict_or_resolution, "resolution", verdict_or_resolution)
    if not reduces_exposure:
        return False, (
            f"refused under {res}: this order does not reduce exposure, and while the book "
            f"is unresolved an over-sized close opens the opposite side")
    return True, f"allowed under {res}: it reduces exposure"


def entries_allowed(verdicts: Sequence[SubmittedVerdict]) -> "tuple[bool, list]":
    """Entries are allowed only when every unresolved row has been settled."""
    blocking = [v for v in verdicts if v.blocks_entries]
    if blocking:
        return False, [r for v in blocking for r in v.reasons]
    return True, []
