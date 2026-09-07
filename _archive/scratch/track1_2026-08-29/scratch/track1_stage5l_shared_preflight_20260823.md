# Stage 5L — the 13:45 pre-flight becomes shared production infrastructure

**2026-08-23 · no scheduler, backend, or dashboard started or stopped · no IBKR connection ·
no order · no `STOP_TRADING` or `STOP_TRADING.track1` created or removed · no confirmation
file · no commit.**

---

## Verdict: **READY_FOR_5M_NORMAL_R4_PROMOTION**

All four conditions met, each by measurement:

| Condition | Evidence |
|---|---|
| pre-flight functionally unchanged | trigger, both child commands, the record it writes, and its fail-closed direction are all asserted against the built scheduler and a captured argv — not against the source text |
| classified and protected as shared infra | `route_classification()` buckets all 60/84 jobs with **zero unclassified**; the retirement set excludes it in both modes |
| freshness contract pinned | the 13:45 boundary is asserted from both sides and compared against the scheduler's own trigger |
| dashboard parity holds | `parity_report()` true with the flag off and on |

**49 Stage 5L tests pass. 7 of 7 mutations are detected** — every protection has been shown to
go red when the thing it guards is removed.

---

## But first: I damaged two production state files, and it was not this stage

I have to lead with this because it contradicts something I told you yesterday.

**What happened.** `global_index/preflight_state.json` and `global_index/maxhold_state.json`
were both overwritten at **20:03:21 on 2026-08-23**, in the same second, each reduced to a
single key:

```
{"2026-08-23": true}
```

**Who did it.** I did — in the *previous* turn, during the legacy→Track 1 audit I reported as
read-only. To capture the exact commands the safety jobs spawn, a probe of mine fired the
pre-flight and max-hold job bodies with the subprocess runner patched out. Patching the runner
stops any child process from starting; it does **not** stop the job's success path from writing
its own state file. Those two jobs are the only ones whose bodies write state, and I fired both.

**So the "no side effects" line in
[track1_legacy_to_track1_full_route_audit_20260823.md](scratch/track1_legacy_to_track1_full_route_audit_20260823.md)
is wrong.** That audit had side effects. This report is the correction.

**How I know it was not the real scheduler.** The scheduler's own log shows the last genuine
pre-flight on 2026-08-21 and names its next run as 2026-08-24. The job is Mon–Fri and
2026-08-23 is a Sunday. There is no legitimate Sunday record.

**What was lost.** The real weekday records — at minimum 2026-08-20 and 2026-08-21.

**What it costs right now: nothing.** The running scheduler read that file once, at startup on
2026-08-20, and has held the full dictionary in memory ever since — the loader is called only
from `main()`. It is not re-read. On Monday at 13:45 that live process writes its own
in-memory dictionary back out, which **restores the real records by itself**.

**The condition on that.** Self-healing only holds if the scheduler is not restarted before
Monday 13:45. If it is restarted first, it reloads the damaged file, and the Monday NKD night
slots at 01:10–02:55 — which read the *previous business day*, 2026-08-21 — find no record and
fail closed. Every night slot skipped. That is the safe direction, and it is silent.

**Why I did not repair it.** Writing `true` for a day I did not observe is fabricating exactly
the evidence the record exists to hold; a fail-closed gate whose evidence I invented is not a
gate. The 2026-08-21 pre-flight *is* independently attested by the scheduler log, so a repair
is reconstructable rather than invented — but it is a write to live state that races a running
process, and that is your call, not mine. **If the scheduler is going to be restarted before
Monday 13:45, repair it first.**

**What stops it recurring.** A test now fires both job bodies the unsafe way with the write
paths redirected and asserts the real files did not move — and it refuses to pass at all if
neither file exists, rather than passing vacuously. Mutation M7 confirms it goes red when a
body writes past the redirect.

**Why I did not catch it yesterday.** The repository has a tripwire in `conftest.py` that
prints when a test touches guarded state. It *printed*. I piped that run through `tail` and cut
the message off — the exact failure mode already written down in my own notes as "don't pipe a
long run through `tail`".

---

## What changed

Four files, and only one of them contains executable logic that is new.

**`global_index/run_scheduler.py` — comments only.** The job block and the module docstring now
say what the pre-flight is: shared infrastructure that both routes read, not a legacy strategy
job. The comment names its three consumers, states that Track 1's morning slots run on D-1 data
by contract, and records why the job's *name* must not be tidied up.

**`global_index/track1_freshness.py` — docstrings only.** "The Track 1 reading of the legacy
pre-flight record" became "…of the SHARED pre-flight record". The line "Track 1 does not own
this file" was misleading in a way that mattered — it read as *this belongs to someone else*
when the true statement is *one writer, many readers*. No code path altered.

**`global_index/track1_slots.py` — the new part.** A classification table and three functions:

```
SHARED_INFRA_JOBS            preflight, heartbeat, session_report_fallback — and why each
route_classification()       every registered job, bucketed, read from the scheduler itself
legacy_retirement_candidates()  exactly what a retirement may remove — nothing else
surviving_jobs()             the complement, derived, not a second hand-written list
```

Measured, both modes:

| | shared infra | legacy entry | safety | Track 1 | **unclassified** | total |
|---|---|---|---|---|---|---|
| flag off | 3 | 45 | 12 | 0 | **0** | 60 |
| flag on | 3 | 45 | 11 | 25 | **0** | 84 |

The `unclassified` column is the point. A hand-written list of legacy jobs cannot notice a job
nobody wrote a rule for — it just omits it, silently. This derives every bucket from the
scheduler that actually runs, so tomorrow's unclassified job turns the suite red.

(Safety drops 12 → 11 with the flag on because the 12:20 stop-repair sweep is displaced by
Track 1's Stress window. That was already true; it is now visible in a table.)

**`docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md` — append-only section 6.** States the rule, the
accident it prevents, the D-1 contract, and the two things that must not move.

---

## What intentionally did NOT change

This is the more important list, because Stage 5L was an **ownership** change and every line
below is something it would have been easy to "improve" while in there.

**The job's display name.** This is the one I expected to change and did not, and the reason is
worth stating plainly: the name looks like a label and is load-bearing. The dashboard's job
journal maps a run back to a job by matching the name **prefix** `"Pre-flight update"`. Rename
the job to something clearer — `"Shared data refresh 13:45 ET"` — and the mapper returns
nothing, drops the run, and every pre-flight vanishes from the Job Journal. No error, no
warning; a job that runs fine and reports nowhere. That is the same "does this show up
anywhere?" failure family that has already produced two jobs running nightly and appearing in
no reader. Ownership is now stated in the comments and enforced by the classification table,
where saying it costs nothing. A test pins the name against the journal's own mapper, so
reverting this decision is no longer free.

**The job id `preflight`.** The dashboard mirror keys on it.

**13:45.** Both the trigger and `required_data_through` hold it, and a test now compares them
to each other so moving one alone turns red.

**The body.** Still `update_ibkr_daily`, then `update_spy_csv --csv spy_daily_live.csv`, then
the record. Still fail-closed: a failure records `False` and does **not** run the second step.

**`required_data_through` semantics.** Untouched.

**No pre-market refresh.** A second refresh before 10:00 would turn the morning Track 1 slots
from D-1 into same-day and silently invalidate every measured Track 1 number. A test asserts
the 13:45 job is the only updater in the schedule — checked against the schedule, not against a
comment promising it.

**`conftest.py`.** Its tripwire prints rather than failing, deliberately, and that is documented
in its own docstring. Making it fail is a decision about the whole suite, not a side effect of
this stage. Worth revisiting — it is the check that would have caught yesterday's damage on the
day it happened, if I had read its output.

---

## Test results

| Suite | Result |
|---|---|
| **Stage 5L** `test_track1_stage5l_shared_preflight_20260823.py` | **49 passed** |
| Stage 5L mutation harness | **7 / 7 detected** |
| `monitor/test_ops.py` | 8 passed |
| `scratch/test_track1_stage3_route_20260822.py` | 41 passed, 1 skipped |
| `scratch/test_track1_stage3b_blockers_20260822.py` + `monitor/test_schedule_status_track1_20260823.py` | 98 passed, 1 skipped |
| `global_index/test_scheduler_heartbeat.py`, `test_maxhold_catchup.py`, `test_scheduler_shadow_verify.py` | passed |
| `scratch/test_track1_stage4_production_clean_20260823.py` | **1 failed**, rest passed |
| `scratch/test_track1_stage5z_freshness_root_20260823.py` | **3 failed**, 42 passed |

`global_index/test_event_playback.py` was **not run** — it is still the known hang.

### The two failures, and why neither is Stage 5L

**Stage 4, one test — a stale stub, pre-existing.** `test_c_a_track1_slot_calls_the_shadow_route_and_nothing_else`
replaces the subprocess runner with a lambda that has no `route` parameter. Stage 5I later
taught the Track 1 slot to stamp its route, so the real call now passes `route=` and the stub
raises `TypeError`. Nothing to do with the pre-flight; my Stage 5L edits to that file are
comments. The fix is one line — add `route=None` to that lambda's signature — but the test
belongs to another stage and I have left it so its failure stays attributable.

**Stage 5Z, three tests — caused by the damaged state file, not by code.** They pin a replay at
2026-08-21 12:00, which requires a pre-flight record for 2026-08-20. That record is one of the
ones my probe destroyed, so the gate now refuses where those tests measured it passing. They
will pass again once the record is restored — either by Monday's 13:45 run or by a repair. I
have deliberately not "fixed" them by moving their pinned clock: that would hide the damage
behind a green suite.

---

## No side effects — this stage

* No scheduler, backend, or dashboard started or stopped. The running scheduler (pid 36656) was
  read about, never signalled.
* No IBKR connection. No order.
* No `STOP_TRADING`, no `STOP_TRADING.track1`, no confirmation file created or removed.
* No commit.
* `preflight_state.json` and `maxhold_state.json` were **verified byte-identical before and
  after every run in this stage**, including the mutation harness — the mutation that proves
  the guard works runs against temp copies precisely so the real files cannot be touched while
  proving it.

The damage described at the top of this report happened in the **previous** turn and is
recorded here because that turn's report claimed otherwise.

---

## Next

Stage 5M — promote Normal-R4 into Track 1 slots covering 14:05–15:55. That is the audit's
blocker L1, and the expensive one: legacy's swing is a different strategy, not a differently
wired one.

Before that, one operational decision is yours: **if the scheduler will be restarted before
Monday 13:45 ET, repair `preflight_state.json` first**, using the 2026-08-21 pre-flight the
scheduler log attests to. If it will not be restarted, the file repairs itself at Monday 13:45.
