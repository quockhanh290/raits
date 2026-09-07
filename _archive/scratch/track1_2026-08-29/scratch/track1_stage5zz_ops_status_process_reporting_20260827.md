# Stage 5ZZ — the health check was telling the truth in a language nobody could read

**2026-08-27, ET 04:40–05:00.** `monitor/ops.py` only. Nothing restarted · no orders · no
confirmation file · no broker order path · no runtime file touched.

---

## Verdicts

| | |
|---|---|
| `ops_status_reliable` | **YES** — every process line now carries its source, and a failed probe carries a code and the probe's own words |
| `scheduler_restarted` | **NO** — PID 5856 before and after |
| `backend_restarted` | **NO** — PID 2108 before and after |
| `runtime_files_touched` | **NO** — every runtime mtime predates this stage |
| `orders_possible` | **false** — unchanged, blockers unchanged |
| `next_calm_phase_ready` | **YES** — the scheduler restarted at 04:08 ET and registered **71** slots; status now says so on its own |

---

## 1. The failure did not reproduce, and that is the first thing to say

Running `python monitor\ops.py status` at the start of this stage printed pids, not UNKNOWN:

```text
scheduler_pids=[5856]
backend_pids=[2108]
```

So the fault is **intermittent**, and I could not make it appear on demand. What follows is not
a fix for something I watched fail; it is a fix for the reason a failure would be unreadable
when it does happen — which I could reproduce exactly.

Two theories were tested and one died:

- **Timeout.** The probe has a 20-second limit and `status` runs it twice. Measured over three
  runs each: **0.63–0.73 s**, on a host with 471 processes. Filtering the query down to python
  processes measured **0.65 s** — no better, because the cost is PowerShell's startup and not
  the enumeration. So the timeout theory is wrong, and the "obvious" optimisation of narrowing
  the query would have bought nothing while quietly excluding a scheduler launched under a
  different interpreter name. Not done.
- **The reason was never readable.** This one reproduced perfectly. See below.

## 2. What actually made UNKNOWN useless

When the probe failed, the recorded reason was `stderr[:200]`. PowerShell's default error
rendering **echoes the whole command** before it gets to the message. Reproduced on a
deliberately broken probe:

```text
stderr length: 692
what ops.py recorded (first 200 chars):
  "$ErrorActionPreference='Stop'; try { $p = @(Get-CimInstance Win32_ProcessDoesNotExist | ..."
where the actual message lived:
  ": Invalid class"      <- at the very end
```

So the operator was shown `scheduler_pids=UNKNOWN (` followed by their own script. The reason
was printed and was worthless, which reads exactly like a bare UNKNOWN.

There is one recorded instance of this in the project's own ops log, from **2026-08-13**, and
it is truncated in precisely that way: it says a scan failed and then quotes the opening of the
script, and nothing about what went wrong.

**And the message is not simply "the last line", either.** Measured against genuine output:

```text
0 | <the command, echoed and wrapped>
1 | ...rest of the command } : Invalid       <- the message starts here
2 | class                                    <- and continues here
3 | At line:1 char:181
6 |     + CategoryInfo          : NotSpecified: ...
7 |     + FullyQualifiedErrorId : Microsoft.PowerShell.Commands.WriteErrorException
```

Three wrong answers are available: the first 200 characters are the command, the last line is
an exception **class name**, and the message itself is split across two lines by wrapping. The
extractor is built from that measured shape, and recovers `Invalid class` from real output both
with the new marker and without it.

## 3. The tri-state was built and then thrown away one function later

`ProcessScan` has three states on purpose, and its docstring says why: collapsing "could not
look" into an empty list is what made ops.py launch a second scheduler on top of a live one.

`scheduler_processes()` returns a **list**, and a list cannot say "I could not look". So a
failed probe reached `track1_status` as `[]`, became `scheduler_running=False`, and printed as
`track1_mode=n/a` — the health check announcing that Track 1 is not running, about a scheduler
that is. The same defect family the dataclass was written to end, one function down.

Now: `scheduler_running` is `True`, `False`, or **`None`**, and `None` prints as
`track1_mode=unknown` with the reason attached.

## 4. Before and after

**Before** — the successful path was fine and said nothing about where it came from:

```text
backend_port=5002 listeners=[2108]
scheduler_pids=[5856]
backend_pids=[2108]
track1_mode=track1-only-shadow
```

**After**, the same machine:

```text
backend_port=5002 listeners=[2108]
scheduler_pids=[5856] source=process_table
backend_pids=[2108] source=process_table
track1_mode=track1-only-shadow track1_mode_source=process_table
track1_slot_table=fresh source_slots=71 registered_slots=71
```

**After**, with the probe denied — the path that used to be unreadable:

```text
scheduler_process_scan=permission_denied: Access is denied.
scheduler_pids=unknown_due_to_process_scan_error source=none
backend_process_scan=permission_denied: Access is denied.
backend_pids=unknown_due_to_process_scan_error source=none
backend_fallback=listeners:[2108] source=port_listener proves_running=True
scheduler_fallback=last_registered_71_slots at 2026-08-27 02:08:11 machine-local source=log proves_running=False
track1_mode=unknown track1_mode_source=log (permission_denied: Access is denied.)
track1_slot_table=fresh source_slots=71 registered_slots=71
```

**Where the scheduler pid and mode come from, said in the output itself.** Right now:
**process-table-derived** — `source=process_table` on both lines. There are no pid files in this
project, so the only fallback is log-derived, and it is labelled `source=log` with
`proves_running=False`. A log line is a history: it is equally consistent with a process still
going and one that died a minute later. The backend has a port, so its fallback is a live
listener and may say `proves_running=True`; the scheduler has no port and never claims it.

## 5. The stale-table check, which is the one that would have caught 5ZY-PRE

A scheduler builds its job table once, at boot, and holds it. Every edit afterwards changes the
code and not the running process. Stage 5ZY-PRE had to discover that by hand — comparing a log
line against the package by eye.

`status` now does it:

```text
track1_slot_table=fresh source_slots=71 registered_slots=71
```

and when they part company:

```text
track1_slot_table=stale source_slots=71 registered_slots=70
  RESTART NEEDED - the running scheduler registered 70 slots and the code now declares 71.
  It builds its table once at boot, so the difference is edits it has never seen.
```

It works from the log alone, so it still answers when the process table cannot be read — which
is exactly when an operator most needs to know whether the schedule is the one they wrote.

## 6. A latent defect found while fixing this one

**The probe matched itself.** The search pattern is embedded verbatim in the probe's own
PowerShell command line, so any pattern without a regex escape finds the process doing the
searching. Both production patterns happen to be immune because they escape their dots — an
**accident**, and `ensure_single` decides whether to **kill** a process from this same scan.

Closed by excluding the probe's own process, and pinned by a test asserting that each
production pattern does not match its own source text. Measured afterwards: invoked the way
production invokes it, a pattern matching nothing returns nothing, and the three real patterns
return exactly the right processes.

## 7. A mistake of mine, caught by the tests, worth recording

The first version had `track1_status` read the scan directly. That looked tidier and **silently
bypassed the seam every existing test patches** — five suites that believed they had described
a transitional or absent scheduler were reading the real machine, and passing or failing on
whatever happened to be running. A test that is not isolated is worse than no test: it reports
on the wrong system with full confidence.

The rows come back through `scheduler_processes()`. The scan is consulted only for its third
state, and the two are joined honestly: rows are proof whatever the probe said, and only "no
rows **and** the probe could not look" is genuinely unknown.

## 8. A correction to the Stage 5ZY-PRE record

That stage reported **three** true Stage 5ZX regressions. It is **four**. A third copy of the
same argv extractor lives in the ops-startup suite, and it failed with a differently-worded
message — `_track1_body argv not found` rather than `no _run([...]) call found` — so my grouping
by reason string put it in the pre-existing bucket. It was not pre-existing; Stage 5ZX broke it.

It matters more than the arithmetic: that test asserts **no order flag can reach a Track 1
slot**, and it had stopped running. It is repaired here, widened the same way, and it now also
pins that a phased slot carries its phase.

The corrected split: **45** caused by the Calm slot split, **~50** pre-existing, **4** true
Stage 5ZX regressions — all four repaired.

## 9. Tests

**22**, in `scratch/test_track1_stage5zz_ops_status_process_reporting_20260827.py`, plus repairs
to five cases across three older suites and the argv extractor above. Five mutations, each
performing a collapse and demanding its test go red:

```text
an exception in the probe read as a definite empty scan      RED
the printer reverting to a bare UNKNOWN                      RED
the reason reverting to the first 200 characters of stderr   RED
a 70-against-71 slot table reported as fresh                 RED
a log line promoted to proof that the scheduler is running   RED
```

Adjacent suites after the repairs: ops status/mode, ops startup, route-aware safety,
pre-sleep readiness — **135 passed, 2 failed**, and both failures were already failing before
this stage (a blocker-roster pin, and an absence proxy asserting the live runtime tree does not
exist on a machine where the route has been running for days).

## 10. Where the route stands

Nothing about the gate moved. `orders_possible=false`, blocking on B1 and
`PAPER_SHADOW_EVIDENCE`, no confirmation file, the order journal still absent, the shadow intent
stream still absent because the two phases have not run yet.

The next thing to watch is unchanged: **2026-08-27 09:32 ET**, `TRACK1_CALM_DECIDE_0932`, the
first run of either phase in production — and `status` will now say, on its own, whether the
scheduler about to fire it is running the schedule anybody wrote.
