# -*- coding: utf-8 -*-
"""Restore the three position rows the morning sweep erased.

Nothing here is invented. The rows come from the book as it stood at 23:28 ET on 2026-09-24 --
the state B1 verified against the broker at the time -- with MNKD's size corrected from the order
journal, where order 40 records qty 1.

Refuses rather than guessing:
  * if the live book is not empty (someone else has already acted)
  * if the snapshot's (instrument, direction, qty) set does not match what the broker holds now
  * if any row's size cannot be confirmed by a FILLED order-journal row

READ-ONLY unless --write is passed.
"""
import argparse
import glob
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "d:/raits")

BOOK = Path("live_positions.track1.json")
SNAP = Path("live_positions.track1.json.before_qty_repair_20260924_232859")

ap = argparse.ArgumentParser()
ap.add_argument("--write", action="store_true")
a = ap.parse_args()


def refuse(msg):
    print("REFUSED:", msg)
    raise SystemExit(2)


live = json.loads(BOOK.read_text(encoding="utf-8"))
if live.get("positions"):
    refuse("the live book already holds %d position(s); nothing to restore"
           % len(live["positions"]))

rows = json.loads(SNAP.read_text(encoding="utf-8"))["positions"]
if len(rows) != 3:
    refuse("the snapshot holds %d rows, expected 3" % len(rows))

# what the order journal says was FILLED, by trade id
filled = {}
for f in sorted(glob.glob("global_index/track1_runtime/orders/track1_orders_*.jsonl")):
    for line in Path(f).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if str(r.get("state")) == "filled" and str(r.get("action")) == "OPEN":
            filled[str(r.get("candidate_id") or r.get("trade_id"))] = r

# what the broker holds right now
from global_index.ibkr_broker import IBKRBroker                                # noqa: E402

br = IBKRBroker(port=4002, client_id=95)
br.connect()
try:
    held = {(str(p.inst)[:4].rstrip("Z6"), str(p.direction).upper()): int(p.contracts)
            for p in br.get_positions()}
    raw_held = [(p.inst, p.direction, p.contracts) for p in br.get_positions()]
finally:
    br.disconnect()
print("broker holds:", raw_held)

fixed = []
for row in rows:
    tid = str(row["trade_id"])
    j = filled.get(tid)
    if not j:
        refuse("no FILLED order-journal row for %s; its size cannot be confirmed" % tid)
    jq = int(j.get("qty") or 0)
    if jq <= 0:
        refuse("the journal records qty %r for %s" % (j.get("qty"), tid))
    root = str(row["instrument"])
    match = [v for (i, d), v in held.items() if i.startswith(root[:3]) and d == str(
        row["direction"]).upper()]
    if not match:
        refuse("the broker holds nothing matching %s %s" % (root, row["direction"]))
    if match[0] != jq:
        refuse("the broker holds %d of %s but the journal says %d" % (match[0], root, jq))
    new = dict(row)
    new["qty"] = jq
    new["restored_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new["restored_reason"] = (
        "the legacy runner's book reader demanded the engine's field spelling, raised on every "
        "row of this route's book, and the outer handler persisted an empty book over three live "
        "positions on 2026-09-25 around 08:20-09:31 ET. Rows restored from the 23:28 ET snapshot "
        "of 2026-09-24; size confirmed against order %s in the order journal and against the "
        "broker's own count" % j.get("order_id"))
    fixed.append(new)
    print("  %-5s qty %s -> %s  (order %s, broker %d)"
          % (root, row["qty"], jq, j.get("order_id"), match[0]))

if not a.write:
    print()
    print("READ-ONLY. Re-run with --write to apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
snap = BOOK.with_suffix(".json.before_restore_%s" % stamp)
shutil.copyfile(BOOK, snap)
live["positions"] = fixed
BOOK.write_text(json.dumps(live, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print()
print("snapshot :", snap.name)
print("restored :", [(r["instrument"], r["qty"]) for r in fixed])
