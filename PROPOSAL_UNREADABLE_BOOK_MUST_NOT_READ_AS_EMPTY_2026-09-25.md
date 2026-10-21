# Proposal: a book that cannot be read is not an empty book

Not implemented. This is the live order path and it needs a decision. Written 2026-09-25, after the
incident it describes.

## What happened

The route's position book was erased this morning while the broker held three positions, none with a
stop, and both jobs involved reported "completed OK". The dialect mismatch that started it is fixed.
This proposal is about the second half: why it was silent, and why the obvious fix is wrong.

The chain, measured:

1. The legacy book reader raised on every row of the route's book.
2. Its outer handler caught that, logged a WARNING, and set loaded_positions to an empty list --
   the comment on that branch calls it "fresh start" and the message says "manually verify broker has
   no orphaned positions".
3. With no positions loaded, no stops were placed.
4. The persist step then wrote the book back with an empty positions list inside the correct
   envelope, so nothing downstream objected.
5. WARNING is below the scheduler's ERROR/CRITICAL echo filter, so that line never reached the log.
   Measured: zero occurrences of either phrase in the scheduler log.

## The obvious fix is wrong, and here is the number

The tempting change is to admit WARNING into the parent's loud-line filter so a message like that can
never be lost again. Measured before proposing it:

    monitor/logs/update_ibkr_daily_20260924.log    232 lines, 16 of them WARNING
    monitor/logs/update_ibkr_daily_20260925.log     88 lines,  0 of them WARNING
    global_index/runner.py                          31 logger.warning call sites

The parent's response to loud lines is to log "exited OK but wrote N CRITICAL/ERROR lines -- not
ignoring this" and mark the job accordingly. A data update that emits sixteen warnings on a
successful run would be flagged as a problem every day it succeeds. Within a week nobody reads the
flag. That is the alarm-that-never-turns-off failure, bought at the price of the one message we
wanted.

So: do not widen the filter.

## The proposal

Fix it where the state is decided, not where it is reported.

**A book file that EXISTS and cannot be parsed must not load as zero positions.** It must refuse.

This is not a new rule in this repository; it is the rule two other readers of the same file already
follow, in words:

    track1_paper_executor.read_book
        "A missing file is an empty book and is fine ... A file that exists and cannot be parsed is
        NOT an empty book: it raises, because 'I could not read what I hold' answered as 'I hold
        nothing' is the shape that lets a reconcile pass over a real position."

    _carry_forward_book
        "Refuses on an unreadable book. A window close must not be able to erase a position by
        failing to parse the file that records it."

The legacy reader is the one place that answers the same question the permissive way, and it is the
one place that erased a book.

Three states, not two: file absent is a real empty book; file present and parsed is the answer; file
present and unparseable is an error and must be raised.

## What it costs, stated plainly

After this change, a corrupt or unreadable book stops the safety sweeps: they exit non-zero, the
parent echoes their output, and the dashboard shows a failed job with the reason.

That is not a loss. Compare what the two behaviours actually deliver when the book cannot be read:

    today          no stops placed, book overwritten empty, job reports completed OK
    proposed       no stops placed, book intact, job reports failed with the reason

No stops are placed either way. The difference is whether the record survives and whether anyone is
told.

## Gates

**G1** A book file that does not exist still loads as zero positions, exactly as today. This is the
first-run case and it must keep working.

**G2** A book file that exists with a well-formed empty positions list still loads as zero
positions. Empty is a legitimate answer when it is written down.

**G3** A book file that exists and cannot be parsed raises, and the message names the file and the
parse failure.

**G4** The persist step is never reached on that path, so the book on disk is byte-identical after a
failed load. Assert the bytes, not the row count.

**G5 -- the over-application guard.** Every book and snapshot on disk today that loads must still
load to identical values. That golden set exists: it was built for the dialect change and covers ten
position rows across eight files.

**G6** The suites that cover this path keep their counts: test_contract_month 8, test_operational_fixes
39, test_stp 53, test_runner_book_dialects 10.

## What this does not fix

The scheduler's level filter still drops child WARNING lines, and the job journal still reports an
"unclassified error" for a failure whose reason the child printed on stdout. Those are separate items
on the dashboard list and are being handled there. This proposal makes them matter less by ensuring
the failure is not silent in the first place, rather than by widening what gets echoed.
