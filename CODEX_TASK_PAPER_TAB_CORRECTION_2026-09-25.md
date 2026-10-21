# Paper tab correction — the clause I left out of my own gate

Read this whole file first. One defect, one missing clause, and two suites that were never run.

Batch 2 is accepted. The paper tab now reconciles protection against broker positions and working
stop orders in three states, the book dialect falls back, eight rows that read NOT_WIRED were
wired, the fill-quality label reads as correspondence rather than cost, and zero renders differently
from absent. None of that is being re-opened.

This file is about one place where the fix reached further than the defect, and it is my fault, not
yours: the gate I wrote said "when the broker cannot be read, say unknown" and was missing the
clause "unless there is nothing to protect".

---

## The defect

With ZERO persisted positions and a broker that cannot be read, the tab now renders UNKNOWN.

It should render nothing-to-protect: zero of zero. With no positions there is nothing a stop could
be protecting, and that is knowable without the broker. UNKNOWN there is a false uncertainty —
the same family as the defect Batch 2 fixed, pointed the other way.

Keep the distinction sharp, because the correct behaviour differs by case and all three must hold
at once:

| Positions | Broker | What the tab must say |
|---|---|---|
| zero | unreadable | nothing to protect — zero of zero. NOT unknown |
| zero | readable | nothing to protect — zero of zero |
| one or more | unreadable | unknown, with the reason. This is what Batch 2 correctly added |
| one or more | readable | the real count, in the three states already built |

The third row is the one Batch 2 was written for and it must not regress.

---

## What to do

1. Add the missing clause where the unknown state is decided. The absence of positions is checked
   before the broker is consulted, because it does not depend on the broker.

2. Run the two suites Batch 2 never ran: the paper DOM suite and the dashboard backend suite. At
   least one test in the paper DOM suite is currently red on this exact case — I ran it, which is
   how the defect was found, and Batch 2's own gates did not catch it. Report the full red set in
   BOTH suites before you change anything, with raw output. That is step one, not step two.

3. If the dashboard backend suite has failures whose fixtures encode the pre-Batch-2 behaviour —
   that is, fixtures asserting the old silence rather than a real defect — you have permission to
   update those fixtures, and only those. Name each one and say what it asserted before and after.
   Any failure that is NOT of that kind, stop and report it instead of fixing it.

---

## Gates

Show measured output for each. Prose is not a gate.

- G1. All four rows of the table above, each rendered, each shown. Four outputs, not a description
  of four outputs.
- G2. The red test that found this goes green, and I want to see it red first on the unchanged tree
  and green after. It is not obsolete: it was written after three panels each answered the
  empty-book case differently, and it carries a control assertion beneath it. Do not delete or skip
  it.
- G3. Over-application, the half people leave out. A tab WITH positions and an unreadable broker
  still says unknown with its reason. Show it, before and after, unchanged.
- G4. Both suite counts. Before and after, raw. The dashboard backend suite was at 225 passing
  before this round of work; if your before-count is not 225, say what it is and do not adjust
  anything to reach that number — a mismatch is a finding.

- G6. One more red test, found by a wide regression run I finished at 22:18 machine time and
  measured rather than guessed. In the dashboard truthfulness suite, the test that checks a naked
  position adds a next-protection line without replacing the next job asserts the protection line
  reads as a bare clock. The panel now renders a weekday in front of it, so the assertion fails on a
  string while the rendered text is strictly more informative than what the test was written for.
  The sibling assertion on the line above, which carries no time, still passes.

  Decide which side is right and say why, in one line, before you change either. If the weekday is
  wanted, the fixture is stale and you may update that one assertion. If it is not, the renderer is
  wrong and the test is doing its job. Do not change both to meet in the middle.
- G5. Falsifiability, per test you add or touch: name the one-line mutation it catches and show it
  red under that mutation. A test that cannot be made to fail has measured nothing.

---

## Scope

Dashboard and monitor files only. Do NOT touch the live slot or the signal layer — a separate batch
is in flight on those two files and the two must not collide. If a fix seems to require either
file, stop and say so.

No broker orders. No scheduler or backend restart. No commits.

---

## How to answer

Three labels, kept apart: verified by my own measurement · claimed but not measured · cannot tell
from here. Do not collapse the third into the second.

Report the red set from step 2 first. If what you find disagrees with what I wrote above, say so —
I found this by running one suite, not by reading every panel, and the description of the defect is
only as good as that one run.
