# The plausibility band protects us by 0.70 percent — give it a real edge

Small change, safety constant, live decision path. Full gates.

## The measurement that opened this

The band you built refuses a mark outside account divided by five to account times five, which is
10,000 to 250,000 against a design base of 50,000. It exists to stop a broker-account balance being
written where a sleeve equity belongs, because that mistake has been made once already and the retired
route carries a named guard against it.

The current recorded broker account balance is 251,752.25 — measured, from the newest baseline record,
status PASS, taken 2026-09-25 at 18:05 UTC.

So the band refuses that figure by 1,752.25 dollars. **0.70 percent.**

It works today by luck. That account has held 1,000,480 in July and 996,730 in August; it is 251,752
now. If it sat at 240,000 the broker figure would pass the band, the breaker would arm on
account-scale money, and its daily arm would be unreachable again — silently, because everything would
look armed and plausible.

A guard whose margin is under one percent, against a quantity that has moved by a factor of four in
three months, is not a guard.

## What is wrong with the shape, not just the number

The edges are a symmetric multiple of the base. That looks principled and it is not, for two reasons.

**The two directions have opposite consequences.** A mark far too large makes the breaker halt
spuriously, which is visible and annoying. A mark far too small makes the daily arm unreachable and
admits every entry, silently. So the tolerances should NOT be symmetric — the loose edge is currently on
the dangerous side.

**And the upper edge is anchored to the wrong thing.** It is derived from the base, so whether it
excludes the account balance depends on where the account happens to sit. That is a coincidence, not a
property.

## What to build

Edges derived from what a sleeve equity can legitimately BE, with each bound justified from evidence in
this repository rather than chosen for symmetry.

The evidence exists. The recorded reproductions print an ending equity per window — the floor window
ends at 114,902.91 on a 50,000 base, which is the largest legitimate value this route's own record has
ever produced. The vault windows end at 63,236.11 and 58,259.85. Those are measured anchors for the
upper edge. Use them; do not invent a multiple.

For the lower edge, ask what the sizing can actually lose. The four open positions carry 3,817.28 of
total risk against a 50,000 base. Work out what a legitimate floor is from that and from the recorded
drawdowns, and state the reasoning.

One option worth evaluating rather than assuming: refuse any value that sits closer to the last recorded
broker mark than to the design base. That makes the rule about identity rather than magnitude, which is
what the band is actually for. It couples the check to a record that can go stale, so weigh that and say
which you chose and why.

Whatever you choose, the report must answer: if the account balance moves to 240,000, or to 80,000, does
the band still refuse it? Show the arithmetic, not an assertion.

## What must not change

The three thresholds. Ten, fifteen and four, exactly as they are.

The two distinct refusal reasons — no measured marks at all, versus a mark present and out of band.
Those were one sentence before this week and they must stay two.

The classification of the four shapes already tested: a plausible mark arms, a broker balance does not, a
profit-and-loss delta does not, zero does not.

And the seed the operator is about to write: the design base of 50,000 must still pass. If your band
refuses it, you have broken the thing this is protecting.

## Gates

- G1. The four existing shapes classify exactly as they do today. Show all four.
- G2. The current recorded broker figure of 251,752.25 is refused, and state the margin as a percentage.
  It must be a margin you would defend, not 0.70 percent.
- G3. Stability against the account moving. Show the verdict for a broker mark at 240,000 and at 80,000.
  Both must be refused. If your rule cannot refuse 80,000 while still accepting an equity of 114,902,
  say so and explain what the tension is rather than picking a side quietly.
- G4. The operator's seed value passes and arms the breaker, with the three marks read back.
- G5. The live book as it stands is still refused with the same two-part reason, and the dashboard still
  agrees with the signal layer on it. The agreement test must stay green.
- G6. Falsifiability, per test: name the one-line mutation it catches and show it RED under that mutation
  before green. For the new edges specifically, show that widening them back to a symmetric multiple of
  five turns your account-figure test red.
- G7. Regression, measured by you before and after, and NAME EVERY SUITE WITH ITS COUNT.

## Scope

The band and its tests. Nothing else. Do not touch the writer, the day boundary, the dashboard's
rendering, or the runner.

No broker orders. No writes to the live book. No scheduler or backend restart. No commits.

## How to answer

Seven gates with measured output including the red run, and the G3 arithmetic in full. Three labels kept
apart: verified by my own measurement · claimed but not measured · cannot tell from here.

If the honest answer is that no single band can both exclude account-scale money and admit a doubled
sleeve equity, say that plainly — it would mean the check needs a second input rather than a wider
window, and that is a finding worth more than a chosen number.
