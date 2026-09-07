# Stage 5Q-3 — the live frame's schema, and a splice refusal that leaves a record

**2026-08-24 ·** scheduler **not** started, stopped or restarted (pid 28696, started
07:25:31 local = 09:25 ET, unchanged before and after) · backend **not** restarted · no IBKR
connection made by this work · no order · no `--allow-orders` · `TRACK1_ORDERS_APPROVED`
unset · no `STOP_TRADING`, `STOP_TRADING.track1` or confirmation file · every test write went
to `tmp_path` · no commit · no strategy logic, order gate or job inventory changed.

---

## Verdict: **B-5R-A AND B-5R-B CLOSED — and one live blocker remains, which is not a schema problem**

Both faults in this morning's one-line failure are fixed and each has been observed failing
when removed. But the fix does not unblock today's Stress window, and saying so is the point:
`overlap_disagreement` fires *before* the splice and it is a price disagreement, not a schema
one. Detail in **What is still blocking**.

---

## 1. Which layer owns the schema projection

**`global_index/track1_live_source.live_frame` — the only caller of `splice` in this repo.**

Asserted, not asserted-in-prose: a test scans every production module in `global_index/` and
requires the list of files containing a `splice(` call to be exactly
`["track1_live_source.py"]`.

The projection sits immediately after `on_frozen_clock` — the other "normalise the live half"
step — and before the two pre-splice refusals:

```text
fetch  ->  on_frozen_clock  ->  project_to_frozen_columns  ->  bars_from_the_future
       ->  overlap_disagreement  ->  guard.splice
```

**Schema before prices, deliberately.** The overlap check compares values column by column and
cannot compare a column that is not there. A test pins the ordering by handing in a feed that
is *both* wide and mis-converted and requiring the clock refusal.

**Why not relax the guard instead.** `track1_live_frame.splice` keeps its rule that the two
frames must have IDENTICAL columns. Relaxing it to "extras are fine" would let a future caller
that forgot to project hand it a wider frame and get a wider frame back, with provider fields
riding downstream into every sleeve. With one caller, normalising in the caller costs nothing
and keeps the guard able to catch a caller who skips the step — pinned by its own test, and
mutation **M6** relaxes the guard and reds it.

### The three rules

| the live half | what happens |
|---|---|
| carries extra provider columns | **DROPPED**, and the names travel with the frame |
| is missing a frozen column | **REFUSED**, `missing_required_columns`, naming the column |
| has NaN in a frozen column | **REFUSED**, `nan_in_required_columns`, naming column and first bar |

Never synthesised. A made-up `volume` of 0 or a forward-filled `close` is a bar every
indicator downstream would treat as measured.

**Extras are dropped by a general rule, not an allowlist.** An allowlist of
`average`/`barcount` is a table that drifts the first time IBKR adds a field, and it would
refuse a harmless new column with a message about a column nobody reads. What matters is that
the frozen schema is complete and carries the frozen columns' own values — which dropping
guarantees. What must not happen is the drop being **invisible**, so the names are returned,
carried on `JoinedFrame.dropped_columns`, and printed in its record. A new name appearing
there is how anyone finds out the feed changed shape. Mutation **M5** silences the names and
reds.

Column order comes from `frozen`, so the two frames are identical rather than merely equal as
sets — `splice` compares lists.

---

## 2. The reason code for a caught `SpliceRefused`

**`live_frame_refused`**, with the guard's own code in `detail`:

```json
{"event": "slot_observed", "slot_id": "TRACK1_CALM_1000", "decided": false,
 "reason": "live_frame_refused",
 "detail": "column_mismatch: frozen columns [...] != live [...]"}
```

The stage is the reason, the check is the detail — the same shape `gate_refused` already uses
for the intraday gate's codes, so a window of these rows can be told apart at a glance.

`observe_live_slot` caught four exception types and `SpliceRefused` was not one of them, so it
propagated and the slot died before writing anything. The module's own docstring already said
the refusal is the record; it just did not say it about this one.

**The audit needed no change.** `live_frame_refused` has `decided=False` and a reason that is
not `gate_refused`, so `classify_slot_row` already returns `observed_hard_refusal` — verified
by test rather than assumed. And because the slot now writes its row and closes its window,
the audit reports `slot_could_not_evaluate` instead of `coverage_unobserved` +
`missing_slot_ids`: "the slot looked and the join was refused, here is the code", not "nobody
looked". Mutations **M8** and **M9** each turn it back into a softer verdict and red.

---

## 3. A third defect, found while checking the timing story

The brief asked whether a caught refusal would still leave a timing row, and preferred that it
does. Measuring that turned up something larger:

**`run_live_day_track1.py` had never imported `slot_telemetry` at all.** The word "telemetry"
appeared in it exactly once, in a comment naming the recommended directory. `slot_timing/` was
created, `monitor/ops.py` exported `RAITS_TELEMETRY_DIR` to the child, and **no Track 1
strategy slot has ever written a timing row** — which makes the acceptance gate's
`no_timing_records` unsatisfiable and its p95 cadence check unable to run on anything.

Wired now, in the same additive shape the legacy runner uses: `begin()` before argument
parsing so a slot that dies on its own argv still records that it started, `mark()` for sleeve
and outcome, and `set_outcome("ok")` when the slot completes. Off unless
`RAITS_TELEMETRY_DIR` names a directory.

`ok` means **the slot ran**, not that it decided. A refusal recorded by name is a successful
observation of a window that refused, and its runtime belongs in the cadence numbers exactly
as much as a decision does — the p95 gate asks how long slots take, not how many liked what
they saw.

**Measured live, from the running scheduler, first Track 1 timing rows ever written:**

```text
TRACK1_STRESS_1100  ok  2.641s  route=track1_candidate  reason=overlap_disagreement
TRACK1_STRESS_1105  ok  2.671s
TRACK1_STRESS_1110  ok  2.766s
TRACK1_STRESS_1115  ok  2.734s
```

The p95 gate has a number for the first time: **2.7 s** against a 240 s target and a 300 s
ceiling. Mutation **M10** removes the wiring and reds.

---

## 4. Today's evidence — what is left as it is

**`TRACK1_CALM_1000` remains a failed slot for 2026-08-24 and nothing was rewritten.**

It ran at 10:00 ET on the code as it stood, crashed in the splice, and left only a
`window_open` line. The 10:10 audit job recorded `FAIL` with `coverage_unobserved`,
`missing_slot_ids` and `no_timing_records`. That record stands. Migrating or back-filling it
would be manufacturing evidence for a window nobody observed, which is the one thing this
route's whole ledger design exists to prevent.

Only slots that spawn *after* the change pick it up — and that is visible in the tree: the
Stress slots from 11:00 ET onward are the first with timing rows.

Read-only audit of the live tree at 11:19 ET, writing nothing:

```text
roska4_calm    10:00-10:00  FAIL                 expect 1  observed 0  p95 None
      coverage_unobserved, missing_slot_ids, no_timing_records
roska4_stress  10:35-12:30  NOT_ENOUGH_DATA_YET  expect 24 observed 9  p95 2.7
      window has not closed yet (closes 12:30:00, now 11:19:29)
```

---

## 5. What is still blocking, and the honest correction to my own brief

**The Stress window is refusing for a different reason, and the schema fix does not touch it.**

Every Stress slot today records:

```text
overlap_disagreement — MNQ: the live half and history disagree on 1 of 1186 shared
timestamps in 'low'; first at 2026-08-21 13:45:00-04:00, history says 29400.2500 and the
feed says 29395.7500, largest gap 4.5000
```

That check runs **before** the splice, so those slots never reached the column mismatch — and
they will not reach it after the fix either. One bar of MNQ history, 2026-08-21 13:45 ET,
disagrees with the feed by 4.5 points in `low`. Two readings of the same instrument at the
same instant cannot differ: this is a contract, a source or a stored-data question, and the
guard is right to refuse.

So the correct statement, replacing the one in the Stage 5Q-2 report that named the column
mismatch as the single thing standing between this route and a judgeable day:

> **B-5R-A was one of two live-frame blockers, not the only one.** The column mismatch stopped
> the sleeves without an overlap disagreement — Calm. `overlap_disagreement` stops MNQ, which
> is Stress's only instrument and one of the swing basket's four. Fixing the schema was
> necessary and is not sufficient.

### Blockers before Stage 5R

| id | what | state |
|---|---|---|
| **B-5R-D** *(new)* | one MNQ history bar at 2026-08-21 13:45 ET disagrees with the live feed by 4.5 pts in `low`. Refuses every Stress slot, and MNQ is in the swing basket too | **open — the live one** |
| **B-5R-C** | NKD after 2026-11-01: 12 of 22 ET slots fall outside the Tokyo decision band | open, reported as WARN |
| **B1** | the order gate | open by design; orders impossible |
| ~~B-5R-A~~ | live frame column mismatch | **closed by this stage** |
| ~~B-5R-B~~ | `SpliceRefused` crashed the slot | **closed by this stage** |
| ~~B-5R-1/2~~ | writer truncation, substring freshness check | closed by 5Q-2 |

B-5R-D is a data question, not a code one, and it is deliberately not touched here: deciding
whether the parquet bar or the feed is right — and which one to change — is a stored-history
decision with its own audit trail.

---

## 6. Tests

| Suite | Result |
|---|---|
| **Stage 5Q-3** `test_track1_stage5q3_live_frame_splice_20260824.py` (new, 32) | **32 passed** |
| **Stage 5Q-3 mutation harness** (new, 10) | **10 / 10 detected**, four production files restored byte-for-byte |
| Track 1 scratch regression (24 files) | **903 passed, 2 skipped** |
| `monitor/` production suites (6 files) | **313 passed** |

`global_index/test_event_playback.py` **not run** — still the known hang.

### The ten mutations

```
M1   the live half is spliced without being projected   -> the extras test reds
M2   the projection runs AFTER the concat               -> the no-NaN test reds
M3   a missing frozen column is filled not refused      -> the missing-column test reds
M4   a NaN in a frozen column is allowed through        -> the NaN test reds
M5   the dropped column names are not reported          -> the named-drop test reds
M6   the guard tolerates mismatched columns             -> the skipped-projection test reds
M7   SpliceRefused is not caught                        -> the slot-record test reds
M8   the refusal is filed as a gate refusal             -> the audit test reds
M9   the audit calls it an observed no-action           -> the classification test reds
M10  the slot stops emitting telemetry                  -> the wiring test reds
```

**M1 and M3 are not inventions — they put back exactly what was on disk at 10:00 ET**, and
what that cost is in section 4.

### Two older tests changed meaning, and neither is a weakened test

**`test_mismatched_columns_are_refused` (Stage 4C)** asserted `SpliceRefused` /
`column_mismatch` for a live half missing `volume`. That refusal now happens earlier and by a
more specific name — `LiveSourceRefused` / `missing_required_columns`, which names the column.
The contract it defends is unchanged; what changed is which layer says so. A new test beside
it pins the other half (extras no longer refuse), and the guard's own `column_mismatch` is
still live and still reachable, pinned by the 5Q-3 suite.

**`test_no_legacy_path_is_touched` (Stage 5Z)** fingerprinted `scheduler_*.log` before and
after a shadow run and went red because the **live scheduler** appends to it every five
minutes. A different process doing its job is not this route touching a legacy path, and a
guard that goes red whenever the system is running is one people learn to skip. The property
was kept and made stronger: the shadow entry point must not NAME a scheduler or log file at
all.

That replacement's own first draft was wrong in a way worth recording: `".log" not in src`
went red on the module **docstring**, which describes the files the route must not write — a
substring test over free text, the same shape as the freshness check 5Q-2 replaced. It now
parses string literals and excludes docstrings.

---

## 7. Files

**Added**

```text
scratch/test_track1_stage5q3_live_frame_splice_20260824.py       32 tests
scratch/track1_stage5q3_mutations_20260824.py                    10 mutations
scratch/track1_stage5q3_live_frame_splice_report_20260824.md     this report
scratch/track1_stage5q3_live_frame_splice_report_20260824.json   the same, machine-readable
```

**Changed**

```text
global_index/track1_live_source.py       + project_to_frozen_columns (the owner) and its two
                                           refusal codes; JoinedFrame carries dropped_columns
global_index/run_live_day_track1.py      + catches SpliceRefused as `live_frame_refused`
                                         + wires slot_telemetry (begin / mark / set_outcome)
scratch/test_track1_stage4c_live_source_20260823.py   the column test re-aimed, one added
scratch/test_track1_stage5z_freshness_root_20260823.py  the log guard made structural
```

`track1_live_frame.py` is **unchanged** — the guard stays strict on purpose.
`track1_shadow_acceptance.py` is **unchanged** — the classification already handled this.

---

## 8. Operator action

**No scheduler restart.** Each slot spawns a fresh `run_live_day_track1` that imports the
current modules from disk, so the fix is already live: the Stress slots from 11:00 ET onward
ran on it and are the first Track 1 slots ever to write timing rows.

**No backend restart is required.** The dashboard reader is unchanged by this stage. If a
refreshed UI is wanted for any earlier stage's panel, the command — verified against
`python monitor\ops.py restart --help`, which has no `--backend` flag — is:

```powershell
python monitor\ops.py restart --no-scheduler --track1-only-shadow
```

**What needs a decision, not a command:** blocker **B-5R-D**. One MNQ bar of stored history
disagrees with the live feed. Until that is resolved, every Stress slot refuses by name — and
the refusal is now recorded, timed and audited, which is the difference this stage makes.

---

## Follow-up (appended 2026-08-24, Stage 5Q-4)

Nothing above is rewritten.

**B-5R-D is confirmed and the parquet is the wrong side.** MNQ 2026-08-21 13:45 ET is the
FILE'S LAST BAR; the feed's low is 4.5 points LOWER, which is the only direction a partial
minute's low can be wrong in; `open` and `high` agreed exactly; twelve independent slot fetches
over an hour reported it identically. No broker query was needed - the evidence is the route's
own window-ledger rows.

**Two further blockers were found while measuring it.**

- **B-5R-F** - `update_ibkr_daily` appends `new_bars[... > last_existing]`, strictly newer, so
  the bar the fetch stopped on is never revisited. Every 13:45 leaves a partial boundary bar.
  B-5R-D is one instance, and repairing it is a day's relief rather than a fix.
- **B-5R-E** - the 13:45 pre-flight marks a day true before that day's SPY close exists, so the
  regime CSV is permanently one business day behind what the freshness gate requires. Measured:
  `regime_csv: stale`, `allow: False`. Because `shadow_live` binds that gate, **no candidate can
  be admitted at any instant**. This outranks B-5R-D: repairing the MNQ bar would let the Stress
  window join and every admission would still be refused.

A dry-run repair tool exists at `scratch/track1_stage5q4_repair_boundary_bar_20260824.py`. It
was NOT applied and no parquet was mutated.

Full detail: `scratch/track1_stage5q4_mnq_overlap_audit_20260824.md`.
