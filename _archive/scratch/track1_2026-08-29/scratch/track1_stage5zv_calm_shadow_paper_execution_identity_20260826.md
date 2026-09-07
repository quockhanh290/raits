# Stage 5ZV — a judgeable contract is not a tradable one

**Opened 2026-08-26, closed 2026-08-27 00:06 ET.** No orders · no order send wired · no
confirmation file · no broker connection · **nothing restarted** · no runtime evidence written
· the entry price definition unchanged and asserted · splice guard untouched.

---

## Verdict

| | |
|---|---|
| Calm contract | **TRADABLE** — the original 10:00 open, Option A |
| shadow/paper identity | **MATCH** under the contract declared here; it was a **MISMATCH** under the 10:01 reading 5ZU left open |
| backtest rerun required | **no** |
| Calm can count toward `PAPER_SHADOW_EVIDENCE` | **yes — for the decision half only**, under an explicit definition (§7) |
| orders possible | **false** |

---

## 1. The measurement that decides it

The question is not "when can the route see the 10:00 bar" — 5ZU answered that. It is **how
early is the setup known.**

Every one of the 421 frozen setups was rebuilt from a frame **truncated at 09:30**, and the
features required to be identical to the full-frame detector's:

```text
407 of 421 reproduce
  5  sessions missing their own 09:30 bar
  9  the rule no longer selects on today's re-adjusted series (the 5ZU finding)
```

Neither remainder is about truncation. The rule reads the prior RTH session and today's 09:30
OPEN, and nothing else.

That OPEN exists at **09:30:00**. A closed one-minute bar carrying it exists at **09:31:00**.
The entry is at 10:00.

> **Twenty-nine minutes of slack.** That is what makes the original contract tradable, and it
> is why the entry does not have to move.

## 2. Why the 5ZU reading was not enough

5ZU let the gate read the 10:00 open from a closed one-minute bar at 10:01. For **shadow** that
is exact and causally sound. For **paper** it is not: an order sent at 10:01 cannot fill at an
open that happened a minute earlier. A shadow row claiming that price would be claiming a fill
paper can never achieve — and it would enter the evidence gate as though it had been achieved.

Judgeable and tradable are different properties. 5ZU delivered the first.

## 3. What moving the entry would cost

Measured over 416 comparable rows, one consistent read, compared on **differences** because
absolute levels drift with roll adjustment:

| entry at | total | vs 10:00 | mean | win % | per-trade stdev | trades whose sign flips |
|---|---:|---:|---:|---:|---:|---:|
| **10:00** (the record) | $14,776 | — | $35.5 | 61.5 | — | — |
| 10:01 | $13,606 | **−$1,170 (−7.9%)** | $32.7 | 61.1 | $20.6 | **18 of 416 (4.3%)** |
| 10:05 | $14,726 | −$51 (−0.3%) | $35.4 | 61.8 | **$36.7** | **29 of 416 (7.0%)** |

**Read the 10:05 row carefully.** Its total is almost unchanged and its per-trade spread is
nearly double. The aggregate hides the change rather than showing there is none — twenty-nine
trades in four hundred flip sign. A number that looks like *"no difference"* is the one to
distrust.

Moving the entry is a different strategy that happens to sum to a similar figure, and it would
need its own walk-forward rather than a parameter edit. Since Option A is tradable, that cost
buys nothing.

## 4. The structure that lets paper send at 10:00 without reading the future

```text
DECIDE    ~09:32 ET   reads the prior session and the CLOSED 09:30 bar.
                      Computes setup, direction, qty, stop rule and risk inputs.
                      Writes INTENDED setup evidence, not a sent order.
                      Reads nothing from after 09:30.

SEND      10:00:00    paper only. Sends the journalled intent as a market order.
                      Reads no bars at all — it acts on the journal.

OBSERVE   10:01+      shadow and paper. Reads the CLOSED one-minute 10:00 bar and
                      records its OPEN as the reference. In shadow that is the end
                      of it; in paper it is the denominator for slippage.
```

**The machinery already exists.** Stage 5V's order journal separates `INTENDED` from
`SUBMITTED` and refuses a first record that is not `INTENDED`. This stage invented nothing —
it named the contract those states were built for.

The SEND phase is **not built here**: the constraints forbid wiring an order send, and the
route still constructs `NoOrderBroker` unconditionally.

## 5. What shadow may say, and what it may not

```text
before entry                   setup · instrument · direction · qty
                               stop_rule · risk_inputs
                               entry_reference_time · intent
after the reference bar closes entry_reference_price · planned_stop
never in shadow                fill_price · fill_time · realised_pnl · slippage
```

Shadow sends nothing, so nothing filled. The three groups are asserted not to overlap, and the
reference price is asserted **not** to be in the before-entry group — recording a price before
the bar carrying it exists is the same error in a smaller costume.

**`planned_stop` is on the after side, and the first draft of this section had it wrong.**
Calm's stop is `entry - 1.5 x ATR`, so the stop LEVEL cannot exist before the 10:00 reference
does. What *can* be known at 09:31 is everything else about it, and the distinction is sharper
than it first looks — measured with two different entry prices and the same ATR:

```text
entry 5000.00  ->  stop 4982.00   distance 18.00
entry 5123.75  ->  stop 5105.75   distance 18.00
```

The stop **distance** is `1.5 x ATR` and is independent of the entry; so is the dollar risk,
which is `distance x point_value x qty` and cancels the entry out; and `qty` is a fixed sleeve
constant, `SLEEVE_QTY["roska4_calm"]`, not a risk-derived number. Only the stop **level** — a
price — waits for 10:00. That is why before-entry evidence carries `stop_rule` and
`risk_inputs` and the after side carries `planned_stop`.

Four things only paper can establish, and shadow evidence can never stand in for: that an order
sent at 10:00:00 was accepted; the actual fill against the 10:00 open; the slippage between
them; and that a protective stop rested at the broker afterwards.

## 6. Four independent proofs the setup reads no 10:00 high, low or close

1. `entry_conditions(prev_row, cur_rth_open, params)` takes two inputs and neither is today's
   entry bar — signature, asserted.
2. The causal detector calls it exactly once — AST.
3. The causal path never subscripts today's minute frame directly; every read goes through
   `_bar_open_at`, which takes an OPEN and only an OPEN — AST, Stage 5ZU.
4. **407 of 421 setups reproduce from a frame with those bars removed.** The strongest of the
   four, because it takes the data away rather than asserting it is unread.

## 7. How the evidence gate should count Calm before any real fill

> A Calm day counts as judgeable when the slot decided causally from closed bars at or before
> 09:31, an INTENDED order was journalled before 10:00, and the 10:00 reference was observed
> afterwards.

That certifies the route **would have acted**. It certifies nothing about execution, and the
gate should say which of the two it is counting rather than inheriting the stronger claim.

So `PAPER_SHADOW_EVIDENCE` can reach its five clean days with Calm contributing, and the first
paper day is still the first time execution is tested. Different claims, kept apart.

## 8. The gate state changed while this stage ran

I reported three blockers repeatedly. That was true when measured. **It is two now.**

| | |
|---|---|
| `REGIME_LABEL_VERIFICATION` | **RELEASED — its first PASS ever.** Two records today: 17:47 UTC (the 13:45 ET pre-flight) and 20:20 UTC (the 16:20 ET post-close refresh), both *"1761 label(s) compared through 2024-12-31, none changed"*. Stage 5ZL built that gate; this is the first time it has said yes. |
| `PAPER_SHADOW_EVIDENCE` | 2 judgeable days → **3 of 5** |
| `legacy_broker_flat` | still PASS, on a **newer** record than 5ZQ's: 2026-08-26T15:34:28Z — 11:34 ET, the same minute the book repair was applied. Whoever ran the repair re-recorded B1 afterwards, which is what the 5ZS runbook asked for. |

B1 still blocks because no decision is recorded. That is correct.

## 9. A test that could not stay green, and one that went off on time

**`test_ledger_matches_the_registry_exactly`** compares a frozen file against `as_ledger()`,
which **embeds live measurement results**. Regenerated at Stage 5ZR, it had drifted again
within hours: the judgeable-day count moved and the regime verification went from *no record*
to *PASS*. Neither is a registry change; both are the world moving.

A parity test that goes red on its own schedule is one people learn to regenerate past without
reading. So the **static** half is now compared exactly — every id, status, evidence sentence,
releasing flag and dependency — and the **live** half is checked for shape: a blocker that
declares a measurement must carry its result, and one that declares none must not pretend to.
That is what the exact comparison was really protecting.

**`test_the_preflight_record_still_holds_the_operator_restored_seven_days`** was a time bomb,
and it went off correctly. Stage 5ZM put it up after the 5ZL incident so no test of mine could
fabricate today's clearance. The real 13:45 ET pre-flight has now run: `2026-08-26` is present
and `2026-08-17` has rolled off the seven-day window. **The guard did its job for four stages
and has expired.** It should assert the property — that no day was added by anything but the
real pre-flight — rather than a date list. That is a repair for whoever next touches 5ZN, not
something to slip into a stage about execution identity.

## 10. Tests

**20 tests**, mutation sweep **9 of 9 red**.

One was still green on the first sweep and the reason is worth keeping: `test_5`'s fixture used
`order_sent_at="09:59"`, which **also** breaks the send-equals-reference rule — so
`self_check()` stayed non-empty with the ordering check disabled entirely, and the test passed
for a rule it was not testing. A bare *"is non-empty"* over a validator with five rules cannot
say which one fired. It now trips exactly one rule, asserts the message, and requires
`len(errs) == 1` so it cannot drift back.

## 11. Remaining before paper

| | item | class |
|---|---|---|
| 1 | the B1 decision — and the state of the world that makes it true | operator |
| 2 | five clean judgeable days — **3 of 5**, and Calm cannot contribute until its slot moves | time + one cron edit |
| 3 | ~~the regime gate's first PASS~~ | **done, 2026-08-26** |
| 4 | machine sleep | operator |
| 5 | **the order path** — the SEND phase of §4 does not exist | code, unwritten |
