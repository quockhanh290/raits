# Stage 5ZS — the safety net stops writing the route's book in someone else's handwriting

**2026-08-26, ET 11:00–11:40.** No orders · no confirmation file · `TRACK1_ORDERS_APPROVED`
unset · no `--allow-orders` · no broker connection · **nothing restarted** · **no runtime file
written** — the corrupt book was left exactly as found and the repair is a dry run.

```text
UTC 2026-08-26 15:35 · ET 2026-08-26 11:35 EDT · Calgary 2026-08-26 09:35 MDT
```

---

## Verdict

| | |
|---|---|
| live book corrupted? | **yes** |
| repaired? | **dry-run only** — the prompt did not say apply |
| safety jobs fixed? | **yes** — three layers, fifteen mutations, all red |
| legacy unchanged? | **yes** — byte-for-byte, asserted at every layer |
| runtime files touched? | **none** |
| orders possible? | **false**, three blockers, unchanged |
| next shadow window ready? | **runs — and will refuse to write evidence until the book is repaired.** That is the fix working (§8) |
| remaining before paper | five, unchanged |

---

## 1. What the book says right now

```text
live_positions.track1.json    218 B    2026-08-26 09:31:13 ET

  schema_version   1          <- was 2
  route            ABSENT     window ABSENT   cut_instant ABSENT   cur_day ABSENT
  equity           ABSENT     peak_equity ABSENT   day_start_equity ABSENT
  booked_counter   ABSENT     counters ABSENT
  positions        0          <- unchanged
  breaker          {peak_equity: 50000.0, system_equity: 50000.0,
                    last_broker_equity: 996881.46}     <- invented
```

**Nine fields dropped, the schema downgraded, and an account-scale equity this route has never
used written in their place.** `positions` was `[]` before and after, which is exactly why it
was quiet — and why it would not have been quiet on the first day the route held something.

## 2. Which job, and it was doing everything right

```text
2026-08-26 09:31:00 ET  TRACK1_MAX_HOLD_EXIT
  -m global_index.run_maxhold_exit
     --positions-path live_positions.track1.json
     --stop-path      STOP_TRADING.track1
     --lock-path      runner.track1.pid
     --client-id      90
     --trade-log-path global_index/track1_runtime/trade_log.track1.jsonl
     --route          track1_candidate
     --port           4002
2026-08-26 09:31:13 ET  completed OK          <- the book's mtime, to the second
```

The argv is **fully route-aware**. Stage 5ZG's routing worked exactly as built: its own book,
kill switch, lock, client id, trade log and route tag, every one of them honoured. The book was
still written in legacy shape, because the writer had no idea the envelope mattered.

**Today was the first opportunity.** The schema-2 book was created at 02:55 by Stage 5ZN's
cross-day carry, and `MAX_HOLD` runs once a day at 09:31. Six and a half hours later, it did.

## 3. The code path, and the fail-open inside it

`FuturesRunner._persist_state` builds one payload and always has:

```python
payload = {"schema_version": 1, "positions": positions_data, "breaker": breaker_data}
```

The invented numbers come from the other end. The **loader** reads the schema-2 file, hits
`if sv not in (0, 1)` — and logs *"unrecognised schema_version=2 … proceeding anyway"*. It then
looks for a `breaker` key, finds none, and every breaker field keeps its **default**. The
writer persists those defaults.

An unrecognised schema was a log line, not a refusal. That is the same fail-open shape as the
dashboard's empty order list in Stage 5ZQ, in a different file.

## 4. The same defect is in stop-repair, and it is latent

`run_stop_repair` builds the same `FuturesRunner` with the same positions path and reaches the
same `_persist_state`. It did not corrupt anything at 02:20, 04:20, 06:20 or 08:20 today only
because there was nothing to change. **The first Track 1 stop it ever repaired would have done
exactly this.** Both entry points are fixed together.

## 5. Three layers, because they fail independently

### The writer — preserve the envelope you read

A route-stamped sweep now writes positions back into the envelope it loaded, instead of
replacing that envelope with the legacy one. The gate is `route is not None` — the same switch
Stage 5ZG used — so with no `--route` the method is byte-for-byte what it was.

A route-stamped run whose book has **no** envelope (a first fill into a file that does not exist
yet) falls through to the legacy payload deliberately: there is nothing to preserve, and
inventing a schema-2 envelope there would be this method deciding a format it does not own.

### The carry-forward — refuse what is not yours

```python
route = prev.get("route")
if route is not None and str(route) != ROUTE:     # before: None PASSED
carried = dict(prev)                              # before: copied every key
```

`route is None` passing is precisely how a legacy-written book was accepted in silence. Both
are fixed: the route and the schema must match, and only fields the schema declares are
carried — so a foreign `breaker` is dropped rather than inherited. A declared field the previous
book lacked comes back at its fresh default, so a reader never has to guess which of the two it
is.

### The entry points — the book gets the contract the trade log already had

Stage 5ZG gave these two scripts one contract for their trade log and wrote down why the
destination must be chosen rather than inferred. The book never got the same treatment. Now:

```text
no argument                           -> the legacy book, byte for byte
--route track1_candidate + legacy book-> refused
the Track 1 book without --route      -> refused
a Track 1 book that is not one        -> refused
```

Placed **before** the positions-exists early return, for the same reason 5ZG placed the
trade-log probe there: both scripts return early on a missing book, which is every run during
shadow, so a check after it would never execute.

**It was narrowed once, deliberately.** The first draft also demanded the canonical Track 1
filename for *any* routed run. That is not the hazard — it forbade a harness using its own path
and broke four Stage 5ZG tests that were exercising the trade-log contract with a temporary
book. A false positive is not a caught hazard. The rule now targets the legacy book, and the
envelope check targets the canonical artefact; a mutation pins the narrowing so it cannot widen
back by accident.

## 6. Missing is not corrupt

| state | meaning | verdict |
|---|---|---|
| `missing` | the normal shadow state; both scripts return early | **allowed** |
| `unreadable` | not JSON, or not an object | fails closed |
| `corrupt` | readable, and not this route's book | fails closed |
| `track1` | schema 2, route-stamped, positions list | allowed |

Four states, and `inspect` never raises.

## 7. The repair — and what it cannot do

```text
python -m global_index.b1_book_repair            # dry run
python -m global_index.b1_book_repair --apply    # writes, after a backup
```

**It recovers nothing, and it says so.** The checkpoint carries per-instrument resume state and
**no book envelope**, so the nine lost fields have no source on disk. The tool rebuilds the
envelope at the route's own defaults and carries `positions` forward.

That is only sound while the route has never traded, so it proves it rather than assuming it:

```text
  trade log global_index/track1_runtime/trade_log.track1.jsonl: 0 row(s)
  order journal global_index/track1_runtime/orders: absent
  => never traded: True
```

Over an open position, or a route that has traded, it **stops** — rebuilding equity and
counters from defaults would be a guess about money. The damaged file is copied to
`*.corrupt-<stamp>.bak` before any write, and the result is re-inspected after.

**Not applied.** The prompt did not say apply.

## 8. What happens at 12:30 ET if it is not repaired

The stress window closes at 12:30 and `_carry_forward_book` will now **refuse** the corrupt
book, so that close writes no checkpoint and no book, and the window will read as failed.

That is the fix working. The alternative is the one it replaced: the corruption propagating
into a schema-2 book carrying a legacy breaker and missing five fields, silently, for as long
as nobody looked. **A failed window is the cheaper of the two, and it is visible.**

Applying the repair before 12:30 avoids it.

**No restart is needed for any of this.** Every slot and every safety job is a separate
`python -m` invocation, so the children pick up this code on their next run. The scheduler
parent holds job definitions, not this logic.

## 9. A gap this stage also closed: B1 called the corrupt book flat

`read_book` asks one question — how many positions — and for the legacy book that is the whole
question. For Track 1 it is not: a legacy-shaped file over the route's path still carries
`positions: []`, so **B1 reported "Track 1 book flat" about a book that was not the route's
book at all.**

```text
before   B1 read_book : read, 0 positions, flat = True
after    B1           : UNKNOWN (book_unreadable) — "it is stamped route=None…"
```

`ops.py status` still prints `PASS`, and that is correct: it reads the **06:15 record**, which
was true at 06:15. The corruption happened at 09:31. The record is honest about its own
timestamp; the next audit will not be.

## 10. Tests

**42 tests.** The corrupt fixture is copied field-for-field off the live file, so the suite
reproduces the real event rather than an idea of it. Real methods, real argv in a subprocess,
AST at call sites.

**Mutation sweep: 15 of 15 red**, including the four the stage names — route deletion, schema
downgrade, legacy breaker copy, and missing/corrupt collapse.

**Two of my own tests proved nothing and the sweep caught both:**

- the **loader stash had no test at all**. Tests 10–13 inject `_loaded_book_envelope` into a
  stub, so the loader could be deleted entirely and every one of them stayed green. There is no
  way to run the real loader — it lives inside a constructor that needs a broker, a guard,
  contracts, a signal function and a breaker, and this repo has no offline construction path —
  so the chain is pinned structurally, with the two halves **derived from each other**: whatever
  attribute the writer reads must be the one the loader assigns.
- the **narrowing test used a path that did not exist**, so `dest.exists()` short-circuited and
  it could not tell a narrow rule from a wide one. It now creates the file, legacy-shaped, which
  is the realistic case anyway.

**Regression: 658 passed, 0 failed, 1 skipped** — 5ZS, 5ZG, 5ZK, 5ZN, 5ZQ, 5ZR, 5O, 5S, 3B, 5W
and the monitor ops / dashboard / schedule-status suites.

## 11. Remaining before paper

Unchanged by this stage, which touched no gate:

| | item | class |
|---|---|---|
| 1 | the B1 decision — and the state of the world that makes it true | operator |
| 2 | five clean judgeable shadow days | time |
| 3 | the regime gate's first PASS | time |
| 4 | machine sleep | operator |
| 5 | **the order path** — `run_live_day_track1` constructs `NoOrderBroker` and never `IBKRBroker` | code, unwritten |

Plus one new operator item, and it is time-bound:

```powershell
python -m global_index.b1_book_repair            # look
python -m global_index.b1_book_repair --apply    # repair, before 12:30 ET
python -m global_index.b1_audit --broker ibkr --record   # re-record B1 after
```
