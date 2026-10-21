# The paper track must be readable at a glance — say WHICH KIND of not-yet

The paper tab currently shows twenty-four rows and an operator cannot tell, without reading every
evidence string, whether the track is early or broken. That is the whole task. It is a presentation
change: do not invent evidence, do not compute a number that was not measured, do not turn an absence
into a figure.

## Before you measure anything, read this

The running backend process started 2026-09-25 at 06:01 and the readers it serves were last modified
on the 26th and 27th. Python loads modules at process start, so **the live dashboard is serving code
from before two days of fixes**. I was briefly misled by this myself.

So: measure through the CURRENT code, and if you query the running backend, state that its process may
predate the code you are reading. If the operator has restarted it by the time you run, say so.

## The seven kinds that currently look alike

Measured today. These are real rows with real states, and they are seven different situations wearing
one appearance:

    1  not yet, sample building        fill quality 3 of 100 records; paper duration 2 days
    2  no Track 1 source exists at all roll slippage, manual intervention
    3  source exists, not consumed     four rows want a live-state file; Track 1 publishes its runtime
                                       on its own endpoint and this reader does not read it yet
    4  happened, and was fixed         three broker/file mismatch episodes, 2026-09-24 16:20 and 18:20
                                       ET and 2026-09-25 10:20 ET — the last is the morning the book
                                       was erased, which is fixed. None on the 26th or 27th
    5  real signal, sample too small   C1 open slippage -7.67 ticks against a 3 tick limit, on N=3
                                       where the gate wants 20 per instrument
    6  faulting right now              nothing, once the backend is current
    7  known debt, scheduled decision  model age HARD stale, waiting on the annual re-freeze gate

An operator scanning that page needs to separate 1 from 6 in one second. Today they cannot.

## What to build

**A second axis, not more statuses.** The existing statuses answer "is this green". Add the axis that
answers "why is it not green", with the kinds above as its values, rendered distinctly enough that a
glance separates early from broken. Name the kinds from the operator's question, not from the code's
internals.

Two rules the axis must obey:

- Kind 4 must not read as a current fault. A recovered incident stays in the record — that is the truth
  about that day — but an alarm that never turns off is an alarm people learn to ignore. Distinguish
  episodes that have been superseded by a later clean run from ones that have not. Note that today
  there is no clean run to supersede them because nothing has run since Friday, so the honest state is
  "awaiting the next run", which is itself a kind and not a fault.
- Kind 5 must not be softened into kind 1. A number that is 2.5 times its limit is a signal even at
  N=3. Show both halves: the measurement and the distance to the sample gate. Do not let the sample
  caveat hide the figure, and do not let the figure read as a verdict.

**A headline that answers where the track is, in one line.** Days, fills, the single worst measurement
against its limit, the distance to its sample gate, and whether anything is faulting now. One line, no
scrolling, and it must be derivable entirely from rows already on the page — if you need a number that
is not there, the answer is to say it is not there.

**Nothing may go blank.** Every kind renders as words. A dash with no explanation is the thing this
page spent a week learning not to do.

## What NOT to do

Do not add or change any gate threshold. Do not wire the four rows in kind 3 — that is separate work
and it is a decision about which source feeds them. Do not build sources for kind 2. Do not mark any
incident resolved by hand; resolution must be derived from a later clean observation or not claimed.

Do not reduce the row count by hiding rows. Twenty-four rows that are legible beat six rows that are
selective.

## Gates

- G1. All seven kinds rendered, each shown, each visually distinguishable from the others. Seven
  outputs, not a description of seven.
- G2. Kind 1 and kind 6 side by side, and a one-line statement of how a reader tells them apart in one
  second. If you cannot state that, the rendering is not done.
- G3. The C1 row shows the measurement AND the sample distance. Show the rendered row. A version that
  shows only one of the two fails.
- G4. The three historical episodes render as history awaiting a clean run, not as a live fault. And
  the control: a mismatch that has NOT been superseded must still render as a fault. Show both.
- G5. The headline, rendered, on today's real data. Then rendered again on a fabricated day where
  something IS faulting, to prove it changes.
- G6. Over-application: a row that is genuinely green today still renders green and gains no new
  caveat. Show three.
- G7. Falsifiability, per test: the one-line mutation it catches, shown RED before green. For the axis
  specifically, show that collapsing two kinds into one turns a test red.
- G8. Suite counts before and after, NAMING EVERY SUITE WITH ITS COUNT. The paper DOM suite is at 11
  and the backend suite at 224 on the current code.

## Scope

The paper evidence reader and the paper tab, plus their tests. Do not touch the realtime page, the
signal layer, the runner, or the scheduler.

No broker orders. No writes to the live book. No scheduler or backend restart — say if one is needed
and leave it to the operator. No commits.

## How to answer

Eight gates with measured output including the red run. Three labels kept apart: verified by my own
measurement · claimed but not measured · cannot tell from here.

If you find an eighth kind I have not listed, that is a finding — report it rather than folding it into
the nearest one.
