"""global_index/track1_paper_executor.py — the paper executor skeleton. NEW FILE.

Stage 5W. **Imported by nothing in production, and a test proves it.** This module can, in
principle, call a broker's `send_order` — which is exactly why every other sentence here is
about what stops it.

What it is
----------
The narrow layer between a decision the book has ALREADY made and a broker. It decides nothing:
no bars, no caps, no rules. If a future version of this file needs a strategy rule, the rule is
in the wrong place.

It is assembled from the three pure pieces the previous stages built, and adds no vocabulary of
its own:

    Stage 5T  track1_paper_order    candidate -> Order, and the refusals around it
    Stage 5U  track1_order_state    the state machine and the reconcile verdicts
    Stage 5V  track1_order_journal  the fail-closed write-ahead log

The order of operations, and why it is that order
--------------------------------------------------
    1. refuse unless the cap gate said TAKE
    2. build the Order          (refuses on identity drift, bad qty, missing ref_day)
    3. journal INTENDED         durable, fsynced, fail-closed
    4. journal SUBMITTED        BEFORE the broker call — see Stage 5V
    5. broker.send_order(...)
    6. journal the outcome      FILLED / PARTIAL / REJECTED / UNKNOWN

Steps 3 and 4 are both before step 5 and both raise on failure, so an order can only reach a
broker after the intent to send it is durable on disk. A crash anywhere leaves a journal a
restart can read: nothing after INTENDED means the broker was never reached, and anything
stuck at SUBMITTED means ask.

**Ambiguity is UNKNOWN, never REJECTED.** A broker that raises, times out, or answers with
something this module cannot classify produces `UNKNOWN` and the exception is re-raised. "No"
and "I could not hear you" are different facts, and a filled order recorded as rejected is a
position nobody believes in.

**It never touches the book.** There is no writer for `live_positions.track1.json` here at all
— not a guarded one, none. The executor returns the `Fill` and the caller advances the book,
and only on a confirmed fill. A test asserts this module contains no write to that path.

Why it cannot be used today
----------------------------
Three independent facts, each with a test:

  * it refuses to construct without an ARMED gate, and the real `OrderGate` cannot arm while
    `B1_broker_account_or_legacy_retirement` and `PAPER_SHADOW_EVIDENCE` are open;
  * nothing in `global_index/` or `monitor/` imports it;
  * the scheduler's own slot path, `observe_live_slot`, takes no order gate at all, so there is
    no argument by which a slot could reach this even if the other two changed.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from dataclasses import fields as _fill_fields

from global_index import track1_slots as _ts
from global_index import track1_order_journal as journal
from global_index import track1_order_state as st
from global_index import track1_paper_order as po
from global_index.broker import Fill

#: Refusal codes this module adds. Everything else reuses the codes the pieces already define.
NOT_ARMED = "paper_executor_not_armed"
BOOK_UNREADABLE = "paper_executor_book_unreadable"

#: Where the route's own book lives. Never the legacy file — that path is the first entry in
#: `run_live_day_track1.LEGACY_PATHS`, the list this route must never write.
#: Stage 5ZN corrected this from `global_index/live_positions.track1.json`, which is a path
#: the book has never occupied. Every other component — the slot entry point, the safety jobs'
#: argv, the acceptance reader, the route's own constants table — uses the repository root, and
#: that is where `track1_bootstrap.write` puts it.
#:
#: The consequence was not cosmetic. `read_book` treats a missing file as an empty book, which
#: is right for a route that has never held anything, so this constant made `reconcile_at_
#: startup` compare an ALWAYS-empty book against the broker and conclude the route was flat
#: whatever it actually held. That is "resume flat against a book that is not", in the one
#: object built to prevent it. It never fired because nothing imports this executor.
#:
#: Read from `track1_slots`, not restated, so the two cannot drift apart again.
BOOK_PATH = _ts.TRACK1_POSITIONS_PATH


class PaperExecutorRefused(RuntimeError):
    """The executor would not act. Raised, never returned."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ── what the broker cannot yet do, named rather than discovered ──────────────────────────

#: Stage 5U found these missing on `IBKRBroker` and Stage 5W still needs them. Named here so a
#: future implementer meets the gap in code rather than in production.
REQUIRED_BROKER_METHODS: tuple = ("send_order", "get_positions", "get_order_status",
                                  "cancel_order", "place_stop")

#: CORRECTED IN STAGE 5X. This tuple used to name `get_open_orders` and `get_executions`, and
#: both entries were wrong:
#:
#:   * the execution lookup EXISTS, spelled `find_execution(order_id, inst)`. Stage 5W tested
#:     `hasattr(IBKRBroker, "get_executions")`, which is true-but-useless — it measured a name
#:     nobody had ever proposed rather than the capability.
#:   * `get_open_orders` did not exist as a method, but `reqAllOpenOrders()` was already
#:     called at five sites inside `ibkr_broker.py`. The API surface was never the gap, and
#:     Stage 5X added the method in a dozen lines.
#:
#: So the method list is empty now, and the real remaining gap is not a method at all.
MISSING_BROKER_METHODS: tuple = ()

#: Whether `broker.Fill` carries the broker's own order id. Stage 5W measured this as False
#: and Stage 5Y closed it: the field exists now, defaulted to None and appended last so no
#: legacy caller moved. Read from the dataclass rather than asserted, because the point of
#: the original finding was that nobody had checked.
FILL_CARRIES_ORDER_ID = "order_id" in {f.name for f in _fill_fields(Fill)}

#: The name of the keyword that asks a broker to report its order id at PLACEMENT time,
#: before the outcome is known. A broker that does not accept it is not broken — it simply
#: cannot report early, and the reconcile falls back to the Stage 5X working-order path.
SUBMIT_CALLBACK = "on_submit"

#: What is left once the id exists. Kept as a value because the previous two versions of this
#: constant were both wrong and both went unnoticed until someone read the broker file.
INTERIM_UNKNOWN_RESOLUTION = (
    "an unresolved order is identified by its broker order id when one was recorded — which "
    "is now the ordinary case, because the receipt is journalled before the fill poll begins. "
    "Without an id it falls back to the working-order book matched on instrument AND action, "
    "and finally to positions, which never resolve an order on their own. See "
    "track1_broker_read.resolve_submitted.")


def accepts_receipt(broker: Any) -> bool:
    """Can this broker report its order id at placement time? Measured, not assumed."""
    import inspect

    send = getattr(broker, "send_order", None)
    if not callable(send):
        return False
    try:
        return SUBMIT_CALLBACK in inspect.signature(send).parameters
    except (TypeError, ValueError):
        return False


def broker_capability_report(broker: Any) -> dict:
    """What this broker can and cannot do, as data. No call is made on it."""
    have = {m for m in REQUIRED_BROKER_METHODS + MISSING_BROKER_METHODS
            if callable(getattr(broker, m, None))}
    return {
        "required_present": sorted(m for m in REQUIRED_BROKER_METHODS if m in have),
        "required_absent": sorted(m for m in REQUIRED_BROKER_METHODS if m not in have),
        "optional_present": sorted(m for m in MISSING_BROKER_METHODS if m in have),
        "optional_absent": sorted(m for m in MISSING_BROKER_METHODS if m not in have),
        "reports_order_id_at_placement": accepts_receipt(broker),
        "fill_carries_order_id": FILL_CARRIES_ORDER_ID,
        "interim_unknown_resolution": INTERIM_UNKNOWN_RESOLUTION,
    }


# ── the gate, as production actually answers it ───────────────────────────────

@dataclass(frozen=True)
class ProductionGate:
    """`track1_gates` answers with `(bool, reasons)`; the executor asks for `.allow_orders`.

    This is the adapter, and it exists so the refusal can be demonstrated against the REAL
    blocker table rather than against a hand-made stand-in. A test builds one and watches the
    executor refuse it. Nothing else constructs it.
    """

    allow_orders: bool
    reasons: tuple = ()


def production_gate() -> ProductionGate:
    """What the gate says right now, with no confirmations granted — which is the only state
    it has ever been in. `blocks_orders` blockers include the two MEASURED ones, so this is a
    live measurement, not a constant."""
    from global_index import track1_gates as G

    allowed, reasons = G.may_enable_orders()
    return ProductionGate(allow_orders=bool(allowed), reasons=tuple(reasons))


# ── the book, read back ──────────────────────────────────────────────────────────────────

#: The shape `track1_bootstrap.snapshot_book` actually writes — read from that function, not
#: guessed. It says `qty`, and a reader that asked for `contracts` would have refused every
#: genuine book while looking fail-closed. `contracts` is accepted only because `broker.Order`
#: spells it that way and a hand-written fixture will reach for it.
QTY_KEYS: tuple = ("qty", "contracts")
BOOK_SCHEMA: int = 2


def _stop_candidate_id(plan: Any, ref_day: Any) -> str:
    """A stable identifier for a protective stop's journal key.

    The key refuses an empty part, and it is right to: a key missing a component collides with
    every other key missing the same one. A plan that travelled with a candidate carries its
    trade id; a plan built for a position being repaired may not, so the fallback SAYS what it
    is rather than inventing something that looks like a trade id.
    """
    tid = str((getattr(plan, "detail", None) or {}).get("trade_id") or "")
    return tid or f"stop:{plan.inst}:{plan.ref_day or ref_day}"


def _open_candidate_id(plan: Any, ref_day: Any) -> str:
    """Same rule as `_stop_candidate_id`, for an entry leg."""
    tid = str((getattr(plan, "detail", None) or {}).get("trade_id") or "")
    return tid or f"open:{plan.inst}:{plan.ref_day or ref_day}"


def read_book(path: str | Path = BOOK_PATH) -> "tuple[list, str]":
    """`(positions, detail)` from the route's own book. Fails CLOSED.

    A missing file is an empty book and is fine — the route has held nothing yet. A file that
    exists and cannot be parsed is NOT an empty book: it raises, because "I could not read what
    I hold" answered as "I hold nothing" is the shape that lets a reconcile pass over a real
    position. That is the `scheduler_processes() -> []` mistake, in the one place it would put
    size on the wrong side.

    It also refuses a book stamped with another route or another schema. `live_positions.json`
    and `live_positions.track1.json` are the same shape, so a mistaken path would otherwise
    read as a valid answer to the wrong question.
    """
    import json

    p = Path(path)
    if not p.exists():
        return [], f"{p} does not exist; the route has held nothing yet"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        rows = raw.get("positions", raw) if isinstance(raw, dict) else raw
        if isinstance(raw, dict):
            route = raw.get("route")
            if route is not None and str(route) != journal.ROUTE:
                raise ValueError(f"book is stamped route={route!r}, not {journal.ROUTE!r}")
            schema = raw.get("schema_version")
            if schema is not None and int(schema) != BOOK_SCHEMA:
                raise ValueError(f"book schema {schema} is not {BOOK_SCHEMA}")
        out = []
        for r in rows:
            qty = next((r[k] for k in QTY_KEYS if k in r), None)
            if qty is None:
                raise ValueError(f"position row has none of {QTY_KEYS}: {sorted(r)}")
            out.append(st.Position(instrument=str(r["instrument"]),
                                   direction=str(r["direction"]),
                                   contracts=int(qty)))
    except Exception as exc:
        raise PaperExecutorRefused(
            BOOK_UNREADABLE,
            f"{p} exists and could not be read ({type(exc).__name__}: {exc}); an unreadable "
            f"book is not an empty one")
    return out, f"{len(out)} position(s) from {p}"


# ── the executor ─────────────────────────────────────────────────────────────────────────

#: Stage 5ZN refusal codes. One per condition; "it refused" is not a diagnosis.
NO_BOOK = "book_unreadable"
NO_SUCH_POSITION = "no_such_position_in_book"
NO_PLANNED_STOP = "no_planned_stop"
NOT_SAME_SYMBOL = "not_the_same_symbol"


@dataclass(frozen=True)
class Intent:
    """One operation this stage is willing to describe and unwilling to perform.

    It exists so a caller receives something that is obviously NOT a fill. A method that
    returned `None` on the way to a future send would be indistinguishable from one that had
    sent and got nothing back.
    """
    kind: str
    order: Any
    record: Any
    planned_stop: Any
    reduces_exposure: bool
    detail: str
    sent: bool = False


@dataclass(frozen=True)
class SwitchIntent:
    close: Intent
    open: Intent

    @property
    def sent(self) -> bool:
        return False


@dataclass
class Track1OrderExecutor:
    """Turns admitted decisions into broker calls. Decides nothing.

    `gate` must report `allow_orders is True`. That is not the safety story on its own — a test
    can hand it anything — but combined with "nothing imports this" and "the slot path has no
    gate", it means there is no path from the scheduler to a broker through this object.
    """

    broker: Any
    gate: Any
    journal_root: str | Path = "."
    #: Injected so a test can pin it. Never read from the wall clock inside a branch.
    now_fn: Any = None

    def __post_init__(self) -> None:
        if not bool(getattr(self.gate, "allow_orders", False)):
            raise PaperExecutorRefused(
                NOT_ARMED,
                "the order gate does not permit orders. Construction is refused rather than "
                "each call, so an unarmed executor cannot exist to be called by mistake")
        missing = broker_capability_report(self.broker)["required_absent"]
        if missing:
            raise PaperExecutorRefused(
                NOT_ARMED,
                f"the broker is missing {missing}; an executor that cannot place or query an "
                f"order must not be built to find that out later")

    # ── helpers ─────────────────────────────────────────────────────────────
    def _now(self) -> str:
        fn = self.now_fn or (lambda: _dt.datetime.now(_dt.timezone.utc))
        return fn().isoformat(timespec="seconds")

    def _record(self, *, key, state, order, ref_day, slot_id, candidate_id, **kw):
        return journal.JournalRecord(
            idempotency_key=key, state=state, ref_day=str(ref_day),
            sleeve=order.cluster, instrument=order.inst,
            tradable_symbol=po.tradable_symbol(order.inst), action=order.action,
            candidate_id=str(candidate_id), created_at=self._now(),
            slot_id=str(slot_id or ""), **kw)

    @staticmethod
    def _classify(fill: Any) -> str:
        """A broker `Fill` -> one journal state. Anything unrecognised is UNKNOWN."""
        status = str(getattr(fill, "status", "") or "").upper()
        if status == "FILLED":
            return st.FILLED
        if status == "PARTIAL":
            return st.PARTIAL
        if status in ("CANCELLED", "FAILED", "REJECTED"):
            return st.REJECTED
        return st.UNKNOWN

    # ── Stage 5ZN: the other three verbs, as INTENT only ─────────────────────
    #
    # `open_position` (Stage 5W) hands its order to whatever broker it was built with. These
    # three deliberately do not: they run every refusal, write the INTENDED journal row, and
    # return the intent. The send step is not built, and that asymmetry is the point of this
    # stage rather than an omission — the brief is explicit that no broker order may be placed
    # here, and a method that could send is a method somebody can call.
    #
    # Everything they refuse, they refuse BEFORE the journal row exists, so a refused
    # operation leaves no trace that a later reader could mistake for an attempt.

    def _book_positions(self, book_path: "str | Path | None" = None) -> "tuple[list, str]":
        """The route's own book, or a reason it could not be read. Never a synthesised empty.

        Stage 5ZN, and the distinction matters the day paper starts: an absent book and a flat
        book are different facts, and a path that turns the first into `positions: []` hides
        exactly the state a restart must not guess at.
        """
        return read_book(Path(book_path) if book_path is not None
                         else Path(self.journal_root) / BOOK_PATH)

    def close_position(self, held: Any, reason: str, *, ref_day, slot_id: str = "",
                       book_path=None) -> Any:
        """Intend to close a position the BOOK says exists. Sends nothing.

        Refuses when the book holds no matching position, because a close for something the
        route does not believe it holds is either a duplicate or an instruction to open the
        opposite side — and the broker cannot tell those apart either.
        """
        bp = (Path(book_path) if book_path is not None
              else Path(self.journal_root) / BOOK_PATH)
        if not bp.exists():
            # Stage 5ZN. `read_book` treats a missing file as an empty book, which is right
            # for a route that has never held anything — but it is NOT right here. A close
            # asked for against a book that was never written is not a close against a flat
            # book; it is a close nobody can check. Refused rather than absorbed.
            raise PaperExecutorRefused(
                NO_BOOK,
                f"{bp} does not exist, so there is no book to close against. A missing book "
                f"and a flat book are different facts and must not be answered the same way")
        positions, detail = self._book_positions(bp)
        inst = str(getattr(held, "instrument", "") or getattr(held, "inst", "") or "")
        match = [x for x in positions if str(getattr(x, "instrument", "")) == inst]
        if not match:
            raise PaperExecutorRefused(
                NO_SUCH_POSITION,
                f"the book holds no {inst!r}, so there is nothing to close; "
                f"{len(positions)} position(s) are open")
        sleeve = str(getattr(held, "sleeve", "") or getattr(held, "cluster", "") or "")
        qty = int(getattr(match[0], "contracts", 0) or 0)
        if qty <= 0:
            raise PaperExecutorRefused(
                NO_SUCH_POSITION,
                f"the book row for {inst} carries {qty} contract(s), which closes nothing")

        order = po.Order(inst=inst, action="CLOSE",
                         direction=str(getattr(match[0], "direction", "")),
                         contracts=qty, cluster=sleeve, ref_day=str(ref_day))
        key = journal.idempotency_key(ref_day=str(ref_day), instrument=inst,
                                      sleeve=sleeve, action="CLOSE",
                                      candidate_id=str(reason))
        rec = self._record(key=key, state=st.INTENDED, order=order, ref_day=ref_day,
                           slot_id=slot_id, candidate_id=str(reason), qty=qty)
        journal.append(rec, root=self.journal_root)
        return Intent(kind="close", order=order, record=rec, planned_stop=None,
                      reduces_exposure=True,
                      detail=f"intend to close {qty} {inst} ({reason}); nothing was sent")

    def place_protective_stop(self, held: Any, *, plan=None, ref_day, slot_id: str = "") -> Any:
        """Intend to place the protective stop this entry was admitted with. Sends nothing.

        Refuses without a plan, and that refusal is the whole reason Stage 5ZN exists: a
        protective stop invented at placement time is not the stop the strategy decided on, and
        nothing downstream could tell the difference.
        """
        from global_index import track1_planned_stop as ps

        if plan is None:
            plan = getattr(held, "planned_stop", None)
        if plan is None:
            raise PaperExecutorRefused(
                NO_PLANNED_STOP,
                f"{getattr(held, 'instrument', getattr(held, 'inst', '?'))}: no planned stop "
                f"travelled with this position, so the only stop available would be one "
                f"invented here — which is not the stop the strategy admitted")
        if ps._num(getattr(plan, "stop_price", None)) is None:
            raise PaperExecutorRefused(
                NO_PLANNED_STOP,
                f"{plan.inst}: the plan carries no usable stop price")

        order = po.Order(inst=plan.inst, action="STOP", direction=plan.direction,
                         contracts=int(plan.qty), cluster=plan.sleeve, ref_day=str(ref_day))
        key = journal.idempotency_key(ref_day=str(ref_day), instrument=plan.inst,
                                      sleeve=plan.sleeve, action="STOP",
                                      candidate_id=_stop_candidate_id(plan, ref_day))
        rec = self._record(key=key, state=st.INTENDED, order=order, ref_day=ref_day,
                           slot_id=slot_id or plan.slot_id,
                           candidate_id=_stop_candidate_id(plan, ref_day),
                           qty=int(plan.qty),
                           planned_stop_price=float(plan.stop_price),
                           planned_stop_type=str(plan.stop_type),
                           planned_stop_distance=plan.stop_distance)
        journal.append(rec, root=self.journal_root)
        return Intent(kind="protective_stop", order=order, record=rec, planned_stop=plan,
                      reduces_exposure=True,
                      detail=f"intend {plan.one_line()}; nothing was sent")

    def switch_same_symbol(self, decision: Any, displaced: Any, *, ref_day,
                           slot_id: str = "", book_path=None) -> Any:
        """Intend to replace one position with another on the same symbol. Sends nothing.

        TWO legs, journalled separately, and that is the finding this method exists to fix.
        `track1_switch` is imported by nothing and calls `send_order` at two sites with no
        journal at all — so if it were ever wired, two orders would leave one record between
        them, or none. The close is intended first: a switch that opened before it closed would
        double the exposure on that symbol for however long the gap lasted.
        """
        close_intent = self.close_position(displaced, "switch", ref_day=ref_day,
                                           slot_id=slot_id, book_path=book_path)
        open_order, plan = po.plan_entry(getattr(decision, "candidate", decision),
                                         ref_day=ref_day, slot_id=slot_id)
        if plan.inst != close_intent.order.inst:
            raise PaperExecutorRefused(
                NOT_SAME_SYMBOL,
                f"a same-symbol switch was asked for {close_intent.order.inst} out and "
                f"{plan.inst} in; those are two different trades and must not share one "
                f"decision")
        key = journal.idempotency_key(ref_day=str(ref_day), instrument=plan.inst,
                                      sleeve=plan.sleeve, action="OPEN",
                                      candidate_id=_open_candidate_id(plan, ref_day))
        rec = self._record(key=key, state=st.INTENDED, order=open_order, ref_day=ref_day,
                           slot_id=slot_id, candidate_id=_open_candidate_id(plan, ref_day),
                           qty=int(plan.qty),
                           planned_stop_price=float(plan.stop_price),
                           planned_stop_type=str(plan.stop_type),
                           planned_stop_distance=plan.stop_distance)
        journal.append(rec, root=self.journal_root)
        open_intent = Intent(kind="open", order=open_order, record=rec, planned_stop=plan,
                             reduces_exposure=False,
                             detail=f"intend to open {plan.one_line()}; nothing was sent")
        return SwitchIntent(close=close_intent, open=open_intent)

    # ── the one operation this skeleton implements ──────────────────────────
    def open_position(self, decision: Any, *, ref_day, slot_id: str = "") -> Any:
        """Place the entry for an ADMITTED decision. Returns the broker's `Fill`.

        Writes nothing to the book. The caller advances it, and only on a confirmed fill.
        """
        po.assert_admitted(decision)
        cand = decision.candidate
        order = po.candidate_to_order(cand, ref_day=ref_day, action="OPEN")

        key = journal.idempotency_key(
            sleeve=order.cluster, instrument=order.inst, ref_day=str(ref_day),
            action=order.action, candidate_id=str(cand.trade_id))
        common = dict(key=key, order=order, ref_day=ref_day, slot_id=slot_id,
                      candidate_id=cand.trade_id)

        # 1. intent, durable, before anything else. Raises on failure — and that is the point.
        journal.append(self._record(state=st.INTENDED, **common), root=self.journal_root)
        # 2. and the attempt, BEFORE the call, so a crash inside send_order is attributable.
        journal.append(self._record(state=st.SUBMITTED, **common), root=self.journal_root)

        # The receipt, when the broker can give one. It fires while `send_order` is still in
        # flight — after placement, before the fill poll — and writes a second SUBMITTED row
        # carrying the id. That row is an amendment, not a second order, and the journal
        # enforces the difference.
        #
        # It is NOT wrapped in a try. If the id cannot be journalled the order is already
        # live and unrecorded, and the only honest response is to stop; `send_order` raises
        # that straight past its own error handling so a live order is never reported as
        # cancelled.
        seen_id: dict = {}

        def _receipt(r):
            oid = str(getattr(r, "order_id", "") or "")
            if not oid:
                return              # nothing learned; the row would not be an amendment
            seen_id["order_id"] = oid
            journal.append(self._record(state=st.SUBMITTED, order_id=oid, **common),
                           root=self.journal_root)

        kwargs = {SUBMIT_CALLBACK: _receipt} if accepts_receipt(self.broker) else {}
        try:
            fill = self.broker.send_order(order, **kwargs)
        except BaseException as exc:
            # UNKNOWN, not REJECTED. The order may be live; we simply cannot see it. If the
            # receipt arrived first the id goes on this row, which is the difference between
            # an unresolved order we can ask about and one we cannot.
            journal.append(
                self._record(state=st.UNKNOWN, error=f"{type(exc).__name__}: {exc}",
                             order_id=seen_id.get("order_id", ""), **common),
                root=self.journal_root)
            raise

        state = self._classify(fill)
        # The id from the outcome, falling back to the one the receipt already reported. They
        # agree in the ordinary case; the fallback covers a broker that fires a receipt and
        # then returns a Fill without one. Still empty means the broker never named the
        # order, and the reconcile says so rather than guessing.
        outcome_id = str(getattr(fill, "order_id", "") or "") or seen_id.get("order_id", "")
        journal.append(self._record(
            state=state,
            order_id=outcome_id,
            fill_status=str(getattr(fill, "status", "") or ""),
            filled_qty=int(getattr(fill, "filled_qty", 0) or 0),
            avg_price=float(getattr(fill, "avg_price", 0.0) or 0.0),
            commission=float(getattr(fill, "commission", 0.0) or 0.0),
            error=str(getattr(fill, "error_msg", "") or ""),
            **common), root=self.journal_root)
        return fill

    # ── what a restart asks ─────────────────────────────────────────────────
    def unresolved(self, *, day=None) -> list:
        """Keys whose last journal state leaves the route unable to say what it holds."""
        return journal.resolve(root=self.journal_root, day=day)["unresolved"]

    def reconcile_at_startup(self, *, broker_positions: Sequence, broker_settled: bool = True,
                             legacy_book: Sequence = (), shared_account: bool = True,
                             day=None) -> st.ReconcileResult:
        """The Stage 5U contract, wired to this route's own book and journal.

        The broker's positions are passed IN rather than fetched here, so this stays testable
        without a socket and so the caller owns the decision to open one.
        """
        book, _detail = read_book(Path(self.journal_root) / BOOK_PATH)
        records, invalid = journal.read(root=self.journal_root, day=day)
        if invalid:
            raise journal.OrderJournalRefused(
                journal.UNREADABLE,
                f"{len(invalid)} unreadable journal line(s); a journal that cannot be read "
                f"whole cannot authorise anything: {invalid[:2]}")
        return st.reconcile(book, broker_positions, broker_settled=broker_settled,
                            journal=[r.as_order_record() for r in records],
                            legacy_book=legacy_book, shared_account=shared_account)
