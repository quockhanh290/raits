# Stage 5W — the paper executor skeleton, and the three walls around it

**2026-08-25, 04:00–06:10 ET ·** no order · no broker connection · no confirmation file ·
`TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` · scheduler and backend untouched
(pid 48604 / 35352, the same processes as before this stage) · no runtime evidence written ·
no ledger row edited · no parquet touched · no commit.

---

## Verdict: **READY_FOR_PAPER_EXECUTOR_WIRING**

The skeleton exists, it is fail-closed at every step that could reach a broker, and it is
provably unreachable from production. What is **not** ready is the wiring itself, and the
reason is not this module — it is that the two gates in front of it are still shut and one
broker capability is still missing. Both are named below with the measurement behind them.

---

## What was built

```text
global_index/track1_paper_executor.py          NEW · 265 lines · imported by nothing
global_index/track1_paper_order.py             + tradable_symbol()
```

The executor is assembled from the three pure pieces the earlier stages built and adds no
vocabulary of its own:

| stage | module | what it contributes |
|---|---|---|
| 5T | `track1_paper_order` | candidate → `broker.Order`, and the refusals around it |
| 5U | `track1_order_state` | the state machine and the reconcile verdicts |
| 5V | `track1_order_journal` | the fail-closed write-ahead log |

One operation is implemented — `open_position`. The other three (`close_position`,
`place_protective_stop`, `switch_same_symbol`) are deliberately still the refusing stubs from
Stage 5T. Building the entry path first is the smallest thing that proves the *shape*; adding
three more before anyone has seen the first one run would be three more things to unwind.

### The order of operations, and what each step buys

```text
1. refuse unless the cap gate said TAKE
2. build the Order            refuses on identity drift, bad qty, missing ref_day
3. journal INTENDED           durable, fsynced, RAISES on failure
4. journal SUBMITTED          BEFORE the broker call, RAISES on failure
5. broker.send_order(...)
6. journal the outcome        FILLED / PARTIAL / REJECTED / UNKNOWN
```

Steps 3 and 4 both precede step 5 and both raise, so **an order can only reach a broker after
the intent to send it is durable on disk.** A crash anywhere leaves a journal a restart can
read: nothing after INTENDED means the broker was never reached; anything stuck at SUBMITTED
means ask before doing anything else.

The most important of those claims is proved from *inside* the broker call — the fake broker
reads the journal at the moment it is invoked and the test asserts the two rows are already
there. A test that checked the file afterwards would pass under either ordering.

---

## The six questions

### 1 · What does the executor need from the broker, and what is missing?

Named as data in the module rather than discovered at runtime:

| | methods | present on `IBKRBroker` |
|---|---|---|
| required | `send_order`, `get_positions`, `get_order_status`, `cancel_order`, `place_stop` | yes — all five |
| still missing | `get_open_orders`, `get_executions` | **no — neither** |

Construction refuses if any *required* method is absent, so an executor that cannot place or
query an order cannot exist to discover that later.

The two missing ones matter for exactly one thing: resolving an `UNKNOWN`. The interim answer
is written into the module as a value, not left in someone's memory:

> resolve by comparing broker **positions** against the book, keyed by the client-side
> idempotency key written before the call — **not** by order id, because a crash inside
> `send_order` can leave an order with no id ever returned.

That is genuinely weaker than asking the broker what orders are open, and it is labelled as
weaker. A test asserts `IBKRBroker` still lacks both methods, so **the day someone adds one,
that test fails and the interim answer can be retired** rather than quietly outliving its
reason.

There is a second, smaller absence worth naming: **`broker.Fill` carries no order id at all.**
Checked, not assumed. That absence is the whole reason the idempotency key is computed before
the call — it is the only handle a restart has on an attempt whose outcome nobody saw.

### 2 · How does an ambiguous broker answer get recorded?

As `UNKNOWN`, never as `REJECTED`, and the exception is re-raised rather than swallowed.

"The broker said no" and "I could not hear the broker" are different facts. A filled order
recorded as rejected becomes a position nobody believes in — which is the same shape as the
2026-08-14 defect, arriving from the other side.

| broker says | recorded |
|---|---|
| `FILLED` | FILLED |
| `PARTIAL` | PARTIAL |
| `CANCELLED` / `FAILED` / `REJECTED` | REJECTED |
| anything else, including empty, `PendingSubmit`, `ApiCancelled`, `None` | **UNKNOWN** |
| the call raised | **UNKNOWN**, then the exception propagates |

An UNKNOWN order is reported to a restart as unresolved; a FILLED one is not.

### 3 · What advances the book, and what stops it advancing early?

**The executor never touches the book. Not a guarded write — none at all.**

There is no writer for `live_positions.track1.json` anywhere in the module, and a test proves
it by AST: no `open()`, no `write_text`, no `dump`. The executor returns the `Fill` and the
caller advances the book, only on a confirmed fill. That is the strongest available form of
"no mutation before a confirmed fill", because it is a property of the file rather than a
discipline someone has to keep.

Reading the book back **fails closed, and this is where I got it wrong first.** My initial
reader asked for a `contracts` key. The real writer — `track1_bootstrap.snapshot_book` — spells
it **`qty`**. A reader that refused every genuine book while raising a fail-closed exception is
the worst of both: it looks safe and it never works. It now reads the writer's key, and a test
asserts against the writer's source so the two cannot drift apart silently.

While fixing that, two more refusals earned their place. `live_positions.json` and
`live_positions.track1.json` are the *same shape*; only the route stamp differs. So a book
stamped with another route, or another schema version, is refused rather than read as a valid
answer to the wrong question.

And the distinction that matters most: a **missing** book is an empty book and is fine — the
route has held nothing yet, and it currently holds nothing (the file does not exist). A book
that exists and cannot be parsed is **not** an empty book. That is the
`scheduler_processes() -> []` mistake, in the one place where it would put size on the wrong
side.

### 4 · Where would the call site be, and what must it look like?

`run_shadow` in `run_live_day_track1.py`, at line 1062, where it constructs `NoOrderBroker()`
unconditionally today. That single line is the seam, and nothing else in the run path would
move.

The shape it must have, in order:

```text
gate armed?          -> otherwise keep NoOrderBroker, which is today's behaviour
reconcile at startup -> MISMATCH or UNKNOWN blocks ENTRIES; exits always allowed
per admitted decision:
    fill = executor.open_position(decision, ref_day=..., slot_id=...)
    if fill confirms:  the CALLER advances live_positions.track1.json
```

Not yet written, deliberately. Writing the call site is the step that makes orders possible,
and the two gates in front of it are still shut.

### 5 · Do shadow and armed decide the same thing up to the broker boundary?

**Yes, and it is proved structurally rather than by running one day twice.**

A two-arm run would show the two modes agreed *on the day it was run*. The structural proof
covers every day:

- inside `run_shadow`, the derived mode is read **exactly once** after it is assigned, and
  that single read is the `mode=` argument to `emit_explanations` — a label on a recorded
  explanation. It reaches no gate, no rule, no cap. Proved by walking the function's AST.
- both live modes sit in `FRESHNESS_BINDING_MODES`, so arming cannot loosen the freshness
  gate. `decision_mode_for("live", …)` returns `shadow_live` unarmed and `armed` armed, and
  `{shadow_live, armed} ⊆ FRESHNESS_BINDING_MODES`.

So arming changes what a run is *called* and nothing that decides. Both facts are pinned by
test, and mutations M13 and M14 turn each of them red.

### 6 · What actually stops this reaching production today?

Three independent walls, each measured, each with a test — and none of them is "we remembered
not to call it":

1. **It refuses to construct without an armed gate.** `production_gate()` reads the real
   blocker table; it answers `allow_orders=False`, and the executor refuses it by name.
2. **Nothing imports it.** An AST scan of `global_index/`, `monitor/` and `futures/`.
3. **The slot path has no order argument.** `observe_live_slot` takes no gate, so there is no
   argument by which a scheduled slot could reach this even if the other two changed.

Wall 2 is where mutation M11 found a real hole in my own test: it checked `ImportFrom.module`
but not the imported *names*, so `from global_index import track1_paper_executor` — the most
natural import in this repo — sailed straight through while the test stayed green. Both halves
are checked now.

---

## Measurements, not assertions

| claim | how it was measured |
|---|---|
| `Fill` has no order id | `dataclasses.fields(Fill)` — checked, not assumed |
| the book's quantity key is `qty` | read from `snapshot_book`, and pinned against its source |
| the book file does not exist | `ls` — the route has never held a position |
| `IBKRBroker` lacks both lookup methods | `hasattr` on the class, pinned so it fails when fixed |
| arming reaches only the explanation writer | AST walk of `run_shadow` |
| the scheduler passes no `--allow-orders` | AST string literals, **not** a substring scan |
| `orders_possible=False` | `monitor/ops.py status`, unchanged before and after |

That sixth row deserves a note. A plain substring check **fails** here, and correctly so:
`run_scheduler.py` both documents and comments that it passes no such flag, so a search for
the string matches the prose forbidding the thing. This is the third stage in a row where a
substring scan matched its own prohibition. Only a string *literal* in an argv counts.

And the flag's own **definition** is not a caller. `run_live_day_track1` owns the argparse
argument; the claim under test is that nothing hands it over. That file is checked separately,
pinned to the one shape it is allowed to have: exactly one literal, inside exactly one
`add_argument` call.

---

## Tests and mutations

**52 tests**, and **18 mutations, all red.** Most mutations do not remove a check — they make
the module fail **open**, which is the only direction that matters for a file that could one
day reach a broker.

| | mutation | caught by |
|---|---|---|
| M1 / M1b | the armed-gate demand removed | construction, and against the real blocker table |
| M2 | SUBMITTED written after the broker call | the spy inside `send_order` |
| M3 | an unclassifiable answer folded into REJECTED | the five unrecognised statuses |
| M4 | a raising broker swallowed | the propagation test |
| M5 / M5b | the executor treats a journal refusal as best-effort | first write, and second |
| M6 | `read_book` fails open | the unreadable-book test |
| M7 / M7b | the executor advances the book | the file-unchanged test, and the AST scan |
| M8 | the journal records the HISTORY symbol | the MNKD identity test |
| M9 | the key recomputed per record | the same-key test |
| M10 | reconcile drops unparsable lines | the corrupt-journal test |
| M11 | production imports the executor | the import scan |
| M12 | the scheduler passes `--allow-orders` | the argv literal scan |
| M13 | ARMED drops out of the freshness-binding set | the binding test |
| M14 | the mode label reaches a second consumer | the AST single-read test |
| M15 | `NoOrderBroker` replaced on the run path | the broker-construction test |

### Three mutations that were wrong before they were right

Worth recording, because in each case the harness was lying rather than the code.

**M5 patched `J.append` — the same object the test patches.** The test's patch wins, so the
mutation had no effect and stayed green while proving nothing. The question is whether the
*executor* treats a refusal as fatal, so the mutation had to go on the executor.

**M9 patched `idempotency_key`.** The executor calls it **once** and reuses the value, so a
drifting stub changes nothing. The faithful break is to make the executor recompute per record.

**M11 was faithful and the test was wrong** — see wall 2 above.

An unfaithful mutation is worse than no mutation: it produces a green line that reads as proof.
Each of the three is now commented in the harness with why the obvious patch point is the wrong
one.

---

## What this stage changed that was not the main task

Three test files needed updating, all for honest reasons, none by widening:

**`test_track1_stage5u_…` and `test_track1_stage5v_…`** asserted their modules were imported by
nothing. The executor now imports all three, so that assertion is no longer the right one. What
must stay true is that the *head* of the chain is imported by nothing, which keeps the whole
chain unreachable — so both suites now assert exactly that, and both were upgraded from
substring scans to AST while I was there.

**`test_track1_stage5v1_…`** pinned the live NKD ledger as a *subset* of two refusal codes. The
window has since **closed**, and the 22nd row — the 02:55 `too_late` — arrived after Stage 5V-1
ran. Since the distribution is now final it can be pinned exactly, which is strictly stronger:

```text
partial_coverage,stale   20
stale                     1     ← the span fix live, the staleness fix not yet
too_late                  1     ← benign, pre-existing, classified observed_window_shut
                         ──
                         22     21 hard refusals, which is why this window cannot pass
```

Stage 5V-1's report said "nineteen slots"; the ledger says twenty-one hard refusals. The
narrative was written mid-window and undercounted. The number in the test is now the measured
one and cannot drift again.

---

## Regression

| suite group | result |
|---|---|
| 5S / 5T / 5U / 5V / 5V-1 / 5Q-9 / 5R-0 / 5W (8 files) | **234 passed** |
| 5Q-7 / 5Q-8 / 5F / schedule-status mirror (4 files) | **95 passed, 1 skipped** |
| Stage 5W mutations | 18 red, 0 green |
| Stage 5V mutations (tests changed under them) | 10 red, 0 green |

No Stage 4 reproduction run this time, deliberately: this stage adds a module the strategy
path does not import and touches no gate, no rule and no sizing. The reproduction is the check
for changes that could move a decision, and mutation M14 is the evidence that this one cannot.

---

## Runtime, before and after

```text
scheduler_pids=[48604]          unchanged — not restarted
backend_pids=[35352]            unchanged
track1_mode=track1-only-shadow
track1_stop_trading=False  confirmation=False  track1_orders_approved=False
track1_blocking=['B1_broker_account_or_legacy_retirement', 'PAPER_SHADOW_EVIDENCE']
orders_possible=False
```

And nothing was created: `global_index/track1_runtime/orders` does not exist, and neither does
`live_positions.track1.json`. Every test that writes a journal writes it under `tmp_path`.

---

## What remains before the wiring can happen

| # | what | why it is not this stage's to close |
|---|---|---|
| 1 | `PAPER_SHADOW_EVIDENCE` — 0 judgeable days | needs 5 clean days. The first NKD window that can be judged on the fixed gate is **2026-08-26 01:10 ET** |
| 2 | `B1_broker_account_or_legacy_retirement` | a user decision about the account, not a code change |
| 3 | `get_open_orders()` / executions lookup on `IBKRBroker` | the interim answer works and is labelled weaker; the test fails the day it is fixed |
| 4 | the call site in `run_shadow` | one line, and it is the line that makes orders possible |
| 5 | `close_position`, `place_protective_stop`, `switch_same_symbol` | still Stage 5T's refusing stubs |

Item 1 is the near one. `spy_refresh_pm` fires for the first time today at 16:20 ET, so
Tuesday's freshness should pass — but that is a different gate and it has not yet been
observed working.

---

## Files

```text
global_index/track1_paper_executor.py                       NEW
global_index/track1_paper_order.py                          + tradable_symbol()
scratch/test_track1_stage5w_paper_executor_20260825.py      52 tests
scratch/track1_stage5w_mutations_20260825.py                18 mutations, all red
scratch/test_track1_stage5u_order_state_reconcile_20260825.py   wiring test -> AST
scratch/test_track1_stage5v_order_journal_20260825.py           wiring test -> AST
scratch/test_track1_stage5v1_intraday_causality_20260825.py     ledger pinned exactly
TASK.md                                                     + the pending seam audit
```
