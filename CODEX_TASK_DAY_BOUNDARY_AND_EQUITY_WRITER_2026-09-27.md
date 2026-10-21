# The day baseline moves to where the accepted replay puts it, and the breaker finally gets marks

Operator decision, taken 2026-09-26: option (a). The day baseline is taken BEFORE the day's first
closes are booked, matching the replay that produced the accepted portfolio figures.

This is the most consequential change in this series. It alters which entries are admitted. Read the
whole file before touching anything, and note that it has a HARD STOP in the middle.

## Stage 1 — measure what the change costs before making it. Do this first and stop.

The ordering you are about to change lives in the same function that produced Track 1's own recorded
figures. There is a comment in the parameters module referring to that function by name and quoting a
figure difference, so the vault windows run through it.

So before implementing anything:

1. Reproduce Track 1's recorded figures on the current tree. Whatever the canonical shadow or vault
   reproduction is, run it and record the numbers exactly as it prints them.
2. Then apply ONLY the ordering change described in stage 2 item 1, and run the same reproduction again.
3. Report both sets side by side.

If any figure moves, STOP and report. Do not proceed to the rest. A moved figure means Track 1's
recorded numbers were produced under the old rule and the operator has to decide what replaces them.
That is a decision, not a consequence to absorb.

If nothing moves, say so with both outputs shown, and continue.

## Stage 2 — the change, in four parts

### 1. The day opens before the closes are booked

The accepted replay does three things in this order, and it is three steps rather than a swap of two
lines. Measured from its own source:

    the day rolls and the baseline is taken       -- BEFORE this instant's closes
    the closes due at this instant are booked     -- equity moves here
    the breaker updates and returns its verdict   -- AFTER the closes

The live instant loop currently settles first and then does all three of the remaining steps together
inside one call. Splitting matters: if the breaker's update ran before the closes were booked, the peak
would miss this instant's profit and loss, which is a different bug in the other direction.

So: the day-roll and baseline capture move ahead of settling. The update and the verdict stay after it.

### 2. A baseline read from disk survives the open

Every slot is its own process, so the book always opens with no current day and the baseline is
re-captured every five minutes. Seed the session day from the book alongside the equity marks, and make
the day-roll treat a session day equal to today as a day already open — do not re-capture, do not
overwrite. Only a genuinely new or absent session day opens a day.

### 3. The writer

Write the equity marks to the route book. The model is the retired route, which solved this exact
problem and whose book still carries real numbers; its own comment states the reason — every cron slot
is a separate process, so the ledger and the broker mark it was reconciled against must both survive on
disk or equity resets to base each slot.

Per the operator's decision, only the broker mark gains a home beside the three breaker marks. The epoch
and the paper-start fields served the retired route and do not come across.

The broker mark is context for reconciliation and must never flow into equity, peak or day start.

### 4. The guard against the easiest wrong implementation — read this twice

There is already a flag that serialises the book including all three marks. Turning it on for a live
slot is the shortest path to "the writer exists" and it is WRONG.

Measured: a fresh slot book carries an equity of fifty thousand by default — the account constant. So
that flag on a live slot writes the account constant as though it were a measured mark. It is in the
right unit, it sits inside the plausibility band, the band passes it, and the breaker arms on a
fabricated number while reporting itself armed.

Whatever you build must be incapable of writing a number that was not measured. If you cannot
distinguish "measured" from "the default that happens to be plausible", say so and stop — that is a
design problem worth surfacing, not a detail to route around.

## The gate that exists because I measured it failing

The two-reader agreement test compares two readers of the book. Both read the recorded day start. The
running slot does not, and that is the whole defect.

Measured on a book with equity 51,000, peak 55,000 and day start 54,000 — a 5.6 percent day, past the
four percent limit:

    the dashboard reported     ARMED, level HALT_DAY, daily 5.56%, entries refused
    the running slot held      level OK, daily 0.00%, entries ALLOWED, day start overwritten to 51,000

The page says the brake fired and the engine lets trades through. Extend the agreement test to compare
the dashboard against THE SLOT BREAKER AFTER THE DAY HAS OPENED, not only against the shared book
reader. Two readers of one file will always agree; that is not the question an operator is asking.

That extended test must be RED on the current tree — if it is green before your change, it is not
testing what I just measured, and you should say so rather than continue.

## Gates

- G1. Stage 1's two reproductions, side by side, with the verdict on whether any figure moved.
- G2. The three-step order, shown: a position closing at the day's first instant counts toward that
  day's loss. Build the case and show the daily figure with and without the change.
- G3. A seeded session day equal to today is not re-opened, and the recorded baseline survives a slot
  run. Show the baseline before and after.
- G4. The writer never writes an unmeasured number. Show what happens on a slot that has measured
  nothing — it must write nothing or write an explicit absence, not the account constant.
- G5. The extended agreement test, red before and green after. Both runs.
- G6. The over-application guard. A day with no closes at its first instant behaves exactly as it does
  today. Same decisions, same verdicts, same counts.
- G7. No regression, measured by you before and after, and NAME EVERY SUITE WITH ITS COUNT. Include at
  minimum the risk-wire suite, the book dialect suite, the slot-sees-what-the-route-holds suite, the
  entry-date suite, and the agreement suite. A list of suites without counts is not a gate.
- G8. Falsifiability, per test you add: name the one-line mutation it catches and show it red under that
  mutation before green.

## Scope

The signal layer's instant loop and seeding, the live slot's writer, and their tests, plus the agreement
test. Do not change any threshold — ten, fifteen and four stay exactly as they are. Do not touch the
dashboard's rendering. Do not touch the runner.

No broker orders. No writes to the LIVE book outside a test temporary directory. No scheduler or backend
restart. No commits.

## How to answer

Stage 1 first, on its own, and stop there if a figure moved. Otherwise both stages with all eight gates
measured.

Three labels, kept apart: verified by my own measurement · claimed but not measured · cannot tell from
here. Do not collapse the third into the second.
