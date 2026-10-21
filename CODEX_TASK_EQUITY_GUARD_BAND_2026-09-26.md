# The breaker's scale guard must bound both sides — approved, implement it

Small change, and the reason it is worth a round of its own is that the guard as designed protects
the direction that already protects itself, and lets through the direction that silently disarms.

## What is wrong with the guard as proposed

The equity-writer design ports the legacy trap guard: refuse a persisted value larger than five times
the account base. Measured against a day start of each shape, with equity at 48,000:

    correct            50,408.25   daily loss    4.78%   halts       passes the guard
    broker balance    996,730.93   daily loss   95.18%   halts       REFUSED by the guard
    a P&L delta           408.25   daily loss  -11657%   DOES NOT    passes the guard
    zero, today             0.00   daily loss    0.00%   DOES NOT    passes the guard

The direction it catches fails safe on its own: a value far too large makes the breaker halt
spuriously, which is visible and annoying. The direction it misses is the one that disarms — a value
far too small makes the daily arm unreachable and admits every entry while reporting a daily loss of
minus eleven thousand percent.

Zero is simply the extreme of too-small, and zero is exactly what the live book carries today. So the
guard as proposed would pass the current broken state without a word.

## What to build

A plausibility BAND, not a ceiling. One rule saying what an equity mark is allowed to look like,
replacing both the upper bound and the special case for zero that the reader currently carries.

Requirements, and the reasoning matters as much as the rule:

- The band is symmetric in intent: a mark too small is as refusable as one too large. Choose the
  bounds and justify them from the account base, not from the numbers in this file.
- A value outside the band must NOT be silently corrected and must NOT arm the breaker. It leaves the
  breaker unarmed with a named reason, the same way the reader already handles zeros today — that
  behaviour is correct and this change makes it principled instead of a special case.
- The reason must name which field was out of band and what it held. An operator reading the slot row
  must be able to tell a book with no marks from a book with an implausible one. Those are different
  situations and today they would read the same.
- The broker mark, when a future writer stores one beside the system equity, is NOT subject to the
  same band — it is legitimately about twenty times the sleeve base. It must never flow into the three
  breaker fields, and the band must not be written in a way that would reject it if it is stored.

## What NOT to do

Do not add a writer. Do not seed anything. Do not change a threshold — warn at 10 percent, halt at 15,
daily at 4, all exact and all unchanged. Do not touch the day-open path; a separate question about
which day boundary applies is still open and the band does not depend on its answer.

Do not touch the legacy bookkeeping. Another round is removing legacy from the dashboard and has been
told that bookkeeping stays.

## Gates

- G1. Each of the four shapes above, run through the guard, with its verdict shown: correct, broker
  balance, P&L delta, zero. The first arms; the other three do not, each with a distinct reason.
- G2. The reason distinguishes an absent mark from an out-of-band one. Show both rows.
- G3. The over-application guard. A book carrying plausible marks arms exactly as it does today, with
  the same equity, peak and day start. Nothing about the working path changes.
- G4. Falsifiability, per test: name the one-line mutation it catches and show it RED under that
  mutation before green. For the band in particular, show that widening it to a bare ceiling turns the
  too-small test red.
- G5. Regression, and read this bound carefully. Run ONLY the suites under global_index that import
  the changed module. Do NOT run any suite under monitor — another round is editing one of them right
  now and two browser suites must not run at once. Name every suite you ran and its before and after
  count, measured by you.

## Scope

The Track 1 signal layer and its tests under global_index. Nothing under monitor, nothing under
dash, nothing in the runner — a third round is working in the runner's book loader.

No broker orders. No writes to the live book. No scheduler or backend restart. No commits.

## How to answer

Five gates with measured output including the red runs. Three labels kept apart: verified by my own
measurement · claimed but not measured · cannot tell from here.
