"""global_index/track1_paper_send.py — the one place a decision may become an order.

Stage 5ZZG. This is the seam that did not exist: the executor, the journal, the order mapping and
the stop plan were all built and **nothing called them**. That was safe and it was also a hole in
the story — "the wire is missing" is not a state anybody can test, and a wire built later under
time pressure is a wire built without the tests written here.

What this module is
-------------------
A gate, a loop, and a summary. It decides nothing: not what to trade, not how large, not whether
a candidate was admitted. Every one of those questions is answered before a decision reaches it,
and answering any of them here would put strategy behind an order gate where nobody would look
for it.

**It never constructs a broker.** The caller already holds one — the live-shadow path builds
`(provider, broker)` together for bars — and building a second would mean a second connection, a
second client id, and an order path that exists independently of the one the gate governs. The
broker is a required argument when armed, and the module is named `track1_*` so the live-frame
gate scans it: a construction here would close that gate, which is the outcome we want if anyone
ever tries.

What "closed" means
-------------------
When the gate is shut this function imports nothing, builds nothing and writes nothing. Not "it
builds an executor and then declines to call it" — the executor's own constructor refuses when
unarmed, and relying on that would still mean the import happened, the object existed, and the
only thing between a decision and a broker was a boolean somewhere else.

The measured state on the day this was written: `orders_possible=False`, blocked by
`B1_broker_account_or_legacy_retirement` and `PAPER_SHADOW_EVIDENCE`, no confirmation file,
`TRACK1_ORDERS_APPROVED` unset, and no order directory on disk. Nothing here changes any of that.

Failure is never a rejection
----------------------------
If a send raises, the executor writes UNKNOWN and re-raises. This module lets that through and
reports the run as fatal. An order that may be live is not an order that was refused, and the
difference is the whole reason the journal has both words.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

#: Why a run sent nothing.
GATE_CLOSED = "gate_closed"
NO_BROKER = "no_broker_supplied"
NOTHING_ADMITTED = "nothing_admitted"
SENT = "sent"

#: The one flag that opens this. Read from the object the caller already holds rather than
#: re-derived here: two places deciding whether orders are allowed is two places to disagree,
#: and the gate is the one with the registry behind it.
ARMED_ATTR = "allow_orders"


class SendRefused(RuntimeError):
    """A caller error — armed with no broker. Never raised because an order failed."""


@dataclass(frozen=True)
class SendSummary:
    """What one slot's send pass did. Counts, not opinions."""
    status: str
    reason: str = ""
    offered: int = 0
    admitted: int = 0
    sent: int = 0
    filled: int = 0
    partial: int = 0
    rejected: int = 0
    unknown: int = 0
    errors: list = field(default_factory=list)
    executor_built: bool = False

    @property
    def fatal(self) -> bool:
        """An unknown outcome or an error is fatal. A clean zero-send run is not."""
        return bool(self.unknown or self.errors)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["fatal"] = self.fatal
        return d

    def one_line(self) -> str:
        if self.status == GATE_CLOSED:
            return f"send_order calls: 0 — {self.reason}"
        return (f"send_order calls: {self.sent} — offered {self.offered}, admitted "
                f"{self.admitted}, filled {self.filled}, partial {self.partial}, rejected "
                f"{self.rejected}, unknown {self.unknown}"
                + (f", errors {len(self.errors)}" if self.errors else ""))


def _armed(order_gate: Any) -> bool:
    return bool(getattr(order_gate, ARMED_ATTR, False))


def _admitted(decisions: Sequence[Any]) -> list:
    """The decisions the cap gate TOOK, asked of the layer that owns the word.

    Not `getattr(d, "verdict") == "take"` spelled here: the constant lives in the signal layer
    and a second copy of it is a second thing to drift.
    """
    from global_index import track1_signal_layer as T

    return [d for d in decisions or () if getattr(d, "verdict", None) == T.TAKE]


def maybe_send_orders(decisions: Sequence[Any], *, order_gate: Any, broker: Any = None,
                      ref_day: Any, slot_id: str = "", root: str | Path = ".",
                      now_fn: Any = None) -> SendSummary:
    """Send the admitted decisions, or say why nothing was sent.

    The gate check is FIRST and it returns before any order import happens. That ordering is the
    contract, not a style choice: a test can assert the executor module was never imported, and
    that assertion is only meaningful while the import sits after the check.
    """
    offered = len(decisions or ())

    if not _armed(order_gate):
        # Nothing imported, nothing built, nothing written. The route is exactly as it was.
        return SendSummary(status=GATE_CLOSED, offered=offered,
                           reason="the order gate is closed; no executor was built and no "
                                  "broker was called")

    if broker is None:
        # Armed and handed nothing to send with. Refusing beats building a broker here: a second
        # connection on a second client id is how this project lost six entry slots in a
        # morning, and an order path the gate does not govern is worse than no order path.
        raise SendRefused(
            f"{NO_BROKER}: orders are armed and no broker was supplied. This module never "
            f"constructs one — the caller already holds the connection the bars came from")

    admitted = _admitted(decisions)
    if not admitted:
        return SendSummary(status=NOTHING_ADMITTED, offered=offered, admitted=0,
                           reason="the cap gate admitted nothing this slot")

    # Imported HERE, past the gate, so an unarmed run never loads the order layer at all.
    from global_index import track1_order_state as st
    from global_index import track1_paper_executor as ex

    executor = ex.Track1OrderExecutor(broker=broker, gate=order_gate, journal_root=root,
                                      now_fn=now_fn)

    filled = partial = rejected = unknown = sent = 0
    errors: list = []
    for decision in admitted:
        try:
            fill = executor.open_position(decision, ref_day=ref_day, slot_id=slot_id)
        except BaseException as exc:                                  # noqa: BLE001
            # The executor has already written UNKNOWN and re-raised. Counted as UNKNOWN and
            # NEVER as rejected: the order may be live and simply invisible, which is a
            # different problem with a different response.
            unknown += 1
            sent += 1
            errors.append(f"{getattr(getattr(decision, 'candidate', None), 'trade_id', '?')}: "
                          f"{type(exc).__name__}: {exc}")
            continue
        sent += 1
        status = str(getattr(fill, "status", "") or "").lower()
        if status == st.FILLED:
            filled += 1
        elif status == st.PARTIAL:
            partial += 1
        elif status == st.REJECTED:
            rejected += 1
        else:
            unknown += 1

    return SendSummary(status=SENT, offered=offered, admitted=len(admitted), sent=sent,
                       filled=filled, partial=partial, rejected=rejected, unknown=unknown,
                       errors=errors, executor_built=True)
