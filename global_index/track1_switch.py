"""global_index/track1_switch.py — close-confirm-open for the Track 1 Stress switch. NEW FILE.

Stage 3. Broker-agnostic. Nothing here connects to IBKR; it takes a broker object and calls
four methods on it. Every test drives it with a fake.

What it is
----------
Track 1's Stress sleeve may displace a Normal or Calm position on the same symbol. At IBKR
the two legs cannot be simultaneous: `get_positions()` returns the NET signed quantity per
contract, so a Normal LONG 1 and a Stress SHORT 7 on MNQ do not coexist as two positions —
they coexist as a net short 6 that no reconcile can decompose. That is the same mechanism
that put the legacy STRESS_MID cron behind `if False:`.

So the switch is sequential, and the sequence has to be the one `_handle_rollover` already
uses, because that sequence has been thought about:

    cancel the old stop, CONFIRMED   ->   close the old position, VERIFIED FILLED
    ->   only then open the new one

Why this is not `_handle_rollover` itself
------------------------------------------
Stage 2D looked at reusing it directly and the answer was no. `_handle_rollover` is gated on
`get_roll_event` returning a roll date, assumes the two legs are the same symbol, same
direction, same quantity and different MONTH, stamps both fills with front/next month, and
its caller interprets the result through a rollover-specific state update. A cluster switch
is the same symbol, possibly a different direction, a different quantity, and the same
month. What transfers is the SHAPE, and the shape is here.

The three failure branches, and why each is what it is
-------------------------------------------------------
1. **The stop cancel fails -> abort before anything is closed.** An orphaned protective stop
   under a reversed position is not merely useless: a SELL stop with no long behind it fills
   into a short nobody asked for. Aborting leaves the Normal position intact and protected,
   which is the recoverable state.
2. **The close does not verifiably fill -> abort, do not open.** Anything short of FILLED,
   including PARTIAL, is a refusal: a partly-closed Normal leg plus a 7-lot Stress leg nets
   at the broker into a quantity neither sleeve believes it holds.
3. **The open fails after the close filled -> the account is FLAT on that symbol.** The book
   must record that before anything else can happen, because the next process to start will
   compare the file against the broker and a stale "we hold it" turns into a halt that costs
   a session. Persistence happens through a callback the caller supplies, and a callback
   that raises is caught and reported rather than being allowed to lose the fact.

Emission before action, not after
---------------------------------
Every stage emits BEFORE it acts. A crash between two steps is then attributable from the
log; emitting afterwards would leave the most interesting case — the one that died halfway —
as the one with no record.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from global_index.broker import Fill, Order

# Stages, in order. Named so a reader of the event stream can tell how far it got.
REQUESTED = "switch_requested"
STOP_CANCEL = "stop_cancel"
STOP_CANCEL_FAILED = "stop_cancel_failed"
CLOSE_PLACED = "close_placed"
CLOSE_FILLED = "close_filled"
CLOSE_FAILED = "close_failed"
OPEN_PLACED = "open_placed"
OPEN_FILLED = "open_filled"
OPEN_FAILED_FLAT = "open_failed_account_flat"

STAGES = (REQUESTED, STOP_CANCEL, STOP_CANCEL_FAILED, CLOSE_PLACED, CLOSE_FILLED,
          CLOSE_FAILED, OPEN_PLACED, OPEN_FILLED, OPEN_FAILED_FLAT)


@dataclass(frozen=True)
class Leg:
    """One side of the switch."""
    inst: str
    action: str            # "CLOSE" | "OPEN"
    direction: str         # the POSITION's direction, not the broker verb
    qty: int
    cluster: str
    contract_month: str | None = None
    stop_price: float | None = None

    def to_order(self, ref_day) -> Order:
        return Order(self.inst, self.action, self.direction, int(self.qty), self.cluster,
                     ref_day, contract_month=self.contract_month)


@dataclass
class SwitchResult:
    ok: bool
    stage: str
    detail: str = ""
    close_fill: Fill | None = None
    open_fill: Fill | None = None
    account_flat: bool = False
    events: list = field(default_factory=list)

    @property
    def opened(self) -> bool:
        return self.ok and self.open_fill is not None


def _emit(events: list, on_event, stage: str, detail: str, **ctx) -> None:
    rec = {"stage": stage, "detail": detail, **ctx}
    events.append(rec)
    if on_event is not None:
        try:
            on_event(rec)
        except Exception:
            # Telemetry must never be able to stop a switch. It also must never be able to
            # make one look like it succeeded, which is why the record is appended to
            # `events` first: the in-memory trail survives a failing sink.
            pass


def close_then_open(broker, *, close_leg: Leg, open_leg: Leg, ref_day,
                    stop_order_id: str | None = None,
                    on_event: Callable[[dict], None] | None = None,
                    persist_flat: Callable[[], None] | None = None,
                    allow_orders: bool = False) -> SwitchResult:
    """Displace one position with another on the same symbol, sequentially.

    `allow_orders` is False by default and refuses before touching the broker. A primitive
    whose default reaches an exchange is a primitive that will reach one by accident.
    """
    events: list = []
    _emit(events, on_event, REQUESTED,
          f"{close_leg.cluster} {close_leg.direction} x{close_leg.qty} {close_leg.inst} "
          f"-> {open_leg.cluster} {open_leg.direction} x{open_leg.qty} {open_leg.inst}",
          inst=close_leg.inst, close_qty=close_leg.qty, open_qty=open_leg.qty)

    if not allow_orders:
        return SwitchResult(False, REQUESTED,
                            "order sending is disabled; nothing was placed",
                            events=events)

    if close_leg.inst != open_leg.inst:
        # Not a defensive nicety: a switch across symbols is not a switch, it is two
        # unrelated trades, and running them through this sequence would make the second
        # one wait on the first for no reason.
        return SwitchResult(False, REQUESTED,
                            f"close leg {close_leg.inst} and open leg {open_leg.inst} are "
                            f"different symbols; this primitive is same-symbol only",
                            events=events)

    # ── 1. the old stop ──────────────────────────────────────────────────────
    if stop_order_id is not None:
        _emit(events, on_event, STOP_CANCEL, f"cancelling stop {stop_order_id}",
              order_id=str(stop_order_id))
        try:
            cancelled = bool(broker.cancel_order(str(stop_order_id)))
        except Exception as exc:
            cancelled = False
            _emit(events, on_event, STOP_CANCEL_FAILED, f"cancel_order raised: {exc}",
                  order_id=str(stop_order_id))
        if not cancelled:
            _emit(events, on_event, STOP_CANCEL_FAILED,
                  "the protective stop is still working; aborting before anything is closed",
                  order_id=str(stop_order_id))
            return SwitchResult(False, STOP_CANCEL_FAILED,
                                f"stop {stop_order_id} could not be confirmed cancelled; "
                                f"the switch was abandoned and the old position is intact",
                                events=events)

    # ── 2. close the old position ────────────────────────────────────────────
    _emit(events, on_event, CLOSE_PLACED,
          f"CLOSE {close_leg.direction} x{close_leg.qty} {close_leg.inst}",
          inst=close_leg.inst, qty=close_leg.qty, month=close_leg.contract_month)
    try:
        close_fill = broker.send_order(close_leg.to_order(ref_day))
    except Exception as exc:
        _emit(events, on_event, CLOSE_FAILED, f"send_order raised: {exc}")
        return SwitchResult(False, CLOSE_FAILED, f"close leg raised: {exc}", events=events)

    if getattr(close_fill, "status", None) != "FILLED":
        _emit(events, on_event, CLOSE_FAILED,
              f"close status={getattr(close_fill, 'status', None)}; the new position is NOT "
              f"opened", status=getattr(close_fill, "status", None))
        return SwitchResult(False, CLOSE_FAILED,
                            f"close did not verifiably fill (status="
                            f"{getattr(close_fill, 'status', None)}); nothing was opened",
                            close_fill=close_fill, events=events)

    _emit(events, on_event, CLOSE_FILLED,
          f"closed at {getattr(close_fill, 'avg_price', 0.0)}",
          price=getattr(close_fill, "avg_price", 0.0))

    # ── 3. open the new position ─────────────────────────────────────────────
    _emit(events, on_event, OPEN_PLACED,
          f"OPEN {open_leg.direction} x{open_leg.qty} {open_leg.inst}",
          inst=open_leg.inst, qty=open_leg.qty)
    try:
        open_fill = broker.send_order(open_leg.to_order(ref_day))
    except Exception as exc:
        open_fill = Fill(open_leg.inst, "OPEN", open_leg.direction, open_leg.qty,
                         open_leg.cluster, status="CANCELLED", error_msg=str(exc))

    if getattr(open_fill, "status", None) not in ("FILLED", "PARTIAL"):
        # The account is flat on this symbol. Record that before anything else.
        persisted = True
        if persist_flat is not None:
            try:
                persist_flat()
            except Exception as exc:
                persisted = False
                _emit(events, on_event, OPEN_FAILED_FLAT,
                      f"persist_flat raised: {exc}; the book still says the old position is "
                      f"open and the next start-up will halt on the mismatch")
        _emit(events, on_event, OPEN_FAILED_FLAT,
              f"open status={getattr(open_fill, 'status', None)}; the account is FLAT on "
              f"{open_leg.inst}", status=getattr(open_fill, "status", None),
              persisted=persisted)
        return SwitchResult(False, OPEN_FAILED_FLAT,
                            f"close filled but open did not (status="
                            f"{getattr(open_fill, 'status', None)}); the account is flat on "
                            f"{open_leg.inst} and the book has been told so",
                            close_fill=close_fill, open_fill=open_fill,
                            account_flat=True, events=events)

    _emit(events, on_event, OPEN_FILLED,
          f"opened at {getattr(open_fill, 'avg_price', 0.0)}",
          price=getattr(open_fill, "avg_price", 0.0))
    return SwitchResult(True, OPEN_FILLED, "", close_fill=close_fill, open_fill=open_fill,
                        events=events)
