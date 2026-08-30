"""global_index/track1_paper_order.py — the paper order boundary, specified. NEW FILE.

Stage 5T. **Nothing here can send an order.** There is no broker, no connection, no `placeOrder`
and no import of `ib_insync`. What is implemented is the one piece that is pure and therefore
provable today: turning an ADMITTED Track 1 candidate into a `broker.Order`. Everything that
would touch a socket is a specification with a refusing stub behind it.

Why this file exists
--------------------
Stage 5S found that "paper mode" does not exist. `run_shadow` constructs `NoOrderBroker()`
unconditionally, `IBKRBroker` is never constructed in `run_live_day_track1.py`, and the
scheduler's own slot path — `observe_live_slot` — takes no order gate at all. Arming changes
the recorded decision mode and whether freshness binds; it changes nothing about what is sent,
because nothing is sent.

So the order gate has been guarding a door with no room behind it. This file is the room's
floor plan, plus the one wall that could be built without a broker.

The seam, in one sentence
-------------------------
**Shadow and paper must differ at exactly one point: the object that receives an `Order`.**
Everything upstream — the live frame, the freshness gate, the sleeve rules, admission and caps,
the explanation, the checkpoint, the params hash and the sizing basis — is the same code
reading the same inputs, or the paper book is not the book the shadow evidence describes.

The three identities, and which one goes on the order
------------------------------------------------------
Stage 5Q-7 and 5Q-9 separated them and this is where the separation is spent:

    runner name     MNKD     what the Candidate carries, and what goes on the Order
    history symbol  NKD      what the BAR provider asks for — never on an order
    order symbol    MNK      what IBKR is asked to trade

`Order.inst` carries the RUNNER name, and `IBKRBroker.send_order` resolves it through
`_front_month_contract` -> `_RAITS_TO_IBKR`, so MNKD reaches MNK without this module naming
MNK at all. That is the correct division: one map, in the layer that owns the broker. What this
module does is REFUSE if that map has drifted from the identity the route hashed, because a
silent disagreement there is the 2026-08-14 defect (-$1,400 against -$140 in the ledger,
exactly 10.0000x) arriving from the other direction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from global_index.broker import Fill, Order

#: Refusal codes. Named so a refusal is a value a test can assert, not a message it must match.
IDENTITY_DRIFT = "order_identity_drift"
NOT_ADMITTED = "candidate_not_admitted"
QTY_INVALID = "order_quantity_invalid"
REF_DAY_MISSING = "order_ref_day_missing"
NOT_IMPLEMENTED = "paper_execution_not_implemented"


class PaperOrderRefused(RuntimeError):
    """The order could not be built or sent. Raised rather than returned, for the reason the
    live-frame guard raises: a caller who must remember to check a flag will forget once."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ── the one thing that is pure, and therefore built ──────────────────────────────────────

def tradable_symbol(inst: str) -> str:
    """What an order for `inst` is routed to, from the contract record the identity hashes.

    Exposed because the journal records it on every line and the journal is read back after a
    crash: a record that did not say which contract it meant would leave a reconcile guessing
    between MNKD's two names. `candidate_to_order` below is what checks this against the
    broker's own map; this is only the lookup.
    """
    from global_index import track1_params as tp

    return tp._contract(inst).ibkr


def candidate_to_order(candidate: Any, *, ref_day: Any, action: str = "OPEN") -> Order:
    """An admitted Track 1 candidate -> the `broker.Order` a paper run would send.

    Pure. No broker, no connection, no side effect. This is the whole of the translation layer
    and it is deliberately small: the quantity is the candidate's, the cluster is the sleeve,
    and the instrument is the RUNNER name because the broker owns the map to a ticker.

    It refuses rather than guesses in three cases, and each is a defect this route has already
    met once:

    `order_identity_drift` — the runner name must resolve, through the broker's own map, to
    the same `tradable_symbol` the route hashed into its params identity. If those two ever
    disagree, one of them is describing a different contract, and the last time that happened
    live orders for a $0.50 micro were routed to a $5 full-size contract for four days.

    `candidate_not_admitted` — an order may only be built from a candidate the cap gate TOOK.
    Building one from a rejected candidate would put size behind a decision the book refused,
    which is the whole point of having a book.

    `order_quantity_invalid` — quantity comes from the candidate, never from the instrument
    table, because MNQ is one micro under Normal and seven under Stress on the same day. A
    non-positive quantity is a defect upstream and must not become a zero-lot order.

    `ref_day` is REQUIRED and is not derived from `candidate.entry_time`. For the Rổ 4 sleeves
    the two would agree; for `global_nkd` the entry stamp is an AWARE Tokyo instant, and the
    session it belongs to is a decision the route already makes elsewhere. Deriving a trading
    day from a Tokyo timestamp inside an order builder is the shape of every clock defect this
    route has had, so it refuses to guess and asks the caller who already knows.
    """
    from global_index import track1_params as tp
    from global_index.ibkr_broker import ibkr_symbol_and_exchange

    inst = str(getattr(candidate, "instrument", "") or "")
    sleeve = str(getattr(candidate, "sleeve", "") or "")
    qty = int(getattr(candidate, "qty", 0) or 0)
    direction = str(getattr(candidate, "direction", "") or "")

    if qty <= 0:
        raise PaperOrderRefused(
            QTY_INVALID,
            f"{inst}: quantity {qty!r} is not positive; quantity is a property of the "
            f"candidate and a non-positive one is an upstream defect, not a zero-lot order")

    declared = tp._contract(inst).ibkr
    routed, _exchange = ibkr_symbol_and_exchange(inst)
    if declared != routed:
        raise PaperOrderRefused(
            IDENTITY_DRIFT,
            f"{inst}: the params identity says this trades {declared!r} and the broker map "
            f"would route it to {routed!r}. One of them describes a different contract; "
            f"routing a micro to its full-size sibling cost -$1,400.00 against -$140.00 in "
            f"the ledger on 2026-08-14, exactly 10.0000x")

    if ref_day is None:
        raise PaperOrderRefused(
            REF_DAY_MISSING,
            f"{inst}: ref_day is required and is deliberately not derived from the entry "
            f"stamp — see the docstring above for why a Tokyo-aware instant must not be "
            f"turned into a trading day here")

    return Order(inst=inst, action=action, direction=direction,
                 contracts=qty, cluster=sleeve, ref_day=ref_day)


def plan_entry(candidate: Any, *, ref_day: Any, slot_id: str = "",
               params_hash: str = "", stop_type: str = "") -> tuple:
    """`(Order, PlannedStop)` for one admitted candidate.

    Stage 5ZN. `candidate_to_order` is left exactly as it was — it is called from places that
    want an order and nothing else — and this is the pairing an ENTRY must go through, because
    an entry without a plan for its protection is the one shape that must never reach a broker.

    The stop is CARRIED, not computed: `PlannedStop.from_candidate` copies `stop_price` off
    the candidate the strategy produced. A second implementation beside the one that trades is
    how the planned stop and the meant stop quietly become two numbers.
    """
    from global_index import track1_planned_stop as ps

    order = candidate_to_order(candidate, ref_day=ref_day, action="OPEN")
    plan = ps.from_candidate(candidate, ref_day=str(ref_day), slot_id=slot_id,
                             params_hash=params_hash,
                             tradable_symbol=tradable_symbol(
                                 str(getattr(candidate, "instrument", "")
                                     or getattr(candidate, "inst", ""))),
                             stop_type=stop_type or ps.BASIS_UNKNOWN)
    ps.assert_sendable(order, plan)
    return order, plan


def assert_admitted(decision: Any) -> None:
    """Refuse unless the cap gate TOOK this candidate. Separate from `candidate_to_order` so a
    caller cannot satisfy it by constructing a plausible-looking object."""
    from global_index import track1_signal_layer as T

    verdict = getattr(decision, "verdict", None)
    if verdict != T.TAKE:
        raise PaperOrderRefused(
            NOT_ADMITTED,
            f"the cap gate returned {verdict!r}, not {T.TAKE!r}; an order may only be built "
            f"from a candidate the book admitted")


# ── the specification: what still has to be built ────────────────────────────────────────

@runtime_checkable
class Track1OrderExecutor(Protocol):
    """What a paper run needs, stated as an interface so the shape can be reviewed before it
    is written. NOTHING implements this yet.

    It is deliberately NARROW. The executor receives decisions the book has already made and
    turns them into broker calls; it never decides anything, never reads bars, and never
    consults a cap. If a future implementation needs a rule, the rule is in the wrong place.
    """

    def open_position(self, decision: Any) -> Fill: ...

    def close_position(self, held: Any, reason: str) -> Fill: ...

    def place_protective_stop(self, held: Any) -> Any: ...

    def switch_same_symbol(self, decision: Any, displaced: Any) -> Any: ...


@dataclass(frozen=True)
class UnbuiltPaperExecutor:
    """The stub that stands where the executor will go. Every method refuses by name.

    It exists so the seam is visible, importable and testable BEFORE anything can trade, in the
    same spirit as `NoOrderBroker`: a shadow run that silently produced fills would be worse
    than one that crashed, and a paper path that silently produced none would be worse still.
    """

    reason: str = ("the Track 1 paper execution path has not been built. See "
                   "scratch/track1_stage5t_paper_broker_path_audit_20260825.md")

    def _refuse(self, what: str):
        raise PaperOrderRefused(NOT_IMPLEMENTED, f"{what}: {self.reason}")

    def open_position(self, decision: Any) -> Fill:
        self._refuse("open_position")

    def close_position(self, held: Any, reason: str) -> Fill:
        self._refuse("close_position")

    def place_protective_stop(self, held: Any) -> Any:
        self._refuse("place_protective_stop")

    def switch_same_symbol(self, decision: Any, displaced: Any) -> Any:
        self._refuse("switch_same_symbol")


#: What must be IDENTICAL between a shadow run and a paper run. Written as data so a test can
#: walk it, rather than as prose in a document nothing checks.
#:
#: Each entry is (what, where it lives, why it cannot move). If a paper implementation changes
#: any of these, the shadow evidence stops describing the thing that is trading — which is the
#: entire premise of the readiness gate.
MUST_BE_IDENTICAL: tuple = (
    ("live frame + splice guard", "track1_live_source.live_frame",
     "the bars a decision was made on"),
    ("history symbol per instrument", "track1_live_source.history_symbol",
     "MNKD reads NKD; an order symbol must never reach the bar path"),
    ("freshness gate", "track1_freshness.evaluate",
     "a stale input is a refusal in both modes, not a warning in one"),
    ("sleeve rules", "track1_normal_r4 / track1_calm_a / track1_stress_mnq",
     "reproduced exactly against the committed artifacts"),
    ("sizing basis", "track1_params.risk_dollars",
     "the cap gate must read the same number the measured book was admitted under"),
    ("admission + caps", "track1_signal_layer.Track1Book",
     "including the risk-high-first ordering inside an instant"),
    ("explanations", "track1_explain",
     "a decision without an explanation is not auditable in either mode"),
    ("checkpoint + params hash", "track1_params.sleeve_identity",
     "a paper book resumed under a different identity is a different strategy"),
)

#: The only things a paper run may add. Everything else is the shadow path unchanged.
MAY_DIFFER: tuple = (
    ("the broker object", "NoOrderBroker -> a real IBKRBroker adapter"),
    ("send / cancel / close-then-open", "track1_switch.close_then_open already has the shape"),
    ("fill and reconcile results", "Fill.status, filled_qty, avg_price, commission"),
    ("the book after CONFIRMED fills", "live_positions.track1.json, never the legacy file"),
)
