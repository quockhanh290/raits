# The band's two remaining holes, both found by measuring what it hides

Your band is accepted. I re-ran the six suites myself — 63 passed — and the upper edge is right: anchored
to the largest ending equity this route's own replays have produced, with a 54 percent margin against the
recorded account balance instead of 0.70. The second identity input was the right call and your own note
about why a single magnitude band cannot do the job is the most useful sentence in that report.

Two residuals. Neither is a mistake in what you built; both are consequences of it that only show up when
you ask what the rule hides rather than what it catches.

## Residual 1 — the lower edge hides the drawdowns that matter most

The comment justifies 42,000 as the mark that proves a persisted hard-drawdown equity still arms the
breaker and is HALTED rather than hidden as an implausible placeholder. That reasoning is right and it is
the reason this is worth fixing, because the edge does not carry it far enough.

Measured, all three marks set to each value, against the 50,000 base:

    46,000   -8%   armed
    42,000  -16%   armed        <- the case the edge was set for
    40,000  -20%   UNARMED      <- the drawdown is hidden
    35,000  -30%   UNARMED      <- hidden
    30,000  -40%   UNARMED      <- hidden

So beyond sixteen percent, a genuine deep drawdown is reported as an unarmed brake. That is the exact
failure the comment says it is avoiding, one notch deeper, and it lands precisely where an operator most
needs the state to be visible. The halt stops new entries; it does not close positions, so equity CAN keep
falling past sixteen percent and the record should say so.

And the case the edge exists to catch does not need it that high. A profit-and-loss delta of 408.25 is
0.8 percent of base. Measured: a floor at 5,000 or at 10,000 catches 408.25 and admits a forty percent
drawdown.

So the floor should be the boundary between NOT EQUITY SHAPED and MERELY LOW, not the boundary between
acceptable and unacceptable risk. Choose it from that question, justify it, and state what drawdown it
still admits.

While you are there: the upper edge is anchored to a measured maximum. The floor should be anchored the
same way if the evidence exists. The reproduction windows print an ending equity but I could find no
saved settlement stream to reconstruct their equity PATH, so the minimum each window passed through is
unknown to me. The floor window records two breaker halts, so it went down somewhere. If you can recover
those minima, anchor the floor to them and say so; if you cannot, say that too and anchor it to the
shape argument instead.

## Residual 2 — the identity rule depends on a field nothing writes

The identity rule is what catches broker money whose magnitude sits inside the sleeve's range, and it is
the right mechanism. Measured:

    80,000 with broker_equity recorded as 80,000   refused, named as broker context
    80,000 with no broker_equity field at all      ARMED

The live book has no broker_equity field and no component writes one. So the second half of the guard is
currently inert, and the only thing standing between an account-scale mark and an armed breaker is the
magnitude band — which today has a comfortable margin only because the account sits at 251,752. That
account held 1,000,480 in July and 996,730 in August. If it continues down into the 42,000 to 114,903
range, magnitude stops distinguishing and the inert half is the only half that would.

This changes what the broker mark is for. It was described as reconciliation context. It is now a
PROTECTIVE DEPENDENCY, and the band's own safety statement should say so, so that nobody later removes it
as decoration.

What I want from you here is small: make the dependency explicit rather than implicit. When the marks sit
inside the band and no broker mark is recorded, the state is not simply armed — it is armed without the
identity check having been possible. Decide whether that deserves its own wording in the reason, and
justify whichever way you go. Do not add a writer for the broker mark; that belongs to the writer round.

## Gates

- G1. The new floor, with the drawdown it admits stated as a percentage, and the profit-and-loss delta
  case still refused. Show the sweep.
- G2. Whatever you choose for the floor, show that a deep drawdown now ARMS and is HALTED rather than
  reported unarmed. That is the whole point: halted and visible, not hidden.
- G3. The upper edge and the four existing shapes are unchanged. Show all four.
- G4. The operator's seed of 50,000 still passes and arms.
- G5. The live book is still refused with the two-part reason, and the dashboard still agrees. The
  agreement suite stays green.
- G6. Residual 2, whichever way you decide it: show the reason string for a mark inside the band with no
  broker mark recorded, and say in one line why that wording is right.
- G7. Falsifiability, per test: the one-line mutation it catches, shown RED before green.
- G8. Regression, before and after, NAMING EVERY SUITE WITH ITS COUNT.

## Scope

The band, its reason strings, and their tests. Do not add a writer. Do not change the three thresholds.
Do not touch the day boundary, the dashboard's rendering, or the runner.

No broker orders. No writes to the live book. No scheduler or backend restart. No commits.

## How to answer

Eight gates with measured output. Three labels kept apart: verified by my own measurement · claimed but
not measured · cannot tell from here.

If you conclude the floor should not exist at all for the equity mark — that a low equity is always a real
state and only a non-equity-shaped value should be refused — make that argument. It may be the right
answer and it would be a cleaner rule than any number.
