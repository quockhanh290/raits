# Track 1 must publish its own breaker state, before the page can stop reading legacy's

This is a reporting change. It does not touch the engine, the strategy, any threshold, or anything
that decides whether a trade is taken. It makes the page able to say something it currently cannot.

Read this whole file. It corrects the previous round rather than reverting it.

## The regression this repairs, and why the failing tests are right

The legacy-removal round edited monitor/test_realtime_dom.py and did not run that suite in full — its
report lists three suites and that is not one of them, only focused nodes from it. Run in full: 8
failed, 80 passed. It was 88.

    test_sharpe_is_withheld_below_the_sample_floor
    test_sharpe_is_shown_once_the_sample_is_long_enough
    test_a_tripped_circuit_breaker_is_never_reported_as_nominal[HALTED]
    test_a_tripped_circuit_breaker_is_never_reported_as_nominal[SHUTDOWN]
    test_numbers_from_a_dead_source_are_not_shown_as_current
    test_a_stale_model_is_shown_as_debt_without_crying_wolf
    test_a_failed_refreeze_is_shown_as_debt_not_as_an_incident
    test_blocked_entries_are_visible_on_the_page

DO NOT rewrite any of these to pass. They are correct. One of them is the most important assertion on
the page.

I traced that one to the mechanism. With a tripped breaker in the payload the status rail reads
"systems nominal: feeds live, no open positions". The rail builds a list of what is wrong and says
nominal when the list is empty — its own comment states that design, only add a line when the answer
is no. So a page whose default is nominal cannot afford to lose a condition, and it lost one.

The breaker condition is fed by two expressions and BOTH are legacy: one reads the level out of a
helper whose argument is the legacy snapshot, the other reads the snapshot directly. And the Track 1
runtime payload carries no breaker key at all — measured, the key is absent; its safety block holds
jobs and paths, its gates block holds only whether orders are possible.

So Track 1 has never published a breaker level. The page always read legacy's. Remove legacy and the
page has no source, and the default is nominal.

## What to build

Track 1 publishes its own breaker state into its own runtime payload, and the page reads it from
there. Then these tests pass on the Track 1 path and the legacy source can go for good.

### Three states, and the third is the one everyone forgets

The breaker on this route is UNARMED today. It has no equity marks to work from — measured, the three
marks in the live book are zero and have been zero in every snapshot of that file for a month. The
reader already refuses to arm on them and says why, in a named reason that reaches the durable slot
row as breaker_armed and breaker_unarmed_reason.

So the payload and the page must carry three states, not two:

    armed and within limits    the ordinary day
    armed and tripped         a condition on the rail, naming the level
    NOT ARMED                 also a condition on the rail. This is the state we are in now

An unarmed brake is not a working brake. If the page treats "not armed" the same as "fine", it will
report systems nominal while the route has no risk brake at all, which is exactly today's situation.
Read the unarmed reason that already exists and say it; do not invent a level.

### Why this is urgent rather than tidy

The rail is not saying nominal today, but only by luck: a different condition is firing because the
broker-account reconcile record is stale, so the page shows that orders are not possible. The moment
that record is refreshed — which the operator is about to do — that condition clears and the rail
returns to systems nominal, with the breaker unarmed and its display source removed.

## The other seven failures

I have not traced them. Do not assume one root cause. One touches the model age, which DOES have a
Track 1 source, so it is probably a different shape from the breaker one.

For each, trace it to the mechanism and then decide which side is wrong — the test or the change. In
that order. If a test is genuinely stale, say what it asserted, what the Track 1 equivalent is, and
rewrite it against the Track 1 source rather than deleting it. If there is no Track 1 equivalent, that
is the same finding as the breaker one and the removal of that signal is held until there is.

## Gates

- G1. All 88 tests in that suite pass, on the Track 1 path, with no test deleted and none rewritten
  merely to agree with the new behaviour. If the count is not 88, say what it is and why.
- G2. The three states, each shown as a rendered rail: armed and within limits, armed and tripped,
  and not armed. The third must produce a visible condition, not silence.
- G3. The over-application guard. On an ordinary day with a working armed breaker, the rail reads
  exactly as it does today and gains nothing. Show it.
- G4. Falsifiability, per test you add or rewrite: name the one-line mutation it catches and show it
  RED under that mutation before green. For the unarmed state in particular, show that treating
  unarmed as fine turns your test red.
- G5. Suite counts before and after, measured by you, and NAME EVERY SUITE YOU RAN WITH ITS COUNT.
  The previous round reported focused nodes from a suite it had edited and the eight failures above
  are what that hid. A list of suites without counts is not a gate.
- G6. Nothing outside dashboard, monitor and the Track 1 runtime reader is touched. No threshold
  changes. No writer for the equity marks — a separate round will do that and it is blocked on an
  operator decision.

## Scope

The Track 1 runtime payload, the dashboard, and their tests. Do not add an equity writer. Do not touch
the day-open ordering. Do not touch the runner — another round is in its book loader.

No broker orders. No writes to the live book. No scheduler or backend restart. No commits.

## How to answer

Six gates with measured output including the red runs. Three labels kept apart: verified by my own
measurement · claimed but not measured · cannot tell from here.
