# Take legacy off the dashboard — phase 1, survey only

The operator has decided: legacy comes off the dashboard. It is retired, its drain is finished, and
the panels that still describe it make the page harder to read than it needs to be.

This phase writes NO code. Read, classify, propose, report, stop. The reason is the size: legacy is
referenced in roughly four hundred places across the dashboard and its backend, and three of those
places are load-bearing for something that has nothing to do with legacy. A blind removal would take
them with it.

## What I measured before writing this, so you do not have to establish it again

The legacy position book holds ZERO open positions. The drain is complete. That is the fact that
makes removal safe rather than blinding: there is nothing left on that route for a panel to fail to
show.

Reference counts, by file, case-insensitive:

    realtime.js                  121
    shared/live.js                 5
    paper.js                       1
    realtime/index.html            1
    backend/schedule_status.py    42
    backend/paper_evidence_reader.py  33
    backend/open_issue_reader.py      24
    backend/app.py                    20
    backend/runner_state_reader.py    19
    backend/job_journal_reader.py     14
    backend/track1_runtime_reader.py  12
    backend/track1_meta_reader.py      8
    backend/execution_quality_reader.py 7
    backend/track1_series_reader.py    2
    monitor/ops.py                    81

Do not treat that last line as in scope. See below.

## Three things must survive, and one of them matters a great deal

### 1. The legacy book is the only place a working equity mark exists

Do not delete the legacy book file, and do not remove the code that reads or writes it in the runner.

Measured today: that book carries a breaker block with real numbers — a peak, a day start, a session
day, a system equity of 50,408.25 and, separately, a last broker equity of 996,730.93. The Track 1
book carries the same concepts as top-level fields and they are all zero, because no Track 1
component writes them. The consequence is that the four-percent daily arm of the circuit breaker
cannot fire on the live route at all.

The legacy writer is the model for fixing that. Its own comment states the reason it exists: every
cron slot is a separate process, so the system ledger and the broker mark it was reconciled against
must both survive on disk, or equity resets to base each slot. It also keeps sleeve equity and whole
account balance as two separate fields and carries a guard that discards a persisted peak larger than
five times the account base, because someone once wrote the broker balance where the sleeve base
belonged.

So: legacy comes off the DASHBOARD. Legacy's equity bookkeeping is the reference for a port that has
not happened yet. If your survey finds a removal that would touch that bookkeeping, list it
separately and do not propose it.

### 2. The schedule parity check

The Track 1 slot table names legacy sixty-six times, and most of those are a parity check: the file
says what the slots would be and a test compares that against the legacy schedule, including the one
legacy job that lands inside the Stress window. That is a test of Track 1 correctness that happens to
use legacy as its yardstick. Removing the yardstick deletes the check.

Report it. Do not propose removing it in this phase.

### 3. The operational drain machinery

The eighty-one references in the ops module start, stop and watch things. That is operations, not
dashboard. Out of scope for this task entirely. Do not touch it, and do not include it in your
proposal.

## What I want you to produce

A classification of every legacy reference in the dashboard surfaces and their backend readers — the
fifteen files above minus the ops module — into exactly four buckets:

- **REMOVE.** Purely a display of legacy, or a route branch that only ever serves legacy. Say what
  the page shows today and what it will show after.
- **KEEP, load-bearing elsewhere.** The reference mentions legacy but something else depends on it.
  Name what depends on it.
- **DECIDE.** Removal is defensible but has a consequence the operator should choose. Two I already
  know of, below; find the rest.
- **CANNOT TELL.** You could not establish which of the above it is. Say so rather than guessing;
  this bucket being non-empty is an acceptable outcome and a silently wrong classification is not.

### The two DECIDE items I already know of

**The staleness dimming.** One of the last round's items exists solely to stop live Track 1 numbers
being dimmed as though they were legacy values a month old. If legacy leaves the page, that whole
mechanism protects nothing, and the four gates written for it become tests of a removed feature.
Say what should happen to them. Do not delete a test in this phase, and do not leave a test asserting
the behaviour of something that no longer exists.

**The registered legacy safety jobs.** Eleven legacy safety jobs are still registered and a test pins
the total job count. With zero open positions they protect nothing. Turning them off is a schedule
change that needs a scheduler restart to take effect and would move a number a test asserts. Report
the arithmetic — what the count is now and what it would become — and stop.

## How to answer

One report, the four buckets, every reference accounted for. A count at the end: how many references,
how many in each bucket, and confirm they add up.

Three labels, kept apart: verified by my own measurement · claimed but not measured · cannot tell from
here. Do not collapse the third into the second.

No code. No file edits. No suite runs are needed for this phase, and if you run any, name them — one
other round is working in the monitor directory and two browser suites must not run at once.

Wait for approval before anything is removed.
