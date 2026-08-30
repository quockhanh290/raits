"""global_index/track1_order_state.py — order state and startup reconcile, as contracts. NEW FILE.

Stage 5U. **Nothing here can send an order or open a connection.** Every function is pure: it
takes data and returns a verdict. The broker appears only as plain lists a caller has already
fetched, so every branch is testable without a socket.

This resolves the two questions Stage 5T left open.

---
A. Why the window ledger cannot own order state
------------------------------------------------
`window_ledger._write` catches every exception and disables the channel for the process, with
the comment: *"It must never escape into a trading path — the ledger records availability, it
does not enforce it."*

That is exactly right for evidence and exactly wrong for a write-ahead log. If the ledger owned
"an order is about to be sent", a failed write would mean an order goes out with no record of
intent — the one thing a write-ahead log exists to prevent.

So the two files keep opposite contracts, and a third is added:

    window_coverage/*.jsonl     EVIDENCE.  Best-effort. Never blocks. Unchanged by paper.
    orders/*.jsonl              INTENT.    Append-only. FAIL-CLOSED: a write that fails
                                           must abort the order before it is sent.
    live_positions.track1.json  BELIEF.    What the route holds. Advances only on a
                                           CONFIRMED fill.

`decided` on a slot row keeps meaning exactly what it means today: **the route reached a
decision**. It must never come to depend on whether a fill happened, or a broker outage would
read as the strategy having stopped deciding — and the shadow evidence and the paper evidence
would stop being comparable, which is the premise the whole readiness gate rests on.

B. Why reconcile needs three answers and not two
------------------------------------------------
`IBKRBroker.get_positions()` reads until two consecutive reads agree and, if they never do,
*warns and returns the last one*. The caller cannot tell a settled truth from a guess. That is
the third time in this project a status reader has had no way to say "I do not know" — and the
first one, `scheduler_processes()` returning `[]`, cost six entry slots.

So `reconcile` returns MATCH, MISMATCH or **UNKNOWN**, and UNKNOWN blocks entries exactly as
MISMATCH does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# ── A. the order state machine ───────────────────────────────────────────────────────────

#: Written BEFORE any broker call. The book admitted the candidate; nothing has been sent.
INTENDED = "intended"
#: Written BEFORE `send_order` is called — not after. The outcome is not yet known and MUST
#: NOT be assumed.
#:
#: Stage 5V. The first draft said "handed to the broker", which left it ambiguous whether the
#: line is written before or after the call, and the ambiguity was a hole: a process that dies
#: DURING `send_order` would leave a journal whose last state is INTENDED while a live order
#: exists. Writing it first closes that — and it is the same rule `track1_switch` already
#: follows, whose docstring says "Every stage emits BEFORE it acts. A crash between two steps
#: is then attributable from the log."
#:
#: The cost is the opposite error, and it is the cheap one: an order that was never actually
#: sent looks unresolved until a reconcile says the broker has nothing.
SUBMITTED = "submitted"
#: The broker confirmed a complete fill.
FILLED = "filled"
#: The broker confirmed a fill smaller than requested.
PARTIAL = "partial"
#: The broker definitively refused: CANCELLED, FAILED or rejected. Nothing is held.
REJECTED = "rejected"
#: The broker did not answer, or answered unusably — disconnect, timeout, unparsable.
#: DISTINCT from REJECTED: "no" and "I could not hear you" are different facts, and treating
#: the second as the first is how a filled order becomes a position nobody believes in.
UNKNOWN = "unknown"

ORDER_STATES: tuple = (INTENDED, SUBMITTED, FILLED, PARTIAL, REJECTED, UNKNOWN)

#: States from which nothing further will happen on its own.
TERMINAL: frozenset = frozenset({FILLED, PARTIAL, REJECTED})

#: States that leave the route unable to say what it holds. Each one blocks new entries until
#: a reconcile resolves it.
UNRESOLVED: frozenset = frozenset({SUBMITTED, UNKNOWN})

#: The only transitions allowed. Anything else is a defect in whoever wrote the record, and is
#: reported rather than accepted — an order journal that accepts an impossible history cannot
#: be used to reconstruct what happened.
ALLOWED_TRANSITIONS: dict = {
    INTENDED: frozenset({SUBMITTED, REJECTED, UNKNOWN}),
    SUBMITTED: frozenset({FILLED, PARTIAL, REJECTED, UNKNOWN}),
    UNKNOWN: frozenset({FILLED, PARTIAL, REJECTED}),   # resolvable, only by asking
    PARTIAL: frozenset({FILLED, REJECTED}),            # the remainder resolves one way or other
    FILLED: frozenset(),
    REJECTED: frozenset(),
}


def transition_allowed(old: str, new: str) -> bool:
    """Is `old -> new` a history that could actually have happened?"""
    return new in ALLOWED_TRANSITIONS.get(old, frozenset())


@dataclass(frozen=True)
class OrderRecord:
    """One line of the order journal. Flat and scalar, because the journal is read back by a
    reconcile that must not depend on a nested schema surviving a crash mid-write."""
    trade_id: str
    sleeve: str
    instrument: str
    tradable_symbol: str
    direction: str
    qty: int
    state: str
    ref_day: str
    #: The client-side key, generated BEFORE the broker call so an order can be recognised
    #: again even when no broker id was ever returned.
    idempotency_key: str = ""
    broker_order_id: str = ""
    filled_qty: int = 0
    avg_price: float = 0.0
    detail: str = ""
    #: Stage 5ZN. The stop this entry was admitted with, carried from the candidate and never
    #: recomputed. Appended LAST and defaulted, so every row written before this stage still
    #: parses and every positional caller written before it still constructs.
    #:
    #: None means "this row carries no plan", which for an OPEN is a refusal condition checked
    #: before anything can be sent — not a value to be filled in later by whatever runs next.
    planned_stop_price: float | None = None
    planned_stop_type: str = ""
    planned_stop_distance: float | None = None

    def __post_init__(self) -> None:
        if self.state not in ORDER_STATES:
            raise ValueError(f"unknown order state {self.state!r}; one of {ORDER_STATES}")


def is_amendment(previous: Any, record: Any) -> bool:
    """Is `previous -> record` the arrival of the broker's order id, rather than a transition?

    Stage 5Y. `SUBMITTED -> SUBMITTED` is not a state change and `transition_allowed` is right
    to refuse it. But the journal writes SUBMITTED *before* the broker is called, so the id
    cannot exist on that row; it arrives on a receipt while the call is still in flight, and
    is recorded as a second row in the same state.

    This lives here, and both the writer and every reader use it, because the first version
    put the rule only in the writer: `append` accepted the amendment and `resolve` then called
    the resulting journal an impossible history. Every order that successfully got an id would
    have made that day's journal unreadable — fail-closed, and completely broken. Fifty-two
    tests missed it because they all checked the write and none re-read.

    Narrow on purpose. Only the id may appear, and only where there was none.
    """
    if previous is None:
        return False
    if getattr(previous, "state", None) != SUBMITTED or getattr(record, "state", None) != SUBMITTED:
        return False
    if str(getattr(previous, "broker_order_id", "") or getattr(previous, "order_id", "") or ""):
        return False
    return bool(str(getattr(record, "broker_order_id", "")
                    or getattr(record, "order_id", "") or ""))


def resolve_journal(records: Sequence[OrderRecord]) -> dict:
    """`{idempotency_key: final_state}` plus the histories that could not have happened.

    Returns `{"final": {...}, "impossible": [...]}`. An impossible history is reported, never
    smoothed over: the journal's whole purpose is to say what actually happened, and a reader
    that quietly repairs it is a reader that can be lied to.
    """
    final: dict = {}
    order: dict = {}
    impossible: list = []
    for rec in records:
        key = rec.idempotency_key or rec.trade_id
        prev = final.get(key)
        if prev is not None and not transition_allowed(prev, rec.state):
            # The one lawful repeat: the broker's id arriving on a row already SUBMITTED.
            if not is_amendment(order.get(key), rec):
                impossible.append(f"{key}: {prev} -> {rec.state}")
                continue
        final[key] = rec.state
        order[key] = rec
    return {"final": final, "records": order, "impossible": impossible}


def unresolved_orders(records: Sequence[OrderRecord]) -> list:
    """Keys whose last state leaves the route unable to say what it holds."""
    res = resolve_journal(records)
    return sorted(k for k, s in res["final"].items() if s in UNRESOLVED)


# ── B. startup reconcile ─────────────────────────────────────────────────────────────────

MATCH = "match"
MISMATCH = "mismatch"
RECONCILE_UNKNOWN = "unknown"
VERDICTS: tuple = (MATCH, MISMATCH, RECONCILE_UNKNOWN)


@dataclass(frozen=True)
class Position:
    """The three fields both sides can actually compare.

    `cluster` is deliberately absent. `IBKRBroker.get_positions` sets it to `"UNKNOWN"` because
    IBKR has no cluster concept, so any reconcile that compared it would be comparing a
    sentinel against a real value and calling the result a mismatch every time.
    """
    instrument: str
    direction: str
    contracts: int


@dataclass(frozen=True)
class ReconcileResult:
    verdict: str
    blocks_entries: bool
    allows_exits: bool
    reasons: tuple = field(default_factory=tuple)
    detail: Mapping[str, Any] = field(default_factory=dict)


def _net(positions: Iterable[Position]) -> dict:
    """`{instrument: signed_contracts}`. LONG positive, SHORT negative — the same convention
    `ib.positions()` uses, so the two sides are comparable without a second rule."""
    out: dict = {}
    for p in positions:
        sign = 1 if str(p.direction).upper() == "LONG" else -1
        out[p.instrument] = out.get(p.instrument, 0) + sign * int(p.contracts)
    return {k: v for k, v in out.items() if v != 0}


def reconcile(book: Sequence[Position],
              broker: "Sequence[Position] | None",
              *,
              broker_settled: bool = True,
              journal: Sequence[OrderRecord] = (),
              legacy_book: Sequence[Position] = (),
              shared_account: bool = True) -> ReconcileResult:
    """Compare what the route believes it holds with what the broker reports.

    Three answers, never two. Entries are blocked on MISMATCH **and** on UNKNOWN; exits are
    allowed in all three, because refusing to REDUCE exposure while the book is confused is the
    wrong failure direction — a stop that cannot be placed is worse than one placed against a
    position that turns out to be flat.

    `shared_account` is the B1 question, and it changes what this can prove. While one IB
    Gateway login serves both routes, `get_positions()` returns the NET per contract for BOTH,
    so the strongest available statement is:

        broker_net(contract) == track1_net(contract) + legacy_net(contract)

    which detects disagreement but cannot ATTRIBUTE it. With a dedicated account the comparison
    is exact. That is a concrete reason B1 has to be closed BEFORE paper rather than alongside
    it: until it is, a mismatch cannot be pinned on a route.
    """
    reasons: list = []

    if broker is None or not broker_settled:
        return ReconcileResult(
            RECONCILE_UNKNOWN, blocks_entries=True, allows_exits=True,
            reasons=("broker_positions_unsettled",),
            detail={"why": "get_positions returned without settling, or returned nothing at "
                           "all; an unsettled read is a guess and must not be treated as truth"})

    stuck = unresolved_orders(list(journal))
    impossible = resolve_journal(list(journal))["impossible"]
    if impossible:
        reasons.append("order_journal_impossible_history")
    if stuck:
        reasons.append("orders_unresolved")

    b_net = _net(book)
    k_net = _net(broker)
    expected = dict(b_net)
    if shared_account:
        for inst, qty in _net(legacy_book).items():
            expected[inst] = expected.get(inst, 0) + qty
        expected = {k: v for k, v in expected.items() if v != 0}

    disagreements = {}
    for inst in sorted(set(expected) | set(k_net)):
        want, got = expected.get(inst, 0), k_net.get(inst, 0)
        if want != got:
            disagreements[inst] = {"book_expects": want, "broker_reports": got}

    #: An instrument the route does not trade at all. A leftover full-size NKD position is the
    #: real case: `_to_runner` deliberately no longer maps NKD back to MNKD, so it arrives
    #: under a name the book does not use. It must block, not be ignored — and must NOT be
    #: adopted as MNKD, which is how the ten-times-size incident would be re-inherited.
    unrecognised = sorted(set(k_net) - set(expected))
    if unrecognised:
        reasons.append("broker_holds_an_instrument_the_route_does_not")

    if disagreements:
        reasons.append("position_disagreement")

    if reasons:
        # Explicit branches rather than one chained conditional. The first version of this was
        # a three-clause expression whose precedence had to be worked out to read, and a
        # reconcile verdict is not a place to make a reader do that.
        if disagreements or unrecognised:
            verdict = MISMATCH          # a definite disagreement about what is held
        elif impossible:
            verdict = MISMATCH          # the journal records a history that cannot have happened
        else:
            verdict = RECONCILE_UNKNOWN  # only unresolved orders: we do not know yet
        return ReconcileResult(verdict, blocks_entries=True, allows_exits=True,
                               reasons=tuple(reasons),
                               detail={"disagreements": disagreements,
                                       "unrecognised": unrecognised,
                                       "unresolved_orders": stuck,
                                       "impossible_history": impossible,
                                       "shared_account": shared_account})

    return ReconcileResult(MATCH, blocks_entries=False, allows_exits=True,
                           reasons=(), detail={"instruments": sorted(expected),
                                               "shared_account": shared_account})


#: What a crash in each state means, and what a restart must do about it. Data rather than
#: prose so a test can walk it and an implementation cannot quietly disagree with the design.
CRASH_RECOVERY: dict = {
    INTENDED: ("nothing was ATTEMPTED. SUBMITTED is written before send_order is called, so "
               "a journal whose last state is INTENDED means the broker was never reached. "
               "The candidate did not trade; the book is unchanged. Safe to continue once "
               "reconcile returns MATCH."),
    SUBMITTED: ("an attempt was made or was about to be. The outcome is unknown. Ask the "
                "broker — get_order_status if an id was recorded, otherwise compare "
                "positions. Block entries until resolved; allow exits."),
    UNKNOWN: ("same as SUBMITTED and for the same reason: 'no' and 'I could not hear you' are "
              "different facts. Block entries; allow exits."),
    PARTIAL: ("the book records the FILLED quantity only, never the requested one. The "
              "remainder is flagged and entries stay blocked until it resolves."),
    FILLED: ("the book advances. This is the only state that may add a position."),
    REJECTED: ("nothing is held. The cap the candidate reserved is released and the refusal is "
               "recorded as a divergence from the shadow book."),
}

#: The close-then-open case `track1_switch` already handles, restated here because its recovery
#: lives in this file's half of the problem. When the close FILLED and the open FAILED, the
#: account is FLAT and `persist_flat` is called; if that callback raised, `persisted=False` and
#: the book still claims the old position. On restart that is a MISMATCH — book says held,
#: broker says flat — and the repair is to believe the BROKER about existence.
SWITCH_FLAT_RECOVERY = ("close filled + open failed -> the account is flat. If persist_flat "
                        "raised, the book is wrong and the broker is right about existence; "
                        "mark flat, then reconcile again before any entry.")
