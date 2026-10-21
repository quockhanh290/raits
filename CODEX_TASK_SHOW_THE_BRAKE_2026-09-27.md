# Nowhere on the page says the brake is armed — and silence cannot mean healthy

Small task, one page, and the reason it matters is measured below rather than asserted.

## The measurement

I grepped the realtime page markup for any element showing the circuit breaker's state. There is
none. The breaker appears in exactly one place in the code — the status rail — and the rail only adds
a line when something is wrong:

    const track1Breaker = state.track1?.breaker || {};
    const stripBreakerUnarmed = track1Breaker.armed === false || level === 'UNARMED';

So three situations currently produce the same blank:

    armed and inside its limits      nothing printed, because nothing is wrong
    no breaker block in the payload  armed is undefined, not false, so nothing is printed
    (and only this one speaks)       armed === false prints "risk breaker not armed"

The strict comparison against false is CORRECT and must stay — treating an absent field as false is
how a missing source becomes a confident claim. But the consequence is that a healthy brake and a
silent publisher look identical.

That is the same blindness we removed yesterday, one layer narrower. Yesterday a TRIPPED breaker read
"systems nominal" because the page had no source for it. The fix gave Track 1 its own publisher. If
that publisher ever breaks, the page goes quiet again and quiet still reads as fine.

A rail that only speaks on problems cannot distinguish OK from NOT REPORTED. So something has to say
it affirmatively.

## What to build

One place on the page that states the brake's condition, including when that condition is good.

Five states, and the fifth is the one this exists for:

    armed, inside limits       say so, with how much room is left (see below)
    armed, warning level       say so, naming the level
    armed, halted              say so, naming the level and that entries are refused
    not armed                  say so, carrying the reason the payload already provides
    NO BREAKER BLOCK AT ALL    say that the brake's state is NOT BEING REPORTED. This must not
                               resemble any of the four above, and above all not the first

For the good state, "OK" alone wastes the row. The payload carries the daily loss and the drawdown as
fractions, and the thresholds are fixed and known — four percent daily, ten percent warning, fifteen
percent halt. So the row can say how far the current reading sits from the limit that would bite
first. Derive it; do not hardcode a figure, and if a needed field is absent, say it is absent rather
than substituting a zero.

The payload also names the file it read the marks from. An operator asking "armed against what" should
not have to guess.

## What not to touch

The rail's design. It prints only problems and that is deliberate — this is an ADDITION beside it, not
a change to it. Do not make the rail announce good news.

The strict comparison against false. Absent is not false and must stay distinguishable.

No thresholds. No writer. Nothing in the signal layer, the runner, the paper tab or the scheduler. A
separate round is working on the paper tab.

## Gates

- G1. All five states rendered, each shown. Five outputs, not a description of five.
- G2. The control that this whole task exists for: with NO breaker block in the payload, the rendering
  must differ from the armed-and-inside-limits rendering. Show the two side by side. If they are
  distinguishable only by a missing number rather than by words, that is not enough.
- G3. The good state shows distance to the limit that would bite first, derived from the payload's own
  figures. Show the row on the live payload, which today reads armed with the marks at fifty thousand.
- G4. An absent field inside a present block renders as absent, not as zero.
- G5. Falsifiability: show the G2 test RED when the absent-block case is allowed to fall through to the
  healthy rendering. That is the mutation that matters.
- G6. Over-application: the rail is unchanged. Show that on a day with a tripped breaker the rail still
  prints its line, and that on a clean day it still prints nothing about the breaker.
- G7. Suite counts before and after, NAMING EVERY SUITE WITH ITS COUNT. The realtime DOM suite is at 90
  and the truthfulness suite at 20 on current code.

## A warning about measuring

The running backend process started 2026-09-25 and the readers it serves were modified on the 26th and
27th, so a live query may answer from code that predates the publisher. Measure through the current
code. If the operator has restarted the backend by the time you run, say so and note that your live
figures are then trustworthy.

No broker orders. No writes to the live book. No scheduler or backend restart — say if one is needed
and leave it to the operator. No commits.

## How to answer

Seven gates with measured output including the red run. Three labels kept apart: verified by my own
measurement · claimed but not measured · cannot tell from here.
