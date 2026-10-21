# Paper tab, phase 2 — approved, with the premise of phase 1 withdrawn

Your phase 1 report was right and mine was wrong. Read this before anything else, because the main
item in the previous file is already done and you must not go looking for it.

## What I withdraw

The previous file said: with zero persisted positions and an unreadable broker the tab renders
UNKNOWN, and it should render zero of zero. That was true when I wrote it down. It is not true on
this tree. You said so, and you were right.

I checked it at three layers rather than taking either of our word for it:

- Backend, on a built fixture with an empty position list: the protection item comes back MISSING
  with the evidence line reading zero of zero, not UNKNOWN.
- Front end: there is now one function deciding the protection read for all three panels, and it
  tests the position count for zero BEFORE it looks at whether the source status is UNKNOWN. An
  empty book returns a neutral tone and the words "the book is empty, so there is no position to
  protect". That is exactly the clause I said was missing, including the ordering.
- The paper DOM suite: eleven passed, run by me, one hundred and six seconds.

So the defect is closed and the fix is better than the one I asked for, because it put the decision
in one place instead of three.

## The one thing I still want from it

The fix handles four combinations and the suite pins three. The fourth — zero positions AND a
source status of UNKNOWN at the same time — is the one that decides the ordering inside that
function, and nothing currently fails if the two branches are swapped back.

Add that case. Zero positions with the source reporting UNKNOWN must still read as nothing to
protect, neutral, not as unknown. Then show it red under the mutation that swaps those two branches,
and green after. A gate that cannot be made to fail has measured nothing.

## The three backend failures — all approved, and here is why each

I checked all three myself rather than accepting the labels.

### 1. The durable-artifacts test expecting OBSERVED

Approved as a stale expectation. My reasoning is stronger than "Batch 2 changed it", so use this
one: the reader now carries an explicit statement of the rule — a persisted stop order id is context
only, not proof that an order is working. The fixture's only protection evidence IS a persisted stop
order id. So the old assertion encodes precisely the belief the batch was written to remove. The
status it expects, OBSERVED, is not even in that item's declared vocabulary any more.

I also checked the thing that would have made this a real defect rather than a stale test: whether
UNKNOWN swallows the recorded id and loses the difference between a position with a recorded stop
and one with nothing at all. It does not. Measured on both fixtures: the id travels beside the
status, in the protection row and again under the state-persistence item, while the status itself
stays UNKNOWN for both. Nothing was collapsed, so there is nothing to build here.

Required of the replacement assertion: assert the UNKNOWN status AND that the recorded id is still
visible beside it. If you only assert the status, a later change could quietly drop the context and
this test would not notice.

### 2. The C1 detail test expecting the old phrase

Approved as a stale expectation. The phrase moved from a cost vocabulary to a correspondence
vocabulary, which was a deliberate relabel and is the wording now in the panel. The status code kept
its old name and the stylesheet class kept its old name, which is why the sibling assertions on
those two still pass — only the human-facing sentence changed. Update the expected phrase to the one
the panel actually renders. Do not add the old phrase back to the source to satisfy the test.

### 3. The cache test whose stub went out of date

Approved to fix, and this is the answer to your question — it was the right question to stop on,
because it is a different class from the other two and my permission did not cover it.

What it is: the scan function gained a keyword argument naming the route, the test's counting stub
never did, so the call raises before the cache is ever exercised. The test is not asserting the wrong
thing; it is currently asserting nothing at all.

I checked whether it was hiding a real defect, because a stale stub is a good disguise for one. The
obvious candidate was a cache key that ignores the route, which would let a scan of one route return
another route's parsed result. It does not: the key already carries the route beside the epoch, the
resolved path, the size and the modification time. So the production side is correct and only the
stub is behind.

Required, and this is the part that matters more than the fix: after the signature is repaired, show
the test going RED when the memoisation is removed. A caching test that passes with the cache deleted
is worse than no test, and this one has been in that state for some unknown number of runs. If it
cannot be made to fail that way, say so and stop — that would mean it is not testing the cache at
all and needs to be rewritten rather than repaired.

## One item deliberately REMOVED from this round

An earlier draft asked you to also fix a weekday-prefix assertion in the dashboard truthfulness
suite. It has been pulled out and is not part of this round. Do not touch that file.

The reason is worth knowing, because it is the kind of overlap that is invisible until it costs
something. That suite imports one of the two modules a separate batch is changing right now, so it
is a member of that batch's frozen regression set — and the failing test in question is the only
member of that set outside the scratch directory. If you fixed it mid-flight, the other batch's
after-run would come back one failure short of its baseline, and its instructions tell it to stop and
report a difference. That stop would be a false alarm costing a forty-minute run.

It will be sent as its own round once the other batch has landed.

## Gates

Measured output for each. Prose is not a gate.

- G1. The four combinations of the protection read, each rendered and shown: no positions and no
  broker, no positions with a broker, positions without a readable broker, positions with one.
- G2. The new fourth-combination test red under the branch swap, green after. Show both runs.
- G3. The cache test red with the memoisation removed, green with it. Show both runs.
- G4. Both suite counts, before and after, raw. The backend suite is at 222 passing and 3 failing
  right now — that is your before, measured by you in phase 1 and matching mine. It must end at 225
  passing, 0 failing. The paper DOM suite is at 11 and must stay at 11.
- G5. Over-application: a tab WITH positions and an unreadable broker still reads unknown with its
  reason, unchanged. Show it.
- G6. No file outside dashboard and monitor is touched. A separate batch is running on the live slot
  and the signal layer at the same time.
- G7. Neither of these is touched or run, at all: the dashboard truthfulness suite, and any suite
  under global_index or scratch. They belong to the other batch's regression set and running them
  concurrently also puts two browser suites on the machine at once, which this repository has been
  bitten by before. The two suites you DO run — the backend suite and the paper DOM suite — are not
  in that set; I checked. Name in your report every suite you ran, so the overlap is auditable rather
  than assumed.

## Scope

Dashboard and monitor only, minus the two exclusions in G7. No broker orders. No scheduler or backend
restart. No commits.

Three labels, kept apart: verified by my own measurement · claimed but not measured · cannot tell
from here. You kept them apart in phase 1 and it is why this file exists in this shape.
