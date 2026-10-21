# Plan: addressing everything the four reviews found

Merged from the risk-layer review, the paper-tab review, the dashboard Phase 2 run and my own
cross-checks. Ordered by what it could cost, not by how hard it is to fix.

Each batch below is self-contained: scope, what must be true when it is done, and a prompt ready to
hand over. Batches are partitioned by FILE so two can run at once without colliding.

---

## 0. Two corrections to earlier conclusions, before anything is built on them

**The C1 absolute value is deliberate and documented. My earlier call was wrong.**

I read the threshold rationale, found it written entirely in cost terms, and concluded that comparing
an absolute mean does not implement the spec. I never looked for a rationale for the absolute value
itself. There is one, and it is explicit:

    "use_absolute": true
    "why_absolute": "A mean is judged on its absolute size, so favourable slippage counts too.
     MES came in 4.00 ticks BETTER than its stop reference and that is still a 4-tick error in the
     expected fill price -- the model that sizes risk from that reference is wrong by the same
     amount whichever way the miss falls. It is not an economic loss..."

So the gate measures expected-price correspondence, not execution cost, and it says so. The maths is
right. What is wrong is narrower: the word QUALITY_BREACH sits on a tile a reader takes for a cost
statement. That is item P3.1 below, a naming fix, and the one-sided change I proposed earlier is
withdrawn.

**A fingerprint comparison told me three files were untouched while they had been changed.** I took
the baseline while the run was still writing and read the result as evidence. Content checks settled
it. Do not use hash comparison as proof of what an agent did unless both ends were taken at a known
quiet moment.

---

## P0 — the live order path. Money, and one of these has already cost us.

| Ref | Finding | Why first |
|---|---|---|
| A1 | The kill-switch file stops nothing. It is printed and reported, never enforced. observe_live_slot, the path that calls the send, never reads it | It is the mechanism of last resort. Today the only working control is stopping the scheduler |
| A2 | An unreadable book is answered as an empty book, in the loader both safety jobs use | It already happened: three positions lost their record and their stops while two jobs reported completed OK |
| A5 | entry_day does not survive the book dialect, so the deferral rule answers not-deferred and stops arm immediately | Measured: two stops placed nine and twenty-two hours early. This divergence was measured at roughly 53,000 dollars once already and fixed |
| A3 | The circuit breaker is driven by a per-process constant | It logs a verdict and cannot trip on accumulated drawdown |
| A4 | The B3 mismatch halt never reaches the Track 1 entry path | On 25/9 B3 found three orphans and Track 1 kept deciding |
| A8 | read_route_positions turns a missing positions key into empty, and drops non-dictionary rows silently | Same family as A2, inside the function written to prevent A2. Mine |

A2 is NEEDS DECISION, not ready to hand over. A5 already has its own written spec. The rest go in
Batch 1.

## P1 — statements about safety that are false

| Ref | Finding |
|---|---|
| N1 | The paper tab reports BREACH, 0 of 4 positions protected, while the broker holds four working PreSubmitted stops. It checks for a stop_order_id field in the book; the route's writer never fills that field, and all four rows carry a stop_price instead. Verified: no row has stop_order_id, every row has stop_price, and the broker log shows four live STP orders |
| N2 | paper_evidence_reader expects inst, cluster and contracts, so every displayed protection row loses its instrument, cluster and size. Sixth instance of the dialect family, third module |
| A6 | The order gate is read once at process start; the send reads a cached boolean, and the live path never calls overridden() |
| A7 | The audit artifact writes "no gate blocker is open — an order would not have been refused" while the evidence gate is failing and overridden |

## P2 — evidence that exists and nothing reads

From the NOT_WIRED classification. These are wiring, not missing data, and that distinction is the
useful part of that review.

    source exists, nothing reads it     b3_reconcile, log_hygiene, rejections, stp_placement,
                                        stp_verification, tws_restart
    read, then discarded                open_incidents (read at 3084, replaced by _track1_finish),
                                        state_persist (feeds current_protection, then erased for
                                        lacking a legacy field)
    genuinely missing                   data_freshness, manual_intervention, paper_vs_backtest,
                                        pnl_thresholds, roll_slippage, runner_freshness,
                                        tws_restart_nights

Only the first two groups are work. The third is a decision about what to build.

Also here: the readiness card reads obsolete flat properties and renders undefined targets with
PENDING instead of the gate's real verdict; and the payload carries a superseded spec string
(N>=100, abs mean <=5 ticks) beside the active one.

## P3 — wording, where the number is right and the sentence is not

    P3.1  QUALITY_BREACH reads as a cost verdict on a gate that measures correspondence
    P3.2  the paper tab maps both null and numeric zero to the same dash, so a real zero and an
          absent value cannot be told apart
    P3.3  sizing divides by design capital; if that is the validated model, the display must not
          read as live-equity sizing

---

## Batch 1 — the live order path

SCOPE: A1, A3, A4, A8. A5 is already specified separately and must not be duplicated here. A2 is
blocked on a decision.

MODIFY ONLY:

    global_index/run_live_day_track1.py
    global_index/track1_signal_layer.py
    new test files under global_index/

DO NOT MODIFY: global_index/runner.py and the two sweep entry points (separate task), anything under
global_index/track1_runtime/, the books, monitor/**, scratch/**.

GATES:

**B1.1 kill switch.** With the file present, a slot must refuse to send, and the refusal must be
recorded in its evidence row. Re-read at the send, not only at process start — a file created
mid-session must take effect. Over-application guard: with the file absent, the slot behaves exactly
as it does today, and the refusal path must not also suppress observation. Stopping trading is not
the same as stopping looking.

**B1.2 breaker input.** The breaker is driven by a measured figure rather than the account constant.
State where that figure comes from and why it is trustworthy; if the only honest source is the
persisted book and the book carries zeroes, say so and propose rather than invent. Over-application
guard: a synthetic drawdown past the limit makes it refuse, AND a flat day does not.

**B1.3 B3 reaches the route.** A recorded broker/book mismatch blocks new entries on this route.
Over-application guard: a clean reconcile does not block, and a mismatch does not also stop exits or
stop placement.

**B1.4 the reader.** A book that exists with no positions key raises. A non-dictionary row raises
rather than being dropped. Over-application guard: a genuinely absent file still returns empty, and
every row in every book and snapshot on disk that loads today still loads to identical values.

**B1.5** No live book, journal or order is written. Compare positions content, not the file hash:
a window close restamps the envelope legitimately.

## Batch 2 — the paper tab

SCOPE: N1, N2, P2 groups one and two, P3.1, P3.2.

MODIFY ONLY:

    monitor/backend/paper_evidence_reader.py
    global_index/dash/paper/paper.js
    new test files under monitor/

DO NOT MODIFY: the realtime dashboard, track1_market_view.py, job_journal_reader.py, anything on the
order path, the books.

GATES:

**B2.1 protection.** Protection status is derived from what the broker actually holds, not from a
field the route's writer never fills. Over-application guard: when the broker cannot be read, the
row says unknown — not protected, and not breached. Three states.

**B2.2 dialect.** The protection rows show instrument, cluster and size for a Track 1 book row.
Over-application guard: a legacy-shaped row still renders exactly as it does today.

**B2.3 wiring.** Each row moved out of NOT_WIRED names its source and shows a measurement.
Over-application guard: a row whose source genuinely does not exist stays NOT_WIRED and keeps saying
so — moving it would be the worse defect.

**B2.4 read-then-discarded.** open_incidents and state_persist keep the value already computed.
Over-application guard: assert the value shown equals the value the reader produced, not merely that
it is non-empty.

**B2.5 the label.** The correspondence gate does not read as a cost verdict, and the sample size
appears beside the verdict. Do NOT change use_absolute or any threshold; the maths is deliberate and
documented.

**B2.6 zero versus absent.** A real zero and an absent value render differently. Assert both.

---

## What is NOT in either batch, and why

    A2    needs an operator decision; the proposal is written with its gates
    A5    has its own spec, unstarted
    A9    may be the intended capital model; a wording fix at most, after confirmation
    A10   a failed max-hold run has no same-day retry; recorded, low
    the genuinely-missing evidence sources: a build decision, not a fix
