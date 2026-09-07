# Stage 5ZZT — the SPY ladder becomes visible, and one false recovery stops

**Route:** `track1_candidate` · **Date:** 2026-08-28 · **Orders:** never enabled, still impossible

---

## 1. What was red

Stage 5ZZS left two parity tests failing on purpose. Running them showed the count was wrong —
there were **four**, in two files:

| Test | File |
|---|---|
| `test_scheduler_and_mirror_are_still_in_parity[False]` / `[True]` | 5L shared-preflight suite |
| `test_parity_report_still_true_with_the_flag_off` / `_on` | `monitor/test_schedule_status_track1_20260823.py` |

All four said the same thing, in both scheduler modes:

```text
only_in_scheduler       : ['spy_last_chance_pre_nkd', 'spy_refresh_pm_r1', 'spy_refresh_pm_r2']
only_in_dashboard_mirror: []
compared 62 · mirror rows 59          (legacy mode)
compared 132 · mirror rows 129        (track1-shadow)
```

Three jobs the scheduler runs, and no row in the panel that could report any of them late or
missing.

---

## 2. What the failure had actually cost

Before touching anything, the journal was read for the days around it. It is not hypothetical.

```text
2026-08-26  SPY_REFRESH_PM            spy_refresh_pm   completed
2026-08-27  SPY_REFRESH_PM            spy_refresh_pm   FAILED     lifecycle=open
2026-08-27  SPY_REFRESH_PM_R1         other            FAILED     lifecycle=recovered
2026-08-27  SPY_REFRESH_PM_R2         other            FAILED     lifecycle=recovered
2026-08-28  SPY_LAST_CHANCE_PRE_NKD   other            completed
```

**On 2026-08-27 every rung of the evening ladder failed**, and the 00:45 last look the next
morning is what brought the series up to date — precisely the case Stage 5ZZD built it for.

Three separate defects are visible in those five lines.

**A false recovery.** Both failed retries read `lifecycle_status: recovered`, `recovered_at
2026-08-27T22:20:14Z`. Listing every `other`-typed job that day identifies it exactly: that
timestamp is **`TRACK1_STOP_REPAIR_1820`**, a stop-repair sweep. A sweep of broker stops closed a
failed data refresh, because `later_same_stream` matches on job type and `other` is a catch-all —
and a catch-all is not a stream.

**Language that told the operator nothing.** The two retries read *"The job emitted an
unclassified error… reconcile current broker state before taking operational action"* — advice to
reconcile the broker, for a job that never touches it. The code's own comment describes this
bucket as saying something "true of anything, and tells an operator nothing".

**No row at all.** None of the three appeared on the schedule panel, so the recovery that saved
the next session was invisible and the failures could not be reported overdue.

---

## 3. What changed

### The mirror

Three rows added to `PIPELINE_FIXED_SLOTS`, with the times **read from the scheduler's
decorators**, not assumed:

| Job | Cron | Mirror row |
|---|---|---|
| `spy_refresh_pm` | mon-fri 16:20 | already there |
| `spy_refresh_pm_r1` | mon-fri 16:45 | added |
| `spy_refresh_pm_r2` | mon-fri 17:15 | added |
| `spy_last_chance_pre_nkd` | mon-fri 00:45 | added |

### The streams

The three refresh rungs now share one job type. That is not cosmetic: `later_same_stream`
matches on type, so a rung that missed and a later rung that completed now reads as a recovery
automatically, through the mechanism that already existed for stop-repair sweeps.

The 00:45 job gets **its own** type. It asks a different question — the previous *trading* day,
not today's close — so letting it mark an evening rung recovered would be a recovery for a
question that rung never asked.

### The language

The `spy_refresh_pm` branch now splits on whether a later rung caught it, exactly as the
stop-repair branch above it has always done:

- **caught** → *"This rung of the post-close SPY ladder did not run; the series was brought up to
  date when SPY_REFRESH_PM_R1 completed."* No immediate action.
- **not caught** → the original severe wording, unchanged: the series is a day short and
  tomorrow's slots meet a freshness refusal.

The softening is deliberately conditional. Stage 5ZZC's title is *"a ladder, and the measurement
that stopped it becoming an alarm nobody reads"*, and its finding was that two retries reporting
failure on every good day is an alarm people learn to ignore. Copying the 16:20 wording onto the
rungs would have rebuilt that alarm through the missed path instead of the failed one. Making it
unconditional would have been the opposite error — a total ladder failure reading mild. Both
directions are pinned by tests.

The last look states its own consequence, including the case it exists for: on a Monday the
evening ladder last ran thirty-one hours earlier.

---

## 4. The check parity could not make

Parity compares slot **ids**. A row added at the wrong minute passes it and then reports overdue
every day forever — the alarm nobody can silence, which is exactly why Stage 5ZZS declined to
add these rows without measuring the times first.

So the new suite derives the schedule from `run_scheduler.py`'s own decorators and compares
clocks, in both directions. The mutation that moves `SPY_REFRESH_PM_R1` one hour early **passes
parity** and is caught only by that test.

---

## 5. Results

```text
parity, both modes            in_parity: True   only_in_scheduler: []   only_in_dashboard_mirror: []
2026-08-27 retries            lifecycle open, recovered_at None      (the false recovery is gone)
schedule status today         0 incidents · 0 open · 0 unexplained_overdue · no SPY row overdue
track1-only mode              state_slot_count 71   (unchanged)
```

| | |
|---|---|
| New suite | **18 passed** |
| Adjacent schedule / dashboard / ops suites | **407 passed**, 5 failed |
| Mutations | **9/9 caught** |
| Caused by this stage | **0** — measured by reverting both edits and diffing |
| Fixed by this stage | 4 parity tests |

The 5 remaining failures are pre-existing and were confirmed so by reverting: three expect a
`TRACK1_CALM_1000` slot and a "Calm one-shot band" from before Calm became two phases, one pins
the old 70-slot literal, and one reads the running backend's mode.

### Safety

```text
track1_mode                track1-only-shadow      orders_possible   False
track1_blocking            ['PAPER_SHADOW_EVIDENCE']
scheduler_mode             compatible · confirmation True · legacy_entry_jobs 0
track1_runtime/orders      ABSENT      live_positions.track1.json  ABSENT
TRACK1_ORDERS_APPROVED     unset
scheduler restarted        no          backend restarted  no        broker connections  0
runtime trading files      not edited — `run_scheduler.py` was read, never written
```

The three jobs are classified `shared_infra`, are not Track 1 strategy slots
(`is_track1_strategy_job` False for all four), and the strategy slot count is 71 before and
after. They reach the gates only where they always did — through the SPY coverage and
verification records — and `may_enable_orders()` returns the same single blocker.

---

## 6. Does the dashboard need a backend restart?

**Yes.** Measured rather than assumed:

```text
backend pid 20212 started    2026-08-28 03:13:01
schedule_status.py edited    2026-08-28 04:52:17
job_journal_reader.py edited 2026-08-28 04:52:53
```

Python imports a module once per process, so the running backend holds the pre-5ZZT versions and
will keep serving the old model until it is restarted. This stage did **not** restart it: the
model was verified in-process instead, and the brief allows a restart only where display
verification explicitly needs one.

Nothing else needs restarting. The scheduler is untouched, and a backend-only restart does not
disturb it (Stage 5ZZO).

---

## 7. Still open

**The `other` bucket is still a shared stream.** Removing the SPY jobs from it fixes the
measured case, but the mechanism remains: `TRACK1_STOP_REPAIR_*` and `TRACK1_AUDIT_*` are
deliberately kept away from the legacy prefixes — the classifier's comment says the two routes'
safety jobs must stay distinguishable — and were never given types of their own. They all sit in
`other` together. Today every one of them completed, so nothing receives a false recovery; the
next time a Track 1 stop-repair sweep fails, an unrelated audit job completing afterwards will
close it. Same defect, different jobs, and it wants its own stage.

**Cross-day recovery is invisible.** The 00:45 job on the 28th genuinely repaired the 27th's
failure, and the journal reads one day at a time, so the 27th still shows three open failures
with no sign of what fixed them. Correct within a day, incomplete across the boundary.

**Five pre-existing failures** listed in §5, none of them this stage's.
