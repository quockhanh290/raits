"""The stop the strategy decided on, written down where it can be checked later.

The gap this closes, measured before it was built: `Candidate` carries `stop_price` — the
strategy works it out and it survives all the way through admission — and `candidate_to_order`
builds an `Order` that has no field to put it in. `OrderRecord` has none either. So the planned
stop reached the edge of the order path and was dropped there, and the protective stop was
placed later by the safety sweep, in a different process, on a different schedule, with nothing
anywhere holding both the price that was intended and the price that was placed.

Nothing could be compared, so nothing was. Side, size, price, whether a bracket behaves,
whether an abandoned stop is still sitting on the book — every one of those questions needs the
two numbers side by side, and there was only ever one.

It is not theoretical. An abandoned stop left behind by a close on 2026-08-10 filled and opened
a position in the opposite direction. That incident is why both routes must share one
connection id, and it is why a stop with no record is an accounting hole rather than untidiness.

What this module refuses to do
------------------------------
**It never computes a stop.** It carries the one the strategy already decided. A second
implementation beside the one that trades is how "the planned stop" and "the stop the engine
meant" quietly become two different numbers — and the plan would be the one that looks right.
`from_candidate` reads `stop_price` and copies it; there is no arithmetic in this file.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

#: Why an entry has no plan. Each is a distinct condition, because "no stop" is not a diagnosis.
NO_STOP_PRICE = "no_stop_price"
STOP_NOT_A_NUMBER = "stop_not_a_number"
STOP_WRONG_SIDE = "stop_on_the_wrong_side_of_entry"
NO_QTY = "no_qty"

#: Stop basis, as reported by the sleeve. Recorded rather than derived: the two sleeves that
#: hold overnight use different rules, and a reconcile that assumed one of them would silently
#: mis-read the other.
BASIS_UNKNOWN = "unknown"


class PlannedStopMissing(RuntimeError):
    """An admitted entry has no usable stop. Raised before anything can be sent.

    Fail-closed on purpose: an entry order with no plan for its protection is the one shape
    that must never reach a broker, because the position exists from the fill and the stop
    would be decided afterwards by whatever ran next.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class PlannedStop:
    """What protection this entry was admitted with, in enough detail to reconcile later.

    Every field is here to answer a question a live working stop will raise: is it on the right
    instrument, the right side, the right size, at the right price, from the settings this run
    used. `stop_distance` is carried when the entry price is known so a reconcile does not have
    to re-derive it from two numbers that may have moved.
    """
    inst: str
    tradable_symbol: str
    direction: str
    qty: int
    stop_price: float
    #: The rule the sleeve used, as the sleeve names it. Never inferred here.
    stop_type: str = BASIS_UNKNOWN
    #: entry - stop for a long, stop - entry for a short. None when the entry is not known.
    stop_distance: float | None = None
    entry_price: float | None = None
    ref_day: str = ""
    sleeve: str = ""
    slot_id: str = ""
    #: The engine identity this plan belongs to, when the caller has it. A plan compared
    #: against a stop placed under different settings is a comparison of two different runs.
    params_hash: str = ""
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)

    def one_line(self) -> str:
        return (f"{self.direction} {self.qty} {self.tradable_symbol} stop {self.stop_price} "
                f"({self.stop_type})")


def _num(value: Any) -> "float | None":
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f          # NaN is not a stop


def requires_protection(candidate: Any) -> bool:
    """Does this admitted entry open exposure that needs a stop?

    Everything Track 1 admits does. The predicate exists so the rule has a name and a single
    place to change, rather than being an `if` repeated at each call site — and so a future
    exit-only or flattening order can say so instead of being special-cased silently.
    """
    action = str(getattr(candidate, "action", "") or "OPEN").upper()
    return action in ("", "OPEN")


def from_candidate(candidate: Any, *, ref_day: str = "", slot_id: str = "",
                   params_hash: str = "", tradable_symbol: str = "",
                   stop_type: str = BASIS_UNKNOWN) -> PlannedStop:
    """Carry the strategy's stop onto a record. No arithmetic beyond the distance.

    Raises `PlannedStopMissing` rather than returning something empty: a caller that received
    a `PlannedStop` must be able to trust it holds a price, and an "empty plan" object is the
    shape that gets passed along and checked nowhere.
    """
    inst = str(getattr(candidate, "instrument", "") or getattr(candidate, "inst", "") or "")
    direction = str(getattr(candidate, "direction", "") or "").lower()
    qty = getattr(candidate, "qty", None)
    qty = getattr(candidate, "contracts", None) if qty is None else qty
    stop = _num(getattr(candidate, "stop_price", None))
    entry = _num(getattr(candidate, "entry_price", None))

    if getattr(candidate, "stop_price", None) is None:
        raise PlannedStopMissing(NO_STOP_PRICE,
                                 f"{inst or 'candidate'} was admitted with no stop_price, so "
                                 f"there is no plan for its protection")
    if stop is None:
        raise PlannedStopMissing(STOP_NOT_A_NUMBER,
                                 f"{inst}: stop_price {getattr(candidate, 'stop_price')!r} is "
                                 f"not a usable number")
    try:
        qty_i = int(qty)
    except (TypeError, ValueError):
        raise PlannedStopMissing(NO_QTY, f"{inst}: qty {qty!r} is not a whole number") from None
    if qty_i <= 0:
        raise PlannedStopMissing(NO_QTY, f"{inst}: qty {qty_i} does not open a position")

    distance = None
    if entry is not None:
        distance = (entry - stop) if direction in ("long", "buy") else (stop - entry)
        if distance <= 0:
            # A long whose stop sits above its entry is not a stop, it is a target. Caught here
            # rather than at the broker, where it becomes an immediately-triggering order.
            raise PlannedStopMissing(
                STOP_WRONG_SIDE,
                f"{inst}: {direction} entry {entry} with stop {stop} — the stop is on the "
                f"wrong side and would trigger at once")

    return PlannedStop(
        inst=inst, tradable_symbol=str(tradable_symbol or inst), direction=direction,
        qty=qty_i, stop_price=stop, stop_type=str(stop_type or BASIS_UNKNOWN),
        stop_distance=distance, entry_price=entry, ref_day=str(ref_day),
        sleeve=str(getattr(candidate, "sleeve", "") or ""), slot_id=str(slot_id),
        params_hash=str(params_hash),
        detail={"source": str(getattr(candidate, "source", "") or ""),
                "trade_id": str(getattr(candidate, "trade_id", "") or "")})


def assert_sendable(order: Any, plan: "PlannedStop | None") -> None:
    """Refuse an entry that has no plan for its protection, before anything can send it.

    Placed between building the order and doing anything with it, so the refusal happens while
    the only cost is a raised exception. After the fill the position exists and the stop is
    whatever the next process decides — which is the state this whole module exists to prevent.
    """
    action = str(getattr(order, "action", "") or "OPEN").upper()
    if action not in ("", "OPEN"):
        return
    if plan is None:
        raise PlannedStopMissing(
            NO_STOP_PRICE,
            f"{getattr(order, 'inst', '?')}: an entry order was prepared with no planned "
            f"stop. Nothing may be sent: the position would exist from the fill and its "
            f"protection would be decided afterwards by whatever ran next")
    if _num(plan.stop_price) is None:
        raise PlannedStopMissing(STOP_NOT_A_NUMBER,
                                 f"{plan.inst}: the plan carries no usable stop price")
    if str(getattr(order, "inst", "")) and plan.inst != str(order.inst):
        raise PlannedStopMissing(
            NO_STOP_PRICE,
            f"the plan is for {plan.inst} and the order is for {order.inst} — a stop planned "
            f"for a different instrument protects nothing")
    o_qty = getattr(order, "contracts", None)
    if o_qty is not None and int(o_qty) != int(plan.qty):
        raise PlannedStopMissing(
            NO_QTY,
            f"{plan.inst}: the order is {o_qty} contract(s) and the plan protects "
            f"{plan.qty} — a partly-protected position is not a protected one")
