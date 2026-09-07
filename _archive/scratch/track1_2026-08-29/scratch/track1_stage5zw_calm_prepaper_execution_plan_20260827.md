# Stage 5ZW — the correction holds, and the plan is two jobs and one stream

**2026-08-27, ET 00:20–01:20.** Review and plan. No order-send implementation and none
authorised · no orders · no confirmation file · no `IBKRBroker` · **nothing restarted** · no
runtime file written · the Calm entry time and the backtest untouched.

---

## Verdict

| | |
|---|---|
| 5ZV correction | **ACCEPTED** |
| Calm contract | still **TRADABLE**, Option A, the 10:00 open |
| shadow evidence | can count the **decision**; the fill is paper-only |
| paper readiness | **NOT_READY** |
| orders possible | **false** |

---

## 1. The correction is right, and it is sharper than it was stated

The claim under review: Calm's stop is `entry − 1.5 × ATR`, so a concrete stop price cannot
exist before the 10:00 reference does.

Read from source: `disaster_stop(entry, atr) = entry − mult × atr`. The stop **level** requires
the entry price. My first draft of 5ZV put `planned_stop` in the before-entry group — shadow
would have recorded a price it cannot compute, which is the same error as recording the
reference price early, in a smaller costume. **Accepted.**

But "the stop is not known" is looser than the truth. Measured with two entry prices and one
ATR:

```text
entry 5000.00  ->  stop 4982.00   distance 18.00
entry 5123.75  ->  stop 5105.75   distance 18.00
```

The **distance** is `1.5 × ATR` and does not move with the entry. The **dollar risk** is
`distance × point_value × qty`, so the entry cancels out of it entirely. And `qty` is a fixed
sleeve constant — `SLEEVE_QTY["roska4_calm"]` — not a risk-derived number.

**Only the stop level waits for 10:00.** That is what justifies `stop_rule` and `risk_inputs`
before the entry and `planned_stop` after it, and it is a stronger statement than the one the
correction made.

### The split, as agreed

```text
before entry                   setup · instrument · direction · qty
                               stop_rule · risk_inputs
                               entry_reference_time · intent
after the reference bar closes entry_reference_price · planned_stop
never in shadow                fill_price · fill_time · realised_pnl · slippage
```

### What the review also found

- **Strategy unchanged**: entry stays the 10:00 open, asserted against `CalmAParams`.
- **Nothing authorised**: no send wired, `NoOrderBroker` still unconditional.
- **No runtime file touched by the edits.** `live_positions.track1.json` and the checkpoint
  moved at 15:56:24 ET because the **swing window closed** — the route wrote them. The book
  came through still schema 2, route-stamped, no foreign keys: the **third** window close the
  Stage 5ZS repair has now survived.
- **The docs were not internally consistent.** The 5ZV markdown listed `planned_stop` under
  before-entry in its code block and contradicted itself five lines later. The block, the JSON
  and the pipeline doc are now aligned — the block is the thing a reader copies.
- **Tests**: 22 pass alone, 76 with 5ZN. The repairs in those suites were to stale **roster**
  and **date** pins, not to safety assertions.

## 2. What is still missing for Option A

| phase | state |
|---|---|
| **DECIDE ~09:32** | **missing.** Nothing computes the setup from the closed 09:30 bar and records an intent. Today's single Calm slot fires at 10:00 and does everything at once. |
| **SEND 10:00:00** | **missing by design, and must stay missing.** `NoOrderBroker` is unconditional; `UnbuiltPaperExecutor` is the placeholder. |
| **OBSERVE 10:01+** | **missing.** 5ZU let the gate read the 10:00 open from a closed one-minute bar; nothing records it as the reference. |

## 3. Two jobs and one new stream

**Two scheduler jobs**, not one expanded slot:

```text
TRACK1_CALM_DECIDE_0932    one_shot   reads bars closed by 09:30, records the intent
TRACK1_CALM_OBSERVE_1002   one_shot   reads the closed 10:00 minute bar, records the
                                      reference and the planned stop level
```

replacing `TRACK1_CALM_1000`. Net one extra job; the scheduler goes from 101 to 102.

**Not one expanded slot**, because a slot starting at 09:32 and finishing after 10:01 holds a
process and a client id across the entry instant, and a crash anywhere in that half hour loses
both halves. The two phases have different inputs and different failure modes, and a slot that
spans them cannot report which one failed.

**A new stream**, `global_index/track1_runtime/shadow_intent/`, because every existing stream
already has a reader that counts it. `shadow/` holds per-slot explanations; a reader counting
rows there would start counting intents.

## 4. Why the intent must not go in the order journal

This is not a preference. **Four readers treat the existence of
`global_index/track1_runtime/orders/` as proof the route has acted:**

| reader | what it does |
|---|---|
| `b1_book_repair.route_has_never_traded` | **refuses the book repair** if it exists |
| `track1_paper_callsite` | guards the production root against it |
| `track1_report` | reports `NOT_PRODUCED` while it is absent |
| the shadow-window runbook | *"an order journal was written — stop and investigate"* |

A shadow intent written there would make all four report a route that traded, on a day it sent
nothing — and it would **block its own book repair**. That is now pinned by tests, before
anyone implements the plan.

## 5. What changes later, once the gates open

One job, one swap, one promotion:

- a **SEND job at 10:00:00** that reads the recorded intent and calls the executor. It reads
  **no bars at all** — that is what makes it free of future data;
- `UnbuiltPaperExecutor` becomes a **real executor** holding an `IBKRBroker`, built and proven
  separately;
- the shadow intent is **promoted** to an `INTENDED` row in the real order journal — the same
  fields, a different stream, and the promotion is the act that says this is no longer a
  rehearsal.

The DECIDE and OBSERVE phases, their times and the entry reference do not change. That is the
point of building them now.

## 6. What remains blocked

| | |
|---|---|
| `PAPER_SHADOW_EVIDENCE` | **3 of 5** judgeable days. Calm contributes none until DECIDE/OBSERVE exist — its slot still refuses. |
| `B1` | no decision recorded. Its measurement passes on a record from 11:34 ET and **expires 24h later**, so it needs re-running on the day the decision is made. |
| machine sleep | operator; unchanged |
| the SEND wire | does not exist, and this stage does not build it |

## 7. How the gate should count Calm

> A Calm day is judgeable when the DECIDE phase decided causally from bars closed at or before
> 09:31, an intent was recorded before 10:00, and the OBSERVE phase recorded the 10:00
> reference afterwards.

That certifies the route **would have acted**, and at what reference. It certifies nothing
about acceptance, fill, or slippage. `PAPER_SHADOW_EVIDENCE` should carry the label it is
counting — `decision_judgeable` — so a later reader cannot mistake five clean days for five
proven executions.

## 8. A finding recorded rather than fixed

`ORDERS_DIR` is defined **independently in three modules** — `track1_order_journal`,
`b1_book_repair` and `track1_report` — while a fourth references the shared constant. Three
definitions of one path drift silently, and the readers that prove the route has not traded
would start looking in different places.

A test now asserts they still agree, which fails the day they stop — the only way anyone would
find out. Collapsing them to one import belongs to whoever next touches that path.

## 9. Tests

**15 tests**, `scratch/test_track1_stage5zw_calm_prepaper_execution_20260827.py`. They hold the
separation invariant, the three phase times, the stop-level property, and that the send phase
is still unbuilt.

One failed while being written, for a reason worth keeping: it required each reader to contain
the orders-directory **literal**, and `track1_paper_callsite` references the shared **constant**
instead — the module doing it the better way. The test now accepts either and records the
duplication as the finding above.

The blocker assertion is written as a **property**, not a roster: B1 must be blocking and
`orders_possible` must equal "nothing is blocking". The roster moved twice in two days, and
pinning it is how a dozen unrelated suites went red.
