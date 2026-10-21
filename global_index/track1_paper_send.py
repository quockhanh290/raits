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


def _candidate_qty(cand: Any, fill: Any = None) -> int:
    """How many contracts this candidate is for. Reads `qty` FIRST, and that is the whole point.

    `track1_signal_layer.Candidate` -- the object every Track 1 slot passes in here -- declares
    `qty` and has no `contracts` field at all. Both writers below read
    `getattr(cand, "contracts", 0)`, which therefore returned 0 for every real fill.

    Measured on the first NKD paper fill, 2026-09-25 01:25 ET: the broker filled MNKD x1 at
    66,145 and order 40 was journalled FILLED, while the book recorded a position of size ZERO
    and the trade log recorded contracts 0. The comment two lines above the book writer said, in
    so many words, that a zero-size row is "the empty book by another route" -- so the rule was
    written down correctly and the line under it broke the rule. A position that exists at the
    broker and reads as zero in the book is worse than a missing row: a missing row is an ORPHAN
    and shouts, a zero row looks booked.

    `contracts` stays as a fallback because `broker.Order` spells it that way and a hand-written
    fixture reaches for it. The fill's own count comes last on purpose: it has reported 0 on all
    three paper fills so far, which is why nothing here may be keyed on it.
    """
    for src, name in ((cand, "qty"), (cand, "contracts"), (fill, "filled_qty")):
        if src is None:
            continue
        try:
            n = int(getattr(src, name, 0) or 0)
        except (TypeError, ValueError):
            continue
        if n:
            return n
    return 0


def _entry_day_from_entry_time(entry_time: Any) -> str | None:
    """The book's day field is derived from the measured entry clock, never guessed.

    Track 1's stop deferral rule reads `entry_day`, while the live writer naturally has
    `entry_time`.  Leaving the day absent makes a fresh swing position look not-deferred
    to the protection tools; deriving it here keeps the two dialects equivalent without
    inventing a date when the clock itself is absent.
    """
    raw = str(entry_time or "").strip()
    return raw[:10] if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-" else None


def advance_book(fill: Any, decision: Any, *, book_path: "str | Path") -> bool:
    """Put a CONFIRMED fill into the route's book. True if a row was added.

    The half of the contract that was written and never built. `track1_paper_executor` states
    it plainly — "It never touches the book… The executor returns the Fill and the caller
    advances the book, and only on a confirmed fill" — and the caller counted the Fill and
    dropped it. Measured 2026-09-24, the first armed day: two orders FILLED at the broker and
    the book came out of the session with `positions: []`. Everything downstream reads that
    book, so all of it went blind at once — the safety net had nothing to protect, the 14h stop
    arming had no position to arm, and the only thing that noticed was the B3 reconciler, which
    halted new entries on a mismatch the route had created itself.

    Written here rather than in the executor because that module's no-writer property is pinned
    by a test, and it is worth keeping: the thing that talks to the broker and the thing that
    records state stay separable.

    ONLY a confirmed fill. `unknown` is not `rejected` and neither is a position — an order
    whose fate nobody heard may or may not exist, and a book row invented from one produces the
    same mismatch as today's pointing the other way, which is harder to reason about.

    Fails CLOSED and never by starting a fresh book over one it could not read: overwriting
    would drop positions the route really holds, which is worse than failing to add this one.

    `book_path` is REQUIRED (2026-09-24, evening). It defaulted to the module's production
    path, and that default is how the order-layer suites wrote fixture rows into the live
    book the same afternoon. A writer of route state takes its destination from the caller
    or does not run.
    """
    import json

    # Imported here, like every other consumer in this module: the gate check at the top of
    # `maybe_send_orders` must stay ABOVE the order-layer imports, and a module-level import
    # here would put one below nothing at all.
    from global_index import track1_order_state as st
    from global_index.track1_order_journal import ROUTE

    status = str(getattr(fill, "status", "") or "").lower()
    if status != st.FILLED:
        return False

    cand = getattr(decision, "candidate", None)
    if cand is None:
        raise SendRefused("no_candidate_on_decision: cannot book a fill with no candidate")

    from global_index.track1_paper_executor import BOOK_SCHEMA

    p = Path(book_path)
    raw = json.loads(p.read_text(encoding="utf-8"))       # raises on a book it cannot parse
    if not isinstance(raw, dict):
        raise SendRefused(f"book at {p} is not an object; refusing to write over it")
    route = raw.get("route")
    if route is not None and str(route) != ROUTE:
        raise SendRefused(f"book at {p} is stamped route={route!r}, not {ROUTE!r}")
    schema = raw.get("schema_version")
    if schema is not None and int(schema) != BOOK_SCHEMA:
        raise SendRefused(f"book at {p} is schema {schema}, not {BOOK_SCHEMA}")

    rows = list(raw.get("positions") or [])
    trade_id = str(getattr(cand, "trade_id", "") or "")
    qty = _candidate_qty(cand, fill)
    if trade_id and any(str(r.get("trade_id")) == trade_id for r in rows):
        # The 2026-09-24 signal persisted across three slots and re-sent under one idempotency
        # key each time. A row per slot would report three contracts against the broker's one.
        return False

    # `qty` comes from the CANDIDATE, not from the fill. Measured the same day: both fills
    # carried `fill_status=FILLED` with `filled_qty=0`, so a book keyed on the fill's own count
    # would have written a zero-size position — the empty book by another route. The fill's
    # figure is kept beside it, unused by the reader, so the discrepancy stays visible instead
    # of being quietly resolved in favour of whichever field was picked.
    sleeve = str(getattr(decision, "sleeve", "") or getattr(cand, "sleeve", "") or "")
    instrument = str(getattr(cand, "instrument", "") or "")
    direction = str(getattr(cand, "direction", "") or "")
    entry_time = str(getattr(cand, "entry_time", "") or "")
    rows.append({
        "trade_id": trade_id,
        "sleeve": sleeve,
        "cluster": sleeve,
        "instrument": instrument,
        "inst": instrument,
        "direction": direction,
        "qty": qty,
        "contracts": qty,
        "risk_dollars": float(getattr(cand, "risk_dollars", 0.0) or 0.0),
        "entry_day": _entry_day_from_entry_time(entry_time),
        "entry_time": entry_time,
        "exit_time": None,
        "exit_day": None,
        "pnl_sized": 0.0,
        "exit_pending": False,
        "entry_price": getattr(fill, "avg_price", None) or getattr(cand, "entry_price", None),
        "stop_price": getattr(cand, "stop_price", None),
        "stop_order_id": None,
        "booked_from": "paper_send.advance_book",
        "order_id": str(getattr(fill, "order_id", "") or ""),
        "fill_reported_qty": getattr(fill, "filled_qty", None),
        "exit_reason": None,
        "contract_month": None,
    })
    raw["positions"] = rows
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(raw, indent=1, default=str), encoding="utf-8")
    tmp.replace(p)
    return True


def record_broker_equity(broker: Any, *, book_path: "str | Path") -> bool:
    """Write the broker mark only when this slot actually measured one.

    This is deliberately separate from `advance_book`: a fresh Track1Book's `equity` is the
    account constant until a measured route mark is restored, and serialising that default would
    arm the breaker on a plausible-looking invention. The broker mark is reconciliation context
    only; it is stored beside the route's breaker marks and never copied into them.
    """
    import json

    get_equity = getattr(broker, "get_equity", None)
    if not callable(get_equity):
        return False
    try:
        mark = float(get_equity())
    except Exception:                                             # noqa: BLE001
        return False

    from global_index.track1_paper_executor import BOOK_SCHEMA
    from global_index.track1_order_journal import ROUTE

    p = Path(book_path)
    raw = json.loads(p.read_text(encoding="utf-8"))       # raises on a book it cannot parse
    if not isinstance(raw, dict):
        raise SendRefused(f"book at {p} is not an object; refusing to write over it")
    route = raw.get("route")
    if route is not None and str(route) != ROUTE:
        raise SendRefused(f"book at {p} is stamped route={route!r}, not {ROUTE!r}")
    schema = raw.get("schema_version")
    if schema is not None and int(schema) != BOOK_SCHEMA:
        raise SendRefused(f"book at {p} is schema {schema}, not {BOOK_SCHEMA}")

    raw["broker_equity"] = mark
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(raw, indent=1, default=str), encoding="utf-8")
    tmp.replace(p)
    return True


def append_trade_open(fill: Any, decision: Any, *, trade_log_path: "str | Path",
                      ref_day: Any = None, slot_id: str = "",
                      booked_from: str = "paper_send.append_trade_open") -> bool:
    """Put a CONFIRMED fill into the route's trade log as an OPEN row. True if a row was added.

    The third record of one fact. Measured 2026-09-24: `trade_log.track1.jsonl` held 0 rows,
    last written 2026-08-25, while two orders filled that afternoon. The fills reached the
    order journal; the book was wired this afternoon (`advance_book`); nothing wrote the trade
    log. The safety sweeps append CLOSE rows to this file (Stage 5ZG gave them the path and the
    route tag), so without an OPEN row every close the route ever books would be a close of a
    position the log never saw opened, and no P&L series can be built from half a round trip.

    Shape: the same keys the legacy runner writes for an OPEN (`runner.py`, H4 path F), so one
    reader can read both files, plus the Track 1 identity (`route`, `trade_id`, `order_id`,
    `slot_id`) a reader needs to join it to the journal and the book.

    `filled_qty` follows the broker's own convention and the legacy writer's reading of it:
    `broker.Fill.filled_qty` documents 0 as "full fill", and `runner.py` writes
    `filled_qty or n`. Both of 2026-09-24's fills reported 0. The raw figure is kept beside it
    as `fill_reported_qty` so nobody has to trust this function's reading of it.

    Idempotent on `trade_id`: the 2026-09-24 signal persisted across three slots and re-sent
    under one idempotency key each time; a row per slot would triple the entry.

    `trade_log_path` is REQUIRED, for the reason `advance_book`'s book path is.
    """
    import datetime as _dt
    import json

    from global_index import track1_order_state as st
    from global_index.track1_order_journal import ROUTE

    status = str(getattr(fill, "status", "") or "").lower()
    if status != st.FILLED:
        return False
    cand = getattr(decision, "candidate", None)
    if cand is None:
        raise SendRefused("no_candidate_on_decision: cannot log a fill with no candidate")

    p = Path(trade_log_path)
    trade_id = str(getattr(cand, "trade_id", "") or "")
    if trade_id and p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue                      # a torn line is the reader's to report, not ours
            if (isinstance(r, dict) and str(r.get("type")) == "OPEN"
                    and str(r.get("trade_id")) == trade_id):
                return False

    contracts = _candidate_qty(cand, fill)
    direction = str(getattr(cand, "direction", "") or "")
    expected = getattr(cand, "entry_price", None)
    price = getattr(fill, "avg_price", None)
    reported = getattr(fill, "filled_qty", None)
    slip = None
    if isinstance(expected, (int, float)) and isinstance(price, (int, float)) and price:
        # Adverse is positive, the legacy log's sign: a LONG filled above the signal paid up.
        slip = (price - expected) if direction.upper() == "LONG" else (expected - price)
    entry_time = str(getattr(cand, "entry_time", "") or "")
    row = {
        "type": "OPEN",
        "route": ROUTE,
        "trade_id": trade_id,
        "inst": str(getattr(cand, "instrument", "") or ""),
        "cluster": str(getattr(decision, "sleeve", "") or getattr(cand, "sleeve", "") or ""),
        "direction": direction,
        "contracts": contracts,
        "entry_day": entry_time[:10] or (str(ref_day) if ref_day is not None else None),
        "entry_time": entry_time or None,
        "expected_entry": expected,
        "fill_price": price,
        "slip": slip,
        "commission": getattr(fill, "commission", None),
        "filled_qty": (reported or contracts) if isinstance(reported, int) else contracts,
        "fill_reported_qty": reported,
        "status": "FILLED",
        "stop_price": getattr(cand, "stop_price", None),
        "risk_dollars": getattr(cand, "risk_dollars", None),
        "regime": getattr(decision, "regime", None) or getattr(cand, "regime", None),
        "order_id": str(getattr(fill, "order_id", "") or ""),
        "slot_id": slot_id or None,
        "booked_from": booked_from,
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    return True


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
            # The other half of the executor's contract. Outside the try above on purpose: a
            # book that could not be advanced is not an order whose fate is unknown — the order
            # filled and is known. It is a RECORDING failure, and flattening the two would file
            # the more recoverable problem under the less recoverable one.
            try:
                # UNDER `root`, never the bare production path. Defaulting to the module
                # constant is how running the order-layer suites on 2026-09-24 wrote two test
                # fixtures — entry 5000.0, order_id "OID-1", qty 0 — straight into the live
                # `live_positions.track1.json`, the file the safety net and the reconciler both
                # trust. The executor already does it this way (`journal_root / BOOK_PATH`);
                # this line had not.
                from global_index.track1_paper_executor import BOOK_PATH as _BP
                advance_book(fill, decision, book_path=Path(root) / _BP)
                record_broker_equity(broker, book_path=Path(root) / _BP)
            except BaseException as exc:                              # noqa: BLE001
                errors.append(
                    f"BOOK NOT ADVANCED for "
                    f"{getattr(getattr(decision, 'candidate', None), 'trade_id', '?')}: "
                    f"{type(exc).__name__}: {exc} — the order FILLED and the book does not "
                    f"know; reconcile before the next session")
            # The third record, in its own try: a book that could not be written must not
            # also cost the trade log its row, and the other way round. Each failure names
            # which record is missing, because the repair for each is different.
            try:
                from global_index.track1_report import TRADE_LOG as _TL
                append_trade_open(fill, decision, trade_log_path=Path(root) / _TL,
                                  ref_day=ref_day, slot_id=slot_id)
            except BaseException as exc:                              # noqa: BLE001
                errors.append(
                    f"TRADE LOG NOT WRITTEN for "
                    f"{getattr(getattr(decision, 'candidate', None), 'trade_id', '?')}: "
                    f"{type(exc).__name__}: {exc} — the order FILLED and the trade log has no "
                    f"OPEN row; P&L for this trade cannot be built until it is back-filled")
        elif status == st.PARTIAL:
            partial += 1
        elif status == st.REJECTED:
            rejected += 1
        else:
            unknown += 1

    return SendSummary(status=SENT, offered=offered, admitted=len(admitted), sent=sent,
                       filled=filled, partial=partial, rejected=rejected, unknown=unknown,
                       errors=errors, executor_built=True)
