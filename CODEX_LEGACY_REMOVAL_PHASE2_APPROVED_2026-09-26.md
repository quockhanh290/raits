# Legacy off the dashboard — phase 2, approved, with the fork settled

Your survey is accepted. The counts were exact — 309 in scope, four buckets summing to 309 — and the
reasoning in the KEEP bucket held up when I sampled it. Two corrections before the work, one of them
important, and then the decision that collapses most of your DECIDE bucket.

## Correction 1 — the schedule item is VOID. Do not act on it.

You reported eleven legacy safety jobs still registered and computed the weekday schedule going from
93 slots to 82 if they are turned off. **Acting on that arithmetic would remove the stop-repair sweeps
and the max-hold exit that protect four live positions.**

There are two different elevens in this system and they coincide by accident.

Legacy had eleven safety sweeps. They came off the schedule on 2026-09-06, in a commit whose message
says exactly that and gives the reason: the book had held nothing since 2026-09-04. Measured today:
zero open positions on that route.

Track 1 has its own eleven safety jobs and every one is named for Track 1 — the max-hold exit, nine
stop repairs and the Sunday sweep. They are live. The Sunday sweep is the next scheduled job on this
machine.

What you counted was neither: a slot constant in the schedule reader with no route in its name,
generating every even hour at twenty past except two and fourteen. Ten plus Sunday is eleven. Its
membership gives it away — it contains 12:20, which Track 1 does not have, because Track 1 skips the
hours inside its own Stress window.

Nothing in the schedule changes. That change was made three weeks ago.

## Correction 2 — your REMOVE bucket cannot go before your DECIDE bucket

You put the backend serving of the legacy payload in REMOVE and left the page fallback mechanics in
DECIDE. But the page reads that payload by name, on purpose, so the legacy figure is captioned as
legacy instead of Track 1 measured equity being labelled the legacy runner's state.

Remove the producer while the consumer is undecided and the panel reads an absent value. That is the
failure family this whole week has been about. The decision below removes both, together.

## The decision

Everything that serves legacy goes. The operator's words: remove all of it, nothing is kept for
legacy's sake.

**Every fallback to a legacy value becomes an explicit absence.** With legacy holding nothing and no
longer trading, a fallback can only ever show a figure from a route that stopped. This page already has
the vocabulary — it spent this week learning to say not-recorded instead of zero and unknown instead of
missing. Use that vocabulary. No panel may go blank, show a dash with no explanation, or render a zero
where a value is simply absent.

So your DECIDE bucket mostly becomes REMOVE, and the producer goes in the same change as the consumer.

## The distinction that decides what "remove" means, and it is the crux

Your KEEP bucket is 144 references and your reasoning for it was right: those exist to stop Track 1
facts being filled with legacy values, or to label a source honestly.

Those are not kept FOR legacy. They are guards. When legacy is gone there is no competing source, so
the guard's LOGIC can collapse — but its EFFECT must not. A panel that today says "this is Track 1's
value, not the legacy runner's" becomes a panel that simply says what the value is; a panel that today
falls back must instead say the value is not recorded.

So this is a rewrite of 144 references, not a deletion of them. If your change deletes a guard and
leaves nothing in its place, you have reintroduced the exact substitution the guard existed to prevent.
Every one of those 144 must end as one of:

- the statement without the disclaimer, where a single source now makes the disclaimer meaningless, or
- an explicit absence, where the value could be missing.

Never as nothing.

## What stays, and when it goes

The legacy equity bookkeeping in the runner and in the legacy book stays. Do not touch it. It carries
the only working equity marks in this repository and it is the reference for a port a separate round is
designing right now. It comes out after that port lands, not before, and not by you in this round.

The schedule parity check stays for this round. It uses the legacy schedule as a yardstick for Track 1
correctness, so removing it deletes a check rather than a legacy feature. Report it as still standing.

## The staleness dimming

Its whole purpose was to stop live Track 1 numbers being dimmed as though they were month-old legacy
values. With legacy off the page it protects nothing. Retire the mechanism.

Its four gates must be REWRITTEN to assert the new surface — that nothing on the page is dimmed for a
reason that no longer exists, and that the values in that band render at full opacity because they are
Track 1's own. Do not delete them silently, and do not leave a test asserting the behaviour of
something that is gone. If you believe one of the four has no successor, say which and why rather than
removing it.

## Gates

- G1. Every one of the 309 in-scope references is accounted for in the final state: removed, rewritten,
  or explicitly still standing with the reason. A count at the end that adds up to 309.
- G2. No panel goes blank, dashes without explanation, or renders zero for an absent value. Show the
  rendered state of every panel you touched, before and after.
- G3. The over-application guard. A value that is genuinely present and genuinely Track 1's still
  renders exactly as it does today. Show three such panels unchanged.
- G4. Falsifiability, per test you add or rewrite: name the one-line mutation it catches and show it
  RED under that mutation before green.
- G5. Suite counts, before and after, measured by you. The backend suite is at 224 passing and zero
  failing; the paper DOM suite at 11; the dashboard truthfulness suite at 20 passing and zero failing.
  All three are fully green right now — there is no known red to work around.
- G6. Nothing outside dashboard and monitor is touched, and the ops module is not touched at all.
  Name every file you changed and every suite you ran.

## How to answer

The gates with measured output. Three labels kept apart: verified by my own measurement · claimed but
not measured · cannot tell from here.

If the rewrite of any of the 144 guards turns out to need a decision rather than a judgement, stop on
that one and ask. Stopping on the cache gate last round was the right call and this file exists partly
because of it.
