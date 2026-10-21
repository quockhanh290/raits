# -*- coding: utf-8 -*-
"""Record the Track 1 route's starting equity once, with its provenance.

Why one number is all that is missing. Everything downstream of it is already measured: the book
adds realised profit and loss at settlement, the three marks now survive across slot processes, and
the day baseline is no longer destroyed when a slot opens. Measured end to end on 2026-09-27: with a
starting value in place, a realised loss of 2,100 produced a daily figure of 4.17 percent, level
HALT_DAY and entries refused. Without one, the reader refuses to arm and says why.

Why the figure is the design base and not a computed one. The route has realised NOTHING: zero
closed trades, an empty booked counter, four positions still open. Equity here is realised-only, so
the route's equity IS its base.

And why that distinction has to be written down rather than assumed. Fifty thousand is also the value
a fresh book carries by default, which means the same number can arrive two ways:

    because it is the default sitting in an empty book        -- a fabrication
    because nothing has been realised, so equity IS the base  -- a measured fact

They are indistinguishable once written unless the provenance travels with them. So this records the
evidence beside the value, and refuses if that evidence does not hold.

The base is read from the route's own ACCOUNT constant. It is not typed into this file.

Run it, read what it prints, and it changes nothing unless every check passes.
"""
import glob
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

BOOK = Path("live_positions.track1.json")
APPLY = "--apply" in sys.argv

sys.path.insert(0, ".")
from global_index.track1_params import ACCOUNT                     # noqa: E402
from global_index import track1_signal_layer as sl                 # noqa: E402


def fail(msg):
    print("REFUSED: " + msg)
    raise SystemExit(2)


book = json.loads(BOOK.read_text(encoding="utf-8"))

# CHECK 1 — the marks must be unrecorded. A real mark already present means someone measured it and
# this script must not overwrite it.
marks = {k: book.get(k) for k in ("equity", "peak_equity", "day_start_equity")}
for name, value in marks.items():
    if value not in (None, 0, 0.0):
        fail("%s already carries %r. That is either a measured mark or a bad one, and either way "
             "overwriting it is not this script's job." % (name, value))

# CHECK 2 — the evidence. Equity equals the base ONLY because nothing has been realised.
open_rows = [r for r in book.get("positions", []) if not r.get("exit_time")]
closed_rows = [r for r in book.get("positions", []) if r.get("exit_time")]
booked = book.get("booked_counter") or {}
counters = book.get("counters") or {}

journal_closes = 0
for path in glob.glob("global_index/track1_runtime/**/*.jsonl", recursive=True):
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            row = json.loads(line)
        except Exception:                                          # noqa: BLE001
            continue
        if row.get("action") == "CLOSE" or row.get("exit_reason"):
            journal_closes += 1

if closed_rows or booked or counters or journal_closes:
    fail("the route HAS realised something — %d closed row(s), %d journal close(s), booked=%r, "
         "counters=%r. The starting equity must then be DERIVED from that realised profit and loss, "
         "not taken as the base, and this script cannot do that."
         % (len(closed_rows), journal_closes, booked, counters))

# CHECK 3 — the value must satisfy the reader's OWN rule. This does not reconstruct the band:
# an earlier version of this script recomputed it from a constant, that constant was replaced when
# the band was tightened, and the script broke. So it asks the rule instead of restating it — the
# same discipline the rule itself was given, one place answering one question.
value = float(ACCOUNT)
_probe_dir = Path(tempfile.mkdtemp(prefix="seed_probe_"))
try:
    _probe = _probe_dir / BOOK.name
    _trial = dict(book)
    _trial["equity"] = _trial["peak_equity"] = _trial["day_start_equity"] = value
    _probe.write_text(json.dumps(_trial), encoding="utf-8")
    _verdict = sl.route_book_breaker_state(_probe)
finally:
    shutil.rmtree(_probe_dir, ignore_errors=True)
if not _verdict.get("armed"):
    fail("the reader would REFUSE this value: %s. The band has changed and this script's premise "
         "with it — do not widen the band to fit the seed." % _verdict.get("reason"))

print("book            : %s" % BOOK)
print("open positions  : %d   realised: nothing (this is the evidence)" % len(open_rows))
print("closed rows     : %d   journal closes: %d   booked: %r   counters: %r"
      % (len(closed_rows), journal_closes, booked, counters))
print("account base    : %r  (read from the route's own constant)" % ACCOUNT)
print("reader's verdict: would arm, equity=%r peak=%r day_start=%r"
      % (_verdict.get("equity"), _verdict.get("peak_equity"), _verdict.get("day_start_equity")))
print("would write     : equity = peak_equity = day_start_equity = %r" % value)
print("cur_day         : left as %r — a later session opens its own day and re-baselines, which is"
      % book.get("cur_day"))
print("                  the correct behaviour; this seed is the base that day starts from.")
print("all checks passed.")

if not APPLY:
    print()
    print("DRY RUN. Nothing was written. Re-run with --apply to write it.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = BOOK.with_suffix(BOOK.suffix + ".before_equity_seed_%s" % stamp)
shutil.copy2(BOOK, backup)
print("snapshot        : %s" % backup)

book["equity"] = value
book["peak_equity"] = value
book["day_start_equity"] = value
book["equity_seed"] = {
    "recorded_at": datetime.now().astimezone().isoformat(),
    "value": value,
    "basis": "design account base",
    "why": ("the route had realised nothing when this was recorded, so its realised-only equity "
            "equalled its base"),
    "evidence": {"closed_position_rows": len(closed_rows),
                 "journal_closes": journal_closes,
                 "booked_counter": booked,
                 "counters": counters,
                 "open_positions": len(open_rows)},
    "source_constant": "global_index.track1_params.ACCOUNT",
}
BOOK.write_text(json.dumps(book, indent=1, sort_keys=True), encoding="utf-8")
print("written.")

# Read it back through the SHARED decision function — the same one the slot and the dashboard use.
state = sl.route_book_breaker_state(BOOK)
print("shared reader   : armed=%r equity=%r peak=%r day_start=%r"
      % (state.get("armed"), state.get("equity"), state.get("peak_equity"),
         state.get("day_start_equity")))
if not state.get("armed"):
    fail("the shared reader still refuses to arm: %r. The snapshot above is the pre-change file; "
         "restore it." % state.get("reason"))
print()
print("OK. The brake is armed. Next: record the broker-account baseline so the order gate can open,")
print("and expect the dashboard to show the breaker as ARMED rather than UNARMED from now on.")
