# Stage 5Q-1 — what a slot's row means, and where the explanations actually are

**2026-08-24 ·** scheduler **not** started, stopped or restarted by this work · backend **not**
restarted · no IBKR connection · no order · no `--allow-orders` · `TRACK1_ORDERS_APPROVED`
unset · no `STOP_TRADING`, `STOP_TRADING.track1` or confirmation file · nothing written under
`global_index/track1_runtime/` · no commit.

**One thing about the environment changed between sessions and it was not me.** The scheduler
running now is **pid 6880, started 06:23:03 local = 08:23 ET**, not the pid 33868 the Stage 5Q
report named. The operator restarted it. Measured, from its own log:

```text
2026-08-24 06:23:04  [track1-only] 5 Track 1 audit jobs registered (read-only, no broker)
2026-08-24 06:23:04  Jobs (100):
                       track1_audit_global_nkd
                       track1_audit_roska4_calm
                       track1_audit_roska4_stress
                       track1_audit_roska4_swing
                       track1_audit_daily
```

So the Stage 5Q audit jobs are **already live**. That changes the operator page at the bottom.

---

## Verdict: **AUDIT_SEMANTICS_REPAIRED — and one guaranteed false FAIL removed**

The exact claim: **the audit now distinguishes a slot that looked from a slot that could not
evaluate, and it reads explanations from the path the writer actually uses.** Both changes
were made because measurement said so, not because the design read better.

Not claimed: that any shadow day has passed; that Track 1 is paper- or live-ready; that the
explanation evidence is complete — it is not, and the reason is a writer defect this stage
deliberately did not fix. See **Blockers before 5R**.

---

## The premise I was handed, and where it was wrong

The brief said `no_signal / no_candidate` was among the refusals that do not count toward
coverage. **It is not.** Measured by running `observe_live_slot` against a temp tree rather
than by reading it:

| what happened to the slot | `decided` | `reason` | `detail` |
|---|---|---|---|
| no bar provider | `False` | `no_bar_provider` | prose |
| gate allowed, **zero candidates** | **`True`** | `decided` | `candidates=0` |
| gate refused, clock | `False` | `gate_refused` | `too_late` |
| gate refused, data | `False` | `gate_refused` | `stale` |
| live source not ready | `False` | `live_source_not_ready` | prose |

A slot that looked and found nothing already records `decided=True` and already counts. So
the gap was narrower than stated, and it is worth saying rather than answering the question
as asked: **the only designed refusal that was being miscounted is the CLOCK one.**

That one matters, and not hypothetically. `track1_intraday` refuses a slot `too_early` /
`too_late` when the instant sits outside the sleeve's own decision band — and that band is
not the scheduler's ET slot grid. For NKD the band is the **Tokyo session**, and the ET grid
is fixed while Japan has no DST. In summer `01:10–02:55 ET` is `14:10–15:55 JST` and every
slot is inside. After **2026-11-01** the same grid lands at `15:10–16:55 JST`, so twelve of
the twenty-two slots fire after the band closes and are refused **by design** — legacy's own
inherited behaviour. Under 5Q's rule the NKD window could never be complete again, and the
audit would have failed every winter night for a route that was behaving correctly.

An audit that fails every winter night is an audit nobody reads.

---

## The classification

Derived from the row, never from a file's existence. Fails closed: a row the classifier
cannot read is a hard refusal, not evidence that somebody looked.

| class | the row | counts as observed? |
|---|---|---|
| `observed_decision` | `decided=True`, candidates evaluated | yes |
| `observed_no_action` | `decided=True`, zero candidates | yes |
| `observed_window_shut` | `gate_refused`, and **every** code is a clock code | yes |
| `observed_hard_refusal` | anything else with `decided=False` | **no** |
| `unobserved` | no ledger row at all | **no** |

`too_late,stale` is a **hard** refusal. A stale frame that also happened to be late is still a
stale frame, and letting the clock code license the data code is how a real gap gets waved
through.

`freshness_refused` is a **hard** refusal, and the reason is at its raise site rather than in
its name: it fires only when a binding mode caught the engine **admitting** a candidate while
the daily inputs were refused. That is the route about to act on data it does not trust — the
loudest thing in the evidence, not a quiet skip.

The clock codes are read from `track1_intraday`, not restated. A new clock code added there
and not here reads as a hard refusal: loud and wrong in the safe direction.

---

## The defect that was not on the list

**The acceptance gate was reading a path nothing has ever written to.**

Measured, by driving the real writer into a temp tree:

```text
writer lands at   .../shadow/explanations/live_2026-08-25/explanations_20260825.jsonl
gate looked at    .../shadow/explanations/explanations_20260825.jsonl
rows the gate found: 0
```

`emit_explanations` resolves its destination as `<shadow>/explanations/<window>/`, one
directory deeper, keyed by the window name — and `write_shadow` is its only caller in the
repo. So on the first real shadow day both the `explanations` and the `freshness_proofs`
checks would have failed a route that wrote its explanations **correctly**, and the failure
would have looked exactly like missing evidence.

The dashboard's own explanation counter globbed the same shallow directory and would have
reported zero rows every day beside it.

Both now resolve through **one** function, `track1_shadow_acceptance.explanation_files`, and a
test drives the real writer and requires the gate's reader to find what it wrote. That is the
test that would have caught this on day one; a hand-written fixture in the layout the reader
expects is a fixture agreeing with itself.

---

## What the audit now checks

| check | rule |
|---|---|
| window closed | no `window_closed` record → FAIL. The ledger's fail-closed rule, kept exactly |
| every slot looked | every registered id in an observed class → else FAIL, naming the ids |
| duplicates | a doubled id is reported **by name**; it can never fill the gap left by a missing one, and a duplicate alone is a WARN, not a gap |
| unregistered ids | a row for a slot this sleeve does not register → WARN, named |
| could not evaluate | any hard refusal → FAIL, with the reason and the gate codes |
| timing, both ways | a ledger row with no timing record → FAIL (it ran unmeasured); a timing record with no ledger row → FAIL (a crash, or a mutex skip the scheduler wrote on the child's behalf) |
| runtime | unchanged: p95 ≥ 300 s FAIL, ≥ 240 s WARN, any single slot ≥ 300 s FAIL |
| explanations | owed only where the ledger's own counters say candidates were seen |
| freshness | every row present must carry a freshness reference → else FAIL |
| checkpoint | unchanged, expected once the ledger reports the window complete |
| orders | unchanged, judged on every audit whatever the window did |

Two verdicts that are new and deliberately not failures:

- **every slot ran and every one was shut out** → `WARN`, `all_slots_observed_window_shut`.
  Legitimate for NKD in winter; still worth an operator's eye, because a grid that never
  opens is also what a misconfiguration looks like.
- **every slot ran, evaluated, and found nothing** → `PASS`, `all_slots_observed_no_action`.
  A complete observation of a quiet window.

And the ledger's own verdict never disappears. Whenever the two completeness notions disagree
the record carries `coverage_incomplete` as an **informational** reason beside
`ledger_outcome`, so an operator reading `all_slots_observed_window_shut` +
`coverage_incomplete` gets the whole story: the window *was* observed, and the committed daily
gate will not count it.

---

## The quiet day

The second thing 5Q left open: the committed daily gate requires explanation rows for the
**whole day**, so a session in which every sleeve legitimately found no candidate cannot
satisfy it.

The audit's operational roll-up is built from the sleeve verdicts and is **not** forced down
by that gate. The gate's verdict rides along by name — `daily_acceptance_gate_refused`, plus
its `failed` list verbatim — so a green audit can never be read as having satisfied it. Two
answers, neither softened, and a mutation restores the old behaviour to prove the separation
is load-bearing.

Per sleeve, the requirement is derived from the ledger's own counters rather than from a file
existing:

```text
slots saw candidates, no row anywhere for the day      -> FAIL   explanations_missing
slots saw candidates, no row for THIS sleeve but rows
  from another sleeve do exist                          -> named  explanations_overwritten_by_a_later_sleeve
slots saw no candidate, no row                          -> PASS   no_candidates_to_explain
```

The middle line is the writer defect below, surfaced by name and charged to the writer rather
than to the sleeve — with a `not_checked_here` note in the record, so the day cannot be read
as having verified per-candidate attribution.

---

## Blockers before Stage 5R

**1. The live explanation writer truncates the day's file on every slot.** Measured: after a
second slot wrote the same window, the file held that slot's single row and nothing else.
`write_shadow` is called with `mode="w"` unconditionally, and all four sleeves share **one
file per session date**. So at the end of a day the file holds only the last slot's rows, and
per-candidate attribution cannot be verified by anything.

Not fixed here on purpose. The obvious one-line fix does not work: truncating only on
`seq == 0` still lets Stress's first slot at 10:35 erase Calm's 10:00 rows, because the
window name is `live_<date>` for all of them. The real choice is between

- a per-sleeve window name (`live_<date>_<sleeve>`), truncating on the sleeve's first slot; or
- append-only for the live path, with the replay path keeping truncation.

That is an evidence-layout decision with operational consequences for the runbook, and it
belongs to whoever owns the runner — not to an audit stage. Both readers already resolve
paths through one function, so either choice is a one-place change on the reading side.

**2. The freshness "proof" check is a substring match.** The context record the writer emits
carries no `proofs` key at all, so the check falls through to
`"freshness" in json.dumps(row).lower()` — a match on free text anywhere in the record. That
is the same shape as the incident where every traceback line containing `python` was counted
as a job launch. It passes today and it is not measuring what its name says.

**3. NKD after 2026-11-01.** Twelve of twenty-two ET slots will fall outside the Tokyo
decision band. The audit now reports this correctly as `WARN` rather than `FAIL`, but the
underlying question — should the NKD slot grid follow the Tokyo session instead of ET — is a
rule change, unowned, and it is legacy's inherited behaviour today.

None of the three blocks the coming shadow days. All three block reading a green day as proof
that the explanation evidence is complete.

---

## Tests

| Suite | Result |
|---|---|
| **Stage 5Q-1** `test_track1_stage5q1_audit_semantics_20260824.py` (new, 42) | **42 passed** |
| **Stage 5Q-1 mutation harness** (new, 15) | **15 / 15 detected**, two production files restored byte-for-byte |
| **Stage 5Q mutation harness**, re-run against the changed code | **16 / 16 detected** |
| Track 1 scratch regression (5Q-1, 5Q, 5P ×2, 5O, 5N, 5M-B/D, 5L, 5Z, 5I, 3B, dashboard wiring, pre-sleep ×2, ops status) | **565 passed, 1 skipped** |
| `monitor/` production suites (dashboard backend, schedule-status Track 1, realtime contract, realtime DOM, realtime skin) | **305 passed** |

`global_index/test_event_playback.py` **not run** — still the known hang.

### The fifteen mutations

```
R1   a hard refusal counts as an observation                  -> the observed-count assert reds
R2   the audit stops failing a window that could not evaluate -> the no_bar_provider test reds
R3   any gate refusal counts as the band being shut           -> the stale-frame test reds
R4   an unreadable row is read as a window-shut               -> the fail-closed test reds
R5   freshness_refused becomes a valid no-action              -> the freshness test reds
R6   slot IDS stop being checked, only the count              -> the doubled-slot test reds
R7   a duplicate id fills the gap left by a missing one       -> the doubled-slot test reds
R8   a ledger row with no timing is ignored                   -> the unmeasured-slot test reds
R9   a timing record with no ledger row is ignored            -> the crash-shape test reds
R10  the gate reads the flat path nothing writes              -> the real-writer test reds
R11  a sleeve is failed for rows a later sleeve overwrote     -> the overwrite test reds
R12  the committed daily gate is enforced on the roll-up      -> the quiet-day test reds
R13  an unobserved sleeve stops failing the day               -> the one-hole test reds
R14  the dashboard reader guesses at the layout again         -> the agreement test reds
R15  a window nobody could decide in passes without a word    -> the WARN test reds
```

**Two of them were unfaithful on the first attempt and the harness records why.** R5 added
`freshness_refused` to a reason test, and such a row carries prose in `detail`, so it fell
through to `hard` by the code check anyway and the mutation changed nothing (0/0/0). R1
changed `OBSERVED_CLASSES` and the verdict did not move, because the verdict fails on the
hard-refusal list independently — `OBSERVED_CLASSES` feeds the reported `observed` **count**,
and the faithful guard is a test that reads that number. Both are recorded rather than
quietly repointed, and R1's finding is a real one about this stage's own code: a constant that
looked load-bearing and is reporting-only.

Two Stage 5Q mutations also had to be re-aimed, and the harness **failed loudly** rather than
reporting detections it had not made — which is the only reason it was noticed.

### One Stage 5Q test changed meaning, and it is not a weakened test

`test_an_incomplete_window_fails_on_coverage` stamped `outcome=incomplete` on the close record
while every slot row still said `decided=True`, and required a FAIL. Under 5Q-1 that is a PASS
with the disagreement named, because the observation was whole. It is now
`test_a_ledger_incomplete_close_is_reported_but_does_not_by_itself_fail`, and a **new** test
beside it pins the case that is still a failure: no `window_closed` record at all.

---

## Files

**Added**

```text
scratch/test_track1_stage5q1_audit_semantics_20260824.py       42 tests
scratch/track1_stage5q1_mutations_20260824.py                  15 mutations
scratch/track1_stage5q1_audit_semantics_report_20260824.md     this report
scratch/track1_stage5q1_audit_semantics_report_20260824.json   the same, machine-readable
```

**Changed**

```text
global_index/track1_shadow_acceptance.py   + SLOT_* classes, classify_slot_row,
                                             window_observation, clock_refusal_codes,
                                             explanation_files (the path repair),
                                             rewritten evaluate_sleeve, 8 new reason codes
monitor/backend/track1_runtime_reader.py   explanations now resolved through the acceptance
                                             module instead of a second guess
global_index/dash/realtime/realtime.js     + an "Audit reasons" row beside the verdict
scratch/test_track1_stage5q_post_window_audit_20260824.py   one test re-aimed, one added
scratch/track1_stage5q_mutations_20260824.py                two mutations re-aimed
```

`global_index/track1_shadow_audit.py` is **unchanged** — it remains orchestration and
reporting, and a test asserts it carries no threshold, no class name and no gate vocabulary.

Nothing under `global_index/track1_runtime/` was written. No book, no checkpoint, no
confirmation file exists.

---

## The operator page — and a correction

The Stage 5Q report gave `python monitor\ops.py restart --backend`. **That flag does not
exist.** Verified against the real CLI:

```text
usage: ops.py restart [-h] [--scheduler] [--no-scheduler] [--no-shadow-resume]
                      [--yes] [--assume-preflight-ok] [--track1-shadow]
                      [--track1-only-shadow]
```

Backend-only is `--no-scheduler`, and the Track 1 flag still has to be passed because it is
what tells the **backend** which slot table to mirror:

```powershell
python monitor\ops.py restart --no-scheduler --track1-only-shadow
```

**Does the scheduler need restarting?** No.

- The five audit jobs are already registered — the operator's 06:23 local restart picked up
  the Stage 5Q code, and the scheduler logged `Jobs (100)` with all five audit ids.
- Stage 5Q-1 changed only modules the audit **child** imports fresh on every spawn, plus the
  backend's reader. A scheduler restart would buy nothing and would cost today's judgement:
  every window that has already closed reads as pre-start on a new process.
- The backend is a long-running process holding its imports, so it **does** need the restart
  above to serve the repaired explanation reader and the `audits` block.

**Today's first real audit** is `track1_audit_roska4_calm` at **10:10 ET**. The scheduler came
up at 08:23 ET, before the 10:00 Calm window, so Calm is judgeable today. NKD is not —
01:10–02:55 ET closed before the process existed, which the audit reports as
`window_closed_before_scheduler_start`, not as a failure.

Live, read-only, writing nothing, at 09:01 ET:

```text
  global_nkd     01:10-02:55  NOT_ENOUGH_DATA_YET  window_closed_before_scheduler_start
  roska4_calm    10:00-10:00  NOT_ENOUGH_DATA_YET  window_not_closed
  roska4_stress  10:35-12:30  NOT_ENOUGH_DATA_YET  window_not_closed
  roska4_swing   14:05-15:55  NOT_ENOUGH_DATA_YET  window_not_closed
  DAY 2026-08-24  verdict NOT_ENOUGH_DATA_YET
```

By hand, against any day, without restarting anything:

```powershell
python -m global_index.track1_shadow_audit --latest --all
python -m global_index.track1_shadow_audit --date 2026-08-25 --sleeve global_nkd
```

---

## Correction (appended 2026-08-24, Stage 5Q-2)

Nothing above is rewritten. What it got wrong is recorded here.

### The substring check was too LOOSE only, not also too strict

This report said a real REJECTED live decision "contains the word NOWHERE" and would therefore
have failed the audit. **That is wrong, and it is wrong because the probe behind it was
unfaithful:** it built the record with an empty `inputs_summary`, and the real writer always
passes `{"decision_mode": ..., "regime_csv": ..., "freshness_allow": <bool>, ...}`. Re-measured
with the writer's actual shape, a rejected row contains the word and passes.

The defect was one-directional. The correct statement is: **a row whose only mention of
freshness is prose passed, and that is what the structured check now refuses.**

### Both of this report's blockers are closed

- **B-5R-1**, the writer truncating the day's shared file, is fixed: each live slot now writes
  under `live_<date>/<sleeve>/<slot_id>/` and truncation is scoped to a slot's own file.
- **B-5R-2**, the substring freshness check, is replaced by a structural rule that lives in
  the module that builds the records.

`explanations_overwritten_by_a_later_sleeve` therefore no longer fires on a healthy day. The
reason and its test remain: rows written before the fix are still readable, and a rule that
can never be observed refusing is a rule nobody can trust.

### One line of the 5Q-1 semantics changed, and a live day is why

A sleeve whose slots wrote nothing at all no longer prints "it observed its window and found
nothing to admit". Seen on the real tree at 10:07 ET beside three correct FAIL reasons for a
slot that had crashed before reporting — the verdict was right and one of its sentences was
about the wrong thing.

### **B-5R-3** (NKD winter grid) is unchanged and still open.

Full detail: `scratch/track1_stage5q2_explanation_integrity_report_20260824.md`.
