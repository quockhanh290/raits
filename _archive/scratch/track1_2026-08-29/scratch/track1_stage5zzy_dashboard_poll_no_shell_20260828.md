# Stage 5ZZY — a polled endpoint must not open a console

**Route:** `track1_candidate` · **Date:** 2026-08-28 · **Orders:** never enabled, still impossible

---

## What this stage found already done

`monitor/backend/schedule_status.py` and `open_issue_reader.py` were modified at **08:04**, after
Stage 5ZZX finished at ~07:35 and before this stage began. `scheduler_track1_mode_status()`
already existed, `scheduler_track1_only()` already used it, `legacy_retirement_state()` already
took a `root`, and neither file called `ops` any more. **Items 1–3 of this brief were implemented
by someone else.** This stage verified that work, and did items 4, 5 and 6.

Recording it because the alternative is a report that reads as though I wrote it.

---

## 1. The regression, measured

Stage 5ZZW made the backend ask the **scheduler** which mode it is in rather than trusting its own
environment. That was the right correction, and it reached for `ops.track1_status()` to make it:

```text
ops.track1_status()   →  2.84s,  2 × powershell.exe
```

On a page polling every eight seconds, that is a console window several times a minute. Stage
5ZZX's log filters could never have helped, because the noise was never in the log.

The backend already had the answer it needed. `_scan_scheduler_processes()` enumerates with
**psutil**, keeps each scheduler's command line, and sits behind a 60-second TTL with a background
refresh. Its own docstring says *"never call this on a request path"* — the discipline the ops
reader does not have, since the ops reader is a command-line tool where 2.8s is fine.

### One measurement that had to be re-done

The first probe reported **zero** subprocess calls from every endpoint, which would have meant
there was no regression at all. A zero that convenient is a reason to check the instrument: a
deliberate `subprocess.run` proved the spy was live, and calling `ops.track1_status()` directly
showed the two PowerShell spawns. The endpoints were already clean because the fix was already on
disk — but I could not have known that from the zero, and every measurement in this report now
carries a self-check for the same reason.

---

## 2. Verified, not assumed

```text
20 warm requests across the four polled endpoints
    subprocess.run   0
    powershell.exe   0
```

Mode parsing, from a synthetic command line:

| command line | mode | track1_only | legacy entry jobs |
|---|---|---|---|
| `--track1-only-shadow` | `track1-only-shadow` | True | **0** |
| `--track1-shadow` | `track1-shadow` | False | **45** |
| *(default)* | `legacy-only` | False | 45 |
| *(empty)* | `n/a` | **None** | None — source `unknown` |
| *(no scheduler)* | `n/a` | **None** | source `none` |

`--track1-shadow` shares a prefix with the safe mode and still runs every legacy entry slot, so
reporting it as retirement-compatible would hide legacy issues while legacy is trading. It reports
45. An unreadable command line is **unknown, never legacy** — a mutation pushes it to legacy and
the suite catches it.

---

## 3. Task 6 — the Calm tests, and a defect underneath them

The three Calm failures had already cleared. Two of the three properties held on inspection:
`TRACK1_CALM_1000` is absent from the slot table and from the mirror, and both current phases —
`TRACK1_CALM_DECIDE_0932` and `TRACK1_CALM_OBSERVE_1002` — are mirrored.

The third did not. The passing test guards the **incidents** lane, which keys on `slot_id` and was
never wrong. The **journal** and **issue** lanes key on job type, and every Track 1 strategy slot
shares one:

```text
before:  TRACK1_CALM_DECIDE_0932 failed 09:32
         TRACK1_STRESS_1035     completed 10:35
         → Calm reported lifecycle_status: recovered, recovered_at 10:35
```

A completed Stress run closing a failed Calm run. That is the Stage 5ZZU defect family — a bucket
read as a stream — one layer up, and the green test would never have found it because it watches a
different lane.

Recovery now keys on the **sleeve** for strategy slots, through a `recovery_stream()` the issue
lane defers to, so the two lanes cannot disagree:

```text
Calm failed   ← Stress completed    open       (was: recovered)
Calm DECIDE   ← Calm OBSERVE        recovered  — two phases of one sleeve's day
Swing failed  ← Swing completed     recovered
NKD failed    ← Swing completed     open
```

`job_type` is unchanged. Everything that asks *is this a strategy slot* — the chip, the
scheduler-owned list, the panel — gets the same answer it always did; only recovery is finer. A
mutation leaks the finer value into the type to prove that stays true, and another splits the
stream per **slot** so a Calm phase cannot recover its own other phase — the complement, because
separating the sleeves must not separate a sleeve from itself.

---

## 4. Live verification

```text
python monitor/ops.py restart --no-scheduler --yes --track1-only-shadow

scheduler   UNTOUCHED — pid 3000, started 2026-08-27 22:53:45
backend     35956 → 34664
```

```text
32/32 requests across the four polled endpoints → 200
shell processes before polling   24
shell processes peak while polling   24        delta 0
```

The baseline of 24 includes the measurement's own PowerShell; the number that matters is the
delta, and it is zero.

```text
python monitor/ops.py status
  track1_mode=track1-only-shadow   track1_mode_source=process_table
  track1_scheduler_mode=compatible confirmation=True legacy_entry_jobs=0
  track1_blocking=['PAPER_SHADOW_EVIDENCE']  orders_possible=False
  scheduler_pids=[3000]  backend_pids=[34664]
```

---

## 5. Results

| | |
|---|---|
| New suite | **28 passed** |
| Named + adjacent suites | **681 passed**, 1 failed |
| Mutations | **10/10 caught** |

`monitor/test_dashboard_backend.py` and `monitor/test_schedule_status_track1_20260823.py` — the
two the brief names — both pass, the latter now including the three Calm tests.

Nine tests in the Stage 5ZZW suite were moved to the new seam. They monkeypatched
`ops.track1_status` and expected the resolver to consult it; the resolver reads the cached scan
now, so they describe a seam that no longer exists. Each keeps its property and asserts it through
`_running_schedulers` instead — and the retirement fixture now writes its confirmation under
`tmp_path`, so those tests can no longer be answered by the production file.

The single remaining failure is pre-existing and previously measured: a rule grid and a
`JSON.stringify` in the market-view render path, from Stages 5ZZL/5ZZR.

### Safety

```text
scheduler pid 3000 unchanged · scheduler NOT restarted · no broker connection opened by this stage
orders_possible False · track1_blocking ['PAPER_SHADOW_EVIDENCE']
orders dir ABSENT · live_positions.track1.json ABSENT · TRACK1_ORDERS_APPROVED unset
gates, strategy logic, order logic and scheduler registrations untouched
```

The restart reconnected the read-only broker reader the backend always starts; no new connection
came from this stage's code. `ops.py` reported *"TRACK1_ORDERS_APPROVED: removed from the child
environment"* and *"orders: impossible — blocked by PAPER_SHADOW_EVIDENCE"* on the way up.

---

## 6. Still open

- `ops.py` itself still shells out, and should — it is a command-line tool, not a request path.
  What changed is that nothing on a polled path calls it. A test makes any such call an explicit
  failure rather than a slow surprise.
- The frontend keeps its own recovery lane at `realtime.js`, matching on `job_type`. It only runs
  to *name* the job that recovered one already marked recovered, so with the backend correct it
  has nothing to find — but it is a fourth lane with a coarser rule, and it is worth its own pass.
- The pre-existing render-path assertion above.
