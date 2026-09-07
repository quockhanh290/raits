# Stage 5V — the fail-closed order journal

**2026-08-25, 02:05–02:20 ET ·** the `global_nkd` window was **open** throughout (01:10–02:55)
and was not disturbed: no scheduler or backend restarted, no runtime file written, every
journal in this stage created under `tmp_path` · **no IBKR connection** · no order · no
confirmation file · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` anywhere · no commit.

---

## Verdict: **READY_FOR_PAPER_EXECUTOR_SKELETON**

The journal is written, fail-closed, and held there by 47 tests and **10 mutations, all red**.

### The direct answers

| question | answer |
|---|---|
| **Exact journal path** | `global_index/track1_runtime/orders/track1_orders_YYYYMMDD.jsonl` — durable, route-stamped, never scratch |
| **Are writes fail-closed?** | **Yes.** `append` contains no exception handler at all; the write is `flush`ed and `os.fsync`ed before it returns; a failure at any point reaches the caller |
| **Which transitions are accepted/refused?** | table below — and `INTENDED → FILLED` is refused, which is the whole point |
| **Any production order path today?** | **No.** The journal is imported by nothing, `run_live_day_track1` still holds `NoOrderBroker`, and no `placeOrder`/`MarketOrder`/`IBKRBroker(` exists in the route |
| **What remains before `Track1OrderExecutor`?** | the executor itself, `get_open_orders()` + an executions lookup on the broker, `live_positions.track1.json` read-back, and the call sites |

---

## The contract, and why it is the opposite of the ledger

`window_ledger._write` catches every exception and disables the channel for the process,
because *"it must never escape into a trading path"*. Right for evidence, wrong for a
write-ahead log — a failed write there would let an order go out with no record of intent.

```text
window ledger   best-effort. Swallows. Never blocks.          UNCHANGED by this stage.
this journal    fail-closed. Raises. A write that did not
                land must stop the order.
```

Nothing in `append` is caught. Every failure — a bad record, an illegal transition, a path
outside the runtime root, a full disk, a failing `fsync` — leaves as an exception, because the
only correct response to *"I could not record that I am about to trade"* is not to trade. A
test parses `append` and requires that it contains **no `try` at all**.

**Durability, and its honest limit.** The line is written, flushed and `os.fsync`ed before
`append` returns, so a record it claims is durable has reached the device rather than an OS
buffer. The *directory entry* is not fsynced — there is no portable way on Windows. The
exposure is a file created in the same instant as a crash, which is exactly the case the
startup reconcile exists to catch. Stated rather than left to be discovered.

---

## The state machine on disk

| from | may become |
|---|---|
| *(no record)* | **`INTENDED` only** — an order whose intent was never recorded is what this file exists to make impossible |
| `INTENDED` | `SUBMITTED`, `REJECTED`, `UNKNOWN` |
| `SUBMITTED` | `FILLED`, `PARTIAL`, `REJECTED`, `UNKNOWN` |
| `UNKNOWN` | `FILLED`, `PARTIAL`, `REJECTED` |
| `PARTIAL` | `FILLED`, `REJECTED` |
| `FILLED`, `REJECTED` | *nothing* |

`INTENDED → FILLED` is **not** a legal history. The refusal happens before the line is written,
and a test asserts the file still contains only the `INTENDED` row afterwards — a refusal that
wrote its record anyway would be no refusal.

### A hole a failing test found

My own test expected both `INTENDED` and `SUBMITTED` keys to count as *unresolved*. It failed,
and being wrong about it exposed something real: Stage 5U said `SUBMITTED` meant "handed to the
broker", which never said **whether the line is written before or after the call**.

If it were written after, a process dying *inside* `send_order` would leave a journal whose last
state is `INTENDED` while a live order existed — and `INTENDED` is documented as "nothing was
sent".

So the rule is now explicit: **`SUBMITTED` is written BEFORE `send_order` is called.** That is
the same discipline `track1_switch` already follows — *"Every stage emits BEFORE it acts. A
crash between two steps is then attributable from the log."* The cost is the opposite error and
it is the cheap one: an order that was never actually sent looks unresolved until a reconcile
says the broker has nothing.

`INTENDED` is therefore genuinely safe to read as "the broker was never reached", and it is not
in `UNRESOLVED`. Both halves are now pinned by tests.

---

## Corruption is reported, never skipped

- a corrupt line is **returned** by `read()` as an `invalid` entry with file and line number;
- a corrupt journal **refuses to authorise another order** — a journal that cannot be read
  whole cannot authorise an order;
- an impossible history already on disk (hand-written, bypassing `append`) makes `resolve`
  **raise** rather than repair. A reader that quietly fixes the journal is a reader that can be
  lied to.

## Path safety

The filename is built from an eight-digit day, and both a shape check and a resolved-parent
check must pass. `../../etc/passwd`, `/abs`, `2026-8-5`, `20260825x`, `..`, `""`, `2026082` and
`202608255` are all refused with `order_journal_path_escape`. The writer creates its own
directory, and only inside the given root.

---

## Tests and mutations

**47 tests** (`scratch/test_track1_stage5v_order_journal_20260825.py`) — write and read-back,
every declared field surviving a round trip as a flat scalar, append ordering, deterministic
idempotency keys, both fail-closed paths, every legal history, every terminal state, key
isolation, corruption, impossible histories, eight path-escape cases, and four "nothing else
moved" checks.

**10 mutations, 10 red:**

| | mutation | test that went red |
|---|---|---|
| M1 / M1b | `append` swallows its write exception | behaviourally, **and** through the AST |
| M2 | `INTENDED → FILLED` allowed | the refusal |
| M3 | the route stamp check removed | the route refusal |
| M4 | the day string no longer validated | eight path-escape cases |
| M5 / M5b | the reader silently drops corrupt lines | reported, **and** the refusal to authorise |
| M5c | impossible histories silently repaired | the resolve refusal |
| M6 | `ib_insync` imported | the no-broker check |
| M7 | `os.fsync` removed | durability |

**M3 was unfaithful on the first attempt** and is worth recording. It patched the module's
*source text*, which cannot change an already-imported `__post_init__` — so it stayed green and
proved nothing. An unfaithful mutation is worse than no mutation: it reports a test as
protective when it has not been shown to be. It is now a real in-process replacement of
`__post_init__` with the route check removed.

**Regression:** 187 passed, 1 skipped across five suites. No `orders/` directory exists in the
real runtime tree, asserted by a test rather than checked by hand.

---

## What is built, and what is not

```text
BUILT   global_index/track1_order_journal.py
          JournalRecord         18 flat scalar fields, validated at construction
          idempotency_key()     deterministic, no timestamp, generated before the call
          journal_path()/dir()  eight-digit day, two independent escape checks
          append()              transition-validated, flushed, fsynced, catches nothing
          read()                returns (records, invalid) — invalid never dropped
          resolve()             refuses to answer on a journal it cannot read whole

NOT     the executor · get_open_orders() and an executions lookup on IBKRBroker ·
        live_positions.track1.json read-back and repair · any call site
```

`track1_order_journal` is imported by nothing. `track1_order_state` is imported only by the
journal, and the journal by nothing — enumerated by a test rather than asserted as a slogan,
because "imported by nothing" stopped being the right assertion the moment 5V built on 5U.

---

## Separately: what the live NKD window is doing right now

Not part of this stage, but it is running as this is written and it changes what to expect at
03:05.

```text
14 slots observed · 0 decided · every one: gate_refused  partial_coverage,stale
runtime p50 2.44s   max 3.05s   all outcome=ok
```

The `stale` is the predicted `spy_refresh_pm` gap, confirmed by running the freshness gate:

```text
regime_csv             stale   last date 2026-08-21 is before the required 2026-08-24
preflight_consistency  stale   the 13:45 job for 2026-08-24 says SUCCEEDED and regime_csv
                               still does not satisfy what the gate asks
```

`spy_refresh_pm` was only registered at last night's 23:29 restart — after 16:20 — so it has
never run. **Its first firing is today at 16:20 ET**, and from Wednesday morning the gate should
pass.

So tonight's NKD window will not produce a PASS, and the readiness count stays at zero. That is
the gate working on a real refusal, not a new fault — and the slot cadence is healthy
throughout, which is the other thing the window was there to show.
