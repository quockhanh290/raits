# Stage 5T — the paper order boundary: what is missing, and exactly what has to be built

**2026-08-25, 00:20–00:35 ET ·** all Track 1 windows closed (NKD opens 01:10) · no scheduler or
backend restarted · **no IBKR connection** · no order · no confirmation file ·
`TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` added anywhere · no parquet, CSV or runtime
evidence written · no commit.

---

## Verdict: **PAPER_BROKER_PATH_NOT_IMPLEMENTED_DESIGN_READY**

The boundary is specified, the one piece that could be built without a broker is built and
tested, and the test plan for the rest is written. It is **not** `READY_FOR_IMPLEMENTATION`,
because two ordering questions are genuinely open and naming them is worth more than a
confident verdict — see the last section.

---

## 1. What `--allow-orders` actually does today

There are two paths and they behave differently. Neither can send anything.

```text
main(--allow-orders)
  └─ gate = OrderGate(a.allow_orders)
       requested AND not allowed  ->  prints REFUSED, lists the open blockers, returns 2
       requested AND allowed      ->  falls through
  ├─ source == "live-shadow"   ← THE SCHEDULER'S PATH
  │     the gate is never threaded anywhere. `observe_live_slot` takes no order-gate
  │     parameter and contains no reference to OrderGate at all.
  │     `print("send_order calls: 0")` is a LITERAL.
  └─ else (replay)
        run_shadow(..., order_gate=gate)
          -> resolve_decision_mode() records `armed` instead of `shadow_live`
          -> freshness BINDS
          -> broker = NoOrderBroker()          ← unconditional
```

So arming changes **two** things: a string in the evidence, and whether the freshness gate
binds. `IBKRBroker` is **never constructed** anywhere in `run_live_day_track1.py`, and the
module contains no `placeOrder`, `MarketOrder`, `LimitOrder` or `reqIds`.

**Where `IBKRBroker` would need to be constructed:** in the slot path, beside the bar provider,
and *only* when the gate is armed. Not inside `run_shadow` — that function is the replay
harness and giving it a live broker would let a replay send orders.

**Where orders would be translated:** between "the book admitted it" and "the ledger row is
written" — from the `Decision` objects `Track1Book` returns with verdict `TAKE`. Nowhere else:
a candidate that the cap gate rejected must never reach an order builder.

---

## 2. What must be identical between shadow and paper

Written as data in `track1_paper_order.MUST_BE_IDENTICAL` so a test can walk it, rather than as
prose nothing checks:

| what | where | why it cannot move |
|---|---|---|
| live frame + splice guard | `track1_live_source.live_frame` | the bars a decision was made on |
| history symbol per instrument | `track1_live_source.history_symbol` | MNKD reads NKD; an order symbol must never reach the bar path |
| freshness gate | `track1_freshness.evaluate` | a stale input is a refusal in both modes, not a warning in one |
| sleeve rules | `track1_normal_r4` / `track1_calm_a` / `track1_stress_mnq` | reproduced exactly against the committed artifacts |
| sizing basis | `track1_params.risk_dollars` | the cap gate must read the number the measured book was admitted under |
| admission + caps | `track1_signal_layer.Track1Book` | including the risk-high-first ordering inside an instant |
| explanations | `track1_explain` | a decision without an explanation is not auditable in either mode |
| checkpoint + params hash | `track1_params.sleeve_identity` | a paper book resumed under a different identity is a different strategy |

If a paper implementation changes any of these, **the shadow evidence stops describing the
thing that is trading** — which is the entire premise of the readiness gate built in Stage 5S.

## 3. What may differ, and only here

```text
the broker object            NoOrderBroker  ->  an adapter over IBKRBroker
send / cancel / switch       track1_switch.close_then_open already has the shape
fill and reconcile results   Fill.status, filled_qty, avg_price, commission
the book after CONFIRMED fills   live_positions.track1.json — never the legacy file
```

---

## 4. The objects that are needed

**Built and tested in this stage** (pure, no broker, cannot send):

```python
track1_paper_order.candidate_to_order(candidate, *, ref_day, action="OPEN") -> broker.Order
track1_paper_order.assert_admitted(decision)          # refuses unless the cap gate said TAKE
track1_paper_order.Track1OrderExecutor                # Protocol — nothing implements it
track1_paper_order.UnbuiltPaperExecutor               # every method refuses by name
```

`candidate_to_order` refuses rather than guesses in four cases, each one a defect this route
has already met:

- **`order_identity_drift`** — the runner name must resolve, through the broker's own map, to
  the same `tradable_symbol` the route hashed. A test re-injects the 2026-08-14 defect
  (`_RAITS_TO_IBKR["MNKD"] = "NKD"`) and requires the refusal.
- **`candidate_not_admitted`** — orders come only from `Decision.verdict == TAKE`.
- **`order_quantity_invalid`** — quantity is the candidate's, never the instrument's, because
  MNQ is one micro under Normal and seven under Stress on the same day.
- **`order_ref_day_missing`** — `ref_day` is **required and deliberately not derived** from
  `candidate.entry_time`. For Rổ 4 the two would agree; for `global_nkd` the entry stamp is an
  **aware Tokyo instant**, and turning that into a trading day inside an order builder is the
  shape of every clock defect this route has had.

**Still to be built:** an adapter implementing `Track1OrderExecutor` over `IBKRBroker`.

### How MNKD stays split, for free

`Order.inst` carries the **runner** name. `IBKRBroker.send_order` resolves it through
`_front_month_contract` → `_RAITS_TO_IBKR`, so MNKD reaches **MNK** without the order layer
naming MNK at all — one map, in the layer that owns the broker. Meanwhile the bar path goes
through `history_symbol("MNKD") = "NKD"`. Verified:

```text
Order(inst='MNKD', …)   broker routes to MNK   bar provider fetches NKD
```

**The trap to write down:** `IBKRBroker.fetch_bars` resolves through the *order* map. If a
future implementation hands one `IBKRBroker` to both the executor and a bar reader, the bar
reader gets MNK and Stage 5Q-7 comes straight back. The executor must be the **only** consumer
of that object for orders, and bars must keep coming through `IBKRBarProvider`.

### `NoOrderBroker` stays

Shadow keeps it, and its `send_order` must keep raising. A shadow run that silently produced
fills would be worse than one that crashed.

---

## 5. The gates that must still hold

| gate | kind | state |
|---|---|---|
| `PAPER_SHADOW_EVIDENCE` | measured — cannot be signed, only earned | **holding** (1 judgeable day, 5 needed) |
| `B1_broker_account_or_legacy_retirement` | operator decision on disk | **holding** |
| `TRACK1_ORDERS_APPROVED=1` | environment, out of band | unset |
| `--allow-orders` | argv, per invocation | never passed by the scheduler or ops |
| broker-flat / orphan-STP | **not a machine gate** | a decision that still has to be made |

That last row is unchanged from Stage 5S and is worth repeating: the reconciliation question is
handled today by the eleven legacy safety jobs and by the B1 decision. It is **not** enforced on
the order path. If a paper run should refuse to start against a broker whose positions disagree
with `live_positions.track1.json`, that is a fifth gate to add — and it is the one I would add
first.

---

## 6. The runbook sequence, once the evidence passes

```powershell
# 1. EVIDENCE  — every check PASS. Cannot be signed, only earned.
python -m global_index.track1_paper_readiness

# 2. DECISION  — record the B1 choice in track1_go_live_confirmation.json. Written by a person.

# 3. BUILD     — the executor. This stage says what it must do; it does not exist.

# 4. PROVE     — the test plan in section 7, including the failure branches.

# 5. RECONCILE — decide the broker-flat / orphan-STP question before the first order.

# 6. CONFIRM   — python monitor\ops.py status   ->  orders_possible=True, track1_blocking=[]

# 7. ARM       — per invocation, never from the scheduler:
#                TRACK1_ORDERS_APPROVED=1  and  --allow-orders
```

Steps 1, 2, 6 and 7 are commands. **Steps 3, 4 and 5 are work.**

---

## 7. The test plan

**Written and passing now — 20 tests** (`scratch/test_track1_stage5t_paper_broker_path_20260825.py`):

| | |
|---|---|
| `NoOrderBroker` still raises, and `run_shadow` still builds it | pinned by AST + a live raise |
| `IBKRBroker` never constructed in the runner | AST |
| the scheduler's slot path takes **no order gate at all** | AST over `observe_live_slot`'s signature and names |
| no `placeOrder`/`MarketOrder`/`LimitOrder` anywhere in the runner | source |
| the executor protocol has no implementation | every stub method refuses by name |
| the design module cannot reach a broker | AST over imports and calls |
| MNKD orders MNK while its bars come from NKD | direct |
| the order never carries the history symbol | all five instruments |
| quantity from the candidate, not the instrument | MNQ 1 vs 7 |
| non-positive quantity refused, not rounded | parametrised |
| `ref_day` required, never guessed from a Tokyo stamp | direct |
| identity drift refused | the 2026-08-14 defect re-injected |
| orders only from `TAKE` | all three reject verdicts |
| the invariant list names everything and every module in it exists | walks `MUST_BE_IDENTICAL` |
| sizing basis is the measured book's | 5Q-9 |
| all four gates hold; evidence gate cannot be signed | registry |
| no scheduler/ops path requests orders | AST |

**Required before an executor may be enabled — not yet written:**

1. **partial fill** — `Fill.status == "PARTIAL"` on an entry must not book a full position;
   on a close it must leave the remainder flagged, never silently.
2. **failed fill** — `FAILED`/`CANCELLED` on an entry frees the cap and records a divergence;
   on an exit it sets a retry, and three consecutive failures escalate.
3. **disconnect mid-order** — the book must end in a state the next process can reconcile, and
   the ledger row must say the slot could not complete rather than that it decided nothing.
4. **close-then-open** — the three failure branches `track1_switch` already specifies: stop
   cancel fails → abort before closing; close not verifiably FILLED → abort, do not open; open
   fails after the close filled → **the account is flat and the book must record it**.
5. **no duplicate same-symbol order** — `SUPPRESS_SAME_SLEEVE` and `SUPPRESS_SAME_SYMBOL`
   already exist in the book; the executor must never see a second order for a symbol it holds.
6. **no order when the upstream refused** — explanation missing, freshness stale or admission
   rejected must each independently prevent an order, asserted one at a time.
7. **an armed run and a shadow run over the same window produce the same DECISIONS** — the
   strongest test available, and the one that proves the seam is only at the broker.

---

## 8. Is any legacy code safely reusable?

| | reusable? | why |
|---|---|---|
| close-then-open shape | **already done** | `track1_switch.close_then_open` is Track 1's own extraction. Its docstring records that Stage 2D examined reusing `_handle_rollover` directly and said no — that function is gated on a roll date and assumes same symbol, same direction, same quantity, different month. What transferred was the shape |
| order placement | **yes** | `IBKRBroker.send_order` / `place_stop` / `cancel_order` are broker-level and instrument-agnostic, and `send_order` already resolves the tradable symbol correctly |
| **reconciliation** | **no** | `runner.py`'s reconcile is written against `live_positions.json` — the first entry in `run_live_day_track1.LEGACY_PATHS`, the list of files this route must never write. Reusing it would reintroduce exactly the legacy state assumptions the route was built to leave behind |
| stop *state* | **no** | same reason: the legacy stop bookkeeping lives in the legacy position file |

So: reuse the broker methods, reuse Track 1's own switch primitive, and write the reconciliation
against `live_positions.track1.json` from scratch.

---

## 9. The two open questions I am not going to paper over

**Ordering between the ledger row and the order.** `observe_live_slot` writes the slot's row and
returns. If an order is sent *before* the row is written, a crash in between leaves a position
nobody recorded; if *after*, a crash leaves a row claiming a decision that was never placed.
Legacy answers this with "emit before act" (`track1_switch` does the same), which implies the
row comes first and must be able to say *intended* as distinct from *filled*. The ledger schema
has no such field today.

**Reconcile on startup.** Nothing yet reads `live_positions.track1.json` back and compares it
with the broker before the first slot of a session. Until that exists, a paper run that is
restarted mid-session cannot know what it holds — and that is the failure mode B1 exists to talk
about, arriving from inside the route rather than from legacy.

Neither is hard. Both need deciding **before** code, not during it.

---

## Files

```text
global_index/track1_paper_order.py                          NEW — pure mapping + the spec.
                                                            No broker, no ib_insync, no
                                                            placeOrder. Not wired into the
                                                            scheduler or the runner.
scratch/test_track1_stage5t_paper_broker_path_20260825.py   20 tests
scratch/track1_stage5t_paper_broker_path_audit_20260825.md / .json
```

`track1_paper_order` is imported by nothing in production. It is a specification with one
working wall, and it can be deleted without changing a single runtime behaviour.

Regression: **218 passed, 1 skipped** across 7 suites.

---

## The direct answers

- **Current behaviour of `--allow-orders`:** refused unless every gate is open; if it were open,
  the scheduler's slot path ignores it entirely and the replay path records `armed` while still
  holding `NoOrderBroker`.
- **Exact missing code:** an implementation of `Track1OrderExecutor` over `IBKRBroker`, its
  construction in the slot path under the gate, the mapping call site between admission and the
  ledger row, and reconciliation against `live_positions.track1.json`.
- **What must be built before paper:** that executor, the seven failure-branch tests, and a
  decision on the two ordering questions above.
- **What must never change from shadow:** the eight items in `MUST_BE_IDENTICAL` — frame,
  history symbol, freshness, sleeve rules, sizing basis, admission and caps, explanations,
  checkpoint and params hash.
- **Accidental order path today:** **none.** Four gates, a broker that raises, a slot path that
  cannot see the gate, and no order-placing call anywhere in the route.
