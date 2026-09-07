# Stage 5S — the gate from shadow to paper, made explicit and unable to fail open

**2026-08-25, 23:50–00:20 ET ·** all Track 1 windows closed throughout (NKD opens 01:10) · no
scheduler or backend restarted · **no IBKR connection** · no order · **no confirmation file
created** · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` added anywhere · no parquet,
CSV or runtime evidence written · no commit.

---

## Verdict: **PAPER_NOT_READY_WAITING_FOR_SHADOW_EVIDENCE**

…and it would have been **NOT_READY_GATE_DEFECT** an hour ago. That is not a turn of phrase; it
is measured:

```text
with a confirmation file releasing B1 and ZERO judgeable shadow days:
  may_enable_orders()  BEFORE Stage 5S :  True
  may_enable_orders()  AFTER  Stage 5S :  False
```

Every condition on the order gate was about **authorisation** and not one was about
**evidence**. B1 is a decision recorded on disk. `LIVE_FRAME_ADAPTER_VERIFICATION` measures the
code's wiring. `TRACK1_ORDERS_APPROVED` is an out-of-band approval and `--allow-orders` is a
request. Meanwhile `track1_shadow_acceptance` has been computing, every day, whether the route
actually did what it was supposed to — and **nothing that decides whether orders may be sent
had ever read it**. A route with zero judgeable days and a route with a hundred were
indistinguishable to the gate.

---

## 1. What evidence is required before paper orders

Now explicit, in one named block in `global_index/track1_paper_readiness.py`:

| question | answer | constant |
|---|---|---|
| how many judgeable days? | **5** — one full trading week | `REQUIRED_JUDGEABLE_DAYS` |
| must all four sleeves pass? | **yes**, each must reach PASS at least once inside the window | `REQUIRED_SLEEVES` |
| no-candidate days? | **they count.** A sleeve that observed its window and found nothing is `observed_no_action` — judged, not failed. That is why a *day* can pass on such a sleeve while the sleeve still owes its own PASS | (the per-sleeve rule) |
| WARN vs FAIL? | **FAIL: none allowed. WARN: one day allowed** | `MAX_FAIL_DAYS=0`, `MAX_WARN_DAYS=1` |
| p95 threshold? | **<300 s is required, <240 s is the target.** Over the ceiling the acceptance gate FAILS the day; between target and ceiling it WARNs — so the ceiling is a refusal and the target spends the one WARN allowance | `RUNTIME_P95_REQUIRED_S`, `RUNTIME_P95_TARGET_S` |
| checkpoint accepted? | **yes** — already folded into the day verdict by `evaluate_day` | — |
| explanations / freshness proof? | **yes** — also folded in: a decision without an explanation, or an explanation without a freshness proof, fails the day | — |
| how recent must it be? | **newest qualifying day within 21 days** | `MAX_EVIDENCE_AGE_DAYS` |

**Those five numbers are judgement calls, not derived quantities.** They are gathered in one
block so they can be moved deliberately in one place. Moving them changes what "ready" means
and nothing else.

### Why it cannot be satisfied by stale or missing evidence

- a missing audit directory, a missing day, an unparsable line, a `NOT_ENOUGH_DATA_YET` verdict
  and a record for another route **all count against** readiness;
- **absence is never a pass** — a day with no audit record is a day nobody watched;
- the qualifying days are the **most recent** judgeable ones, and the newest must be inside the
  age limit, so five clean days in August cannot make December ready;
- the gate **closes again** if the evidence goes stale;
- the measurement **fails closed** on any exception — `scheduler_processes()` returning `[]`
  for "I could not tell" already cost this project six entry slots, and this is the one place
  where repeating that mistake would *open* a gate.

Read it with:

```powershell
python -m global_index.track1_paper_readiness
```

Right now:

```text
  [PASS] audit_records_readable
  [FAIL] judgeable_days      1 judgeable day(s) on record, 5 required
  [FAIL] no_failing_days     1 FAIL day(s) in the qualifying window, at most 0 allowed
  [PASS] warn_days_within_allowance
  [PASS] evidence_is_recent
  [FAIL] every_sleeve_passed_at_least_once   never PASSED: all four
  READY FOR PAPER (evidence half): False
```

---

## 2. What still blocks paper — and which are decisions, which are code

| | blocker | kind | who closes it |
|---|---|---|---|
| **B1** | `B1_broker_account_or_legacy_retirement` | `USER_DECISION_GATE` | **operator** — retire legacy, or fund a separate IBKR account, and record it in `track1_go_live_confirmation.json` |
| **new** | `PAPER_SHADOW_EVIDENCE` | `MEASURED_GATE` | **nobody** — it cannot be signed, only earned. It opens when the audit records exist and closes again if they go stale |
| | `LIVE_FRAME_ADAPTER_VERIFICATION` | `MEASURED_GATE` | already released by measurement; holds again if the wiring regresses |
| | `TRACK1_ORDERS_APPROVED=1` | environment | **operator**, out of band |
| | `--allow-orders` | argv | **operator**, per invocation |

**Not in the registry, and worth saying so.** Broker-flat / orphan-STP reconciliation and the
legacy drain are handled by the eleven legacy safety jobs still scheduled and by the B1
decision itself — they are **not** machine gates on the order path. If they should be, that is
a further blocker to add, not something the current table implies.

---

## 3. Is there a single command or file that could accidentally enable orders?

**No — and there are two independent reasons, either of which alone would be sufficient.**

**Three deliberate acts are required, not one.** A confirmation file schema-checked on disk,
`TRACK1_ORDERS_APPROVED=1` in the environment, and `--allow-orders` on the command line. A
test asserts the file alone does not arm the gate. And `blocking()` now also demands evidence,
so all three plus a clean shadow week are needed.

**Even fully armed, the route holds a broker that cannot send.** `run_shadow` constructs
`NoOrderBroker()` unconditionally, whose `send_order` raises; `IBKRBroker` is **never
constructed** anywhere in `run_live_day_track1.py`. Pinned by an AST test.

**And nothing automated ever asks.** Neither `run_scheduler.py` nor `monitor/ops.py` contains
the string `--allow-orders` in any argv it builds, and `ops.py` never assigns
`TRACK1_ORDERS_APPROVED`. Both pinned by AST tests rather than grep, so a docstring mentioning
the flag cannot pass or fail them.

---

## 4. Does the dashboard expose all the required evidence?

Mostly. `monitor/backend/track1_runtime_reader.py` surfaces window coverage, slot timing,
audits (with their acceptance gate), explanations, the book, the checkpoint, the gate ledger
and the safety state.

**The one thing it does not surface is the readiness roll-up itself.** The operator sees the
raw evidence and sees `PAPER_SHADOW_EVIDENCE` in `blocking_now`, but the per-check breakdown
lives only in the CLI. Not fixed here — a dashboard row is a UI change, and this stage was
scoped to the gate — but named so it is a decision rather than an oversight.

---

## 5. Does the acceptance gate read durable runtime paths, not scratch?

**Yes**, and it is now asserted:

```text
COVERAGE_DIR = global_index/track1_runtime/window_coverage
TIMING_DIR   = global_index/track1_runtime/slot_timing
AUDITS_DIR   = global_index/track1_runtime/audits
```

None of them is under `scratch/`. The audits directory carries its own comment saying why: an
audit is evidence about evidence, and ordinary cleanup of scratch would delete the record of
whether the route was ever fit to trade.

---

## 6. Does paper differ from shadow only at the broker boundary?

**No — because paper mode is not implemented.**

This is the largest finding of the stage and it was not what I expected to find. Arming changes
exactly two things today: the recorded decision mode (`armed` instead of `shadow_live`) and the
fact that the freshness gate binds. **The broker is `NoOrderBroker` either way.** The code that
would swap in a real broker, place an order, reconcile the fill and book it does not exist in
this route.

So the honest reading of the whole gate is: it currently guards a door that does not open onto
anything. That is a safe state, and it means the shadow period can be collected without any
risk of an order — but "turn the gate on and we are trading paper" is not true, and nothing in
the runbook said so.

---

## 7. Does any code path reference legacy strategy state for Track 1 decisions?

**No.** `run_live_day_track1.LEGACY_PATHS` is a list of nine paths the route must never write —
`live_positions.json`, `global_index/replay_checkpoint.json`, `runner.pid`,
`global_index/preflight_state.json` and the rest — and it is asserted by test, not merely
intended. No Track 1 decision path reads them either.

---

## 8. Is B-5R-I relevant while legacy strategy jobs are omitted?

**No — measured, not assumed.**

The defect is that `IBKRBroker.fetch_bars` resolves through the ORDER map, so legacy code
asking for MNKD bars gets the micro MNK. It lives in `runner.py:1592` and
`run_live_day.py:677`, both **strategy** paths, and `run_live_day.py:88` sets
`NKD_INST = "MNKD"`.

In track1-only shadow there are **zero** legacy strategy jobs. What remains scheduled is the
legacy *safety* set — eleven jobs draining the old book — and `run_stop_repair.py` and
`run_maxhold_exit.py` contain **no call to `fetch_bars` at all**. So nothing currently running
can reach the defect.

It becomes relevant again the moment a legacy strategy job is re-registered. It should be
closed before that, not because of it.

---

## 9. The exact sequence from shadow to paper

Once — and only once — `python -m global_index.track1_paper_readiness` reports every check
PASS:

```powershell
# 1. The evidence half. Every check must read PASS; this cannot be signed, only earned.
python -m global_index.track1_paper_readiness

# 2. The decision half. Record the B1 choice — retire legacy, or a separate account.
#    Written by a person, never by a script. Schema-checked; it fails closed on anything
#    it cannot fully validate.
#    global_index/track1_go_live_confirmation.json
#      {"schema_version": 1, "confirmed_by": "<name>", "confirmed_at": "<YYYY-MM-DD>",
#       "legacy_retired_confirmed": true}      (or separate_account_confirmed)

# 3. Confirm the registry agrees that nothing is blocking.
python monitor\ops.py status        # expect  orders_possible=True, track1_blocking=[]

# 4. THE PART THAT DOES NOT EXIST YET — see finding 6. A broker that can actually place an
#    order has to be built and proved before any of the above means anything.

# 5. Only then, per invocation and never from the scheduler:
#    TRACK1_ORDERS_APPROVED=1  and  --allow-orders
```

Steps 1–3 are reachable today. **Step 4 is a project, not a command.**

---

## What changed

**Production**

```text
global_index/track1_paper_readiness.py   NEW — read-only. The evidence rule, its thresholds,
                                         a fail-closed gate measurement and a CLI report.
global_index/track1_gates.py             + the `shadow_evidence` measurement and the
                                         PAPER_SHADOW_EVIDENCE blocker
```

The blocker can **only refuse**. It adds a condition to arming, removes none, and cannot arm
anything by itself. Its marginal cost on `blocking()` — which `ops status`, the dashboard poll
and every slot spawn call — is **1 ms** against the 106 ms `live_frame_wiring` already spends.
(The first version cost 75 ms because it imported pandas to get today's date; that is now
stdlib.)

**Tests** — 24 new, and seven existing files updated because they pinned "B1 is the only
blocker", which was true when written and is now legitimately false. Two of them are worth
naming: the Stage 3B ledger tests had already been rewritten **twice** by a measured gate
opening and closing, and their own comment says "chasing the state is the wrong test". They are
now generalised over `MEASUREMENTS` — release every measurement and the route opens; hold each
one shut in turn and exactly its own gate must be the reason — so the next measured gate will
not red them.

The generated `track1_blocking_ledger_20260822.json` was regenerated from the registry and the
markdown ledger gained a section for the new blocker.

**Found, not fixed: seven pre-existing failures.** `test_track1_stage5b/5c/5d` assert a Track 1
route that adds **25** slots (it adds 70 now) and that no runtime evidence exists yet (it does).
They are stale snapshots from before the route grew its four sleeves. Confirmed not mine by
running them with `PAPER_SHADOW_EVIDENCE` removed — **all seven fail identically**. Deciding
what they should now assert is a separate call and was not made tonight.

---

## The direct answers

- **Exact evidence count before paper:** 5 judgeable days, 0 FAIL, ≤1 WARN, every one of the
  four sleeves PASSED at least once, newest day within 21 days, p95 under 300 s throughout.
- **Operator decisions vs code blockers:** B1, `TRACK1_ORDERS_APPROVED` and `--allow-orders`
  are operator acts. `PAPER_SHADOW_EVIDENCE` and `LIVE_FRAME_ADAPTER_VERIFICATION` are
  measurements no one can sign.
- **Accidental go-live path:** none. Three deliberate acts, plus a broker that cannot send, plus
  nothing automated that ever asks.
- **After each judgeable window:** run the post-window audit, confirm the sleeve reached PASS
  rather than NOT_ENOUGH_DATA_YET, and re-run the readiness report to see the count move.
- **Next runtime audit step:** the NKD window at 01:10 ET tonight is the first that should be
  judgeable. When it closes at 02:55, `track1_audit_global_nkd` fires at 03:05 and writes the
  first record that can count toward the five.

```powershell
python -m global_index.track1_shadow_audit --latest --all --dry-run
python -m global_index.track1_paper_readiness
```
