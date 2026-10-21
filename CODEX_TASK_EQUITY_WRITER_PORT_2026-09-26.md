# The circuit breaker has no equity to breaker on — design the port, phase 1

No code in this phase. Read, design, report, stop. The reason is that the thing being designed writes
to a file the live route reads before every entry decision, and a wrong scale in that file keeps the
breaker wrong until someone notices. Once has already happened, one route over.

## The state of it, measured, so you start from facts and not from the spec

The four-percent daily-loss arm of the Track 1 circuit breaker cannot fire. Two independent reasons.

**Nothing writes an equity mark.** The live route book carries equity, peak equity and day start
equity as top-level fields and all three are zero, alongside four real open positions. The book repair
writes them as zero deliberately and says in its own output that they are reconstructed rather than
recovered. So there is no number for a day to be measured against.

**And the day start is destroyed even when it is seeded.** There are two rebase paths and they behave
differently. The update call initialises the day start only when it is absent. The day-open call
overwrites it unconditionally with the equity as it stands right then. Every slot is a separate
process, so every slot opens with no current day and takes the second path. Measured: seed a day start
of 54,000 against an equity of 51,000 — a 5.6 percent day, past a 4 percent limit — and the daily loss
reads exactly 0.00 percent, because the seed was replaced at the moment the instant opened. Seed it and
DO NOT let the open rebase it, and the same breaker returns a day halt at 5.56 percent. So the branch
works. It is unreachable.

The peak-drawdown arm does work, and its thresholds are exact rather than approximate: warn and half
size at 10 percent, refuse at 15, daily at 4.

## The part that changes the design: this is a port, not an invention

The legacy route already solved all of this, and its book still holds the proof — a breaker block with
a peak, a day start, a session day, a system equity of 50,408.25 and, separately, a last broker equity
of 996,730.93.

The code that writes it states the reason in its own comment: every cron slot is a separate process, so
the system ledger and the broker mark it was last reconciled against must both survive on disk, or
equity resets to base each slot and the same profit is re-booked every five minutes.

It also carries the trap and the guard. The trap is writing the broker's whole account balance where
the sleeve's own equity belongs. The guard discards a persisted peak larger than five times the account
base and logs that such a value was recorded against the broker balance rather than the system base.
That guard exists because the mistake was made.

So the question "which equity source is authoritative" is already answered by the route that ran for
years: the sleeve's own system equity, with the broker mark kept beside it for reconciliation and never
allowed to flow into it. Your design should follow that answer unless you can show it is wrong here,
in which case say why.

One thing already in your favour: the reader on the new route treats those zeros as absent and says so
rather than trusting them. The day a writer starts filling them, the breaker arms itself with no
further change to the reader.

## What the report must answer

1. **The field mapping.** Legacy's nested breaker block against the live route's top-level fields, field
   by field. Name every legacy field that has no home on the new schema and say whether it needs one.
   The new schema is version two and the fields moved out of a nested block on purpose; do not propose
   reverting the shape.

2. **Where the writer is called from, and at which instant.** Every slot is a separate process. Say
   which slot writes the day start, what makes it the first slot of a session rather than a later one,
   and what happens on a restart or a missed first slot. Say separately when equity and peak are
   written, which is not the same instant.

3. **How a seeded day start survives the open.** This is the crux and a mapping alone does not solve
   it. The day-open call overwrites unconditionally. Say what has to change so that a day start read
   from disk is not destroyed, and say it in terms of what the book already carries — it does carry the
   session day it belongs to, which is the piece that exists.

4. **The scale guard on the new route.** State what it should be and what it should do when it fires.
   Silently correcting a wrong scale is not acceptable; neither is arming a breaker on a number five
   times too large.

5. **The day with no fills.** What the writer does on a session where nothing trades, and what the
   record says on the next session. A day start that quietly carries forward from last week is worse
   than an absent one.

6. **What this does NOT fix.** Be explicit. If a working daily arm would change which entries are
   refused, say so plainly — the operator needs to know that arming a dead safety layer is a change in
   behaviour, not only a change in honesty.

## What to leave alone

Do not write code. Do not seed anything, do not add a writer, do not change a threshold, do not touch
the book.

Do not touch the legacy route. A separate round is surveying legacy for removal from the dashboard and
has been told explicitly that legacy's equity bookkeeping stays until this port exists. Read it as
much as you like; change nothing.

Do not run any browser suite. Another round is working in the monitor directory.

## How to answer

The six questions, in order. Commands and raw output for anything you assert about current behaviour.

Three labels, kept apart: verified by my own measurement · claimed but not measured · cannot tell from
here. Do not collapse the third into the second.

Where the design has a genuine fork the operator should choose, present it as a fork with its
consequences rather than picking one and moving on. Where it does not, do not invent one.
