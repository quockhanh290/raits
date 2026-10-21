# -*- coding: utf-8 -*-
"""A5 Part 3 — give the MES row the date its own fill journal already carries.

Why this row and no other. The live setup builder discarded the date when it stamped
`entry_time`, so the MES row reads `15:00` with no day attached. The reader added in Part 2
refuses to guess a day from a bare clock, which is correct — but it means the deferral rule
cannot say anything about this position. The row reads "not deferred", which is
indistinguishable from "due", and that is the state it has been in since it was booked.

Where the date comes from. Not from the trade id, and not from the clock. From `ref_day` on the
MES order journal's own `state: "filled"` record for this order id. Measured:

    ref_day    = 2026-09-25
    created_at = 2026-09-25T19:07:02+00:00  -> 15:07:02 ET, the same ET calendar day
    order_id   = 68, avg_price 7797.25, slot TRACK1_SWING_1505

`created_at` corroborates the day and is NOT used as the value: it is the journal's event time,
not the strategy's entry-reference time. The clock stays 15:00, which is the bar the 15:05 slot
decided on.

What changes operationally: nothing for this position. An already-placed stop is never cancelled
when a position becomes deferred — deferred rows are excluded from the branch that inspects or
places a stop, and there is no cancellation branch. MES arms Saturday 2026-09-26 14:00 ET, which
is before the Sunday 18:30 ET sweep, so the first job that looks at it afterwards sees it due,
exactly as it does today. Only the record becomes true.

Run it, read what it prints, and it makes no change unless every check passes.
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

BOOK = Path("live_positions.track1.json")
JOURNAL = Path("global_index/track1_runtime/orders/track1_orders_20260925.jsonl")
TARGET_INSTRUMENT = "MES"
EXPECTED_OLD = "15:00"
APPLY = "--apply" in sys.argv


def fail(msg):
    print("REFUSED: " + msg)
    raise SystemExit(2)


book = json.loads(BOOK.read_text(encoding="utf-8"))
rows = [r for r in book.get("positions", []) if r.get("instrument") == TARGET_INSTRUMENT
        and not r.get("exit_time")]
if len(rows) != 1:
    fail("expected exactly one open %s row, found %d" % (TARGET_INSTRUMENT, len(rows)))
row = rows[0]

if row.get("entry_time") != EXPECTED_OLD:
    fail("the row's entry_time is %r, not the bare clock this repair was written for (%r). "
         "Either it was already repaired or something else wrote it."
         % (row.get("entry_time"), EXPECTED_OLD))
if row.get("entry_day"):
    fail("the row already carries entry_day=%r" % row.get("entry_day"))

order_id = str(row.get("order_id") or "")
if not order_id:
    fail("the row carries no order_id, so its fill cannot be found in the journal")

fills = []
for line in JOURNAL.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    d = json.loads(line)
    if (d.get("instrument") == TARGET_INSTRUMENT and str(d.get("order_id")) == order_id
            and d.get("state") == "filled"):
        fills.append(d)
if len(fills) != 1:
    fail("expected exactly one filled journal record for order %s, found %d"
         % (order_id, len(fills)))
fill = fills[0]

ref_day = str(fill.get("ref_day") or "")
if len(ref_day) != 10:
    fail("the journal record carries ref_day=%r, which is not a date" % ref_day)

# created_at must land on the SAME ET calendar day as ref_day, or the two sources disagree and
# this script has no business picking a winner.
created = str(fill.get("created_at") or "")
try:
    import pandas as pd
    et_day = str(pd.Timestamp(created).tz_convert("America/New_York").date())
except Exception as exc:                                              # noqa: BLE001
    fail("could not convert created_at=%r to an ET day (%s)" % (created, exc))
if et_day != ref_day:
    fail("the journal's ref_day is %s but its created_at falls on ET day %s; two sources "
         "disagree about the entry day and neither wins by default" % (ref_day, et_day))

# The price the book recorded must be the price that fill reported, or this is not that fill.
if abs(float(row.get("entry_price", 0)) - float(fill.get("avg_price", 0))) > 1e-9:
    fail("the row's entry_price %r is not the filled avg_price %r"
         % (row.get("entry_price"), fill.get("avg_price")))

new_value = "%s %s:00" % (ref_day, EXPECTED_OLD)

print("book        : %s" % BOOK)
print("row         : %s order_id=%s entry_price=%s sleeve=%s"
      % (TARGET_INSTRUMENT, order_id, row.get("entry_price"), row.get("sleeve")))
print("journal fill: ref_day=%s created_at=%s (ET day %s) avg_price=%s"
      % (ref_day, created, et_day, fill.get("avg_price")))
print("entry_time  : %r  ->  %r" % (row.get("entry_time"), new_value))
print("all checks passed.")

if not APPLY:
    print()
    print("DRY RUN. Nothing was written. Re-run with --apply to write it.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = BOOK.with_suffix(BOOK.suffix + ".before_mes_entrydate_%s" % stamp)
shutil.copy2(BOOK, backup)
print("snapshot    : %s" % backup)

row["entry_time"] = new_value
row["entry_date_repaired_at"] = datetime.now().astimezone().isoformat()
row["entry_date_repaired_from"] = "order journal ref_day, order_id=%s" % order_id
BOOK.write_text(json.dumps(book, indent=1, sort_keys=True), encoding="utf-8")
print("written.")

# Read it back through the production reader, not through this script's own idea of the schema.
sys.path.insert(0, ".")
from global_index.runner import _openpos_from_dict            # noqa: E402

again = json.loads(BOOK.read_text(encoding="utf-8"))
for r in again["positions"]:
    if r.get("instrument") == TARGET_INSTRUMENT and not r.get("exit_time"):
        p = _openpos_from_dict(r)
        print("reader      : entry_time=%r entry_day=%r" % (p.entry_time, p.entry_day))
        if p.entry_day is None:
            fail("the production reader still derives no entry_day. The snapshot above is the "
                 "pre-change file; restore it.")
print("OK. Next: run the B1 reconcile and confirm it is still PASS with four positions.")
