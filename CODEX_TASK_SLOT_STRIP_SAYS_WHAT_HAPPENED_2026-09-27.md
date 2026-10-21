# The slot strip reads "unknown" while the answer sits in the same row

The market view draws two things across the same horizontal scale: the rule lanes above, and the
slot-decision strip beneath. The lanes give EVERY slot a truthful state. The strip gives most slots
the word unknown. This closes that gap.

## The measurement

Built from the current code, on the live session:

    NKD      22 slots   17 read "unknown"
    Swing    23 slots   11 read "unknown"
    Stress   24 slots    0 read "unknown"

And the slots reading unknown carry their outcome in the very same row:

    TRACK1_NKD_0125     reason = shadow_only            candidate_count = 1
    TRACK1_NKD_0130     reason = shadow_only            candidate_count = 1
    TRACK1_SWING_1505   reason = shadow_only            candidate_count = 2
    TRACK1_SWING_1510   reason = suppress_same_sleeve   candidate_count = 2

The cause is a seven-entry translation table keyed on UPPERCASE words — no signal, signal, accepted,
candidate, rejected, refused, slot refused — with everything else falling through to unknown. The rows
carry lowercase reasons instead, so the fallback catches them all.

So this is not missing information. It is information discarded one line before it would have been
displayed.

Worth knowing what is being hidden: suppress_same_sleeve is the rule that stops a sleeve re-entering an
instrument it already holds. It was repaired two days ago after sixteen slots in one night died
re-proposing the same trade. It now fires, it is recorded, and the page says unknown.

## What to build

The strip's mark must be derived from the same evidence the lanes already use, so that a slot whose
outcome is recorded is never rendered as unrecognised.

Requirements:

- Each real outcome gets its own mark, and outcomes that mean different things must look different.
  Admitted in shadow is not the same as suppressed by a rule, and neither is the same as no signal.
  Do not fold them together to keep the legend short.
- The candidate count is part of the outcome. A slot that found two candidates and suppressed them is a
  different fact from a slot that found none, and today both can read the same.
- Unknown must survive, and must become rare. When a status genuinely is not recognised, the mark must
  NAME THE RAW WORD it did not recognise, so the next gap of this kind is visible on the page instead
  of silently absorbed. A fallback that hides what it fell back from is how this defect lasted.
- Do not widen the table by guessing. For each word you map, say where in the route that word is
  written, so the mapping is anchored to a producer rather than to a screenshot.

## What not to change

The lanes. They are the reference for this work and they are already right.

The strip's alignment with the lanes — cells and slot marks are the same moment on the same scale and
must stay so.

No thresholds. Nothing in the signal layer, the runner or the scheduler. Nothing in the paper tab or
the realtime status rail — separate rounds are working there.

## A separate finding, NOT part of this task

Stress publishes thirteen rule lanes, including its actual detector conditions — breadth, gap-down
count, wide count, average gap, stop reference, stop within max percent, target computed. NKD and Swing
publish four, all generic: gate allow, freshness allow, regime lag, admission cap.

So on two of the three sleeves, the detector's own conditions do not appear as lanes at all. That is a
gap in what those sleeves publish, not in how the page draws it, and it belongs to whoever owns those
detectors. Report it if you confirm it; do not fix it here.

## Gates

- G1. Every declared slot in every sleeve renders with a mark that is not the unrecognised fallback,
  OR names the raw word it did not recognise. Show the count per sleeve before and after: NKD 17,
  Swing 11, Stress 0 are the before figures.
- G2. Each distinct outcome renders distinguishably. Show the legend and one real slot per outcome.
- G3. The candidate count reaches the reader. Show a suppressed slot with two candidates and a
  no-signal slot with none, and state how a reader tells them apart.
- G4. The unrecognised fallback still exists and still names what it saw. Feed it a status no producer
  writes and show the mark.
- G5. Over-application: Stress already reads zero unknown. Show that its twenty-four marks are
  unchanged, all of them.
- G6. Alignment: a lane cell and the slot mark beneath it are still the same moment. Show one slot
  index with both.
- G7. Falsifiability, per test: the one-line mutation it catches, shown RED before green. For the
  fallback specifically, show that removing the raw word from the unrecognised mark turns a test red.
- G8. Suite counts before and after, NAMING EVERY SUITE WITH ITS COUNT.

## A warning about measuring

The running backend process started 2026-09-25 and the readers it serves were modified on the 26th and
27th, so a live query may answer from stale code. Measure through the current code and say whether the
operator has restarted the backend by the time you run.

No broker orders. No writes to the live book. No scheduler or backend restart. No commits.

## How to answer

Eight gates with measured output including the red run. Three labels kept apart: verified by my own
measurement · claimed but not measured · cannot tell from here.
