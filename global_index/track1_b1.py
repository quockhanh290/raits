"""Is the legacy route flat, at the broker, with nothing working behind it?

B1 exists because one IB Gateway login is one position book. `IBKRBroker.get_positions()`
reads `ib.positions()` unfiltered and `get_equity()` reads NetLiquidation unfiltered, so two
routes on one login do not coexist as two books — they coexist as one net signed quantity per
contract that no reconcile can decompose.

Until this module, B1 was released by a signature and by nothing else. A person writing
`legacy_retired_confirmed: true` asserted a fact about an account, and nothing ever asked the
account. This module asks, and the gate now requires both: the decision AND the proof.

Why zero is answerable on a shared account
------------------------------------------
Attribution is the whole difficulty of B1 — a Flex statement cannot say which route a fill
belonged to. But attribution only matters when something is NONZERO. Zero positions and zero
working orders is unambiguous no matter how many routes share the login: there is nothing to
attribute. That is the one shape of this question a shared account can answer, and it is why
the broker half of B1 is closable at all.

The corollary is the rule this module enforces everywhere: any nonzero broker position or
working order on a shared account is UNKNOWN-or-FAIL and never PASS, because the route it
belongs to cannot be established from the broker.

Absence is never a pass
-----------------------
A missing book cannot testify that nothing is held. A broker that could not be queried has not
said the account is flat. An empty list from a collector that swallows its own exception is
not an answer. Each of those is UNKNOWN, and UNKNOWN holds the gate — the same rule the window
ledger applies to slots and the checkpoint reader applies to a missing book.

What this module does NOT do
----------------------------
It does not close, cancel, arm, or write anything except its own evidence record. It does not
decide B1: proving the account flat this morning does not stop legacy from opening a position
this afternoon, and no measurement can. The decision stays with the operator; this only
refuses to let the decision be made on an unexamined account.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "track1_b1/1"

#: Legacy and the broker are both flat, and nothing is working behind them.
PASS = "PASS"
#: Something is held or working. A known risk.
FAIL = "FAIL"
#: The question could not be answered. NEVER reported as PASS.
UNKNOWN = "UNKNOWN"

STATUSES = (PASS, FAIL, UNKNOWN)

# ── codes ───────────────────────────────────────────────────────────────────────
OK = "legacy_and_broker_flat"

LEGACY_BOOK_POSITIONS = "legacy_book_has_positions"
TRACK1_BOOK_POSITIONS = "track1_book_has_positions"
BROKER_POSITIONS = "broker_has_positions"
ORPHAN_ORDERS = "orphan_working_orders"

BOOK_MISSING = "book_missing"
BOOK_UNREADABLE = "book_unreadable"
BROKER_NOT_QUERIED = "broker_not_queried"
BROKER_POSITIONS_UNKNOWN = "broker_positions_unknown"
BROKER_ORDERS_UNKNOWN = "broker_orders_unknown"
BROKER_EVIDENCE_STALE = "broker_evidence_stale"

NO_RECORD = "no_record"
RECORD_UNREADABLE = "record_unreadable"
RECORD_STALE = "record_stale"

#: Every code and the one status it may carry. A code that could be either would be a code
#: that says nothing, and this table is cross-checked on construction so a future edit cannot
#: quietly file a failure as a pass.
CODE_STATUS: dict = {
    OK: PASS,
    LEGACY_BOOK_POSITIONS: FAIL,
    TRACK1_BOOK_POSITIONS: FAIL,
    BROKER_POSITIONS: FAIL,
    ORPHAN_ORDERS: FAIL,
    BOOK_MISSING: UNKNOWN,
    BOOK_UNREADABLE: UNKNOWN,
    BROKER_NOT_QUERIED: UNKNOWN,
    BROKER_POSITIONS_UNKNOWN: UNKNOWN,
    BROKER_ORDERS_UNKNOWN: UNKNOWN,
    BROKER_EVIDENCE_STALE: UNKNOWN,
    NO_RECORD: UNKNOWN,
    RECORD_UNREADABLE: UNKNOWN,
    RECORD_STALE: UNKNOWN,
}

#: Where the evidence records live.
B1_DIR = "global_index/track1_b1"

# ══════════════════════════════════════════════════════════════════════════════
# Judgement calls. These are decisions about what "recent enough" means, not derived
# quantities. They live here, in one named block, and nowhere else.
# ══════════════════════════════════════════════════════════════════════════════

#: How old the broker observation inside a single measurement may be. An account that was
#: flat an hour ago is not evidence about an account now; this is deliberately tight because
#: the probe is read-only and costs seconds to repeat.
MAX_BROKER_OBSERVATION_MINUTES = 30

#: How old the newest RECORD may be before the gate stops counting it. One trading day: a
#: flat account last week says nothing about today, and the gate must close again on its own
#: rather than remembering a pass forever.
MAX_RECORD_AGE_HOURS = 24


# ══════════════════════════════════════════════════════════════════════════════
# what a book says
# ══════════════════════════════════════════════════════════════════════════════

#: The book file exists and parsed; `count` is meaningful.
BOOK_READ = "read"
#: The file is not there. It cannot testify that nothing is held.
BOOK_ABSENT = "absent"
#: It is there and could not be parsed, or carries no `positions` key.
BOOK_BAD = "unreadable"


@dataclass(frozen=True)
class BookState:
    path: str
    state: str
    count: int | None = None
    positions: list = field(default_factory=list)
    error: str = ""

    @property
    def flat(self) -> bool:
        return self.state == BOOK_READ and self.count == 0

    @property
    def known(self) -> bool:
        return self.state == BOOK_READ


def read_track1_book(path: str | Path) -> BookState:
    """The Track 1 book, checked as the ROUTE's book and not merely as a list of positions.

    Stage 5ZS. `read_book` asks one question — does this file say what is held — and for the
    legacy book that is the whole question. For Track 1 it is not: measured 2026-08-26, a
    legacy-shaped file written over the route's path still carried `positions: []`, so B1
    reported "Track 1 book flat" about a book that was not the route's book at all. Flat and
    unrecognisable are different facts and a gate must not read them the same.
    """
    from global_index import safety_book as _sb

    base = read_book(path)
    if base.state != BOOK_READ:
        return base
    verdict = _sb.inspect(path)
    if verdict["ok"]:
        return base
    return BookState(base.path, BOOK_BAD, error=verdict["why"])


def read_book(path: str | Path) -> BookState:
    """What this book says about what is held. Three states, because two is not enough.

    A missing book is NOT an empty book. `positions: []` is a statement by something that
    ran; absence is the absence of a statement, and the two must never read the same.
    """
    p = Path(path)
    if not p.exists():
        return BookState(str(p), BOOK_ABSENT,
                         error=f"{p} does not exist, so it cannot testify that nothing is held")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:                                      # noqa: BLE001
        return BookState(str(p), BOOK_BAD, error=f"{type(exc).__name__}: {exc}")
    if not isinstance(raw, dict):
        return BookState(str(p), BOOK_BAD, error="the book is not a JSON object")
    if "positions" not in raw:
        return BookState(str(p), BOOK_BAD,
                         error="the book carries no `positions` key, so it says nothing about "
                               "what is held")
    pos = raw.get("positions")
    if not isinstance(pos, list):
        return BookState(str(p), BOOK_BAD,
                         error=f"`positions` is {type(pos).__name__}, not a list")
    return BookState(str(p), BOOK_READ, count=len(pos), positions=list(pos))


# ══════════════════════════════════════════════════════════════════════════════
# what the broker said, and whether it said anything
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BrokerEvidence:
    """`None` and `[]` are different answers and are kept different all the way through.

    `positions=None` means the account was not asked or the ask failed. `positions=[]` means
    it was asked and holds nothing. Collapsing the two is the defect this class exists to make
    impossible — see `from_dashboard_snapshot`, which refuses to read an old snapshot as proof
    precisely because that snapshot's collector cannot tell them apart either.
    """
    source: str
    connected: bool | None = None
    observed_at: str = ""
    positions: list | None = None
    open_orders: list | None = None
    equity: float | None = None
    positions_error: str = ""
    orders_error: str = ""

    @property
    def positions_known(self) -> bool:
        return self.positions is not None

    @property
    def orders_known(self) -> bool:
        return self.open_orders is not None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["positions_known"] = self.positions_known
        d["orders_known"] = self.orders_known
        return d


def broker_unavailable(reason: str, source: str = "none") -> BrokerEvidence:
    return BrokerEvidence(source=source, connected=False,
                          positions_error=reason, orders_error=reason)


def from_direct_probe(probe: Mapping) -> BrokerEvidence:
    """Evidence from a read-only `IBKRBroker` query.

    `get_positions()` raises rather than returning `[]` when it cannot read, and
    `get_open_orders()` returns `None` rather than `[]` when it cannot testify. Both
    contracts are honoured here rather than re-derived.
    """
    pos = probe.get("positions")
    orders = probe.get("open_orders")
    return BrokerEvidence(
        source=str(probe.get("source") or "ibkr_direct"),
        connected=bool(probe.get("connected")),
        observed_at=str(probe.get("observed_at") or ""),
        positions=list(pos) if isinstance(pos, list) else None,
        open_orders=list(orders) if isinstance(orders, list) else None,
        equity=probe.get("equity"),
        positions_error=str(probe.get("positions_error") or ""),
        orders_error=str(probe.get("open_orders_error") or ""),
    )


def from_dashboard_snapshot(payload: Mapping) -> BrokerEvidence:
    """Evidence from the backend's cached IBKR snapshot — only if it says it succeeded.

    The collector behind that snapshot builds `positions` and `orders` inside try/except
    blocks that log a warning and leave the list EMPTY, then publishes the payload with
    `connected: true` and `error: null`. So an empty list from it means either "the account
    holds nothing" or "the call raised" — and B1 is exactly the question where those two must
    not be the same answer.

    A snapshot that does not carry `positions_ok` / `orders_ok` is therefore read as UNKNOWN,
    not as flat. That is the backward-compatible direction: an old payload proves nothing.
    """
    inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    connected = payload.get("connected")
    observed = str(payload.get("observed_at") or "")

    def _section(name: str, ok_key: str):
        rows = inner.get(name)
        ok = inner.get(ok_key)
        if ok is not True:
            why = (f"the snapshot does not report {ok_key}, so an empty {name} list cannot be "
                   f"told apart from a collector that swallowed its own exception"
                   if ok is None else
                   f"the snapshot reports {ok_key}={ok!r}: the {name} query did not succeed")
            return None, why
        if not isinstance(rows, list):
            return None, f"{name} is {type(rows).__name__}, not a list"
        return list(rows), ""

    pos, pos_err = _section("positions", "positions_ok")
    orders, ord_err = _section("orders", "orders_ok")
    return BrokerEvidence(source="dashboard_snapshot", connected=connected,
                          observed_at=observed, positions=pos, open_orders=orders,
                          equity=inner.get("equity"),
                          positions_error=pos_err, orders_error=ord_err)


# ══════════════════════════════════════════════════════════════════════════════
# the result
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class B1Result:
    status: str
    code: str
    detail: str
    checked_at: str = ""
    inputs: dict = field(default_factory=dict)
    findings: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status {self.status!r} is not one of {STATUSES}")
        expected = CODE_STATUS.get(self.code)
        if expected is None:
            raise ValueError(f"code {self.code!r} is not in CODE_STATUS — every code must "
                             f"declare which status it carries")
        if expected != self.status:
            raise ValueError(f"code {self.code!r} carries {expected}, not {self.status} — a "
                             f"failure filed as a pass is the one bug this table prevents")

    def as_dict(self) -> dict:
        return {"schema": SCHEMA, **asdict(self)}


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _result(status: str, code: str, detail: str, **kw) -> B1Result:
    return B1Result(status=status, code=code, detail=detail,
                    checked_at=kw.pop("checked_at", None) or _now_iso(), **kw)


# ══════════════════════════════════════════════════════════════════════════════
# orphan detection
# ══════════════════════════════════════════════════════════════════════════════

def _inst_of(row: Mapping) -> str:
    for key in ("instrument", "inst", "symbol", "localSymbol"):
        v = row.get(key)
        if v:
            return str(v)
    return "?"


def _held_instruments(broker_positions: list, books: list) -> set:
    held = {_inst_of(p) for p in broker_positions}
    for book in books:
        for row in book.positions:
            held.add(_inst_of(row))
    return {h for h in held if h and h != "?"}


def orphan_orders(open_orders: list, broker_positions: list, books: list) -> list:
    """Working orders with nothing behind them.

    A stop with no position is the dangerous one and the reason step S3 of the switch-over
    runbook exists: it does not protect anything, and if it triggers it OPENS a position
    nobody asked for. An order on an instrument held by neither the broker nor any book is
    the same hazard with a different shape.
    """
    held = _held_instruments(broker_positions, books)
    out = []
    for o in open_orders:
        inst = _inst_of(o)
        if inst not in held:
            out.append({"instrument": inst,
                        "order_type": str(o.get("order_type") or o.get("type") or ""),
                        "action": str(o.get("action") or ""),
                        "quantity": o.get("quantity", o.get("qty")),
                        "status": str(o.get("status") or ""),
                        "order_id": o.get("order_id"),
                        "why": "working order on an instrument held by neither the broker "
                               "nor any book"})
    return out


def unprotected_positions(broker_positions: list, open_orders: list) -> list:
    """Broker positions with no working stop behind them.

    Named separately from an orphan because the fix is the opposite one: an orphan must be
    cancelled, a naked position must be protected or closed.
    """
    stop_insts = {_inst_of(o) for o in open_orders
                  if "STP" in str(o.get("order_type") or o.get("type") or "").upper()}
    return [{"instrument": _inst_of(p),
             "direction": str(p.get("direction") or ""),
             "contracts": p.get("contracts", p.get("position"))}
            for p in broker_positions if _inst_of(p) not in stop_insts]


# ══════════════════════════════════════════════════════════════════════════════
# the measurement
# ══════════════════════════════════════════════════════════════════════════════

def measure(legacy_book: BookState, track1_book: BookState, broker: BrokerEvidence,
            *, now: Any = None,
            max_observation_minutes: int = MAX_BROKER_OBSERVATION_MINUTES) -> B1Result:
    """PASS only when all five conditions hold. FAIL on a known risk, UNKNOWN on no answer.

    Order matters: a KNOWN risk is reported ahead of an unknown, because "there is a position
    in the legacy book" is more useful to an operator than "and also the broker did not
    answer". Only when nothing is known to be wrong does the absence of an answer become the
    headline.
    """
    inputs = {"legacy_book": asdict(legacy_book), "track1_book": asdict(track1_book),
              "broker": broker.as_dict()}
    findings: dict = {}

    # ── known risks first ───────────────────────────────────────────────────
    if legacy_book.known and legacy_book.count:
        return _result(FAIL, LEGACY_BOOK_POSITIONS,
                       f"the legacy book holds {legacy_book.count} position(s). Legacy is not "
                       f"flat and Track 1 must not share the login until it is.",
                       inputs=inputs, findings={"legacy_positions": legacy_book.positions})

    if track1_book.known and track1_book.count:
        return _result(FAIL, TRACK1_BOOK_POSITIONS,
                       f"the Track 1 book holds {track1_book.count} position(s) before paper. "
                       f"The route has placed no order, so a position here is unexplained and "
                       f"must be investigated rather than cleared.",
                       inputs=inputs, findings={"track1_positions": track1_book.positions})

    if broker.positions_known and broker.positions:
        insts = sorted({_inst_of(p) for p in broker.positions})
        # Which of them are naked travels as a FINDING on this failure rather than as a
        # status of its own. It cannot be a status: any nonzero position fails here first, so
        # a separate `position_without_stop` result would be a branch nothing could reach —
        # and an unreachable branch reads, to anyone auditing this table, as a check that runs.
        naked = (unprotected_positions(broker.positions, broker.open_orders or [])
                 if broker.orders_known else None)
        extra = ("" if not naked else
                 f" {len(naked)} of them have no working stop behind them.")
        return _result(FAIL, BROKER_POSITIONS,
                       f"the broker holds {len(broker.positions)} position(s) in {insts}. On a "
                       f"shared login the route cannot be established from the broker, so this "
                       f"is unattributed risk whichever route opened it.{extra}",
                       inputs=inputs,
                       findings={"broker_positions": list(broker.positions),
                                 "unprotected": naked})

    if broker.orders_known and broker.positions_known:
        orphans = orphan_orders(broker.open_orders or [], broker.positions or [],
                                [legacy_book, track1_book])
        if orphans:
            return _result(FAIL, ORPHAN_ORDERS,
                           f"{len(orphans)} working order(s) have nothing behind them. A stop "
                           f"with no position does not protect anything — if it triggers it "
                           f"opens a position nobody asked for.",
                           inputs=inputs, findings={"orphans": orphans})
        findings["orphans"] = []

    # ── then the absences ───────────────────────────────────────────────────
    for name, book in (("legacy", legacy_book), ("Track 1", track1_book)):
        if book.state == BOOK_ABSENT:
            return _result(UNKNOWN, BOOK_MISSING,
                           f"the {name} book at {book.path} does not exist. A missing book is "
                           f"not an empty book — it cannot testify that nothing is held.",
                           inputs=inputs)
        if book.state == BOOK_BAD:
            return _result(UNKNOWN, BOOK_UNREADABLE,
                           f"the {name} book at {book.path} could not be read: {book.error}",
                           inputs=inputs)

    if broker.source == "none" or broker.connected is False:
        return _result(UNKNOWN, BROKER_NOT_QUERIED,
                       f"the broker was not asked ({broker.positions_error or 'no evidence'}). "
                       f"A clean local book says this system holds nothing; it says nothing "
                       f"about the account.",
                       inputs=inputs)

    if not broker.positions_known:
        return _result(UNKNOWN, BROKER_POSITIONS_UNKNOWN,
                       f"broker positions could not be established: "
                       f"{broker.positions_error or 'no reason given'}",
                       inputs=inputs)

    if not broker.orders_known:
        return _result(UNKNOWN, BROKER_ORDERS_UNKNOWN,
                       f"working orders could not be established: "
                       f"{broker.orders_error or 'no reason given'}. Positions being flat is "
                       f"not enough — a working stop with no position behind it is the exact "
                       f"hazard B1 is asked about.",
                       inputs=inputs)

    stale = _observation_age_minutes(broker.observed_at, now)
    if stale is None:
        return _result(UNKNOWN, BROKER_EVIDENCE_STALE,
                       f"the broker evidence carries no usable timestamp "
                       f"({broker.observed_at!r}), so its age cannot be established",
                       inputs=inputs)
    if stale > max_observation_minutes:
        return _result(UNKNOWN, BROKER_EVIDENCE_STALE,
                       f"the broker was last observed {stale} minute(s) ago, past the "
                       f"{max_observation_minutes}-minute allowance. An account that was flat "
                       f"then is not evidence about the account now.",
                       inputs=inputs)

    findings["broker_observation_age_minutes"] = stale
    return _result(PASS, OK,
                   f"the legacy book holds nothing, the Track 1 book holds nothing, and the "
                   f"broker reports 0 position(s) and 0 working order(s) as of {stale} "
                   f"minute(s) ago. Zero needs no attribution, which is why a shared login can "
                   f"answer this at all.",
                   inputs=inputs, findings=findings)


def _observation_age_minutes(stamp: str, now: Any = None) -> int | None:
    if not stamp:
        return None
    try:
        when = _dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except Exception:                                             # noqa: BLE001
        return None
    ref = now or _dt.datetime.now(_dt.timezone.utc)
    if isinstance(ref, str):
        try:
            ref = _dt.datetime.fromisoformat(ref.replace("Z", "+00:00"))
        except Exception:                                         # noqa: BLE001
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=_dt.timezone.utc)
    return max(0, int((ref - when).total_seconds() // 60))


# ══════════════════════════════════════════════════════════════════════════════
# the record, so a gate can read what a probe found
# ══════════════════════════════════════════════════════════════════════════════

def record_path(root: str | Path = ".", day: str | None = None) -> Path:
    d = day or _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")
    return Path(root) / B1_DIR / f"track1_b1_{d}.jsonl"


def record(result: B1Result, root: str | Path = ".", *, source: str = "") -> Path:
    """Append one result. Append-only and dated, like every other evidence file here."""
    p = record_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({**result.as_dict(), "source": source}, default=str) + "\n")
    return p


def latest(root: str | Path = ".", *, now: Any = None,
           max_age_hours: int = MAX_RECORD_AGE_HOURS) -> B1Result:
    """The newest recorded result, or an UNKNOWN saying why there is none."""
    d = Path(root) / B1_DIR
    files = sorted(d.glob("track1_b1_*.jsonl")) if d.is_dir() else []
    rows: list = []
    for f in files:
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        except Exception as exc:                                  # noqa: BLE001
            return _result(UNKNOWN, RECORD_UNREADABLE,
                           f"{f.name} could not be read ({type(exc).__name__}: {exc}), so the "
                           f"B1 history cannot be trusted whole")
    if not rows:
        return _result(UNKNOWN, NO_RECORD,
                       f"no B1 audit has been recorded under {B1_DIR}. A check that never ran "
                       f"is not a check that passed, and a signature alone cannot assert a "
                       f"fact about an account nobody asked.")

    rows.sort(key=lambda r: str(r.get("checked_at") or ""))
    newest = rows[-1]
    status = str(newest.get("status") or "")
    code = str(newest.get("code") or "")
    if status not in STATUSES or CODE_STATUS.get(code) != status:
        return _result(UNKNOWN, RECORD_UNREADABLE,
                       f"the newest record carries status {status!r} with code {code!r}, which "
                       f"do not agree — the record cannot be trusted")

    age_min = _observation_age_minutes(str(newest.get("checked_at") or ""), now)
    if age_min is None:
        return _result(UNKNOWN, RECORD_UNREADABLE,
                       f"the newest record's checked_at "
                       f"{newest.get('checked_at')!r} is unparseable")
    if age_min > max_age_hours * 60:
        return _result(UNKNOWN, RECORD_STALE,
                       f"the newest B1 audit is {age_min // 60} hour(s) old, past the "
                       f"{max_age_hours}-hour allowance. An account that was flat then is not "
                       f"evidence about the account now — re-run the audit.")

    return B1Result(status=status, code=code, detail=str(newest.get("detail") or ""),
                    checked_at=str(newest.get("checked_at") or ""),
                    inputs=newest.get("inputs") or {},
                    findings=newest.get("findings") or {})


# ══════════════════════════════════════════════════════════════════════════════
# operator-facing summary
# ══════════════════════════════════════════════════════════════════════════════

def operator_line(result: B1Result) -> str:
    """One plain sentence. No identifiers, no JSON, nothing to decode."""
    if result.status == PASS:
        return "Legacy book flat, Track 1 book flat, broker flat, no working orders."
    if result.code in (BROKER_NOT_QUERIED, BROKER_POSITIONS_UNKNOWN,
                       BROKER_ORDERS_UNKNOWN, BROKER_EVIDENCE_STALE):
        return "Broker evidence unavailable — B1 cannot be closed."
    if result.code == ORPHAN_ORDERS:
        return "A working order exists with no position behind it."
    if result.code == LEGACY_BOOK_POSITIONS:
        return "The legacy book still holds a position."
    if result.code == TRACK1_BOOK_POSITIONS:
        return "The Track 1 book holds a position before paper — investigate."
    if result.code == BROKER_POSITIONS:
        return "The broker holds a position that cannot be attributed to a route."
    if result.code in (NO_RECORD,):
        return "No B1 audit has been run."
    if result.code == RECORD_STALE:
        return "The last B1 audit is too old to count."
    return "B1 could not be established."
