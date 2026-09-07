# Stage 5ZH — the audit was reading a checkpoint shape nothing has ever written

**2026-08-25, ET 21:10–22:00.** No orders · no confirmation file · `TRACK1_ORDERS_APPROVED`
unset · no `--allow-orders` · **nothing restarted** · no IBKR call · **no runtime evidence
written or edited** · no strategy change · no paper-gate change.

```text
UTC 2026-08-26 01:55 · ET 2026-08-25 21:55 EDT · Calgary 19:55 MDT · Tokyo 10:55 JST (26th)
```

---

## Verdicts

| | |
|---|---|
| `checkpoint_wrong_route: route is None` | **live defect in the READER** — reproduced on demand, not stale, not expected behaviour |
| 2026-08-25 Swing window | **operationally valid** — and it now **PASSES** its audit |
| a future quiet complete Swing window | **passes**, provided both artefacts are present and dated today |
| any runtime / live file touched | **no** — every evidence file still carries its 13:56–14:15 mtime |
| paper readiness | **unchanged** — `NOT_READY`, same four blockers |
| Track 1 trade log path (5ZG) | untouched here |

---

## 1. Reproduced first, before touching anything

```text
evaluate_day("2026-08-25").checks["checkpoint"]
  status : fail
  detail : route is None

evaluate_sleeve("2026-08-25", "roska4_swing")
  verdict : FAIL
  reasons : ['all_slots_observed_no_action', 'checkpoint_wrong_route']
```

Byte for byte what the 20:15 UTC audit record says. **Current, reproducible, not a stale
artefact.**

The day's audit file also dates the change of symptom precisely. At 16:40 UTC the checkpoint
check said *"global_index/replay_checkpoint.track1.json does not exist"*; at 20:05 and 20:15
it said *"route is None"*. The file appeared between those two runs — at 15:56:19 ET, one
second after the 15:55 Swing slot closed a complete window. So the writer did its job in
between, and the reader's complaint changed from absence to nonsense.

## 2. The writer is correct — and the evidence says which window wrote it

`write_route_checkpoint` is called from exactly one production site, and only when
`slots_decided >= expected`. The day proves the guard held:

| sleeve | window closed ET | complete? | checkpoint after it? |
|---|---|---|---|
| `global_nkd` | 02:55 | no (0 of 22 decided) | **no** — 16:40 UTC audit: "does not exist" |
| `roska4_stress` | 12:30 | no (17 of 24) | **no** — same audit, same answer |
| `roska4_swing` | **15:55** | **yes (23 of 23)** | **yes — 15:56:19 ET** |

Three windows closed, only the complete one wrote. `live_positions.track1.json` carries the
same second, because `track1_bootstrap.write` produces both artefacts in one call.

What it wrote is valid schema 2 and loads cleanly through the route module's own loader:

```json
{"schema_version": 2,
 "routes": {"track1_candidate": {"sleeves": {
    "roska4_swing": {"instruments": {}}, "global_nkd": {"instruments": {}},
    "roska4_calm":  {"instruments": {}}, "roska4_stress": {"instruments": {}}}}}}
```

Empty instruments are correct for a quiet window and are a designed state, not an accident.
The route's own code says so in two places: *"present-but-empty says 'accounted for' where
absent would say 'nobody thought about it'"*, and *"a checkpoint recording that nothing was
open is as valid as one recording a position"*.

## 3. The reader was written against a shape that has never existed

```python
payload = json.loads(ck.read_text(encoding="utf-8"))
cut = str(payload.get("cut_instant", ""))[:10]
if payload.get("route") != "track1_candidate":
    ... FAIL f"route is {payload.get('route')!r}"
```

Flat `route`, flat `cut_instant`. **Neither key exists in schema 2**, where the route lives
one level down under `routes` and the day lives on each instrument entry as `last_day`. So
`payload.get("route")` was always going to be `None`, and the sentence *"route is None"* was
never a description of the file — it was a description of the reader.

Not "reading the wrong file": right file, wrong schema, and specifically the schema-1 shape.

**This check has never been able to pass against a real checkpoint.** It looked green only
because it had never met one — before today the file did not exist, so it failed on absence
instead.

### Why nothing caught it

Three test suites cover this check, and all three build their fixture by hand:

```python
{"schema_version": 2, "route": "track1_candidate",
 "cut_instant": f"{day}T15:55:00", "sleeves": {}}
```

That payload is not merely unusual. Measured: `route_checkpoint.load()` returns `{}` for it —
the route module **refuses** it, because it has no `routes` key. Nothing in the system could
have produced it and nothing could have consumed it. It existed only to agree with the reader,
which is the one thing a fixture must never be built to do.

The whole defect is one line of causation: reader and fixture written together, writer never
consulted.

## 4. The same defect, read a second time — on the dashboard

Found while repairing the neighbours. `monitor/backend/track1_runtime_reader.py` summarised
the checkpoint with the identical flat keys, so the Track 1 panel reported:

```text
before   route: null    sleeves: []          (for a file that names its route perfectly well)
after    route: track1_candidate   sleeves: [4]   entries: 0
```

Fixed in the same stage, because it is one defect read twice, and the second copy is the one
an operator looks at.

## 5. The quiet-window contract — Option C, which the writer already implements

An empty checkpoint carries no day anywhere: `last_day` is a property of an instrument entry
and there are none. So "is this today's checkpoint?" has no answer from the checkpoint alone.

The answer is the companion book. `track1_bootstrap.write` writes the book and the checkpoint
in one call, atomically beside each other, and the book carries `cut_instant`. That is Option
C — *"must write both checkpoint and empty book marker"* — and it is not a new requirement:
it is what the writer has always done. Only the acceptance rule needed to learn it.

The rule now:

| condition | verdict |
|---|---|
| file absent | FAIL `checkpoint_missing` |
| unparseable, not schema 2, or no `routes` map | FAIL `checkpoint_unreadable` |
| `routes` does not hold `track1_candidate` | FAIL `checkpoint_wrong_route`, naming what it *did* hold |
| entries present, all `last_day` == the judged day | **OK** — the book is not consulted |
| entries present, any other day | FAIL `checkpoint_wrong_day` |
| no entries, book says the judged day | **OK** — the quiet-window pass |
| no entries, book says another day | FAIL `checkpoint_wrong_day` |
| no entries, no book / unreadable / undated | FAIL `checkpoint_day_unverifiable` |

The last row is the one that matters. *"I could not check"* is not *"I checked and it was
fine"*, and this route has spent five stages removing exactly that collapse from its broker
reads. It would have been easy to pass a quiet checkpoint for lack of any way to date it.

Also removed: the reason was classified by matching prose (`"route is" in detail`). It now
carries a structured `code` and a code→reason table, so rewording a sentence cannot silently
re-label a failure. Two conditions that an `else` used to force into `wrong_day` — a payload
of the wrong *shape*, and a day that could not be *established* — now say what they are.

Unchanged, deliberately: a checkpoint is only ever asked for after a **complete** window, and
a passing checkpoint never rescues anything. It can only add a failure.

## 6. The result

```text
roska4_swing    PASS   reasons=['all_slots_observed_no_action']
                checkpoint: ok — route ok, no entries (a quiet window admitted nothing),
                               book cut 2026-08-25

roska4_stress   FAIL   coverage_incomplete, missing_slot_ids
roska4_calm     FAIL   coverage_unobserved, missing_slot_ids, no_timing_records
global_nkd      FAIL   coverage_incomplete, slot_could_not_evaluate, no_candidates_to_explain
```

**The first Track 1 sleeve window ever to pass its audit.** The other three still fail on
their own genuine grounds — the machine slept through Calm's single slot and Stress's first
seven, and NKD's slots were gate-refused as stale. None of those is a checkpoint problem and
none of them was touched.

`all_slots_observed_no_action` survives as a reason on a PASS. It never set the verdict; it is
the sentence that says a quiet window was quiet, and it stays. A window that admitted nothing
should say so out loud, not pass in silence.

## 7. Named, not fixed: the checkpoint cannot resume anything

The one production call site is:

```python
write_route_checkpoint(a.sleeve, now_et=now, regime_csv=..., data_paths=default_data_paths())
```

No `frames`. `checkpoint_entries` skips every instrument whose frame is missing, so the entry
map is empty **whatever the day did** — a day with an open Swing position would write the same
empty file. `get_entry` then returns `{}`, `usable` refuses with `no_entry`, and every run
replays in full.

So the artefact is real, correctly scoped, correctly guarded and currently **inert**: it
records that a window completed, and nothing that could accelerate a resume. Five instruments'
worth of identity — fingerprint, params hash, data source, last day — none of it recorded.

Not fixed here. Loading four Swing frames plus MNKD at window close is real work inside a
78.5s p95 budget, and the stage's remit is the audit reader. Recorded as a blocker for a stage
of its own. Harmless while in shadow, because there is nothing to resume; not harmless once
the route holds a position overnight.

## 8. Tests

**46 tests**, `scratch/test_track1_stage5zh_quiet_checkpoint_audit_20260825.py`. All eight
items the brief asked for, plus the branches the code suggested.

**Every checkpoint in the file is produced by `route_checkpoint.save_route`**, never written
by hand. That is the direct lesson: a fixture that agrees with the reader proves the reader
agrees with itself. One test exists purely to keep it that way — a hand-built payload must
equal `empty_payload`'s output byte for byte, so the two can never drift apart again.

Notable coverage beyond the list:

- the flat payload three suites used is refused, **and** `rc.load` rejects it — pinned, so
  nobody re-adopts it;
- a `routes`-shaped payload of any other schema is still refused, so a future schema 3 cannot
  be read as schema 2 — this one was added *because* the mutation survived without it;
- entries win over the book: a checkpoint cut on the 19th fails even if the book says today;
- a second route beside ours does not disturb the check, because `save_route` merges scoped;
- the wrong-route failure must name what it *did* find;
- rewording a detail cannot change the reason.

**Mutation harness: 15 mutations, 15 red.** Source-level edits run in a subprocess; every
mutation proves its tests green first. One survivor on the first pass — removing the schema
guard changed nothing, because the `routes` guard caught every fixture behind it. That was a
real gap, not a harness artefact, and it is now covered.

One test of my own caught a wrong assumption while being written: a foreign-route checkpoint
written *over* an existing one leaves ours in place, because `save_route` merges scoped by
design. The test was asking the wrong question; the writer was right.

## 9. Repaired neighbours

Six tests in four suites depended on the invented flat payload, and were repaired to go
through the writer:

| suite | change |
|---|---|
| 5Q `build_green_day` | fixture via `save_route` + companion book |
| 5Q `test_a_checkpoint_naming_another_route_fails` | unlink first, then a foreign-route file |
| 5Q `test_a_checkpoint_cut_on_another_day_fails` | moves the **book's** day, which is where an empty checkpoint's day lives |
| 5Q1, 5Q2 fixtures | same, via `save_route` |
| 5P `test_a_wrong_checkpoint_fails` | three real ways to be wrong, replacing two impossible ones |
| 5P `test_the_reader_reports_a_green_day…` | the book is present now — a checkpoint without one was never reachable |

Two further failures in those same files were the *absence-as-proxy* pattern this project has
already diagnosed three times, and both were fixed because this stage was editing the files
anyway:

- 5P asserted `live_positions.track1.json` absent. The live 15:55 close writes it, by design,
  in the same call as the checkpoint. Moved onto the mtime check that already sat three lines
  below it for the max-hold marker, which came off the same list on 2026-08-24 for the same
  reason.
- 5Q2 asserted no file in the real shadow tree has today's date in its name. Forty live
  explanation files do, written between 11:11 and 14:11 ET by the system doing its job. A name
  match said *"a test wrote this"*; it only ever meant *"a file for that day exists"*. Now
  asked by mtime, which cannot be satisfied by the system working correctly.

## 10. Regression

| suite | result |
|---|---|
| Stage 5ZH | **46 passed** |
| Stage 5ZH mutations | **15 / 15 red** |
| acceptance and checkpoint (5Q, 5Q1, 5Q2, 5Q3, 5P, route-checkpoint stage 1, bootstrap stage 2, dashboard wiring) | passed |
| Stage 5ZG, 5ZF, 5ZE, 5ZD, 5ZB, dashboard backend, realtime contract | passed |
| **combined** | **836 passed, 0 failed** |

`test_event_playback.py` not run.

Three failures seen mid-stage in suites this stage did **not** touch are pre-existing and
unrelated, measured rather than assumed: `stage3_route::test_8c` asserts
`live_positions.track1.json` absent (written by the live system at 13:56, hours before any
edit here), and two `stage4b` tests expect a blocker list without `PAPER_SHADOW_EVIDENCE`, a
gate added after that stage and defined in files this stage never opened. Same class as the
two repaired above; left alone under the brief's instruction not to chase untouched suites.

## 11. Files touched

| file | change |
|---|---|
| `global_index/track1_shadow_acceptance.py` | `checkpoint_check()` reads schema 2; quiet-window day proof; structured codes; two new reasons; docstring corrected |
| `monitor/backend/track1_runtime_reader.py` | the panel's checkpoint summary reads schema 2 |
| `scratch/test_track1_stage5zh_…py` | new, 46 tests |
| `scratch/track1_stage5zh_mutations_…py` | new, 15 mutations |
| `scratch/test_track1_stage5q…`, `5q1`, `5q2`, `5p…` | fixtures now go through the writer; two absence-proxies repaired |

**No file under `global_index/track1_runtime/`, no `replay_checkpoint.track1.json`, no
`live_positions.track1.json`, no audit record.** Every one still carries its live mtime:
13:56:19 for the two artefacts, 14:15:03 for the audit journal, against 19:37 and 19:44 for
the two source files this stage edited.

## 12. Paper readiness — unchanged

| blocker | class | open |
|---|---|---|
| `PAPER_SHADOW_EVIDENCE` 0 / 5 clean sessions | evidence | **yes** |
| `B1_broker_account_or_legacy_retirement` | operator | **yes** |
| route-aware P&L / Flex / session report | code | **yes** — 5 of 6 pieces |
| `verify_regime_labels` warn-only | code | **yes** |
| checkpoint cannot resume anything (§7) | code | **new, named here** |

Measured: `orders_possible=False`, blocking
`['B1_broker_account_or_legacy_retirement', 'PAPER_SHADOW_EVIDENCE']`, no confirmation file,
no orders directory.

One thing did move, and it is worth stating precisely rather than generously — precisely
enough that a first draft of this paragraph was wrong and is corrected here.

The evidence gate asks for five judgeable days, **zero** of them FAIL, at most one WARN, every
sleeve PASSED at least once, and evidence no older than 21 days. It reads the audit **records
written to disk**, not a fresh evaluation. The 2026-08-25 Swing record was written at 20:15
UTC, before this fix, and still says FAIL; re-running the audit for that day would write a
corrected record, and this stage did not do that because it would be writing runtime evidence.

So measured against the gate right now, `every_sleeve_passed_at_least_once` reports
`passed: []` — nothing has moved. What changed is that a Track 1 window can now pass at all,
which before tonight it could not, whatever it did. The day itself would still be FAIL either
way: Calm, Stress and NKD all failed, and one FAIL day is one too many.
