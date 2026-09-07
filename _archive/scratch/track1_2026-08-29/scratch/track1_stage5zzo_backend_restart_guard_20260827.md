# Stage 5ZZO — a guard that fired where nothing was starting

**2026-08-27.** No orders · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` · no orders
directory · confirmation unchanged · **scheduler untouched** · no broker order call.

---

## Root cause

Stage 5ZZN's guard ran **unconditionally**, before anything had decided whether a scheduler
would be started at all. So `restart --no-scheduler` — the command whose entire meaning is
*leave the scheduler alone and rebuild the backend* — was refused with:

```text
legacy/default: REFUSING to start
  - this start would register 45 legacy entry job(s) on that same login …
```

about a start nobody had requested.

That mattered more than a wrong message. It was the **only** route to a backend restart, and
5ZZN had just documented that as the way to pick up the new dashboard API route. A guard that
fires where no start happens is not a stricter guard — it teaches an operator to work around it,
and the workaround here was `restart --scheduler`: restarting a live scheduler to rebuild a
read-only backend, which is the more dangerous of the two acts.

## Reproduced

```text
scheduler_pids=[3000]  backend_pids=[38152]
track1_mode=track1-only-shadow   scheduler_mode=compatible   legacy_entry_jobs=0
blocking=['PAPER_SHADOW_EVIDENCE']   orders_possible=False

$ python monitor/ops.py restart --no-scheduler --yes
legacy/default: REFUSING to start
  - track1_go_live_confirmation.json records legacy_retired_confirmed …
```

5ZZN itself had landed correctly — the operator ran the restart and the scheduler is in
`track1-only-shadow` with **0** legacy entry jobs.

## The fix — and what it deliberately does not relax

The guard now fires at each of the **two** places a scheduler is actually started, not once at
the top.

**1. The explicit restart path**, checked before `ensure_single` stops anything — 5ZZN's
property, kept. A guard that fired after the kill would leave the operator with no scheduler at
all.

```python
if args.restart_scheduler and not track1_only:
    if _refuse_legacy_start(...): return 2
```

**2. The cold-start path in the `else` branch**, which was easy to miss. That branch starts a
scheduler in legacy/default mode — the call passes no Track 1 flag — and both `up` **and**
`restart --no-scheduler` reach it when there is no scheduler to leave alone. So a backend-only
restart on a machine with no scheduler running is still a real legacy start, and is still
refused. Nothing has been stopped on that path, so checking there costs the operator nothing.

## The mode matrix, measured

Run against a fully stubbed process world — nothing started, nothing stopped:

| command | scheduler running | result | what was touched |
|---|---|---|---|
| `restart --no-scheduler` | yes | **allowed**, rc 0 | backend only |
| `restart --no-scheduler` | **none** | refused, rc 2 | nothing |
| `restart --scheduler` (default) | yes | refused, rc 2 | **nothing** |
| `restart --scheduler --track1-shadow` | yes | refused, rc 2 | **nothing** |
| `restart --scheduler --track1-only-shadow` | yes | **allowed**, rc 0 | scheduler + backend |
| `up` | yes | allowed, leaves scheduler alone | backend only |
| `up` | none | refused, rc 2 | nothing |

In every refusal the call list is empty — the refusal precedes any stop or start.

## Live verification

```text
BEFORE   scheduler_pids=[3000]   backend_pids=[38152]
$ python monitor/ops.py restart --no-scheduler --yes
   scheduler=UNTOUCHED — pid 3000 started 2026-08-27 22:53:45 (8m ago)
   backend: stopped [38152]
   backend=started pid 28320
AFTER    scheduler_pids=[3000]   backend_pids=[28320]
         track1_mode=track1-only-shadow   scheduler_mode=compatible   legacy_entry_jobs=0
         track1_slot_table=fresh   blocking=['PAPER_SHADOW_EVIDENCE']   orders_possible=False
```

**Scheduler pid unchanged. Backend pid changed. Mode still compatible.**

### The Stage 5ZZL route is now served

The first request timed out at 25s, which is worth stating precisely rather than leaving as
"it timed out": that was the cold import chain on a freshly started backend, not the endpoint.
Measured immediately after:

```text
call 1 (cold)  1.47s   sleeves = global_nkd, roska4_stress, roska4_swing   regime = Calm
call 2 (warm)  0.11s
```

The day-slice cache is doing its job.

## Tests

**15** in `scratch/test_track1_stage5zzo_backend_restart_guard_20260827.py`. Nothing starts a
process, stops one, or touches the production confirmation file.

The regression is asserted twice, deliberately. Once on the output, and once **at the guard
itself** — a spy on `legacy_entry_start_blockers` proving a backend-only restart never consults
it. A message that stopped being printed for some unrelated reason would pass a text check and
prove nothing.

And what must stay refused is pinned: default restart, transitional `--track1-shadow`, `up` with
nothing running, and — the case the fix must not open — **`restart --no-scheduler` when there is
no scheduler to leave alone**.

### One 5ZZN test restated

`test_plain_track1_shadow_is_not_exempt` pinned the literal source line `if not track1_only:`,
which this stage rewrote to `if args.restart_scheduler and not track1_only:`. A source pin goes
stale the first time the code around it moves, and goes red for a reason unrelated to what it is
about. It is behavioural now: ask for the transitional mode, watch it be refused, and assert
nothing was touched.

### Suites

```text
5ZZO + 5ZZN + 5ZZ ops status + monitor/test_ops + dashboard backend
  + 5ZZJ + 5ZZK + 5ZQ + 5ZR                                    395 passed, 0 failed
```

**The 5ZZJ alarm now passes** — and for the right reason: the running scheduler is in
`track1-only-shadow` and registers no legacy entry job. It was left red at the end of 5ZZN
precisely so it would only go green when that became true.

## Safety, before and after

```text
orders_possible                False -> False
track1_blocking                ['PAPER_SHADOW_EVIDENCE'] -> unchanged
confirmation                   True -> True, untouched
scheduler pid                  3000 -> 3000  (untouched)
scheduler mode                 track1-only-shadow, compatible, 0 legacy entry jobs
backend pid                    38152 -> 28320  (the intended change)
TRACK1_ORDERS_APPROVED         unset
track1_runtime/orders          ABSENT
broker order calls             0
strategy / slots / gates / SEND wire   untouched
```

## One thing I could not explain

The backend I started during verification (pid 28320) served normally — including the new route,
200 — until 23:04:53, then **exited with nothing recorded**: no traceback in either log stream,
no kill entry in the ops action log, and it detaches with the same flags as the scheduler, so it
was not orphaned by my shell.

**I do not know why it stopped, and I am not going to guess.** What is ruled out is ruled out by
measurement; the cause itself is unexplained. It was restarted with the same command (pid 46600)
and the dashboard is up.

Worth watching: if it recurs, the thing to capture is whether it coincides with the market-view
route's cold parquet read, which is the only new work this backend does.

Both commands now behave as documented:

```powershell
python monitor\ops.py restart --no-scheduler --yes                     # backend only
python monitor\ops.py restart --scheduler --track1-only-shadow --yes   # the compatible mode
```
