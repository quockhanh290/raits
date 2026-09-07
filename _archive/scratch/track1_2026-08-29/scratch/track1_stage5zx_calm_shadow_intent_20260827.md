# Stage 5ZX — Calm decides at half past nine and writes it down; nothing sends

**2026-08-27, ET 02:00–03:10.** Implementation of the 5ZW plan. **No SEND, none built, none
authorised** · no orders · no confirmation file · no `--allow-orders` · no `IBKRBroker` · no
`placeOrder` · nothing written to `track1_runtime/orders/` · **nothing restarted** · no runtime
production file edited by hand.

---

## Verdict

| | |
|---|---|
| the two phases | **BUILT AND WIRED** — driven end to end through the slot the scheduler calls |
| Calm evidence | can now count the **DECISION**; never an execution |
| orders possible | **false** — measured before and after, unchanged |
| blocking gates | **B1** and **PAPER_SHADOW_EVIDENCE** — unchanged, neither created nor released |
| strategy identity | **UNCHANGED** — proven on 319 sessions by identical digest |
| paper readiness | **NOT_READY** |

---

## 1. What the measurement changed about the plan

The plan said: a decide job at half past nine, an observe job just after ten. Building it turned
up two facts that would have made a faithful implementation of that plan produce evidence that
looked right and said nothing.

**The decide half cannot ask the route for candidates.** The Calm detector returns nothing at
all when today has no ten o'clock bar — and at half past nine, that is every day that has ever
existed. A decide slot calling the ordinary candidate path would receive an empty list every
morning and record, in perfectly good faith, *Calm did not set up today*. Five clean weeks of
that would satisfy a counter and mean nothing.

So the rule was split where it actually divides. Everything Calm decides is fixed once today's
half-past-nine bar has closed: the prior session closed yesterday, and the opening price is the
last thing the rule reads. The only thing the ten o'clock bar adds is the price — and, through
it, the stop level. That split now exists as one shared function that the full detector is built
**on**, not beside. Two copies of one rule is a rule that will drift, and this one would drift
silently: an intent recorded from a stale copy still looks exactly like evidence.

**Neither half can go through the candidate path at all.** The route asks "which sleeve may
decide at this instant" before anything else, and Calm's window is the single instant ten
o'clock. Half past nine is outside it; two minutes past ten is outside it. The observe half was
written to call it anyway, and the first run refused with *no sleeve at this instant* — the
right answer to the wrong question. The observe half is not looking for a setup. The setup was
found half an hour earlier and written down; all that is left is to read the price the decision
named.

**And the first refusal row lied about who refused.** It carried "the gate refused" when the
gate had passed and the refusal came from the candidate source. Whoever read that row would have
gone to inspect a gate that was working. The rows now carry the slot's own vocabulary.

None of the three was visible from reading. All three came from running it.

## 2. Proof the strategy did not move

The shared function was extracted from live code, so the burden is to show the detector answers
exactly as it did.

```text
319 sessions examined      84 set up      235 did not
digest before   a573a9e32e326b937a8350addff31b94ab74f6f31c7b489773bc9987f09203f5
digest after    a573a9e32e326b937a8350addff31b94ab74f6f31c7b489773bc9987f09203f5
```

Identical — day, direction, signal time, entry time, entry price, prior session, and all four
features, on every one of the 319. The new pre-entry half independently agrees on exactly the
same 84 days. The parameters are untouched: the entry is still the ten o'clock open, the stop is
still an ATR-and-a-half below it.

The comparison is clock-independent by construction — the same frame goes through both runs — so
it holds regardless of which clock the frame is on. That matters, because the frame used to pick
the digest window is the raw parquet, which is UTC; the end-to-end run below deliberately uses
the route's own loader instead, which converts to New York. Measuring the two halves of this
stage on the same clock would have been the easier mistake and the wrong one.

## 3. The scheduler, measured rather than counted

```text
                        slots   track1-only total   legacy+track1 total
before (1 Calm slot)      70            101                 130
after  (2 Calm phases)    71            102                 131
```

Built from real scheduler construction in one process, with the old slot table reconstructed
in memory for the "before" row. 102 is the number the plan predicted; it is reported here
because it was measured, not because it was expected.

```text
TRACK1_CALM_DECIDE_0932    09:32   phase DECIDE    decides from bars closed by 09:30
TRACK1_CALM_OBSERVE_1002   10:02   phase OBSERVE   records the 10:00 OPEN and the stop level
```

Neither sits on the entry instant, and that is the fix rather than a side effect: the slot that
did sit there needed a five-minute bar that would not close until four minutes after its own
deadline, so it refused every morning of its life.

The phase travels in the argv of a slot that **has** one. The first draft passed it for every
slot including the three unsplit sleeves, on the reasoning that the command line should say
which half is running — and the regression caught that the reasoning does not extend to a sleeve
with no halves. Printing an empty phase for Stress, the swing sleeve and the Nikkei changed the
command line of three sleeves this stage has no business touching. Narrowed; their argv is now
byte-identical, which was measured rather than assumed.

**A typo refuses.** A phase the sleeve does not declare returns no requirement at all rather
than falling back to the sleeve's own. Falling back is the tempting choice: it would gate the
decide half with the entry-half rule, pass it at the wrong instant, and leave a record
indistinguishable from a slot that ran correctly.

## 4. The two phases, run end to end

Driven through the function the scheduler calls, on a real session, with the route's own loader:

```text
DECIDE   @09:32   decided   RECORDED  ok   MES   ref —          stop —
OBSERVE  @10:02   decided   RECORDED  ok   MES   ref 7680.75    stop 7577.919642857143
```

The decide row carries the setup, the instrument, the direction, the size, the stop **rule** and
its inputs — and no price of any kind. The observe row adds the two things only it can know. The
reference price equals the frame's real ten o'clock open to the cent; the stop is exactly an
ATR-and-a-half below it, cross-checked by arithmetic rather than trusted:
`7680.75 − 7577.9196 = 102.83 = 1.5 × 68.55`.

The day classifies as **decision judgeable**, and the words that travel with that label say what
it does not mean: *this says the route WOULD have acted; it says nothing about whether an order
would have been accepted or where it would have filled.*

**What the run wrote, and nothing else:**

```text
global_index/track1_runtime/shadow_intent/shadow_intent_20260821.jsonl
global_index/track1_runtime/signals/track1_signals_20260821.jsonl
ledger/window_coverage_20260827.jsonl
```

No orders directory. No trade log. No book. No checkpoint. Asserted, not observed in passing.

## 5. Why the intent is not in the order journal

Carried forward from 5ZW and now enforced by a test that mutates the stream's path and demands
the assertion go red. Four readers treat the mere existence of that directory as proof this route
has acted — the book repair refuses to run, the call-site guard trips, the reporting layer flips
off "not produced", and the runbook says stop and investigate. A rehearsal written there would
make all four describe a route that traded on a day it sent nothing, and would block its own book
repair.

## 6. How the gate counts Calm now

The readiness report gained a line per qualifying day, in words rather than codes:

```text
  calm decision evidence   :
      2026-08-24  missing
      2026-08-25  missing
      2026-08-26  missing
      counts the DECISION only — never acceptance, fill or slippage
```

All three say **missing** because all three predate the stream, which is the honest answer and
not a failure of the reader. A day with no rows does not count; a day where the rule looked and
found nothing **does**, because the route was watching and correctly recorded that there was
nothing to do. Those two are the same silence to a counter, and telling them apart is the whole
reason the stream exists.

The gate carries `proves: decision_only` and `does_not_prove: acceptance_fill_or_slippage` in
every record it writes, and raises rather than returns if the classifier ever hands it an
execution label. A count read alone becomes a claim in the mind of whoever reads it next.

## 7. The dashboard

One row beside the existing ones, three states like all of them, currently reading *absent — the
two Calm phases have not run*. It says that rather than showing nothing, because a panel that
shows nothing shows the same nothing for a route that is watching and a route that cannot.

## 8. Two findings recorded, not fixed

**The signal diagnostics have never carried a parameter identity.** The reader guards on the
parameter module having a hash function; that module has never had one. The real function lives
elsewhere and takes a full configuration rather than a sleeve name — and refuses a partial one
outright, which is good design that this caller never reaches. So every diagnostics row written
since the field existed has carried an empty identity, and a later reader comparing two rows
would find them equal because both are blank. Fixing it changes what diagnostics rows contain and
belongs to whoever owns that channel.

**The order journal's path is still defined in three modules independently** (carried from 5ZW,
unchanged). A test asserts they still agree.

## 8b. What the regression caught, and what it cost

The full scratch corpus: **109 failed, 2460 passed**. Re-running the same failures with the
pre-stage slot table restored through a probe fixture turned **45 of them green** — so 45 are
caused by the slot split, and the rest were already red. That is a measurement rather than a
reading of the names, and it was worth taking: the split was suspected of causing all of them.

The comparison also turned up something separate. The same set of tests, run twice, produced
109 failures and then 98. **Eleven tests pass or fail depending on what ran before them.** That
is a property of the corpus, not of this stage, and it means any failure count from it carries
about ten per cent of noise. Worth knowing before anyone treats such a number as a threshold.

Four failures were repaired because they were **not** stale pins:

- **Two causal-path assertions** (from the two previous stages) counted how many times the
  detector takes an opening price and how many times it evaluates the rule — inside a single
  function. The causal path is now two functions, so counting inside one of them reports one
  read and calls it a violation. The property never was "this function calls it twice"; it was
  "the causal path takes exactly the two opens and evaluates the rule exactly once". Widened to
  both halves **and per half** — because a total of two split two-and-zero would pass a
  total-only count while meaning the pre-entry half had reached into the entry bar, which is the
  one thing it exists not to do. Three mutations confirm all three assertions still go red,
  including that one.
- **A stale test stub** whose signature predates the requirement argument.
- **The paper-readiness fixtures**, which build a clean shadow period. A clean period now
  includes Calm decision evidence, so the fixture had to grow it — and the fact that those tests
  went red before it did is the natural mutation proof that the new check can actually refuse.
  The two that matter most are the ones proving the gate CAN open; leaving those red would have
  meant nobody could tell whether it was still openable at all.

The remaining slot-shape failures are count and identifier pins — `assert len(slots) == 70`,
`assert total == 101`, tests driving `TRACK1_CALM_1000` by name. They are the roster-pin
anti-pattern already on this project's record, and the ones that drive the old slot need more
than a name swap: they exercise ten-o'clock semantics that no longer exist. **They are left red
and listed**, because repairing them means deciding per test what the new Calm timing should
mean, and doing that quietly inside this stage is how an assertion gets weakened without anyone
choosing to weaken it.

## 9. Tests

**20**, in `scratch/test_track1_stage5zx_calm_shadow_intent_20260827.py` — fifteen cases and five
mutations, one per named collapse: the intent written to the orders directory, a stop price in
the decide row, an observe-only day counted, a decide-only day counted, and the decision label
turned into an execution claim. Each mutation performs the collapse and asserts its test goes
red.

Three failed while being written, and two of the three are worth keeping in the record. One
counted a function's use of a call by searching its **source text** — and the function's own
docstring says it makes that call once, so the test read the sentence and reported two. That is
the same trap that broke a substring assertion two stages ago when a new comment quoted an old
label; the reader now strips docstrings before counting. The other found that the decide-row
builder cannot even be **asked** for a price — the argument does not exist — so the refusal it
was aiming at lives one layer down. The test now proves both doors, because proving only the
missing argument would be proving a `TypeError` and calling it a safety guarantee.

## 10. Live runtime during the stage

The route's book and checkpoint both moved at **02:55:42 ET**, while this stage was running. That
is the overnight Nikkei window closing and the route writing its own state — live runtime, not
stage output. The book came through it still carrying the right envelope version, the right route
stamp, no foreign fields and no positions: the **fourth** window close the Stage 5ZS repair has
now survived.

## 11. What remains before paper

| | |
|---|---|
| `PAPER_SHADOW_EVIDENCE` | 3 judgeable days of 5, and **0 of them carry Calm evidence** — the phases have not run in production yet |
| `B1` | no decision recorded; its measurement passes on a record that expires 24h after it was taken |
| the SEND wire | **does not exist**, and this stage did not build it |
| machine sleep | operator; unchanged |

The send step is still one job, one swap and one promotion away — a job at the entry instant that
reads the recorded intent and reads no bars at all, a placeholder executor replaced by a real one
proven separately, and the rehearsal intent promoted into the real journal. The promotion is the
act that says this is no longer a rehearsal. The phase times and the entry reference do not move;
that is the point of having built them before the gates open.
