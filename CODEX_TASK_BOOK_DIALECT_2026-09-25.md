# Task: one book, two dialects — teach the live runner to read and write both

This is on the LIVE ORDER PATH. It has a hard deadline and a no-regression requirement that is
stricter than the fix itself. Read the whole file before editing anything.

All output in ENGLISH only. Do not run git add or git commit. Do not restart the scheduler or the
backend. Do not delete any parquet file or anything under data/cache/.

---

## 1. What happened, so you can see what the fix has to survive

The route keeps its open positions in a JSON book. There are two books with the same shape and two
different dialects for the same three fields:

    legacy  live_positions.json          inst        contracts   cluster
    track1  live_positions.track1.json   instrument  qty         sleeve

Two scheduled safety jobs — the stop-repair sweep and the max-hold exit — are built on the LEGACY
runner and are pointed at the TRACK 1 book on purpose. Yesterday the Track 1 route held its first
real positions. This morning those jobs read that book, did not recognise the dialect, and the
consequences ran all the way through:

1. Every row raised on a missing key. Measured, read-only, against a snapshot of the 3-position
   book:

        python -c "import sys,json; sys.path.insert(0,'.'); from global_index.runner import _openpos_from_dict; rows=json.load(open('live_positions.track1.json.before_qty_repair_20260924_232859',encoding='utf-8'))['positions']; [print(r['instrument'], '->', type(e).__name__, e) for r in rows for e in [None] if False] "

   Simpler form, which is what was actually run:

        for each row:  _openpos_from_dict(row)  ->  KeyError: 'inst'      (all 3 rows)

2. The loader's outer handler swallows that to a WARNING and sets loaded_positions = [] with the
   message "failed to load ... — fresh start; manually verify broker has no orphaned positions".
3. WARNING is below the scheduler's ERROR/CRITICAL echo filter, so that line never reached the log
   at all. Measured: 0 occurrences of "failed to load" and 0 of "manually verify broker has no
   orphaned" in monitor/logs/ops_scheduler.err.log.
4. With zero positions loaded, no stops were placed.
5. The persist step then wrote the book back with positions = [] inside the correct envelope, so the
   file still looked valid and nothing downstream objected.
6. Both jobs reported "completed OK".

Result at 12:0x ET: the broker holds 3 positions, the book holds 0, none has a stop, and the
dashboard showed a clean morning.

**Do not fix items 2 and 3.** The swallowing handler and the log filter are real defects and they
are being handled separately. Widening either of them is out of scope and would change what every
job on the page reports.

---

## 2. The fix

Two functions in global_index/runner.py, and nothing else in that file.

**Read side.** _openpos_from_dict accepts either dialect for the three fields that differ:

    inst       <- "inst"       or "instrument"
    contracts  <- "contracts"  or "qty"
    cluster    <- "cluster"    or "sleeve"

Everything else in that function stays exactly as it is.

**Write side, and this is the half that is easy to miss.** _openpos_to_dict currently emits only
the legacy dialect. If you fix the read side alone, the sweep will load the three Track 1 rows and
then write them back as inst/contracts/cluster into the Track 1 book — and then the Track 1 readers
cannot read their own book. You would have converted a silent failure into a loud one, which is
better and still broken.

So the writer must emit a row both dialects can read. Write both spellings, with the same values.

**Fail-closed is not negotiable.** A row carrying NEITHER spelling must still raise, exactly as it
does today. The comment above the function says so, and it is right: there is no sensible default
for an instrument or a size, and a fresh start is the correct response to a row nobody can parse.

**A row carrying BOTH spellings with DIFFERENT values must raise too.** That cannot happen today,
but it becomes possible the moment both are written, and silently picking one is how the two drift
apart for months. Refuse loudly instead.

---

## 3. The no-regression gates. These matter more than the fix.

This code is the live order path for both routes. "It works for Track 1 now" is not the bar.

**G1 — equivalence, anchored on values measured BEFORE your change.** Build a golden file first,
while the code is untouched: for every position row in every book and snapshot you can find on disk,
record what _openpos_from_dict returns today, field by field. Include at least:

    live_positions.json
    live_positions.track1.json
    live_positions.track1.json.before_qty_repair_20260924_232859
    live_positions.track1.json.pre-backfill-20260924T165053.bak
    live_positions.track1.json.pre-cleanup-20260924T164932.bak
    live_positions.track1.json.corrupt-20260826T113414.bak
    anything else matching live_positions*.json* or any positions book under _archive/

Rows that raise today must be recorded as raising, with the exception type and the key. After the
change, every row that loaded must load to identical values, and every row that raised for a reason
OTHER than the three dialect fields must still raise. That last clause is the point: your change may
only turn a dialect KeyError into a successful load. It may not rescue anything else.

Note that live_positions.json and live_positions.track1.json both hold 0 rows right now, so the
golden file's substance comes from the snapshots. If your golden set ends up empty, the gate proved
nothing — assert it is non-empty before comparing.

**G2 — a Track 1 row loads, with the right values.** inst, contracts and cluster must come out as
the instrument, the size and the sleeve. Assert the numbers, not just that it did not raise.

**G3 — a row with neither spelling still raises.** Assert the exception type.

**G4 — a row with both spellings and conflicting values raises.** Assert it, and assert the message
names the field.

**G5 — round trip, both directions.** A row written by _openpos_to_dict must load through
_openpos_from_dict to the same values, AND be readable by the Track 1 side:

    global_index/track1_signal_layer.py::read_route_positions  and  seed_open_positions
    global_index/track1_b1.py::read_track1_book

Feed a written row to those and assert they accept it and see the right size. This is the gate that
catches the write-side half being forgotten.

**G6 — the legacy dialect is still present and unchanged in what gets written.** Assert that a
written row still contains inst, contracts and cluster with the same values they have today. Other
code and other readers depend on those names; this change adds, it does not rename.

**G7 — the suites that cover this path do not regress.** Baselines measured immediately before this
file was written:

    global_index/test_contract_month.py                                8 passed
    global_index/test_operational_fixes.py                             39 passed
    global_index/test_stp.py                                           53 passed
    scratch/test_track1_stage5zs_book_carry_forward_20260826.py        1 failed, 41 passed, 1 skipped
    scratch/test_track1_stage5zg_route_aware_safety_reporting_20260825.py   3 failed

The four failures are present BEFORE your change. Three of them are the "orders are still
impossible" family and a job-inventory assertion; whether they are old or recent has not been
isolated, and it is not your job to fix them. The gate is: the same four fail, by name, and nothing
new joins them.

There are 26 test files that import the runner. Run at least the five above. If you have time, run
more and report what you ran.

**G8 — you wrote nothing to live state.** Record these at the start and the end and report both.
They must be identical, whatever they are:

    python -c "import hashlib;print(hashlib.sha256(open('live_positions.track1.json','rb').read()).hexdigest())"
    python -c "import hashlib;print(hashlib.sha256(open('live_positions.json','rb').read()).hexdigest())"

---

## 4. Files

MODIFY:

    global_index/runner.py                 the two serialisation functions only
    new test files you create under global_index/

DO NOT MODIFY, for any reason:

    live_positions.json  live_positions.track1.json  and any .bak or snapshot beside them
    anything under global_index/track1_runtime/
    global_index/run_stop_repair.py  global_index/run_maxhold_exit.py
    global_index/track1_signal_layer.py  global_index/run_live_day_track1.py
    global_index/track1_paper_send.py  global_index/track1_gates.py
    monitor/**  scratch/**
    TASK.md  SCRATCHPAD.md

Restoring the three position rows into the live book is NOT your task. It is a live-data write and
it stays with the operator.

---

## 5. Deadline and why it is real

The scheduled stop-repair sweep runs at **16:20 ET today**. The operator has deliberately chosen to
let that scheduled run be the test: if the mechanism places the three stops, it is proven; if it
does not, that is a second defect and they want to see it rather than mask it with a manual run.

So your change must be finished and verified before 16:20 ET. Do not run the sweep yourself to check
your work — that would consume the very observation the operator is waiting for. Prove the fix with
tests and with the golden-file comparison, not by running the live job.

---

## 6. Report

    BASELINE HASHES   the two hashes at the start
    GOLDEN FILE       where you put it, how many rows it covers, and how many of those raise today
    CHANGE            the two functions, what you changed, quoted
    GATES             G1 through G8, each PASS/FAIL with the command and its output
    SUITES            every suite you ran, counts before and after
    END HASHES        the two hashes at the end
    NOT DONE          anything left, with the reason
    PLAN PROBLEMS     anything in this file you believe is wrong, or empty — and if empty, say you
                      looked
