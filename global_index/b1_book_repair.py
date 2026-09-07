"""Rebuild the Track 1 book after a legacy-shaped writer has been over it.

    python -m global_index.b1_book_repair                 # dry run: prints the diff, writes nothing
    python -m global_index.b1_book_repair --apply         # writes, after backing the file up

What this can and cannot recover
--------------------------------
The route's checkpoint carries per-instrument resume state and **no book envelope**, so
there is nothing on disk to restore the lost fields FROM. This tool therefore does not
claim to recover them. It rebuilds the envelope at the route's own defaults and carries the
`positions` list forward from the damaged file.

That is only sound while the route has never traded, so the tool proves it rather than
assuming it, and refuses if any of it fails:

  * the damaged book's `positions` must be empty — a book holding a position cannot have
    its equity and counters reconstructed from defaults, and reconstruction would be a
    guess about money;
  * the route's trade log must be empty — a closed trade means equity moved;
  * the route's order journal must not exist — an order means the route has acted.

If any of those is false the repair stops and says which, because at that point the right
answer is an operator reading the evidence, not a script picking defaults.

Why not just let the next window write a fresh one
--------------------------------------------------
Because after Stage 5ZS it will not. `_carry_forward_book` refuses a book at the route's
path that is not stamped for the route, and refusing is correct: a window close that
overwrote an unreadable book is exactly how a real position would be erased. The refusal is
the reason this tool exists, and the reason it is a deliberate operator step.

Not named `track1_*` on purpose: it is an operator repair, like `run_stop_repair`, and the
live-frame gate scans that namespace for modules that can reach live bars.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from global_index import safety_book as _sb
from global_index import track1_slots as _ts

BOOK = _ts.TRACK1_POSITIONS_PATH
TRADE_LOG = _ts.TRACK1_TRADE_LOG_PATH
ORDERS_DIR = "global_index/track1_runtime/orders"


def route_has_never_traded(root: Path) -> "tuple[bool, list]":
    """`(never_traded, evidence)` — each check named, so a refusal says which one failed."""
    ev = []
    ok = True

    log = root / TRADE_LOG
    if not log.exists():
        ev.append(f"trade log {TRADE_LOG}: absent — no sweep has ever proved it writable")
    else:
        rows = [l for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
        ev.append(f"trade log {TRADE_LOG}: {len(rows)} row(s)")
        if rows:
            ok = False

    orders = root / ORDERS_DIR
    ev.append(f"order journal {ORDERS_DIR}: {'PRESENT' if orders.exists() else 'absent'}")
    if orders.exists():
        ok = False

    return ok, ev


def fresh_book(now_et: _dt.datetime) -> dict:
    """The envelope the route writes for itself when it holds nothing.

    Deliberately the same field set `run_live_day_track1._carry_forward_book` builds, and a
    test pins the two against each other so a repair cannot produce a book the route would
    then refuse.
    """
    return {"schema_version": _ts.TRACK1_BOOK_SCHEMA, "route": _ts.TRACK1_ROUTE,
            "window": "live", "cut_instant": now_et.isoformat(), "equity": 0.0,
            "cur_day": str(now_et.date()), "peak_equity": 0.0, "day_start_equity": 0.0,
            "positions": [], "booked_counter": {}, "counters": {}}


def plan(root: Path = Path("."), *, now_et: _dt.datetime | None = None) -> dict:
    """What the repair would do. Reads only."""
    now_et = now_et or _dt.datetime.now(ZoneInfo("America/New_York"))
    book = root / BOOK
    verdict = _sb.inspect(book)
    never, evidence = route_has_never_traded(root)

    problems = []
    if verdict["state"] == "missing":
        problems.append(f"{book} does not exist — there is nothing to repair. The next "
                        f"completed window creates one.")
    elif verdict["ok"]:
        problems.append(f"{book} is already a valid Track 1 book — nothing to repair.")
    if verdict.get("positions"):
        problems.append(f"the damaged book holds {verdict['positions']} position(s). Equity "
                        f"and counters cannot be reconstructed from defaults over a real "
                        f"position; an operator must read the evidence.")
    if not never:
        problems.append("the route has traded, so its equity and counters are not their "
                        "defaults and rebuilding them would be a guess about money.")

    proposed = fresh_book(now_et) if not problems else None
    if proposed is not None:
        current = json.loads(book.read_text(encoding="utf-8"))
        proposed["positions"] = list(current.get("positions") or [])

    return {"book": str(book), "current": verdict, "never_traded": never,
            "evidence": evidence, "problems": problems, "proposed": proposed,
            "can_repair": not problems}


def render(p: dict) -> str:
    out = [f"Track 1 book repair — {p['book']}", "=" * 72]
    c = p["current"]
    out.append(f"  current state  : {c['state']}")
    out.append(f"  schema_version : {c['schema_version']!r}   route: {c['route']!r}   "
               f"positions: {c['positions']}")
    if c.get("foreign_keys"):
        out.append(f"  foreign keys   : {c['foreign_keys']}  <- not part of a Track 1 book")
    if c.get("why"):
        out.append(f"  why it refuses : {c['why']}")
    out.append("")
    out.append("  has the route ever traded?")
    for e in p["evidence"]:
        out.append(f"    - {e}")
    out.append(f"    => never traded: {p['never_traded']}")
    out.append("")
    if p["problems"]:
        out.append("  REFUSING:")
        for w in p["problems"]:
            out.append(f"    * {w}")
        return "\n".join(out)
    out.append("  would write:")
    for k, v in p["proposed"].items():
        out.append(f"    {k:18s} = {json.dumps(v)}")
    out.append("")
    out.append("  RECONSTRUCTED, NOT RECOVERED: equity, peak_equity, day_start_equity,")
    out.append("  booked_counter and counters come back at the route's defaults. Nothing on")
    out.append("  disk holds their old values — the checkpoint carries per-instrument resume")
    out.append("  state and no book envelope. This is only sound because the route has never")
    out.append("  traded, which is checked above rather than assumed.")
    return "\n".join(out)


def apply(root: Path = Path("."), *, now_et: _dt.datetime | None = None) -> dict:
    """Write the repaired book, after backing up the damaged one. Re-checks first."""
    p = plan(root, now_et=now_et)
    if not p["can_repair"]:
        raise RuntimeError("refusing to apply: " + "; ".join(p["problems"]))
    book = root / BOOK
    stamp = (now_et or _dt.datetime.now(ZoneInfo("America/New_York"))).strftime("%Y%m%dT%H%M%S")
    backup = book.with_suffix(book.suffix + f".corrupt-{stamp}.bak")
    shutil.copy2(book, backup)
    tmp = book.with_suffix(book.suffix + ".tmp")
    tmp.write_text(json.dumps(p["proposed"], indent=1) + "\n", encoding="utf-8")
    tmp.replace(book)
    after = _sb.inspect(book)
    if not after["ok"]:
        raise RuntimeError(f"the repaired book still does not validate: {after['why']}")
    return {"backup": str(backup), "written": str(book), "verified": after}


def main(argv: "list | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--apply", action="store_true",
                    help="write the repaired book. Without this, nothing is written.")
    a = ap.parse_args(argv)
    root = Path(a.root)

    p = plan(root)
    print(render(p))
    if not a.apply:
        print("\nDRY RUN — nothing written. Pass --apply to repair.")
        return 0 if p["can_repair"] else 1
    if not p["can_repair"]:
        print("\nnot applying: see the refusal above")
        return 1
    result = apply(root)
    print(f"\nbacked up  -> {result['backup']}")
    print(f"written    -> {result['written']}")
    print(f"verified   -> {result['verified']['state']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
