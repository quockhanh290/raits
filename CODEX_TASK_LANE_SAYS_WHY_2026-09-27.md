# Seven lanes read as blank rows, and their explanations blame the wrong rule

Two defects in the same place, found because the operator said seven rows on the Stress tab look empty.
The visual complaint is real. The reason those rows give for being empty is worse.

## Measured, on the live session, through current code

The Stress sleeve publishes thirteen lanes over twenty-four slots. Six carry verdicts. Seven carry one
uniform non-verdict state across all twenty-four cells, rendered in muted and hollow classes, so they
read as blank rows:

    mnq only short setup       not_published x24    "value not published by the detector"
    pre high stop reference    not_published x24    "value not published by the detector"
    stop within max pct        not_published x24    "value not published by the detector"
    rr target computed         not_published x24    "value not published by the detector"
    same symbol suppression    not_reached   x24    "not reached — the gate stopped the slot first"
    family cap                not_reached   x24    "not reached — the gate stopped the slot first"
    cluster cap               not_reached   x24    "not reached — the gate stopped the slot first"

And in the SAME payload:

    gate allow                 pass x24             24/24 pass
    freshness allow            pass x24             24/24 pass
    gapdown count              fail x24              0/24 pass
    avg gap                    fail x24              0/24 pass

## The second defect, and take it first

Three lanes say the gate stopped the slot. The gate passed twenty-four out of twenty-four, in the same
payload, two rows above. The sentence is false and the evidence contradicting it is on the same screen.

What actually happened is visible in the same thirteen rows: the setup failed at gapdown count and at
average gap, so no candidate was produced, so the admission rules never had anything to admit.

The other four say the detector did not publish a value, which reads as the detector failing to do its
job. It did its job and stopped early, for the same reason: two rules had already failed, so the stop
reference, the stop-width check and the target were never computed.

So all seven rows have the same true cause and none of them says it. This is the same defect family the
week has been spent on: a status branch that asserts the story of the one case it was written for.

The fix is that the sentence must be DERIVED from which rule actually stopped the chain, not asserted.
If the chain cannot be determined from the payload, say that instead — do not fall back to naming a
rule that passed.

## The first defect

A lane whose every cell carries one non-verdict state must read as a statement, not as an absence. The
word column already exists and already carries text; the twenty-four faint cells are what read as
nothing, and a reader scanning the card sees seven empty rows.

Make those lanes legible as what they are. The requirement is the outcome, not a specific design: a
reader must be able to tell, without hovering, that the row HAS an answer and what kind of answer it
is. And the two kinds must stay distinguishable — a rule that was never reached is not the same as a
rule whose value was never published, and today both look like nothing.

Do not solve it by making the cells louder in a way that competes with real failures. A failed rule
must remain the most visible thing on the card.

## What not to change

The six lanes that carry verdicts. They are the reference.

The cell-per-slot construction. Every lane already has one cell per slot and that is correct — the
complaint is legibility, not coverage. Do not reduce or reflow the cells.

The alignment between a lane cell and the slot mark beneath it.

Nothing in the detectors, the signal layer, the runner or the scheduler. The separate finding that NKD
and Swing publish only four generic lanes is NOT in scope and is not a rendering problem.

## Gates

- G1. The corrected cause, on the live session: the three admission lanes and the four setup lanes each
  name what actually stopped the chain. Show all seven rows, before and after.
- G2. The control that makes G1 mean something: build a case where the GATE really did stop the slots,
  and show that those lanes then say the gate stopped them. A fix that simply stops mentioning the gate
  fails this.
- G3. The two kinds stay distinct. Show a not-reached lane and a not-published lane side by side and
  state how a reader tells them apart without hovering.
- G4. Legibility: the seven rows shown before and after, and a one-line statement of what a reader now
  sees that they did not see before.
- G5. Over-application: a failed rule is still the most visible thing on the card. Show the gapdown
  count lane unchanged in prominence.
- G6. Alignment unchanged: one slot index, its lane cell and its slot mark, still the same moment.
- G7. Falsifiability, per test: the one-line mutation it catches, shown RED before green. For the cause
  specifically, show that reverting to the hardcoded gate sentence turns a test red.
- G8. Suite counts before and after, NAMING EVERY SUITE WITH ITS COUNT.

## How to answer

Eight gates with measured output including the red run. Three labels kept apart: verified by my own
measurement · claimed but not measured · cannot tell from here.

The backend was restarted at 11:06 today and is current, so a live query is trustworthy — but say which
you used.

No broker orders. No writes to the live book. No scheduler or backend restart. No commits.
