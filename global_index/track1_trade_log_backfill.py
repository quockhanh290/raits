"""global_index/track1_trade_log_backfill.py — OPEN rows for fills the trade log never saw.

WHY THIS EXISTS, ONCE
---------------------
On 2026-09-24, the first armed day, two orders filled (MYM order 28 at 51,732.00, M2K order 30
at 2,857.00). The book was back-filled at 18:50 ET by `track1_book_backfill`; the trade log was
not, and still held 0 rows. `track1_paper_send.append_trade_open` now writes the OPEN row live
for every fill; it cannot reach backwards, so this exists for the two it cannot.

Nothing here is typed in. Each row is built from the BOOK row for the trade (itself derived from
the order journal and the admission record, and stamped `track1_book_backfill`), and is written
only if the ORDER JOURNAL independently says that trade filled at that price. A book row the
journal does not confirm is refused, not logged.

The writer is `append_trade_open` itself, so a back-filled row has exactly the live shape; only
`booked_from` differs, and says who assembled it.

READ-ONLY unless --write. `--root` is required: this module has no production default.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from types import SimpleNamespace


def _journal_fills(root: Path, day: str) -> dict:
    """{trade_id: journal row} for every row the order journal records as `filled` on `day`."""
    from global_index.track1_report import ORDERS_DIR

    p = root / ORDERS_DIR / ("track1_orders_" + day.replace("-", "") + ".jsonl")
    out: dict = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if str(r.get("state")) == "filled":
            out[str(r.get("candidate_id"))] = r
    return out


def plan(root: "str | Path", day: str) -> "tuple[list, list]":
    """(rows to write as (fill, decision, slot_id), refusals). Reads only."""
    from global_index.track1_report import BOOK

    root = Path(root)
    book = json.loads((root / BOOK).read_text(encoding="utf-8"))
    fills = _journal_fills(root, day)
    todo, refused = [], []
    for pos in book.get("positions") or []:
        tid = str(pos.get("trade_id") or "")
        if not str(pos.get("entry_time") or "").startswith(day):
            continue
        j = fills.get(tid)
        if j is None:
            refused.append(f"{tid}: in the book but the order journal has no fill for it")
            continue
        if float(j.get("avg_price") or 0) != float(pos.get("entry_price") or -1):
            refused.append(f"{tid}: book entry {pos.get('entry_price')} != journal fill "
                           f"{j.get('avg_price')}")
            continue
        cand = SimpleNamespace(
            trade_id=tid, instrument=pos.get("instrument"), direction=pos.get("direction"),
            contracts=int(pos.get("qty") or 0), entry_price=pos.get("signalled_entry_price"),
            stop_price=pos.get("stop_price"), risk_dollars=pos.get("risk_dollars"),
            entry_time=pos.get("entry_time"), sleeve=pos.get("sleeve"))
        decision = SimpleNamespace(candidate=cand, sleeve=pos.get("sleeve"))
        fill = SimpleNamespace(status="filled", avg_price=j.get("avg_price"),
                               filled_qty=j.get("filled_qty"), order_id=j.get("order_id"),
                               commission=j.get("commission"))
        todo.append((fill, decision, str(j.get("slot_id") or pos.get("slot_id") or "")))
    return todo, refused


def run(root: "str | Path", day: str, *, write: bool) -> int:
    from global_index import track1_paper_send as ps
    from global_index.track1_report import TRADE_LOG

    root = Path(root)
    todo, refused = plan(root, day)
    for r in refused:
        print("REFUSED  " + r)
    for fill, dec, slot in todo:
        c = dec.candidate
        print(f"derived  {c.trade_id}  {c.direction} {c.contracts} {c.instrument} "
              f"fill={fill.avg_price} signalled={c.entry_price} order={fill.order_id} slot={slot}")
    if refused:
        print("REFUSING to write anything while a row is unconfirmed")
        return 2
    if not write:
        print("READ-ONLY: pass --write to apply")
        return 0
    log = root / TRADE_LOG
    if log.exists():
        bak = log.with_suffix(log.suffix + ".pre-backfill.bak")
        shutil.copy2(log, bak)
        print("snapshot -> " + str(bak))
    added = 0
    for fill, dec, slot in todo:
        added += ps.append_trade_open(fill, dec, trade_log_path=log, ref_day=day, slot_id=slot,
                                      booked_from="track1_trade_log_backfill")
    print(f"added {added} row(s); {len(todo) - added} already present")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--day", required=True)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    return run(a.root, a.day, write=a.write)


if __name__ == "__main__":
    raise SystemExit(main())
