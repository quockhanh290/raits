"""What Track 1 can say about its own trading, from Track 1's own artefacts only.

The rule this module exists to hold: **it never reads a legacy path.** Not as a fallback, not
as a default, not "just to fill the panel". A Track 1 report that quietly showed legacy's book
would be worse than an empty one, because an empty one is obviously empty and a borrowed one
looks like an answer.

Three states, not two — the same discipline the broker reads, the checkpoint and the regime
verification all landed on:

    not_produced   the artefact does not exist. Nothing has written it yet.
    empty          it exists and holds nothing. Something ran and had nothing to say.
    available      it exists and holds rows.

`empty` and `not_produced` are different facts and must never print the same. A trade log that
exists with zero rows means the route swept and closed nothing; a missing one means no sweep
has ever reached the point of proving its destination writable.

What this module deliberately cannot do
---------------------------------------
It cannot tell you the paper P&L, because there is none: no Track 1 order has ever been placed.
Everything it reports about money is EXPECTED or INTENDED, sourced from the dry run, and every
payload says `broker_verified: false` with a reason. Measured 2026-08-26 on the newest broker
statement: 37 fields, and not one of them is a route, a strategy, an order reference or a
client id — only `ClientAccountID`, one account for both routes. So even once fills exist, a
statement cannot say which route made them until B1 is closed. That is `route_unattributed`,
and it is a fact about the statement format rather than a gap in this reader.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

SCHEMA = "track1_report/1"

#: The executor verbs this route needs. Declared, not imported — see `lifecycle`.
LIFECYCLE_VERBS = ("open_position", "close_position", "place_protective_stop",
                   "switch_same_symbol")
ROUTE = "track1_candidate"

#: Track 1's own artefacts. Every path here is route-scoped; there is deliberately no legacy
#: path in this module, and a test asserts it by AST rather than by trusting this sentence.
TRADE_LOG = "global_index/track1_runtime/trade_log.track1.jsonl"
BOOK = "live_positions.track1.json"
ORDERS_DIR = "global_index/track1_runtime/orders"

# ── artefact states ─────────────────────────────────────────────────────────────────────
NOT_PRODUCED = "not_produced"
EMPTY = "empty"
AVAILABLE = "available"
UNREADABLE = "unreadable"

# ── parity ──────────────────────────────────────────────────────────────────────────────
PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

# ── why the broker cannot confirm anything ──────────────────────────────────────────────
NO_ORDERS_YET = "no_track1_orders_have_been_placed"
STATEMENT_UNAVAILABLE = "statement_unavailable"
ROUTE_UNATTRIBUTED = "route_unattributed"
ATTRIBUTION_UNKNOWN = "attribution_unknown"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _jsonl(path: Path) -> "tuple[str, list, list]":
    """`(state, rows, malformed)`. Missing and empty are different answers."""
    if not path.exists():
        return NOT_PRODUCED, [], []
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError as exc:
        return UNREADABLE, [], [f"{type(exc).__name__}: {exc}"]
    rows, bad = [], []
    for i, ln in enumerate(lines, 1):
        try:
            v = json.loads(ln)
        except json.JSONDecodeError as exc:
            bad.append(f"line {i}: {exc}")
            continue
        (rows if isinstance(v, dict) else bad).append(v if isinstance(v, dict)
                                                      else f"line {i}: not an object")
    if not rows and not bad:
        return EMPTY, [], []
    return AVAILABLE, rows, bad


def read_trade_log(root: str | Path = ".") -> dict:
    """Track 1's trade log, with every row's route checked.

    A row that does not carry `route == track1_candidate` is INVALID, not silently accepted.
    The tag is written by the runner for exactly this reason (Stage 5ZG): a row that ended up
    in the wrong file still names its own route, and a row in the right file that does NOT
    name it is either legacy's, hand-edited, or written by something that has not been taught
    the contract. None of those should be counted as Track 1 P&L.
    """
    p = Path(root) / TRADE_LOG
    state, rows, malformed = _jsonl(p)
    valid = [r for r in rows if str(r.get("route") or "") == ROUTE]
    invalid = [{"row": i, "route": r.get("route"), "type": r.get("type")}
               for i, r in enumerate(rows, 1) if str(r.get("route") or "") != ROUTE]
    closes = [r for r in valid if str(r.get("type") or "").upper() == "CLOSE"]
    return {
        "path": TRADE_LOG, "state": state,
        "rows": len(valid), "invalid_rows": len(invalid), "invalid": invalid[:10],
        "malformed_lines": len(malformed), "closes": len(closes),
        "reading": {
            NOT_PRODUCED: "no Track 1 sweep has written here yet",
            EMPTY: "the file exists and holds no rows — a route that has closed nothing",
            AVAILABLE: f"{len(valid)} route-tagged row(s)",
            UNREADABLE: "the file could not be read",
        }[state],
        "route_required": ROUTE,
    }


def read_book(root: str | Path = ".") -> dict:
    """Track 1's own position book. Zero positions is an answer, not an absence."""
    p = Path(root) / BOOK
    if not p.exists():
        return {"path": BOOK, "state": NOT_PRODUCED, "positions": None,
                "reading": "no Track 1 window has closed and written a book yet"}
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:                                   # noqa: BLE001
        return {"path": BOOK, "state": UNREADABLE, "positions": None,
                "detail": f"{type(exc).__name__}: {exc}",
                "reading": "the book could not be read"}
    if str(state.get("route") or "") != ROUTE:
        return {"path": BOOK, "state": UNREADABLE, "positions": None,
                "detail": f"the book names route {state.get('route')!r}, not {ROUTE!r}",
                "reading": "this file is not Track 1's book"}
    positions = list(state.get("positions") or [])
    return {"path": BOOK, "state": EMPTY if not positions else AVAILABLE,
            "positions": len(positions),
            "cut_instant": state.get("cut_instant"), "cur_day": state.get("cur_day"),
            "equity": state.get("equity"),
            "reading": ("the book exists and holds nothing — a flat route"
                        if not positions else f"{len(positions)} open position(s)")}


def read_order_journal(root: str | Path = ".") -> dict:
    """The order journal, real or rehearsed.

    Before paper there are no real orders, and the dry run is the only thing that produces
    journal rows. Reported with its source named, so an INTENDED order is never mistaken for
    one that was sent.
    """
    d = Path(root) / ORDERS_DIR
    if not d.is_dir():
        return {"path": ORDERS_DIR, "state": NOT_PRODUCED, "rows": 0, "source": None,
                "reading": "no order journal exists — nothing has been sent or rehearsed"}
    files = sorted(d.glob("track1_orders_*.jsonl"))
    rows, malformed = [], []
    for f in files:
        st, r, bad = _jsonl(f)
        rows.extend(r)
        malformed.extend(bad)
    if not files:
        return {"path": ORDERS_DIR, "state": EMPTY, "rows": 0, "source": None,
                "reading": "the directory exists and holds no journal"}
    states = sorted({str(r.get("state") or "") for r in rows})
    submitted = [r for r in rows if str(r.get("state") or "") == "submitted"]
    return {"path": ORDERS_DIR, "state": EMPTY if not rows else AVAILABLE,
            "rows": len(rows), "files": len(files), "malformed_lines": len(malformed),
            "order_states": states, "submitted": len(submitted),
            # Named, never inferred: a rehearsal and a real send produce the same shape, and
            # the only honest way to tell them apart is the gate that was open at the time.
            "source": "dry_run" if rows else None,
            "reading": (f"{len(rows)} journal row(s) — INTENDED, not sent: no Track 1 order "
                        f"path has ever been armed" if rows else "no journal rows")}


def broker_evidence(root: str | Path = ".") -> dict:
    """Can a broker statement confirm any of this? Today: no, for two separate reasons.

    Both are stated because they need different things to change. The first closes itself the
    day a Track 1 order fills. The second needs B1 — a statement that cannot name a route
    cannot attribute a fill to one, and that is a property of the statement format, measured:
    37 fields, none of them a route, a strategy, an order reference or a client id.
    """
    root = Path(root)
    journal = read_order_journal(root)
    statements = sorted((root / "monitor" / "inputs" / "ibkr_flex").glob("*.csv")) \
        if (root / "monitor" / "inputs" / "ibkr_flex").is_dir() else []
    reasons = []
    if journal["rows"] == 0 or journal.get("source") == "dry_run":
        reasons.append(NO_ORDERS_YET)
    if not statements:
        reasons.append(STATEMENT_UNAVAILABLE)
    else:
        reasons.append(ROUTE_UNATTRIBUTED)
    return {"broker_verified": False, "reasons": reasons,
            "statements_on_disk": len(statements),
            "reading": ("no broker evidence can confirm Track 1 trading: "
                        + "; ".join(reasons))}


def open_position_parity(root: str | Path = ".") -> dict:
    """Does the book agree with what the journal says was opened?

    Three answers. UNKNOWN is never PASS — a comparison that could not be made is not a
    comparison that agreed, and while one login serves both routes a broker figure cannot be
    attributed to a route at all.
    """
    book = read_book(root)
    journal = read_order_journal(root)

    if book["state"] in (NOT_PRODUCED, UNREADABLE):
        return {"status": UNKNOWN, "code": "book_" + book["state"],
                "detail": f"the book is {book['state']}, so there is nothing to compare",
                "book_positions": None, "journal_rows": journal["rows"],
                "broker_verified": False, "attribution": ATTRIBUTION_UNKNOWN}

    if book["positions"] == 0 and journal["rows"] == 0:
        return {"status": PASS, "code": "both_flat",
                "detail": "the book holds nothing and no order has been journalled — the two "
                          "agree, and both are empty for the same reason",
                "book_positions": 0, "journal_rows": 0,
                "broker_verified": False, "attribution": ATTRIBUTION_UNKNOWN,
                "attribution_note": "file-level agreement only; while one IB login serves "
                                    "both routes a broker position cannot be attributed to "
                                    "one of them — see B1"}

    if book["positions"] == 0 and journal["rows"] > 0:
        return {"status": FAIL, "code": "journal_without_book",
                "detail": f"{journal['rows']} order row(s) exist and the book is flat",
                "book_positions": 0, "journal_rows": journal["rows"],
                "broker_verified": False, "attribution": ATTRIBUTION_UNKNOWN}

    if book["positions"] > 0 and journal["rows"] == 0:
        return {"status": FAIL, "code": "book_without_journal",
                "detail": f"the book holds {book['positions']} position(s) and no order was "
                          f"ever journalled — a position nobody can account for",
                "book_positions": book["positions"], "journal_rows": 0,
                "broker_verified": False, "attribution": ATTRIBUTION_UNKNOWN}

    return {"status": UNKNOWN, "code": "not_comparable_yet",
            "detail": f"the book holds {book['positions']} position(s) against "
                      f"{journal['rows']} journal row(s); matching them per instrument needs "
                      f"real fills, which do not exist",
            "book_positions": book["positions"], "journal_rows": journal["rows"],
            "broker_verified": False, "attribution": ATTRIBUTION_UNKNOWN}


def lifecycle(root: str | Path = ".") -> dict:
    """What the order lifecycle can and cannot do yet — Stage 5ZN.

    Reports the two contracts this stage built and the one it cannot: a broker stop. "Planned
    stop ready" and "broker stop verified" are separate facts and are never merged, because
    the first is about a record and the second is about an order sitting on an exchange.
    """
    from global_index import track1_planned_stop as ps

    # The executor is NOT imported here, and that is deliberate rather than awkward. Part of
    # the safety argument for the whole order path is that nothing which runs imports it —
    # combined with "the slot path has no gate", it means there is no route from the scheduler
    # to a broker. A reporting module reaching in to read `hasattr` would put the first import
    # in the graph for the sake of a panel field.
    #
    # So the verbs are DECLARED here, and a test compares this list against the real class.
    # The check lives where imports are free.
    verbs = {name: True for name in LIFECYCLE_VERBS}
    return {
        "planned_stop_ready": True,
        "planned_stop_fields": [f for f in ps.PlannedStop.__dataclass_fields__],
        "planned_stop_required_for_entry": True,
        "lifecycle_verbs": verbs,
        "verbs_send_orders": False,
        "verbs_reading": ("close, protective stop and switch produce INTENT and journal it; "
                          "the send step is not built, so none of them can place an order"),
        "book_carried_across_days": True,
        "book_never_synthesised_over": True,
        # The one this stage cannot close, stated in its own words rather than as an absence.
        "broker_stop_verified": False,
        "broker_stop_reason": ("no Track 1 order has ever been sent, so no stop has ever been "
                               "placed for one to be compared against; this needs paper"),
    }


def report(root: str | Path = ".") -> dict:
    """Everything Track 1 can honestly say about its own trading right now."""
    root = Path(root)
    trades = read_trade_log(root)
    book = read_book(root)
    journal = read_order_journal(root)
    broker = broker_evidence(root)
    parity = open_position_parity(root)
    return {
        "schema": SCHEMA, "route": ROUTE, "generated_at": _now(),
        "trade_log": trades, "book": book, "order_journal": journal,
        "broker": broker, "open_position_parity": parity,
        "lifecycle": lifecycle(root),
        # The single sentence a reader who scrolls no further must not be able to misread.
        "headline": (
            f"Track 1 has no broker-verified P&L: {'; '.join(broker['reasons'])}. "
            f"Trade log {trades['state']} ({trades['rows']} row(s)); "
            f"book {book['state']}; order journal {journal['state']} "
            f"({journal['rows']} INTENDED row(s)); parity {parity['status']}."),
        "reads_legacy_paths": False,
    }
