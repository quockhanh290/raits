# Stage 5X — the broker read side, made able to say "I don't know"

**2026-08-25, 04:05–05:00 ET ·** no order · **no IBKR connection** · every broker in every test
is a fake · no confirmation file · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` ·
scheduler pid 48604 and backend pid 35352 untouched, not restarted · no runtime evidence
written, no ledger row edited, nothing backfilled · no commit.

Worked between the NKD window closing (02:55 ET) and the Calm slot at 10:00 ET.

> **Clock correction (Stage 5ZB, 2026-08-25).** The times in this header were read with
> `TZ=America/New_York date`, which on this machine returns **UTC**. The real ET times were
> four hours earlier than stated. Nothing else in this report depends on them — no window
> was open during the work either way — but the numbers themselves were wrong and are
> corrected here rather than left for a later reader to trust. Anchor with
> `zoneinfo`, never with the shell.

---

## Verdict: **READY_FOR_PAPER_ORDER_CALLSITE_DESIGN**

The read side can now distinguish *nothing* from *cannot say*, the six reconcile scenarios all
behave, and the one capability Stage 5W called missing turned out to be two mistakes rather
than one gap. What blocks paper orders is unchanged and is not on the read side.

---

## The correction Stage 5W owes

Stage 5W named two missing broker methods. **Both entries were wrong**, and this stage found it
by reading the file instead of testing a name:

| 5W claimed missing | actually |
|---|---|
| `get_executions` | the capability **exists**, spelled `find_execution(order_id, inst)` at `ibkr_broker.py:1541`. Stage 5W tested `hasattr(IBKRBroker, "get_executions")` — true, and useless: it measured a name nobody had proposed. |
| `get_open_orders` | did not exist as a method, but `reqAllOpenOrders()` was already called at **five** sites inside the same file. The API surface was never the gap. |

`get_open_orders()` is now a dozen lines over that same call. `MISSING_BROKER_METHODS` is
empty, and what is pinned in its place is the gap that actually survives: **`broker.Fill`
carries no order id**, so both id-keyed lookups are unusable on an entry this route sent.

Stage 5W's `test_32` fired on this change, which is precisely what it was built to do.

---

## What was actually wrong with the read side

Three methods, three different pairs of facts collapsed into one value. All measured from the
source, and each is now asserted by a test so the claim cannot decay into a story.

| method | what it returns | what that also means |
|---|---|---|
| `get_positions()` | the last read, with a warning, after 4 unstable attempts | "I could not settle" arrives looking like "here is what I hold" |
| `get_order_status()` | `NOT_FOUND` from its own `except Exception` | "I could not ask" arrives looking like "that order does not exist" |
| `find_execution()` | `None` — from **three** places | not-found, *any* error, and "two executions match and nothing distinguishes them" |

`NoOrderBroker.get_positions()` returns `[]`, which in shadow means **never asked**, not flat.

### The convention already existed

None of this is a new idea in this repo. `broker.py` states it, in `get_working_stops`:

> Returns None only when this broker is offline (test mode), never {} — the caller must be
> able to tell "nothing working" from "cannot say".

One method follows it. Three do not. Stage 5X extends the existing convention rather than
inventing one.

---

## What was built, and what was deliberately left alone

```text
global_index/track1_broker_read.py     NEW · pure · no ib_insync, no ibkr_broker import
global_index/ibkr_broker.py            + get_open_orders()  — additive, called by nothing
global_index/run_live_day_track1.py    + NoOrderBroker.CAN_TESTIFY = False  — a marker only
```

**The three legacy readers were not touched, and a test now stops anyone touching them.**
`runner.py` reads all three and its B3/B4 logic is built on today's answers. Changing them to
fail closed would look like a fix and would silently move what the legacy runner does on every
reconnect. So Stage 5X sits *above* them and re-labels, and `test_42` reads the file to assert
each still returns what it returns.

That guard matters because the collapse points in opposite directions for the two routes. For
legacy, `NOT_FOUND` on a stop means "treat as mismatch" — conservative. For an entry Track 1
just submitted, `NOT_FOUND` would read as "it never reached the broker", and acting on that
means **sending it again**.

There is a second design difference worth naming, because it is easy to mistake for an
oversight. Legacy does not fix the read; it compensates at each *call site* — a banner when the
file claims positions and the broker shows none, a bare `except: pass` around
`get_order_status`. Track 1 compensates once, at the read. Both are now asserted, so a future
tidy-up of runner.py's per-site guards turns a test red rather than quietly removing legacy's
only protection.

### `get_open_orders()`, and why the unfiltered list

Both existing lookups need an order id. After a crash Track 1 holds a journal row saying
SUBMITTED and no id, because the `Fill` carries none. This is the only read that can answer
"is anything of ours still working" without one.

It returns `None` offline and `[]` for "the book is clear" — the `get_working_stops` contract,
verbatim. It is **not** filtered by clientId: an order placed by another client on this account
is still exposure on this account, which is Stage 5U's shared-account finding.

---

## The six scenarios

| # | situation | resolution | entries |
|---|---|---|---|
| 1 | SUBMITTED + the order is working at the broker | `still_working` | **blocked** |
| 2 | SUBMITTED + no open order + no execution + positions unchanged | **UNKNOWN** | **blocked** |
| 3 | FILLED + execution confirms the full size | `FILLED` | allowed |
| 4 | FILLED + execution confirms *part* of the size | `PARTIAL` | **blocked** |
| 5 | broker read raises / times out | **UNKNOWN** | **blocked** |
| 6 | broker *states* CANCELLED | `REJECTED` | allowed |

**REJECTED is reachable only from a broker statement.** Silence is never rejection, and that is
tested across every silent shape there is: `NOT_FOUND`, empty string, `None`, and a raised
exception.

A seventh case fell out of writing it: **FILLED with no execution record is UNKNOWN, not
FILLED.** The broker says it filled and will not say how much or at what price. A book advanced
on a size nobody stated is a book that has stopped describing the account.

### The order of questions is not arbitrary

Working orders first — an order still on the book is the one unambiguous answer, and it settles
the row with no inference. Executions second. **Positions are consulted last and never decide
anything on their own:** a matching position proves *something* filled, not that *this order*
filled it. `test_29` asserts positions were read (the evidence dict is populated) and that they
did not resolve the row.

### Matching a working order without an id

By id when there is one; otherwise by instrument **and** action together. Instrument alone would
claim a protective stop working on the same contract — `test_20` is that case, and mutation M10
is the version of the code that gets it wrong.

---

## Exits: one word changed from Stage 5U

Stage 5U said "exits always allowed". That was right about intent and loose about wording, and
Stage 5X narrows it:

> exits are allowed under UNKNOWN and MISMATCH **if they reduce exposure**

Under an unresolved book a "close" whose size exceeds what is actually held does not reduce
exposure — it opens the other side. That is the one thing an unaccounted book must not be
allowed to do by accident. A reducing exit is still always allowed, because a position you
cannot account for is a position you should be able to close.

---

## The book read-back

Confirmed against the writer, not against a guess:

- the reader accepts **`qty`**, which is what `track1_bootstrap.snapshot_book` writes, and the
  test asserts against that function's source so the two cannot drift;
- a **missing** book is an empty Track 1 book — and that is the state production is in right
  now: `live_positions.track1.json` does not exist, because shadow has never held a position;
- a **corrupt** book raises, and `test_39` follows that through to the call site: the reconcile
  itself refuses, so fail-closed means something where entries are decided rather than only
  inside the reader.

---

## Tests and mutations

**52 tests. 20 mutations, all red.** Every mutation has the same shape — collapse "I do not
know" back into "nothing" — because that is the only direction that matters here.

| | mutation | caught by |
|---|---|---|
| M1 | `CAN_TESTIFY` ignored | the mute-broker positions test |
| M2 | a raising read swallowed into `[]` | the timeout test |
| M3 | one unreadable row dropped instead of refusing | the partial-book test |
| M4 | `None` open orders read as "nothing working" | the offline test |
| M5 | `NOT_FOUND` accepted as definite | the conflation test |
| M6 | `None` execution read as "no fill happened" | the three-meanings test |
| M7 / M7b | silence promoted to rejection | scenario 2, and every silent shape |
| M8 | a partial fill reported as full | scenario 4 |
| M9 | FILLED accepted with no execution record | the seventh case |
| M10 | a working order matched on instrument alone | the stop-on-same-contract test |
| M11 | `reduces_exposure` ignored | the over-sized close |
| M12 | blocking rows not counted | the entries gate |
| M13 | `get_open_orders` returns `[]` offline | the convention test |
| M14 | `NoOrderBroker` claims it can testify | the marker test |
| M15 | a legacy reader "fixed" underneath legacy | the do-not-touch guard |
| M16 | production imports the read module | the import scan |
| M17 | the legacy route calls the new method | the call scan |
| M18 | the read side reaches for the legacy book | the boundary test |
| M19 | legacy loses its own compensating banner | the call-site guard |

### The harness was lying, and now it cannot

**M13 reported RED against a test name that had been renamed one edit earlier.** pytest exits
non-zero when a test id does not exist, so the harness read "mutation worked" from a mutation
that was never exercised. This is the same family as the harnesses in `measure-first` §2.1 that
cannot go red — except worse, because it produced a *green-looking* proof.

`expect_red` now **runs each test unmutated first and requires it to pass** before applying the
mutation. A test that is failing, or absent, reports `BASELINE NOT GREEN` and fails the run.

Two mutations were also unfaithful before they were right: M13 and M15 patched module *source*
while their tests used `inspect.getsource`, which reads the **linecache** — so the patch never
reached them. Both tests now parse the file via `Path.read_text`, which is what makes them
breakable at all, and both are AST-based rather than substring.

### Substring, a fourth time

`test_41` first used a text scan for `get_open_orders` and matched the *corrected comment* in
`track1_paper_executor.py` that names the method while calling nothing. Fourth occurrence in
this arc. It is AST now, looking for an actual call node.

---

## Regression

| suite group | result |
|---|---|
| Stage 5X alone | **52 passed** |
| one combined run: Stage 5X + Track 1 stages 5Q-7…5W + the 10 legacy IBKR suites + the schedule mirror (21 files) | **546 passed**, 31s |
| Stage 5X mutations | 20 red, 0 green, every baseline proven green first |

The legacy suites matter most here — `ibkr_broker.py` is the file the legacy route depends on,
and the change to it is purely additive with no caller.

One Stage 5U test needed updating: it asserted its module was imported by nothing, and the read
side now imports it. The chain has **two heads** — the executor and the read module — and both
must stay unimported; the test asserts exactly that instead.

---

## Orders are still impossible

```text
track1_mode=track1-only-shadow
track1_stop_trading=False  confirmation=False  track1_orders_approved=False
track1_blocking=['B1_broker_account_or_legacy_retirement', 'PAPER_SHADOW_EVIDENCE']
orders_possible=False
scheduler_pids=[48604]   backend_pids=[35352]   — not restarted
```

- `track1_paper_executor` and `track1_broker_read` are imported by nothing in
  `global_index/`, `monitor/` or `futures/` — AST scan, both halves of every import node.
- no caller passes `--allow-orders` — AST string literals, not a text search.
- `global_index/track1_runtime/orders` was not created; every journal in every test lives under
  `tmp_path`.
- no IBKR connection was opened by this stage at all.

---

## What is left before the call site

| # | what | why not now |
|---|---|---|
| 1 | `PAPER_SHADOW_EVIDENCE` — 5 judgeable days needed, **0** so far | the first NKD window that can be judged on the fixed gate is **2026-08-26 01:10 ET** |
| 2 | `B1_broker_account_or_legacy_retirement` | a decision about the account, not a code change |
| 3 | the `Fill` carries no order id | the reason the working-order read exists; closing it properly means `send_order` returning an id, which is a write-path change |
| 4 | the call site itself in `run_shadow` | one line, and it is the line that makes orders possible |
| 5 | `close_position` / `place_protective_stop` / `switch_same_symbol` | still Stage 5T's refusing stubs |

Item 3 is the one Stage 5Y should look at, because the interim resolution — chase the working
orders, then positions — is weaker than an id and is labelled weaker in code.

---

## Files

```text
global_index/track1_broker_read.py                              NEW
global_index/ibkr_broker.py                                     + get_open_orders()
global_index/run_live_day_track1.py                             + CAN_TESTIFY marker
global_index/track1_paper_executor.py                           capability claim corrected
scratch/test_track1_stage5x_broker_readside_20260825.py         52 tests
scratch/track1_stage5x_mutations_20260825.py                    20 mutations + baseline guard
scratch/test_track1_stage5w_paper_executor_20260825.py          tests 31/32 follow the correction
scratch/test_track1_stage5u_order_state_reconcile_20260825.py   two chain heads
```
