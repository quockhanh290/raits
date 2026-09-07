# Stage 5ZZN — the guard that pushed the operator into the unsafe mode

**2026-08-27.** No orders · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` · no orders
directory · confirmation unchanged · **scheduler not restarted** · no broker call · no strategy,
slot, threshold, SEND-wire or evidence-rule change.

---

## Root cause

`monitor/ops.py::track1_shadow_blockers` refused a Track 1 shadow start **because the
confirmation file exists**:

```python
if TRACK1_CONFIRMATION.exists():
    blockers.append(f"{name} exists — that file arms the Track 1 route. A shadow start must
                      not run while it is present; remove it or start without --track1-shadow.")
```

That sentence was true when it was written: the signature was the only thing between this route
and an order. It stopped being true when **Stage 5S** added a measured evidence gate, and again
when **Stage 5ZZK** gave B1 a measured half. The file no longer arms anything by itself.

So on 2026-08-27 the sequence was:

```text
operator signs the B1 decision            ->  confirmation file exists
--track1-only-shadow now REFUSES          ->  because of that file
scheduler restarted without any T1 flag   ->  45 legacy entry jobs registered
                                              on the very login the signature
                                              had just declared retired
```

**The guard pushed the operator out of the only safe mode and into the unsafe one.** It was not
a missing check — it was a check whose premise had expired, and nothing failed loudly when it
did.

## Part A — reproduced, before any edit

```text
scheduler pid            11332, started 2026-08-27 21:51:23
argv                     run_scheduler --port 4002 --shadow-resume
                         (no --track1-shadow, no --track1-only-shadow)
track1_mode              legacy-only            source: process_table
legacy entry jobs        45  registered
Track 1 slots            0   registered
confirmation             True
track1_blocking          ['PAPER_SHADOW_EVIDENCE']
orders_possible          False
b1_legacy_flat           PASS
```

**Verified rather than assumed.** An earlier probe printed the command line one character per
line, which would have meant the mode detection was type-confused and the whole alarm a false
positive. It is not: `scheduler_command_lines` returns a single string, the substring test is
correct, and the argv above is the real one.

### Job counts, from the route table the scheduler itself removes from

```text
mode                    legacy_entry   track1   safety   shared   total
legacy / default             45           0       12        4       64
--track1-shadow              45          71       11        4      134
--track1-only-shadow          0          71       11        4       89
```

### A second defect found while reproducing

`ops status` printed `track1_slot_table=fresh source_slots=71 registered_slots=71` — a
statement about a process that had **already exited**. The last `[track1-only] … registered`
line in the log is `2026-08-27 05:08:33`; the running scheduler started at `21:51:23` and
registered none. A freshness check that compares the code against a dead process's log reports
on the wrong system with full confidence.

## Part B — chosen implementation: **Option A**

Relax the guard, do not invent a mode. Smaller and clearer: there is nothing wrong with
`--track1-only-shadow` — it already registers no legacy entry job, keeps legacy's safety sweeps
draining the old book, and cannot send an order. A new mode name would have been a second thing
to explain and a second thing to keep in step.

The guard now asks the **gate registry** whether an order is actually possible, because since
5ZZK the registry reads the confirmation file *and* the measurement behind every blocker — it
is the thing that knows.

```python
if TRACK1_CONFIRMATION.exists() and orders_would_be_possible()[0]:
    blockers.append("… exists AND every order blocker is clear, so this route can send
                     orders. A shadow start must not run while that is true …")
```

**The half of the old guard that was right is kept**: if every blocker really is clear, a shadow
start is starting something nobody asked for. And `orders_would_be_possible` **fails closed** —
an unreadable registry reports "possible", so a guard built on it refuses rather than waving a
start through on a question it could not answer.

## Part C — the guard that was missing

Nothing ever asked whether a **legacy** start was safe. The answer stopped being "always" the
moment an operator signed a decision saying this paper login belongs to Track 1.

`legacy_entry_start_blockers()` refuses, naming the four things Part C.2 asks for:

```text
legacy/default: REFUSING to start
  - track1_go_live_confirmation.json records legacy_retired_confirmed — the operator has
    decided that legacy is retired for this paper login.
  - this start would register 45 legacy entry job(s) on that same login, which contradicts
    the decision the B1 gate is currently reading as true.
  - start with --track1-only-shadow instead: it registers Track 1's slots and no legacy entry
    job, keeps legacy's safety sweeps draining the old book, and cannot send an order while
    PAPER_SHADOW_EVIDENCE is unsatisfied.
  - if legacy really must run entries again, retire the decision first — edit or remove
    track1_go_live_confirmation.json — rather than leaving a signature that says otherwise.
```

Placed **before either launch path**, next to the existing flags-conflict refusal. That
placement is the point: `restart --scheduler` stops the running process first, and a guard that
fired after that would leave the operator with no scheduler at all. Proven — with the guard
tripped, `ensure_single`, `stop_runners` and `start_scheduler` are all untouched and the command
returns 2.

`--track1-shadow` is **not** exempt. It adds Track 1's slots and keeps all 45 legacy entry jobs,
which is exactly the collision B1 exists to prevent. Only `--track1-only-shadow` is exempt,
because it is the one mode that removes them.

Both guards count legacy jobs from `legacy_retirement_candidates` — the same table the
scheduler's own removal step and the retirement audit read. One table, three readers, so the
number in the refusal cannot drift from the number actually registered.

## Part D — status

```text
track1_slot_table=stale_log source_slots=71 registered_slots=71
track1_scheduler_mode=INCOMPATIBLE confirmation=True legacy_entry_jobs=45
  MODE CONFLICT - the B1 decision says legacy is retired for this login, and the running
                  scheduler registers 45 legacy entry job(s) on it
  fix: python monitor/ops.py restart --scheduler --track1-only-shadow --yes
```

Three answers, and the third is the point: `unknown` when the process table cannot be read.
A mode nobody could read is **not** a compatible mode, and printing it as one would be the
fail-open this route keeps finding.

Two stale sentences repaired at the same time:

- `track1_slot_table` now reports **`stale_log`** when the registration line predates the
  running process.
- `orders : impossible — B1 open and no confirmation file` was false on **both** halves after
  the operator signed, and went on printing. It now asks the registry and names whichever
  blockers are actually holding: `orders : impossible — blocked by PAPER_SHADOW_EVIDENCE`.

## Part E — the restart command

Verified accepted against the **real, signed** confirmation — `track1_shadow_blockers(track1_only=True)`
returns `[]`, and the legacy guard exempts this mode by design:

```powershell
python monitor\ops.py restart --scheduler --track1-only-shadow --yes
```

**Not run.** After it, the mode conflict clears, `track1_slot_table` returns to `fresh`, and the
5ZZJ alarm passes *because the mode is compatible* rather than because anything was loosened.

Orders stay impossible either way: `PAPER_SHADOW_EVIDENCE` is measured, not signed, and the
approval variable is unset.

## Part F — the dashboard backend, kept separate

Stage 5ZZM's visual polish is source-only and still needs a backend restart for the
`/api/v1/track1-market-view` route added in 5ZZL. That is a **different** restart and must not
be mixed with the scheduler one:

```powershell
python monitor\ops.py restart --no-scheduler --yes
```

`--no-scheduler` leaves a running scheduler alone and prints its age. It does not start one and
does not change its mode.

## Part G — tests

**26** in `scratch/test_track1_stage5zzn_scheduler_mode_enforcement_20260827.py`. Nothing starts
a process, stops one, or touches the production confirmation file — every decision file lives
under `tmp_path`.

Covering all ten items: pre-B1 behaviour unchanged; the STOP_TRADING requirement for plain
shadow still standing; a legacy start refused once the decision exists; a confirmation that does
not validate asserting nothing; one that does not carry the flag not blocking; the post-B1 mode
allowed; the job shape (71 Track 1, 45 removed, safety surviving); orders impossible; a shadow
start still refused when orders *would* be possible; the registry failing closed; no
`--allow-orders` anywhere; no orders directory; the status reading compatible / incompatible /
**unknown**; the dead-process log no longer called fresh; and the guard firing before anything is
touched.

**The 5ZZJ alarm is pinned as still strict** — a test reads that file and asserts the assertion
`capability != dec.LEGACY_ENTRY_PRESENT` is still there and has not become a skip. It must pass
because the mode is compatible, never because it was loosened.

### Three of my own mistakes, all caught by running

- I compared **scheduler job ids** against **slot-table ids**: jobs register lowercase
  (`track1_calm_decide_0932`), the table names them `TRACK1_CALM_DECIDE_0932`. Two namespaces,
  one assertion.
- A test Namespace was missing `api_port`, so it ran past the guard into backend startup.
- `slot_table_freshness` scanned the **live process table** inside itself, so two 5ZZ unit tests
  that hand it a fixture log began failing because the real scheduler outside had started after
  their fixture's timestamp. A function that reads ambient state cannot be asked a hypothetical
  — the process start is now passed in, and the real caller supplies it.

### Suites

```text
5ZZN + 5ZZ ops status + monitor/test_ops + dashboard backend
  + 5ZZK + 5ZR + 5ZQ + 5ZZJ                              379 passed, 1 failed
```

**The one failure is the 5ZZJ alarm**, still red because the running scheduler has not been
restarted. That is the correct state: the enforcement is in the code, not yet in the process.
It clears with the Part E command.

Four `ops up`/`restart` tests in the dashboard suite were **isolated, not weakened**: they
describe a legacy start and were reading the real machine's confirmation file, so they began
failing for a reason that has nothing to do with process management. They now point at a
path that does not exist — the pre-B1 world they were written for — and the refusal they would
otherwise have hit is asserted in the 5ZZN suite instead.

## Part H — safety, before and after

```text
orders_possible                False -> False
track1_blocking                ['PAPER_SHADOW_EVIDENCE'] -> unchanged
confirmation                   True -> True, untouched
B1                             closed -> closed
TRACK1_ORDERS_APPROVED         unset
track1_runtime/orders          ABSENT
scheduler restarted            no
broker order calls             0
strategy / slots / gates / SEND wire   untouched
```

### External

```text
scheduler pid 11332, started 2026-08-27 21:51:23, argv without any Track 1 flag
  — the restart that caused this, done outside these stages
```
