# Stage 5Y — explanation write path wired into the Track 1 shadow route

**Session 2026-08-23 · shadow route only · nothing committed**

---

## What the existing artifacts implied before any edit

Read first, not recalled:

- **The audit** established that the dashboard has no route awareness, that one reader is a
  nine-key allow-list which drops unknown fields, and that the paper-evidence reader
  aggregates the whole trade log with no route split. Consequence for this stage: Track 1's
  records go to their own files, and nothing is added to a legacy artifact.
- **The 5X report** left the write path ready and the dashboard explicitly not ready,
  because Track 1 slots are invisible to every health signal the monitor has.
- **The design note and the schema** fix the record contract: twenty-one required fields,
  thirty-eight rules, thirty-four reason codes, and an accepted decision must prove it
  checked the cluster cap, the freshness gate and the breaker.
- **The scaffold module** re-derives the identifier, the code references and the evidence
  references at validation, so a record cannot be edited after the fact — that is what makes
  writing rows to disk worth doing.
- **The shadow route** already wrote a decision row per candidate carrying a verdict and a
  free-text detail, and its own docstring pins that it touches no legacy path.
- **The signal layer** owns the seven admission verbs, which is where the reason codes and
  the status mapping had to come from rather than a new list.

Taken together: the record format was ready, the route had a decision stream, and the only
thing missing was the pass that turns one into the other.

---

## What was wired

One emission layer in the shadow route, written **beside** the existing decision file and
never instead of it.

- `explanations_for(...)` builds one `DECISION` record per shadow decision and validates
  each one. Pure — no filesystem, so a test can inspect records without writing any.
- `emit_explanations(...)` groups them by session date and writes them.
- `run_shadow(..., explain=True)` calls it after the decision file is written, **from the
  same list in the same pass**, and puts the counts in the run summary.

The verdict mapping is data, not a chain of `if`s, and it is complete by test: every verb
the signal layer can return has a row, and a verb without one **raises** rather than being
filed under a default.

| Verdict | Status | Rules cited |
|---|---|---|
| take | accepted | cluster cap, freshness, breaker |
| reject_cap | rejected | cluster cap |
| reject_family_cap | rejected | family cap |
| suppress_same_symbol | rejected | same-symbol gate |
| suppress_same_sleeve | rejected | same-sleeve gate |
| reject_window | rejected | window gate |
| halt_breaker | rejected | breaker |

Two small supporting changes:

- `write_shadow` gained a `mode` argument. Genuinely needed: the decision file beside it is
  opened truncating, so append-only explanations would have reached twice the count on a
  second run of the same window, and a count that drifts on a re-run is a count nobody can
  use as a check. The first batch per date truncates, later batches append.
- `run_shadow` gained a `root` argument that relocates **everything** the run writes. A test
  that moved only half the output would leave the rest landing in the real shadow directory,
  and a suite cannot audit a directory it is also writing into.

`fill_law` is read **once per run** and shared by the summary, the checkpoint report and the
explanation identity. Three readings of `NormalR4Params().fill_law` would be three places for
the literal that Stage 4B removed to come back.

---

## File naming: grouped by each record's own session date

**Chosen: option 1.** One file per session date, under a per-window sub-directory:

```
scratch/track1_shadow/explanations/<window>/explanations_YYYYMMDD.jsonl
```

Measured reason. A replay window spans many historical sessions — **139 decisions across 75
distinct session dates** on vault2026, **183 across 104** on vault2025. Naming one file after
the run date would produce `explanations_20260823.jsonl` holding rows from 2026-01-02 onward.

This repository has already paid for exactly that shape: a scheduler log named for the day
the process started collected the next day's slots, so looking for last night's window in
last night's file found it empty — which reads exactly like the window never ran. A file
named for a date it does not contain is a trap, so the date in the name is always the date
in the rows, and a test asserts that for every file written.

The per-window sub-directory exists because two windows can cover the same calendar date and
neither may silently overwrite the other's evidence. Cost of the choice: 75 and 104 small
files rather than one. That is the price of a filename that cannot lie.

---

## Counts: shadow decisions vs explanations

Both windows, run in a relocated root so nothing real was disturbed:

| Window | Decisions | Explanations | Files | Session dates | Invalid on re-read |
|---|---|---|---|---|---|
| vault2026 | 139 | **139** | 75 | 75 | **0** |
| vault2025 | 183 | **183** | 104 | 104 | **0** |

Matched by identity, not only by count — the tuple (candidate, sleeve, instrument, verdict)
is compared element for element, because two streams can agree on length and disagree on
every row.

vault2026 breakdown: 91 accepted, 48 rejected (37 cluster cap, 10 family cap, 1 same-symbol).
Rules cited: cluster cap 128, freshness 91, breaker 91, family cap 10, same-symbol 1.

---

## Validation result

Every row validates, and validates again after being read back off disk — which is the
check that matters, since Stage 5X's re-derivation guards only mean something against what
actually landed. **0 invalid rows in 322 across both windows.**

---

## The honest gaps, made into numbers

Three features cannot be filled with a real value today. They are **not** filled with a
plausible one.

| Feature | Why absent | vault2026 | vault2025 |
|---|---|---|---|
| `cluster_gross_after` | the cluster guard returns no number on success and a one-decimal sentence on failure | 128 | 176 |
| `family_gross` | the family check returns the same shape | 10 | 3 |
| `held_by_clusters` | the blocking clusters are named only inside the refusal sentence | 1 | 4 |

The only honest ways to get these are to capture them **inside** the admission loop — an
engine change this stage is not authorised to make — or to parse the refusal sentence, which
is the regex-over-prose failure this route's own audit flagged as the thing to get away from.
So they travel as absent values carrying a `source` that says why, they are counted into the
run summary, and a test fails if that count silently drops to zero. Zero would mean either the
gap was closed (good, and it should be reported) or a value was invented (bad).

What **is** real in every record: the freshness verdict for the run, the breaker state
derived from the verdict itself (the admission function returns the breaker refusal before
looking at anything else, so any other verdict proves the breaker allowed new risk), the ET
wall-clock reading taken with the same function the window gate compares against, the
per-sleeve parameter hash from the same helper the checkpoint uses, the data and regime file
identities, and the git commit.

### A finding the first real run surfaced

**91 of 91 accepted decisions on vault2026 (128 of 128 on vault2025) carry a freshness proof
that says it FAILED.**

That is not a bug in the records. `fresh.evaluate` refused because the regime CSV's last date
was 2026-08-20 against a required 2026-08-21 — and nothing in the shadow route consults its
verdict before running candidates. The freshness result is computed, reported in the summary,
and never gates anything.

For a replay of a historical window that may well be correct: today's regime file being one
session short says nothing about January 2026. But the record is not the place to decide
that, so it states the contradiction, the summary counts it under
`accepted_with_failed_proof`, and a test pins that the counter and the rows agree. **Whether
the freshness gate should bind on a replay, on a live run, or on neither is an open question
this stage did not answer.**

---

## Legacy fingerprint result

**Unchanged.** Ten legacy paths plus every scheduler log, day log and runner-event file are
hashed before and after a shadow run and compared; the fingerprint is asserted non-trivial
first, so it cannot pass by covering nothing.

Stronger evidence than the fingerprint: the run is executed **both ways** — explanations on
and off — into two roots, and the decision file, the settlements file and the book state are
compared **byte for byte**. They are identical. The explanation layer is additive in the
literal sense.

The decision file's key set is pinned as a literal (`ts, trade_id, sleeve, inst, direction,
qty, risk, verdict, detail, forced_closes`) rather than derived from the writer, because
deriving it would make the test agree with whatever the writer currently does. Its text is
also asserted to contain no `explain_id` and no `schema_version`: additive means beside, not
inside.

No monitor file, no dashboard asset and no runtime state file was written. The real
`scratch/track1_shadow` was **not** overwritten either — every run in this stage was
relocated to a temporary root, because a parallel session is working in that directory. Four
files there did change at 08:28; measured, they lack the `explanations` key this stage's code
always writes, so they came from the other session and not from here.

---

## A conflict this stage had to resolve

The Stage 3 route tests call `run_shadow` with `out_dir` pointed at a pytest temporary
directory, precisely to prove a run touches nothing real. The explanation writer's bound is
stricter — it writes only under the shadow root — and it cannot know that directory is
harmless. The two contracts collide.

Resolved by **saying so**, never by loosening the bound and never by silence: when `out_dir`
has been redirected outside the shadow root, explanations are skipped, and the summary
records `written: false` plus a sentence naming why and pointing at `root=` as the supported
way to relocate a whole run. If the route's **own** directory were ever refused, that is a
defect and it raises rather than degrading.

This matters because "no explanations" must never be readable as "nothing to explain" — the
exact conflation the dashboard audit found on the live decision panel.

A hole the tests caught while being written: with zero decisions the destination was never
resolved, so a run aimed at a legacy directory would have passed quietly and only written
there on the first pass that happened to have rows. The destination is now checked **before**
anything is built.

---

## Test update, and why it was deliberate

The scaffold-era test forbade every production importer *including* the shadow route. That
was right while the module was a scaffold. Stage 5Y opens exactly one door, so the test's job
changes from "nothing imports it" to "only that imports it" — the same guard, one name wider.

It now also asserts the allowed door is **actually open**, so it cannot keep passing after
the wiring is reverted, and a second test sweeps the whole monitor tree and every dashboard
asset for any mention. Forbidden importers: the legacy day-runner, the scheduler, the runner,
and four monitor readers including the schedule mirror.

---

## Tests run

```
global_index/test_dashboard_live_snapshot.py
global_index/test_log_hygiene.py
scratch/test_track1_explain_20260823.py              127 passed in 3.88s
                                                     (109 -> 111 in the explain suite)

scratch/test_track1_explain_wiring_20260823.py        30 passed in 53.69s   (new)

scratch/test_track1_stage3_route_20260822.py
scratch/test_track1_stage3b_blockers_20260822.py     113 passed, 2 skipped
                                                     (unchanged from baseline)
```

`global_index/test_event_playback.py` was not run.

### The wiring guards were mutation-checked

Twelve assertions broken in process, one at a time:

| Mutation | Assertion that should fail | Result |
|---|---|---|
| delete the last explanation row from disk | count equals decisions / matched by identity | red (2/2) |
| edit a written row's session date | every row validates / file named for its rows | red (2/2) |
| smuggle a field into the decision file | schema unchanged / no explanation field | red (2/2) |
| remove a verdict from the mapping | every verdict has a mapping | red |
| remove the unmeasured declaration | the builder refuses a feature it has no honest source for | red (raises) |
| make the gap counter report zero | gaps declared and counted | red |
| revert the wiring | only the shadow route imports it | red |
| pretend the monitor imported it | monitor stays clean / forbidden importers | red (2/2) |

All restored to green afterwards. The monitor file touched by the last mutation was restored
byte for byte and asserted so; it currently differs from the index only by a pre-existing
`/realtime-next` route from another session, and contains zero occurrences of the module name.

---

## Final verdict

**Write path wired?** **Yes.** One validated `DECISION` record per shadow decision, written
beside the existing artifacts and never into them, bounded to the shadow root in code.

**Explanations valid?** **Yes.** 322 rows across two windows, zero invalid, including after
being read back off disk.

**Legacy behaviour changed?** **No.** Byte-for-byte identical artifacts with the layer on and
off; legacy fingerprint unchanged; no monitor, dashboard or runtime state file written; the
real shadow directory untouched by this stage.

**Dashboard ready?** **No**, and nothing here moved it closer on purpose. Track 1 slots are
still invisible to every health signal the monitor has — enabling the slot mirror changes
only the "next job" caption — so an explanation drawer would hang off a row that never
appears.

---

## Next step

1. **Decide whether the freshness verdict should gate anything.** It is computed on every
   shadow run, reported, and consulted by nothing. Right now every accepted decision carries
   a proof that says it failed. Three possible answers — bind it on live only, bind it
   always, or state that a replay is exempt — and the records cannot choose between them.
2. **Close the three measured gaps** by capturing the cap numbers inside the admission loop.
   That is an engine change and needs its own stage, its own equivalence test against the
   current decision stream, and the owner's agreement that touching the signal layer is in
   scope.
3. **Settle the older owner question** carried over from Stage 5X: is the empty live decision
   block a design choice or a wiring gap?
4. **Teach the health slot table about Track 1** before any endpoint or drawer work. Until a
   Track 1 slot failure can raise an incident, there is nothing on screen to attach an
   explanation to.
