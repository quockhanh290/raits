# Stage 5ZN — the stop gets written down, the lifecycle gets verbs, the book survives the day

**2026-08-26, ET 03:20–04:20.** No orders · no confirmation file · `TRACK1_ORDERS_APPROVED`
unset · no `--allow-orders` · **nothing restarted** · no runtime file changed · no
`IBKRBroker` constructed anywhere · no production order journal written · no strategy, rule,
cap or backtest-identity change.

```text
UTC 2026-08-26 07:24 · ET 2026-08-26 03:24 EDT · Calgary 2026-08-26 01:24 MDT
```

---

## The eleven answers

| | |
|---|---|
| 1. runtime/live file changed? | **no** |
| 2. orders still impossible? | **yes** — three blockers, no confirmation file, no orders directory |
| 3. where does the planned stop live? | on a `PlannedStop`, on `OrderRecord`, and on the journal row (§3) |
| 4. can an admitted entry be sendable without one? | **no** — refused in two places before anything could send |
| 5. close / stop / switch — built or stubs? | **built**, as intent-only. They journal and refuse; the send step is not built |
| 6. does the route carry a cross-day book safely? | **yes now** — and it did not before (§5) |
| 7. what stays unverified until paper? | one thing: that a broker actually holds the stop (§7) |
| 8. legacy unchanged? | **yes** — `Order` and `Fill` untouched, asserted |
| 9. strategy identity unchanged? | **yes** — hashes identical across the new path |
| 10. next shadow window READY? | **yes** |
| 11. is only evidence/operator/paper-proof left? | **yes for Track 1's own code** — with one honest caveat (§9) |

---

## 1. Baseline, and a live confirmation of the previous stage

```text
scheduler pid 18096   backend pid 30604   track1-only-shadow   orders_possible False
blocking  B1, PAPER_SHADOW_EVIDENCE, REGIME_LABEL_VERIFICATION
book      live_positions.track1.json — route track1_candidate, 0 positions
journal   global_index/track1_runtime/orders/ — ABSENT; no order has ever been journalled
preflight the operator's seven days; 2026-08-26 absent, as it must be until 13:45 ET
```

The 02:55 ET NKD close ran between the last stage and this one, and it is worth recording
because it is the first live proof of 5ZK:

```text
roska4_swing  4 entries   global_nkd  1 entry   TOTAL 5
global_nkd 2026-08-26 → PASS
  checkpoint: route ok, 5 entr(y/ies) through ['2026-08-24'] (2 days behind),
              book cut 2026-08-26, 0 open position(s) matched
```

Five real checkpoint entries where there had only ever been zero, and the **second** Track 1
window ever to pass its audit — the first with a checkpoint anything could resume from.

## 2. What was actually missing

`Candidate` carries `stop_price`. The strategy works it out, and it survives all the way
through admission. `candidate_to_order` then builds an `Order` that has nowhere to put it, and
`OrderRecord` had nowhere either.

So the planned stop reached the edge of the order path and was dropped there. The protective
stop was placed later by the safety sweep — a different process, a different schedule — and
**nothing anywhere held both the price that was intended and the price that was placed.**
Side, size, price, bracket behaviour, an abandoned stop still sitting on the book: every one of
those questions needs two numbers, and there was only ever one.

An abandoned stop left by a close on 2026-08-10 filled and opened a position the opposite way.
That is why a stop with no record is an accounting hole rather than untidiness.

## 3. The planned stop

`global_index/track1_planned_stop.py`. A `PlannedStop` carries instrument, tradable symbol,
direction, quantity, stop price, stop type, stop distance, entry price, session day, sleeve,
slot id and params hash — every field there to answer a question a live working stop will
raise.

**It never computes a stop.** `from_candidate` copies the price the strategy already decided.
A second implementation beside the one that trades is how "the planned stop" and "the stop the
engine meant" quietly become two numbers, and the plan would be the one that looks right. A
test asserts it by AST: the only arithmetic in the whole function is the two subtractions that
make `stop_distance`, and nothing else.

Six conditions refuse, each with its own code: no stop price, a stop that is not a number, NaN,
zero or absent quantity, and — the one worth naming — **a long whose stop sits above its
entry**. That is not a stop, it is a target, and it would trigger the moment it reached a
broker. Caught here rather than there.

`assert_sendable` runs between building the order and doing anything with it, and refuses a
missing plan, a plan for a different instrument, and a plan covering fewer contracts than the
order — *a partly-protected position is not a protected one*.

`plan_entry(candidate, …)` returns `(Order, PlannedStop)` and is the pairing an entry must go
through. `candidate_to_order` is untouched, because it is called from places that want an order
and nothing else.

The fields were appended **last** on both `OrderRecord` and `JournalRecord` with defaults, so
every row written before this stage still reads back and every positional caller still
constructs — both asserted. `Order` and `Fill`, which the legacy route shares, gained nothing.

## 4. The lifecycle verbs

Three were unbuilt. All three exist now, and all three are **intent-only**: they run every
refusal, write the INTENDED journal row, and return an `Intent` carrying `sent: False`. The
send step is not built, and that asymmetry with `open_position` is the point of this stage
rather than an omission — a method that *could* send is a method somebody can call.

| verb | refuses when | produces |
|---|---|---|
| `close_position` | the book does not exist; the book holds no such instrument; the row carries zero contracts | one CLOSE intent, `reduces_exposure: True` |
| `place_protective_stop` | no plan travelled with the position; the plan carries no usable price | one STOP intent carrying price, type and distance |
| `switch_same_symbol` | anything the close leg refuses; the two legs name different symbols | **two** intents, journalled separately, close first |

Every refusal happens **before** the journal row exists, so a refused operation leaves no trace
a later reader could mistake for an attempt — asserted for each.

The switch matters more than its size. `track1_switch` is imported by nothing and calls
`send_order` at two sites with no journal at all, so if it were ever wired, two orders would
leave one record between them or none. The close leg is intended first, because a switch that
opened before it closed would double the exposure on that symbol for the length of the gap.

Structurally proven: none of the three so much as mentions `self.broker`, checked by AST; the
executor imports no `ib_insync` and names no `IBKRBroker`; the slot path still builds
`NoOrderBroker`, which raises on send, cancel and equity.

## 5. A real defect, found by building on it

`track1_paper_executor.BOOK_PATH` was `global_index/live_positions.track1.json` — **a path the
book has never occupied.** Every other component uses the repository root, and that is where
`track1_bootstrap.write` puts it.

Not cosmetic. `read_book` treats a missing file as an empty book, which is right for a route
that has held nothing — so that constant made `reconcile_at_startup` compare an *always*-empty
book against the broker and conclude the route was flat whatever it actually held. That is
"resume flat against a book that is not", in the one object built to prevent it. It never fired
because nothing imports the executor.

Corrected, and now **read from `track1_slots`** rather than restated, so the two cannot drift
again.

**A test was green because of it.** Stage 5X's `test_37_the_live_book_really_is_absent_right_now`
asserted the book was absent, and it passed by asserting something true of a file nobody
writes. Rewritten to what it meant: the constant matches the route's own, and the book — which
the first complete window wrote on 2026-08-25 — exists and is flat, which is a different fact
from not existing.

## 6. The cross-day book

`write_route_checkpoint` synthesised `positions: []` whenever no book state was handed in,
which is every production call. Harmless while the route holds nothing, and exactly wrong the
moment it does: a window close would overwrite a book holding a position with one claiming
none, and the checkpoint written beside it would agree.

Now the existing book is **read and carried forward**, restamped for this cut. Three outcomes:

```text
no book        a flat one is created,  book_carried_from: None
book exists    positions carried,      book_carried_from: <path>, positions_carried: n
unreadable     the write is REFUSED and the file is left exactly as it was
```

The last is the one that matters. *"I could not read what I hold"* answered as *"I hold
nothing"* is the shape that erases a real position, and a window close that did it would be
unrecoverable. A book stamped with another route is refused for the same reason.

Intending a close does not move the book — asserted. Only a confirmed fill can, and there has
never been one.

Restart classification already existed and is now exercised against the real book path:
MATCH, MISMATCH, and UNKNOWN — with UNKNOWN blocking entries, allowing exits, and never
becoming MATCH.

## 7. What paper, and only paper, can settle

One thing: **that a broker actually holds the stop that was planned.** Price, quantity, side,
whether it survives a close, whether an abandoned one is left behind. Every part of that needs
an order to exist first, and none does.

The report says exactly that and refuses to blur it:

```json
"planned_stop_ready": true,
"verbs_send_orders": false,
"book_carried_across_days": true,
"broker_stop_verified": false,
"broker_stop_reason": "no Track 1 order has ever been sent, so no stop has ever been
                       placed for one to be compared against; this needs paper"
```

*Planned stop ready* and *broker stop verified* are separate facts and are never merged: the
first is about a record, the second about an order sitting on an exchange.

## 8. Tests

**52 tests**, `scratch/test_track1_stage5zn_planned_stop_lifecycle_20260826.py`. All fifteen
items the brief lists, plus what the code suggested. The fake broker **raises** on `send_order`
and `place_stop`, so a send would fail loudly rather than pass quietly.

Three worth naming: the AST check that the planned-stop module does no arithmetic beyond the
distance; the check that each new verb never touches `self.broker`; and the check that a
refused operation leaves the journal empty.

### A pin I nearly weakened, and did not

Six tests across five suites assert that **nothing which runs imports the order path** — part
of the safety argument that there is no route from the scheduler to a broker. My first version
of the reporting block imported the executor to read `hasattr` for a panel field, and broke all
six.

The easy fix was to loosen the pins. Instead the report now **declares** the verb names and a
test compares that declaration against the real class, where imports are free. Production's
import graph is unchanged, the claim stays checked, and a panel field did not buy the first
import into the order path.

One test was widened rather than worked around: 5V asserted every serialised journal value is
`str | int | float`, and the planned-stop fields default to `None`. `None` is load-bearing —
*no plan travelled with this row* must be distinguishable from a stop at a price, and `0.0`
would collide with a real one. `None` round-trips through JSON unchanged, so the property that
line guards still holds; the rule now admits it, with the reason.

## 9. Regression

**690 passed, 0 failed** — 5ZN, 5ZM, 5ZL, 5ZF, 5ZG, 5ZK, 5ZH, 5S, 5O, the whole order-path
family (5T–5Z), the whole `monitor/` suite, and the legacy stop and max-hold suites.

## 10. Files changed

| file | change |
|---|---|
| `global_index/track1_planned_stop.py` | **new** — `PlannedStop`, six refusal codes, `assert_sendable` |
| `global_index/track1_paper_order.py` | `plan_entry` alongside the untouched `candidate_to_order` |
| `global_index/track1_order_state.py` | three stop fields, appended last, defaulted |
| `global_index/track1_order_journal.py` | the same three plus `qty`, appended last |
| `global_index/track1_paper_executor.py` | three intent-only verbs, four refusal codes, `Intent`/`SwitchIntent`, **`BOOK_PATH` corrected** |
| `global_index/run_live_day_track1.py` | the book is carried forward, never synthesised over |
| `global_index/track1_report.py` | a `lifecycle` block; declares verbs rather than importing them |
| `scratch/test_track1_stage5zn_…py` | new, 52 tests |
| `scratch/test_track1_stage5x_…py`, `5v_…py` | one test corrected, one rule widened — both with reasons |

**No runtime file changed.** The book and checkpoint carry 00:55 from the live NKD close; the
Track 1 trade log carries 22:20 from 5ZJ's probe; the legacy log is untouched from 2026-08-15;
`preflight_state.json` still holds your seven days with 2026-08-26 absent. No order journal
directory was created. Nothing restarted — the dashboard's `lifecycle` block appears after a
backend restart.

## 11. What remains

| | item | class |
|---|---|---|
| 1 | machine sleep | **operator** |
| 2 | B1 — separate account, or a proven-flat legacy book | **operator decision** |
| 3 | five clean judgeable days | **time**, once 1 is fixed |
| 4 | the regime gate's first PASS | **time** — the 16:20 job records it |
| 5 | broker stop proof, partial fills, an order in flight across a restart | **paper only** |

**Is only evidence, operator and paper-proof left?** For Track 1's own code, **yes** — with one
caveat stated rather than buried. The lifecycle verbs produce intent and **the send step is
deliberately not built**. Wiring a real call site is a stage of its own and it should come
*after* the gates open, not before, because the day it is built is the day the distance between
the scheduler and a broker stops being structural. Until then the remaining code is a wire, not
a design.

The honest summary: nothing Track 1 needs is unknown any more. What is left is a machine that
must stay awake, an account decision, five clean days, and a broker.
