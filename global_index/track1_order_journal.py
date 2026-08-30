"""global_index/track1_order_journal.py — the fail-closed order journal. NEW FILE.

Stage 5V. **Nothing here can send an order.** No broker, no `ib_insync`, no connection. This
module writes one thing: a durable, append-only record that an order is INTENDED, and then what
became of it.

Why it is not the window ledger
-------------------------------
`window_ledger._write` catches every exception and disables the channel for the process, with
the comment: *"It must never escape into a trading path — the ledger records availability, it
does not enforce it."*

That contract is right for evidence and wrong for a write-ahead log. If the ledger owned "an
order is about to be sent", a failed write would let the order go out with no record of intent
— the single thing a write-ahead log exists to prevent. So this module is the opposite in every
respect that matters:

    window ledger        best-effort. Swallows. Never blocks a trading path.
    THIS module          fail-closed. Raises. A write that did not land must stop the order.

Nothing here is caught and turned into a return value. Every failure — a bad record, an illegal
transition, a path outside the runtime root, a disk error — leaves as an exception, because the
only correct response to "I could not record that I am about to trade" is not to trade.

Durability, and its honest limit
--------------------------------
An append is written, flushed, and `os.fsync`ed before `append` returns, so a record that this
function claims is durable has reached the device rather than an OS buffer. The directory entry
itself is not fsynced: on Windows there is no portable way to do it. The exposure is a file
created in the same instant as the crash, which is the one case a reconcile against broker
positions is there to catch anyway — stated rather than left to be discovered.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from global_index import track1_order_state as st

SCHEMA_VERSION = 1

#: Durable, under the Track 1 runtime root. NOT scratch: an order journal is the record of what
#: the route committed to, and ordinary cleanup of scratch would delete it.
ORDERS_DIR = "global_index/track1_runtime/orders"

ROUTE = "track1_candidate"

# ── refusal codes. Values a caller can branch on, not messages it must match. ─────────────
BAD_RECORD = "order_journal_bad_record"
BAD_ROUTE = "order_journal_wrong_route"
BAD_TRANSITION = "order_journal_illegal_transition"
#: A second row in the same state that is not a lawful amendment. See `_check_amendment`.
BAD_AMENDMENT = "order_journal_bad_amendment"
PATH_ESCAPE = "order_journal_path_escape"
UNREADABLE = "order_journal_unreadable"
WRITE_FAILED = "order_journal_write_failed"


class OrderJournalRefused(RuntimeError):
    """The journal could not record what it was asked to. **The caller must not send the
    order.** Raised rather than returned for the reason the live-frame guard raises: a caller
    who has to remember to check a flag will forget once, and the cost here is an untracked
    position."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class JournalRecord:
    """One line. Flat and scalar throughout, because it is read back after a crash by a
    reconcile that must not depend on a nested schema having survived a partial write."""

    idempotency_key: str
    state: str
    ref_day: str
    sleeve: str
    instrument: str
    tradable_symbol: str
    action: str
    candidate_id: str
    created_at: str
    slot_id: str = ""
    order_id: str = ""
    fill_status: str = ""
    filled_qty: int = 0
    avg_price: float = 0.0
    commission: float = 0.0
    error: str = ""
    route: str = ROUTE
    schema_version: int = SCHEMA_VERSION
    #: Stage 5ZN. The stop this entry was admitted with, carried from the candidate and never
    #: recomputed here. Appended LAST and defaulted, so every row written before this stage
    #: still reads back and every existing constructor still works.
    #:
    #: None on a CLOSE is correct — a close carries no protection of its own. None on an OPEN
    #: is a refusal condition checked before the row can be considered sendable, not a blank
    #: for something later to fill in.
    planned_stop_price: "float | None" = None
    planned_stop_type: str = ""
    planned_stop_distance: "float | None" = None
    #: How many contracts this row is about. Previously implied by the order and lost on the
    #: way into the journal, which made a partial fill impossible to check against intent.
    qty: int = 0

    def __post_init__(self) -> None:
        if self.state not in st.ORDER_STATES:
            raise OrderJournalRefused(
                BAD_RECORD, f"unknown state {self.state!r}; one of {st.ORDER_STATES}")
        for name in ("idempotency_key", "ref_day", "sleeve", "instrument",
                     "tradable_symbol", "action", "candidate_id", "created_at"):
            if not str(getattr(self, name) or "").strip():
                raise OrderJournalRefused(
                    BAD_RECORD,
                    f"{name} is empty; every field a reconcile reads back must be present at "
                    f"write time, because there is no second chance to fill it in")
        if self.route != ROUTE:
            raise OrderJournalRefused(
                BAD_ROUTE,
                f"route {self.route!r} is not {ROUTE!r}; an unstamped record cannot be told "
                f"apart from legacy's and would be counted by whichever reader found it first")
        if int(self.filled_qty) < 0:
            raise OrderJournalRefused(BAD_RECORD, "filled_qty may not be negative")

    def as_row(self) -> dict:
        return asdict(self)

    def as_order_record(self) -> st.OrderRecord:
        """The reconcile view. Deliberately a conversion rather than a second dataclass with
        the same fields: `track1_order_state` owns the state vocabulary, this module owns the
        wire format, and one of them has to be able to change without the other."""
        return st.OrderRecord(
            trade_id=self.candidate_id, sleeve=self.sleeve, instrument=self.instrument,
            tradable_symbol=self.tradable_symbol, direction="", qty=0,
            state=self.state, ref_day=self.ref_day,
            idempotency_key=self.idempotency_key, broker_order_id=self.order_id,
            filled_qty=int(self.filled_qty), avg_price=float(self.avg_price),
            detail=self.error)


def idempotency_key(*, sleeve: str, instrument: str, ref_day: str, action: str,
                    candidate_id: str) -> str:
    """A key generated BEFORE the broker call, from things known before it.

    Deterministic on purpose: a retry of the same intent produces the same key, so a crash
    between `INTENDED` and `SUBMITTED` leaves something a restart can recognise. It contains no
    timestamp for the same reason — a key that changes every attempt cannot identify an attempt.
    """
    parts = [str(p).strip() for p in (ROUTE, ref_day, sleeve, instrument, action, candidate_id)]
    if not all(parts):
        raise OrderJournalRefused(
            BAD_RECORD, f"an idempotency key needs every part; got {parts}")
    return ":".join(parts)


# ── paths ────────────────────────────────────────────────────────────────────────────────

def journal_dir(root: str | Path = ".") -> Path:
    return (Path(root) / ORDERS_DIR).resolve()


def journal_path(day: str, root: str | Path = ".") -> Path:
    """`<root>/global_index/track1_runtime/orders/track1_orders_YYYYMMDD.jsonl`.

    `day` is validated rather than formatted into the name: an eight-digit string is the whole
    of what may appear, so a caller cannot reach outside the journal directory by naming a day
    like `../../etc/passwd` or an absolute path.
    """
    d = str(day).replace("-", "")
    if not (len(d) == 8 and d.isdigit()):
        raise OrderJournalRefused(
            PATH_ESCAPE,
            f"day {day!r} is not YYYYMMDD; a filename is built from it and anything else is a "
            f"way out of the journal directory")
    base = journal_dir(root)
    p = (base / f"track1_orders_{d}.jsonl").resolve()
    # Belt and braces: even with the digit check above, the resolved path must sit inside the
    # journal directory. Two independent checks because one of them is a regex-shaped argument
    # and this one is a fact about the filesystem.
    if base != p.parent:
        raise OrderJournalRefused(
            PATH_ESCAPE, f"{p} resolves outside {base}")
    return p


# ── writing ──────────────────────────────────────────────────────────────────────────────

def _check_amendment(previous: "JournalRecord", record: "JournalRecord") -> None:
    """A second SUBMITTED row is lawful ONLY as the arrival of the broker's order id.

    Stage 5Y. `SUBMITTED -> SUBMITTED` is not a state transition and the state machine is
    right to forbid it. This is an AMENDMENT: the order did not change, we merely learned its
    name. The sequence is forced by the ordering the journal already commits to — SUBMITTED is
    written BEFORE the broker is called, so the id cannot exist yet when that row is written,
    and the receipt arrives while the call is still in flight.

    The rule is narrow on purpose, because a permissive self-transition would let a genuine
    duplicate send look like a legal history:

      * the earlier row must carry NO order id, and this one must carry one — an amendment
        that adds nothing is not an amendment;
      * an id may never be REPLACED. Two ids under one key are two orders, and that is the
        single worst thing this journal could be made to hide;
      * nothing else about the order may move. A different instrument, side, size or day
        under the same key is a different order wearing a borrowed name.
    """
    # Recognition is `st.is_amendment`; the refusals below are this module's, and they say
    # which of the three ways it failed. Keeping recognition in one place is what stops the
    # writer and the readers disagreeing about what a journal means.
    if previous.order_id:
        raise OrderJournalRefused(
            BAD_AMENDMENT,
            f"{record.idempotency_key}: already recorded order id {previous.order_id!r} and "
            f"this row carries {record.order_id!r}. Two ids under one key are two orders")
    if not str(record.order_id or ""):
        raise OrderJournalRefused(
            BAD_AMENDMENT,
            f"{record.idempotency_key}: a second {st.SUBMITTED!r} row that adds no order id "
            f"is not an amendment; it reads as a second send")
    moved = [f for f in ("sleeve", "instrument", "tradable_symbol", "action", "ref_day",
                         "candidate_id")
             if getattr(previous, f) != getattr(record, f)]
    if moved:
        raise OrderJournalRefused(
            BAD_AMENDMENT,
            f"{record.idempotency_key}: an amendment may only add the order id, but "
            f"{moved} changed; a different order under the same key is not an amendment")
    if not st.is_amendment(previous, record):
        # Unreachable given the three checks above, and asserted anyway: if the shared rule
        # and this one ever drift, the row would be written here and rejected on read-back.
        raise OrderJournalRefused(
            BAD_AMENDMENT,
            f"{record.idempotency_key}: the shared amendment rule in track1_order_state "
            f"does not recognise this row, so a reader would call the journal impossible")


def append(record: JournalRecord, *, root: str | Path = ".", day: str | None = None) -> Path:
    """Append one record durably. Raises on ANY failure; never returns a status.

    The transition is validated against what is already on disk for this key, so an illegal
    history cannot be created even by a caller that has lost track of where it was. A record
    whose predecessor is unreadable is refused too: a journal that cannot be read is a journal
    that cannot authorise an order.
    """
    if not isinstance(record, JournalRecord):
        raise OrderJournalRefused(
            BAD_RECORD, f"expected a JournalRecord, got {type(record).__name__}")

    target = journal_path(day or record.ref_day, root)

    existing, invalid = read(root=root, day=day or record.ref_day)
    if invalid:
        raise OrderJournalRefused(
            UNREADABLE,
            f"{len(invalid)} unreadable line(s) in {target.name}: {invalid[:2]}. A journal that "
            f"cannot be read whole cannot authorise an order")

    prior = [r for r in existing if r.idempotency_key == record.idempotency_key]
    if prior:
        previous, last = prior[-1], prior[-1].state
        if last == st.SUBMITTED and record.state == st.SUBMITTED:
            _check_amendment(previous, record)
        elif not st.transition_allowed(last, record.state):
            raise OrderJournalRefused(
                BAD_TRANSITION,
                f"{record.idempotency_key}: {last} -> {record.state} is not a history that "
                f"could have happened; allowed from {last}: "
                f"{sorted(st.ALLOWED_TRANSITIONS.get(last, ()))}")
    elif record.state != st.INTENDED:
        raise OrderJournalRefused(
            BAD_TRANSITION,
            f"{record.idempotency_key}: the first record for a key must be {st.INTENDED!r}, "
            f"not {record.state!r}; an order whose intent was never recorded is exactly what "
            f"this journal exists to make impossible")

    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record.as_row(), ensure_ascii=False, sort_keys=True) + "\n"
    # No try/except. A failure here must reach the caller: the only correct response to "I
    # could not record that I am about to trade" is not to trade.
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    return target


# ── reading ──────────────────────────────────────────────────────────────────────────────

def read(*, root: str | Path = ".", day: str | None = None) -> "tuple[list, list]":
    """`(records, invalid)` for one day, or for every day when `day` is None.

    Invalid lines are RETURNED, never dropped. A reader that silently skips what it cannot
    parse turns a corrupt journal into a clean one, and the whole point of this file is to be
    able to say what actually happened.
    """
    base = journal_dir(root)
    if not base.is_dir():
        return [], []
    files = ([journal_path(day, root)] if day is not None
             else sorted(base.glob("track1_orders_*.jsonl")))
    records: list = []
    invalid: list = []
    for f in files:
        if not f.exists():
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                records.append(JournalRecord(**row))
            except Exception as exc:
                invalid.append(f"{f.name}:{n}: {type(exc).__name__}: {exc}")
    return records, invalid


def resolve(*, root: str | Path = ".", day: str | None = None) -> dict:
    """The journal's own view of where every order got to, refusing to answer if it cannot be
    read whole. Delegates the state rules to `track1_order_state` rather than restating them."""
    records, invalid = read(root=root, day=day)
    if invalid:
        raise OrderJournalRefused(
            UNREADABLE, f"{len(invalid)} unreadable line(s): {invalid[:2]}")
    res = st.resolve_journal([r.as_order_record() for r in records])
    if res["impossible"]:
        raise OrderJournalRefused(
            BAD_TRANSITION,
            f"the journal on disk records a history that cannot have happened: "
            f"{res['impossible']}")
    return {"final": res["final"], "records": records,
            "unresolved": sorted(k for k, s in res["final"].items() if s in st.UNRESOLVED)}
