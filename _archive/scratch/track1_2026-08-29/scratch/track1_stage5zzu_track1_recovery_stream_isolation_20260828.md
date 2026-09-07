# Stage 5ZZU — a job may only be closed by another job that did the same work

**Route:** `track1_candidate` · **Date:** 2026-08-28 · **Orders:** never enabled, still impossible

---

## 1. Who was sharing the catch-all

Reading the type map rather than the brief's list, nine job ids landed in `other` — and one of
them was not in the brief:

```text
TRACK1_STOP_REPAIR_*   ×9 slots (00:20 · 04:20 · 06:20 · 08:20 · 10:20 · 16:20 · 18:20 · 20:20 · 22:20)
                        + track1_stop_repair_sun_1830
TRACK1_MAX_HOLD_EXIT
TRACK1_AUDIT_*         ×5 (global_nkd · roska4_calm · roska4_stress · roska4_swing · daily)
HEARTBEAT              — in the catch-all too, though it never reaches the journal
```

The classifier had kept them clear of the legacy prefixes since it was written — its comment
says the two routes' safety jobs must stay distinguishable — but **distinguishable is not the
same as typed**, and untyped meant they were all one thing.

---

## 2. What could happen, in both directions

`other` is a bucket. Two lanes were reading it as a stream, and they were wrong in **opposite**
ways. Both were reproduced with a fixture before anything was changed.

### The journal lane — anything closed anything

```text
FALSE RECOVERY   a failed Track1 STOP_REPAIR closed by a Track1 AUDIT
FALSE RECOVERY   a failed Track1 AUDIT closed by a Track1 STOP_REPAIR
FALSE RECOVERY   a failed Track1 MAX_HOLD closed by a Track1 AUDIT
```

This is the mechanism Stage 5ZZT measured in production: on 2026-08-27 `TRACK1_STOP_REPAIR_1820`
completing marked two failed SPY refreshes as recovered. The cross-route pairs were already safe
— legacy has a real type — so the exposure was Track 1's maintenance jobs closing each other.

### The issue lane — nothing ever closed anything

```text
TRACK1_STOP_REPAIR_0620   stream = TRACK1_STOP_REPAIR_0620      each sweep alone
TRACK1_STOP_REPAIR_0820   stream = TRACK1_STOP_REPAIR_0820
STOP_REPAIR_0620          stream = stop_repair                  legacy shares a stream
STOP_REPAIR_0820          stream = stop_repair
```

`open_issue_reader._stream()` falls back to the job id when the type is `other`. So a Track 1
sweep that failed at 06:20 could **never** be closed by the identical sweep at 08:20, while its
legacy counterpart always could. One lane gave a false all-clear; the other opened an issue that
nothing could ever clear. This half was not in the brief and was found by reading the second
reader.

---

## 3. The new streams

| Type | Jobs |
|---|---|
| `track1_safety_stop_repair` | `TRACK1_STOP_REPAIR_*` |
| `track1_safety_max_hold` | `TRACK1_MAX_HOLD_EXIT` / `TRACK1_MAXHOLD_EXIT` |
| `track1_window_audit` | `TRACK1_AUDIT_*` |

Both spellings of the max-hold id are matched deliberately: the slot table declares
`track1_maxhold_exit` and the log label reaching the reader is `TRACK1_MAX_HOLD_EXIT`. Matching
one would type the job on some days and not others.

Matching is on the **structured type**, not a substring — `TRACK1_STOP_REPAIR_0620` contains the
string `STOP_REPAIR`, and any lane testing substrings would merge the two routes' sweeps, which
is the one thing B1 exists to keep apart. A test pins that.

### After

```text
audit closes a failed sweep          no   (was: yes)
sweep closes a failed audit          no   (was: yes)
audit closes a failed max-hold       no   (was: yes)
legacy sweep closes a Track 1 sweep  no   (unchanged)
Track 1 sweep closes a legacy sweep  no   (unchanged)
Track 1 sweep closes a SPY refresh   no   (fixed in 5ZZT, pinned here from both sides)

a LATER Track 1 sweep closes an earlier failed sweep    yes  (was: never)
a LATER Track 1 audit closes an earlier failed audit    yes  (was: never)
the legacy sweep stream still recovers itself           yes  (untouched)
```

Every "must not close" has a "must close" beside it. A change that simply stopped closing
anything would have satisfied half this suite and been worse than the bug it replaced — the
issue lane was already broken that way. Mutation **M8** exists to make that impossible to ship.

---

## 4. Wording

The `other` branch told an operator a Track 1 audit had "emitted an unclassified error" and to
"reconcile current broker state" — advice about a broker the job never touches.

| Job | Now says |
|---|---|
| Track 1 stop-repair sweep | protective stops **on the Track 1 book** were not rechecked at this slot |
| …caught by a later sweep | the book was rechecked when `TRACK1_STOP_REPAIR_0820` completed — no immediate action |
| Track 1 max-hold check | a position **past its maximum hold** would not have been closed |
| Track 1 window audit | **no evidence record** was written for that window; nothing is at risk in the book, and the paper-evidence gate reads that record |

A test asserts the word "broker" appears in none of the audit's impact or action text, in either
failure state.

---

## 5. The UI, and what a type change costs at its call sites

Changing a type is not free for the code that reads it. Four lanes read `job_type`, and two of
them needed work:

**Attribution.** `component = … ['stop_repair','preflight','session_report','other'].includes(job_type) ? 'scheduler' : 'runner'`. These jobs reached that list *through* `other`. Typing them
without naming them here would have silently moved a missed sweep to `runner` — blamed on a
runner that never ran. The three types are named explicitly now.

**Labels.** `TRACK1_STOP_REPAIR_0620` was the primary text on both the issue row and the journal
row. It is an identifier, so it moved to the tooltip and a readable name took its place — "Track
1 stop-repair sweep 06:20".

That relabelling is **scoped to the three types this stage introduces**, and the first attempt
proved why. Covering the strategy slots broke five tests in the Stage 5ZE operator view, which
addresses a row by its id; covering the legacy sweep broke a sixth that finds a row by looking
for `STOP_REPAIR` in its name. Renaming a taxonomy is a design change of its own and was not
what this stage was asked for. One test in that suite was updated to read the id from the
tooltip, which is where this stage put it.

An unknown type falls back to the id rather than rendering blank — pinned by mutation M14.

---

## 6. A scope error of mine, caught by the suite

The label helper was first inserted next to `stripScheduleBad`, which sits three scopes deep
inside a render function. `jobLabel` was therefore invisible at the journal row, the Job Journal
panel threw, and **19 tests errored with `.job-row` never appearing**. This is the same mistake
as Stage 5ZZL, where render calls landed inside a click handler. The helper now sits beside
`mvEsc` at module scope, and the patch that moved it *asserts the destination's brace depth is 1*
rather than trusting the indentation.

---

## 7. Something else moved while this stage ran

Midway through, `ops.py status` began reporting **two** blockers instead of one:

```text
track1_blocking=['B1_broker_account_or_legacy_retirement', 'PAPER_SHADOW_EVIDENCE']
orders_possible=False
```

**B1 reopened, and nothing in this stage caused it.** The measurement says why:

```text
b1_decision_evidence -> False
  B1 audit PASS (legacy_and_broker_flat); book route track1_candidate;
  account baseline UNKNOWN (baseline_record_stale)
```

```text
account baseline checked   2026-08-27T11:29:47Z
measured at                2026-08-28T11:31:07Z     = 24 hours and 1 minute
```

The account baseline record passed its 24-hour freshness policy **81 seconds** before the
reading. This is the gate doing exactly what Stage 5ZZS's `test_28b` demands of it: B1 is closed
only while a signature **and** a passing measurement both hold. Orders remained impossible
throughout.

**Operator action:** rerun the account baseline check to close B1 again. Nothing else is
required, and nothing is at risk while it stands open.

It also exposed brittleness in tests I wrote yesterday. Three of them pinned a live, ageing state
as though it were an invariant:

- 5ZZT and 5ZZU each asserted the blocker list **by equality** — `== ["PAPER_SHADOW_EVIDENCE"]`.
  Now: `orders_possible is False` and `PAPER_SHADOW_EVIDENCE in ids`.
- 5ZZS's `test_28` asserted `b1_decision_evidence(".") is True`. Now: it is a two-valued answer
  that carries a reason, whichever way it reads today.
- 5ZZS's `test_28b` used "B1 is closed right now" as a **precondition**. Now it drives the
  measurement in both directions and asserts the rule, which is what it was always trying to say.

The 5ZZS mutation harness still catches 11/11 after that rewrite, so the tests were made
time-independent, not weaker.

And a twelfth instance of the pre-B1 staleness family surfaced in a suite Stage 5ZZS had not run
— `test_42` in the 5ZD signal-diagnostics suite, still asserting the operator had signed nothing.
Restated the same way.

---

## 8. Results

| | |
|---|---|
| New suite | **29 passed** |
| Adjacent issue / schedule / dashboard / ops suites | **655 passed**, 6 failed |
| Mutations | **14/14 caught** |
| Caused by this stage | **0** — measured by reverting the edits and diffing |

The 6 remaining failures, none of them this stage's:

- `test_40` / `test_45` — a rule grid and a `JSON.stringify` in the market-view render path,
  from Stages 5ZZL/5ZZR. Measured pre-existing.
- three schedule-status tests expecting a `TRACK1_CALM_1000` slot and a "Calm one-shot band" from
  before Calm became two phases. Measured pre-existing in Stage 5ZZT.
- `test_35` — passes on its own and in a second combined run; intermittent, and it failed in
  neither arm of the attribution measurement. Recorded as flaky rather than fixed.

### Real data

Every Track 1 maintenance job in the retained journal — 30 across three days — completed, and
none carries a recovery marker. A marker on a completed job would mean the annotation is firing
on something other than a failure.

### Safety

```text
orders_possible            False
track1_blocking            ['B1_broker_account_or_legacy_retirement', 'PAPER_SHADOW_EVIDENCE']
                           B1 reopened on record age; see §7. Not caused here.
scheduler_mode             compatible · confirmation True · legacy_entry_jobs 0
track1_runtime/orders      ABSENT      live_positions.track1.json  ABSENT
TRACK1_ORDERS_APPROVED     unset
scheduler restarted        no          backend restarted  no       broker connections  0
runtime trading files      not edited
```

No gate, schedule, strategy or order behaviour changed. This stage edited two monitor backend
readers and one dashboard script.

---

## 9. Backend restart

**Yes, for the dashboard to show any of this.** `job_journal_reader.py` and `open_issue_reader.py`
are imported once per process, and the backend that is running started before they were edited.
`realtime.js` is static and a browser reload picks it up, but the types it now reads come from
the backend, so the reload alone shows nothing new.

Not done here. A backend-only restart does not disturb the scheduler.

---

## 10. Still open

- The account baseline record needs rerunning to close B1 (§7). Operational, not code.
- `HEARTBEAT` remains typed `other`. It never reaches the job journal, so it cannot take part in
  a false recovery today; it is named here so the next reader does not have to rediscover it.
- The two market-view render-path assertions and the three Calm-band tests above.
