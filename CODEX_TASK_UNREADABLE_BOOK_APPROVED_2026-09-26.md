# A book that cannot be read is not an empty book — approved, implement it

The operator has approved this. The proposal is PROPOSAL_UNREADABLE_BOOK_MUST_NOT_READ_AS_EMPTY_2026-09-25.md
at the repo root. Read it first, in full, including the part that explains why the obvious fix is
wrong — you will be tempted by that fix and the numbers against it are already measured.

This is the live order path. It is the change that has already cost us once.

## The one-line version

The shared position-book loader answers "I could not read what I hold" with "I hold nothing". Make it
refuse instead. Three states, not two: file absent is a genuine empty book, file present and parsed is
the answer, file present and unparseable is an error and must raise.

Two other readers of the same file already follow that rule and say so in their own words. The one
that does not is the one that erased a book.

## What you must not do

Do not widen the parent's loud-line filter to admit warnings. The proposal measures why: one data
update emits sixteen warnings on a successful run, so every successful day would be flagged as a
problem and within a week nobody reads the flag. Fix it where the state is decided, not where it is
reported.

Do not change what happens when the file is absent. That is the first-run case and it works.

## Gates

The proposal carries six and they are the gates for this task. Every one needs measured output in your
report, not prose.

- G1. An absent book file still loads as zero positions, exactly as today.
- G2. A book file that exists with a well-formed empty positions list still loads as zero positions.
  Empty is a legitimate answer when it is written down.
- G3. A book file that exists and cannot be parsed raises, and the message names the file and the
  parse failure.
- G4. The persist step is never reached on that path. Assert the BYTES of the book on disk are
  identical after a failed load, not the row count — a row count can match while the envelope was
  rewritten.
- G5. The over-application guard. Every book and snapshot on disk today that loads must still load to
  identical values. That golden set already exists; it was built for the dialect change and covers ten
  position rows across eight files. Use it rather than building a new one.
- G6. Suite counts. The proposal names four suites and the counts they had when it was written. Measure
  your OWN before-counts rather than trusting those numbers — one of them has moved since, for an
  unrelated and correct reason, and a baseline you did not measure is worse than none.

Plus one the proposal does not state, because it was written before today's lesson:

- G7. Falsifiability, per test you add: name the one-line mutation it catches and show it RED under
  that mutation before you show it green. A test that cannot be made to fail has measured nothing.
  For G3 in particular: show that reverting the refusal to a swallowed exception turns your test red.

## What this does not fix, and must not pretend to

The scheduler still drops child warning lines, and the job journal still reports an unclassified error
for a failure whose reason the child printed on stdout. Those are separate items. This change makes
them matter less because the failure stops being silent at the source; it does not address them, and
your report should not claim it does.

## Scope

The shared book loader and its tests. Do not touch dashboard or monitor files — another round is
removing legacy from those and the two must not collide. Do not touch the legacy equity bookkeeping:
it is the reference for a port that has not happened yet and a third round is designing that.

No broker orders. No writes to the live book. No scheduler or backend restart. No commits.

## How to answer

The seven gates with their measured output, including the red run G7 asks for.

Three labels, kept apart: verified by my own measurement · claimed but not measured · cannot tell from
here. Do not collapse the third into the second.
