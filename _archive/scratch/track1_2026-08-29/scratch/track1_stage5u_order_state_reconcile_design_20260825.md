# Stage 5U — order state and startup reconcile, resolved into contracts

**2026-08-25, 00:35–00:45 ET ·** all Track 1 windows closed (NKD opens 01:10) · no scheduler or
backend restarted · **no IBKR connection** · no order · no confirmation file ·
`TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` anywhere · no parquet, CSV or runtime
evidence written · the new module is imported by nothing · no commit.

---

## Verdict: **READY_FOR_PAPER_EXECUTOR_IMPLEMENTATION**

Both Stage 5T questions are resolved into pure, tested contracts — 24 tests, no broker, no
socket. Two prerequisites are named below; neither is an ambiguity, both are work.

---

## A. The order state machine

### Why the window ledger cannot own it

`window_ledger._write` catches every exception and disables the channel for the process. Its
own comment says why:

> It must never escape into a trading path — the ledger records availability, it does not
> enforce it.

That is exactly right for **evidence** and exactly wrong for a **write-ahead log**. If the
ledger owned "an order is about to be sent", a failed write would mean an order goes out with
no record of intent — the one thing a write-ahead log exists to prevent. A test parses `_write`
and requires that it still swallows, so if that contract ever changes someone re-reads this
decision rather than inheriting it.

So three files, three contracts:

| file | contract | on write failure |
|---|---|---|
| `window_coverage/*.jsonl` | **evidence** — unchanged by paper | disable the channel, keep trading |
| `orders/*.jsonl` *(new)* | **intent** — append-only write-ahead log | **abort the order before it is sent** |
| `live_positions.track1.json` | **belief** — what the route holds | advances only on a CONFIRMED fill |

### The six states

```text
INTENDED    written BEFORE any broker call. The book admitted it; nothing sent.
SUBMITTED   handed to the broker. The outcome is not known and must not be assumed.
FILLED      confirmed complete fill.
PARTIAL     confirmed fill smaller than requested.
REJECTED    the broker definitively refused. Nothing is held.
UNKNOWN     the broker did not answer, or answered unusably.
```

`REJECTED` and `UNKNOWN` are separate on purpose. **"No" and "I could not hear you" are
different facts**, and treating the second as the first is how a filled order becomes a
position nobody believes in.

Allowed transitions are a table, and an impossible history is **reported, not smoothed**:

```text
INTENDED  -> SUBMITTED | REJECTED | UNKNOWN
SUBMITTED -> FILLED | PARTIAL | REJECTED | UNKNOWN
UNKNOWN   -> FILLED | PARTIAL | REJECTED        (resolvable only by asking)
PARTIAL   -> FILLED | REJECTED                  (the remainder resolves one way or the other)
FILLED, REJECTED -> nothing
```

`INTENDED -> FILLED` is **not** a legal transition. That is the whole of question A in one
line: intent can never be mistaken for a fill, because the journal will not accept the history.

### What makes a window "decided" — unchanged

`classify_slot_row` reads `decided` and `candidates`, and it must keep meaning **the route
reached a decision**. A test parses it and requires that it mentions no order word at all.

If `decided` ever came to depend on a fill, a broker outage would read as the strategy having
stopped deciding — and the shadow evidence and the paper evidence would stop being comparable,
which is the premise the Stage 5S readiness gate rests on. Shadow behaviour is therefore
**bit-identical** under this design: nothing in the ledger changes.

## Crash recovery, per state

| crashed in | what it means | what restart does |
|---|---|---|
| `INTENDED` | nothing was sent | the candidate did not trade; book unchanged; continue once reconcile says MATCH |
| `SUBMITTED` | outcome unknown | ask the broker — `get_order_status` if an id was recorded, else compare positions. **Block entries, allow exits** |
| `UNKNOWN` | same, for the same reason | **Block entries, allow exits** |
| `PARTIAL` | part of it happened | book records the **filled** quantity only, never the requested one; remainder flagged; entries blocked |
| `FILLED` | it happened | the book advances — the only state that may add a position |
| `REJECTED` | nothing is held | the reserved cap is released and the refusal is recorded as a divergence from the shadow book |

**close FILLED + open FAILED** is already handled by `track1_switch`: it emits
`OPEN_FAILED_FLAT` and calls `persist_flat`. If that callback raised, `persisted=False` and the
book still claims the old position while the account is flat. On restart that is a MISMATCH —
book says held, broker says flat — and the repair is to **believe the broker about existence**.

---

## B. Startup reconcile

### Three answers, never two

`IBKRBroker.get_positions()` reads until two consecutive reads agree and, if they never do,
**warns and returns the last one**. The caller cannot tell a settled truth from a guess.

That is the third time in this project a status reader has had no way to say "I do not know",
and the first one — `scheduler_processes()` returning `[]` — cost six entry slots. So:

```text
MATCH      every position agrees; nothing unattributable
MISMATCH   a definite disagreement, or a journal history that cannot have happened
UNKNOWN    positions never settled, or an order is still SUBMITTED / UNKNOWN
```

**Entries are blocked on MISMATCH *and* on UNKNOWN. Exits are allowed in all three.** Refusing
to *reduce* exposure while the book is confused is the wrong failure direction: a stop that
cannot be placed is worse than one placed against a position that turns out to be flat.

### What it compares

Only `instrument`, `direction`, `contracts`. **Not cluster** — `get_positions` sets
`cluster="UNKNOWN"` because IBKR has no cluster concept, so comparing it would produce a
mismatch every time. Both sides net to a signed quantity per contract, the convention
`ib.positions()` already uses, so a LONG 1 against a SHORT 1 cannot read as agreement.

An instrument the route does not trade **blocks**. The real case is a leftover full-size NKD
position: `_to_runner` deliberately no longer maps NKD back to MNKD, so it arrives under a name
the book does not use. It must not be quietly adopted as MNKD — that is how the ten-times-size
incident would be re-inherited.

### The B1 constraint, and why it is the argument for closing B1 first

While one IB Gateway login serves both routes, `get_positions()` returns the **net per contract
for both**. The strongest available statement is:

```text
broker_net(contract) == track1_net(contract) + legacy_net(contract)
```

which detects disagreement but **cannot attribute it**. And there is a hole under it, now
asserted rather than described:

```text
reality:  Track 1 holds LONG 1, legacy holds LONG 1  ->  broker nets LONG 2
belief:   Track 1's book claims LONG 2, legacy's claims LONG 0
result:   MATCH, entries ALLOWED — while Track 1's book is wrong by a whole contract
```

Equal-and-opposite errors cancel and nothing in this design can see them. With a dedicated
account the same broker truth is caught immediately and entries are blocked.

*(The first version of that test asserted the opposite and passed, because the case it built
was one that IS caught. The difference between "reconcile has a limitation" and "reconcile
covers it" is worth getting right, so it now asserts the hole.)*

**So B1 is not merely a decision to record before paper — it is the thing that decides whether
reconcile can attribute a mismatch at all.**

---

## What the broker offers, and what is missing

Available on `IBKRBroker` today:

```text
get_positions()        net per contract, cluster="UNKNOWN", retry-until-stable
get_equity()
get_working_stops()    /  has_working_stop(inst, direction)
get_order_status(id)
cancel_order(id)   place_stop(...)   send_order(order) -> Fill
```

**Missing, and needed:**

1. **`get_open_orders()`** — there is no way to ask "what of mine is still working". Without
   it, a `SUBMITTED` with no answer can only be resolved through `get_order_status(order_id)`,
   which needs an id the journal can only have if the broker already returned one. That is the
   exact gap a crash lands in.
2. **an executions / fills lookup** — to distinguish "it never filled" from "it filled and I
   missed the confirmation" without inferring it from positions.

Until (1) exists, the design's answer is: the journal writes `SUBMITTED` with a **client-side
idempotency key generated before the call**, and reconcile resolves by comparing positions
(existence), not by order id. That works, and it is weaker than it should be.

---

## Is legacy B3/B4 reusable?

**No, and for the same reason both times.** Legacy B3 reconcile and B4 stop repair are written
against `live_positions.json` — the first entry in `run_live_day_track1.LEGACY_PATHS`, the list
of files this route must never write. Reusing them would reintroduce exactly the state
assumptions the route was built to leave behind.

What **is** reusable is a rule rather than code: `get_positions`' own docstring says B3 compares
only `inst/direction/contracts`. That comparison is right and is what `reconcile` implements.

The minimal Track 1-specific reconcile is the function written in this stage: ~60 lines, pure,
no broker, takes three lists and returns a tri-state verdict.

---

## What is pure and tested vs still unimplemented

**Built and tested — 24 tests, no broker, no socket** (`global_index/track1_order_state.py`):

```text
ORDER_STATES / TERMINAL / UNRESOLVED / ALLOWED_TRANSITIONS
transition_allowed(old, new)
OrderRecord                 flat and scalar — it is read back after a crash
resolve_journal(records)    -> final states + impossible histories, reported not repaired
unresolved_orders(records)
Position / ReconcileResult
reconcile(book, broker, *, broker_settled, journal, legacy_book, shared_account)
CRASH_RECOVERY              one entry per state, walked by a test
SWITCH_FLAT_RECOVERY
```

**Still unimplemented:**

- the order journal writer, with its fail-closed contract
- `Track1OrderExecutor` over `IBKRBroker` (Stage 5T specified it)
- `get_open_orders()` and an executions lookup on the broker
- the call site: reconcile before the first slot of a session, then per-slot order handling
- `live_positions.track1.json` read-back and repair

---

## Tests required before `Track1OrderExecutor` is written

Existing, from Stages 5T and 5U — **44 tests**. Still required:

1. the journal is **fail-closed**: a write that raises aborts the order before it is sent.
2. an order is never sent without an `INTENDED` line already durable on disk.
3. `SUBMITTED` with no answer → reconcile returns UNKNOWN → entries blocked, exits allowed.
4. partial fill books the filled quantity only and flags the remainder.
5. rejected fill releases the reserved cap and records a divergence.
6. disconnect mid-order leaves a state the next process can reconcile.
7. close-then-open's three branches, including `persist_flat` raising.
8. no duplicate same-symbol order.
9. no order when explanation, freshness or admission refused — each asserted alone.
10. **an armed run and a shadow run over the same window produce the same decisions.**

---

## Files

```text
global_index/track1_order_state.py                              NEW — pure. No broker, no
                                                                ib_insync, no connection.
                                                                Imported by nothing; a test
                                                                asserts that.
scratch/test_track1_stage5u_order_state_reconcile_20260825.py   24 tests
scratch/track1_stage5u_order_state_reconcile_design_20260825.md / .json
```

Regression: **156 passed, 1 skipped** across five suites.

---

## The direct answers

- **Ledger/order state machine:** six states in a separate fail-closed journal;
  `INTENDED -> FILLED` is not a legal transition; the window ledger is untouched and `decided`
  keeps meaning "the route reached a decision".
- **Crash recovery:** table above — nothing sent on `INTENDED`; ask the broker on `SUBMITTED`
  and `UNKNOWN`; book the filled part only on `PARTIAL`; believe the broker about existence
  after a failed switch.
- **Startup reconcile contract:** three answers; compares instrument/direction/contracts as a
  signed net; unrecognised instruments block; unsettled reads are UNKNOWN, not flat.
- **Blocks entries vs allows exits:** MISMATCH and UNKNOWN both block entries; exits are
  allowed in all three verdicts.
- **Pure and tested vs unimplemented:** the state machine and the reconcile rule are built; the
  journal writer, the executor, two broker methods and the call sites are not.
- **Accidental order path today: none.** Four gates hold, `run_shadow` still builds
  `NoOrderBroker`, the scheduler's slot path takes no order gate, and neither new module is
  imported by anything in production.
