"""global_index/track1_book_backfill.py — put fills the book never recorded into the book.

WHY THIS EXISTS, ONCE
---------------------
On 2026-09-24, the first day this route was armed, two orders filled at the broker and
`live_positions.track1.json` came out of the session with `positions: []`. The cause was a
contract built in half: `track1_paper_executor` returns the Fill and says the caller advances
the book; the caller counted it. `track1_paper_send.advance_book` closes that for every fill
from now on, and cannot reach backwards — so this exists for the two rows it cannot.

Everything it writes is DERIVED from evidence already on disk, never supplied on a command
line: the order journal says what filled and at what price, and the admission explanation says
the direction, size, stop and risk the route decided. Hand-typing those is how a book comes to
hold a position nobody can trace, and a book nobody can trace is worse than one missing a row —
the missing row at least makes the reconciler shout.

Every row is stamped `booked_from="track1_book_backfill"`, so no later reader has to wonder
which rows the route recorded live and which a person put there afterwards.

READ-ONLY unless --write. Refuses if a row for the same trade is already present.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

ROUTE = "track1_candidate"
BOOK_SCHEMA = 2
BOOK = Path("live_positions.track1.json")
ORDERS = Path("global_index/track1_runtime/orders")
EXPLAIN = Path("global_index/track1_runtime/shadow/explanations")


def _filled_orders(day: str) -> dict:
    """{trade_id: {...}} for every order the journal says FILLED on `day`."""
    p = ORDERS / ("track1_orders_" + day.replace("-", "") + ".jsonl")
    out: dict = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if str(r.get("state")) != "filled":
            continue
        out[str(r.get("candidate_id"))] = {
            "instrument": str(r.get("instrument")),
            "sleeve": str(r.get("sleeve")),
            "slot_id": str(r.get("slot_id")),
            "order_id": str(r.get("order_id") or ""),
            "fill_price": r.get("avg_price"),
            "fill_reported_qty": r.get("filled_qty"),
            "commission": r.get("commission"),
        }
    return out


def _accepted(day: str) -> dict:
    """{candidate_id: outputs} for every admission the route ACCEPTED on `day`."""
    out: dict = {}
    root = EXPLAIN / ("live_" + day)
    for p in root.rglob("*.jsonl"):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if str(r.get("status")) != "accepted":
                continue
            o = r.get("outputs") or {}
            out[str(r.get("candidate_id"))] = {
                "direction": o.get("direction"),
                "qty": o.get("qty"),
                "stop_price": o.get("stop_price"),
                "risk_dollars": o.get("risk_dollars"),
                "signalled_entry_price": o.get("entry_price"),
                "stop_basis": o.get("stop_basis"),
                "cap_bucket": o.get("cap_bucket"),
            }
    return out


def rows_for(day: str) -> list:
    fills, acc = _filled_orders(day), _accepted(day)
    rows = []
    for tid, f in sorted(fills.items()):
        a = acc.get(tid)
        if a is None:
            raise SystemExit(
                "REFUSING: " + tid + " filled but has no accepted admission record; the "
                "direction, size and stop would have to be invented")
        rows.append({
            "trade_id": tid,
            "sleeve": f["sleeve"] or a["cap_bucket"],
            "instrument": f["instrument"],
            "direction": a["direction"],
            "qty": int(a["qty"] or 0),
            "risk_dollars": a["risk_dollars"],
            "entry_time": day + " 15:55:00",
            "exit_time": None,
            # What was PAID, with what was SIGNALLED kept beside it rather than averaged away.
            "entry_price": f["fill_price"],
            "signalled_entry_price": a["signalled_entry_price"],
            "stop_price": a["stop_price"],
            "stop_basis": a["stop_basis"],
            "order_id": f["order_id"],
            "fill_reported_qty": f["fill_reported_qty"],
            "commission": f["commission"],
            "slot_id": f["slot_id"],
            # The stamp. Every field above came off disk; this one says who assembled them.
            "booked_from": "track1_book_backfill",
            "backfilled_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "backfill_reason": ("filled 2026-09-24 while nothing advanced the book; "
                                "track1_paper_send.advance_book now does this live"),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="2026-09-24")
    ap.add_argument("--book", default=str(BOOK))
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    rows = rows_for(a.day)
    print("derived " + str(len(rows)) + " row(s) from the journal and the admission records:")
    for r in rows:
        print("  {:>5} {:<5} qty={} entry={} stop={} risk=${} order={}".format(
            r["instrument"], r["direction"], r["qty"], r["entry_price"],
            r["stop_price"], r["risk_dollars"], r["order_id"]))

    p = Path(a.book)
    raw = json.loads(p.read_text(encoding="utf-8"))
    if str(raw.get("route")) != ROUTE:
        print("REFUSING: book is stamped route=" + repr(raw.get("route")))
        return 2
    if int(raw.get("schema_version")) != BOOK_SCHEMA:
        print("REFUSING: book schema " + str(raw.get("schema_version")))
        return 2
    have = {str(x.get("trade_id")) for x in (raw.get("positions") or [])}
    new = [r for r in rows if r["trade_id"] not in have]
    print("")
    print("book holds " + str(len(have)) + " row(s); " + str(len(new)) + " to add")
    if not new:
        print("nothing to do")
        return 0
    if not a.write:
        print("READ-ONLY: pass --write to apply")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    bak = p.with_suffix(p.suffix + ".pre-backfill-" + stamp + ".bak")
    bak.write_bytes(p.read_bytes())
    print("snapshot -> " + bak.name)
    raw["positions"] = list(raw.get("positions") or []) + new
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(raw, indent=1, default=str), encoding="utf-8")
    tmp.replace(p)
    back = json.loads(p.read_text(encoding="utf-8"))
    print("written and re-read: " + str(len(back.get("positions") or [])) + " position(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
