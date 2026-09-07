# Stage 5ZZZ-C — what was underneath the stale reason

**Route:** `track1_candidate` · **Date:** 2026-08-28 · **Orders:** never enabled, still impossible

---

## The answers

| question | answer |
|---|---|
| Does 2026-08-27 still count as a **failed** evidence day? | **Yes** |
| Exactly why? | `roska4_calm` and `roska4_stress` genuinely failed on **data refusals** — nothing to do with the confirmation file |
| Did `PAPER_SHADOW_EVIDENCE` move? | **No.** Still `False`, same four failing checks |
| `orders_possible` | **False** — `PAPER_SHADOW_EVIDENCE` |
| Any runtime / audit / trading file written? | **No.** Audit digests unchanged; the new module cannot write |

---

## 2026-08-27, sleeve by sleeve

Three answers per sleeve, kept apart because they answer different questions:

| sleeve | stored row | failed **only** by the removed rule? | re-evaluated now | can that re-evaluation be trusted for a past day? |
|---|---|---|---|---|
| `roska4_calm` | FAIL `[confirmation_file_present]` | **yes** | **FAIL** | **yes** |
| `roska4_stress` | FAIL `[confirmation_file_present]` | **yes** | **FAIL** | **yes** |
| `global_nkd` | FAIL `[confirmation_file_present, window_closed_before_scheduler_start]` | no | FAIL | **no** |
| `roska4_swing` | FAIL `[confirmation_file_present]` | **yes** | FAIL | **no** |

### The two that really failed

**`roska4_calm` — a data failure, both phases.**

```text
the committed ledger rule counts only slots that DECIDED: observed 0 of 1
2 slot(s) could not evaluate: TRACK1_CALM_DECIDE_0932, TRACK1_CALM_OBSERVE_1002
   gate_refused: missing_session, entry_quote_absent, stale, partial_coverage
   gate_refused: missing_session, stale, partial_coverage
```

Neither Calm phase could evaluate. The refusals name the cause: no session, stale data, partial
coverage, and on DECIDE no entry quote. This is a **data/provider failure**, and it is why
`calm_decision_evidence` and `every_sleeve_passed_at_least_once` both still fail.

**`roska4_stress` — the first half-hour of the window.**

```text
observed 18 of 24
6 slot(s) could not evaluate: TRACK1_STRESS_1035 … 1100
   gate_refused: missing_session, stale
```

The six slots from 10:35 to 11:00 were refused for missing session and stale data; the remaining
18 decided normally. A data failure at the **open** of the window, not a strategy or code fault.

Both of these were invisible on the day: the stored rows say only `confirmation_file_present`.

### The two that cannot be re-judged, and why

`checkpoint_wrong_day` is not a finding about 2026-08-27. It is an artefact of asking the
question today, and the mechanism is provable:

```text
live_positions.track1.json   cut_instant: 2026-08-28T10:02:01-04:00   (rewritten 08:02 today)
dated history of that file:  none anywhere in the tree
```

The checkpoint check compares the day under judgment against **that** file. It is a single live
artefact, overwritten on every run, with no history — so re-judging **any** past day reports
`checkpoint_wrong_day`, every time, forever. A test asserts the file's shape and the absence of
history, so the claim fails if either changes.

For `global_nkd` there is better evidence than a re-evaluation: **its own row from that day**.

```text
row 1 (window closed)   PASS   ['all_slots_observed_no_action']
row 2 (daily sweep)     FAIL   ['confirmation_file_present', 'window_closed_before_scheduler_start']
```

`global_nkd` **passed on 2026-08-27**. The later sweep overwrote it, and its only failing reason
was the rule Stage 5ZZZ-A removed. The readiness reader keeps the **last** row per
(scope, sleeve, day), so that PASS is why `every_sleeve_passed_at_least_once` lists `global_nkd`
as never having passed.

---

## Classification, not correction

Task 7 asked for read-time classification that preserves the original evidence.
`global_index/track1_audit_reinterpretation.py` reports three things per sleeve and never writes:

- **stored** — the record, verbatim
- **classification** — which reasons came from a rule that has since been removed, and whether
  the row was failed **solely** by those
- **reevaluated** — what the current code says, **with** whether it is entitled to say it

The registry of removed rules is checked against the acceptance module rather than trusted: a
test asserts each registered reason is genuinely no longer appended anywhere. That check found a
loose end from Stage 5ZZZ-A — the `reasons.append(R_CONFIRMATION_FILE)` mapping branch was still
present, unreachable only because no check emitted the string it matched on. Unreachable-by-string
is a thin thing to rest on, and it made the reason look live to anything reading the file to learn
which reasons the code can produce. It is removed.

### It is deliberately not wired into the gate

`track1_gates.shadow_evidence` → `track1_paper_readiness.gate_measurement` → `readiness`. Nothing
on that path imports the new module, and a test asserts it by reading the import graph.

Turning a stored failure into a pass moves the only gate still holding this route. That has to be
an operator's decision with the reasoning in front of them, not a side effect of a reader someone
added. The classification is published so the decision can be made; it does not make it.

**And on this day it would change nothing anyway.** Two sleeves failed for real, so 2026-08-27 is
a failing day under any honest reading.

---

## No corrected rows were written

Task 6 allowed hand-written corrections if proven required and safe. They are neither:

- The rows are **append-only JSONL carrying provenance** — `audit_trigger`, `audit_pid`, `ts`. A
  hand-written row would carry my pid and a trigger no other row means.
- 2026-08-27 fails on merit, so a corrected row states the same verdict.
- 2026-08-28's rows will be rewritten by the scheduled audits from the fixed code.

Digests before and after this stage's work are identical, and a test recomputes them across the
whole audit directory around a reinterpretation call.

---

## `PAPER_SHADOW_EVIDENCE` — before and after

**Unchanged**, and that is the intended outcome:

```text
released: False

  [fail] judgeable_days              4 judgeable day(s) on record, 5 required
  [fail] no_failing_days             4 FAIL day(s) in the qualifying window, at most 0 allowed
  [fail] calm_decision_evidence      missing or incomplete: 2026-08-24, 2026-08-25 …
  [fail] every_sleeve_passed_at_least_once   never PASSED inside the window:
                                              ['roska4_calm', 'global_nkd']
  [ok]   audit_records_readable · warn_days_within_allowance · evidence_is_recent
  [ok]   paper_account_baseline      USD 250,851 — broker reconcile flat
```

What actually stands between this route and paper orders, now that the stale reason is out of the
way:

1. **One more judgeable day** — 4 of 5. That is time, not a defect.
2. **Zero failing days required, four present** — 08-24 and 08-25 have real coverage and schema
   failures, 08-26 has a Calm coverage failure, 08-27 has the Calm and Stress data refusals above.
3. **Calm decision evidence** missing for 08-24 and 08-25 (`pre_shadow_intent_schema`).
4. **`roska4_calm` and `global_nkd` never PASSED in the window** — and `global_nkd` did pass on
   08-27, in a row that a since-removed rule overwrote.

Item 4 is the one where the stale rule still costs something. Items 1–3 are real.

---

## Results

| | |
|---|---|
| New suite | **21 passed** |
| Adjacent suites | **408 passed**, 1 failed |
| Mutations | **10/10 caught** |

Most mutations widen the classifier, because that is the direction it is dangerous in: register a
live reason as stale, dismiss a re-evaluation entitled to speak, wire it into the gate, or let it
write. Two narrow it, since a classifier that dismisses nothing would satisfy every safety test
and be useless.

Two came back green honestly before retargeting. One wrote `{} or {…}`, which Python evaluates to
the non-empty dict — a no-op. The other substituted the re-evaluated verdict into the stored
field, invisible because **every** sleeve is FAIL both ways on this day; a synthetic record that
makes the two disagree by construction now catches it.

The single adjacent failure is the job-inventory pin, measured as pre-existing in an earlier
stage.

### Safety

```text
orders_possible False · blocking ['PAPER_SHADOW_EVIDENCE'] · scheduler pid 3000, not restarted
audit files       digests unchanged        confirmation file  intact and signed
track1_runtime/orders ABSENT               TRACK1_ORDERS_APPROVED unset
strategy · gates · order send              untouched
```

Files written: one new read-only module, one test file, one mutation harness, and the documents.
`global_index/track1_shadow_acceptance.py` lost an unreachable branch.

---

## Still open

- **The Calm and Stress data refusals of 2026-08-27** — `missing_session`, `stale`,
  `partial_coverage`, `entry_quote_absent`. This stage identified them; nobody has yet asked why
  the provider had no session at 09:32 and at 10:35. That is the next question.
- **`global_nkd`'s overwritten PASS.** Whether the readiness reader should keep the last row or
  the best row is a real design question, and changing it moves a gate — so it belongs to an
  operator, not to this stage.
- The audit's Calm window still reads `["10:00","10:00"]` and expects 1 slot where two phases now
  run, noted in Stage 5ZZZ-A and still true.
