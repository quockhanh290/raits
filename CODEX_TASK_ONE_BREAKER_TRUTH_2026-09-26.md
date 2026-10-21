# The breaker publisher says ARMED while the route says it is not — one truth, one place

Your round fixed the eight failures and the suite is 90 green. Keep that. What it published is wrong,
and the way it is wrong is the same shape the whole week was spent removing.

## The measurement

Same file, same instant, two readers:

    the signal layer   armed=False, reason: out-of-band equity=0.0, peak_equity=0.0,
                       day_start_equity=0.0; expected 10000.0 <= mark <= 250000.0
                       and the book's breaker is None
    the dashboard      armed=True, status=ARMED, level=OK, allow_new_entries=True

Before your change the page said systems nominal because it had NO breaker source. Now it makes a
positive claim that the risk brake is armed and inside its limits. An operator reading that believes
they are protected. That is worse than the absence it replaced.

## Why it happens — traced, so you do not have to rediscover it

Two links, both measured.

**The honest branch is unreachable.** It fires on the arming flag read from the newest durable slot row.
Those fields were added this morning and no slot has run since, because it is Saturday. That row comes
back as nothing. So the branch that would say UNARMED cannot fire, and the branch designed to be the
truthful one is the least reachable one in the function.

**Then zero passes as a mark.** The next branch asks whether equity and peak are not None — and zero is
not None. So it builds a breaker with a peak of zero and a day start of zero, asks its status at an
equity of zero, and gets level OK with entries allowed, because a zero drawdown from a zero peak is
zero.

## What this actually is, and therefore what the fix is

It is a SECOND copy of the reading logic, without the band. The plausibility band that refuses zeros
lives in the signal layer. Your reader answers the same question and does not have it.

That is the defect family this week was spent collapsing: three panels answering the empty book three
ways, two readers of the same book disagreeing about field names, a comment asserting an ordering
another file contradicts. Each was fixed by making ONE place answer the question. This created a new
second place.

So the fix is not a new condition bolted on. There must be one function that decides whether the route
breaker is armed, and both the slot path and the dashboard must call it. Where that function lives is
yours to choose and to justify; that it is one function is not.

Requirements that follow from it:

- Zero is not a mark. The band already refuses it. The dashboard must arrive at the same refusal by
  using the same rule, not by growing its own zero check.
- The unarmed answer must be reachable WITHOUT a durable slot row. Any day on which no slot has yet run
  — every weekend, every morning before the first slot, every restart — must still report the truth
  from the book alone. A truthful branch that depends on recent activity is the wrong way round: the
  quiet days are exactly when nobody is watching.
- Keep the three states. Armed and within limits, armed and tripped, not armed. Do not let unarmed
  render as nominal, and do not let it render as armed.

## The gate that would have caught this, and none of your 90 is it

Not another assertion about the payload. An assertion that THE TWO READERS AGREE.

Ask the signal layer whether it would arm on a given book. Ask the dashboard what it reports for the
same book. Require them to match. Run it over the four shapes the band already distinguishes — a
plausible mark, a broker balance, a P&L delta, and zero — and over the real book on disk.

That test cannot be satisfied by two divergent copies, which is why it is the one to write. Ninety tests
passed without it.

## Gates

- G1. The two-reader agreement test above, over all four shapes plus the live book. Show the pairs.
- G2. On the live book as it stands right now, the dashboard reports not-armed and carries the same
  reason the signal layer gives. Show the payload.
- G3. The unarmed answer with NO durable slot row present at all. That is today's real condition and it
  must not depend on one.
- G4. The suite stays at 90 or grows, with nothing deleted and nothing rewritten merely to agree with
  new behaviour. If a test you added this round asserted ARMED for the live book, it was asserting the
  defect — say which and what it says now.
- G5. Falsifiability: show the agreement test RED when the dashboard keeps its own copy of the rule, and
  green after. That is the mutation that matters here.
- G6. Name every suite you ran with its count. Not a list of suites — a list of counts.

## Scope

The Track 1 runtime reader, the dashboard, and wherever the shared arming decision ends up living. If
that means the signal layer gains an importable function, that is acceptable; changing what it DECIDES
is not. Do not add an equity writer. Do not change a threshold. Do not touch the runner.

No broker orders. No writes to the live book. No scheduler or backend restart. No commits.

## How to answer

Six gates with measured output including the red run. Three labels kept apart: verified by my own
measurement · claimed but not measured · cannot tell from here.
