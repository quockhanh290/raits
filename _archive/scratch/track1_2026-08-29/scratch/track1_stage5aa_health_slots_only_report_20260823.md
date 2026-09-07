# Stage 5AA-SAFE — Track 1 slots in the dashboard health table

**Session 2026-08-23 · schedule-status backend only · nothing committed**

---

## Files edited

| File | Change |
|---|---|
| `monitor/backend/schedule_status.py` | three additions, all gated on the existing flag |
| `monitor/test_schedule_status_track1_20260823.py` | **new** focused backend test file |
| `scratch/track1_stage5aa_health_slots_only_report_20260823.md` | this report |

A **new** test file was written rather than extending `monitor/test_dashboard_backend.py`
(4,091 lines, shared lane) — same allowed category, far lower collision risk.

## No forbidden file was edited

Verified by content hash taken before work started and again at the end:

```
global_index/run_live_day_track1.py  629d2f8b…f061363   identical before and after
global_index/track1_explain.py       52aa85f1…f726bd11e  identical before and after
```

Every other forbidden file's mtime predates this stage's first edit (09:54):
`track1_freshness.py` 08-22 22:33 · `track1_signal_layer.py` 08-22 23:12 ·
`track1_slots.py` 00:52 · `run_scheduler.py` 08:39 · the three Stage 5Y/5Z test files
09:00–09:04. No frontend or UI file, no scheduler runtime file, and no write to the real
`scratch/track1_shadow`.

A test in the new file also asserts the boundary rather than trusting it: `schedule_status`
must not import `run_live_day_track1`, `track1_explain` or `ib_insync`, and `app.py` plus
every dashboard `.js` must contain no `explanation` / `explain_id` reference.

---

## The defect this closes

Measured before the change: flipping `RAITS_TRACK1_SHADOW` altered **exactly one field** of
the whole schedule-status payload — `next_scheduled_job`. There are two slot tables and the
mirror only fed one of them.

| Table | Feeds | Flag OFF | Flag ON (before) |
|---|---|---|---|
| scheduled-job mirror | "what runs next" caption | 57 | 81 |
| **state / health table** | freshness, lateness, evidence, incidents | **45** | **45** |

So a Track 1 slot that failed at 11:05 could not raise an incident, could not make the rail
late, and sat inside a period the dashboard still labelled *not expected yet*.

### Why it is safe to add them now

The scheduler emits a marker `_evidence()` can already parse. `_track1_body` calls
`_run(..., label=slot_id)` and `_run` logs `[%s] %s`, i.e. `[TRACK1_STRESS_1035] …` — exactly
the bracket form the evidence scanner looks for. Without that, every Track 1 slot would sit
at `not_observed` forever and manufacture the fake daily incident this module's own comment
warns about. That was checked in the scheduler source before a line was written here.

---

## Visibility before / after

| | Flag OFF | Flag ON before | Flag ON after |
|---|---|---|---|
| health slot table size | 45 | 45 | **70** (45 + 25) |
| Track 1 slots in health table | 0 | 0 | **25** |
| active-window bands | 2 | 2 | **4** (+ Calm 10:00, + Stress 10:35–12:30) |
| Track 1 slot can raise an incident | no | no | **yes** |
| Track 1 slot can be marked recovered | no | no | **yes**, per sleeve |
| scheduled-job mirror | 57 | 81 | **81 (unchanged)** |

The scheduled mirror was deliberately **not** touched, so `parity_report` stays true on both
sides of the gate — asserted in the new suite for `track1_shadow=True` and `False`.

---

## Exact flag OFF vs ON behaviour

Whole-payload diff on a pinned Monday at five pinned ET instants:

| ET | keys that differ |
|---|---|
| 07:00 | `state_slot_count`, `expected_next_at` |
| 10:10 | `active_window`, `state_slot_count`, `latest_expected_at`, `expected_next_at`, `evidence` |
| 11:05 | the above + `next_scheduled_job`, `unexplained_overdue` |
| 12:15 | the above |
| 14:30 | `state_slot_count`, `unexplained_overdue` |

`scheduler_process` also appears in the raw diff and is **not** a flag effect: two
consecutive calls under the *same* flag differ in that key too, because its `age_seconds` is
computed from wall-clock `now()`. Measured and excluded rather than reported as a change.

**Flag OFF is the legacy baseline, unchanged.** The state table is 45, the windows are the
two legacy bands, no `TRACK1` string appears anywhere in the payload, `STOP_REPAIR_1220` is
present, and no Track 1 slot appears in any of the three slot functions.

**Flag ON**, additionally:
- a due Track 1 slot with no closing line becomes `unexplained_overdue` and the rail reads
  `late`;
- a clean slot reads `executed` / severity `none`;
- a failed slot reads `failed` / severity `incident`;
- an incident is marked `recovered` by a later clean slot **of the same sleeve** — a Stress
  run cannot recover a Calm failure, because `_stream_of` yields `TRACK1_CALM` and
  `TRACK1_STRESS` separately;
- a fully clean Track 1 day raises **zero** incidents and **zero** overdue rows;
- `STOP_REPAIR_1220` remains excluded, exactly as Stage 5 specified.

### Implementation notes

Three small additions, all deriving from `track1_slots.TRACK1_SLOTS` rather than retyping:

- `_track1_state_slots(day)` — Track 1 slots as health slots, empty unless the flag is on.
  The allowance is read off the slot's own `kind`: a `one_shot` gets the 15-minute grace the
  legacy final slots get (a missed 10:00 cannot be retried), a `window` slot gets 8 minutes
  (inside the window a missed slot costs nothing).
- `_active_windows()` — the two legacy bands, plus one band per Track 1 sleeve when the flag
  is on, computed from the slot table's own min/max.
- `_state_slot_table_size()` — legacy count when off, legacy + Track 1 when on.

`_slots_for` gained one `out.extend(...)` line. `_pipeline_slots_for` and
`_scheduled_slots_for` were not touched, which is what keeps parity and prevents a
double-add.

---

## Tests run

```
monitor/test_schedule_status_track1_20260823.py       26 passed   (new)
monitor/test_dashboard_backend.py                    187 passed
monitor/test_realtime_contract.py                     22 passed
global_index/test_dashboard_live_snapshot.py
global_index/test_log_hygiene.py                      17 passed
scratch/test_track1_stage3_route_20260822.py
scratch/test_track1_stage3b_blockers_20260822.py     113 passed, 2 skipped

the other two suites that read schedule_status:
scratch/test_track1_stage4_production_clean_20260823.py
scratch/test_track1_stage5b_runbook_fix_20260823.py    47 passed, 1 skipped
```

All three skips are opt-in slow tests, unrelated to this change:
`TRACK1_EQUIV_FLOOR=1`, `TRACK1_REGEN=1`, `TRACK1_STAGE4_ALL=1`.

`global_index/test_event_playback.py` was not run. Stage 5Y/5Z suites were not run — this
change does not touch the explainability path.

### Mutation-checked

Eleven assertions broken in process, one at a time:

| Mutation | Assertions that should fail | Result |
|---|---|---|
| revert `_slots_for` to legacy-only | flag-ON adds the slots / due slot goes overdue | red (2/2) |
| leak Track 1 into the flag-OFF path | 45-slot table / legacy bands / no Track 1 anywhere / payload clean / stop-repair 12:20 present | red (5/5) |
| drop the Track 1 window bands | a Track 1 window is active / a band per sleeve | red (2/2) |
| flatten the allowances | allowance follows the slot kind | red |
| group all Track 1 slots into one stream | a Calm failure is not recovered by a Stress run | red |
| double-add to the scheduled mirror | no duplicate ids | red |

All restored to green.

---

## Legacy behaviour with the flag off

**Unchanged.** 45-slot table, two window bands, `STOP_REPAIR_1220` present, no `TRACK1`
string in the payload, and the full 187-test dashboard backend suite green. The mutation
that leaks Track 1 into the flag-off path turns five assertions red, so the isolation is
enforced rather than intended.

---

## Is the dashboard drawer unblocked?

**The blocker named in Stage 5X/5Y/5Z is closed; a different one now governs.**

The stated reason a drawer could not be designed was that a Track 1 slot failure was
invisible, so a drawer would hang off a row that never appears. That is no longer true: with
the flag on, a Track 1 slot now produces an evidence row, can raise an incident and can be
marked recovered.

What still blocks the drawer, and is out of this stage's scope:

1. **No reader and no endpoint.** Explanation records exist only as JSONL under
   `scratch/track1_shadow/explanations/<window>/`. Nothing serves them, by instruction.
2. **No link key on screen.** A slot row carries a `slot_id`; an explanation carries an
   `explain_id` keyed by candidate. Nothing joins the two yet.
3. **The Stage 5Z cross-impact gap G1 is still open** — `run_shadow` takes both
   `source_name` and `mode` with independent defaults and `main()` never passes `mode=`, so
   `--source live` would emit records stamped `replay`. Designing a drawer on top of records
   whose mode field can be wrong would bake that error into the UI.

---

## Collision / concurrent-edit observations

**No collision in this stage.** The two files I edited were untouched by anyone else
throughout; both forbidden Track 1 files hash identically to the baseline I took at 09:52.

Observed, not caused by me: `global_index/run_scheduler.py` was modified at 08:39 and
`run_live_day_track1.py` at 09:08 by the parallel Stage 5D/5E session, both before this stage
began, and both stable since. `run_live_day_track1.py` remains **untracked in git**, so there
is still no baseline any audit can diff against — the point raised in the collision audit and
still unresolved.

---

## Final verdict

**Track 1 health slots visible?** **Yes** — 25 slots in the health table, 4 active-window
bands, incidents and recovery working per sleeve, when `RAITS_TRACK1_SHADOW=1`.

**Legacy flag-off behaviour changed?** **No.** 45 slots, two bands, no Track 1 string in the
payload; 187-test backend suite and the required pair both green; enforced by five
mutation-checked assertions.

**Forbidden files touched?** **No** — proven by identical content hashes before and after,
plus mtimes predating this stage.

**Collision observed?** **No** in this stage. The parallel session's earlier edits to two
other files are noted above and did not overlap.

**Dashboard drawer now safe to design?** **Partly.** The visibility blocker is closed, but
three things still stand in the way: no route-scoped reader or endpoint, no key joining a
slot row to an `explain_id`, and the open Stage 5Z gap G1 where a live-source run would be
stamped `replay`.

---

## Next step

1. **Close G1 first.** Derive `mode` from `source_name` in `run_shadow`, or refuse a
   mismatch. It is a few lines, it is latent only while the live source refuses, and every
   record written after the live source starts working depends on it being right. It belongs
   to whoever owns `run_live_day_track1.py` — not to this lane.
2. **Decide the join key** between a schedule-status slot row and an explanation. A slot is
   keyed by `slot_id` and a session date; an explanation by `candidate_id`. One of them has
   to carry the other, and that decision precedes any reader.
3. **Then** a route-scoped reader and endpoint — new, never a widening of a legacy one, per
   the Stage 5X integration path.
4. **Commit, or assign one owner to** `run_live_day_track1.py`. Two sessions edited an
   untracked file today; that is still true and still unmitigated.
