# Stage 5Q — the post-window / daily Track 1 audit, made a job

**2026-08-24 ·** scheduler **not** started, stopped or restarted (pid 33868, started
02:32:24 local = 04:32 ET, unchanged before and after this work) · backend **not** restarted ·
no IBKR connection · no order · no `--allow-orders` · `TRACK1_ORDERS_APPROVED` unset · no
`STOP_TRADING`, `STOP_TRADING.track1` or confirmation file created · no live book,
checkpoint or runtime evidence written · no commit.

---

## Verdict: **READY_FOR_THE_NEXT_SHADOW_DAYS — after one operator restart**

The exact claim, no wider: **the audit exists as production code, is scheduled in
track1-only shadow mode, and every one of its refusals has been observed failing.** It is
not yet running, because the running scheduler predates it and this stage does not restart
anything.

Not claimed: that any shadow day has passed; that Track 1 is paper- or live-ready; that the
route's trading behaviour changed in any way. It did not — nothing here is on a decision path.

---

## What was wrong before

The evidence was written every day and nothing ever read it except a dated script somebody
ran by hand:

```powershell
python scratch\track1_shadow_audit_20260824.py
```

Three problems, and each of them has already cost this project something:

| | |
|---|---|
| **Dated** | it audits 2026-08-24 for ever unless a human remembers to edit it |
| **Lives in scratch** | ordinary cleanup deletes it — the same lesson that moved the runtime evidence out of scratch in the first place |
| **Runs only when remembered** | the one morning nobody looks is a morning with no record of whether the night was judged at all |

The whole ledger design in this route rests on **absence being a signal**. It was not true of
the audit itself: an audit nobody ran left silence, and silence read as fine.

---

## What now exists

### The audit runner

`global_index/track1_shadow_audit.py` — production code, not scratch. It reads the runtime
evidence, asks the committed acceptance gate for a verdict, and appends one record per
sleeve. It opens no broker, imports no broker module, sends nothing, and writes nowhere
except its own directory.

```powershell
python -m global_index.track1_shadow_audit --latest --all
python -m global_index.track1_shadow_audit --date 2026-08-25 --sleeve roska4_calm
python -m global_index.track1_shadow_audit --from 2026-08-25 --to 2026-08-29 --all
```

Records go to a **new** directory beside the evidence, never inside it:

```text
global_index/track1_runtime/audits/track1_audit_YYYYMMDD.jsonl
```

Beside, because a judge that can edit the exhibits is not a judge — a test parses the
module's source and requires every write in it to go through one path builder, and another
test hashes the whole evidence tree before and after a run.

Append, not rewrite. Calm is judged at 10:10 and Stress at 12:40, and a rewrite would make
the morning's record of whether Calm was ever judged disappear at lunchtime.

### Where the rules live — not in the runner

Every judgement comes from `global_index/track1_shadow_acceptance.py`, the gate whose
thresholds were committed before any shadow day existed. Stage 5Q added **scope** to that
module and nothing else:

| New public function | Answers |
|---|---|
| `evaluate_sleeve(day, sleeve, …)` | one window on one day |
| `evaluate_day_audit(day, …)` | all four sleeves plus the committed daily gate, side by side |
| `sleeve_slot_ids(sleeve)` | which slot ids that sleeve should have fired |
| `windows_status(…, day=…)` | the existing function, now able to answer about a day that is not today |

The expected slot counts, the 300-second ceiling, the 240-second target, the fail-closed
coverage rule and the freshness contract are all read from where they already lived. There is
no second copy, and that is deliberate: two copies of "what counts as complete" drift, and the
operator gets shown whichever one is looser.

### The four verdicts

| Verdict | When |
|---|---|
| **PASS** | the window closed with the scheduler up for all of it, coverage is complete, every registered slot id wrote a row, timing exists, explanations carry freshness proofs where the ledger says candidates were explained, orders were impossible, the checkpoint names this route and this day |
| **NOT_ENOUGH_DATA_YET** | the window has not closed; **or** it closed before the scheduler existed; **or** the scheduler joined it halfway; **or** it closed leaving no evidence at all *and* the scheduler's start instant could not be read |
| **WARN** | p95 at or over the 240s target but under the 300s ceiling |
| **FAIL** | a judgeable window with a gap: incomplete or unobserved coverage, a missing slot id, no timing, p95 at or over 300s, any single slot at or over 300s, explanations missing when the ledger says some were due, an explanation without a freshness proof, an order mark, an open order gate, a confirmation file, or a checkpoint naming the wrong route or the wrong day |

**Absence is never a default pass.** A sleeve with no timing FAILS. A sleeve with no ledger
rows FAILS on coverage. A sleeve with no explanations passes only when the ledger's own
`explained` counter records that none were due — a positive record saying zero, named in the
audit as `no_candidates_to_explain`, so it can never be confused with explanations that went
missing.

### The false alarm this had to not create

The NKD window of **2026-08-24** ran 01:10–02:55 ET; the track1-only scheduler started at
04:32 ET. The whole window had passed two and a half hours before the process existed. That
is `NOT_ENOUGH_DATA_YET` and it is not a failure — nothing was ever asked to run.

Run against the **live** tree at 07:43 ET today, read-only, writing nothing:

```text
scheduler start: process_table - scheduler pid 33868 started 2026-08-24 02:32:24 local

  global_nkd     01:10-02:55  NOT_ENOUGH_DATA_YET  window_closed_before_scheduler_start
      scheduler started 04:32:23 - AFTER the window closed at 02:55:00; no slot was ever due
  roska4_calm    10:00-10:00  NOT_ENOUGH_DATA_YET  window_not_closed
  roska4_stress  10:35-12:30  NOT_ENOUGH_DATA_YET  window_not_closed
  roska4_swing   14:05-15:55  NOT_ENOUGH_DATA_YET  window_not_closed

  DAY 2026-08-24   verdict NOT_ENOUGH_DATA_YET
```

The rule has three limits so it cannot hide a real miss, and each is pinned by a test:

| Limit | What it stops |
|---|---|
| The window must have CLOSED | a window still open is pending for that reason and says so, without mentioning uptime |
| The start instant must be READABLE | "could not read it" is reported as unknown, never as "no scheduler". Folding those two together is the fail-open shape that once let a second scheduler start, and two schedulers on one client id cost six entry slots |
| No evidence at ALL | a sleeve with ledger rows had a process. Its incomplete coverage stays a failure whatever the process table says |

### How the audit learns when the scheduler started

Three sources, in order, and each is labelled in the record:

```text
argv            the scheduler hands the child its own start instant
process_table   monitor.ops.scheduler_processes(), best effort
unknown         reported as unknown, never as "no scheduler"
```

The scheduler passes its own, because `scheduler_processes()` returns an **empty list** on
any hiccup and an empty list reads as "nothing running". The process table also reports
machine-local time — this box runs Calgary, ET-2 — and the conversion to ET happens in one
place. Two hours is exactly enough to move the NKD window across a scheduler start and
reverse the verdict.

---

## The scheduled jobs

Five, registered in **track1-only shadow mode only**, times DERIVED from the same window
table the slots come from:

| Job | ET | Audits |
|---|---|---|
| `track1_audit_global_nkd` | 03:05 | the NKD window that closed at 02:55 |
| `track1_audit_roska4_calm` | 10:10 | the Calm shot at 10:00 |
| `track1_audit_roska4_stress` | 12:40 | the Stress window that closed at 12:30 |
| `track1_audit_roska4_swing` | 16:05 | the Normal-R4 window that closed at 15:55 |
| `track1_audit_daily` | 16:15 | all four sleeves, plus the committed daily gate |

**The ten-minute buffer is measured, not taste.** The last slot of a window fires AT the
close minute and may legitimately run to the 300-second cadence ceiling the acceptance gate
enforces — so close + 5 minutes is the earliest the window is guaranteed to have finished
writing. The other five are margin, and they are what stops the audit from reading a
half-written window and calling a slot silent that was still running. A test asserts the gap
is at least the ceiling, and the mutation that shortens the buffer to one minute reds it.

What the audit children carry, and what they never carry:

```text
python -m global_index.track1_shadow_audit --latest --sleeve <sleeve> --scheduler-started <ET>

no --allow-orders     no --bar-provider     no --port     no --window
no broker import, measured in a fresh interpreter
```

### Inventory

| Mode | Before | After |
|---|---:|---:|
| default | 60 | **60** |
| `--track1-shadow` | 129 | **129** |
| `--track1-only-shadow` | 95 | **100** |

The five are the audit jobs and nothing else. Legacy strategy jobs remain **0** in
track1-only. Scheduler/dashboard-mirror parity holds in all three modes, because the mirror
reads the SAME table the scheduler registers from — a job the scheduler runs and the mirror
does not know about appears on the operator's screen as a phantom overdue row every day, and
one the mirror does not expect can never be reported missing at all.

The audit ids start `TRACK1_`, so they inherit the pre-start classification: an audit whose
instant passed before this scheduler existed reads `not_applicable`, not `late`.

### Exit code

`0` whenever the audit itself ran, whatever verdict it reached. A FAIL verdict is data and it
belongs in the record and on the dashboard. Making the process exit non-zero would put "the
shadow window had a gap" and "the audit tool is broken" behind the same red light in the
scheduler log. `--exit-nonzero-on-fail` exists for a caller that wants the other behaviour;
the scheduler job does not pass it.

---

## The dashboard

`/api/v1/track1-runtime` now carries an `audits` block, and the Track 1 Runtime panel shows
one more row:

```text
Audit verdict   2026-08-25: PASS - global_nkd=PASS, roska4_calm=PASS, ...
Audit verdict   audit not run yet (no audit directory)
Audit verdict   2026-08-25: day roll-up not run yet - not audited yet: roska4_swing
```

Three states, never two, and the middle one is the whole point: **an audit that has not run
is not a pass.** Before this row existed the page showed coverage and timing and said nothing
about whether anyone had ever judged them, so a day nobody audited looked exactly like a day
that passed. The tone is driven by the verdict and a missing audit is never green.

The reader stays read-only — the Stage 5P source scan that forbids every write call in that
module is re-run here, because 5Q edited the file it protects.

---

## Two things found by running it, not by reading it

**The headline said PASS about a day nobody judged.** Run against the live tree at 07:43 ET,
under four `NOT_ENOUGH_DATA_YET` rows, the last line of the report read
`WORST VERDICT: PASS` — because the roll-up seeded itself at PASS and then skipped every
pending record. The line an operator reads first must not be able to claim a pass over a set
of records that judged nothing. Fixed, and both directions are pinned by tests; mutation Q16
restores the defect and reds the guard.

**A verdict could have been lost to a dash.** A scheduled child writes into a pipe, and on
Windows a pipe takes the locale codepage. The report carries em dashes and cp1252 cannot
encode them — the same failure that once killed `deploy_sim` on its last print after 3m51s of
correct work. The audit now reconfigures its streams to replace rather than raise, and a test
runs it under a forced `PYTHONIOENCODING=cp1252` and requires exit 0.

---

## Tests

| Suite | Result |
|---|---|
| **Stage 5Q** `test_track1_stage5q_post_window_audit_20260824.py` (new, 67) | **67 passed** |
| **Stage 5Q mutation harness** (new, 16) | **16 / 16 detected**, four production files restored byte-for-byte |
| Stage 5P readiness + operator text | **35 + 20 passed** |
| Track 1 scratch sweep (5Q, 5P ×2, 5O, 5N, 5M-B/C/D, 5L, 3B, dashboard wiring, pre-sleep ×2, ops status) | **493 passed, 1 skipped** |
| `monitor/` production suites (dashboard backend, schedule-status Track 1, realtime contract, realtime DOM) | **295 passed** |
| `monitor/` remaining (ops, paper DOM, realtime skin, no-zero-for-missing) | **31 passed** |

`global_index/test_event_playback.py` **not run** — still the known hang.

### The sixteen mutations

Every one is of the form "remove one way the audit can say no", because those are the
mutations that leave a suite green and an operator confident.

```
Q1   slot IDS stop being checked, only the count            -> the doubled-slot test reds
Q2   the p95 ceiling is raised above the cadence            -> the 310s test reds
Q3   the p95 target is moved so a 250s day stops warning    -> the WARN test reds
Q4   a single 301s slot stops counting as a stall           -> the stall test reds
Q5   a pre-start window is called a FAILURE                 -> the 2026-08-24 NKD test reds
Q6   an unreadable start is read as "the scheduler was up"  -> the blind-window test reds
Q7   a window with no timing evidence passes                -> the missing-timing test reds
Q8   explanations may vanish when the ledger says otherwise -> the explanations test reds
Q9   an order mark stops failing the audit                  -> the order-mark test reds
Q10  the audit record loses its route stamp                 -> the route-stamp test reds
Q11  the audit writes into the evidence directory           -> the write-scope test reds
Q12  the dashboard stops saying an audit has not run        -> the absence test reds
Q13  an audit argv gains --allow-orders                     -> the argv probe reds
Q14  the audit buffer drops below the runtime ceiling       -> the buffer test reds
Q15  the mirror stops expecting the audit jobs              -> the parity test reds
Q16  the headline says PASS over records that judged nothing-> the headline test reds
```

Q15 is worth naming. The first form renamed a job id inside the shared table — and that
mutation is **unfaithful**, because the scheduler and the mirror read the same table, so both
sides moved together and the test stayed green. The drift that can actually happen lives in
the mirror itself, so the mutation had to break the mirror. Same family as Stage 5P's P3, and
recorded here for the same reason.

### Two inventory tests went red, and that is what they are for

`test_the_full_inventory_in_all_three_modes` and four Stage 5M-D counts pinned 95 jobs and
Track 1 row counts. They reded on the intended change and were updated to count the audit
jobs **from their own table**, not to a new literal.

One of them was also repaired rather than re-pinned: the argv probe classified children by
the presence of `--sleeve`. The audit children carry `--sleeve` too, so the old classifier
would have counted four audits as strategy slots and still passed. It now keys on the MODULE
each child runs.

---

## What is NOT claimed, and what remains open

- **The audit is not running yet.** The scheduler process (pid 33868) started at 04:32 ET,
  before this code existed, and this stage does not restart anything. Until the operator
  restarts it, the five audit jobs exist only on disk.
- **The dashboard `audits` block is not live yet** for the same reason: the running backend
  predates it. The backend also still needs the restart the pre-sleep note asked for.
- **No shadow day has passed.** Nothing has run; `window_coverage/` and `slot_timing/` are
  still empty directories and the current verdict is `NOT_ENOUGH_DATA_YET` on every sleeve.
- **The committed daily acceptance gate is stricter than the audit's operational roll-up, and
  it is reported unchanged beside it rather than softened.** In particular that gate requires
  explanation rows for the DAY, so a session in which every sleeve legitimately found no
  candidate would not satisfy it. The audit prints both answers; which one governs the
  shadow-period decision is the project owner's call, not the audit's.
- **A window whose slots all RAN but all REFUSED reads as incomplete.** `window_closed`
  counts only slots that *decided*, and a refusal — gate, freshness, live-source-not-ready —
  does not count. That is the committed rule and this stage did not change it, but it is the
  most likely way a first live day produces a FAIL that is really "the route refused by name
  all afternoon". Worth watching on the first judgeable day rather than discovering at 16:15.
- **Not measured here:** broker-flat, orphan working stops, the legacy book's drain, or
  anything requiring an IBKR connection. This work did not connect.

---

## Files

**Added**

```text
global_index/track1_shadow_audit.py                              the audit runner
scratch/test_track1_stage5q_post_window_audit_20260824.py        67 tests
scratch/track1_stage5q_mutations_20260824.py                     16 mutations
scratch/track1_stage5q_post_window_audit_report_20260824.md      this report
scratch/track1_stage5q_post_window_audit_report_20260824.json    the same, machine-readable
```

**Changed**

```text
global_index/track1_shadow_acceptance.py   + evaluate_sleeve / evaluate_day_audit /
                                             sleeve_slot_ids / windows_status(day=)
global_index/track1_slots.py               + track1_audit_jobs() / audit_job_argv()
global_index/run_scheduler.py              + the five audit jobs (track1-only only)
                                           + _PROCESS_START_ET, handed to the children
monitor/backend/schedule_status.py         + the audit jobs mirrored from the same table
monitor/backend/track1_runtime_reader.py   + the audits block
global_index/dash/realtime/realtime.js     + the Audit verdict row
scratch/test_track1_stage5p_*.py           inventory counts derived, argv probe repaired
scratch/test_track1_stage5m_d_*.py         inventory counts derived
```

Nothing under `global_index/track1_runtime/` was written. No book, no checkpoint, no
confirmation file exists.

---

## The operator page

One command, and it is the same restart the pre-sleep note already asked for:

```powershell
python monitor\ops.py restart --backend
```

That brings the dashboard's `audits` block and the pre-start classifier live. It does not
schedule the audit jobs.

To schedule them, the scheduler has to come up on the new code:

```powershell
python monitor\ops.py restart --scheduler --track1-only-shadow
```

**Timing matters and it is the operator's call.** Restarting the scheduler makes every window
that already closed today read as pre-start. Right now (07:43 ET) only NKD has closed, so a
restart before 10:00 ET costs nothing further; a restart after 15:55 would mark the whole day
pre-start.

Either way the audit can be run by hand at any time, against any day, without restarting
anything:

```powershell
python -m global_index.track1_shadow_audit --latest --all
```

The first NKD window fully covered by scheduler uptime remains **Tue 2026-08-25,
01:10–02:55 ET** — 22 slots, the first judgeable window of the shadow period, and the first
one the 03:05 audit job would grade.

---

## Corrections and follow-up (appended 2026-08-24, Stage 5Q-1)

Nothing above is rewritten. What it got wrong is recorded here.

### 1. The operator command was wrong

This report gave `python monitor\ops.py restart --backend`. **That flag does not exist.**
Verified against the real CLI:

```text
usage: ops.py restart [-h] [--scheduler] [--no-scheduler] [--no-shadow-resume]
                      [--yes] [--assume-preflight-ok] [--track1-shadow]
                      [--track1-only-shadow]
```

Backend-only is `--no-scheduler`, and the Track 1 flag still has to be passed, because it is
what tells the **backend** which slot table to mirror:

```powershell
python monitor\ops.py restart --no-scheduler --track1-only-shadow
```

### 2. The scheduler restart happened, and it was the operator, not this work

This report named pid 33868. The scheduler running now is **pid 6880, started 06:23:03 local
= 08:23 ET**. It logged `Jobs (100)` and all five audit ids, so **the audit jobs are already
live** and the "restart the scheduler to schedule them" step is done.

### 3. Two of the audit's checks would have produced false results, and neither was on the
open-items list

Both found by RUNNING the code against a temp tree rather than by reading it:

- **The explanation reader was pointed at a path nothing writes.** The live writer nests
  under the window name — `.../shadow/explanations/live_<date>/explanations_<date>.jsonl` —
  one directory deeper than the gate looked. On the first real shadow day both the
  `explanations` and the `freshness_proofs` checks would have failed a route that wrote its
  explanations correctly. Repaired in 5Q-1; the dashboard's own counter had the same bug.
- **"No candidate" was never the problem.** This report's open item said a slot that found no
  signal did not count toward coverage. Measured: such a slot already records `decided=True`.
  The refusal that was actually being miscounted is the CLOCK one (`too_early`/`too_late`),
  which for NKD becomes twelve of twenty-two slots every winter once US DST ends.

### 4. A third finding, not fixed, now a named blocker

The live writer opens the day's explanation file with `mode="w"` on **every** slot, and all
four sleeves share one file per session date — so only the last slot's rows survive. Measured
by writing two slots in a row. Recorded as blocker **B-5R-1**; the audit names it rather than
charging the gap to a sleeve.

Full detail: `scratch/track1_stage5q1_audit_semantics_report_20260824.md`.
