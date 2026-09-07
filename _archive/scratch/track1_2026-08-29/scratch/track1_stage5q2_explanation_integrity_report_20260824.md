# Stage 5Q-2 — the live explanation evidence: durable, attributable, structurally proved

**2026-08-24 ·** scheduler **not** started, stopped or restarted by this work · backend **not**
restarted · no IBKR connection · no order · no `--allow-orders` · `TRACK1_ORDERS_APPROVED`
unset · no `STOP_TRADING`, `STOP_TRADING.track1` or confirmation file · every test write went
to `tmp_path` · no commit.

**The scheduler was restarted again between sessions, and again it was the operator.** It is
now **pid 28696, started 07:25:31 local = 09:25 ET**. This session ran no start/stop command.

---

## Verdict: **EXPLANATION_EVIDENCE_REPAIRED — and the first live day found something else**

The two 5Q-1 blockers are closed: no slot can erase another's rows, and the freshness proof is
structural. Both fixes have been observed failing when removed.

**But today's first real slot never reached them.** The 10:00 ET Calm slot crashed inside the
live-frame splice on a column mismatch, wrote no `slot_observed` row, and the 10:10 audit job
recorded `FAIL` with three named reasons. That is a new, measured blocker and it is now the
thing standing between this route and a judgeable shadow day. Details below.

---

## 1. The evidence layout

**Option B, per sleeve and per slot:**

```text
global_index/track1_runtime/shadow/explanations/
    live_<YYYY-MM-DD>/<sleeve>/<slot_id>/explanations_<YYYYMMDD>.jsonl
```

Three levels, each earning its place: the session day so a day is one subtree, the sleeve so
"what did Normal-R4 explain today" is a directory rather than a filter, and the slot so a slot
owns its file.

**Why not Option A (append + dedupe).** Truncation was never the bug. It is what stops a
re-run of one slot doubling its own rows, and the decision file written beside it is opened
`"w"` for the same reason. The bug was that one path was shared by writers that are separate
processes with separate lifetimes. Give each slot its own file and truncation becomes exactly
right: a slot may replace its own evidence and can no longer touch anyone else's — with no
read-modify-write, no dedupe pass, and no window where two processes hold the same file.

**Re-run semantics, stated rather than implied:** a re-run of one slot **replaces that slot's
rows** and nothing else. A day therefore holds at most one record set per slot, so a count is
a count. Pinned by `test_rerunning_one_slot_replaces_only_its_own_rows`, and mutation **S4**
turns it into append and reds it.

**The layout has one owner.** `track1_explain.live_window()` builds it and
`track1_explain.explanation_files()` finds it; the acceptance gate delegates, and the
dashboard delegates to the gate. Two readers guessing at a layout independently is how they
came to disagree with the writer in the first place.

**Traversal is refused, not sanitised.** A sleeve or slot name containing a separator raises.
A name that needs cleaning is a name a caller got wrong, and silently rewriting it files the
rows somewhere nobody will look for them.

**The replay path is untouched and explicitly scoped.** A replay writes one window from one
process — the case truncation was designed for — and every committed replay artefact on disk
is in the flat `explanations/<window>/` shape. Mutation **S11** migrates it and reds.

### Are previous live rows preserved and readable?

**There were none.** Measured at 09:30 ET today: `global_index/track1_runtime/` held only two
empty directories — no coverage file, no timing file, no explanations. The first live slot ran
at 10:00 ET and crashed before reaching the writer. So nothing had to be migrated and nothing
was lost.

The reader is recursive regardless, and finds all three shapes — flat, the 5Q
`live_<date>/`, and the 5Q-2 `live_<date>/<sleeve>/<slot>/`. Rows written in an older shape
are evidence, not litter, and a reader that only accepts today's shape is the same brittleness
that made the gate read a path nothing wrote to, pointing the other way.

---

## 2. The freshness proof

**What was there:** `"freshness" in json.dumps(row).lower()` — a substring test over the whole
record, including free text. A row whose only mention was a sentence passed.

**A correction to Stage 5Q-1.** That report said the substring check was *also too strict* —
that a real rejected decision contained the word nowhere and would have failed. **That was
wrong, and it was wrong because my probe was unfaithful:** it built the record with an empty
`inputs_summary`, and the real writer always passes `{"freshness_allow": <bool>, ...}`. Re-run
with the writer's actual shape, a rejected row contains the word and passes. The defect is
one-directional: **too loose only.**

**The structured rule**, derived from the tables the records are built from rather than
restated:

| the row | what it owes |
|---|---|
| accepted, binding mode (`shadow_live`/`armed`) | must cite `GATE.FRESHNESS` — from `ACCEPTED_PROOF_RULES_BY_MODE` — and carry a boolean `freshness_allow` feature that passed |
| accepted, `replay` | nothing. The gate reads today's inputs and did not govern an admission taken months ago — the Stage 5Z finding, kept |
| rejected | the feature only if a cited rule declares it. A cap refusal never reached the gate and must not be asked to prove one |
| any `DECISION` record | the **run's** verdict as a typed field, `inputs_summary["freshness_allow"]`, boolean |
| the `NO_ACTION` context record | a boolean `freshness_allow` feature — this is the record a day's freshness verdict is audited from |
| anything unrecognisable | **fails closed.** A row with no `record_type` owes nothing by the rules above and would sail through, which is how a malformed line becomes a passing check |

Measured on the four cases:

```text
rejected with the writer's real inputs_summary   -> []                      (owes nothing more)
only the word, in a sentence                     -> ["...carries no boolean inputs_summary
                                                      ['freshness_allow']; the word appearing
                                                      in prose is not a record of it"]
accepted binding, cites the gate, feature passed -> []
accepted binding, cites neither                  -> ["does not cite ['GATE.FRESHNESS']",
                                                     "owes a 'freshness_allow' feature and
                                                      carries none"]
```

It lives in `track1_explain` — the module that BUILDS the records — so the writer and the
judge cannot disagree about what a proof is. The acceptance gate calls
`tx.check_freshness_proof(row)` and holds no copy.

---

## 3. What Stage 5Q-1 semantics survive

Unchanged and re-verified by re-running that stage's whole mutation harness (15/15):
`observed_decision` / `observed_no_action` / `observed_window_shut` / `observed_hard_refusal`;
a clock-only gate refusal is a WARN and not a false FAIL; a quiet no-candidate day is not
failed by the committed daily gate; missing timing and a missing ledger row are still FAILs
in both directions.

One line changed inside that semantics, and it changed because of something seen live:

> A sleeve whose slots wrote **nothing at all** no longer prints "it observed its window and
> found nothing to admit". Watching the real Calm audit, that sentence appeared beside three
> correct FAIL reasons for a slot that had crashed before reporting. The verdict was right and
> one of its sentences was about the wrong thing.

The `explanations_overwritten_by_a_later_sleeve` reason from 5Q-1 remains in the code and its
test remains with it. The writer no longer produces that shape — a healthy day never fires it,
which is the measure of the fix — but rows written before the fix are still readable, and a
rule that can no longer be observed refusing is a rule nobody can trust.

---

## 4. The dashboard

`/api/v1/track1-runtime` now reports rows and attribution per day:

```text
Explanations   1 day(s), latest 20260825: 12 row(s) across 3 sleeve(s) / 12 slot(s)
```

Before the fix that count was whatever the last slot of the day happened to write.

The reader resolves paths through the acceptance module and **does not import the writer** —
a boundary held by a source test, because a panel that imported the writer would be one edit
away from being able to produce evidence rather than read it. Mutation **S9** breaks the
delegation and reds. Read-only in every branch; the Stage 5P AST scan still passes. No legacy
explanation path is read, and "audit not run yet" is still not a pass.

---

## 5. What the first live day found

The whole pipeline ran end to end on a real day, and it worked — by reporting a failure
correctly rather than by going green.

```text
08:00:04 local  [TRACK1_CALM_1000] SpliceRefused: column_mismatch:
                frozen columns ['open','high','low','close','volume']
                != live ['open','high','low','close','volume','average','barcount'];
                concatenating them yields NaN holes
08:10:00 local  [TRACK1_AUDIT_ROSKA4_CALM] -m global_index.track1_shadow_audit
                --latest --sleeve roska4_calm --scheduler-started 2026-08-24T09:25:31
08:10:01 local  [TRACK1_AUDIT_ROSKA4_CALM] completed OK
```

The audit record it wrote, route-stamped, in `track1_audit_20260824.jsonl`:

```json
{"route": "track1_candidate", "date": "2026-08-24", "scope": "sleeve",
 "sleeve": "roska4_calm", "verdict": "FAIL",
 "reasons": ["coverage_unobserved", "missing_slot_ids", "no_timing_records"],
 "missing_slot_ids": ["TRACK1_CALM_1000"], "scheduler_start_source": "argv"}
```

Three true reasons, no false one, and the scheduler handed the child its own start instant as
designed. This is the shape 5Q-1 built the crash checks for, firing on its first real day.

---

## 6. Blockers before Stage 5R

**B-5R-A — the live frame cannot be spliced: column mismatch.** *(new, measured live, and the
one that matters)* The frozen frames carry `open, high, low, close, volume`; the IBKR live
fetch returns those plus `average` and `barcount`. `track1_live_frame.splice` refuses rather
than concatenating into NaN holes, which is correct. Every sleeve will hit this on every slot
until the live fetch is projected onto the frozen columns (or the frozen frames are widened).
**Until it is fixed no shadow day can be judged**, because no slot gets as far as a decision.

**B-5R-B — `SpliceRefused` crashes the slot instead of being recorded.** `observe_live_slot`
catches `ShadowRefused`, `FreshnessRefused`, `LiveSourceRefused` and `NotImplementedError`;
`SpliceRefused` is none of them, so it propagates and the slot writes no `slot_observed` row
at all. Its own docstring says the refusal is the record. Measured today: the Calm slot left a
`window_open` line and nothing else, so the audit could only report `coverage_unobserved` +
`missing_slot_ids` where a named `live_frame_refused` row would have said what actually
happened. Not fixed here — it changes slot error handling, which this stage was told not to
touch — and it is a small, well-scoped job for whoever owns the runner.

**B-5R-C — NKD after 2026-11-01.** Carried from 5Q-1, unchanged: twelve of twenty-two ET slots
will fall outside the Tokyo decision band. Reported as `WARN`, not `FAIL`. Whether the grid
should follow Tokyo is a rule change, unowned.

**B1 — the order gate.** Unchanged and intentional. Orders remain impossible.

The 5Q-1 blockers **B-5R-1** (writer truncation) and **B-5R-2** (substring freshness check)
are closed by this stage.

---

## 7. Tests

| Suite | Result |
|---|---|
| **Stage 5Q-2** `test_track1_stage5q2_explanation_integrity_20260824.py` (new, 29) | **29 passed** |
| **Stage 5Q-2 mutation harness** (new, 12) | **12 / 12 detected**, three production files restored byte-for-byte |
| **Stage 5Q-1 mutation harness**, re-run (R10 re-aimed) | **15 / 15 detected** |
| **Stage 5Q mutation harness**, re-run | **16 / 16 detected** |
| Track 1 scratch regression (21 files) | **792 passed, 2 skipped** |
| `monitor/` production suites (6 files) | **313 passed** |

`global_index/test_event_playback.py` **not run** — still the known hang.

### The twelve mutations

```
S1   all sleeves share one file per session date again  -> the real-slot-path test reds
S2   the sleeve level is dropped from the layout        -> the attribution test reds
S3   the row loses its slot_id                          -> the provenance test reds
S4   a slot re-run appends instead of replacing         -> the re-run test reds
S5   the freshness proof is a substring match again     -> the prose test reds
S6   a binding admission need not cite the gate         -> the 5Z-contract test reds
S7   an unreadable row passes the freshness check       -> the fail-closed test reds
S8   the reader only looks at the flat path             -> the reader-agreement test reds
S9   the dashboard reaches into the writer module       -> the reader-agreement test reds
S10  a duplicate slot id masks a missing one            -> the 5Q-1 doubled-slot test reds
S11  the replay path is migrated to the live layout     -> the replay-layout test reds
S12  a traversing sleeve name is sanitised not refused  -> the traversal test reds
```

**S1 was undetected on its first form, and the gap it exposed was in my suite.** It edits the
CALL SITE in `observe_live_slot`, and I had aimed it at a test that drives `emit_explanations`
directly — a test of the writer cannot see a call site. Fixed by adding two tests that run the
real slot function with only the bar source and the intraday gate stubbed. Same family as the
project's own rule: check the call site, not the implementation.

Two mutations in the older harnesses had to be re-aimed because 5Q-2 moved their targets
(`Q1`-style id guard, `R10`'s path resolver). Both harnesses **raised rather than reporting a
detection they had not made**, which is the only reason it was noticed.

### Four pre-existing or obsolete guards, repaired rather than left attributable to this stage

| guard | what happened |
|---|---|
| `test_no_monitor_or_dashboard_file_mentions_the_module` | **already red since 2026-08-23** — it counted a monitor TEST file that names `track1_explain` precisely in order to assert it is not imported. Now scans production files only |
| `test_no_switch_or_state_file_was_created` ×2, `test_no_switch_or_state_file_exists` | tripped by `global_index/maxhold_state.track1.json`, which the **live scheduler** wrote at 07:31 local (`[TRACK1_MAX_HOLD_EXIT] completed OK`) — exactly what Stage 5O built that marker for. Absence had been standing in for "no test wrote it"; replaced with an mtime check against module-import time, which is a stronger statement than absence ever was |
| the 5Q/5Q-1 explanation fixtures | carried a `proofs` key **no producer in this repo has ever emitted**, so every test using it checked a shape that does not exist — and passed the old substring check for the same reason a sentence would have. They now build rows through `track1_explain`'s own record builders |

---

## 8. Files

**Added**

```text
scratch/test_track1_stage5q2_explanation_integrity_20260824.py       29 tests
scratch/track1_stage5q2_mutations_20260824.py                        12 mutations
scratch/track1_stage5q2_explanation_integrity_report_20260824.md     this report
scratch/track1_stage5q2_explanation_integrity_report_20260824.json   the same, machine-readable
```

**Changed**

```text
global_index/track1_explain.py             + live_window / explanation_files /
                                             attribution_from_path / freshness_proof /
                                             check_freshness_proof / freshness_context_records
global_index/run_live_day_track1.py        the live slot writes under its own window sub-path
                                             and stamps the row with its slot id
global_index/track1_shadow_acceptance.py   delegates the layout; structured freshness check;
                                             no "found nothing" for a sleeve that reported nothing
monitor/backend/track1_runtime_reader.py   rows + attribution per day, via the acceptance module
global_index/dash/realtime/realtime.js     the Explanations row shows rows / sleeves / slots
scratch/test_track1_stage5q*_*.py          fixtures build real records; four guards repaired
scratch/track1_stage5q_mutations_*.py      R10 re-aimed after the layout moved
```

**Trading decision logic, the order gate, the job inventory and the scheduler are unchanged.**

---

## 9. Operator action

**None for this stage.**

- **No scheduler restart.** Each slot spawns a fresh `run_live_day_track1` that imports the
  current modules from disk, so the writer change is picked up by the next slot without one.
  Verified against the real CLI (`python monitor\ops.py restart --help`): there is no
  `--backend` flag; backend-only is `restart --no-scheduler --track1-only-shadow`.
- **The backend** would need that command to serve the new Explanations row, but it is
  cosmetic — the audit records are written and readable either way. It can wait for whenever
  the backend is next restarted.
- **What does need someone:** blocker **B-5R-A**, the live-frame column mismatch. Until the
  IBKR fetch is projected onto the frozen columns, every Track 1 slot today will refuse the
  same way and no window can be judged.

---

## Correction (appended 2026-08-24, Stage 5Q-3)

Nothing above is rewritten. What it got wrong is recorded here.

### B-5R-A was one of TWO live-frame blockers, not the only one

This report said the column mismatch was the thing standing between the route and a judgeable
day — *"every sleeve will hit this on every slot"*. Measured on the same day's later slots,
that is not what happens. `overlap_disagreement` runs **before** the splice, so a sleeve whose
instrument disagrees with stored history never reaches the column check at all:

```text
overlap_disagreement — MNQ: the live half and history disagree on 1 of 1186 shared
timestamps in 'low'; first at 2026-08-21 13:45:00-04:00, history says 29400.2500 and the
feed says 29395.7500, largest gap 4.5000
```

Calm (MES + MNQ) reached the splice and died on the columns. Stress (MNQ only) refuses earlier
and would have done so with or without the schema fix. **Fixing the schema was necessary and
is not sufficient** — recorded as blocker **B-5R-D**, which is a stored-history question
rather than a code one.

### B-5R-A and B-5R-B are closed

- the live half is now projected onto the frozen frame's columns before the join, by
  `track1_live_source.live_frame` — the only caller of the splice guard;
- `SpliceRefused` is caught and written as `live_frame_refused` with the guard's own code in
  `detail`, so the slot leaves a record instead of dying.

### A third defect, found while answering this report's own timing question

`run_live_day_track1.py` had **never imported `slot_telemetry`**. `slot_timing/` existed, the
scheduler exported `RAITS_TELEMETRY_DIR`, and no Track 1 strategy slot had ever written a
row — so the acceptance gate's `no_timing_records` was unsatisfiable and the p95 cadence check
could never run on anything. Wired now; first measured runtimes **~2.7 s** against a 240 s
target.

Full detail: `scratch/track1_stage5q3_live_frame_splice_report_20260824.md`.
