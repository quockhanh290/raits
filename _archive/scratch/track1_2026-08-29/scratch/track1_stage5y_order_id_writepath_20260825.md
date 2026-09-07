# Stage 5Y — the write path learns to name the order it sent

**2026-08-25, 04:25–05:40 ET ·** no order · **no IBKR connection** · fake brokers only · no
confirmation file · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` · executor still not
wired into the runtime slot path · scheduler pid 48604 and backend pid 35352 untouched, not
restarted · no runtime evidence written · nothing backfilled · no commit.

Worked between the NKD window closing (02:55 ET) and the Calm slot at 10:00 ET.

> **Clock correction (Stage 5ZB, 2026-08-25).** The times in this header were read with
> `TZ=America/New_York date`, which on this machine returns **UTC**. The real ET times were
> four hours earlier than stated. Nothing else in this report depends on them — no window
> was open during the work either way — but the numbers themselves were wrong and are
> corrected here rather than left for a later reader to trust. Anchor with
> `zoneinfo`, never with the shell.

---

## Verdict: **READY_FOR_PAPER_ORDER_CALLSITE_DRY_RUN_DESIGN**

The broker names every order it places, the name is durable *before* the fill poll, and the
reconcile prefers it. Nothing about the legacy route moved.

---

## The gap, and the shape chosen to close it

`get_order_status(order_id)` and `find_execution(order_id, inst)` both exist and both need an
id — and until today **nothing that placed an order ever learned one.** After a crash the
Track 1 journal held a row saying SUBMITTED and no way to ask about it.

Three options were on the table. What was built is both of the first two, because neither
alone is sufficient:

| | what it fixes | what it leaves |
|---|---|---|
| `Fill.order_id` | the outcome can be tied to an order | nothing survives a crash *during* the call |
| a placement receipt | the id is durable before the wait | the outcome row still has to carry it |

**The poll is the whole reason the receipt exists.** `send_order` blocks for up to 30 seconds
on an entry, and that window is where a crash loses everything. A field on the returned `Fill`
is only populated if the call returns.

```text
placeOrder(...)          →  the order is live
on_submit(OrderReceipt)  →  the id is journalled HERE, before anything waits
while not trade.isDone() →  up to 30s
return Fill(order_id=…)  →  and again on the outcome
```

### Additive, and provably so

Both changes were made in the one shape that leaves every pre-existing caller untouched:

- **`Fill.order_id`** is appended **last** with a `None` default. Positional construction,
  keyword construction and the mixed form the runner uses all still work; nothing anywhere
  does `asdict(Fill)` or `astuple`, so no serialisation moved. `None` rather than `""`,
  because an empty string reads as an id.
- **`on_submit`** is **keyword-only** with a `None` default, on the ABC, `MockBroker` and
  `IBKRBroker` alike. `broker.send_order(order)` — the form used at **6 sites in `runner.py`**
  and 2 in `track1_switch.py` — still binds against every implementation, and a test asserts
  those call sites still pass exactly one argument and no keywords.

A broker that ignores `on_submit` is not broken. It simply cannot report early, and the
reconcile falls back to the Stage 5X path and says so.

---

## The one place this adds information rather than a field

`send_order`'s broad `except` used to answer two completely different situations identically:

- the order **never reached IBKR** — contract resolution failed, the month conflicted, the
  socket died before `placeOrder`;
- the order **reached IBKR** and something afterwards threw.

The second leaves live exposure. A caller that cannot tell them apart has to assume the worse
one every time. `trade` is now initialised to `None` and the handler reports `order_id` only
when placement actually happened.

### A live order must never be reported as cancelled

If the receipt callback raises *after* placement, the broad handler would have caught it and
returned `Fill(status="CANCELLED")` — for an order that is live at the broker. That is the
worst answer available, worse than crashing, because the caller believes it.

So `OrderReceiptRefused` has its own type and travels beside `IBKRConnectionError` in the
re-raise clause. It lives in `broker.py`, not the IBKR module, so any broker implementation
can honour the same contract.

---

## The journal: an amendment, not a transition

SUBMITTED is written **before** the broker call — that ordering is Stage 5V's and it does not
move — so the id cannot exist on that row. The receipt arrives mid-call and is recorded as a
second row in the same state.

`SUBMITTED → SUBMITTED` is **not** a state transition and the state machine still refuses it.
This is an *amendment*: the order did not change, we learned its name. The rule is deliberately
narrow, because a permissive self-transition would let a genuine duplicate send look like a
legal history:

- the earlier row must carry **no** id and this one must carry one — an amendment that adds
  nothing is not an amendment;
- an id may **never be replaced**. Two ids under one key are two orders, and that is the single
  worst thing this journal could be made to hide;
- nothing else may move. A different instrument, side, size or day under the same key is a
  different order wearing a borrowed name.

A full entry now reads:

```text
INTENDED    (no id — nothing has been sent)
SUBMITTED   (no id — written before the call, by design)
SUBMITTED   order_id=55        ← the amendment, while send_order is still in flight
FILLED      order_id=55
```

---

## The bug I shipped, and how it was found

**The first version of this stage was broken, and all 52 tests passed over it.**

`append` accepted the amendment. `resolve` then read the journal back, found
`submitted -> submitted`, and refused the whole day as an impossible history. So **every order
that successfully got an id would have made that day's journal unreadable** — fail-closed in
direction, and completely non-functional.

It was found by running the round trip by hand, not by a test. Fifty-two tests all checked the
*write*; not one re-read.

The cause was two rules where there should be one: the writer knew about amendments and the
reader did not. The fix is `track1_order_state.is_amendment`, used by `resolve_journal` and
asserted by the writer, so the two cannot drift again. Six tests now cover the read-back, and
the writer carries a deliberately unreachable assertion against the shared rule — if they ever
disagree, the row is refused at write time rather than stranding a journal.

---

## The read side prefers the id — including when it says *no*

Stage 5X matched a working order by instrument **and** action. That fallback stays, but it is
no longer consulted after an id mismatch:

> **an id, when both sides have one, is the whole answer — including when it says no.**

Falling through to instrument-and-action after a mismatch would let a different order on the
same contract, with the same action, answer for ours. That is precisely the failure the id was
added to remove. The evidence dict now records which route answered — `matched_by_order_id`,
`matched_by_instrument_and_action`, or `no_working_order_matched` — because the two are not
equally strong and a report should not have to pretend they are.

Positions are still last and still never decisive alone.

---

## Exits: unchanged, and re-asserted

Under UNKNOWN or MISMATCH an exit is allowed **only if it reduces exposure**. An oversized
close still blocked. Both re-tested here rather than assumed to have survived.

---

## Every outcome

| situation | journal | id |
|---|---|---|
| filled | INTENDED · SUBMITTED · SUBMITTED · **FILLED** | yes |
| partial | … **PARTIAL** | yes |
| broker states cancelled | … **REJECTED** | yes |
| unclassifiable status | … **UNKNOWN** | yes |
| exception **after** the receipt | … **UNKNOWN** | **yes** — the order is live and we can name it |
| exception **before** the receipt | INTENDED · SUBMITTED · **UNKNOWN** | no, and none invented |
| broker returns no id at all | INTENDED · SUBMITTED · FILLED | no — Stage 5X fallback, stated |
| pre-5Y broker (`send_order(order)`) | INTENDED · SUBMITTED · FILLED | no — keyword never passed |

Two rules run through that table. **A missing id is never invented** — test mode places nothing
and reports nothing, and a fabricated identifier in a journal is worse than none because a
reconcile trusts it. And **UNKNOWN stays UNKNOWN**: no amount of missing information promotes
to REJECTED.

---

## Tests and mutations

**58 tests. 24 mutations, all red**, each with a proven-green baseline. The mutations fall into
five families, and the second is the dangerous one — a missing id degrades and says so, a wrong
id is believed:

| family | mutations |
|---|---|
| the id is lost | receipt never requested, receipt moved after the poll, outcome drops it, `Fill` drops it, field no longer last |
| the id is fabricated or answers for the wrong order | test mode invents one, a failure before placement invents one, an id mismatch falls through to the weaker match, an id replaced, an amendment that adds nothing, an amendment that moves the instrument, `SUBMITTED→SUBMITTED` opened in the state machine, the executor writes a row it knows is unlawful |
| a live order called cancelled | `OrderReceiptRefused` caught by the broad handler, the except path collapsing placed and never-placed |
| legacy moved | `on_submit` made positional, a legacy call site changed, `MockBroker` stops recording fills |
| the amendment does not survive read-back | `resolve_journal` stops recognising it, it accepts any repeat, it accepts a replacement |

### The harness lied three times before it worked

Seven mutations came back green on the first run and every one was **my mutation at fault**:

- **M9, M10, M11, M13, M18, and later M3 and M7** were written as source patches against tests
  that assert *behaviour*. `_source_patch` only changes what `Path.read_text` returns; it can
  never alter an already-imported function. **This is the Stage 5V M3 lesson, repeated in the
  same session it was written down** — and then repeated again after being fixed once. All are
  now in-process replacements of the real callable.
- **M5** patched `broker.Fill`, but the test does `from global_index.broker import Fill`, so
  the name is bound in the test module and the patch never reached it. It now reorders
  `__dataclass_fields__`, which is what `dataclasses.fields()` actually reads.
- **M17 was faithful and found a real hole.** Its first form produced
  `send_order(on_submit=None, Order(...))` — positional after keyword, a **SyntaxError**. The
  test caught the `SyntaxError` and `continue`d, so an unparseable `runner.py` was silently
  skipped and the test passed while a legacy call site had changed. Same shape as answering *"I
  could not read it"* with *"there is nothing there"* — the exact defect Stage 5X spent itself
  on. An unparseable file is now a reported failure.

---

## Regression

| suite group | result |
|---|---|
| one combined run: Stage 5Y + 5Q-9 · 5R-0 · 5S · 5T · 5U · 5V · 5V-1 · 5W · 5X + the 16 legacy `Fill`/`send_order` consumers (26 files) | **620 passed**, 38s |
| Stage 5Y mutations | 24 red, 0 green |
| Stage 5V mutations (journal changed under them) | 10 red, 0 green |
| Stage 5X mutations (read side changed under them) | all red |

The legacy suites are the ones that mattered: `broker.py` and `ibkr_broker.py` are what the
legacy runner depends on, and both changes were additive with no caller. `test_event_playback.py`
was not run, as instructed.

Two Stage 5W tests fired on this change and were right to — they pinned "the Fill carries no
order id". That test has now fired twice, once for 5X and once for 5Y, and both times the claim
it was guarding had become false. It now pins that the claim is *derived from the dataclass*
rather than asserted, which is the actual lesson from being wrong twice.

---

## Orders are still impossible

```text
track1_blocking=['B1_broker_account_or_legacy_retirement', 'PAPER_SHADOW_EVIDENCE']
orders_possible=False   confirmation=False   track1_orders_approved=False
scheduler_pids=[48604]  backend_pids=[35352]  — not restarted
```

- `track1_paper_executor` and `track1_broker_read` are imported by nothing in `global_index/`,
  `monitor/` or `futures/` — AST, both halves of every import node.
- `run_shadow` still constructs `NoOrderBroker` and nothing else.
- no caller passes `--allow-orders` — AST literals, not a text search.
- `global_index/track1_runtime/orders` was not created; every journal in every test is under
  `tmp_path`.
- nothing outside `broker.py` and `ibkr_broker.py` constructs an `OrderReceipt`.

---

## What is left before the dry run

| # | what | note |
|---|---|---|
| 1 | `PAPER_SHADOW_EVIDENCE` — 0 of 5 judgeable days | first fixed-gate NKD window **2026-08-26 01:10 ET** |
| 2 | `B1_broker_account_or_legacy_retirement` | a decision about the account, not code |
| 3 | the call site in `run_shadow` | one line; a dry-run design should place it behind a mode that builds the executor and refuses at the broker boundary |
| 4 | `close_position` / `place_protective_stop` / `switch_same_symbol` | still Stage 5T stubs |
| 5 | `perm_id` is carried but never waited for | it is usually 0 at placement; if a stable global id is wanted, that is a second read, not a longer wait |

Nothing on this list is a broker-capability gap. **The write path is no longer what blocks
paper orders.**

---

## Files

```text
global_index/broker.py                  + Fill.order_id (last, default None)
                                        + OrderReceipt, OrderReceiptRefused
                                        + on_submit on the ABC and MockBroker
global_index/ibkr_broker.py             + on_submit; receipt fired between placement and poll
                                        7 of 8 Fill returns carry the id (the 8th places nothing)
                                        the except path separates placed from never-placed
global_index/track1_order_state.py      + is_amendment(), used by resolve_journal
global_index/track1_order_journal.py    + BAD_AMENDMENT, _check_amendment
global_index/track1_paper_executor.py   + accepts_receipt(); the receipt writes the amendment
global_index/track1_broker_read.py      the id is authoritative, including negatively
scratch/test_track1_stage5y_order_id_writepath_20260825.py    58 tests
scratch/track1_stage5y_mutations_20260825.py                  24 mutations, all red
scratch/test_track1_stage5w_paper_executor_20260825.py        tests 31/32 follow the change
```
