"""Which book a safety sweep may write, and what it must already look like.

Stage 5ZG gave the two safety entry points one contract for their TRADE LOG, and its
docstring said why the destination has to be chosen on purpose rather than inferred. The
book — the positions file, the thing that records what is actually held — never got the
same treatment, and on 2026-08-26 at 09:31 ET that gap produced the defect this module
exists to close.

What happened
-------------
`TRACK1_MAX_HOLD_EXIT` runs with every route argument the scheduler can give it: its own
positions path, kill switch, lock file, client id, trade log, and `--route
track1_candidate`. All of that worked. Then `FuturesRunner._persist_state` wrote the file
in LEGACY shape, because that is the only shape it knew:

    schema_version 2  ->  1
    route, window, cut_instant, cur_day, equity, peak_equity, day_start_equity,
    booked_counter, counters                                        ->  all dropped
    breaker: {peak_equity: 50000.0, last_broker_equity: 996881.46}  ->  invented

Nine fields gone and an account-scale equity this route has never used written in their
place. `positions` was `[]` before and after, so nothing was held and nothing was lost —
which is exactly why it could happen quietly, and would not have been quiet on the first
day the route held something.

The rule this module holds
--------------------------
    no argument                     -> the legacy book, byte for byte as before
    --positions-path P              -> P
    --route R with the legacy book  -> refused
    the Track 1 book without --route-> refused
    a Track 1 book that exists and is not a Track 1 book -> refused

The last line is the one that matters today, and it is deliberately a REFUSAL rather than
a repair. A sweep that finds a book it does not recognise must stop, not rewrite: the file
records what is held, and a process that cannot read it has no business replacing it. The
alternative — carry on and write a fresh one — is how a real position would be erased by a
job that could not parse the file recording it.

Missing is not corrupt
----------------------
An absent book is the normal state through the whole shadow period: Track 1 holds nothing,
so the file need not exist, and both scripts return early when it does not. That is
allowed and stays allowed. A book that EXISTS and does not validate is a different fact and
always refuses — the same distinction the window ledger draws for a slot that did not run
and the checkpoint reader draws for a book it cannot read.
"""
from __future__ import annotations

import json
from pathlib import Path

from global_index import track1_slots as _ts

#: What both jobs wrote before any of this existed, and still write with no argument.
DEFAULT_BOOK = "live_positions.json"

TRACK1_BOOK = _ts.TRACK1_POSITIONS_PATH
TRACK1_ROUTE = _ts.TRACK1_ROUTE
TRACK1_SCHEMA = _ts.TRACK1_BOOK_SCHEMA


class BookRefused(Exception):
    """The requested book cannot be honoured — the job must fail, not fall back.

    Never raised for the default path with no route: an odd legacy book behaves exactly as
    it did before Stage 5ZS, because changing that would change legacy safety behaviour.
    """


def resolve(positions_path: str | None, route: str | None, cwd: Path) -> "tuple[Path, str | None]":
    """Return `(book, route)` or raise `BookRefused`.

    `cwd` is the repository root; both entry points already refuse to start anywhere else.
    """
    dest = Path(positions_path or DEFAULT_BOOK)
    if not dest.is_absolute():
        dest = cwd / dest

    is_track1_path = dest.name == Path(TRACK1_BOOK).name

    # ── the two paths and the two routes must agree ─────────────────────────
    if route is not None and route != TRACK1_ROUTE:
        raise BookRefused(
            f"--route {route!r} is not a route this contract knows. The only route with a "
            f"book of its own is {TRACK1_ROUTE!r}.")

    # The hazard is a route-stamped sweep editing the LEGACY book — that is the shape which
    # makes a book and a trade log disagree about what was closed. It is NOT "the file is
    # named something else": the first version of this rule required the canonical Track 1
    # filename for any routed run, which forbade a harness or an alternate root using its own
    # path, and broke four Stage 5ZG tests that were exercising the trade-log contract with a
    # temporary book. Narrowed to the hazard rather than to the name.
    if route == TRACK1_ROUTE and dest.name == Path(DEFAULT_BOOK).name:
        raise BookRefused(
            f"--route {TRACK1_ROUTE} was given with the LEGACY book {dest.name}. A sweep that "
            f"tags its rows for one route while editing another route's positions file is the "
            f"shape that makes a book and a trade log disagree about what was closed.")

    if is_track1_path and route != TRACK1_ROUTE:
        raise BookRefused(
            f"{dest.name} is the Track 1 book and no --route {TRACK1_ROUTE} was given. "
            f"Editing it without naming the route is how it came to be written in the "
            f"legacy shape on 2026-08-26.")

    # ── if it exists, it must be the book this route owns ───────────────────
    # Scoped to the route's CANONICAL book — the file it writes and reads across days, which
    # is what carries the schema-2 envelope worth protecting. Matched by name, so an alternate
    # root holding a real `live_positions.track1.json` is still checked, while a harness
    # pointing the sweep at its own temporary file is not: there is no envelope there to lose.
    if route == TRACK1_ROUTE and is_track1_path and dest.exists():
        verdict = inspect(dest)
        if not verdict["ok"]:
            raise BookRefused(
                f"{dest} exists and is not a Track 1 book: {verdict['why']}. Refusing to "
                f"write over it. Repair it from the route's last checkpoint before letting "
                f"a sweep touch it — a job that cannot read what is held must not replace "
                f"it.")

    return dest, route


def inspect(path: str | Path) -> dict:
    """What this file is, in the terms the refusal needs. Never raises.

    Four outcomes, and `missing` is deliberately not one of the failures: absence is the
    normal shadow state and the callers handle it by returning early.
    """
    p = Path(path)
    if not p.exists():
        return {"state": "missing", "ok": False, "why": "the file does not exist",
                "schema_version": None, "route": None, "positions": None}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:                                      # noqa: BLE001
        return {"state": "unreadable", "ok": False,
                "why": f"it is not readable JSON ({type(exc).__name__}: {exc})",
                "schema_version": None, "route": None, "positions": None}
    if not isinstance(raw, dict):
        return {"state": "unreadable", "ok": False, "why": "it is not a JSON object",
                "schema_version": None, "route": None, "positions": None}

    schema = raw.get("schema_version")
    route = raw.get("route")
    positions = raw.get("positions")
    n = len(positions) if isinstance(positions, list) else None
    base = {"schema_version": schema, "route": route, "positions": n,
            "foreign_keys": sorted(set(raw) - set(_TRACK1_KEYS))}

    if not isinstance(positions, list):
        return {**base, "state": "corrupt", "ok": False,
                "why": "it carries no positions list"}
    if route != TRACK1_ROUTE:
        return {**base, "state": "corrupt", "ok": False,
                "why": (f"it is stamped route={route!r}, not {TRACK1_ROUTE!r} — a book at "
                        f"the route's own path that does not name the route was written by "
                        f"something else")}
    if int(schema or 0) != TRACK1_SCHEMA:
        return {**base, "state": "corrupt", "ok": False,
                "why": (f"it carries schema_version={schema!r}, not {TRACK1_SCHEMA} — a "
                        f"downgraded envelope has already lost the fields this route "
                        f"carries across days")}
    return {**base, "state": "track1", "ok": True, "why": ""}


#: The keys a Track 1 book is allowed to carry. Anything else is reported by `inspect` as a
#: foreign key so a repair can say what it is dropping rather than dropping it silently.
_TRACK1_KEYS = ("schema_version", "route", "window", "cut_instant", "equity", "cur_day",
                "peak_equity", "day_start_equity", "positions", "booked_counter", "counters")
