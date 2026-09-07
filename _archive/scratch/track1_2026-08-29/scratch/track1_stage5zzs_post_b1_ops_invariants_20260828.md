# Stage 5ZZS — the ops tests catch up with a world where B1 is closed

**Route:** `track1_candidate` · **Date:** 2026-08-28 · **Orders:** never enabled, still impossible

---

## 1. The ten, and what each was actually saying

They arrived looking like one family. They are two, and the difference matters — half of them
have nothing to do with B1 at all.

### Family A — six stale pre-B1 assumptions

| Test | Asserted | Why it went red |
|---|---|---|
| `test_no_switch_or_confirmation_file_exists` | the confirmation file is absent | Stage 5ZZJ placed it on 2026-08-27 |
| `test_nothing_real_was_created_by_this_suite` | the same | the same |
| `test_30_no_order_journal_book_or_confirmation_exists` | the same | the same |
| `test_it_refuses_when_the_confirmation_file_exists` | the file alone refuses a shadow start | Stage 5ZZN narrowed that rule |
| `test_status_reports_what_an_operator_must_see` | B1 is in `blocking` | Stage 5ZZK closed B1 |
| `test_28_orders_are_still_impossible` | the same, plus the file is absent | the same |

Three of the six asserted the **absence of a file the operator deliberately signed**. That is
not a safety assertion; it is an assertion that nobody had decided anything.

### Family B — four stale post-refactor assumptions, unrelated to B1

Stage 5ZZC moved the SPY refresh body out of `job_spy_refresh_pm` and into a shared
`_spy_refresh` helper, and Stages 5ZZC/5ZZD added three more rungs to the ladder.

| Test | Asserted | Truth |
|---|---|---|
| `test_27_a_label_drift_is_now_visible_as_a_job_failure` | `--verify-strict` is in the job body | it is in `_spy_refresh`, one call deeper |
| `test_5_spy_refresh_pm_emits_normal_job_evidence` | one `_run(label="SPY_REFRESH_PM")` call site | the label became a parameter |
| `test_1_the_inventory_is_101_jobs...` | 70 slots, 4 shared-infra jobs, 101 total | 71 slots, and three jobs nobody had classified |
| `test_13_the_route_health...` | the mirror tracks 70 slots | it tracks 71 |

`test_27` is the one that mattered. Its failure message read *"the post-close refresh no longer
runs strict, so a drift exits 0 again"* — which, had it been true, would have meant a regime
label drift silently exiting zero every evening. It is not true. The flag is at
[run_scheduler.py:995](global_index/run_scheduler.py#L995), inside the helper the job delegates
to. A test that reads one function body cannot survive that body moving.

---

## 2. Did any test expose a real defect?

**Yes, one — and it is the defect the module was designed to surface.**

`route_classification` buckets every registered job, and its own comment says:

> *a job added tomorrow lands in `unclassified` and turns the Stage 5L test red — the one
> outcome a hand-written list could never produce.*

That is exactly what happened. `spy_refresh_pm_r1`, `spy_refresh_pm_r2` and
`spy_last_chance_pre_nkd` were registered by Stages 5ZZC and 5ZZD and never named, so the
classifier had been returning them as `unclassified` ever since, with the test red and waiting
for someone to come and name them. The mechanism worked; nobody answered it.

It was **fail-closed throughout**. `legacy_retirement_candidates` returns only the
`legacy_entry` bucket, so an unclassified job was never removable and the legacy job count was
never inflated by one. Measured before and after: `_bucket_for("live_day_0935")` is
`legacy_entry` either way.

They are now declared as shared infrastructure — they refresh the regime CSV that **both** routes
read, and none of them decides a trade — in the production table and, by hand, in the 5L
survivors list that deliberately does not derive from it.

### A second real defect, measured but NOT fixed here

The dashboard's schedule mirror does not know those same three jobs.
[schedule_status.py:181](monitor/backend/schedule_status.py#L181) lists only `SPY_REFRESH_PM`,
so `parity_report` returns:

```text
only_in_scheduler: ['spy_last_chance_pre_nkd', 'spy_refresh_pm_r1', 'spy_refresh_pm_r2']
```

Three jobs run every night and the schedule panel has no row to report them late or missing.
This is the same root cause as the classification gap — a job added without being written into
the hand-written tables that describe it — and it is the recurring shape this project has met
before: *the thing runs, and it shows up nowhere.*

It is **left red on purpose**. Adding rows to the dashboard's expected-slot model is a different
subsystem, and a row for a job that does not fire when expected creates a permanently-red alarm,
which is the failure mode this project has already paid for. It needs its own stage, with the
cron times measured rather than assumed. The two parity tests stay red so the alarm keeps
ringing; they were red before this stage and are not counted as its work.

---

## 3. The new post-B1 invariants

Every repair removed an assertion that used to fail, so the cheap way to make ten tests green
would have been to assert less. These are what replaced them.

| # | Invariant | Where |
|---|---|---|
| I1 | Orders are impossible, and something **measured** is what holds them | `test_28` |
| I2 | B1 closed requires a **signature** — take it away and B1 returns | `test_28` |
| I3 | B1 closed requires a **measurement** — make the composite fail while signed, and B1 returns | `test_28b` *(new)* |
| I4 | Nothing a signature or an environment variable can do releases what is holding orders | `test_28c` *(new)* |
| I5 | A confirmation on disk must be **signed**, and must not imply `orders_possible` | `test_30`, ops-status-mode, 5S |
| I6 | The confirmation file alone does **not** refuse a shadow start | `test_the_confirmation_file_alone_no_longer_refuses_a_shadow_start` |
| I7 | …but a confirmation **plus every order blocker clear** still does | the same test, second half |
| I8 | A legacy entry start **is** refused while the decision says legacy retired, and the refusal names the mode that is allowed | `test_a_legacy_start_is_refused_...` *(new)* |
| I9 | Shared-infra membership is exact in **both** directions, against the production classifier | `test_4` |
| I10 | Nothing is unclassified, and the counts are **derived** from the tables | `test_1` |

I6 and I7 are one test on purpose. Narrowing the refusal without I8 would have been a straight
loss: the signature stops refusing the safe mode and nothing refuses the unsafe one. That is the
trade Stage 5ZZN made, and it is now pinned from both sides.

I4 never sets `TRACK1_ORDERS_APPROVED` — not even under monkeypatch. It asserts the stronger
structural fact: everything currently holding orders is a `MEASURED_GATE` with `released_by ==
()`, and the registry does not read the environment on its way to that answer.

---

## 4. Three things the mutations caught in my own work

The harness refused to score anything it could not first prove green, which is how all three
surfaced rather than being written down as successes.

**My test could not tell the two halves of B1 apart.** Waiving the B1 measurement entirely left
the whole suite green. `test_28` shows the *signature* is necessary — remove it and B1 returns —
and I had assumed that also showed the *measurement* was. It does not: B1 is a decision gate, so
it reappears unsigned whatever the measurement says. One half of the rule was being asserted
twice. `test_28b` makes the other half.

**Nothing asserted the approval variable is harmless.** Every test said the variable was
*unset*. None said what happens if it is set. A mutation opening orders on that variable stayed
green across the suite, because an assertion about the environment is not an assertion about the
gate. `test_28c` closes it.

**Two mutations came back green honestly, and were right to.** Breaking the `unclassified`
fallback proves nothing today — once the three rungs were declared, no registered job reaches
that line, so the edit was to unreachable code. A mutation on a path the tests never execute is
not a passing test; it is a mutation that never ran. Retargeted at the opposite direction — every
job bucketed as shared whether declared or not — it goes red.

And one plain error of mine: I asserted `conf.get("confirmed_by")`, but that is an attribute of
`Confirmations`, not one of its flags, so a properly signed decision read as unsigned. The test
caught it on the first run.

---

## 5. Attribution — which failures are this stage's

33 tests were failing in the wider slot and scheduler suites. Rather than reason from their
names, the one production edit was reverted, the same suites re-run, and the two failure sets
diffed:

```text
pre-existing (fail both ways): 29
CAUSED BY MY CHANGE          :  1   test_the_shared_infra_table_covers_exactly_the_jobs_that_must_survive
FIXED BY MY CHANGE           :  2   test_every_registered_job_is_classified[False] / [True]
```

The one I caused is the hand-written `REQUIRED_SURVIVORS` list, which the 5L suite keeps
deliberately un-derived — its comment records that an earlier version iterated the table it was
guarding and therefore agreed with whatever the table said. The three names were added by hand,
which also gives each its own parametrised survival case.

Guessing from the names would have put `test_b1_still_blocks_orders` in the wrong bucket: it
reads like mine and is not.

---

## 6. Results

| | |
|---|---|
| Ops, gates and readiness suites | **363 passed**, 2 failed |
| The 2 failures | the mirror-parity alarm of §2, pre-existing and deliberately left ringing |
| Mutations | **11/11 caught** |
| Tests added | 4 (`test_28b`, `test_28c`, the legacy-start refusal, and 3 new survivor cases) |
| An eleventh stale test | found in the 5S readiness suite while running the adjacent work, repaired the same way |

### Safety after

```text
track1_mode                track1-only-shadow  (from the process table)
track1_blocking            ['PAPER_SHADOW_EVIDENCE']
orders_possible            False
scheduler_mode             compatible · confirmation True · legacy_entry_jobs 0
track1_runtime/orders      ABSENT
live_positions.track1.json ABSENT
TRACK1_ORDERS_APPROVED     unset
scheduler restarted        no        broker connections  0
runtime trading files      not edited
```

`run_scheduler.py` is a runtime trading file and the two mutations that break it run against a
temp **copy**, with the real file's digest checked before and after. "It is restored a few
seconds later" is not an answer when a killed process would leave the live scheduler's own module
broken on disk.

---

## 7. Still open

- The dashboard schedule mirror does not model the three SPY-ladder jobs (§2). Needs its own
  stage, with the cron times measured.
- 29 pre-existing failures in the wider slot and scheduler suites, outside this stage's scope:
  a `live_day` / `maxhold_exit` aliasing group, job-count literals, and a rendered-blocker
  pinning mismatch.
- `PAPER_SHADOW_EVIDENCE` remains the sole thing between this route and an order, and it is
  measured, not signable.
