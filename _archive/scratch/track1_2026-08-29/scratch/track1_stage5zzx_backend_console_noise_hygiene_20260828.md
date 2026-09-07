# Stage 5ZZX — the console was reporting questions, not answers

**Route:** `track1_candidate` · **Date:** 2026-08-28 · **Orders:** never enabled, still impossible

---

## 1. What was actually in the log

Measured on the retained backend log before changing anything — **358,361 lines**:

| lines | share | what |
|---|---|---|
| 337,972 | **94.3%** | `GET … 200` — dashboard polling |
| 8,860 | 2.5% | `GET … 3xx` |
| 8,036 | 2.2% | everything else |
| 2,806 | 0.8% | WARNING / ERROR |
| **685** | 0.19% | `Adding job tentatively` |
| **2** | — | `Track 1 SHADOW slots registered: 71` |

The brief framed the APScheduler lines as a co-equal cause. They are **0.19%** of the file, and
they are not continuous: they arrive in bursts on six distinct days. The flood is the access log.

A page polling every eight seconds writes about ten thousand successful GETs a day whether the
system is healthy or on fire, which is why the window "looks like jobs are continuously running".
Those lines record that a question was asked, not that anything happened.

### The APScheduler lines are not the backend serving requests

```text
2026-08-28 07:17:13   Adding job tentatively … ×7
2026-08-28 07:17:13   run_scheduler: Track 1 SHADOW slots registered: 71
2026-08-28 07:21:12   monitor.backend.app: Starting Flask on http://127.0.0.1:5002
```

The burst lands **four minutes before this backend logged its own startup**. It is `ops.py`
building a scheduler object to enumerate it during the restart, with its console output going to
the same file.

Confirmed from the other side too: with a log handler attached in-process, each of
`/api/v1/schedule-status`, `/api/v1/track1-runtime`, `/api/v1/track1-market-view` and
`/api/v1/open-issues` emits **zero** APScheduler records. Every one answers 200.

---

## 2. Does the backend ever start a scheduler?

**No.** An AST walk over `global_index/` and `monitor/` finds exactly one call:

```text
global_index/run_scheduler.py:1942      sched.start()
```

and it is inside the scheduler's own main. The mirror builds a scheduler object and enumerates
`get_jobs()`; nothing is started, and `dry_run=True` means even a fired job would execute nothing.
A test asserts that list stays exactly one entry, and another asserts the scheduler pid is
unchanged across a `/api/v1/schedule-status` request.

*(That test was first written as a text search, and found a match inside this stage's own
docstring in `app.py` — a sentence explaining that `sched.start()` appears once, counted as
though it were the call. It parses the source now.)*

---

## 3. What changed

Two logging filters, installed in `app.py` and therefore **in the backend process only**:

- `_QuietSuccessfulRequests` on the `werkzeug` logger — drops access lines whose status is
  `200/204/301/302/304`.
- `_NoTentativeJobAdds` on `apscheduler` **and** `apscheduler.scheduler` — drops the
  `Adding job tentatively` INFO. A filter on the parent is not consulted for a record made by a
  child logger, so it is attached at both levels; a mutation checks that.

### What is deliberately kept

| kept | why |
|---|---|
| every 4xx and 5xx | a failed request is the thing worth seeing |
| every WARNING and ERROR, including on a 200 | level is checked before anything else |
| tracebacks | never routed through either filter |
| backend startup lines | `monitor.backend.app` is not filtered |
| `Scheduler started`, `Running job …` | if a scheduler ever ran here, it would still say so |
| an access line the filter cannot parse | an unrecognised line is not a line to throw away |
| **the scheduler's own log** | a different process, untouched — its INFO lines are the record of work actually done |

Nothing global is disabled. `logging.disable` would have silenced the scheduler's own log too if
that code ever ran in that process; a test asserts the global disable is still zero, and a
mutation adds one to prove the test would catch it.

### What was NOT done

**The mirror still builds a real scheduler object** (task 6's optional half). Replacing it with a
hand-written slot list is what `scheduler_slot_ids` exists to avoid — its own comment records that
a second list is how the two drift apart, and Stage 5ZZT was spent on precisely that class of
drift. Quieting the logger is the smaller change and it is the one the brief allows. The
construction also already carries its own suppression, and it costs **two lines per backend
start**, not per request.

**Polling frequency is unchanged** at `POLL_MS = 8000`. Task 8 asked for a measurement before
touching it, and the measurement says the interval was never the problem: at zero log lines per
request, the same eight seconds now costs nothing.

---

## 4. Verified live

Backend-only restart, as the brief permits:

```text
python monitor/ops.py restart --no-scheduler --yes
  scheduler = UNTOUCHED — pid 3000, started 2026-08-27 22:53:45
  backend   = started pid 35956
```

```text
scheduler pid   3000 before → 3000 after          unchanged
40 warm requests across the four endpoints        40/40 → 200
new backend log lines for those 40 requests       0
```

The only lines written since the restart are **two** at 07:31:10 — `slots registered` and the
session-report notice — about sixty seconds after start, which matches the known cold-start
warm-up recorded in Stage 5ZZR. Once per backend start, not per request.

Before this change those 40 requests would have written at least 40 access lines.

---

## 5. Results

| | |
|---|---|
| New suite | **31 passed** |
| Adjacent backend / ops / dashboard suites | **553 passed**, 3 failed |
| Mutations | **10/10 caught** |

Most mutations widen the filter rather than narrow it, because that is the direction a logging
change is dangerous in: dropping 404s, dropping warnings, dropping a real `Scheduler started`,
throwing away a line it could not parse. Two go the other way and stop it filtering at all, and
one replaces the whole approach with a global `logging.disable` — the blunt instrument this stage
deliberately did not use.

The 3 remaining failures are pre-existing and previously measured: they expect a
`TRACK1_CALM_1000` slot and a "Calm one-shot band" from before Calm became two phases.

### Safety

```text
scheduler pid 3000 unchanged · scheduler NOT restarted · no broker connection opened by this stage
orders_possible   False        track1_blocking ['PAPER_SHADOW_EVIDENCE']
scheduler_mode    compatible · confirmation True · legacy_entry_jobs 0
track1_runtime/orders ABSENT   live_positions.track1.json ABSENT   TRACK1_ORDERS_APPROVED unset
runtime trading files not edited
```

Only `monitor/backend/app.py` changed. The backend restart reconnected the existing broker reader
it always starts (`client_id=99`, read-only); no new connection was made by this stage's code.

---

## 6. Still open

- The two construction lines per backend start. They are honest — a scheduler object really is
  being built — and could be removed by extending the existing suppression to the
  `run_scheduler` logger during construction. Left alone because two lines a restart is not
  noise, and widening a suppression is how a real message goes missing.
- The three Calm-band tests above.
- The retained log still holds its 358,361 historical lines. Nothing was truncated: the point was
  to stop adding to it, and deleting the record of the last three weeks to make a window tidier
  would be the wrong trade.
