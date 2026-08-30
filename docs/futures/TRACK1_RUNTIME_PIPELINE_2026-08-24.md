# Track1 Runtime Pipeline — 2026-08-24

## Current Status

Track1-only shadow is running as the intended replacement route shape, but orders are still blocked.

Current operator mode:

```powershell
python monitor\ops.py restart --scheduler --track1-only-shadow
```

Expected status:

```text
track1_mode=track1-only-shadow
track1_safety_routes=['legacy', 'track1']
track1_blocking=['B1_broker_account_or_legacy_retirement']
orders_possible=False
```

This means Track1 strategy jobs are scheduled, legacy strategy jobs are not scheduled, and real orders are still impossible.

## Processes

### Ops

`monitor/ops.py` starts two long-running processes:

1. Scheduler:

```text
pythonw.exe -m global_index.run_scheduler --port 4002 --shadow-resume --track1-only-shadow
```

2. Dashboard/backend:

```text
python monitor/start_backend.py --ibkr-port 4002 --api-port 5002
```

Verified current dashboard state:

`ops.py status` reports the scheduler in `track1-only-shadow`, and after restarting the backend with the Track1 flag, `/api/v1/schedule-status` reports `state_slot_count=70`. That means the backend is now mirroring the Track1 strategy slot table rather than the legacy 45-slot table.

One expected one-day artifact remains: because the scheduler was restarted after the 01:10-02:55 ET NKD window had already closed on 2026-08-24, `/api/v1/schedule-status` may show today's NKD Track1 slots as `not_observed`/`late`. Treat the acceptance script as the source of truth for that condition: a window that closed before the Track1 scheduler existed is `NOT_ENOUGH_DATA_YET`, not a route failure.

## Scheduler Inventory

In `track1-only-shadow`, the scheduler has 100 jobs (95 until Stage 5Q added the five audit
jobs — see the Stage 5Q appendix at the end of this document):

| Group | Count | Purpose |
|---|---:|---|
| Track1 strategy slots | 70 | Four strategy sleeves |
| Track1 safety jobs | 11 | Protect `live_positions.track1.json` |
| Track1 audit jobs | 5 | Read the runtime evidence after each window closes, and record a verdict |
| Legacy drain safety jobs | 11 | Protect any still-open legacy book positions |
| Shared infrastructure | 3 | Shared update/preflight-type jobs |
| Legacy strategy jobs | 0 | Intentionally not scheduled |

Track1 strategy slots:

| Sleeve | Slots | Time |
|---|---:|---|
| Calm A | 1 | 10:00 ET |
| Stress-MNQ | 24 | 10:35–12:30 ET, 5-minute cadence |
| Normal-R4 | 23 | 14:05–15:55 ET, 5-minute cadence |
| NKD/MNKD | 22 | 01:10–02:55 ET, 5-minute cadence |

## What Each Slot Runs

Each Track1 strategy slot spawns `global_index.run_live_day_track1` in live-shadow mode:

```text
python -m global_index.run_live_day_track1
  --source live-shadow
  --sleeve <sleeve>
  --slot-id <TRACK1_...>
  --bar-provider ibkr
  --regime-csv spy_daily_live.csv
```

The slot reads live bars through the Track1 live source, runs the corresponding sleeve decision, records evidence, and exits.

It does not send orders:

- no `--allow-orders` on scheduler slot argv;
- `TRACK1_ORDERS_APPROVED` is stripped from child environment;
- no confirmation file exists;
- B1 remains open;
- order gate reports `orders_possible=False`.

## Does A Slot Rebuild The Whole Backtest?

No. The live-shadow scheduler path does not rebuild the full historical backtest in each slot.

There are two different paths:

| Path | Source | Purpose | Replay/backtest? |
|---|---|---|---|
| `--source replay` | historical measured windows | research/reproduction | yes |
| `--source live-shadow` | live IBKR bars + frozen local frames | production shadow observation | no full backtest replay |

The scheduler uses `--source live-shadow`, not `--source replay`.

In live-shadow, `run_live_day_track1.py` calls `observe_live_slot(...)`. That path:

1. builds or receives a bar provider;
2. fetches session bars for the sleeve/instruments;
3. joins live bars to the frozen frame through the live-frame guard;
4. asks `LiveTrack1Source.candidates(now)` for candidates visible at that slot;
5. runs freshness, caps, admission, same-symbol and switch rules;
6. writes ledger/timing/explanation evidence;
7. writes a Track1 checkpoint only if the sleeve window is complete.

It does not run the entire 2018–2026 backtest on every slot.

## Checkpoint Role

Checkpoint is used for route state continuity, not for replacing the live observation.

Main files:

```text
global_index/replay_checkpoint.track1.json
live_positions.track1.json
global_index/maxhold_state.track1.json
```

Cross-day sleeves:

- Normal-R4
- NKD/MNKD

These sleeves can carry open positions across sessions, so they need state/checkpoint continuity.

Same-day sleeves:

- Calm A
- Stress-MNQ

These are intraday sleeves and do not need historical checkpoint state in the same way. They still write runtime evidence.

Important: checkpoint is written only after a window completes. A partial window must not create a checkpoint, because that would claim the route observed a full window when it did not.

## Track1 Safety

Track1 safety jobs are separate from legacy safety.

Track1 safety watches:

```text
live_positions.track1.json
runner.track1.pid
global_index/maxhold_state.track1.json
STOP_TRADING.track1
clientId 90
```

Legacy drain safety watches:

```text
live_positions.json
```

Legacy drain safety remains scheduled only to protect any old legacy position until legacy is confirmed empty at broker level. It is not Track1's safety net.

## Runtime Evidence

Live-shadow evidence is non-reproducible and must not live in `scratch`.

Durable runtime root:

```text
global_index/track1_runtime/
```

Main subfolders:

```text
global_index/track1_runtime/window_coverage/
global_index/track1_runtime/slot_timing/
global_index/track1_runtime/shadow/explanations/
```

What they mean:

| Path | Meaning |
|---|---|
| `window_coverage/` | Which slots/windows actually ran, decided, refused, or closed |
| `slot_timing/` | Runtime and phase timing for p95/cadence gate |
| `shadow/explanations/` | Why a candidate was accepted/rejected or why no action happened |

A slot with no signal can still pass if it writes a named no-action/refusal record. Silent absence is the failure.

## Dashboard

Backend:

```text
http://127.0.0.1:5002
```

UI:

```text
http://127.0.0.1:5002/realtime
http://127.0.0.1:5002/paper
```

Important endpoints:

| Endpoint | Meaning |
|---|---|
| `/api/v1/schedule-status` | Scheduler health, expected slots, incidents, overdue |
| `/api/v1/track1-runtime` | Track1 runtime evidence and gate state |
| `/api/v1/runner-positions` | Legacy/drain book, not Track1 |
| `/api/v1/runner-state` | Legacy runner state |

Verified current dashboard wiring:

`/api/v1/track1-runtime` exists, is visible in the UI as "Track 1 Runtime", and reads Track1 runtime paths. Before the first Track1 slot writes evidence, it correctly shows `not yet observed`, `window coverage directory present, no day recorded yet`, `slot timing directory present, no day recorded yet`, `book absent`, and `checkpoint absent`.

`/api/v1/schedule-status` now mirrors Track1 in the backend when the backend is started with `--track1-only-shadow`.

## Daily Acceptance Gate

A Track1-only shadow day is accepted only if:

- Calm coverage complete: 1 slot;
- Stress coverage complete: 24 slots;
- Normal-R4 coverage complete: 23 slots;
- NKD/MNKD coverage complete: 22 slots;
- no silent slot;
- no order marks;
- B1 remains open and no confirmation file exists;
- every explanation carries freshness proof;
- route checkpoint exists and names Track1;
- p95 runtime < 300 seconds;
- target p95 < 240 seconds is a warning threshold;
- no sleep/stall inside the collection windows.

`global_index/track1_shadow_acceptance.py` is the acceptance checker for this evidence.

## Practical Operating Rule

For the current shadow period:

1. Do not restart scheduler unless intentionally changing code that requires it.
2. Do not create confirmation files.
3. Do not set `TRACK1_ORDERS_APPROVED`.
4. Do not use `--allow-orders`.
5. After each window, check runtime evidence under `global_index/track1_runtime/`.
6. Treat named refusal as valid evidence.
7. Treat silence as a failure.

## Wrap-Up At Session End

As of the end of this session:

- Scheduler process is running in `track1-only-shadow`.
- Backend is running and connected to the broker.
- `/api/v1/schedule-status` returns `state_slot_count=70`.
- `/api/v1/track1-runtime` is reachable and route-labeled `track1_candidate`.
- No Track1 order can be placed: B1 remains open, no confirmation file exists, and `TRACK1_ORDERS_APPROVED` is not set.
- Runtime evidence folders exist under `global_index/track1_runtime/`.
- No Track1 slot after the scheduler start has completed yet; current verdict remains `NOT_ENOUGH_DATA_YET`.
- Today's NKD false-late rows are expected because the scheduler started after the NKD window had already closed.

Next checks:

```powershell
python -m global_index.track1_shadow_audit --latest --all
```

Run this after the next Track1 window has had time to execute. Stage 5Q replaced the dated scratch script with this module: it is production code, it takes --date / --latest / --from+--to so it never needs editing to follow the calendar, and the same checks now also run as scheduled jobs after each window closes. See the Stage 5Q appendix below.

Open audit before paper/live:

Track1-only shadow covers scheduler wiring and live feed observation. Before enabling paper/live orders, run a separate production-behavior completeness audit covering non-scheduler execution behavior that can diverge from legacy, especially contract rollover, broker-flat/orphan STP checks, order placement/fill semantics, cancel-stop-before-close ordering, stop arming, max-hold, and account-level reconciles.

---

## Stage 5Q — The Audit Is A Job Now (2026-08-24)

Until this stage the runtime evidence above was written every day and read only when someone
remembered to run a dated script in `scratch`. That is the one place in this route where
absence was NOT a signal: an audit nobody ran left silence, and silence read as fine.

### The runner

```powershell
python -m global_index.track1_shadow_audit --latest --all
python -m global_index.track1_shadow_audit --date 2026-08-25 --sleeve roska4_calm
python -m global_index.track1_shadow_audit --from 2026-08-25 --to 2026-08-29 --all
```

`global_index/track1_shadow_audit.py`. Read-only over the evidence; it writes one place and
only one place:

```text
global_index/track1_runtime/audits/track1_audit_YYYYMMDD.jsonl
```

Beside the evidence, never inside it, and append-only. Every judgement comes from
`global_index/track1_shadow_acceptance.py` — the same gate the daily acceptance section above
describes. The audit owns no rule of its own.

### The scheduled jobs

Registered in `--track1-only-shadow` only. Times derived from the same window table the slots
come from, with a ten-minute buffer: the last slot of a window fires AT the close minute and
may run to the 300-second ceiling, so close + 5 minutes is the earliest the window is
guaranteed to have finished writing, and the other five are margin.

| Job | ET | Audits the window that closed at |
|---|---|---|
| `track1_audit_global_nkd` | 03:05 | 02:55 |
| `track1_audit_roska4_calm` | 10:10 | 10:00 |
| `track1_audit_roska4_stress` | 12:40 | 12:30 |
| `track1_audit_roska4_swing` | 16:05 | 15:55 |
| `track1_audit_daily` | 16:15 | all four, plus the committed daily gate |

They connect to nothing, import no broker module, and their argv carries no `--allow-orders`,
no `--bar-provider`, no `--port` and no `--window`. Exit code is `0` whatever the verdict — a
failing shadow window and a broken audit tool must not share one red light in the log.

### Scheduler inventory, updated

In `track1-only-shadow` the scheduler now has **100** jobs:

| Group | Count |
|---|---:|
| Track1 strategy slots | 70 |
| Track1 safety jobs | 11 |
| **Track1 audit jobs** | **5** |
| Legacy drain safety jobs | 11 |
| Shared infrastructure | 3 |
| Legacy strategy jobs | 0 |

The other two modes are unchanged at 60 and 129. The dashboard mirror reads the SAME audit
job table the scheduler registers from, so parity holds in all three modes.

### The four verdicts

| Verdict | Meaning |
|---|---|
| `PASS` | the window closed under scheduler uptime and left complete, id-checked, timed, explained evidence, with orders impossible and the checkpoint naming this route and this day |
| `NOT_ENOUGH_DATA_YET` | the window has not closed; or closed before the scheduler existed; or the scheduler joined it halfway; or it closed leaving no evidence at all AND the start instant could not be read |
| `WARN` | p95 at or over the 240 s target, under the 300 s ceiling |
| `FAIL` | a judgeable window with a gap — coverage, a missing slot id, no timing, p95 or any single slot at or over 300 s, missing explanations or freshness proofs, an order mark, an open gate, a confirmation file, a wrong-route or wrong-day checkpoint |

**Absence is never a default pass.** No timing FAILS. No ledger rows FAILS. No explanations
passes only when the ledger's own `explained` counter records that none were due, and that
reason is named in the record as `no_candidates_to_explain`.

### The pre-start rule, in the audit's own words

A window that closed before the scheduler existed is `NOT_ENOUGH_DATA_YET`, never a failure.
The 2026-08-24 NKD window is the measured case: 01:10-02:55 ET, against a scheduler that
started at 04:32 ET. The audit resolves the start instant three ways — the scheduler hands its
own to the child in argv, else the process table, else **unknown**, never "no scheduler" —
because `scheduler_processes()` returns an empty list on any hiccup and an empty list reading
as "nothing running" is how a pre-start window becomes a manufactured incident.

### Dashboard

`/api/v1/track1-runtime` carries an `audits` block and the Track 1 Runtime panel shows an
**Audit verdict** row. Three states, never two: no audit directory, no record for the day, or
the verdict itself. **An audit that has not run is not a pass**, and the page says so in words.

### Practical operating rule, extended

8. After each window, the audit job records a verdict. If the dashboard says `audit not run
   yet`, the window has not been judged — that is a gap in the record, not a passing day.
9. A `FAIL` from the audit is a statement about a JUDGEABLE window. `NOT_ENOUGH_DATA_YET` is
   a statement about how far the session has got, not about the route's health.

### What the audit does NOT decide

The committed daily acceptance gate is stricter than the audit's operational roll-up — it
requires explanation rows for the whole DAY, so a session in which every sleeve legitimately
found no candidate does not satisfy it. The audit prints both answers side by side and softens
neither. Which one governs the shadow-period decision is the project owner's call.

One related thing to watch on the first judgeable day: `window_closed` counts only slots that
**decided**, and a named refusal — gate, freshness, live-source-not-ready — does not count. A
window whose slots all ran and all refused therefore reads incomplete, and the audit will FAIL
it on coverage. That is the committed rule, unchanged; it is also the most likely way a first
live day produces a FAIL that really means "the route refused by name all afternoon".

---

## Stage 5Q-1 — Observed Is Not The Same As Decided (2026-08-24)

The window ledger counts a slot toward coverage only when it **decided**. That is the right
rule for the committed daily gate and the wrong one for an operational audit, because two of
the ways a slot ends with `decided=False` are the route behaving as designed.

### What a slot actually writes

Measured by running `observe_live_slot` against a temp tree, not read off a docstring:

| what happened | `decided` | `reason` | `detail` |
|---|---|---|---|
| no bar provider | False | `no_bar_provider` | prose |
| gate allowed, **zero candidates** | **True** | `decided` | `candidates=0` |
| gate refused, clock | False | `gate_refused` | `too_late` |
| gate refused, data | False | `gate_refused` | `stale` |
| live source not ready | False | `live_source_not_ready` | prose |

So **"no signal" was never the problem** — a slot that looked and found nothing already
counts. The refusal that was being miscounted is the CLOCK one.

That one matters. `track1_intraday` refuses a slot `too_early`/`too_late` when the instant is
outside the sleeve's own decision band, and for NKD that band is the **Tokyo session** while
the slot grid is fixed in ET. In summer `01:10-02:55 ET` is `14:10-15:55 JST` and every slot
is inside. After **2026-11-01** the same grid is `15:10-16:55 JST`, so twelve of twenty-two
slots fire after the band closes and are refused by design — legacy's inherited behaviour.
Under the old rule the NKD window could never be complete again.

### The classification

| class | the row | observed? |
|---|---|---|
| `observed_decision` | decided, candidates evaluated | yes |
| `observed_no_action` | decided, zero candidates | yes |
| `observed_window_shut` | `gate_refused`, **every** code a clock code | yes |
| `observed_hard_refusal` | anything else with `decided=False` | **no** |
| `unobserved` | no ledger row | **no** |

Fails closed. `too_late,stale` is HARD — a stale frame that also happened to be late is still
a stale frame. `freshness_refused` is HARD, because it fires only when a binding mode caught
the engine **admitting** a candidate while the daily inputs were refused.

### New checks

- a ledger row with **no timing record** → FAIL (it ran unmeasured);
- a timing record with **no ledger row** → FAIL (a crash, or a mutex skip);
- duplicate slot ids named, and never able to fill a gap;
- `all_slots_observed_window_shut` → WARN; `all_slots_observed_no_action` → PASS.

Whenever the audit's completeness and the ledger's disagree, the record carries
`coverage_incomplete` as an **informational** reason beside `ledger_outcome`. The window WAS
observed, and the committed daily gate will not count it — both facts, by name.

### The explanation path was wrong, and it was never right

Measured by driving the real writer into a temp tree:

```text
writer lands at   .../shadow/explanations/live_2026-08-25/explanations_20260825.jsonl
the gate read     .../shadow/explanations/explanations_20260825.jsonl
rows found: 0
```

`write_shadow` is the only caller of that path in the repo and it always nests under the
window name. On the first real shadow day the `explanations` and `freshness_proofs` checks
would both have failed a route that wrote its explanations correctly. Both the gate and the
dashboard now resolve through one function, `track1_shadow_acceptance.explanation_files`, and
a test drives the real writer and requires the reader to find what it wrote.

### A quiet day is not a failed day

The committed daily gate requires explanation rows for the whole DAY, so a session where every
sleeve legitimately found no candidate cannot satisfy it. The audit's roll-up is built from the
sleeve verdicts and is not forced down by it; the gate's verdict rides along by name
(`daily_acceptance_gate_refused`) so a green audit cannot be read as having satisfied it.

Per sleeve the requirement comes from the ledger's own counters:

```text
candidates seen, no row anywhere for the day   -> FAIL   explanations_missing
candidates seen, no row for THIS sleeve but
  rows from another sleeve exist                -> named  explanations_overwritten_by_a_later_sleeve
no candidate seen, no row                       -> PASS   no_candidates_to_explain
```

### Known writer defect — not fixed, named

Every live slot opens the day's explanation file with `mode="w"`, and all four sleeves share
**one file per session date**. Measured: after a second slot wrote, the file held that slot's
single row and nothing else. So only the last slot's rows survive and per-candidate
attribution cannot be verified by anything.

The obvious one-line fix does not work — truncating only on the first slot still lets Stress
at 10:35 erase Calm's 10:00 rows, because the window name is `live_<date>` for every sleeve.
The real choice is a per-sleeve window name or append-only for the live path, and it is an
evidence-layout decision for whoever owns the runner.

### Does the scheduler need restarting?

**No.** The five audit jobs were registered by the 06:23 local restart — the scheduler logged
`Jobs (100)` with all five audit ids. Stage 5Q-1 changed only modules the audit **child**
imports fresh on each spawn, plus the backend's reader. Restarting would buy nothing and would
cost today's judgement, because every window that already closed reads as pre-start on a new
process.

The **backend** does need a restart, and the flag is `--no-scheduler` (there is no
`--backend`):

```powershell
python monitor\ops.py restart --no-scheduler --track1-only-shadow
```

---

## Stage 5Q-2 — Explanation Evidence Is Durable Now (2026-08-24)

### The layout

Each live slot owns its own file:

```text
global_index/track1_runtime/shadow/explanations/
    live_<YYYY-MM-DD>/<sleeve>/<slot_id>/explanations_<YYYYMMDD>.jsonl
```

It was one file per session date shared by all four sleeves, opened `mode="w"` by every slot,
so Calm's 10:00 rows were erased by Stress at 10:35 — measured by running the writer twice.

**Truncation was never the bug and it is still there.** It is what stops a re-run of one slot
doubling its own rows. What changed is the SCOPE: a slot may replace its own evidence and can
no longer touch anyone else's.

Re-run semantics, stated: **a re-run of one slot replaces that slot's rows and nothing else.**
A day holds at most one record set per slot, so a count is a count.

The layout has one owner — `track1_explain.live_window()` builds it,
`track1_explain.explanation_files()` finds it, the acceptance gate delegates, and the dashboard
delegates to the gate. The reader is recursive and still finds rows written in the older flat
and `live_<date>/` shapes.

**The replay path is unchanged** — `scratch/track1_shadow/explanations/<window>/`. A replay
writes one window from one process, which is the case truncation was designed for.

### The freshness proof is structural

It was `"freshness" in json.dumps(row).lower()` — a substring over free text, so a sentence
passed. The rule now lives in the module that BUILDS the records:

| the row | what it owes |
|---|---|
| accepted, binding mode | cite `GATE.FRESHNESS` and carry a boolean `freshness_allow` feature that passed |
| accepted, replay | nothing — the gate reads today's inputs, not the ones that governed a months-old admission |
| rejected | the feature only if a cited rule declares it; a cap refusal never reached the gate |
| any DECISION row | `inputs_summary["freshness_allow"]` as a boolean — the run's verdict, typed |
| the NO_ACTION context row | a boolean `freshness_allow` feature |
| anything unrecognisable | fails closed |

*Correction to the 5Q-1 note below:* that note said the substring check was also too STRICT.
It is not — the probe behind that claim used an empty `inputs_summary` and the real writer
always fills it. The defect was one-directional: too loose only.

### The dashboard

`/api/v1/track1-runtime` reports rows and attribution per day, and the panel shows
`N day(s), latest <day>: N row(s) across N sleeve(s) / N slot(s)`. The reader does not import
the writer — it resolves paths through the acceptance module, and a source test holds that
boundary.

### What the first live day found

The pipeline worked end to end on 2026-08-24, by reporting a failure correctly:

```text
08:00:04 local  [TRACK1_CALM_1000] SpliceRefused: column_mismatch:
                frozen ['open','high','low','close','volume']
                != live [... ,'average','barcount']
08:10:01 local  [TRACK1_AUDIT_ROSKA4_CALM] completed OK
                -> FAIL: coverage_unobserved, missing_slot_ids, no_timing_records
```

**Two new blockers, both for the runner and neither fixed here:**

- **the live frame cannot be spliced** — the IBKR fetch returns two columns the frozen frames
  do not have, so every sleeve refuses on every slot. Until the live fetch is projected onto
  the frozen columns, no shadow day can be judged.
- **`SpliceRefused` crashes the slot** rather than being recorded. `observe_live_slot` catches
  four exception types and this is not one of them, so the slot writes no `slot_observed` row
  at all — the route's own rule is that the refusal is the record.

### Operator

**No action for this stage.** Each slot spawns a fresh child that imports the current modules,
so the writer change is live from the next slot without a scheduler restart. The backend would
need `python monitor\ops.py restart --no-scheduler --track1-only-shadow` to show the new
Explanations row, but that is cosmetic — the audit records are written and readable either way.

---

## Stage 5Q-3 — The Live Frame Joins Now, And A Refused Join Leaves A Record (2026-08-24)

### The schema projection, and who owns it

**`track1_live_source.live_frame`** — the only caller of `track1_live_frame.splice` in the
repo, asserted by a test that scans every production module.

```text
fetch -> on_frozen_clock -> project_to_frozen_columns -> bars_from_the_future
      -> overlap_disagreement -> guard.splice
```

Schema before prices: the overlap check compares values column by column and cannot compare a
column that is not there.

| the live half | what happens |
|---|---|
| carries extra provider columns (`average`, `barcount`, anything new) | **DROPPED**, and the names travel with the frame in `JoinedFrame.dropped_columns` |
| is missing a frozen column | **REFUSED** — `missing_required_columns`, naming the column. Never synthesised |
| has NaN in a frozen column | **REFUSED** — `nan_in_required_columns` |

**The guard stays strict.** `splice` still demands identical columns. Relaxing it would let a
future caller that forgot to project get a wider frame back, with provider fields riding into
every sleeve. With one caller, projecting in the caller costs nothing and keeps the guard able
to catch anyone who skips it.

Extras are dropped by a general rule, not an allowlist — an allowlist drifts the first time
the provider adds a field. What matters is that the drop is **visible**: a new name appearing
in `dropped_columns` is how anyone finds out the feed changed shape.

### A refused join is now a record

`observe_live_slot` catches `SpliceRefused` and writes:

```text
reason  = live_frame_refused
detail  = "<guard code>: <guard detail>"   e.g. "column_mismatch: frozen columns ..."
```

The stage is the reason, the check is the detail — the shape `gate_refused` already uses. The
window still CLOSES (so the audit stops saying `coverage_unobserved`) and no checkpoint is
written for an incomplete window. The audit needed no change: `live_frame_refused` already
classifies as `observed_hard_refusal`.

### Track 1 slots emit telemetry — for the first time

`run_live_day_track1.py` had never imported `slot_telemetry`. `slot_timing/` was created, the
scheduler exported the variable, and no Track 1 strategy slot had ever written a row — so the
acceptance gate's `no_timing_records` was unsatisfiable and the p95 cadence check could never
run on anything.

Measured live from the running scheduler, the first rows ever written:

```text
TRACK1_STRESS_1100  ok  2.641s  reason=overlap_disagreement
TRACK1_STRESS_1105  ok  2.671s
TRACK1_STRESS_1110  ok  2.766s
TRACK1_STRESS_1115  ok  2.734s
```

**p95 = 2.7 s** against a 240 s target and a 300 s ceiling. `ok` means the slot RAN, not that
it decided: a named refusal is a successful observation and its runtime belongs in the cadence
numbers.

### Today's Calm slot stays failed

`TRACK1_CALM_1000` ran at 10:00 ET on the old code, crashed in the splice and left only a
`window_open` line. Its `FAIL` audit record stands and nothing was rewritten — back-filling it
would manufacture evidence for a window nobody observed. Only slots spawning after the change
pick it up, which is visible: the 11:00 ET Stress slots are the first with timing rows.

### Correction: B-5R-A was one of two live-frame blockers

The Stage 5Q-2 note called the column mismatch the single thing standing between this route
and a judgeable day. Measured today, it is not:

```text
overlap_disagreement — MNQ: the live half and history disagree on 1 of 1186 shared
timestamps in 'low'; first at 2026-08-21 13:45:00-04:00, history says 29400.2500 and the
feed says 29395.7500, largest gap 4.5000
```

That check runs **before** the splice, so every Stress slot refuses there and never reaches
the column check — before or after the fix. Fixing the schema was necessary and is not
sufficient.

**B-5R-D (new, open):** one MNQ history bar disagrees with the live feed by 4.5 points. It
refuses every Stress slot, and MNQ is in the swing basket too. It is a data question — which
reading is right, and which to change — not a code one.

### Operator

**No restart of anything.** Slots import their modules fresh on each spawn, so the fix is
already live. The dashboard reader is unchanged by this stage, so no backend restart either.

---

## Stage 5Q-4 — The MNQ Bar, And The Day The Data Cannot Cover (2026-08-24)

### The MNQ mismatch is confirmed, and the parquet is the wrong side

| | |
|---|---|
| bar | 2026-08-21 13:45:00-04:00 — **the file's LAST bar** |
| stored | `low 29400.25` |
| feed | `low 29395.75` |
| gap | 4.50 points, `low` only, **1 of 1186** shared timestamps |
| agreement | 12 independent slot fetches over an hour, all identical |

Two things point the same way. **Direction:** the feed's low is LOWER, and a bar captured while
its minute is still running can only have a low that is too HIGH. **Position:** it is the bar
the append stopped on. `open` and `high` agreed exactly.

No broker query was made — the evidence is the route's own window-ledger rows.

### The mechanism, and why it will happen again

`update_ibkr_daily.py:548`

```python
new_only = new_bars_adj[new_bars_adj.index > last_existing]
```

**Strictly newer.** The bar that was last in the file is never re-fetched, never compared,
never rewritten. So a partial boundary bar is permanent, and tomorrow's 13:45 leaves another
one at whatever minute it stops on. Named **B-5R-F**.

### Scope

| instrument | today |
|---|---|
| MNQ | **disagrees** |
| MES | **agrees** — the 10:00 Calm slot reached the splice, and the overlap check runs before it |
| MYM, M2K | not exercised yet — the 14:05 Normal-R4 slots are the first to touch them |
| MNKD | not exercised yet — the 01:10 NKD slots |

**Historical frequency is unmeasured.** A volume-based probe was tried twice and does not work:
13:45 volumes span 5–20× naturally, the bar we know is wrong is not flagged, and one that is
flagged is not known to be wrong. Reported as a failed instrument rather than a finding.

### B-5R-E — the freshness gate can never pass

```text
preflight_state.json   2026-08-21 : true
spy_daily_live.csv     last date 2026-08-20
required_data_through  2026-08-21
regime_csv             stale
allow                  False
```

`update_spy_csv` runs at 13:45 ET and fetches through "today" — but the day's daily bar does
not close until 16:00. So the CSV gains day **D−1** at day **D**'s pre-flight, while
`required_data_through` returns **D** from 13:45 onward. The two are one business day apart and
stay one business day apart. The 13:45 pre-flight is the only refresh in the schedule.

`shadow_live` is a freshness-BINDING mode, so **no Track 1 candidate can be admitted at any
instant** until this is settled. Slots still observe and still refuse by name.

**This outranks the MNQ bar.** Repairing that bar would let the Stress window join — and every
admission would still be refused.

### The repair: tooled, not applied

`scratch/track1_stage5q4_repair_boundary_bar_20260824.py`, dry run by default. `--apply` needs
`--expect <sha256>`, snapshots first, bounds the window and the bar count, refuses on anything
outside them, and verifies by re-reading.

Not applied, for three measured reasons: only `low` has been compared (the guard stops at the
first differing column); applying needs a broker fetch that would open a second client beside
the Stress slots on client id 89; and it fixes one day while B-5R-F keeps writing new boundary
bars.

**The overlap guard was not touched.** Widening it to swallow 4.5 points would make the route
join a frame it knows is wrong, silently, for ever — deleting the only thing that noticed.

### Operator

Nothing to run. Nothing to restart — no production module changed in this stage. Two
measurements arrive by themselves: **14:05 ET** (MYM, M2K) and **01:10 ET tomorrow** (MNKD). If
either reports `overlap_disagreement`, the mechanism is confirmed on more instruments; if they
join cleanly, MNQ is today's only bad file.

---

## Stage 5Q-5 — The Freshness Contract, And The Boundary Bar (2026-08-24)

### One requirement was being asked of two data sources

`update_spy_csv` runs inside the 13:45 pre-flight and fetches through "today". SPY's daily bar
does not close until 16:00, so it can never bring today's close — and the route does not need
it: a session on day D trades the label of D−1, because `RegimeLabels.get` returns
`reg.asof(day - 1)`. The intraday parquets are a different question: today's minute bars DO
exist at 13:45.

So the requirement is now split:

```text
required_intraday_through(now)      the parquets   — prev trading day, today from 13:45
required_daily_close_through(now)   the daily CSV  — the last TRADING day before today
required_data_through(now)          kept as a name, delegates to the intraday one
```

Holiday-aware, via `raits.live.trading_calendar`, and the calendar in use is reported. A
weekday-only rule names the holiday itself on the day after one — a close no refresh can ever
supply, so the gate would refuse for ever on a route that was fine.

**What it recovers, measured:** the gate used to refuse from 13:45 to midnight on every
trading day, asking the daily series for a close two hours away. It now allows there. About
ten hours a day that were being refused for a reason that was not true.

**What it does not fix:** Monday morning still needs Friday's close and the file holds
Thursday's. That is a missing refresh, not a threshold.

### A contradiction that had no name

`preflight_state.json` says a day's 13:45 job succeeded. It does not say which dates landed —
and on 2026-08-21 it said `true` while the CSV ended 2026-08-20. The new
`preflight_consistency` check names exactly that, and stays silent when the pre-flight itself
failed, because a retry and a contract question are different problems.

### A new job: `spy_refresh_pm`, 16:20 ET

SPY only. No IBKR re-fetch, no `preflight_state` write, and a failure is not a pre-flight
failure. 16:20 rather than 16:00 because Polygon's daily aggregate settles a few minutes after
the close.

Inventory **60→61 / 129→130 / 100→101**, parity holds in all three modes, classified
`shared_infra` so a legacy retirement cannot take the refresher with it.

**Not live until the scheduler restarts.** Job definitions are fixed when the schedule is built.

### The boundary bar: a rule with no threshold to tune

A partial bar can only be **completed**, never contradicted — `open` cannot change, `low` can
only fall, `high` can only rise, `volume` can only grow. So `boundary_replacement()` decides
from the two rows alone, and refuses by name otherwise: `open_changed`, `low_rose`,
`high_fell`, `volume_shrank`, plus a 0.5% net for a bar from a different contract.

The strictly-newer filter is **untouched** — the boundary bar is the one exception. The
replacement is concatenated between history and the new bars so the existing
`~duplicated(keep="last")` prefers it. The history invariant still requires every other bar in
the 200-bar tail unchanged, with the boundary timestamp excluded by name. A replacement
snapshots first and verifies by re-reading.

**OFF by default** (`--repair-boundary`, absent from the scheduler's argv). It is the only path
in that file that rewrites a bar the parquet already has, and the job runs unattended.
**Today's 13:45 run is byte-identical to yesterday's.**

### What is live, and what is not

| | live now |
|---|---|
| the corrected requirement | **yes** — every slot imports it fresh |
| the 16:20 SPY refresh | no — scheduler restart |
| `--repair-boundary` | no — scheduler edit + restart |
| the `SPY_REFRESH_PM` mirror row | no — backend restart |

While neither is restarted, scheduler and mirror agree — because neither has it.

### Operator

Nothing required today. In order, when wanted:

```powershell
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ   # measure, writes nothing
python -m global_index.update_ibkr_daily --repair-boundary --symbols MNQ    # repair, after reading step 1
python monitor\ops.py restart --scheduler --track1-only-shadow              # the 16:20 job
python monitor\ops.py restart --no-scheduler --track1-only-shadow           # the mirror row
```

The scheduler restart costs the current day's judgement, so prefer before 10:00 ET or after
16:00 ET.

---

## Stage 5Q-6 — What The Live Day Said Back (2026-08-24, evening)

Stage 5Q-5 fixed two things in code and predicted what they would do. This stage ran the day
and read the answer. One prediction held, one was better than expected, and one was worse.

### The audit pipeline earned its keep

Eight audit records, on a real trading day, with **no false PASS**:

```text
global_nkd     NOT_ENOUGH_DATA_YET   window_closed_before_scheduler_start
roska4_calm    FAIL                  coverage_unobserved, missing_slot_ids, no_timing_records
roska4_stress  FAIL   p95 3.1s       slot_could_not_evaluate (gate_refused:stale, overlap_disagreement)
roska4_swing   FAIL   p95 2.4s       slot_could_not_evaluate (overlap_disagreement)
DAY            FAIL
```

NKD is **pending, not failed** — its window closed before the scheduler existed, which was the
exact false-incident this design was built to refuse. Five Stress slots carry
`slot_without_timing` because they ran between 10:35 and 10:55, before the telemetry wiring
landed mid-morning: a code change during a session, reported rather than hidden.

And the acceptance gate has real numbers for the first time: **p50 2.41s, p95 2.78s, max
3.27s**, against a 240s target and a 300s limit. Every one of 42 timing rows is `outcome=ok`.
The p95 question is settled by two orders of magnitude.

### Better than expected: the freshness requirement is not just live, it passes

```text
csv last date              2026-08-21
required daily close       2026-08-21
required intraday          2026-08-24
allow                      TRUE
preflight_consistency      ok
```

The 13:45 pre-flight brought the CSV to Friday, and the corrected requirement asks for Friday.
The old rule would still be refusing right now, asking the daily series for a close that does
not exist.

It goes stale again tomorrow at 09:00, which is exactly what `spy_refresh_pm` at 16:20 exists
to prevent — and precisely why the restart matters more than it looked yesterday.

### Worse than expected: the boundary bar is a daily event, on most instruments

One read-only fetch, every window closed:

```text
MNQ    13:45   high +2.0  close +2.0  volume 738 -> 1801     open, low IDENTICAL
MYM    13:45   volume 137 -> 182
M2K    13:46   high +0.1  volume 2 -> 15
MES    13:44   clean
```

**One pre-flight corrupted three of five instruments.** MNQ's stored bar holds 41% of the
minute's real volume. Every one matches the completion signature exactly — `open` and `low`
untouched, `high` risen, `volume` grown — which is what makes them safe to repair and what
makes them unmistakably partial.

Friday's MNQ bar, the one that refused 23 Stress slots this morning, has **fallen out of the
fetch overlap**. It is still wrong in history; no tool can now reach back to measure it. That
is its own small lesson: an evidence window that closes turns a repairable defect into a
permanent one, and there was no alarm counting down.

On that evidence `--repair-boundary` went into the 13:45 pre-flight permanently. Not on
principle — on a count.

### A new blocker with no command attached

```text
MNKD   1052 bars disagree, the first at 2026-08-24 07:01 JST
```

The repair tool refused it rather than calling it a boundary bar, which is what the window
bound is for. **The cause is unmeasured.** A contract roll, a back-adjustment difference and a
clock question are all consistent with what has been measured, and choosing between them by
plausibility is the move this whole sequence of stages exists to avoid. It gets its own audit,
the way MNQ got one in 5Q-4.

### The near miss: a fixture that did not match the file it stood in for

Before applying any repair I checked what the write would actually produce:

```text
raw parquet index    tz-NAIVE, UTC wall clock     2026-08-24 17:45:00
frozen_frame index   tz-AWARE America/New_York    2026-08-24 13:45:00-04:00
```

The Stage 5Q-4 tool's `--apply` wrote `frozen_frame`'s output straight back. One bar repaired,
and **the storage convention of an eight-year, 3.3-million-row file rewritten** underneath
`load_parquet`, `assert_utc_convention` and every backtest that reads it.

Its 26 tests were all green. The fixture wrote a tz-**aware** UTC parquet, so the round trip
preserved awareness in the test and would not have on disk. The test agreed with itself.

The production appender never had this problem, because it concatenates onto the raw frame and
runs `assert_utc_convention` before writing — which is the argument for repairing through the
job that owns the file rather than through a tool that visits it.

### What is live tonight, and what is not

| | live |
|---|---|
| the corrected freshness requirement | **yes** — and passing |
| the audit jobs and their verdicts | **yes** — eight records today |
| slot telemetry and the p95 gate | **yes** — from 10:55 onward |
| the 16:20 SPY refresh | no — scheduler restart |
| `--repair-boundary` in the pre-flight | no — same restart |
| today's three partial bars, repaired | no — one operator command, guarded |

The running scheduler still reports **100 jobs**. The dashboard mirror also lacks the row, so
the two agree — they will agree again at 101 after both restarts, and disagreeing in between
is the thing to watch for.

### Verdict: NOT_READY for 5R

Not because anything regressed. Because three fixes are written and not yet running, and one
instrument has a data disagreement nobody has measured yet. Every blocker except that last one
has a command; the last one has a question.

`B1` remains the order gate, `orders_possible=False`, and nothing in this stage touched it.

---

## Stage 5Q-7 — The Third Name (2026-08-24, late evening)

Stage 5Q-6 ended with one blocker that had no command attached: MNKD, 1,052 minute bars
disagreeing with the feed, cause unknown. It has a name now, and the name was hiding in plain
sight in a comment written three weeks earlier.

### An instrument has three names, and only two had been separated

```text
runner name      MNKD    what this system calls it internally
history symbol   NKD     what the parquet was fetched under
order symbol     MNK     what goes on an IBKR order
```

The second and third were pulled apart in August 2026, after live orders for the $0.50 micro
were routed to the $5 full-size contract and ran at ten times the intended size for four days —
−$1,400 at the broker against −$140 in the sleeve ledger, exactly 10.0000×. The fix made the
order ticker a required field so no layer would ever have to infer it again.

But `IBKRBroker.fetch_bars` resolves whatever it is handed through that same **order** map. So
the live route asked for MNK, the parquet held NKD, and the overlap guard did precisely what it
was built to do: refuse, loudly, every time.

### Two arms, one variable

```text
fetch as MNK   1155 of 1186 shared minutes disagree   worst 375.0   median-where-bad 25.0
fetch as NKD      0 of 1186                            worst   0.0000
```

The clock explanation was tested rather than waved away, because it fitted suspiciously well:
the guard's own docstring records an earlier Nikkei incident of **1,050** bars from a
thirteen-hour error, and 5Q-6 had counted **1,052**. It is ruled out by magnitude, not by
count — the *signed* close difference has median **zero**, and the typical gap is 25 points,
one tick on a five-point grid. A clock error is a large offset in one direction. This was two
order books quoting one index, differing symmetrically, exactly as a thin micro and a liquid
full-size contract should.

The count moved to 1,155 in the re-measurement because the parquet and the fetch window both
moved. The count was never the discriminating number.

### The obvious fix would have broken four instruments to repair one

`Contract.data_symbol` looks like the field for this. It is not:

```text
inst   data_symbol   actually fetched as
MES    ES            MES
MNQ    NQ            MNQ
MYM    YM            MYM
M2K    RTY           M2K
MNKD   NKD           NKD
```

`data_symbol` is the **file stem**. Using it would have sent all four basket instruments at the
full-size E-minis — the original incident again, in reverse and four times over.

The only honest answer to "what was this history fetched as" is the code that fetched it. So
the new function is **derived from the job table that built the files**, and the live source
delegates to it instead of keeping a table of its own. Two tables is how MNKD reached the
full-size contract to begin with.

`point_value` was not touched, and a failing test now pins that: MNKD stays $0.50, NKD stays
$5.00. A multiplier moves sizing, risk and realised P&L. It has never been able to move the
price of a bar.

Sixteen tests, and eight of eight mutations turned the right one red — including the one that
matters most, a mutation that makes the two identities equal again.

### It is live tonight without a restart

The scheduler spawns each Track 1 slot as a fresh subprocess, so the corrected source is what
tomorrow's — and tonight's — slots import. `live_frame("MNKD")` now returns `ok` over 1,186
checked minutes. That is the first MNKD live frame ever built in this sequence, and it means
the NKD window at 01:10 should be judgeable for the first time.

### The repair worked, and taught something the earlier stages had wrong

The approved appender repaired all three partial boundary bars, snapshotting each and verifying
by re-reading. The line worth keeping is the alignment check: **median +0.0000, IQR 0.0000 over
2,566 shared bars.** Outside the single boundary minute, the feed and the file agree exactly.

Then the same run left a fresh partial bar at 20:20, and the guard refused on it.

That is not a mistake in the repair; it is the shape of the defect finally coming into focus.
`update_ibkr_daily` appends strictly-newer bars, and while the market trades the fetch always
ends inside an open minute. **Every run stores one partial bar.** `--repair-boundary` fixes the
*previous* one at the *next* run — so a bad bar poisons the two-day overlap for about one day
instead of two, and never for zero.

Today's own evidence shows both halves: the morning slots refused on Friday 13:45, and the
swing slots — which ran *after* the 13:45 pre-flight — refused on Friday 13:46, an interior bar
nothing had repaired.

The cure is one step earlier: do not store the in-progress minute. That is a behaviour change
to the shared 13:45 job that also writes legacy's data, so it is recorded here with its
measurement rather than slipped in at the end of an evening. Expect, tomorrow morning, exactly
one refusing bar per basket instrument — predicted, not new.

### What the restart was blocked from delivering

`spy_refresh_pm` and `--repair-boundary` are still source-only; the running scheduler still
reports 100 jobs and the dashboard mirror still lacks the row, so the two agree. They should
agree again at 101 after both restarts, and disagreeing in between is the thing to watch.

### Three tests were repaired, none of them a regression

One asserted that no boundary snapshot may exist beside a real parquet — but an approved repair
had legitimately made three, and a guard reading "none may exist" cannot tell that from "this
suite made one". It is now anchored to what was there at import: the suite must add none.

Three more read a coverage file named for the session day while the ledger had written one named
for the UTC day, because the clock had crossed midnight in London. That is worth keeping as a
finding in its own right: **the ledger names files by UTC date and the audit reads by session
date.** They agree except between 20:00 ET and midnight ET, where no Track 1 window currently
runs — but a window that ever moved there would write its rows into a file the audit does not
open.

And one pinned the default schedule at sixty jobs, which Stage 5Q-5 had deliberately made
sixty-one.

### Where this leaves 5R

Closed: the MNKD symbol, and the three boundary bars. Open: the restart, the in-progress-minute
defect it exposed, the same symbol bug still sitting in the legacy route, NKD's winter window,
and B1 — which has blocked orders throughout, as designed.

---

## Stage 5Q-8 — Is It The Same Strategy? (2026-08-24, night)

Everything up to here has been about whether the route *runs*. This stage asked the only
question that matters before money moves: **is the thing it runs the thing the numbers
describe?**

Three identities have to agree. The data the signal is computed on. The rule the signal
applies. And the identity the route *declares* — because that third one is what a checkpoint is
accepted or refused on, and what an operator reads in an explanation record.

The first two are clean. The third is not.

### The signal path is the backtest, exactly

All three committed windows end on or before 2026-08-19, so last night's boundary repair could
not reach them — confirmed by re-running the whole reproduction afterwards rather than assuming
it:

```text
Normal-R4 (incl. MNKD)   980 + 136 + 107 = 1,223 of 1,223 rows      0 mismatches
Calm A                   349 +  44 +  28 =   421 of   421 rows      0 mismatches
Stress-MNQ                50 +   3 +   4 rows, P&L to the cent      0 mismatches
```

Every rule parameter was read off the module that runs and checked against the sleeve's own
spec: EMA 50 and the entry-anchored 2.0×ATR stop for Normal-R4; the bottom-third close, the
down close, the −1.0% gap floor and the 1.5×ATR15 disaster stop for Calm A; breadth 4, gap-down
3, `pre_high × 1.001` and the 1.5R target for Stress. No regime label anywhere in Stress, which
is correct — it never had one.

And the two intentional differences are both explicit, both measured, and both in the identity
hash: MNKD reads NKD bars while its orders route to MNK, and the live route uses the production
fill law where the artifacts used the artifact law — **+$8.78 across three windows on $49,389**,
moving in the safe direction.

### The declaration is wrong for one sleeve

`sleeve_config` is written by hand *beside* the modules that run, not derived from them. For
`global_nkd` it says:

```text
declared   chandelier_atr · 2.5 · extreme_through_prior_bar · ratchet ON  · arm 14:00 Tokyo
executed   entry ± 2.0 × daily ATR      · anchored at entry · ratchet OFF · arm 14:05
```

Five fields, and the code is the one that is right: the committed artifact reproduces exactly
under the executed rule. The declaration describes **legacy** NKD, adopted verbatim in a comment
that says so — "its settings are legacy's on purpose" — while the sleeve was actually promoted
as Normal-R4 at EMA 10.

So the hash that decides whether a `global_nkd` checkpoint is trustworthy is computed over a
rule nothing runs. And a live MNKD decision would be explained to the operator as
`chandelier_atr` while the stop on the book is `entry ± 2.0 × ATR`.

### A wrong turn, recorded because it nearly became the finding

Reading `generate_replay_snapshots.py` — which calls `backtest_swing_tf(ema_period=10,
chandelier_atr_mult=2.5)` — I first concluded the opposite: that the *live path* was the defect.
Running both engines over the same window seemed to confirm it, 62 trades against 26 and a P&L
sign flip.

Then the self-check: the arm that was supposed to reproduce the committed rows reproduced **none
of them**. Zero of twenty-six. The instrument had failed, so the comparison meant nothing and
was thrown away rather than reported. Two things were wrong with it — the frame was sliced with
no EMA warm-up, and `generate_replay_snapshots.py` turns out to be a legacy producer the Track 1
route does not consume at all. The real Track 1 NKD artifact sits inside the Normal-R4 promotion
file, alongside the four basket instruments.

A measurement that cannot reproduce a number you already know is not evidence about anything
else.

### The sizing basis, which nobody had compared

The live route sizes every candidate on the true stop distance — `|entry − stop| × pv × qty`.
Two of the four artifacts agree with that exactly: Calm A on 28 of 28 rows, Stress on 4 of 4.

The other two carry no stop price at all. Their risk is `2.5 × daily ATR × pv × qty`, while the
stop those sleeves actually place is `2.0 × daily ATR`. The ratio is not a distribution:

```text
roska4_swing   938 of 938 rows      every single ratio exactly 1.25
global_nkd     285 of 285 rows      every single ratio exactly 1.25
```

The live route therefore reports **80% of the risk the artifact recorded for the same trade**.
The caps are unchanged and are in the identity hash — but the quantity they gate is now computed
on a different basis, so the same cap admits roughly a quarter more than the measured book did.

Which basis is *better* is a fair question, and the true stop distance probably wins it. That is
not the point. The point is that nobody has measured what the change does to admissions, and a
book whose admissions were never measured is not the book the numbers came from.

### And the hash cannot see the thing that cost real money

`route_params.ALL_FIELDS` names the data file, the fill law, the caps, the filters, the regime.
It names nothing about what an order is routed to, what a contract is worth, or how size is
derived. The August incident — MNKD sent to the full-size contract at ten times the intended
size, −$1,400 at the broker against −$140 in the ledger — **would not have moved a single
params hash**, and a checkpoint written before it would have been accepted after it.

Closing that invalidates every stored hash, which is a decision rather than a tidy-up. It is
recorded and pinned by a test so it stays visible.

### Where this leaves paper trading

Nothing here blocks the shadow session; B1 blocks orders regardless, and the signal path is
proven identical. All three findings block *paper orders*, because each one sits between a
correct signal and the size that would be sent: fix the NKD declaration, measure what the sizing
basis does to admissions, and decide whether the tradable identity belongs in the hash.

The strategy is right. What is not yet right is everything the strategy is described by.

---

## Stage 5Q-9 — Closing The Gap Between A Correct Signal And The Size That Gets Sent (2026-08-24, night)

Stage 5Q-8 ended with an uncomfortable result: the strategy was right and everything describing
it was not. Three findings, none of them in the signal path, all of them between the signal and
the book. This stage closed all three, and two of them turned out to be worth more than they
looked.

### The declaration that described a different sleeve

`global_nkd` declared a chandelier stop at 2.5× ratcheting from the prior bar's extreme, armed
at 14:00 Tokyo. It runs an entry-anchored band at 2.0× daily ATR with the ratchet off, armed at
14:05. Five fields, and the code was the one telling the truth — the committed artifact
reproduces exactly under the rule the code runs.

Correcting it moved the sleeve's hash. **No stored checkpoint was invalidated**, which was
checked rather than hoped: `replay_checkpoint.track1.json` does not exist and the legacy file
holds no hashes at all. This was the cheapest possible moment.

The comment block above it had also drifted — four `SOURCES` entries still said "MNKD keeps
2.5" and "unchanged at 14:00 JST", in the one file whose entire job is to say where every value
came from. A description leaves the thing it describes; that is why this repo prefers derived
values, and where it cannot derive, a test.

### The sizing basis, which nobody had ever compared

Two of the four sleeves carry a real stop price in their artifacts and their risk *is* the stop
distance. The other two carry no stop at all: they were admitted on `2.5 × daily ATR` while the
stop they actually place is `2.0 × daily ATR`. Exactly 1.25×, on every row.

Replaying the committed candidate stream through the real book on both bases:

```text
window      taken            booked P&L              changed admissions
floor       1160 -> 1234     $64,903 -> $71,982      129
vault2025    128 ->  144     $13,236 -> $16,585       20
vault2026     91 ->   98      $8,260 ->  $5,872       17
```

**166 admissions move, and they move in both directions** — 128 rejections become takes, but 33
takes become rejections, because the candidate queue is sorted by risk and shrinking two sleeves
reorders it. Three of the moved rows are Calm A, whose own risk never changed at all. And
vault2026 takes seven more trades for $2,388 *less*.

That settles it: this is a re-rate, not a refinement. The route keeps the basis its published
Calmar, MaxDD and net were measured under, and the live path — which had been sizing on the
honest stop distance — was moved onto it. The consequence is that live candidates now report
risk 25% larger than they did this morning, so the route will admit *fewer* positions. The
conservative direction, and the one that matches the book the numbers describe.

Switching to the true stop distance stays available. It is arguably the better number. It just
costs a re-rate, and `sizing_basis` is now in the identity hash so it cannot happen by accident.

### Three instruments before the cap numbers could be trusted

The first cap-usage harness reported peak `roska4_swing` gross of **0.0903 against a 0.050
cap**. A usage figure above the cap the guard enforces is impossible by construction, and that
impossibility is the whole reason it was caught — the guard tests `max(long, short)`, not the
sum of both sides.

Then two windows showed a *net* peak above cap on both bases, and two further instrumentations
disagreed about why. The second one was wrong in a way worth writing down: it sampled inside
`_book`, which books the P&L, while the position is removed from the book by `settle_due`
afterwards — so a detector looking for the moment a settlement changes the net could never see
one.

The answer, once the instrument was right: **zero** admissions and **zero** forced closes ever
leave the net above cap. The peak is reached after a scheduled close, when one side of the book
disappears and the remaining imbalance rises. The cap gates new risk; it is not an invariant of
the book afterwards, and nothing can un-take a position because another one closed.

Three attempts to measure one number, and the only reason the wrong ones did not ship is that
each disagreed with something already known.

### The hash could not see what cost real money

`route_params` named the data file, the fill law, the caps, the filters and the regime. It
named nothing about what an order is routed to, what a contract is worth, or how size is
derived — so the August defect that sent MNKD orders to the full-size contract at ten times the
intended size, −$1,400 at the broker against −$140 in the ledger, **moved no hash at all**.

Four names were added, each owing a mutation test. And adding them exposed something older:
`sleeve_config(sleeve, inst, …)` has always taken an instrument and, until tonight, never used
it. The signature promised a per-instrument identity for two stages and delivered one only
through the data path. That is precisely the room the routing defect lived in.

A consequence worth stating: the four Rổ-4 instruments no longer share one identity. Pin the
contract as well and they collapse back to one — which is the separation the Stage 2 test was
written to prove, and it now asserts both halves instead of one.

### Where this leaves the route

Identity is confirmed. Reproduction is unchanged and still exact — 1,223 Normal-R4 rows, 421
Calm A, 50/3/4 Stress, re-run after every change here. What still blocks paper orders is all
operational and all from Stage 5Q-7: the in-progress minute the appender keeps storing, the two
job-table fixes waiting on a restart, the same symbol defect still sitting in the legacy route,
and NKD's winter window. B1 has blocked orders throughout.

The strategy was right the whole time. It is now also described correctly, sized the way it was
measured, and identified by something that would have caught the one defect that has actually
cost money.

---

## Stage 5R-0 — The Minute That Had Not Finished (2026-08-25, small hours)

Stage 5Q-5 built a repair for the partial boundary bar. Stage 5Q-7 ran it, and in the same
breath created three more. That was the moment the shape of B-5R-H became clear: the repair was
never the fix, because the thing being repaired is created fresh on every run.

The updater asks IBKR for bars "up to now". IBKR answers with the minute in progress. The
append stores that snapshot as though it were a finished bar, and it stays that way for ever —
the strictly-newer filter guarantees the same minute is never re-fetched.

So `--repair-boundary` repairs yesterday's, and leaves today's. Repairing moves the defect one
minute later. Only refusing to store it removes it.

### One rule, no threshold

A bar stamped T covers `[T, T+1min)`. It is complete exactly when the observation instant has
reached `T + 60s`. Nothing about prices is consulted, and that is the point: a partial bar is
not detectably wrong from its own values — its open is right, its low is merely not yet as low
as it will be — which is precisely why it survived every price check this route has.

Only the final bar is ever a candidate. An interior bar cannot be in progress, and a function
that could drop one would be a filter rather than a tail guard.

### Which instant counts

The stamp is taken **before** the request goes out, not after, and that is the whole design
rather than a detail.

The snapshot IBKR answers with is at or after the moment we asked. Stamp afterwards and a
minute that closed *during the round trip* looks complete — while the row we are holding for it
is still the partial one the snapshot contained. That is the same defect walking back in
through the front door, wearing a timestamp that says it is fine.

Stamping before means every bar kept had already closed before we asked, so the value we have
for it is final. The cost is at most one just-closed minute deferred to the next run, which
appends it as an ordinary new bar. A test parses the function's AST and requires the stamp to
precede the request, because a comment saying so would not survive the next refactor.

### The skip is reported, not silent

```text
MNQ: final-bar check — dropped: 2026-08-25 00:20:00 is still open at 00:20:31
IN-PROGRESS FINAL MINUTES NOT STORED (Stage 5R-0, intentional):
  MNQ   2026-08-25 00:20:00  — still open at fetch; it arrives on the next run
```

A quietly shorter file is how a missing bar becomes a mystery six weeks later.

### Two fixture bugs, both caught by production guards

Worth recording because in both cases the code was right and the test was cheap.

The fake `reqHistoricalData` returned a DataFrame. ib_insync returns a *list* of BarData, and
`_fetch_contfuture` does `if not bars:` — which raises "truth value is ambiguous" on a frame.
The first version of the test was exercising a path production never takes.

Then the synthetic bars ramped one point per minute from a base of 100 — a **0.365%** step at a
price of 205, which trips the real join-jump guard at 0.35% and refuses the append. The guard
was doing its job on data that could not exist. Synthetic data has to sit in the range the
production thresholds were measured for, or the test measures the fixture.

### Live tonight, without a restart — and what is still not

The pre-flight runs the updater as a fresh subprocess, so it imports the corrected source on
every invocation. From tomorrow's 13:45, no in-progress minute is stored. `--repair-boundary`
and `spy_refresh_pm` still wait on the restart, because their job argv was fixed when the
schedule was built.

And 5R-0 prevents new partial bars; it does not repair the three already sitting in MNQ, MYM and
M2K from last night's repair run. Tomorrow morning's Calm and Stress windows will still refuse
on exactly those — one bar per basket instrument, predicted rather than new. MES and NKD are
clean.

The end state this points at is worth naming: once the restart lands and those three are
cleared, `--repair-boundary` becomes a path that never has anything to repair, because nothing
partial is ever written. A repair mechanism whose success condition is that it does nothing.

---

## Stage 5R-1 — The First Clean Tail (2026-08-24, 23:25–23:45 ET)

Everything from Stage 5Q-5 onward has been about one bar: the minute the fetch stops inside.
Tonight was the first time the system was asked to handle it in production with the fix in
place, and the first time it left nothing behind.

### The repair, and the proof it was needed only once

```text
MNQ  final-bar check — dropped: 2026-08-25 03:26:00 is still open
     alignment over 2902 shared bars — median +0.0000, IQR 0.0000
     boundary bar 00:20 replaced and verified by re-read
MYM  same shape at 00:21 · M2K same shape at 00:21 · exit 0
```

Each fetch reached 03:26 UTC and each file stopped at **03:25** — the last closed minute.
Twelve hours earlier the identical command froze three fresh partial bars; tonight it froze
none. Then the probes:

```text
MNQ / MYM / M2K   nothing_to_repair   shared_disagreements_total: 0
```

Zero disagreements anywhere, on all three. That is the observation that closes B-5R-H on the
live files rather than only in the code, and it is the first time in this sequence a repair run
has ended without creating its own successor.

Exactly three files changed. MES, MNKD, the SPY series, the pre-flight state and the splice
sidecar are byte-identical. tz-naive, same five columns, snapshots only for what was touched.

### The log knew something I did not

The restart stopped pids 16752 and 35088 — not the 28696 and 11720 I had on record.
`ops.log` had the answer: **the operator restarted at 23:15 ET**, ten minutes before this stage
began, doing the thing that had been outstanding since 5Q-7. Mine at 23:29 replaced it.

No harm — both came up at 101 jobs and every window was shut in between. But the honest note is
that I restarted a live process without first confirming it was still the one I had recorded.
That check belongs before the command, not in the log afterwards.

### What is running now

101 jobs. Seventy Track 1 strategy slots, eleven Track 1 safety jobs, five audit jobs, eleven
legacy safety jobs draining the old book, four shared. **Zero legacy strategy jobs.**
`spy_refresh_pm` at 16:20. `--repair-boundary` in the 13:45 argv. Orders impossible, B1 open.

### A measurement of mine that was wrong for two stages

Twice I reported that the dashboard mirror was missing `SPY_REFRESH_PM`, tested by looking for
that string in the `/api/v1/schedule-status` payload. **That endpoint does not enumerate slots
at all** — its keys are `freshness`, `active_window`, `next_scheduled_job` and so on. The string
was absent because no slot list is returned, not because the row was missing.

Asked properly, the row is there and at the right time, and may have been since the code landed.
The restart was still needed — `spy_refresh_pm` genuinely was not *registered* in the running
scheduler — but the mirror half of that claim was a substring search over a payload that could
not have answered the question either way.

### The cost of restarting, visible and correctly labelled

Every window on 2026-08-24 now re-derives as `window_closed_before_scheduler_start`, and the
audit says so in words rather than turning it into a failure:

> Nothing here has both closed and been covered by scheduler uptime. That is a statement about
> how far the session has got, NOT about the route's health.

The eight records written during the day remain the truth for that day. This is the cost that
was named in 5Q-6 and accepted then, arriving exactly as described.

### Two red tests, both mine, neither production

`test_7b` pinned the full identity hash — which includes a sha256 of the parquet. Appending
bars moved it, correctly, and the test had a one-trading-day expiry built into it. That is the
same defect I had criticised in Stage 2's log anchor the day before, in a test I wrote the day
before that. It now pins the strategy half, with a companion test proving the data pin still
reaches the hash.

The dashboard test read the **real** scheduler's start time, because `get_schedule_status` uses
it to decide whether a slot is judgeable at all. Correct production behaviour — the same
pre-start rule the audit applies — but it made a file of lateness tests depend on when the
machine was last restarted. Confirmed by patching three start instants and watching the answer
flip. Pinned now.

### Next

`global_nkd`, 01:10–02:55 ET — 14:10 to 15:55 on the Tokyo clock, covered end to end by a
scheduler that has been up since 23:29. MNKD's bars come from NKD, its orders would go to MNK,
and B1 stops them going anywhere. It is the first Track 1 window in this sequence that should
be judgeable on its data rather than refused by it.

---

## Stage 5S — The Paper Readiness Gate (2026-08-25, small hours)

The order gate has been described in these reports for weeks as the thing standing between the
shadow route and a live order. This stage read it properly for the first time and found that it
was guarding the wrong question.

### Authorisation everywhere, evidence nowhere

Four conditions stood on the gate. B1 is a decision the operator records on disk.
`LIVE_FRAME_ADAPTER_VERIFICATION` measures the code's wiring. `TRACK1_ORDERS_APPROVED` is an
out-of-band approval, and `--allow-orders` is a request typed on a command line.

Every one of them is about **permission**. Not one asks whether the route has ever worked.

Meanwhile `track1_shadow_acceptance` computes exactly that, every day, and writes it to a
durable directory — and nothing that decides whether an order may be sent had ever read it. A
route with zero judgeable days and a route with a hundred were the same to the gate. Measured
rather than argued:

```text
confirmation file releasing B1 + zero judgeable shadow days
  may_enable_orders()  ->  True
```

That is the whole defect in one line, and it is now `False`.

### What the evidence gate asks

Five judgeable days, no FAIL among them, at most one WARN, every one of the four sleeves having
reached PASS at least once, and the newest of those days no more than three weeks old. p95
under the 300 s ceiling throughout; between the 240 s target and the ceiling costs the single
WARN allowance.

Those five numbers are judgement calls rather than derived quantities, and they sit in one
named block so they can be moved deliberately in one place rather than discovered scattered
through a checker.

What matters more than the numbers is what cannot satisfy them. A missing audit file is a day
nobody watched, not a day that went well. An unparsable line, a `NOT_ENOUGH_DATA_YET` verdict,
a record for another route — all count against. The qualifying days must be the most recent
ones, so a clean week in August cannot make December ready, and the gate closes again if the
evidence goes stale. And a check that cannot run at all fails **closed**: this is the one place
in the system where the `scheduler_processes()` mistake — returning an empty list for "I could
not tell" — would open a gate rather than shut one.

### The finding that was not on the list

Paper mode does not exist.

Arming changes two things today: the decision mode recorded in the evidence, and whether the
freshness gate binds. The broker is `NoOrderBroker` either way — `run_shadow` constructs it
unconditionally and `IBKRBroker` is never constructed anywhere in the runner. The code that
would swap in a real broker, place an order, reconcile the fill and book it has not been
written.

So the gate has been guarding a door that does not open onto anything. That is a safe state,
and it means the shadow period can be collected with no risk whatsoever of an order escaping.
But "close the blockers and we are trading paper" was never true, and nothing said so.

### Tests that had already been rewritten twice

Adding a blocker reddened seven files that pinned "B1 is the only blocker" — true when written,
legitimately false now. Two of them carried their own warning: the Stage 3B ledger tests had
been rewritten **twice** already, once when a measured gate was added and once when it was
released, and the comment above the assertion says plainly that chasing the state is the wrong
test.

So they are no longer chasing it. They are generalised over the measurement table: release
every measurement and the route must open; hold each one shut in turn and exactly its own gate
must be the reason it did not. The next measured gate will not red them.

Seven other failures turned up in the same sweep and are **not** from this stage — confirmed by
re-running them with the new blocker removed, where all seven fail identically. They are stale
snapshots from before the route grew its four sleeves, asserting that Track 1 adds 25 slots
where it now adds 70. Reported rather than quietly fixed: deciding what they should assert now
is a separate call.

### Where this leaves the route

The gate is correct and it is currently shut on both halves: B1 has not been decided, and the
evidence does not exist. One judgeable day is on record and it is a FAIL — which is the honest
state of a route whose first genuinely clean window has not yet run.

That window is tonight's, at 01:10 ET. When it closes at 02:55 the audit fires at 03:05 and
writes the first record that can count toward the five.

---

## Stage 5T — The Room Behind The Door (2026-08-25)

Stage 5S ended on an uncomfortable sentence: the order gate has been guarding a door that does
not open onto anything. This stage went and looked at what would have to be behind it.

### What arming actually does

Two things. It writes `armed` instead of `shadow_live` into the evidence, and it makes the
freshness gate bind. That is the whole of it.

The replay path passes the gate to `run_shadow`, which constructs `NoOrderBroker()`
unconditionally. The scheduler's path — `observe_live_slot`, the one that actually runs every
five minutes — **takes no order gate at all**: no parameter, no reference, nothing.
`"send_order calls: 0"` is a printed literal. So `--allow-orders` on the path that matters is
not merely refused; it is unreachable.

That is a good place to be standing while designing the thing that will change it.

### The seam is one object

Everything upstream of the broker must be the same code reading the same inputs — the live
frame and its splice guard, the history symbol, the freshness gate, the sleeve rules, the
sizing basis, admission and caps including the risk-high-first ordering inside an instant, the
explanations, the checkpoint and the params hash. Eight things, now written as walkable data
rather than as prose, with a test that requires every module they name to exist.

If any of them moves, the shadow evidence stops describing the thing that is trading, and the
gate built last stage is measuring the wrong route.

What may differ is four things, and all four are downstream of the decision: the broker object,
the send/cancel/switch calls, the fill result, and the book written after a **confirmed** fill.

### The wall that could be built without a broker

Turning an admitted candidate into an order is pure, so it is written and tested. It refuses in
four cases rather than guessing, and each refusal is a defect this route has already met.

The one worth naming is `ref_day`. An `Order` needs the trading day it belongs to, and it would
have been easy to derive it from the candidate's entry time. For Rổ 4 that works. For
`global_nkd` the entry stamp is an **aware Tokyo instant**, and turning that into a trading day
inside an order builder is the shape of every clock defect this route has had. So it refuses to
guess and asks the caller who already knows.

The others: a non-positive quantity is refused rather than rounded; an order may only be built
from a decision the cap gate said `TAKE` to; and the runner name must resolve, through the
broker's own map, to the same tradable symbol the route hashed. A test re-injects the August
defect — `_RAITS_TO_IBKR["MNKD"] = "NKD"` — and requires the refusal.

### MNKD stays split for free, and there is a trap next to it

`Order.inst` carries the runner name and `IBKRBroker.send_order` resolves it to MNK by itself.
One map, in the layer that owns the broker, and the order layer never names MNK at all.

The trap is one line away: `IBKRBroker.fetch_bars` resolves through that **same order map**.
Hand one broker object to both the executor and something that reads bars and Stage 5Q-7 comes
straight back. The executor has to be the only consumer of that object.

### What is reusable from legacy, and what is a trap

The close-then-open shape is already Track 1's own — `track1_switch` exists precisely because
Stage 2D looked at reusing `_handle_rollover` and said no. The broker's order methods are
instrument-agnostic and reusable as they are.

Reconciliation is not. `runner.py` reconciles against `live_positions.json`, which is the first
entry in the list of files this route must never write. Reusing it would bring back the exact
state assumptions the route was built to leave behind, and it has to be written fresh against
`live_positions.track1.json`.

### Two questions worth stopping on

Neither is hard, and both are the kind that get decided badly at 2am inside a pull request.

**Which comes first, the ledger row or the order?** Send first and a crash leaves a position
nobody recorded. Write first and a crash leaves a row claiming a decision that was never
placed. Both legacy and `track1_switch` emit before acting, which implies the row goes first —
and then the row has to be able to say *intended* as distinct from *filled*. The schema has no
such field today.

**What happens on restart?** Nothing yet reads the Track 1 position file back and compares it
with the broker before the first slot of a session. Until that exists, a paper run restarted
mid-session does not know what it holds. That is the failure mode B1 exists to talk about,
arriving from inside the route instead of from legacy.

### Where this leaves it

The design is specified, the pure half is built and tested, and the failure-branch test plan is
written. It is not ready to implement, because those two questions should be answered before
code rather than during it.

And nothing changed in what can happen today: four gates hold, the broker raises, the slot path
cannot see the gate, and there is no order-placing call anywhere in the route. The new module is
imported by nothing and can be deleted without altering a single runtime behaviour.

---

## Stage 5U — Intent, Fills, And What The Broker Cannot Tell You (2026-08-25)

Stage 5T ended on two questions it declined to answer badly at one in the morning. This stage
answered them, and both answers came from reading a contract that was already written down
rather than from inventing one.

### The ledger cannot own order state, and its own comment says why

`window_ledger._write` catches every exception and disables the channel for the process:

> It must never escape into a trading path — the ledger records availability, it does not
> enforce it.

That is precisely correct for evidence and precisely wrong for a write-ahead log. If the ledger
owned "an order is about to be sent", a failed write would let the order go out with no record
of intent — the single thing a write-ahead log exists to prevent.

So the two files keep opposite contracts and a third joins them: the window ledger stays
evidence and best-effort, a new order journal is append-only and **fail-closed**, and
`live_positions.track1.json` remains belief and advances only on a confirmed fill. A test parses
`_write` and requires that it still swallows, so if that ever changes someone re-reads the
decision instead of inheriting it.

### Six states, and one transition that does not exist

`INTENDED → FILLED` is not a legal transition. That is the whole of the first question in one
line: intent cannot be mistaken for a fill, because the journal will not accept the history —
and an impossible history is reported rather than smoothed, because a reader that quietly
repairs the journal is a reader that can be lied to.

`REJECTED` and `UNKNOWN` are separate states, and keeping them separate is the point. **"No" and
"I could not hear you" are different facts.** Treating the second as the first is how a filled
order becomes a position nobody believes in.

And `decided` on a slot row does not move at all. It keeps meaning "the route reached a
decision", pinned by a test that requires `classify_slot_row` to mention no order word. If it
ever came to depend on a fill, a broker outage would read as the strategy having stopped
deciding — and the shadow evidence and the paper evidence would stop being comparable, which is
the premise the whole readiness gate rests on.

### Reconcile needs three answers because the broker only gives one

`get_positions()` reads until two consecutive reads agree and, when they never do, **warns and
returns the last one anyway**. The caller cannot distinguish a settled truth from a guess.

That is the third time in this project a status reader has had no way to say "I do not know",
and the first one — `scheduler_processes()` returning an empty list — cost six entry slots. So
reconcile answers MATCH, MISMATCH or UNKNOWN, and **UNKNOWN blocks entries exactly as MISMATCH
does**. Exits are allowed in all three: refusing to *reduce* exposure while the book is confused
is the wrong failure direction.

### The hole under B1, asserted rather than described

While one login serves both routes, the broker reports one net per contract for both, so the
strongest available check is `broker == track1 + legacy`. It detects disagreement. It cannot
attribute it — and underneath that sits something worse:

```text
reality:  Track 1 holds 1, legacy holds 1   ->  broker nets 2
belief:   Track 1's book says 2, legacy's says 0
verdict:  MATCH — entries allowed — while Track 1's book is wrong by a whole contract
```

Equal and opposite errors cancel, and nothing in this design can see them. With a dedicated
account the same broker truth is caught immediately.

The first version of that test asserted the opposite and passed, because the case it happened to
build is one that IS caught. The difference between "reconcile has a limitation" and "reconcile
covers it" is worth getting right, so the test now asserts the hole.

**This turns B1 from a decision to be recorded into the thing that decides whether reconcile can
attribute a mismatch at all.**

### A gap in the broker, named

There is no `get_open_orders()` and no executions lookup. So a `SUBMITTED` with no answer can
only be resolved through `get_order_status(order_id)` — which needs an id the journal can only
have if the broker already returned one. That is exactly the gap a crash lands in.

The interim answer is a client-side idempotency key written before the call, with reconcile
resolving by comparing positions rather than order ids. It works. It is weaker than it should
be, and the missing method is now a named prerequisite rather than something to discover during
implementation.

### Where this leaves it

Both questions are contracts now, pure and tested — 24 tests, no broker, no socket. What remains
is the journal writer, the executor, two broker methods and the call sites.

And nothing changed about what can happen today: four gates hold, `run_shadow` still builds a
broker that raises, the scheduler's slot path still takes no order gate, and neither of the two
modules written across 5T and 5U is imported by anything in production. A test asserts that
last part rather than trusting it.

---

## Stage 5V — The Journal That Must Not Fail Open (2026-08-25)

Stage 5U argued that the window ledger cannot own order state. This stage built the thing that
can, and the whole of it is one property: **it must never fail open.**

### Two files, opposite contracts

`window_ledger._write` catches every exception and disables the channel for the process,
because *"it must never escape into a trading path"*. That is right for evidence. It is exactly
wrong for a write-ahead log, where a failed write would let an order go out with no record of
intent.

So the journal is the mirror image. Nothing in `append` is caught — not a bad record, not an
illegal transition, not a path outside the runtime root, not a full disk, not a failing
`fsync`. Every one leaves as an exception, because the only correct response to "I could not
record that I am about to trade" is not to trade. A test parses `append` and requires that it
contains **no `try` at all**, and a mutation that wraps one around the write turns two tests red.

The line is flushed and `os.fsync`ed before `append` returns. The directory entry is not — there
is no portable way on Windows — so the exposure is a file created in the same instant as a
crash, which is precisely the case the startup reconcile exists to catch. Written down rather
than left for someone to find.

### A failing test found a hole in the previous stage's design

One of my own tests expected both `INTENDED` and `SUBMITTED` to count as unresolved. It failed,
and being wrong about it exposed something real.

Stage 5U had said `SUBMITTED` meant "handed to the broker" — which never said whether the line
is written **before** or **after** the call. If after, a process dying inside `send_order` would
leave a journal whose last state is `INTENDED` while a live order existed. And `INTENDED` is
documented as *nothing was sent*.

The rule is now explicit: `SUBMITTED` is written **before** `send_order` is called. It is the
same discipline `track1_switch` already follows — *"Every stage emits BEFORE it acts. A crash
between two steps is then attributable from the log."* The cost is the opposite error and it is
the cheap one: an order that was never actually sent looks unresolved until a reconcile says the
broker has nothing.

Which makes `INTENDED` genuinely safe to read as "the broker was never reached", and that is the
whole reason the distinction matters.

### Corruption is reported, never tidied

A corrupt line comes back from `read()` with its file and line number. A corrupt journal
**refuses to authorise another order** — a journal that cannot be read whole cannot authorise
one. And an impossible history already on disk, hand-written past `append`, makes `resolve`
raise rather than repair. A reader that quietly fixes the journal is a reader that can be lied
to.

### One mutation that proved nothing, and had to be rewritten

Ten mutations, ten red — but the route-stamp one was green on the first attempt. It patched the
module's *source text*, which cannot change an already-imported `__post_init__`. It ran, it
passed, and it demonstrated nothing at all.

An unfaithful mutation is worse than no mutation: it reports a test as protective when it has
not been shown to be. Rewritten as a real in-process replacement, it goes red like the rest.

### Meanwhile, the first judgeable window was running

Not part of this stage, but it was happening in the next terminal and it changes what to expect.

```text
global_nkd 01:10-02:55 ET   14 slots observed   0 decided
every slot: gate_refused  partial_coverage,stale
runtime p50 2.44s  max 3.05s  all outcome=ok
```

The `stale` is the `spy_refresh_pm` gap arriving exactly where Stage 5Q-6 said it would: the SPY
series holds 2026-08-21 and a Tuesday session needs Monday's close. `spy_refresh_pm` was only
registered at last night's 23:29 restart — after 16:20 — so it has never run. Its first firing
is today at 16:20 ET.

So tonight's window will not produce a PASS and the readiness count stays at zero. That is the
freshness gate refusing on a real staleness rather than a new fault, and the slot cadence was
healthy throughout, which is the other half of what the window was there to show.

---

## Stage 5V-1 / 5R-2 — Asking For Bars That Had Not Happened (2026-08-25)

The first NKD window that could have been judged refused nineteen slots in a row with
`partial_coverage,stale`. The obvious explanation was the SPY staleness the freshness gate had
been complaining about all night. It was the wrong explanation, and finding that out took one
measurement: three slots ran **after** the CSV was refreshed and said exactly the same thing,
while `freshness.evaluate()` was returning `allow=True`.

Both codes were the intraday gate. `run_live_day_track1` builds the ledger `detail` as
`",".join(verdict.codes)` from `intra.validate` and from nothing else.

### Two bugs, one mistake

**The span asked for the end of the band.** `today_to` for `global_nkd` is 15:55 — where the
*scan stops*, not a bar anything reads. `_span_check` demanded the frame reach it, so a 14:10
slot required 105 minutes that had not happened yet. Measured on the live frame: *"last bar in
the span is 15:46, expected 15:55"* — on a frame holding 107 contiguous bars of that session.

**Staleness was off by three seconds.** A slot fires about three seconds after its own minute,
so the newest *complete* five-minute bucket is exactly one bar back. The check compared
`last + 5min` against raw `now`, and failed by those seconds: *"last bar 15:45 is more than one
5-minute bar behind 15:50:03"*.

Both are the same mistake — a frame that only exists on a five-minute grid, compared against a
continuous instant.

### One idea, used twice

`_last_closed_bar(now, n)` is the newest grid point whose bar must certainly have finished:
floor to the grid, then step back one whole bar. Flooring alone would not do, because at
14:10:03 the 14:10 bar is the one still open — Stage 5R-0 drops it for exactly that reason.

It is used for the span bound and for the staleness horizon, deliberately, so the two can never
disagree about which bar the frame owes. A test parses `validate` and requires exactly two call
sites.

The span bound follows the slot **only for the two scanning sleeves**, declared per sleeve
rather than applied blanket. Calm's `today_to` is its entry bar; Stress's sits before its own
decide band and is always in the past. A blanket `min()` would have quietly shrunk Calm's span
to 09:30–09:55 and stopped demanding the 10:00 bar. Swing had the identical defect as NKD and
is fixed with it — by measurement, not by assumption.

Nothing was widened. The span is still contiguous from 14:00, a hole still refuses, a
late-starting frame still refuses, and a frame two bars behind is still stale.

### The fix was watched landing, in production

The window was open while the two edits went in, and because slot subprocesses import fresh, the
ledger recorded the transition without anything being restarted:

```text
02:45 ET   partial_coverage,stale     old code
02:50 ET   stale                      span fix live, staleness fix not yet
02:55 ET   too_late                   both live
```

That last one is not a third bug. The final slot fires three seconds after the band closes and
can never decide — pre-existing, and benign because the acceptance gate classifies `too_late` as
`observed_window_shut`, an *observed* class. `partial_coverage,stale` classified as
`observed_hard_refusal`, which is precisely why the other nineteen mattered.

### What this window is, and what comes next

It will not pass. Nineteen slots were hard-refused before the fix landed, the window closed
`incomplete`, and nothing was backfilled or edited — the rows say what they said. The next NKD
window, on 2026-08-26, is the first that can be judged on a gate that asks for bars which exist.

Nine mutations, all red, and most of them do not remove the fix — they overshoot it. The danger
with a causality fix is never that it fails to work; it is that it widens something on the way.

---

## Stage 5W — the executor, and the walls around it

*2026-08-25. No order, no broker connection, nothing restarted.*

Verdict: **ready for wiring**, which is not the same as wired. The skeleton exists and is
fail-closed at every step that could reach a broker; what is missing is the one line that would
call it, and the two gates in front of that line are still shut.

### The correction from Stage 5V-1 that this stage owes

The previous section says nineteen slots were hard-refused. The closed ledger says **twenty-one**
— twenty reading `partial_coverage,stale` and one reading `stale`, with a single `too_late`
making twenty-two rows in all. The narrative above was written while the window was still open
and undercounted. The number now lives in a test that pins the distribution exactly, so it
cannot drift again; a subset check was the right shape for an open window and the wrong shape
for a closed one.

### What the executor is

The narrow layer between a decision the book has already made and a broker. It decides nothing —
no bars, no caps, no rules — and it is assembled entirely from the three pure modules the
previous stages built. One operation is implemented, the entry; the other three are still the
refusing stubs from Stage 5T, because adding them before anyone has watched the first one run
would be three more things to unwind.

The order of operations is the whole design:

```text
refuse unless the cap gate said TAKE
build the order              refuses on identity drift, bad size, missing trading day
record the INTENT            durable, flushed to disk, raises if it cannot be written
record the ATTEMPT           before the broker is called, same guarantee
call the broker
record the OUTCOME           filled / partial / rejected / unknown
```

Both records precede the call and both raise, so an order can only reach a broker after the
intent to send it survives a power cut. A crash leaves a journal a restart can read: nothing
after the intent means the broker was never reached, and an attempt with no outcome means stop
and ask.

That last claim is proved from *inside* the broker call — the stand-in broker reads the journal
at the moment it is invoked. Checking the file afterwards would have passed under either order.

### Ambiguity is not refusal

A broker that raises, times out, or answers with something the module cannot classify produces
**unknown**, and the failure is passed up rather than swallowed. "The broker said no" and "I
could not hear the broker" are different facts, and a filled order recorded as rejected becomes
a position nobody believes in.

### It never touches the book

Not a guarded write — none at all. There is no writer for the route's position file anywhere in
the module, which is a property of the file rather than a discipline someone has to keep. The
caller advances the book, and only on a confirmed fill.

Reading the book back is where I was wrong first. My reader asked for the wrong field name; the
writer spells the size differently. A reader that refuses every genuine book while raising a
fail-closed error is the worst of both — it looks safe and it never works. It now reads what the
writer writes, checked against the writer's own source so the two cannot drift apart quietly.
Two further refusals earned their place while fixing it: the route's book and the legacy book
are the same shape and differ only by a stamp, so a book carrying the wrong stamp, or a schema
from the future, is refused rather than read as a valid answer to the wrong question.

A missing book is still an empty book, and that is correct — the route has never held a
position. A book that exists and cannot be read is not an empty book.

### Arming changes the label, not the decision

Proved structurally rather than by running a day twice, because running a day twice would only
show the two modes agreed on that day. Inside the run function the mode is read exactly once
after it is set, and that read is the label handed to the explanation writer. It reaches no
gate, no rule, no cap. Both live modes also sit inside the set where the freshness gate binds,
so arming cannot loosen it.

### Three walls, none of them "we remembered not to call it"

It refuses to exist without an armed gate, and the real gate answers *no*. Nothing imports it.
And the scheduler's slot path takes no order argument at all, so there is no argument by which a
scheduled slot could reach it even if the other two changed.

The second wall is where a mutation found a real hole in my own test: it checked one half of an
import statement and not the other, so the most natural way to write that import in this repo
went straight through while the test stayed green.

### The measurement that keeps failing the same way

A plain text search for the arming flag **fails** in the scheduler — and correctly so, because
the scheduler both documents and comments that it passes no such flag. The search for the thing
matches the prose forbidding the thing. This is the third stage in a row. Only a real string in
a command line counts, and the flag's own definition is not a caller.

### Eighteen mutations, all red — and three of them were wrong first

Two broke the wrong object: they patched the same thing the test already replaces, or patched
something the code calls only once and reuses, so they stayed green while proving nothing. The
third was faithful and found a genuinely weak test. All three are now commented in the harness
with why the obvious place to break it is the wrong place. **An unfaithful mutation is worse
than no mutation, because it produces a green line that reads as proof.**

### What is left

The evidence gate needs five judgeable days and has none. The account decision is a person's to
make. The broker still cannot be asked what orders are open, so an unresolved order is chased
through positions instead — weaker, and labelled weaker, with a test that fails the day someone
fixes it. And the call site is unwritten, deliberately: it is one line, and it is the line that
makes orders possible.

---

## Stage 5X — teaching the broker reads to say "I don't know"

*2026-08-25. No order, no broker connection at all, nothing restarted. Every broker in every
test is a fake.*

Verdict: **ready for the call-site design**. Nothing on the read side blocks paper orders now.

### The correction Stage 5W owes

The previous section named two broker capabilities as missing. Reading the file rather than
testing a name shows **both entries were wrong**. The execution lookup exists — under a
different name, taking an order id. And the open-order read did not exist as a method, but the
underlying broker call it needs was already being made at five places in that same file. It
took a dozen lines to expose.

So the capability gap was never real. What *is* real, and survives this stage, is smaller and
more awkward: **the fill record the broker hands back carries no order id at all.** Both
id-keyed lookups are therefore useless on an entry this route just sent, however complete the
broker's API is.

The lesson underneath it is the one worth keeping: a test that asks "does a method with this
name exist" measures the name, not the capability. Nobody had ever proposed that name.

### What was actually wrong

Three reads, each folding two different facts into one value:

- the position read, after four unsettled attempts, returns the last one with a warning — so
  *"I could not settle"* arrives looking like *"here is what I hold"*;
- the order-status read answers *"not found"* from inside its own error handler — so *"I could
  not ask"* arrives looking like *"that order does not exist"*;
- the execution lookup answers *nothing* for not-found, for any error, **and** for "two records
  match and I cannot tell them apart" — three facts, one value.

And the shadow broker answers the position question with an empty list, which in shadow means
*never asked*, not *flat*.

None of this is a new idea in this repo. The convention is already written down beside the one
read that follows it: return nothing-in-particular only when you are offline, never an empty
collection, because the caller must be able to tell "nothing there" from "cannot say". One
method obeys it. Three do not. This stage extends the existing rule rather than inventing one.

### What was deliberately not fixed

**The three legacy reads were left exactly as they are, and a test now stops anyone helping.**
The legacy runner is built on what they return today, and making them fail closed would look
like a repair while silently changing what that route does on every reconnect.

The collapse even points in opposite directions for the two routes. For legacy, "not found" on
a protective stop means treat it as a mismatch — which is the cautious reading. For an entry
this route just submitted, "not found" would read as *it never reached the broker*, and acting
on that means sending it a second time.

There is a second difference worth naming so it is not mistaken for an oversight: legacy does
not fix the read, it compensates at each place the read is used. The new route compensates once,
at the read. Both are now pinned, so a future tidy-up of those per-site guards turns a test red
instead of quietly removing the only protection legacy has.

### What a submitted order resolves to

Working orders are asked about first, because an order still on the broker's book is the one
unambiguous answer and it settles the question with no inference. Executions second. **Positions
are consulted last and never decide anything by themselves** — a matching position proves
something filled, not that *this* order filled it.

Out of that came a case nobody had written down: the broker says *filled* and will not produce
the record saying how much or at what price. That is **unknown**, not filled. A book advanced on
a size nobody stated has stopped describing the account.

And the rule that governs all of it: **rejection requires a statement.** Silence is never
rejection — not an error, not an empty answer, not a timeout.

### One word changed from Stage 5U

That stage said exits are always allowed. Right about intent, loose about wording. Exits are
allowed while the book is unresolved **only if they reduce exposure** — an oversized "close"
against a book you cannot account for does not reduce anything, it opens the other side.

### The harness was lying

One mutation reported success against a test whose name had changed an edit earlier. The test
runner exits non-zero when asked for a test that does not exist, so the harness read that as
*the mutation worked* — from a mutation never exercised at all. It now runs each test
unmutated first and demands it pass before breaking anything.

Two other mutations patched a file's text while the tests they targeted read the interpreter's
cached copy, so the patch never arrived. Both tests now read the file, which is what makes them
breakable in the first place.

Twenty mutations, all red, every one with a proven-green baseline. And a text search matched
its own prohibition for the fourth time in this arc — a comment that names a method while
calling nothing.

### What is left

The evidence gate still needs five judgeable days and has none; the first window that can be
judged on the fixed gate is tomorrow morning. The account decision is a person's. The missing
order id is the next thing worth solving, and it is a change to the write path rather than the
read. And the call site is still unwritten: one line, and it is the line that makes orders
possible.

---

## Stage 5Y — the write path learns to name the order it sent

*2026-08-25. No order, no broker connection, fake brokers only, nothing restarted.*

Verdict: **ready for the dry-run call-site design.** The broker write path is no longer what
blocks paper orders.

### The gap

Both of the broker's order lookups take an order id, and until today nothing that *placed* an
order ever learned one. After a crash the route held a journal row saying "submitted" and no
way to ask about it.

### Why one change was not enough

A field on the returned fill record only exists if the call returns. The entry poll blocks for
up to thirty seconds, and that window is exactly where a crash loses everything. So the id is
reported **twice**: once by a receipt handed back the instant the broker accepts the order —
before anything waits — and again on the outcome. The receipt is the one that survives a crash;
the outcome is the one the reconcile reads afterwards.

Both were added in the only shape that leaves the older route untouched: a new field appended
last with an empty default, and a keyword-only argument that defaults to off. Every existing
call site still binds, and a test asserts the six places in the legacy runner still pass one
argument and nothing else. A broker that ignores the new argument is not broken — it simply
cannot report early, and the reconcile falls back to the previous stage's weaker
identification and says so.

### The place this adds information rather than a field

The error handler used to answer two completely different situations identically: the order
never reached the broker, and the order reached the broker and something afterwards threw. The
second leaves live exposure. A caller that cannot tell them apart has to assume the worse one
every time. It can tell them apart now.

And one hazard had to be closed on the way: if recording the id fails *after* placement, the
broad handler would have caught it and reported a **live order as cancelled**. That is the
worst answer available — worse than crashing, because the caller believes it. The refusal now
has its own type and travels straight past that handler.

### An amendment, not a transition

The "submitted" row is written before the broker is called, so the id cannot be on it. The
receipt arrives mid-call and is recorded as a second row in the same state.

That is not a state change and the state machine still refuses one. It is an **amendment**: the
order did not change, we learned its name. The rule is narrow on purpose, because a permissive
repeat would let a genuine duplicate send look like a legal history — the earlier row must have
no id and this one must have one, an id may never be replaced, and nothing else may move.

### The bug this stage shipped, and how it was caught

The first version was broken, and **all fifty-two tests passed over it.** The writer accepted
the amendment and the reader then called the resulting journal an impossible history — so every
order that successfully got an id would have made that day's journal unreadable.

It was found by running the round trip by hand. Every one of those tests checked the *write*;
not one re-read. The cause was two rules where there should be one, and the fix is a single
shared rule that the writer asserts against and the reader consults. Six read-back tests now
exist, and they are the ones that would have caught it.

### The id is authoritative, including when it says no

The previous stage matched a working order by instrument and action. That fallback stays, but
it is no longer consulted after an id mismatch: a different order on the same contract with the
same action would otherwise answer for ours, which is the exact failure the id was added to
remove. Which route answered is now recorded in the evidence, because the two are not equally
strong.

### Twenty-four mutations, and a harness that lied three times

Seven came back green on the first run and every one was the harness's fault, not the code's:
they patched a file's text while the tests they targeted assert *behaviour*, which a text patch
can never change. That is a lesson written down two stages ago, repeated in the same session,
and then repeated again after being fixed once. An eighth patched a module attribute the test
had already imported by name.

One mutation was faithful and found a real hole: its first form made a file unparseable, and
the test caught the parse error and **skipped the file** — passing while a legacy call site had
changed. Same shape as answering "I could not read it" with "there is nothing there", which is
the defect the previous stage spent itself on. An unparseable file is now a reported failure.

### What is left

The evidence gate still needs five judgeable days and has none. The account decision is a
person's. The call site is unwritten and should first appear behind a dry-run mode that builds
the executor and refuses at the broker boundary. Three of the four operations are still stubs.

None of that is a broker-capability gap any more.

---

## Stage 5Z — the rehearsal, and the wall it has to stop at

*2026-08-25. No order, no broker connection, and the only broker in the stage refuses by name.
No production file was modified.*

Verdict: **ready for implementation once the evidence exists.**

### The seam was not where the last-but-two section said

That section named a line in the window-replay function — the line where the no-order broker is
constructed — and called it the call site. Reading the file shows both halves are wrong.

The window replay is not what the scheduler runs. The seventy strategy slots run a different
function entirely, one that takes no gate and no broker at all. And in the replay function the
broker object is **never passed to anything**: it is constructed, and then read exactly once for
its call count, to prove nothing was sent. Swapping it for a real broker would change nothing,
because no code hands it an order.

The real seam is one line inside the live slot function, immediately after the call that
produces admitted decisions — the first and only moment a live slot holds any.

The dry run **derives** that location from the file rather than restating it, and refuses when
the anchor becomes ambiguous. A comment naming a line number is a comment that will be wrong,
and this one already was.

### Six stages, and the sixth is a wall

The rehearsal walks everything a real call site would: what the real gate says, whether a
restart would be allowed to enter, whether the executor can be built, the mapping of every
admitted decision, the durable journal rows — and then the broker refuses.

It runs on a synthetic gate, of a deliberately different type from the real one, and reports
the true answer beside it. Arming the rehearsal arms nothing.

**A dry run succeeds by being stopped.** A run where nothing was admitted has every stage pass
and is *not* a pass, because it never reached the thing it exists to test. Three tests hold
that line.

### Where a rehearsal may write

It leaves rows behind, deliberately — the intent, the attempt, and then "could not see what
happened" when the wall raises, which is precisely the crash-path rehearsal worth having.

Those rows are indistinguishable from real ones once written: same route stamp, same schema,
and they read as unresolved orders. The only thing keeping them apart is the directory, so the
directory is checked hard: the real journal is refused, and so is any parent of it and any child
of it. The parent matters because reading the journal with no date walks the whole tree.

### The scope question, and the answer that turned around

Is entry-only safe, or must the exit, the protective stop and the symbol switch be designed
first? The answer came from the scheduler's own registry rather than from judgement.

**The protective stop and the max-hold exit are already covered.** Eleven Track 1 safety jobs
are registered against the route's own position file, and the checks that place stops and book
exits run inside the runner's constructor. They do nothing today only because that position
file does not exist.

Which turns the finding around. An entry-only call site does not leave a naked position — it
does something with a wider blast radius: **the first paper fill activates eleven jobs that have
never run against anything**, and they open connections. That should be a watched event, not a
side effect discovered afterwards.

So entry-only is the right first scope, on three measured grounds: the exit and stop paths
already exist and are already scheduled, the symbol-switch module is imported by nothing and so
cannot bypass the journal, and the strategy-exit gap is not reachable from a live slot either.
One honest gap remains and is named: stops and exits placed by the safety jobs are invisible to
the order journal until a later stage routes them through the executor.

### Twenty-three mutations, and two that found the code being right twice

Three came back green at first, and for once the code was the reason rather than the harness.
The rehearsal's success flag is guarded in two independent places, and the wall is silent in two
independent ways — so removing either guard alone changed nothing.

Redundancy like that usually reads as a smell. Here it is the difference between a rehearsal
that has to lie once and one that has to lie twice, so both are now pinned by their own tests
and the mutations remove both guards — which is what a well-meaning "simplify this" or "make the
fake more useful" change would actually look like.

### One door instead of two

Five tests in earlier sections needed updating, all in the direction of a stronger guarantee.
They asserted the chain had two heads, each imported by nothing. The dry-run module now imports
both, and nothing imports it — one door to watch instead of two, and every one of those five
fails if it is ever opened.

### What is left

The evidence gate still needs five judgeable days and has none; the first window that can be
judged on the fixed gate is tomorrow morning. The account decision is a person's. And the
eleven safety jobs deserve to be watched on their first real run rather than discovered.

Nothing on that list is a code gap in the order path.

---

## Stage 5ZA - post-stage causal slot audit

*2026-08-25. No scheduler/backend restart, no IBKR connection, no order, no runtime evidence
edited.*

Verdict: **ready for the next shadow window, with the causal slot guard now covering all 70
strategy slots.**

This closes the operational-audit item raised after 5V-1: a slot that fires every five minutes
must not require bars from the end of its whole window/session. The new audit builds a partial
frame for every Track 1 strategy slot at its own timestamp plus three seconds and runs the real
intraday gate. All four sleeves are covered: Calm 1, Stress 24, Swing 23, NKD 22.

The pass found one real defect before it became the next live incident. `TRACK1_CALM_1000`
passed at exactly `10:00:00` but refused `too_late` at `10:00:01`. A real scheduler child starts
a few seconds after its nominal minute, so the first Calm slot that reached the gate would have
been refused even though it was the scheduled slot. `track1_intraday.Requirement` now carries a
60-second dispatch grace: seconds late is still the slot; past grace is still fail-closed.

The static seams are pinned too: each live-source sleeve fetches `through=now`; Stress and
Normal/NKD truncate their scans to the slot instant; Calm uses the entry-only detector rather
than the full-day replay; and the paper callsite seam remains `observe_live_slot`, not
`run_shadow`.

Tests: `scratch/test_track1_stage5za_causal_slot_audit_20260825.py` 9 passed;
5V-1 rerun 31 passed; combined 40 passed. Mutation proof for this new audit is still pending
before paper.

---

## Stage 5ZB — the negative audit, and reading the runtime correctly

*2026-08-25, morning. Read-only throughout: nothing restarted, no broker contact, no order, and
no runtime file written, moved or edited. No production file changed either.*

Verdict: **ready for the next shadow window, operationally audited.** Paper remains blocked by
the account decision and by five judgeable days that do not exist yet.

### The clock, first, because it cost an hour

**Asking the shell for New York time returns UTC on this machine.** Three earlier sections were
timestamped with it and are now corrected — each says four hours earlier, with a note saying
why. No conclusion in any of them turned on the number; the numbers were simply wrong, and a
wrong number left in a document is one the next reader trusts.

The cost this morning was worse than a wrong header. A healthy scheduler was read as six hours
hung and a window three and a half hours in the *future* was read as four hours overdue, and I
went looking for a failure that was not there. The scheduler's own log stamps machine time,
which is two hours behind the market — so a line reading `04:20` beside a job named for `06:20`
is not a contradiction, and I read it as one.

The runbook now opens with the anchor rather than a habit.

### Re-verifying the causal audit

All five claims hold, re-measured rather than re-read: seventy strategy slots, each validating
against bars available only up to its own slot time, no sleeve requiring the end of its window,
the Calm dispatch grace bounded on both sides — seconds late still allowed, a minute late
refused — and no strategy rule touched.

That last one is now proved *structurally*: the gate module cannot import a sleeve rule module,
so there is no expression it could change. Comparing identity hashes would only have said the
two agreed on the day the test ran.

### The fixture that agreed with whatever the code decided

The seventy-slot sweep built each slot's frame by reading the very field the sweep exists to
protect. A mutation that flipped that field moved the fixture with it, and the sweep stayed
green while agreeing about the wrong thing.

It now derives the bound from something the gate does not own — whether a sleeve's declared end
is still in the future at that slot. Flip the field now and twenty-two slots demand bars that
cannot exist yet, and the sweep goes red.

### Twenty-four mutations, all red

Every named guard broken and caught: the dispatch grace removed and separately made unbounded,
both truncations dropped and one computed-but-never-applied, a sleeve fetching past its own
slot, the seam claiming the wrong function again, and the two halves of the crash that killed a
live slot last Monday.

Two of them found weak **tests** rather than weak code. Besides the fixture above, the ledger
sweep accepted an empty result — so hiding every ledger file left it green. *"No dangling
windows"* and *"I could not find the ledger"* were the same answer: precisely the defect this
route spent four stages removing from its broker reads, reintroduced by me in a test.

The audit's own seam tests were left in place but are no longer the mutation targets. They ask
the interpreter for a function's source, which comes from a cache, so a source-level mutation
cannot reach them — they are unbreakable, and an unbreakable test is one nobody can trust later.
The versions written here read the file and walk its structure.

### What the ledger actually said

Two days exist, and neither is judgeable — for two entirely different reasons, which is the
part worth recording.

The overnight window failed on the causal gate, in the distribution the previous section
already described. But the day before, forty-six of forty-seven slots failed on something else
entirely: the live feed and the stored history disagreeing about a single bar at the daily
append boundary. That is a history artefact, not a gate problem and not a feed fault — and the
pre-flight already runs the boundary repair for it, with a comment recording that the same
thing refused forty-six slots the Friday before.

The parquets were repaired by hand seven and a half hours *after* the windows that failed on
them. So those refusals were measured on unrepaired history and predict nothing about today.

One more: a window opened last Monday and never closed. The scheduler log gives the cause
outright — the slot died on an uncaught splice refusal, because the feed hands back two columns
the stored history does not have. Both halves were already fixed by another session; this stage
pins both from the file so neither can quietly come back.

### The next judgeable window is today

Earlier sections — mine included — named the overnight window on the 26th as the next one. That
was the answer for one sleeve, presented as the general answer. **Four windows run today**, and
the first is the one-shot slot at ten in the morning, which will be the first ever to run with
the dispatch grace, the splice catch and the column projection all in place. The afternoon
pre-flight will be the first automatic run of the boundary repair.

### One failing test, left alone

A live-state assertion from another session expects the pre-flight to be one business day ahead
of the daily series. It is not, because today's pre-flight has not run yet — it runs in the
early afternoon, and that assertion is therefore false for most of every trading day.

Left exactly as it is. Quietly loosening someone else's invariant to get a green run is how a
real signal gets removed, and this one is telling the truth about the runtime even if its timing
assumption is too strict.

### What is blocked by what

Evidence blocks one thing: five judgeable days, of which there are none. A person blocks two:
the account decision, and being present for the first fill, which activates eleven safety jobs
that have never protected a real book. The order path itself blocks nothing — it is designed,
rehearsed end to end, and deliberately unwired.

---

## Stage 5ZC — the first windows after the audit, and the one that never ran

*2026-08-25, late morning. Read-only: nothing restarted, no broker call started, no order, and
no runtime file written or edited. No production file changed.*

Verdict: **ready for the next shadow window** — the route works. But the day's first window
produced nothing at all, and the reason is not in this repository.

### The window that did not happen

The one-shot morning slot left no trace: no window opened, no slot row, no close. The day
before it at least opened a window before dying; this time there was nothing.

The scheduler said why itself, in a warning it was built to emit: **the machine slept for three
hours and thirty-seven minutes.** The process survived; its wait timer did not advance. Every
job due inside that window was missed and logged as missed — two stop-repair sweeps, a max-hold
exit, the morning slot, that slot's own audit, and seven consecutive slots of the next window.
The first job to run after the machine woke was the eighth slot of that window.

So the morning window is **not a failure — it is an absence**. Nothing about the sleeve, the
gate, the splice guard or the strategy was exercised. The dispatch grace, the splice catch and
the column projection added over the previous days are all still unproven in production, because
they have never yet had a slot to run in.

The previous section's judgement that the scheduler was healthy was correct when it was made:
the heartbeat is hourly, and at that moment the last one was thirty-nine minutes old. The sleep
began an hour later.

### And it is chronic

Every scheduler log that records a stall records at least one. Across the logs on disk: thirty-
three stall events, sixteen days affected, **twenty-two hours of scheduler time lost**. Today's
was the second worst on record and landed squarely on the morning window.

No work on the strategy, the gate or the order path moves that number. Judgeable days need the
machine awake at specific times of day, and on this evidence it is asleep for part of most of
them. The remedy is a power setting and belongs to the operator; the log message names it, and
this stage did not run it. Worth noting the log names only the battery form — the mains form
matters too, and setting one without the other fixes half the problem.

### The route itself works

Two slots ran after the machine woke, and both **decided** — the first decided rows anywhere in
the ledger. The gate passed, freshness passed, and the sleeve looked and found nothing to take.
That is the legitimate no-action case, and it is the first evidence that the whole chain runs
end to end on live data.

The history-boundary disagreement that refused forty-six of forty-seven slots the day before did
not appear on either of them. Two slots is not proof, but it is the first counter-evidence, and
it is on repaired history.

Both slots wrote an explanation record carrying a structural freshness proof and a data
fingerprint, with no candidate rows — because there were no candidates, and the ledger says so
in as many words. **Absence recorded, not merely absent**, which is the condition the runbook
requires before calling that a pass.

### A ledger shape the runbook does not yet teach

The open window has slot rows and **no opening record**, because the opening record is written by
the window's first slot and that slot was the one the sleep ate. It will close this afternoon
without ever having opened.

The runbook teaches the opposite case — opened and never closed — as the loud signal. This is
the equally informative inverse: *the window's first slot never ran*. The audit should refuse to
call such a window judgeable, and this afternoon is the first chance to watch it do so.

### The dashboard agrees, with one collision worth naming

No phantom overdue rows, no incidents, no hidden dangling window, and the Track 1 view
independently reports the same two explanation files and the same two open blockers. It even
names the missing morning sleeve as *not yet audited* rather than omitting it.

One discrepancy: two different fields are called "freshness". The operations command reports the
**broker connection** as fresh; the schedule endpoint reports **stale** at thirty-two hours.
Traced to source, the second reads the *legacy* route's state file — which never gets written
during a shadow period, so it is stale by design and will stay that way for as long as the
shadow lasts.

Classified as a reader mismatch rather than a runtime failure: no runtime evidence corroborates
it and it raises no incident. Left unchanged. But a rail that reads "stale" throughout a healthy
period is a rail an operator learns to ignore, which is the same argument that produced the
open-versus-historical incident split in the first place.

### A test of mine that was wrong

An earlier section pinned the overnight window's refusal distribution by asserting the day's
ledger held exactly twenty-two rows, reasoning that the window had closed. The window had. **The
file had not** — it is one ledger per day, shared by every sleeve, and it broke the moment the
next window wrote into it.

The same family as pinning a line count on a log still being appended to, which this project has
been caught by before. Fixed by scoping the assertion to the sleeve, which keeps the exact
distribution — the durable fact — without pinning the size of the file it happens to live in. A
second test now states the shared-file property outright so the next person meets it as a fact
rather than a surprise.

### Where the paper gate stands

Measured rather than estimated: one judgeable day on record, and it is a failing day; no sleeve
has ever recorded a pass. **Zero of the five qualifying days.** Today is not counted, because
the day is not over.

---

## Stage 5ZD — asking the slots why, and getting an honest answer

*2026-08-25, midday. Observability only: no order, no broker, no connection, and no restart.*

Verdict: **signal diagnostics ready, dashboard ready.** Paper is blocked by exactly what it was
blocked by before.

### The question the evidence could not answer

The window ledger says whether anyone looked. The audit says whether the window held together.
Neither answers the thing an operator actually asks five minutes after a slot runs: **it looked
and did nothing — why?**

`candidates: 0` is not that answer. It is the shape of one. After several stages spent removing
exactly that pattern from the broker reads, it should not have survived on the strategy side.

Every strategy slot now writes a row saying which of five things happened: the gate refused it,
it looked and found nothing, it found something not yet through admission, a **named** layer
declined it, or the book admitted it and no order was attempted. The two in the middle are the
pair worth guarding — one means the market offered nothing, the other means it offered
something and this route declined it, and a summary showing both as "no trade" would hide every
cap and every suppression.

### It went live before the stage finished

Slot subprocesses import fresh, so the writer became live the moment the file was saved. By
midday the running scheduler had produced three real rows on its own, with no restart and no
intervention — and the reader and the job view were then checked against those rather than
against a fixture.

### What the first real row says, and why that is the point

Two rules answered with a measurement. Eight answered *"the sleeve did not tell us"*. Three
answered *"never got that far"*.

The obvious way to fill in the eight was to recompute breadth, the gap count and the average
gap in the diagnostics. **That was not done, deliberately.** A second implementation of a
strategy rule is a second answer to the same question, and it disagrees with the one that
trades on the day it matters — a defect this project has already paid for twice.

So a rule check carries three possible sources rather than a bare pass or fail: *measured*,
*never reached*, and *ran inside the sleeve and was not returned*. The third is the honest one,
and it is never counted as a pass — not in the summary, not in the nearest-miss report, and not
on the dashboard, where it renders in the warning colour rather than the good one. **A rule the
sleeve did not report has not been shown to be fine.**

The one-line summary says so out loud rather than falling silent, because a line naming no
blocker would read as *"nothing was close"* when the truth is *"nobody said"*.

That makes the next piece of work obvious and specific: the four sleeve detectors need to
return their rule values. That is a change to the sleeves, it needs the artifact reproduction
run behind it, and it belongs to its own stage. Recorded, not attempted.

### A slot that never ran is not a slot that declined

Nothing is written for a slot that never spawned. Manufacturing a "no signal" row would turn
*the machine was asleep* into *the strategy looked and declined* — and the machine slept through
a whole window yesterday, so this is not hypothetical.

A third reading was needed within an hour of building it: the thirty-three slots that ran
*before* the journal existed are not missed either. The job view distinguishes them from the
job's own status, because calling them missed would have accused the scheduler of failing when
it had not.

### Two layers on the page, and no new card

The route panel gets one compact row — per sleeve, the latest status, the latest slot, today's
counts, and the most recent accepted signal stated *with* "no order attempted" so an admission
is never mistaken for a trade. The job view gets one sentence under the existing status line,
on strategy slots only; the rule checks and candidate detail appear only when the row is
expanded.

The sentence is composed by the backend rather than the browser, so the phrasing has one owner
and a test can assert it. The line sits inside the existing row and wraps rather than widening
the table.

### Two tests of mine needed correcting

One pinned *exactly one* decision-mode site in the live slot; the diagnostics row records the
mode it decided under, making two — an honest addition that read as a regression. It now
asserts every such site records the shadow mode, which is what its docstring always claimed.

The other asserted that a production directory contained no files. That said what it meant only
until the route wrote its first explanation, which happened this morning. A before/after
snapshot was not the fix either, because the live route writes there every five minutes during
a window and would be blamed on the suite. The durable property is asserted instead: the
directory is a relative constant and the fixture hands the slot a temporary root, which is what
structurally prevents the suite writing there at all.

And my own end-to-end fixture was refused by the frame guard on its first attempt. Rather than
patch around it I imported the helpers that already encode the clock contract — a fixture that
does not play the real data source is a fixture that tests itself.

### What it cannot do

It cannot place an order. The module imports no broker, no executor and no order journal, and
every row states that orders are disabled and none was attempted rather than leaving a future
reader to assume a default. Both gate blockers are unchanged.

---

## Stage 5ZE — health first, signal second

*2026-08-25, early afternoon. Dashboard, one backend reader and a label mapper. No strategy
change, no scheduler change, no gate change, no runtime write, and nothing restarted by this
stage.*

### The audit came first, and it found a hole

The previous stage put signal diagnostics on the job row. Before adding more, this one checked
what the row already told an operator about whether the slot had *run correctly* — a different
question from what the strategy then saw, with a different fix behind it.

Measured from the real payload and the real render path: the panel showed when a slot started,
when it ended, how long it took, an outcome, an impact, an action, and a list of trade events.
**That list is always empty for a shadow slot**, because a shadow slot emits no trades.

So an operator could see that a slot ran and for how long, and nothing at all about whether the
freshness gate passed, whether the live frame was refused, whether the evidence row the audit
counts was written, or whether the duration was anywhere near its budget. The audit verdict and
the checkpoint state existed only at day level, in a different panel.

### What was added, and where

An **Operational** block in the expanded panel, above Signal, in six short sentences: when it
ran in Eastern time and for how long, whether that was inside the runtime budget, whether the
ledger row was written, whether the freshness check and the live frame passed, and — said out
loud so its absence is not read as a fault — that no checkpoint or book write is expected in
shadow. Where a window has been audited, its verdict appears too.

Every field comes from evidence that already existed. Nothing new is computed about the
strategy, and it falls back to the coverage ledger when a slot predates the signal journal —
which is not a corner case, since thirty-three slots do.

### The chip, and what it replaced

The signal is now a **chip** in the page's existing badge language, sitting inside the job row
on its own line: seven labels, each with a required plain-English tooltip. A seven-state chip
with no explanation is seven colours nobody can act on.

It replaced the sentence the previous stage put there, which pushed every row to two lines
whether or not anything had happened — which is what makes a list of thirty rows unscannable.

### What is deliberately not on the page

The previous stage's expanded block showed raw variable names, JSON thresholds and a column of
UNKNOWN. All of it is gone from the view. It still travels on the payload, under a `debug` key
that **no code path in the page reads**, so a later stage can surface it once the sleeves return
measured values.

Mapping those names and showing them anyway was the tempting middle option and it was rejected:
every sleeve rule currently comes back unmeasured, so the result would be thirty human names
with no numbers beside them — a longer way of saying nothing, burying the two lines that carry
information. One honest sentence says the same thing: *detailed setup measurements are not
exposed yet*.

And a refused, missed or undiagnosed slot **points at the Operational block rather than
repeating it**. Two copies of one fact are two things to reconcile, and only one of them ever
gets updated.

### Two mutations that found the tests wrong rather than the code

A chip given a nine-hundred-pixel minimum width on a phone-sized screen stayed green twice. The
first check asked whether the *page* scrolled; it did not, because the chip sits in a scrolling
container. The second used the project's own clipping detector — which deliberately permits
wide content inside a scrolling ancestor, so it stayed green too. Both were answering a
different question from the one this stage actually claimed: *the chip does not widen its row*.
It measures that now.

The second was a browser check mutated in Python, where the fixture builds its own payload and
never calls the patched function. It is mutated in the file the browser loads now. That is the
same mistake in a sixth consecutive stage, which says the lesson belongs somewhere more durable
than a comment in each harness.

### The live page

Nothing was restarted here. The backend process was restarted by someone else between the two
stages, so the running dashboard currently serves the previous stage's shape and will not pick
this one up on its own — the server runs without a reloader. Making it live is one backend-only
restart, and that call is left with the operator so today's remaining window is not disturbed.

---

## Stage 5ZF — what is still missing before paper, measured

*2026-08-25, early afternoon. An audit, plus the two small reader fixes it proved necessary.
Nothing restarted, no runtime file touched, no strategy or scheduler code changed.*

Verdicts: **ready for the next shadow window, not ready for paper** — and the reasons why are
now specific rather than general.

### The inventory holds

Built by constructing the real scheduler and enumerating it rather than counting source: one
hundred and one jobs, nothing unclassified, and no legacy strategy job registered at all. The
legacy drain sweeps are all still scheduled, which is the point — retiring the legacy strategy
must never retire the jobs that unwind its book.

### The post-close SPY job was visible and said nothing

Three of the four things it needed were already true: it runs through the normal job wrapper so
it leaves normal evidence, it is mirrored in the schedule table, and it does not touch the
pre-flight record. No separate evidence system was needed and none was built.

The fourth was not. It fell into the reader's catch-all bucket, so a failure rendered as *"the
job emitted an unclassified error"* — a sentence true of anything and useful for nothing. Its
failure has one specific next-morning consequence: the daily series stays a day short, and every
slot the following morning meets a freshness refusal. The reader says that now, for the failed
case and separately for the missed one, because the machine sleeping through the scheduled time
is the observed failure mode rather than a hypothetical.

### The rail that was always red

The suspicion was right and is now measured end to end. The dashboard's schedule freshness reads
the *legacy* runner's state snapshot. In this mode the legacy strategy jobs are deliberately not
registered, so nothing ever writes that file, its age grows without bound — thirty-four hours
when measured — and the top rail read *attention required* for the entire shadow period.

That is an alarm that never turns off, which is exactly the defect this module already fixed
once by splitting open incidents from historical ones. An operator learns to ignore a light that
is always on, and the next real one is invisible.

The fix is narrow: when the route is in track1-only mode, a stale legacy snapshot no longer
decides the route's health. Every other freshness branch reads the scheduler log, which in this
mode contains the Track 1 slots, so the answer becomes route-correct rather than legacy. The
staleness is **demoted, not hidden** — it is reported under its own key with a reading that says
it is expected, and the legacy drain safety stays visible beside it.

What the rail says now is not green. It says attention required because two Track 1 slots did
not run this morning, and it names them. Before, it was complaining about a file nobody writes.

One thing nearly reported as a defect and was not: the mode flag read as absent in my shell,
which would have made the whole fix inert. It is set on the *backend's* environment, and the
live backend's own payload proves it has it. Measured before reporting.

### The reporting gap is wider than expected

The session report, the broker-statement pull and the P&L comparison were all audited by
structure rather than by reading their prose. **None of the three knows Track 1 exists.** The
P&L comparison reads the legacy book and the legacy trade log; the session report reads the
legacy book; the statement pull mentions neither route.

The sharpest finding is not in those three. Both Track 1 safety jobs — the ones that place its
stops and book its max-hold exits — hardcode the **legacy** trade log with no route scoping,
while being handed Track 1's own position file. The first Track 1 fill that a safety job later
exits writes a close row into the legacy log, indistinguishable from a legacy row. There is one
trade log on disk.

Six pieces are missing before paper, and that one is first, because it is the only one that
*corrupts* an existing artefact rather than merely omitting a new one. None was implemented
here; six is a stage of its own. Five tests pin the absences as negatives, so they fail the day
somebody implements support and leaves this section claiming it is missing.

### Regime labels are safe, and their verification is not

The daily series is a close series only, and the labels are never persisted anywhere — they are
recomputed on every read. So both refresh times are sufficient **by construction**: there is no
materialisation step that could lag behind an update, because there is no materialisation.

The early refresh runs before the close and can never carry that day's bar, and the gate does
not ask it to — the requirement is the last trading day before today, the same answer all day.
The post-close refresh writes what the next morning needs. Monday reads Friday across the
weekend, verified rather than assumed, and holidays use the same trading calendar as the
requirement itself.

The caveat is the verification. It only ever warns, and every one of its failure paths returns
the same value as success — including the paths where it could not verify at all. So a label
drift does not fail the job, the journal shows success, and nothing surfaces. Worse, "verified,
no drift" and "could not check" are the same number: the tri-state defect this route has spent
five stages removing from its broker reads, still standing in the one place that guards which
sleeve is allowed to trade.

Acceptable while in shadow. Not acceptable before the first paper order. Left unchanged here
because it is a behaviour change to a shared job and this stage's remit was reader-level.

### What blocks what

Nothing on the list blocks the next shadow window except the machine sleeping, which is a power
setting and belongs to the operator. Paper is blocked by five things: the evidence days, the
account decision, the six reporting pieces, the safety jobs writing the wrong log, and the
warn-only label verification. Two of the eight items on the list were user-interface problems
and both are now fixed.

---

## Stage 5ZG — the sixth file

*2026-08-25 evening. Closing the one thing on the pre-paper list that corrupted an existing
record rather than merely omitting a new one. Nothing restarted, no runtime file written, no
strategy or scheduler behaviour changed beyond where two jobs send their rows.*

### What was wrong

The route already had five files of its own: its book, its kill switch, its lock, its client
id, its five-day marker. Each of those was split off for a measured reason — a shared marker
had let one route's sweep silently suppress the other's, and that is in this document a few
sections above.

The sixth was never split. Both of the route's safety jobs — the one that repairs its stops
every two hours and the one that closes its five-day positions at the open — read Track 1's
book and wrote the **legacy** trade log, with no way to be told otherwise. There is one trade
log on disk, the reader that judges fill quality and profit consumes all of it, and it splits
on nothing. The first Track 1 fill either job ever closed would have entered that judgement
as a legacy trade, indistinguishable from one.

Worth being precise about which job: the stop-repair sweep takes no entries and places no
exits, so it does not look like a writer. It is one. Booking a stop it finds already filled
happens during construction, and that books money and writes a close row. The hardcoded path
was put there deliberately, in August, after a close moved the equity and left the log empty.

### The destination

One name, one place:

    global_index/track1_runtime/trade_log.track1.jsonl

Under the route's own runtime root rather than beside the legacy log at the top of the
repository, because everything else this route produces already lives there and the readers
that will eventually consume it are being written against that root. The scheduler passes the
name; the two jobs accept it; no reader spells it out. A test moves the name and insists the
command line moves with it.

Checked before adding a file to that directory: every reader of the route's runtime looks
inside a named subfolder with an explicit pattern. None of them lists the folder itself. The
new file is invisible to all of them, which is what was wanted at this stage.

### The rule

Nothing given, and the destination is the legacy log, byte for byte what it was — not probed,
not created, not touched. A destination given, and it must be writable *now* or the job
fails. A route tag given without a destination is refused outright.

The destination is never guessed from which book the job was pointed at. That would have been
one argument fewer and one silent failure: change the book, forget the log, and the rows go on
landing in the file that must not contain them, with nothing said. The mirror case is refused
for the mirror reason — tagging rows with a route while still writing them into the shared
file makes them identifiable and leaves them exactly where they do damage.

The writability check runs **before** the job looks for its book. Both jobs return early when
the book is absent, and through the shadow period that was every single run — so a check
placed after that point would never have executed, and a wrong path would have been discovered
by the first real fill, which is the worst moment available. Checked first, the route's eleven
safety jobs prove the destination writable every day they run, months before there is anything
to write.

The check is an actual append to the actual file, not a permission bit on the folder, because
an append is exactly what the writer will do and a writable folder holding an unwritable file
is a real state that the weaker check waves through. It leaves the file there, empty, on first
success. That is wanted: a reader can then tell a route that has never swept from one that
swept and closed nothing, which absence cannot express.

### The tag

Every row the route writes now carries its own name. The runner gained one optional setting,
off by default and last in its list, so every existing caller writes rows of exactly the shape
it wrote yesterday and no existing reader meets a field it has never seen. Measured on the
real log first: twenty-eight rows, twenty distinct fields between them, no route on any of
them. A route row's fields are the legacy set plus exactly one, checked in both directions.

The tag repeats what the path already says, on purpose. A path can be mis-wired by a single
argument; a row that ends up in the wrong file still names itself. Nothing splits on it yet —
but a row is written once and read for years, and a reader taught to split later cannot go
back and label the rows written before it existed.

The value is the same one every other artefact of this route already carries, not a shorter
one invented here. A tag that disagreed with the one on the timing and coverage records would
have needed a translation table on its first day.

### What this does not close

Five of the six reporting pieces are still missing, and they all merely omit. The session
report, the broker-statement pull and the profit comparison still do not know this route
exists. That is a stage of its own.

And the difference between closed and live matters here. The two jobs are separate programmes,
started fresh each time, so they already run today's code. The command line that invokes them
is built inside the scheduler process that has been running since one in the morning. Until
that process is replaced, the jobs are still called the old way and would still write the old
file. Nothing was restarted; the constraint forbade it and nothing measured here needed it.

One thing changed in the running system today, unrelated to any of this: the route's book file
now exists, written by the late-afternoon slot, holding nothing. Both safety jobs will
therefore stop returning early and will begin taking the lock and connecting to the broker on
every sweep. Not a defect, but it is new since this morning and it is new load.

### Loose thread, named rather than swept

Four tests from earlier stages now fail, none of them from this work. Three assert that the
route's book file does not exist — it does, since this afternoon, written by the running
system doing its job. The fourth expects one item on the blocking list where there are now
two.

The first three are the same one-line habit this project has already diagnosed twice: absence
standing in for "no test wrote this", which stops being true the moment the system starts
writing the file for real. One of those very tests carries a comment explaining the problem,
three lines above the assertion that still has it, with the fix sitting immediately below.
Left alone here — they belong to their own stages — but they are counted, not ignored.

---

## Stage 5ZH — a window that did everything right, failed by its own judge

*2026-08-25, late evening. The Swing window ran all twenty-three of its slots, evaluated every
one, admitted nothing, and finished well inside its time budget. Its audit failed it anyway,
over a sentence that turned out to be about the judge rather than the evidence. Nothing
restarted, nothing in the runtime tree written or edited.*

### What the complaint actually was

The audit's reason read *"the checkpoint's route is nothing at all"*. Reproduced on demand
before anything was touched, so it was current rather than a leftover from earlier in the day —
and the day's own record dates the moment the symptom changed. Just after lunch the audit said
the checkpoint file did not exist. By evening it said the route was nothing. The file had
appeared in between, one second after the Swing window closed.

### The writer was right, and the day proves which window wrote

Three windows closed on the 25th. Only one of them completed. Only one of them left a
checkpoint, and it left it one second after its last slot — which is exactly the rule: a
checkpoint written from a partial window would record a state nobody watched being reached.
The night window and the late-morning window both closed incomplete, and neither wrote
anything. The guard was never in question after that timeline.

What it wrote is the current format, and it loads cleanly through the route's own reader. Its
instrument slots are empty because the window admitted nothing, and empty is a designed answer
here, not a gap: the route's own code says present-and-empty means *accounted for*, where
absent would mean *nobody thought about it*.

### The judge was reading an older format

The check asked the file for a route and a cut instant sitting at the top level. In the format
the writer uses, the route sits one level down and the day lives on each instrument record —
so the top-level question could only ever come back empty. The sentence *"route is nothing"*
was never a description of the file. It was a description of the reader.

And the check had never been able to pass. It looked healthy only because it had never met a
real checkpoint: before that afternoon the file did not exist, so it failed on absence
instead, for a different reason, and nobody looked further.

### Why no test caught it

Three test suites cover this check. All three build their own checkpoint by hand, in the older
flat shape — a payload the route's own reader **refuses outright**, so nothing in the system
could have produced it and nothing could have consumed it. It existed to agree with the
reader, which is the one thing a fixture must never be built to do. Reader and fixture were
written together; the writer was never asked what it writes.

Every checkpoint in the new tests comes from the writer. One test exists only to keep it that
way: a payload built by hand has to match the writer's output exactly, so the two cannot drift
apart again.

### The same mistake, read a second time

Found while repairing the neighbours: the dashboard's own summary of the checkpoint asked the
same top-level questions and so reported no route and no sleeves for a file that names its
route perfectly well. Fixed in the same pass, because it is one mistake read twice, and the
second copy is the one a person actually looks at.

### Dating a quiet checkpoint

An empty checkpoint carries no date anywhere — the date belongs to an instrument record, and
there are none. So *"is this today's?"* has no answer from the checkpoint alone.

The answer is the book written beside it. Both artefacts come from a single call, atomically,
and the book carries the cut. That was already true of the writer; only the rule had to learn
it. A complete window writes both, and the audit reads both.

When neither can answer, the verdict is that the day could not be established, and it fails.
*I could not check* is not *I checked and it was fine*, and this route has spent five stages
pulling exactly that collapse out of its broker reads. It would have been easy to let a quiet
checkpoint pass for want of any way to date it.

Two more things went with it. The reason a failure carries used to be chosen by matching words
inside the failure's own sentence, so rewording the sentence could silently re-label the
failure; it now carries a code. And two conditions that were being forced into "wrong day" by
a catch-all — a file of the wrong *shape*, and a day that could not be *established* — now say
what they are.

Unchanged on purpose: a checkpoint is only ever asked for after a window that completed, and a
good checkpoint rescues nothing. It can only ever add a failure.

### The result

The Swing window of 2026-08-25 passes. It is the first Track 1 sleeve window ever to pass its
audit. The other three still fail, on their own honest grounds — the machine slept through the
single morning slot and through the first seven of the late-morning window, and the night
window's slots were refused for stale data. None of those was touched, and none of them was
ever a checkpoint problem.

The sentence saying the window was quiet survives on the pass. It never decided anything; it
is the record that a window found nothing, and a window that admitted nothing should say so
rather than pass in silence.

### Named, not fixed

The checkpoint cannot resume anything. The one place that writes it hands over no price
history, so the instrument records come out empty whatever the day did — a day holding a
position overnight would write the same empty file. The artefact is real, correctly scoped,
correctly guarded, and inert: it records that a window completed, and nothing that could
shorten tomorrow's replay.

Not fixed here. Loading five instruments' history at the close is real work inside a
seventy-eight-second budget, and this stage's remit was the judge, not the writer. Harmless
while nothing is held overnight. Not harmless after that.

### Loose threads, counted

Two tests in the suites this stage edited were failing for a reason this project has now
diagnosed four times: absence standing in for *no test wrote this*. One insisted the route's
book file does not exist — the live close writes it, by design, in the same call as the
checkpoint. The other insisted no file in the real evidence tree carries today's date — forty
of them do, written by the system doing its job. Both now ask whether anything was written
*during the test run*, which is the thing actually being guarded and cannot be satisfied by
the system working correctly.

Three more failures in suites this stage did not touch have the same shape and were left
alone, measured rather than waved at: one is the same book file, and two expect a blocker list
from before the shadow-evidence gate existed.

---

## Stage 5ZI — everything still standing between here and a paper order

*2026-08-25, last thing at night. A map, not a change. Nothing was implemented, nothing
restarted, no broker contacted, nothing in the runtime tree written or edited.*

Two answers up front. The next shadow window is **ready** — nothing on this map stands in its
way except the machine going to sleep. Paper is **not ready**, and for six reasons rather than
a general sense of unfinishedness.

### Where the route actually stands tonight

Two days of evidence exist, and both are recorded as failures. Re-judged with tonight's
corrected reader, the afternoon Swing window of the 25th passes — twenty-three slots of
twenty-three, every one evaluated, nothing admitted, comfortably inside its time budget. The
record on disk still says otherwise, because the judging ran before the fix and the readiness
gate reads records rather than re-judging. Correcting that record is an operator's call and
would mean writing into the evidence tree, so this stage left it alone.

The other three windows failed for one reason and it is not in the code. At a quarter past
eleven in the morning the scheduler woke and reported sixteen jobs missed in a single burst,
one of them by nearly three hours. The machine had been asleep. The morning sleeve has exactly
one slot and it was inside that sleep, so it was never observed at all. The late-morning sleeve
lost seven of its twenty-four. Only the night sleeve failed for a reason of its own — its slots
ran and were refused for stale data, which is the single genuine data problem of the day.

The route's own book file now exists, holding nothing, written when the afternoon window
closed. That has a measurable consequence the same log records: before it existed the safety
sweeps finished in a second, because they returned early with no book to read. After it
existed they take thirteen, because they now take the lock and open a broker connection every
time. That is the safety net doing exactly what it was built to do the moment there is
something to watch — but it is new behaviour that began today, thirteen times a day.

### The order path exists and is connected to nothing

The state machine, the journal, the order builder, the broker read side and the call-site
rehearsal are all built and tested. In the running system the route holds a broker that raises
if anyone asks it to send an order.

What the map makes plain is how much of the *lifecycle* is still missing rather than merely
unwired. Of the four things an executor must be able to do — open, close, protect, switch —
only opening exists. Closing at the five-day limit and placing the protective stop are both
done today by the safety jobs, in a different process on a different schedule, and neither
leaves a line in the order journal. A closing decision made by the strategy itself has no path
to a broker at all. And the piece that would swap one position for another on the same symbol
is imported by nothing, while containing two order calls and no journal.

### The widest gap is the stop

The strategy works out where the stop belongs. From there it goes nowhere near the order path:
neither the order nor the journal line has anywhere to record it. The stop is placed later, by
the safety sweep, and nothing anywhere holds both the price that was intended and the price
that was placed.

So there is nothing to compare a live working stop against. Everything that would depend on
that comparison — side, size, price, whether a bracket behaves, whether an abandoned stop is
still sitting on the book — inherits the same emptiness. This is not a theoretical worry: an
abandoned stop left behind by a close in August, when it filled, opened a position in the
opposite direction. That incident is the reason both routes must share one connection id, and
it is the reason a stop with no record is an accounting hole rather than untidiness.

### Two things that look worse than they are, and one that looks better

The daily regime check is weaker than the previous stage recorded, and the correction is worth
having exactly right. It is not that every path returns the same number — a genuine drift does
return a count. It is that three separate *"I could not check"* paths return the same value as
*"I checked and it was fine"*, and that the one place calling it throws the answer away
entirely. A drift of fifty labels would log a warning nobody reads, return a number nobody
consumes, and exit successfully; and the scheduler keeps only errors from a child that exited
successfully, so the warning does not reach the journal either. Invisible from end to end.

The launcher's duplicate-scheduler guard looked like the same class of fault and is **not**. It
does throw away the honest third answer one layer below — but both ways an operator can reach
it check that answer first and refuse. The weak guard is a redundant second check sitting
behind a good first one. Recorded as a trap for whoever writes the next caller, not as a live
fault, because the alternative was reporting a defect that cannot happen.

And two thirds of the per-rule detail an operator would want is recorded as *"the rule ran
inside the detector and the detector does not hand back its answer"*. That is the honest label
and the right one — the alternative would put a second copy of the strategy behind the
dashboard, and then *"not measured"* and *"measured and fine"* would stop being different
things. It blocks nobody's plumbing. It blocks the day someone asks why the route declined to
trade.

### The order of what comes next

First, make last night's safety-reporting fix real. It is the only item already finished in
code; it needs a restart that has to happen anyway; and until it lands the running system is
still pointed at the wrong destination. It costs a minute, not a stage.

Second, give the checkpoint something worth resuming from. Tonight's fix made the judge
correct; it did not make the artefact useful. The measured budget says there is room — the
expensive sleeve finishes in seventy-nine seconds against a three-hundred-second ceiling, and
the checkpoint is written once at the close rather than on every slot — but whether the closing
slot can reuse what it already has in memory or must fetch it again is **not measured**, and
that measurement should come before the design rather than after.

Third, let the daily regime check fail. Three answers, not two, and the third one has to reach
the outside world.

After that the reporting and the execution call site, in that order but with one correction to
the obvious plan: a profit reader over the order journal is reading a journal nothing writes
yet. Either accept that it ships tested but unexercised, or have it read what the rehearsal
produces. The latter is cheaper and it is what this map recommends.

Last, and only once a broker is actually involved: everything about a live stop, a partial
fill, and an order left in flight across a restart. Those cannot be finished in shadow, and
pretending otherwise would produce tests that pass without proving anything.

### One thing that has to be decided by a person, and comes before all of it

While one login serves both routes, the strongest statement anyone can make is that the
broker's net position equals this route's plus the other's. That detects a disagreement and
cannot say whose it is — and two opposite mistakes, one on each side, cancel out and read as
agreement. A dedicated account, or a demonstrably empty legacy book, makes the comparison
exact. Until then the paper evidence proves less than it looks like it proves, which defeats
the purpose of gathering it.

---

## Stage 5ZJ — the fix stops being true only on paper

*2026-08-26, just after midnight New York time. The scheduler and the dashboard service were
both replaced, on purpose. One file was created as a direct consequence and it is named below.
No orders, no confirmation file, no change to any rule, cap or identity.*

### Why a restart was the whole stage

The sixth per-route file was finished the previous evening: its own trade log, its own tag, both
entry points teaching, every test green. And none of it was reaching the running system, because
the command line that launches those jobs is assembled inside the scheduler process — and that
process had been running since one in the morning, hours before the change was written.

The evidence for that was not an inference. The last safety launch before the restart is in the
log with its arguments spelled out, and neither new argument is there.

### Choosing the moment

Restarted at three minutes past midnight: no window open, no slot running, seventeen minutes to
the next sweep, sixty-seven to the night window. That is the widest gap the schedule offers, and
it was chosen rather than taken.

The command needed one addition — the flag that tells it not to ask for confirmation — because
this session has no keyboard to answer with. That is the flag's stated purpose and it does not
widen what the command does.

### One restart, not two

Replacing the scheduler replaces the dashboard service as well. The second restart in the plan
would have thrown away a process seconds old and started an identical one, so it was skipped —
and skipped on evidence, not on reasoning. The old service had been started between two of the
recent fixes: it already carried the schedule-health repair and could not carry the checkpoint
one. After the restart, the live interface answers correctly on both, and on the two job-view
additions besides.

### What the new process says about itself

A hundred and forty-six jobs added, forty-five removed, a hundred and one remaining — the same
number the source produces when constructed offline, arrived at independently. Its own banner
names seventy shadow slots, eleven safety jobs watching the route's book, five read-only audits,
and forty-five legacy strategy jobs deliberately not scheduled. The legacy drain sweeps are still
there, which is the point of calling them a drain.

### The proof, twelve minutes later

The sweep at twenty past midnight fired both routes in the same second, which makes the
comparison exact rather than approximate. The route's job went out with its own book, its own
kill switch, its own lock, its own connection id, **its own trade log and its own route tag**.
The legacy job went out beside it with the legacy book and neither new argument. Both finished
cleanly.

That is the thing this stage existed to produce: not a source reading and not a rehearsal, but
the running scheduler launching the real job with the flags on it.

### What the sweep actually wrote, said plainly

The route's trade log now exists and is **empty** — zero bytes, zero rows. It exists because the
job proves its destination is writable before it does anything else, and it is empty because
there was nothing to close. The timing shows the ordering: launched on the minute, file created
a second later, job finished twelve seconds after that having connected to the broker in between.
The check runs first, exactly as it was built to.

The legacy log was not touched: same size, same timestamp from eleven days ago. Both lock files
were handed back.

What has **not** been shown is that a real closing trade lands in the new file wearing its route
tag. That needs the route to hold a position and something to close it, and no part of this stage
pretends otherwise. An empty file is proof of a destination, not of a delivery.

### One test repaired, for a reason that keeps recurring

A test in the safety-wiring suite — the very suite this stage brings to life — insisted the
route's book file does not exist. It does, since the afternoon close of the previous day, written
by the system doing its job. Same habit, fifth occurrence: absence standing in for *no test wrote
this*. Repaired the same way as its neighbours, by asking whether anything was written during the
run instead.

### What is left

Six things, one fewer than yesterday. Two belong to a person rather than to code: the machine
must stop going to sleep, and somebody must decide whether this route gets its own account or
whether the old one is retired first. Four belong to the next stages: a checkpoint that can
actually resume, a regime check that can fail, reporting that knows this route exists, and a
stop that gets written down when it is planned rather than only when it is placed.

The evidence count has not moved and will not until the sleeping stops. That, more than anything
on the code list, is what stands between here and a paper order.

---

## Stage 5ZK — the checkpoint learns to hold something

*2026-08-26, the small hours. Nothing restarted, nothing in the runtime tree written or edited,
no rule or setting that decides a trade touched. The night window opened four minutes after this
was finished and its close will be the first to use the new writer.*

### The thing that was wrong

The previous stage taught the judge to read the checkpoint correctly. It did not make the
checkpoint worth reading. The one place that writes it hands over no price history, so the
instrument records came out empty whatever the day had done — a day holding a position overnight
would have written the same empty file, and every restart would replay from the beginning.

### The obvious fix does not work, and the store says why

Load the price history at the close and stamp it with today's date. Measured, that produces a
checkpoint nothing will ever accept.

The daily top-up of the price store runs at a quarter to two in the afternoon. So when a window
closes at five to four, the store holds *today* only up to a quarter to two, while *yesterday*
runs to midnight. The next day's top-up fills in today's afternoon — and those bars fall inside
the span a stamp dated today would cover. Simulated on both instrument families: a stamp through
the newest stored day does not survive the next top-up; a stamp through the day before it does.

So a record stamped with the closing day is refused by every later restart, and refused with a
code that reads like the data has been corrupted. The honest stamp is the last day the store has
finished with — which is derived from the data itself, not from a calendar, so on a day the
top-up has already run the same rule still names a day that is complete.

The record then says something true and useful: *as of the close of that day the engine held
this, and here is the history that produced it*. The restart resumes there and re-runs the days
after it.

### Something I claimed, that the data corrected

I wrote — in the code and in a test — that the price history already sitting in the closing
slot's memory was the wrong kind, because today's live bars change the stamp. The test written
to prove that went green instead of red, and it was right to.

The claim holds for a stamp dated today and fails for one dated the last complete day, where
the extra bars fall outside the span and both versions stamp identically. **Reusing what was
already in memory would have worked.** Reloading is a choice, and the reasons are ordinary
rather than dramatic: the store is what a restart reads, so stamping it is the agreement itself
rather than something equal to it by argument; the closing slot only holds its own sleeve's
instruments, so reuse could never cover all five from one place; and six seconds against three
and a half minutes of headroom buys a simpler seam. Both the comment and the test now say that,
and the test goes red the day the join starts rewriting history it currently leaves alone.

### The cost, since that was the open question

Six seconds for the whole write, measured three times on the live store — five instruments of
two to three and a half million bars each. Against a five-minute ceiling and a closing sleeve
that takes seventy-nine seconds, that is two per cent of the budget, and it falls on one slot
per sleeve rather than on every slot.

### The case nobody has reached yet

If the book says something is held and the checkpoint records nothing to resume it from, a
restart would come back flat against a book that is not. That is the failure the whole identity
machinery exists to prevent, and it now fails closed and says so by name. So does the mirror —
records claiming a position while the book says empty — because the two are written in one
breath and cannot honestly differ.

That guard matters more than it looks, because the position half of the checkpoint is **built
and tested but cannot yet happen**. The route builds a fresh book every slot and never carries
one across; today's book file is a correctly-shaped *nothing is held* marker, accurate only
because nothing is held. Giving the route a book that survives the day is position work, not
checkpoint work, and it belongs to the stage after next.

### A rule from last night, replaced

Last night's rule said records must be dated the day being judged. This morning's measurement
says a correct record is dated the day before — so that rule would have failed every checkpoint
the writer can actually produce, starting with the first. It is replaced with something simpler:
the book beside the checkpoint proves the day, in every case, because the two are written
together; the records are asked only that their history is not from the future and not stale.

Re-judged against the live evidence, nothing moved. The quiet checkpoint still passes, the
afternoon window of the previous day still passes, and the three sleeves that failed still fail
for the reasons they failed before — a sleeping machine and a stale feed.

### Loose thread, counted rather than swept

Six more tests were failing on the habit this document has now recorded five times: insisting a
file does not exist when the running system writes it every day. They were in the three suites
that exercise the very function this stage changed, so they were repaired the same way as their
predecessors — ask whether anything was written *during the run*.

Two others were left: a job count pinned before a job was added, and a blocker list pinned
before a gate was. And one surfaced that belongs elsewhere: a diagnostics helper builds engine
settings without naming which fill rule it means. It decides nothing — it only reads thresholds
to print them — but if the default ever drifted, the journal would report a number the decision
never used. That belongs with the rule-exposure work.

### What is left

Five things. Two are a person's: the machine must stop sleeping, and the account question needs
an answer. Three are code: a regime check that can fail, reporting that knows this route exists,
and a stop that is written down when it is planned rather than only when it is placed.

Next is the regime check, and it is the smallest of them. Three answers instead of two, the
uncertain one failing closed, and the result reaching the outside world — because today a drift
would be logged as a warning nobody reads, returned as a number nobody consumes, by a job that
exits successfully.

---

## Stage 5ZL — the check that could not report a failure

*2026-08-26, before dawn. Nothing restarted. One production file was changed — by a test of
mine, not by the work — and that is the first thing below rather than a footnote.*

### A test of mine overwrote a production file

The record of which days passed their afternoon pre-flight went from seven days of history to
a single line asserting that **today** had passed. Today's pre-flight has not run; it fires at
a quarter to two this afternoon. So the file briefly claimed a clearance for a day nothing had
checked.

The cause was mine and it is worth naming exactly, because it is a trap anyone would fall into:
my test replaced the thing that launches child processes, and then fired a job whose state
saving happens in the *parent*. Replacing the launcher does not make a job body safe.

It was caught by the same suite's own "did this write anything real" check — the only reason
anyone noticed. The helper now redirects every state path into a temporary directory first, and
the incident is written into the test's own docstring so the next person meets it before they
repeat it.

The damage is bounded and self-repairing: the running scheduler holds the true seven days in
memory, reads that file only when it starts, and will write them back correctly this afternoon.
The exposure is a restart before then. I tried to restore the file and was refused — correctly,
since it is live state and the standing rule forbids editing it — so the restoration is written
out in the stage report for a person to run or decline. It is reconstructed from the scheduler's
own logs rather than guessed: every day, its outcome, and the retention rule all came from the
record.

### What was actually wrong with the check

Which sleeve is allowed to trade is decided from regime labels, and the check that those labels
have not moved **could not report a failure**.

It returned a count of changed dates, and returned zero from five different places that had
compared nothing at all: the engine could not be imported, either file failed to load, the
labeller raised, there were no overlapping dates, or there was no snapshot to compare against.
Zero is also what a clean run returns. So *"I could not check"* and *"I checked and it was
fine"* were the same number.

The fourth of those deserves its own sentence. With nothing to compare, the old code took the
cheerful branch and printed **"Regime labels unchanged (0 dates verified) — HMM stable"**. A
statement about nothing, phrased as reassurance.

And the answer went nowhere anyway. The only caller threw it away. The program's entry point
called its main function bare, so even a returned value never reached the exit code. The
scheduler keeps only errors from a child that exited cleanly, and the drift line was a warning.
Invisible from one end to the other.

### Three answers, and a place to put them

There are now three: the labels were compared and none moved; the labels moved; the labels
could not be verified. Ten reasons sit under those three, and the result object refuses to be
built with a reason belonging to a different answer — a reason that can mean two things is a
reason nobody can act on.

The answer is written to a dated, append-only record beside the other evidence, because a
verification whose answer exists only in a log line is a verification nobody can gate on. No
record at all reads as *could not verify*, never as *fine*; so does an unreadable one, and so
does one more than a week old.

The module itself decides nothing. It reports, and each caller states its own consequence out
loud — because the two callers have very different stakes.

### Where it bites, and where it deliberately does not

The paper gate now refuses to open unless the answer is a clean comparison. Both other answers
hold it, and they are reported separately.

The post-close refresh — which runs after everything that day has finished and gates nothing —
now exits with a failure on either bad answer, so it shows as a failed job. Its failure message
tells the three cases apart: the labels moved, the labels could not be checked, or the series
is simply still short. Three different things to do about it.

The afternoon pre-flight deliberately does **not**. It gates the whole trading day, and a
verification that could not run must not skip every slot. That exclusion is written into the
flag's help text, the scheduler comment and the gate's own record, so nobody later mistakes it
for an oversight.

Nothing about the freshness rule changed, and a test asserts the freshness code does not so
much as import the new module.

What the gate says today is not comfortable and it is honest: nothing has ever verified these
labels in a way anyone can read, so the answer is *could not verify*, and the paper gate is
held shut by it. That is a third lock on a door that already had two.

### A second false reassurance, found on the way

While reading the freshness path I compared the post-close job's own log line from the previous
evening — *"the daily series now covers the twenty-fifth"* — against the series, which ends on
the twenty-fourth. The job prints that sentence whenever it exits cleanly, having checked
nothing. The price source's daily figure is not always final at twenty past four, so the run
genuinely succeeded and genuinely added nothing.

The same defect as the main one, one job over. It now reads the series and either confirms the
coverage or says the close was not available yet, and adds what that means: the next day's
sessions ask for the last trading day *before* them, so it only matters if it is still true
tomorrow. No harm came of it — last night's slots all ran and none refused.

### Loose threads

Two tests written a day earlier as tripwires fired and were inverted: one carried *"if this
ever raises, the finding is closed and the report needs updating"*, and it did. Two gate tests
were updated, because a control that satisfies only the gates existing the day it was written
stops being a control. One check was narrowed after going red for an honest reason — it asked
whether anything at all had been written under the evidence tree during the run, which is only
a statement about tests when nothing else is running, and the night window was open and writing.

Three failures in a freshness suite are not from this work — the freshness code was untouched
and a passing test proves it does not reach the new module — but I have not established what
they are, and say so rather than guessing.

### What is left

Four things. Two belong to a person: the machine must stop sleeping, and the account question
needs an answer. Two are code: reporting that knows this route exists, and a stop that is
written down when it is planned rather than only when it is placed. The new gate is not work —
it opens by itself the first time the evening job records a clean comparison.

---

## Stage 5ZM — the route learns to account for itself

*2026-08-26, small hours. Nothing restarted, nothing in the runtime tree written or edited, no
money figure invented. The operator's repair of the pre-flight record was verified before
anything else, and a test now holds it.*

### Two different ways to get this wrong

A report for this route that quietly showed the old route's book would be worse than an empty
one: an empty one is obviously empty, and a borrowed one looks like an answer. And a row of
this route's landing in the old route's ledger enters the old route's quality and profit gates
as though it belonged there.

Those are different failures and they needed different fixes.

### Nine readers, five kinds

Everything that reads a ledger or a book was enumerated from the code rather than from memory.
Five of them are about the old route by design and were left exactly alone — a reader whose
subject is that book should keep reading that book. One already knew about this route. Two
aggregate *the whole ledger*, and those are the two that had to learn the difference: the
evidence reader the order gate consults, and the profit comparison itself.

One is genuinely missing and stays missing, deliberately: the daily session report. Giving this
route a section of it before the route has anything to report would be a page that says
nothing.

And one cannot be finished at all yet, for a reason measured rather than assumed — see below.

### Three states, because two is not enough

The new reader answers *not produced*, *empty*, or *available*. A ledger that exists and holds
nothing means the route swept and closed nothing. A missing one means no sweep has ever got as
far as proving it could write there. Those are different facts and they never print the same.
The book does the same: missing reports *no answer*, not *zero*.

It never reads the old route's files, and that is asserted rather than promised — three ways.
By reading the code's string literals, so a sentence in a comment is not mistaken for a file
being opened. By **running the whole report with every file-opening call watched** and checking
what it actually touched, which is the only version that survives a path assembled from pieces.
And by saying so in its own output.

Every row must name this route. One that does not is invalid and is counted separately, never
folded into a total — because a row in the right file that does not name its route is either
the old route's, hand-edited, or written by something nobody has taught.

### Keeping the two ledgers apart, in the direction that matters

Both aggregating readers now skip rows tagged with another route, and — this is the part worth
saying — they **report how many they skipped**. Zero is the expected number and it is the one to
watch. A filter whose effect nobody can see is a filter nobody can check.

The design decision underneath is the one that would have been easy to get backwards. The
filter removes *foreign* rows rather than keeping *ours*. Every row written before the route
split carries no tag at all, so "keep only rows tagged as ours" would have silently emptied both
reports of their entire history — and it would have looked exactly like a working filter.

### What still cannot be known, and why

There is no broker-confirmed profit for this route, for two separate reasons that need
different things to change.

The first closes by itself the day an order fills: none has ever been placed.

The second does not. The newest broker statement has thirty-seven columns and not one of them
names a route, a strategy, an order reference or a connection — only the account, and there is
one account. So even after fills exist, **a statement cannot say which route made them** while
both share a login. That is a property of the statement format, measured against the real file
and pinned by a test so the claim decays if the format ever changes. It is a second and sharper
reason the account question has to be answered before paper rather than alongside it.

### The one PASS available, and its qualifier

The position comparison reports agreement — the book holds nothing and no order has been
recorded, so the two agree, and both are empty for the same reason. Carried in the same breath:
agreement *between two files*, and while one login serves both routes a broker position cannot
be attributed to either. The caveat travels inside the same payload so the word cannot be quoted
without it.

Five outcomes exist and *could not tell* is never one of the agreeing ones. A book holding a
position with nothing recorded about it is named for what it is — a position nobody can account
for.

### Loose thread, split rather than deleted

A test written days ago pinned that three reports knew nothing about this route. Two still do
and stay pinned. The third came off the list, and the reason is a distinction worth keeping:
excluding another route's rows is not the same as reading that route's files. It still reads
only the old book and the old ledger; it merely knows which rows are not its own. A new test
draws exactly that line.

### What is left

Three things. Two belong to a person: the machine must stop sleeping, and the account question
now has two reasons behind it instead of one. The third is the stop — neither the order nor the
record of it has anywhere to hold the price that was planned, so there is nothing for a live
protective order to be compared against. The position comparison above ends at *could not tell*
for the same underlying reason: the route still has no book it carries from one day into the
next.

Two other gates will open on their own — one as clean days accumulate, one the first time the
evening job records a clean label comparison.

---

## Stage 5ZN — the stop gets written down

*2026-08-26, before dawn. Nothing restarted, no runtime file changed, no broker object built
anywhere, no order sent or made sendable.*

### One thing happened between stages, and it is worth recording

The night window closed at five to three and wrote the first checkpoint with real content in
it — five instruments, each with the fingerprint of the history that produced its state. It had
only ever written an empty one. The window passed its audit: the second in the route's history
to do so, and the first whose checkpoint anything could resume from.

### What was missing

The strategy decides where the stop belongs. That decision survives the whole admission path —
and then meets an order object with nowhere to put it, and a journal line with nowhere either.

So the planned stop reached the edge of the order path and was dropped. The protective stop was
placed afterwards by the safety sweep, in a different process on a different schedule, and
nothing anywhere held both the price that was intended and the price that was placed. Side,
size, price, whether a bracket behaves, whether an abandoned stop is still sitting on the
book — every one of those needs two numbers, and there was only ever one.

An abandoned stop left behind by a close in August filled and opened a position the opposite
way. That is the reason a stop with no record is an accounting hole rather than untidiness.

### Carried, never recomputed

The plan now travels: the instrument, the side, the size, the price, the rule it came from, the
distance, the session, the slot, and the settings identity — everything a live protective order
will one day have to be checked against.

The price is **copied**. There is no arithmetic in that file beyond the subtraction that gives
the distance, and a test proves it by reading the module's own operators. A second
implementation beside the one that trades is how the planned stop and the meant stop quietly
become two different numbers — and the plan is the one that would look right.

Six conditions refuse, each named. The one worth repeating: a long whose stop sits above its
entry is not a stop, it is a target, and it would trigger the instant it reached a broker.
Caught before it gets there.

An entry with no plan cannot be considered sendable. Nor can one whose plan names a different
instrument, or covers fewer contracts than the order — a partly protected position is not a
protected one.

### Three verbs that describe and refuse to perform

Closing, protecting and swapping all exist now. All three run every refusal, write down what
they intend, and return something that plainly says *nothing was sent*. The step that would
actually send is not built, and that asymmetry is the stage's point rather than an omission: a
method that could send is a method somebody can call.

Every refusal happens before anything is written, so a refused operation leaves no trace a
later reader could mistake for an attempt.

The swap matters more than its size. The module that would have done it is imported by nothing
and calls the broker twice with no record at all — so if it were ever wired, two orders would
leave one line between them, or none. It now produces two, recorded separately, with the
closing leg first, because a swap that opened before it closed would double the exposure on
that symbol for as long as the gap lasted.

### A fault found by standing on it

The order path's idea of where the route's book lives pointed at a place the book has never
been. Every other part of the system uses the repository root, and that is where it is written.

Not cosmetic. A missing book reads as an empty one — correct for a route that has held nothing
— so that setting would have made the restart check compare an always-empty book against the
broker and conclude the route was flat whatever it held. That is *resume flat against a book
that is not*, in the one piece built to prevent exactly that. It never fired because nothing
imports it.

It is corrected, and now read from the route's own table rather than restated, so the two
cannot drift apart again. A test had been green because of it — asserting the book was absent,
and passing by asserting something true of a file nobody writes. It now says what it meant.

### The book survives the day

Closing a window used to write a book claiming no positions, whatever the previous one said.
Harmless while nothing is held; exactly wrong the day something is. The close now reads the
existing book and carries it forward, restamped.

And when the book cannot be read, the write is **refused** and the file is left alone. *I could
not read what I hold*, answered as *I hold nothing*, is the shape that erases a real position —
and a window close that did it would be unrecoverable.

Intending a close does not move the book. Only a confirmed fill can, and there has never been
one.

### A pin nearly weakened, and not

Six tests across five suites assert that nothing which runs imports the order path. That is not
bookkeeping — it is half the argument that there is no route from the scheduler to a broker.

The first version of a reporting field imported the order path to read a property off it, and
broke all six. The easy fix was to loosen the six. Instead the report now states the list and a
test compares that statement against the real thing, where imports cost nothing. The import
graph of the running system is unchanged, the claim is still checked, and a panel field did not
buy the first door into the order path.

### What only a broker can settle

One thing, and it is stated in those words wherever it appears: that a broker actually holds
the stop that was planned. Price, size, side, whether it survives a close, whether an abandoned
one gets left behind. All of it needs an order to exist first, and none does. *Planned stop
ready* and *broker stop verified* are separate facts and are never merged.

### What is left

Five things, and not one of them is a question about how the route should work. A machine that
must stop going to sleep. An account decision that now has two reasons behind it. Five clean
days, which is time. One clean label comparison, which is also time. And a broker.

There is a wire still to run — the step that would let any of this reach an exchange — and it
belongs after the gates open rather than before, because the day it is built is the day the
distance between the scheduler and a broker stops being structural.

---

## Stage 5ZO — proving a slot looked, not just that it decided

*2026-08-26, before dawn. I restarted nothing and wrote nothing into the evidence tree. The
operator restarted both services partway through, which is recorded below because a process
table that disagrees with what you did is a reason to stop and check.*

### The gap was in the evidence, not in the code

The night window passed. Twenty-two slots, every one of them evaluated, nothing admitted, well
inside its time budget. And the human-readable record for its last slot said its bar timestamps
were empty and its data time was nothing at all.

So the ledger proved the slot **decided**, and nothing proved **what it looked at**. Those are
different claims, and on a route that has never traded they are impossible to tell apart: a
slot that fetched nothing and found no trade leaves the same line as one that pulled a thousand
bars and found no trade.

Half of it was already provable. The record carries the fingerprint of the stored history it
read. What was missing was the live half — the bars fetched today, and what was done with them.

### Written down, never recalculated

Every number in the new record already existed. The join that builds a slot's frame keeps count
as it goes: which provider answered, how many bars it offered, how many survived, how many
overlapping timestamps were checked against stored history, what the splice decided, where the
stored history ended and where the finished frame ends.

The new writer reads those and writes them down. It computes no feature, calls no detector,
touches no rule — a diagnostics path that recalculated anything would be a second version of
the strategy sitting beside the one that trades, and the two would disagree on exactly the day
it mattered. That is asserted structurally rather than promised.

Three identities are kept apart in every row, because they have already drifted once: what the
runner calls the instrument, what its history is stored under, and what its orders would go to.
A record printing one of the three and calling it *the symbol* is how somebody later compares
the wrong two.

### One field is deliberately blank

Nothing anywhere records whether the provider's last bar was still forming when it was handed
over. The fetch only keeps bars at or before the moment it was taken, which is a different
promise. So that field is written as an explicit unknown with the reason beside it — never left
out, never guessed. It is a real remaining gap and it is named as one.

### No prices

The record proves a fetch happened, how big it was, over what span, and what the join did with
it. It does not carry the bars. A record that did would grow with the market and would put
price data into a stream whose only job is provenance. A test walks the whole payload and fails
on anything list-shaped enough to be bar data, rather than trusting a sentence saying there is
none.

### Classify the past, do not accuse it

A day with no such records at all is a day whose slots ran under an earlier version of the
writer. That is a fact about the software, not about the window, and it is recorded as exactly
that. Once the stream exists for a day, every slot in it that decided is expected to appear,
and a missing one raises a warning.

A warning, not a failure, and the reasoning is short: the ledger already proves the slot ran
and decided; the new record proves what it saw. A missing one weakens the evidence without
contradicting it, and making it fatal would fail every window recorded before this existed —
which says nothing about those windows. It stops being tolerable the day an order is sent on a
decision nobody can show the data for, and the readiness gate is where that belongs.

Re-judged against the real window: still a pass, twenty-two decided slots, no stream, no
accusation and no downgrade.

### One line on the panel

Inside the block that already carries the runtime facts, not a new heading. Three shapes,
because an operator would act differently on each: what was observed, that no record exists for
that version of the slot, or that the data was refused and why. No variable names, no raw
values, and short enough not to wrap on a phone.

### The restart I did not do

Both services changed process partway through the stage. I checked rather than assumed, and it
was the operator. The restart was clean — same mode, same job inventory, and the seven-day
pre-flight record survived it intact.

It also answered the liveness question, and in the opposite direction from what I first
assumed: the restart came *after* the changes, so the running system picked them all up. Checked
against the live interface rather than reasoned about — the regime block, the reporting block
and the new data line are all being served, and the evening verification now runs in its strict
form. The slot writer needs no restart at all, since slots are separate programmes started
fresh, so the next window will produce real records.

### What is left

Five things, and not one of them is a question about how the route should work. A machine that
must stop going to sleep. An account decision. Five clean days and one clean label comparison,
both of which are time. And a broker.

Plus the blank field above, which is small: closing it means asking the provider layer a
question it does not currently answer.

---

## Stage 5ZP — three panels that looked like three different pages

*2026-08-26, early morning. Nothing restarted, nothing in the evidence tree written, no rule,
threshold or decision touched — and nothing recalculated anywhere near the strategy.*

### One property, not a redesign

The signal chip had three faults and they were smaller than they looked.

Its text read *"Signal NO SIGNAL"* — the word was already implied by where the chip sits, next
to RUNNER and COMPLETED, so doubling it made the longest chip on the row the least useful. It
was a bordered pill of its own invention while every other chip on the page shares one style,
so it read as a different *kind* of thing. And a single line of styling told it to span the
whole badge row, which is the entire reason it appeared underneath rather than beside — and the
entire reason every route row was two lines tall whether or not anything had happened.

It is now the same chip as its neighbours, carrying only its label, in the same group. Measured
in a browser: a route row and a row with no chip at all are the same height to within two
pixels.

### The two detail sections were never inside the panel

They were being pasted on after it — siblings of the structured block rather than part of it,
which is exactly why they rendered as loose text underneath the evidence. They now sit inside
it, after the evidence and resolution, in the same style the impact and action blocks already
use.

That is asserted by counting how many such sections sit *outside* the panel and requiring
zero — a question a text search cannot answer, because the words are identical either way.

### A sentence that named a cause which did not act

The panel had been saying, on the night window that passed: *"First rule that failed: Freshness
check."* Twenty-two times, on twenty-two slots that produced no candidate at all.

Freshness stopped nothing. Nothing reached admission for it to stop. A rule that guards
admission has nothing to say about a slot that admitted nothing, and naming it as the first
failure points an operator at a gate that was never in the path.

It now says what actually happened — the rule was measured, it would not have allowed
admission, and nothing reached it. The correction is kept narrow on purpose: a rule that really
did block a candidate is still named, and a *setup* rule that failed with no candidate is still
named too, because there the failed rule is precisely why no candidate exists.

### Nothing new was exposed, and that is the finding

The brief asked to surface rule values *already computed* during detection. I looked, and there
are none: two thirds of the checks still come back unmeasured because the detectors do not
return what they worked out. The only way to put a number on that panel would be to calculate
it there — a second version of the strategy sitting beside the one that trades, which would
disagree on exactly the day it mattered, and the copy on the screen would be the one that
looked right.

So the panel keeps its one honest sentence, and the work is recorded where it belongs: in the
detectors, not the dashboard.

### The summary panel

Label and value had nothing separating them, so the route name and its label ran together as one
string. The panel now uses the same shape as the schedule facts beside it — a small label above,
the value beneath, room to wrap.

The blocker list was the one value that could grow, and it now reads in plain language rather
than in identifiers, with the exact identifier one hover away. Nothing is hidden; nothing has to
be decoded at a glance. Three gates fit without the panel scrolling sideways, checked rather
than eyeballed, at three widths with the panel open.

### A test that failed for the right reason

Sixteen tests in two earlier stages pinned the old chip, and they were updated rather than
deleted — one of them ended up stronger, asserting that the chip *is* the shared component
rather than that it had borrowed three properties from it.

One failed in a way worth writing down. A test checks that the page never authors the words an
operator reads — and it went red because a comment I had just written quoted the old label in
order to explain why it was gone. A word-search over prose, on a test built to catch a different
kind of word-search. It now reads the code and ignores the commentary.

### What is live

The page's script and styling are served fresh on reload, so everything visual is already
current without restarting anything. The one change that is not visual — the corrected sentence
— lives in a module the service loads at startup, so the running service still composes the old
one until it is restarted.

### What is left

The same five things, none of them touched here. And two smaller items are now recorded rather
than left as open questions: the detectors do not hand back what they measured, and nothing
records whether the data provider's last bar was still forming. Neither blocks anything. Both
are about being able to explain, and both are named where someone can pick them up.

---

## 5ZP follow-up — the part of the panel the stage never measured

*2026-08-26, later the same morning. Two stylesheets, nothing else. Nothing restarted, no
runtime evidence touched, no gate moved.*

The previous stage proved that the two sections sit inside the panel, and that the summary
facts stack label above value. Both were true. Neither says anything about how the content
inside them is painted — and the operator looked at the screen and asked. Measured in a
browser, three things were wrong, and one sentence in the previous write-up was wrong as
written: the summary panel does **not** use "the same shape as the facts beside it". It
borrowed the card and none of the cell.

### Every line in the panel was dressed as a journal row

The stylesheet has one rule that makes a journal row look like a journal row: a coloured
rail down its left edge, a hairline under it, a bullet dot, and a small negative margin so
the row can sit flush against the card. That rule is written to match any list item **inside
the journal**, and an expanded panel is inside the journal.

So a seven-line Operational block was drawing seven rails, seven hairlines and seven dots,
and every line was sitting ten pixels outside the panel's own text column — measurably out
of step with its own heading directly above it. The lines were also the only body text in
the whole card printed in the muted grey at a heavier weight, so the one section that answers
"did this slot run correctly" read like a footnote to the sections around it.

Both are fixed at the panel rather than at each list, so the next list added inside a panel
does not have to remember. And the panel's body text now has a single owner, so the lines and
the paragraphs beside them cannot drift apart again. Measured after: an Operational line and
the resolution paragraph share the same box, the same font and the same colour, exactly.

### The summary panel had borrowed the card and none of the cell

It carries the fact grid's container class, so it gets the card — background, edge, rounded
corner. Its cells carry a different class from the ones the design dresses, so it got none of
the cell: no inset at all, which is why the text sat against the card edge, and no divider,
which is why twelve separate facts read as one block of text.

The inset is now one value declared on the grid and read by both panels, so raising it in one
place moves both instead of leaving this one behind — which is precisely how they came apart.
The dividers are drawn by each cell casting a hairline on its own right and bottom edge,
which stays correct at one, two or four columns without anything having to count cells.

They were first drawn as a one-pixel gap over a hairline ground, and that was wrong for a
reason worth keeping: there are twelve facts in a four-column grid plus one, so the last row
is part empty — and a gap paints the space between cells as well as the space where there are
none. The empty remainder came out as a visible lighter block three cells wide. Nothing in
the suite caught it; looking at the rendered panel did. There is now a test that asserts the
last row really is part empty before checking that the empty part is indistinguishable from a
cell — an assertion that would quietly stop meaning anything if the fact count ever became a
multiple of the column count, so it says so instead. And the labels, which were the
only labels on the page set in the monospace face at heavy weight, now speak the same language
as every other label.

### The sentence under the panel was being cut off

It wears the style built for the short right-aligned note that sits beside a section heading:
capped at just over half the width, no wrapping, and anything past the cap replaced with an
ellipsis. Under a panel that is the wrong shape entirely — measured on a wide screen, the
sentence needed 1255 pixels of a 736-pixel box, so about two fifths of it was never on screen,
and the odd indent on its left was simply the right-alignment. Below a panel a note is a
paragraph: it starts at the left and it wraps.

### The tests compare, they do not pin

Every assertion is derived from the thing it is supposed to match: the panel's lines against
the paragraph beside them, the summary cell against the schedule cell beside it. Nothing is
pinned to a literal measurement, so a future change to either one moves both or fails.

Each part of the fix was then removed in turn, in a separate process, and the matching test
required to go red — nine for nine, with the baseline proven green first and both
stylesheets verified restored afterwards. One of those nine reported red without running
anything: the filter naming which test to check was written as a single word rather than an
expression, so it selected no test at all, and a check on the exit status alone read that as a
failure. The harness now confirms a test was actually selected before believing what the exit
status says. One test exists purely to hold the boundary: the
journal's own rows must **keep** their rail and hairline, so the reset cannot quietly widen
into the thing it was carved out of.

Nothing here is live-behaviour code. The page's styling is served fresh on reload, so all of
it is current without restarting anything.

---

## Stage 5ZQ — somebody finally asked the account

*2026-08-26, early morning. Nothing restarted. No position closed, no order cancelled, no
order modified, no account state written. One file created: the audit's own evidence record.*

### The question B1 had never been asked

B1 exists because one broker login is one position book: two routes holding the same contract
do not coexist as two books, they coexist as one net quantity that no reconcile can take apart.
The switch-over runbook has said since it was written that legacy is not flat until the broker
has been asked, and that a clean local file says only that *this system* holds nothing.

Nothing had ever asked. The gate opened on a signature — a person writing "legacy is retired"
in a file — and that signature asserted a fact about an account no code went and checked.

So the account was asked, read-only, on its own client id, through the same class the safety
jobs use. **Zero positions. Zero working orders.** Equity a shade under a million, which the
dashboard's own reader — a different client id, a different code path — put within ten cents
of the same figure. Two paths, one answer.

Both books hold nothing. Nothing is working behind them, so nothing can be orphaned; and with
no positions at all, nothing can be unprotected either.

### Why a shared account can answer this, when it cannot answer most things

Attribution is the whole difficulty of B1 — a statement from the broker cannot say which route
a fill belonged to. But attribution only matters when something is **nonzero**. Zero positions
and zero working orders is unambiguous however many routes share the login, because there is
nothing to attribute.

That is the one shape of the question a shared account can answer, and the measurement is built
around it: anything nonzero is a failure or an unknown, and never a pass.

### The gate now wants a decision AND a proof

It used to open on either of two signatures. It now opens on a signature **and** a passing
measurement — strictly tighter, since every path that opened it before still needs the
signature and now needs the proof as well.

A waiver exists, because the gateway is sometimes genuinely unreachable and the alternative to
naming that case is an operator quietly deciding the check does not apply today. It releases
nothing on its own, and a confirmation file that carries it without a written reason is refused
outright.

What the measurement deliberately cannot do is close B1 by itself. Proving the account flat at
quarter past six says nothing about the afternoon. Which route owns the login is a decision,
and no measurement makes it.

### The number on the dashboard was never evidence

The panel has been showing no positions and no orders for weeks. That number could not be used,
and the reason is worth stating plainly: both collectors build their list inside a guard that
catches any failure, logs a line, and leaves the list **empty** — and the result is then
published as a healthy, connected reading with no error. So an empty list meant either that the
account holds nothing or that the question failed, with nothing on the page or in the payload to
tell them apart. On the one question where those two must never be the same answer.

There is no backend log on disk either, so the warnings that would have separated them are not
recoverable after the fact.

Each section now reports whether it actually succeeded. Both flags start off, and both are
cleared when the connection drops, so a reading that has gone stale cannot keep testifying with
the last good answer. A payload that does not carry the flags is read as *unknown* rather than
as flat — the safe direction, because an older payload proves nothing.

That fix is not live: it is in the running service's code and the service has not been
restarted. Until it is, the audit has to ask the broker directly.

### A reader written for exactly this, with no caller

The broker class already had an honest way to list every working order — unfiltered by client,
because an order placed by another client is still exposure on the same account, and returning
"cannot say" rather than an empty list when it cannot answer. It was written for this question
several stages ago. It had never been called by anything.

### Three things the files cannot tell you

The legacy trade log looks alarming and proves nothing. Eighteen opens against ten closes leaves
eight unmatched — but six of those eight are the same instrument on the same day, logged at ten
minute intervals, every one of them missing an order id. Six identical opens on a ten-minute
cadence is a job writing the same line repeatedly, not six fills. The log also stops nearly two
weeks before the book was last written. The book and the broker are the authorities here; the
trade log is not evidence of flatness in either direction.

The shadow-window runbook's list of files that must not exist names a path the code never
writes, so that line could never fire. It is stale in substance too: the route's book now
carries state across days and **is** expected during shadow. What matters is that it holds
nothing, not that it is absent.

And a missing book is not an empty book. Absence cannot testify, so it is recorded as unknown —
the same rule the window ledger applies to a slot that did not run.

### Two things caught in this stage's own work

A branch that could never run. The measurement had a separate outcome for a position with no
stop behind it, and any nonzero position failed on the line above, so that check always ran
against an empty list. A branch that cannot fire reads to an auditor as a check that does. The
outcome was removed and the detection kept where it is reachable — as detail on the failure it
belongs to.

And the live-frame gate closed on this stage's own new file. That gate scans the route's modules
for the ways live bars can be obtained and requires each of them to go through the checked join;
the new audit tool constructs a broker, so a fourth blocker appeared the moment it was saved.
The rule was not softened to accommodate it. The file was simply in the wrong category — its
subject is positions and orders and it never asks for a bar, and the other broker-connecting
operator jobs sit outside that namespace for the same reason. The measurement stayed on the
route, where it opens nothing; the tool that connects moved out beside its peers. A test now
pins both halves so the move cannot later read as evasion.

### A pin nobody was watching

One suite pins the panel's fact labels, and one of them had drifted. Which stage renamed it
cannot be established — the whole panel is uncommitted work, so there is no earlier revision to
compare against, and it is not guessed at. What is measurable is that this suite appeared in no
stage's regression set, so whichever stage renamed the label, nothing was watching.

The label is corrected, and the list completed: it pinned ten of the thirteen facts the panel
renders, so three could have vanished unnoticed. It now checks both directions.

### Where this leaves the route

Legacy is flat on disk and flat at the broker, with nothing working behind it, and that is now
a recorded fact rather than an assumption. B1 is still shut, and the reason has changed: from
"nobody has decided" to "nobody has decided, and the fact the decision asserts is now checked".

Five things stand before even a small paper probe, and the fifth is the one the runbook already
warned about: opening every gate produces a route that still cannot send an order, because no
code in it constructs anything that could.

---

## Stage 5ZR — the decision is prepared, previewed, and deliberately not made

*2026-08-26, morning. No confirmation file created. No broker connection opened at all.
Nothing restarted, no runtime file touched, legacy's drain left running.*

### The refusal is measured, not cautious

The previous stage asked the account whether it was flat and recorded that it was. What stood
between that and a closed B1 was the operator's decision, and this stage was to prepare or
record it. It prepares it, and the reason it does not record it is worth stating precisely,
because "played it safe" is not what happened.

The mechanism is safe. Every shape a confirmation file could take was simulated in memory,
writing nothing, and in every one of them orders stay impossible: a decision reaches the one
gate it is meant to reach and stops there. The other two gates are measured rather than
signed, and the registry refuses — structurally, not by intention — to let any signature open
a measured gate.

What is not safe is the **content**. Both decisions assert a fact about the world, and the
file then freezes that fact. Neither is true today.

**Legacy is dormant, not retired.** Building the scheduler both ways without starting it:
in the Track 1-only mode it registers no legacy entry job at all; in the default mode it
registers forty-five. The difference between those two worlds is a single command-line flag.
So a recorded "legacy has retired" is a claim that an ordinary restart falsifies silently,
while the gate goes on reading it as true. Retiring legacy is the switch-over runbook's
ordered procedure, which has not been run — and its eleven drain jobs are still scheduled,
which this stage was told not to disable. A route whose drain is still running has not retired.

**And there is one account.** The second decision says Track 1 has its own broker login.
Nothing in this system has ever seen a second one, so the measurement cannot corroborate that
decision at all.

The runbook has always said the confirmation file is written by a person and never by a
script. That includes this one. What could be done was to make the decision cheap to inspect
and expensive to make by accident.

### A template that refuses by construction

The realistic accident with a template is not a misunderstanding — it is a verbatim copy. So
the template is inert on its own terms: every explanatory key is one the validator does not
recognise, and an unrecognised key refuses the whole file rather than being quietly dropped.
Delete all of them, which is the realistic edit, and the empty operator name refuses it a
second time, independently.

That plural matters more than either reason on its own, and it is now proved by removing each
defence in turn and requiring the refusal to survive every removal.

### A preview, so the effect is visible before the commitment

There is now a read-only previewer: hand it a candidate file and it says what would open, what
would stay shut, whether orders would become possible, what the current measurement says and
when it stops counting, and whether the running scheduler can still open a legacy position.

It writes nothing, and that is asserted rather than promised — every file it opens for writing
is watched during a full run, and the list must be empty. It also never names the live
confirmation path, so a bare invocation cannot drift into reading the real one and, eventually,
being trusted to write it.

The warning about legacy's dormancy is raised there, at the moment of decision, which is the
only moment it helps. It is deliberately not folded into the measurement's pass or fail: for a
*separate account* decision, legacy entry jobs running is correct rather than a fault, and a
gate that could not tell those two apart would be wrong half the time.

### A report describing a gate it did not consult

The paper-readiness report ended with a paragraph saying the order gate requires the blocker
released by a confirmation file. That was true until the previous stage gave it a second half,
and quietly wrong ever since. It now reports the two halves separately — the decision, pending
or recorded; the measurement, passing or stale or missing — because they fail for different
reasons and are fixed by different people. It also states the thing no gate can fix: nothing in
this route constructs anything capable of sending an order.

The evidence half remains unflattering and unchanged: two judgeable days, both failing, and no
sleeve has passed inside the window. Five clean days are required.

### Two of this stage's own tests proved nothing

The template's "more than one reason" test stripped the explanatory keys and checked the file
still refused. Remove that defence from the template itself and the test stays green — because
it removes the defence itself. A test that performs the mutation it is meant to detect cannot
detect it.

The legacy-capability test listed the outcomes the function returns anywhere and required all
three to be present. Change the "no scheduler could be read" branch to answer "legacy cannot
enter" and all three outcomes are still present somewhere in the function, so the test stayed
green while the function began making a confident claim about a scheduler it could not see.

Both were caught by the mutation sweep and both were rewritten — the first to work by
ablation, the second to exercise the branch rather than inventory it. Same lesson twice: a test
that lists what exists is not a test of what happens.

### Where this leaves the decision

It has changed shape. It is no longer "sign the file"; it is *decide which route owns the
login, and make that true* — either by running the switch-over procedure or by funding a second
account. The file records the decision. It does not perform it.

### And a ledger that had gone quiet

Running the whole set of suites that touch the gate registry turned up three failures in the
ledger tests — the ones that check the machine-readable blocking record and the document beside
it against the registry in code. The previous stage's bisect had not covered them, because
those suites were not among the fourteen it ran.

**One of the three was this arc's own doing, and the test was right to fire.** It asserts the
blocker set is satisfiable and, crucially, not satisfiable by signatures alone: hold each
measurement shut in turn, and exactly the gates depending on it must be the ones still
refusing. The previous stage introduced a second kind of measurement — one that must pass even
after a gate has been signed, rather than one whose passing opens it — and that loop only knew
the first kind. So the new measurement came back as releasing nothing, which is true and beside
the point. Both kinds are covered now, and for the second kind the claim is stronger: the gate
must refuse with every signature already granted.

While that test was open it also gained something it never had: granting only the waiver flags,
with every measurement held shut, must open nothing at all. The escape hatch built for the day
the broker cannot be reached must never become a way in.

**The other two were older and worse.** The machine-readable ledger listed two blockers where
the registry has three, and the document beside it did not mention the third at all — a gate
the operator is currently held by, missing from the page they would read to find out what is
holding them. Both had been stale since the stage that added it. A ledger that omits a live gate
is worse than no ledger, because it reads as complete.

Both are repaired. The record was regenerated from the registry, which is exactly what its own
failure message instructs; the document was given the missing gate, written from the registry's
own words, and a section recording that the account blocker now needs a decision and a proof
rather than a signature.

And the reason it drifted is left named rather than fixed: **nothing in the repository writes
that ledger.** "Generated from the registry" is true as intent and manual in practice, which is
precisely how it went a whole stage without being regenerated. A regeneration step belongs in
whatever stage next touches the registry — not in a stage about a decision.

---

## Stage 5ZS — the safety net stops writing the route's book in someone else's handwriting

*2026-08-26, late morning. Nothing restarted, no broker contacted, and no runtime file
written — the damaged book was left exactly as found and its repair is a dry run.*

### What happened, and why it was quiet

At half past nine this morning the route's own max-hold sweep rewrote the route's own book in
the legacy format. Nine fields went: the route tag, the window, the cut instant, the current
day, the equity, the breaker's peak and day-start, and both counters. The envelope version was
downgraded. In their place it wrote a breaker block belonging to the other route, carrying an
account-scale equity this route has never used.

The list of open positions was empty before and empty after. That is the whole reason it passed
unnoticed, and the whole reason it mattered: on the first day the route holds something, the
same write happens with a position in the file.

The job was doing everything right. Its command line carried its own book, its own kill switch,
its own lock file, its own client id, its own trade log and its own route tag — every piece of
routing an earlier stage built, all of it honoured. What it lacked was any notion that the
SHAPE of the book was part of the contract.

### The fail-open underneath it

The reason the numbers were invented rather than merely lost is at the other end. The reader
that loads a book meets an envelope version it does not recognise, logs a line saying so, and
carries on. It then looks for the breaker block that a legacy book would have, does not find
one, and leaves every breaker value at its default. The writer duly persists those defaults.

An unrecognised format was a log line, not a refusal. That is the same shape as the dashboard
reader turning a failed query into an empty list, two stages ago, in a different file.

### The same defect sits in the stop-repair sweep, dormant

It builds the same runner against the same book and reaches the same writer. It corrupted
nothing today only because there was nothing to change. The first Track 1 stop it ever repaired
would have done exactly this. Both are fixed together.

### Three layers, because they fail independently

**The writer** now puts positions back into the envelope it read, rather than replacing that
envelope with the legacy one. The switch is the presence of a route tag — the same switch the
trade-log routing used — so a run with no route is byte-for-byte what it was. A route-stamped
run against a book with no envelope at all falls through to the legacy shape deliberately:
there is nothing to preserve, and inventing an envelope there would be that method deciding a
format it does not own.

**The carry-forward** used to accept a book with no route at all — an unstamped file passed the
check that was meant to catch a foreign one, which is precisely how this morning's file was
taken as the route's own. It also copied every key it found, which is how the foreign breaker
would have travelled onward. Now the route and the version must both match, only declared
fields are carried, and a declared field the previous book lacked comes back at its default
rather than absent, so nobody downstream has to guess which of the two it is.

**The entry points** get the contract the trade log already had: the book is chosen on purpose,
a route may not edit the other route's book, the route's book may not be edited without naming
the route, and a book that exists and is not this route's book is refused rather than rewritten.
The check runs before the early return for a missing book — the same reasoning as the trade-log
probe, because that early return fires on every single run during shadow, and a check after it
would never execute.

That last contract was narrowed once, on purpose. Its first draft also demanded the canonical
filename for any routed run, which is not the hazard: it forbade a test harness using its own
path and broke four tests from the stage that built the trade-log contract. A false positive is
not a caught hazard. The rule now names the hazard — the other route's book — and the envelope
check applies to the canonical artefact. A mutation pins the narrowing so it cannot widen back
by accident.

### Missing is not corrupt

Four states, and the reader never raises: absent, unreadable, readable-but-not-this-route's, and
valid. Absence stays allowed, because it is the normal state through the whole shadow period and
both scripts already return early on it. Everything else fails closed.

### The repair recovers nothing, and says so

The checkpoint holds per-instrument resume state and no book envelope, so the nine lost fields
have no source on disk. The repair tool rebuilds the envelope at the route's defaults and
carries the position list forward — which is only sound while the route has never traded, so it
proves that first, from the empty trade log and the absent order journal, and refuses over an
open position or a route that has traded. Rebuilding equity from a default over a real position
would be a guess about money.

It is a dry run until told otherwise, and it backs the damaged file up before writing.

### What the fix costs today

The stress window closes at half past twelve, and the carry-forward will now refuse the damaged
book, so that close writes no checkpoint and reads as a failed window. That is the fix working.
The alternative is what it replaced: the corruption travelling into a well-formed book carrying
the other route's breaker, silently, for as long as nobody looked. A failed window is the
cheaper of the two and it is visible.

Nothing needs restarting for any of this — every slot and every safety job is its own process,
so they pick the change up on their next run.

### And one thing this stage found on the way

The account-flatness check called the damaged book flat. It asked how many positions the file
listed, and the file listed none — so it reported the route's book as flat when the file was not
the route's book at all. Flat and unrecognisable are different facts and a gate must not read
them the same. It now checks the envelope too.

The status line still prints a pass, and that is correct: it reads this morning's record, which
was true when it was written at quarter past six. The damage came three hours later. The record
is honest about its own timestamp; the next one will not be.

---

## Stage 5ZU — Calm was waiting for a bar that cannot exist while it is allowed to look

*2026-08-26, midday. Nothing restarted, no broker contacted, no runtime evidence written. The
splice guard was not touched and the entry price definition is unchanged.*

### One number carries the whole stage

The frozen Calm record has four hundred and twenty-one rows, and on every single one the
signal is stamped half past nine and the entry ten o'clock. Not approximately: the gap between
them takes exactly one value across the entire file — thirty minutes.

So the decision is fixed half an hour before the bar the live gate was waiting for. The rule
reads yesterday's completed session and this morning's opening price, and nothing else. The
ten o'clock bar contributes exactly one thing: the opening price the trade transacts at.

### The contradiction, in the sleeve's own configuration

The sleeve declared that it may decide at ten o'clock and only then, with a minute of grace for
dispatch latency, and that its decision bar is the ten o'clock five-minute bar — which has to
have closed. A five-minute bar stamped ten o'clock closes at five past. The deadline is one
minute past. Four minutes apart, every day, and it had refused every day it had ever run.

It was the only sleeve where the bar it waited to close was also the first instant it was
allowed to look. The one whose measured level sits five minutes before its own window escapes
by arithmetic; the two scanning sleeves escaped because an earlier stage had already fixed
this class for them, after nineteen consecutive overnight slots refused for the same reason.
Calm was deliberately left out of that fix, because for Calm the bar really is what the trade
transacts at. That was right about the price and wrong about the decision.

### The fix is two names where one was doing both jobs

There is now a declaration of how far the DECISION reads — five to ten — and a separate
declaration of which bar the ENTRY is priced at — ten o'clock — and the second is checked
against the minute-by-minute index it is actually read from rather than against the
five-minute decision frame. Two bar sizes, two questions. Collapsing them is what made the
sleeve impossible.

The grace moves from one minute to three, and that is a change to when the route LOOKS, not to
what it trades: a one-minute bar stamped ten o'clock closes at one minute past, so a minute of
grace put the deadline exactly on the closing instant. Three minutes let a slot see a closed
bar and still refuse anything past three minutes past. The entry price is asserted, in a test,
to be the same value the strategy parameters declare.

Two refusals replace the old one, and they are kept apart: the fill reference is not readable
yet, or nobody said where it would be read from and that half was therefore not checked. The
second is never reported as a pass.

### Changing the gate alone did nothing

The slot handed the gate only the resampled five-minute frame, so every Calm slot would have
refused for a new reason instead of the old one — a different refusal, not a fix. The
regression caught it: a live-source test stopped reaching a decision. The one-minute frame was
already in scope three lines above the call, and is now passed with it.

That is worth recording as its own lesson. A guard added and not wired is the same defect this
project has found four times now, in four different files.

### The constraint about partial bars holds by construction

Measured live at nineteen seconds past ten this morning: one instrument's frame already
carried a bar stamped ten o'clock — nineteen seconds of one — and the other's stopped at one
minute to. A partial bar's OPEN is final from its first tick; its high, low and close are not.

Because the decision span now stops at five to ten, a ten o'clock bar in the frame sits outside
everything the decision reads. That is proved by equality rather than argued: adding a partial
bar with an absurd high and low changes neither the verdict, nor the codes, nor the description
of what the span checked.

### What this does not fix, said plainly

Calm will still refuse tomorrow morning. The slot is dispatched at ten o'clock exactly and the
price it needs becomes readable a minute later. It will refuse for a real reason now instead of
an impossible one, which is an improvement and is not a pass.

The remaining piece is a scheduler edit — dispatch the slot a minute or two later — and it is
recommended rather than applied, because it needs a restart. The entry price does not move, so
it is a change to when the route observes, not to what it trades. Until it happens, the
evidence gate cannot count a Calm pass, and that gate wants every sleeve to pass at least once.

### And a measurement error of my own

The first pass at proving the record read the parquet with a helper that strips a timezone
without converting it, on a file whose index is in UTC — a fact stated in a comment written
after an earlier incident of exactly this kind. Every bar came back four or five hours out and
almost every row mismatched.

What gave it away was not the count of mismatches. It was that the file returned a price with a
long decimal tail where the record held a round number. A price that cannot be a tick is a
fault in the measurement, not in the data.

### A second finding, about the record itself

The older rows' prices are not reproducible from today's file, and that is by design rather
than by error. The series is back-adjusted: every roll subtracts a gap from all prior history,
so the further back a row sits the larger the accumulated shift. The current window reproduces
to the cent; the 2025 window is half a thousand points away and the 2018 window fifteen
hundred.

Three independent signs say adjustment rather than a different bar: the shifts grow
monotonically with age across about fifty distinct levels; the difference between exit and
entry is identical on nineteen rows in twenty, because an additive shift cancels in a
difference; and the one feature that is immune to an additive shift agrees far more often than
the ones that are not.

The existing reproduction test still passes, because it checks the window whose prices are
still current. Anyone re-proving the older windows should expect the levels to have moved and
should compare differences, not levels.

### Stage 5ZT, closed here

The previous stage's validation had two decisive events still in the future when the next stage
arrived, so its report was never written. They have since happened.

At half past twelve the afternoon window closed and wrote both the route's book and its
checkpoint — the first checkpoint since the small hours — and the book came through it still
carrying the version and the route stamp the repair had restored. The repaired envelope
survived a real window close, carry-forward accepted it without a refusal, and the legacy book
sat untouched throughout.

---

## Stage 5ZV — a judgeable contract is not a tradable one

*Opened 2026-08-26, closed after midnight ET. No order send wired, nothing restarted, no
runtime evidence written, the entry price definition untouched.*

### The previous stage answered a different question than it looked like

Stage 5ZU let the gate read the ten o'clock opening price from a closed one-minute bar a minute
later. For shadow that is exact: the price is final from the bar's first tick and reading it a
minute afterwards is simply observation. For paper it is not, and the difference is the whole
of this stage. An order sent at one minute past cannot fill at a price that happened a minute
earlier. A shadow record claiming it would be claiming a fill the real route could never
achieve — and it would enter the evidence gate as though it had.

Judgeable and tradable are different properties. The previous stage delivered the first.

### The measurement that settled which contract to keep

The useful question was not when the route can SEE the entry bar. It was how early the DECISION
is known.

Every one of the four hundred and twenty-one frozen setups was rebuilt from a frame with
everything after half past nine removed, and the features required to match the full detector's.
Four hundred and seven reproduce. The fourteen that do not are five sessions missing their own
opening bar and nine the rule no longer selects on today's re-adjusted series — neither is about
the truncation.

So the rule reads yesterday's completed session and this morning's opening price, and nothing
else. That price exists at half past nine; a closed one-minute bar carrying it exists a minute
later. The entry is at ten.

**Twenty-nine minutes of slack.** That is what makes the original contract tradable, and why the
entry does not have to move.

### What moving it would have cost

Measured on the same rows, one consistent read, compared on differences because absolute levels
drift with roll adjustment: entering a minute later loses about eight per cent of the total and
flips the sign of eighteen trades. Entering five minutes later changes the total by less than
half a per cent — and nearly doubles the per-trade spread while flipping twenty-nine.

That second row is the one worth pausing on. Its total says "no difference" and its dispersion
says the opposite. A figure that looks like nothing changed is the one to distrust, and it is
exactly the shape an aggregate takes when it is hiding a change rather than showing there is
none. Either way it would be a different strategy needing its own walk-forward, and since the
original is tradable, that buys nothing.

### The structure, and the machinery that already existed

Three phases. A DECIDE job in the half hour before the entry, reading only bars that closed by
half past nine, computing the setup and writing an INTENDED order to the journal. A SEND step at
the entry instant that reads no bars at all — it acts on the journal. And an OBSERVE step a
minute later that records what the opening price actually was, which in shadow is the end of the
story and in paper is the denominator for slippage.

None of that needed inventing. The order journal has separated intended from submitted since
Stage 5V, and refuses a first record that is not intended. This stage named the contract those
states were built for. The send step is deliberately not built: the constraints forbid it, and
the route still constructs a broker that cannot place anything.

### What shadow may say

Before the entry it may record the setup, the instrument, the direction, the size, the stop
RULE with the inputs that feed it, and the intent. After the reference bar closes it may record
what that opening price was, and only then the planned stop LEVEL. It may never record a fill,
a fill time, a realised profit or a slippage, because it sent nothing and nothing filled.

The stop deserves its own sentence, because the first draft of this put it on the wrong side.
Calm's stop sits an ATR-and-a-half below the entry, so the LEVEL cannot exist before the entry
reference does. Everything else about it can: measured with two different entry prices and the
same volatility reading, the stop DISTANCE comes out identical, the dollar risk is that
distance times the contract value and cancels the entry out entirely, and the size is a fixed
constant for the sleeve rather than something derived from risk. Only the level waits. The three groups are asserted not to overlap, and the price is
asserted not to belong to the earlier one — recording a price before the bar carrying it exists
is the same error in a smaller costume.

### And the gate moved while the stage ran

Three blockers were reported throughout, which was true when measured. There are two now: the
regime-label gate returned its **first pass ever** — eleven hundred and sixty-one labels
compared, none changed — recorded twice today by the afternoon pre-flight and the post-close
refresh. The stage that built that gate could only ever watch it refuse; this is the first time
it has said yes.

The shadow evidence count also moved, from two judgeable days to three of the five required.

### Two tests, and only one of them was wrong

One compares a frozen ledger against a function that embeds live measurement results, so it
cannot stay equal to it: regenerated a few stages ago, it had drifted again within hours because
a day count moved and a verification passed. Neither is a change to the registry it claims to be
checking. The static half is now compared exactly and the live half checked for shape, which is
what the comparison was really protecting.

The other was a time bomb that went off on schedule, and correctly. It pinned that today had not
been marked pre-flight-clear, put up after an incident where a test of mine wrote a fabricated
clearance into that very file. The real pre-flight has now run and today is legitimately there.
The guard did its job for four stages and has expired; it should assert that no day was added by
anything but the real job, rather than naming dates. That belongs to whoever next touches it.

---

## Stage 5ZW — the correction holds, and the plan is two jobs and one stream

*2026-08-27, small hours. A review and a plan. Nothing implemented that sends anything, nothing
restarted, no runtime file written, the entry time and the backtest untouched.*

### The correction was right, and looser than the truth

Under review: the claim that Calm's stop price cannot be known before the ten o'clock reference
exists, because the stop sits an ATR-and-a-half below the entry.

That is correct, and the previous stage's first draft had it wrong — it listed the planned stop
as something shadow could record half an hour before the entry, which would have the route
writing down a price it cannot compute. The same error as recording the entry price early,
wearing a smaller costume.

But the sharper statement is worth having. Measured with two different entry prices and the
same volatility reading, the stop DISTANCE comes out identical both times; the dollar risk is
that distance times the contract value, so the entry cancels out of it entirely; and the size
is a fixed constant for the sleeve rather than anything derived from risk. **Only the stop
LEVEL waits.** Everything else about the stop is knowable at half past nine, which is precisely
why the before-entry evidence carries the rule and its inputs while the level travels with the
reference price.

The documents did not agree with each other on this, either. The previous stage's report listed
the planned stop on the wrong side in its summary block and contradicted itself five lines
later in the correcting paragraph. The block is the part a reader copies, so it is the part that
had to be fixed.

### And a third confirmation nobody was looking for

The route's book and checkpoint moved during the review, which at first reads like something
being touched. They moved because the afternoon window closed and the route wrote them — and
the book came through it still carrying the right envelope version, the right route stamp, and
no foreign fields. That is the third window close the book repair has now survived.

### The plan: two jobs, one new stream, and one thing that must not be reused

The contract needs three phases and has none of them. Nothing computes the setup from the
half-past-nine bar and writes down an intent; nothing records the ten o'clock opening price as
the reference afterwards; and the send step in between is deliberately absent and stays absent.

Two scheduler jobs, not one longer slot. A slot that began before the entry and finished after
it would hold a process and a broker identity across the entry instant, and a crash anywhere in
that half hour would lose both halves at once. The two phases read different things and fail in
different ways, and one slot spanning both cannot say which of them broke.

A new evidence stream, because every existing one already has a reader that counts it — the
per-slot explanation store in particular, where a reader tallying rows would quietly begin
tallying intents.

**And the intent must not go into the order journal.** That is not a preference. Four separate
readers treat the mere EXISTENCE of that directory as proof the route has acted: the book
repair refuses to run if it is there, the call-site guard watches the production root for it,
the reporting layer reports "not produced" while it is absent, and the operator runbook says to
stop and investigate if it appears. A rehearsal written into that directory would make all four
declare a route that traded, on a day it sent nothing — and it would block its own book repair.
That invariant is now pinned by tests, before anyone implements the plan rather than after.

### What changes later, and what does not

One job, one swap, one promotion. A send step at the entry instant that reads the recorded
intent and calls an executor, reading no bars at all — which is exactly what makes it free of
future data. A placeholder executor replaced by a real one, built and proven on its own. And
the rehearsal intent promoted into the real journal at the moment the route is armed: the same
fields, a different stream, and the promotion itself is the act that says this is no longer a
rehearsal.

The decide and observe phases, their times, and the entry reference do not change. That is the
whole point of building them before the gates open rather than after.

### A duplication recorded rather than repaired

The path to the order journal is defined independently in three modules while a fourth
references the shared constant. Three definitions of one path drift quietly, and the readers
whose whole job is to prove the route has not traded would end up looking in different places.
A test now asserts they still agree, which fails the day they stop — the only way anyone would
find out. Collapsing them belongs to whoever next touches that path.

### Where the route stands

The evidence gate wants five clean days and has three; Calm can contribute none of them until
the two new jobs exist, because its slot still refuses. The account blocker still waits on a
decision, and the measurement backing it expires a day after it was taken, so it will need
re-running on the day that decision is made. And the send step does not exist.

---

## Stage 5ZX — the morning is split in two, and neither half can send anything

*2026-08-27, small hours. The plan from the previous stage, built. No step that sends exists,
none was authorised, nothing was restarted, and no production runtime file was edited by hand.*

### What building it taught that reading it could not

The plan said two jobs: one that decides shortly after half past nine, one that records the
opening price shortly after ten. Both were right. Both would have produced evidence that looked
correct and said nothing, for reasons that only appeared when the code ran.

The first is the important one. The Calm rule, as the route holds it, refuses to answer at all
unless today's ten o'clock bar already exists — it needs that bar to name the price the trade
would transact at, and it declines rather than guess. At half past nine that bar has never
existed on any day in history. So a decide job asking the route the ordinary question would have
been told "nothing set up today" every single morning, and would have written exactly that down,
in perfectly good faith. Five clean weeks of it would have satisfied the counter and meant
nothing at all.

That forced the rule to be split where it genuinely divides rather than where it was convenient.
Everything the rule decides is settled once today's opening bar has closed: the prior session
finished yesterday, and this morning's opening price is the last thing it reads. The only thing
ten o'clock adds is the price — and, through the price, the level the protective stop sits at.
That division now exists as one shared piece of the rule which the full detector is built **on**,
not beside. Two copies of one rule is a rule that will drift, and this one would drift in silence:
an intent recorded from a stale copy still looks exactly like evidence.

The second: neither half can ask the route for candidates at all, because the route's first
question is always "which sleeve is allowed to decide at this instant", and this sleeve's window
is the single instant of ten o'clock. Half past nine is outside it. Two minutes past ten is
outside it. The observing half was written to ask anyway, and the first run refused with "no
sleeve at this instant" — the correct answer to the wrong question. That half is not looking for
a setup. The setup was found half an hour earlier and written down; all that remains is to read
the price the decision named.

The third is small and worth keeping. The first refusal record said the gate had refused, when
the gate had passed and the refusal came from somewhere else entirely. Anyone reading it would
have gone off to inspect a gate that was working perfectly. Refusal records now carry the name of
whatever actually refused.

None of the three was visible from reading the code. All three came from running it.

### Proof the strategy did not move

Splitting a live rule puts the burden on the person splitting it. Three hundred and nineteen
sessions were run through the detector before the change and after it, comparing every field it
produces — the day, the direction, both timestamps, the entry price, the prior session, and all
four features. The two runs hash identically. Eighty-four of those sessions set up, and the new
pre-entry half independently picks out exactly those eighty-four. The parameters are untouched:
the entry is still the ten o'clock open, the stop is still an ATR-and-a-half below it.

The comparison holds regardless of which clock the data sits on, because the same data goes
through both runs. That is worth saying, because the historical file is on universal time and the
route's own loader converts it to New York — and measuring the two halves of this work on
different clocks would have been the easy mistake.

### The schedule, measured rather than counted

Replacing the single morning slot with two takes the route from a hundred and one jobs to a
hundred and two. That number comes from building the schedule for real, twice in one process,
with the old slot table reconstructed in memory for the comparison — not from counting entries by
hand. It happens to be the number the plan predicted, which is why it is reported as a measurement
rather than as a confirmation.

Neither new slot sits on the entry instant, and that is the repair rather than a side effect: the
slot that did sit there needed a five-minute bar that would not close until four minutes after
its own deadline, so it refused every morning of its life.

Which half a process is running travels in its command line — for a slot that has a half. The
first version printed it for every slot, on the reasoning that somebody reading the process list
at half past nine should be able to see which half is running. The regression pointed out that
the reasoning does not survive contact with a sleeve that is not split: printing an empty half
for the other three changed the command line of three sleeves this work has no business touching.
Narrowed, and their command lines are now identical to what they were, which was measured rather
than assumed.

A misspelled half refuses outright rather than falling back to the sleeve's ordinary rule.
Falling back would gate the deciding half with the entry-half requirement, pass it at the wrong
instant, and leave a record indistinguishable from a slot that ran correctly.

### What the two halves actually wrote

Driven end to end through the same function the scheduler calls, on a real session, with the
route's own loader: the deciding half recorded the setup, the instrument, the direction, the size,
the stop RULE and its inputs — and no price of any kind. The observing half added the two things
only it can know, and the reference price it recorded equals the session's real ten o'clock
opening price to the cent, with the stop exactly an ATR-and-a-half below it. That last was
checked by arithmetic rather than trusted.

The day classifies as a decision worth judging, and the words that travel with that label say
what it does not mean: the route would have acted, and this says nothing about whether an order
would have been accepted or where it would have filled.

What the run wrote: the intent stream, the diagnostics row, the coverage row. No order directory.
No trade log. No book. No checkpoint. Asserted, not noticed in passing.

### How the route counts this

The readiness report gained a line for each qualifying day, in words rather than codes. All three
current days read "missing", because all three come from before the stream existed — which is the
honest answer rather than a failure of the reader.

A day where the rule looked and found nothing **counts**: the route was watching and correctly
recorded that there was nothing to do. A day with no record at all does not. Those two are the
same silence to anything that merely counts, and telling them apart is the entire reason the
stream exists.

Every record the gate writes carries what it proves and what it does not, and the reader raises
rather than returning if it is ever handed a label claiming an execution. A count read on its own
becomes a claim in the mind of whoever reads it next.

### A finding recorded rather than repaired

The diagnostics rows have never carried a parameter identity. The reader checks whether the
parameters module offers a way to hash them; that module has never offered one. The real function
lives elsewhere, takes a complete configuration rather than a sleeve's name, and refuses an
incomplete one outright — good design that this particular caller never reaches. So every
diagnostics row written since the field was added carries an empty identity, and two rows compare
equal because both are blank. Repairing it changes what those rows contain, and belongs to whoever
owns that channel.

### While this was being written

The route's book and checkpoint both moved in the small hours, which at first reads like something
being touched. They moved because the overnight Nikkei window closed and the route wrote its own
state. The book came through it still carrying the right envelope version, the right route stamp,
no foreign fields and no positions — the fourth window close the earlier book repair has now
survived.

### Something the regression said about itself

Running the whole accumulated body of tests produced a hundred and nine failures. Re-running the
same failures with the old slot table restored turned forty-five of them green, which is how the
split's cost was established rather than guessed at — the rest were already red before this work
started.

The comparison also said something about the body of tests itself. The same set, run twice,
produced a hundred and nine failures and then ninety-eight. Eleven of them pass or fail depending
on what ran before them. That belongs to the corpus rather than to this work, and it means any
count taken from it carries roughly a tenth of noise — worth knowing before somebody treats such
a number as a threshold.

Four of the failures were repaired, because they were not stale pins. Two counted how many times
the detector reads an opening price and how many times it evaluates the rule, scoped to a single
function — and the causal path is now two. The property they hold was never about one function;
it was that the path takes exactly the two opens and evaluates the rule exactly once. Widened to
both halves and, separately, to each half alone: a total of two split two-and-zero would satisfy
a total, and would mean the pre-entry half had reached into the entry bar, which is the one thing
it exists not to do. Three deliberate breakages confirm all three still catch what they are for.

The readiness fixtures were the other repair. A clean shadow period now includes this sleeve's
decision evidence, so the fixture had to grow it — and that those tests went red before it did is
the proof that the new requirement can actually refuse something. The two that matter are the ones
proving the gate can open at all; leaving those red would have left nobody able to tell whether it
still could.

The rest are counts and names — a pinned number of slots, a pinned total, tests calling the old
slot by its old name. They are left red and listed. Repairing the ones that drive the old slot
means deciding, test by test, what the new timing should mean, and doing that quietly inside this
work is how an assertion gets weakened without anyone choosing to weaken it.

### Where the route stands

The evidence gate wants five clean days and has three, and none of the three carries any Calm
evidence, because the two new jobs have not yet run in production. The account blocker still waits
on a decision, and the measurement backing it expires a day after it was taken. And the step that
sends does not exist.

What remains is one job, one swap and one promotion: a step at the entry instant that reads the
recorded intent and reads no market data at all — which is exactly what makes it free of
information from the future — a placeholder executor replaced by a real one proven separately, and
the rehearsal intent promoted into the real journal. The promotion is the act that says this is no
longer a rehearsal. The times and the entry reference do not move; that is the point of having
built them before the gates open rather than after.

---

## Stage 5ZY-PRE — the code is right, and the process running the route has never heard of it

*2026-08-27, before dawn. A read-only precheck. Nothing was restarted, nothing was written, and
no claim is made that the sleeve has produced any live evidence yet.*

### The thing worth knowing first

The two new morning jobs exist in the code, are registered when the schedule is built, and are
absent from the process that is actually running the route. That process started at ten past ten
last night. Every file the previous stage changed was written four to five hours later. A
schedule is built once, at startup, and held in memory; this one was built from the old table and
has been running from it ever since.

Its own log says seventy slots registered. The code declares seventy-one. And across every
scheduler log this project holds, the names of the two new jobs appear not once.

### And leaving it alone is now the dangerous choice

At ten o'clock this morning the running scheduler will launch the old morning job by its old
name. That name no longer exists in the code, so the child process refuses — and the refusal
happens before the window ledger is opened, which means the window leaves **no record at all**.

Measured, not reasoned about: the refusal was reproduced and the ledger it produced was empty.

Yesterday the sleeve also refused, but it refused inside the ledger and left a row explaining
itself. Today it would vanish, and an audit reads a vanished window as *nobody looked* — which is
strictly worse than a recorded failure, and is precisely the shape an earlier stage went to some
trouble to eliminate for a different refusal.

So the restart is not housekeeping. It is the difference between a window that says why it failed
and a window that is simply not there. It has to happen before half past nine, and there are three
comfortable gaps in the schedule to do it in.

One adjacency is worth knowing before that first morning: the deciding job fires one minute after
the overnight holding sweep — the same sweep that wrote the route's book at thirteen seconds past
half past nine yesterday and caused the corruption an earlier stage repaired. Measured from the
live logs, that sweep takes between one and thirteen seconds, so the deciding job has roughly
forty-seven seconds of clearance at the worst runtime anyone has observed. They hold different
broker identities, so they cannot collide on a connection. Thin, real, and worth watching rather
than assuming.

### What the evidence actually says right now

The sleeve contributes nothing, and this precheck claims nothing otherwise. All three days on
record read *missing*, because all three come from before the stream existed.

Two details from the per-sleeve breakdown change what the next window means, though. On the most
recent complete day the route reached a pass on two of its four sleeves — the stress and the
afternoon sleeve both passed, and this one was among those that did not. And the reason recorded
against it that day was a gate refusal about a bar that had not closed — from a run that happened
*before* the timing repair landed. Which means the most recent live result for this sleeve does
not measure the code that exists now. No live morning window has ever run against either the
timing repair or the two new phases.

### Checked against production rather than against a fixture

The previous stage narrowed the new command-line flag to the jobs that have a phase, and claimed
the other three sleeves' command lines were untouched. Compared against what the running
scheduler has actually been launching, they are identical, character for character. And across
two hundred and five launches recorded in every log this project holds, the flag that would
request orders appears zero times — as it does across all seventy-one jobs the new code would
build.

### A gap found by trying to break it

Deleting the phase from the launcher left every test in the accumulated corpus green. The slot
table knew about phases. The gate knew about phases. Nothing at all asserted that the code which
starts processes passes one — a mechanism built, and its wiring left unproven, for the fifth time
in this programme.

It is closed now by a test that starts the real registered jobs with the launcher swapped out and
reads the command lines they build. One test, four separate collapses caught: the shadow flag
removed, the phase removed, an order flag smuggled in, and a phase leaking onto the sleeves that
do not have one.

### Two repairs this precheck owns

Both were good assertions that the previous stage broke, and neither was loosened to make it pass.

The dashboard has a pin that fails in both directions — it complains if a row is displayed that
its list does not know about. A row was added without being declared, and the pin caught precisely
that. Declaring it also brings it under the per-row check, so it is now held from both sides.

The other is an older suite's reader of the launcher's arguments, which understood a single list
and nothing else. The narrowing turned that list into a joined pair, so the reader stopped finding
the call and reported that no launch existed — which reads like the wiring was deleted rather than
reshaped. It now understands a join, and reports both sides of a conditional, so a reader asking
whether the command line can carry an order flag still gets a truthful answer. Widening what reads
the argument did not loosen what the assertions demand of it: a removed flag still disappears.

### The failures, sorted by cause rather than by name

Of the failures across the whole corpus, forty-five are caused by splitting the morning slot —
established by re-running them with the old table restored and counting what turned green, not by
reading the test names. About fifty were already failing beforehand: pinned rosters, a pinned job
count that drifted, and assertions that the live runtime directory does not exist on a machine
where the route has been running for days. Three were genuine regressions from the previous
stage, and all three are repaired above.

The count now stands at ninety-five failing and two thousand four hundred and seventy-six
passing, which reconciles exactly against a separate count of what the collector finds — a check
worth doing, because totals that nearly agree are how a miscount survives. Four failures went
away and three of them are the repairs above; the fourth is a browser assertion about a tooltip,
in a file this work does not touch, which passes on its own. It is counted as noise rather than
credited as a fix, because claiming it would have been the easy arithmetic and the wrong one. And
nothing turned red — established by comparing the two lists of failures rather than their totals,
since a total can hold steady while one test is quietly traded for another.

The corpus also carries about a tenth of noise in any count taken from it: the same set of tests,
run twice, produced a hundred and nine failures and then ninety-eight. Eleven of them depend on
what ran before them. Worth knowing before anyone treats a failure count here as a threshold.

The forty-five are left red and listed. The count pins are an anti-pattern already on this
project's record, and the ones that drive the old slot by name exercise a ten o'clock behaviour
that no longer exists — repairing those means deciding, one test at a time, what the new timing
ought to mean, and doing that quietly inside a precheck is how an assertion gets weakened without
anybody choosing to weaken it.

### What to watch, in order

The restart, in one of the quiet gaps before half past nine. Then the deciding job at half past
nine — the first time either phase has ever run in production. Then the observing job just after
ten. Success looks like a file appearing for the session with a decision carrying no price and an
observation whose reference equals the ten o'clock open; the day reading as a judgeable decision;
and the order directory still absent. And immediately afterwards, the book still carrying its
right envelope, because the sweep that once damaged it runs a minute earlier.

---

## Stage 5ZZ — the health check was telling the truth in a language nobody could read

*2026-08-27, just before dawn. The operator tool only. Nothing restarted, no runtime file
touched, and the gate exactly where it was.*

### It did not reproduce, and that is the first thing worth saying

Running the status command at the start of this work printed process ids, not the unknowns that
prompted it. The fault is intermittent and could not be summoned. What follows is therefore not
a repair of something watched failing; it is a repair of the reason a failure is unreadable when
it does happen — and that part reproduced exactly.

One theory died on measurement. The probe has a twenty-second limit and the status command runs
it twice, which made a timeout the obvious suspect. Timed over three runs on a host carrying
four hundred and seventy-one processes: two thirds of a second. Narrowing the query to python
processes measured the same, because the cost is the shell starting up rather than the walk
through the process table. So the tempting optimisation was not made: it buys nothing, and it
would quietly stop finding a scheduler somebody launched under a different interpreter name.

### What actually made the unknown useless

When the probe failed, the reason recorded was the first two hundred characters of the error
stream. The shell's default rendering echoes the entire command before it reaches the message.
Measured on a deliberately broken probe: six hundred and ninety-two characters of error output,
of which the first two hundred were the script's own opening, and the words that mattered sat at
the very end.

So the operator was shown the unknown followed by a fragment of their own script. The reason was
printed and was worthless, which reads exactly like no reason at all. There is one instance of
this in the project's own operations log, from a fortnight ago, truncated in precisely that way
and saying nothing about what went wrong.

Nor is the answer simply "take the last line". Measured against genuine output, the last line is
the exception's class name, and the message itself is split across two lines by the shell's
wrapping. Three wrong answers were available and the extractor is built from the shape that was
actually observed, recovering the real message from real output both with the new marker the
probe now writes and without it.

### A third state, built and then thrown away one function later

The scan result was designed with three states, and its own comment says why: collapsing "I
could not look" into "nothing is running" is what once made the tool start a second scheduler on
top of a live one.

But the function above it returns a list, and a list cannot say it could not look. So a failed
probe arrived as an empty list, became "the scheduler is not running", and printed as Track 1
being off — about a scheduler that was running perfectly. The same collapse the design was
written to end, one function down the call chain.

It now has three states all the way to the printed line, and an unknown says which probe failed,
in what category, and in the probe's own words.

### Where each number comes from, said in the output

Every process line now names its source. Today both are read from the process table. There are
no process-id files in this project, so the only fallback is the scheduler's own log, and it is
labelled as such and never claims the process is running — a log line is a history, equally
consistent with something still going and something that died a minute later. The backend has a
port, so its fallback is a live listener and may claim it; the scheduler has no port and never
does.

### The check that would have caught last night

A scheduler builds its job table once, at startup, and holds it. Every edit afterwards changes
the code and not the running process. The previous stage discovered a four-hour-old scheduler
running a table that no longer matched, by comparing a log line against the package by eye.

The status command does that comparison itself now, and says either that the two agree or that
they do not and a restart is needed. It works from the log alone, so it still answers when the
process table cannot be read — which is exactly the moment somebody most needs to know whether
the schedule running is the one they wrote.

### A latent defect found while fixing this one

The probe matched itself. The pattern it searches for is embedded in its own command line, so
any pattern lacking a regular-expression escape finds the process doing the searching. Both
production patterns happen to be immune because they escape their dots — an accident, and the
routine that decides whether to KILL a duplicate reads this same scan. Closed, and pinned by a
test that asserts each pattern cannot match its own source text.

### A mistake of mine, caught by the tests

The first version read the scan directly where the status is assembled. That looked tidier and
silently bypassed the seam every existing test replaces: five suites that believed they had
described a scheduler were reading the real machine, and passing or failing on whatever happened
to be running. A test that is not isolated is worse than no test, because it reports on the wrong
system with complete confidence. The rows come back through the old seam; the scan is consulted
only for its third state.

### And a correction to the previous stage's record

That stage reported three genuine regressions from the work before it. There were four. A third
copy of the same command-line reader lives in the startup suite and failed with differently
worded text, so grouping the failures by their message put it in the wrong bucket. It was not
pre-existing.

The count is the small part. That test asserts that no order flag can reach a Track 1 slot, and
it had stopped running. It is repaired, widened the same way as its two siblings, and it now also
holds that a phased slot carries its phase.

### Where the route stands

Unmoved. Orders remain impossible, the same two gates block, the order journal is still absent,
and the intent stream is still absent because the two morning phases have not run yet. The next
thing to watch is unchanged — the deciding job at half past nine, the first run of either phase
in production — and the status command will now say, on its own, whether the scheduler about to
fire it is running the schedule anybody wrote.

---

## Stage 5ZZB — the warning named its own escalation condition, and nobody was reading

*2026-08-27, early morning. An investigation and a bounded repair. Nothing restarted, no runtime
trading file touched, and the daily file itself left exactly as it was found.*

### The premise needed correcting first

The report that opened this work said the post-close refresh logged success while the daily file
stayed short. It did log success — and on the very next line it warned, in exactly the right
words: the series still ends on the twenty-fifth, not the twenty-sixth, today's close was not
available yet, and *this is only a problem if it is still true tomorrow*.

So there was no silent success. An earlier stage had already removed that defect from this very
job, after the day it announced coverage having checked nothing.

**The defect is that last sentence.** The warning names its own escalation condition and nothing
in the system looks tomorrow. Tomorrow came, the overnight window ran at ten past one in the
morning, and the condition was true. The day before, the same job at the same minute got the
close and said so. Same code, different luck at the provider.

### What the strict verification was actually verifying

Its own output answers it: seventeen hundred labels compared through the end of 2024. It is a
drift check over settled history — it fails when the regime labels move or cannot be verified,
and it says nothing whatever about whether last night's close arrived. A run could append nothing,
verify perfectly, exit zero, and leave the series a day short of what the next morning asks for.

Provider failures are not swallowed, and that was measured rather than assumed: an invalid key
exits non-zero and leaves the file untouched, and an empty fetch records an unknown that strict
mode fails on. The job was honest about the thing it checked and silent about the thing that
mattered.

### Why the file is short, proved against a copy

Running the same command against a temporary copy — the production file's checksum identical
before and after — fetched the missing day immediately. **The provider has it now.** It did not
at twenty past four yesterday afternoon, which is what the warning said.

Everything else was refuted: not a wrong path, not a skipped write, not a clock problem, not a
holiday.

### The contract, changed

Coverage is now a first-class answer with four states and its own exit code, distinct from the
drift failure — because a data-supply gap and a history that moved under you are different
problems with different owners, and one exit code for both leaves an operator unable to tell
which they have. The caller names the day it needs; the job says whether it is there.

The post-close job now names that day, so the shortfall arrives as a job status rather than as a
line somebody has to be reading at the time. That takes effect at the next restart, and nothing
is worse in the meantime, so no restart is asked for here.

And the missing half — the reader for tomorrow — is now the operator's own status command, which
says the thing in words: *the SPY daily file is missing the twenty-sixth; it ends on the
twenty-fifth; the sleeves that run before the quarter-to-two pre-flight will refuse on stale
daily context until the refresh is re-run.* A machine-readable flag is true and tells nobody what
to do. A named file and a named date do. It asks the freshness module for the requirement rather
than restating it, because a second copy of "which day is needed" drifts from the gate that
actually refuses.

It does not blame the window that passed. The overnight window observed every one of its
twenty-two slots and decided in all of them; the daily file being short is a separate fact about
the inputs, and a test holds the wording to that.

### A defect of mine, found by walking into it

Chasing the consequence turned up something worse than the stale file. The two new morning phases
**never evaluated freshness at all** — measured, the gate simply did not run for them. The stage
that built them had put their early exit before that check, bundling freshness in with the
position-taking machinery on the reasoning that a decide half takes no position.

That reasoning does not reach freshness. It is not a statement about positions; it asks whether
the inputs are current enough to decide on, and that is as live for a half that writes down an
intention as for one that books a trade. Left alone, this morning's first-ever decide phase would
have recorded an intention computed from a two-day-old regime label, in a record saying nothing
about it.

Corrected. Freshness now runs for those phases and it binds: stale inputs make the phase record
its refusal instead of an intention, the day classifies as incomplete, and a counter can no longer
reach five clean days through days nobody would have traded on.

### Which means this morning's phases would refuse too

That corrects something written earlier in the same report and had wrong. The quarter-to-two
pre-flight runs *after* both morning phases, so it cannot help them today. Unless the series is
refreshed before half past nine, the first run of the new phases records a refusal.

That is the correct outcome, and it is not the outcome anyone was waiting to see this morning —
which is why it belongs in a sentence rather than a table.

It also widens the structural fact: it is not only the overnight sleeve that runs before its own
pre-flight. Everything before quarter to two depends on the previous evening's refresh having
landed, and that refresh is by design allowed to come up empty, because the provider is not
always ready when it is asked. Closing that means either a retry in between or accepting the
occasional refusal — a change to production scheduling, and an operator's decision rather than
this work's.

### Where the route stands

The gate has not moved: orders remain impossible, the same two blockers stand, the order journal
is absent. The daily file is exactly as it was found — refreshing it writes production data, so
the command is written down and left for whoever decides to run it.

---

## Stage 5ZZC — a ladder, and the measurement that stopped it becoming an alarm nobody reads

*2026-08-27, early. The retry schedule built and tested; the morning watch still ahead of the
clock. Nothing restarted, no runtime file touched, and the daily file left exactly as the
operator's manual refresh left it.*

### The measurement that shaped the design, taken before any of it was written

The obvious way to close yesterday's gap is to try again later. The obvious way is also the one
that would have made things worse, and one measurement said so before a line of it existed.

A retry with nothing to do — the *successful* case, the one that happens on every good day —
fails. The series already ends at today, so the update returns early without fetching anything,
and its verification result says exactly that: nothing was fetched, so nothing was compared,
which is honest and is not a pass. Strict mode then fails on it, correctly, for the run it was
written for.

Two retries a day, each reporting a failure on every day that went well, is an alarm that fires
when nothing is wrong. This project has already written down what happens to those: people learn
to ignore them, and then the one real firing goes unread too.

So a retry asks before it works. If the day it was sent for is already there it says so and
stops — no fetch, no key, no verification. Proven by running it with a deliberately invalid key
and watching it exit cleanly without ever reaching the provider. Only the retries do this; the
first run of the evening still verifies the labels even when the day is already present, because
checking them is part of what that run is for.

### Three rungs, and four things they can say

Twenty past four, quarter to five, quarter past five. Each names the day it needs, so the answer
travels in the child's exit code rather than in a line somebody has to be reading at the time.

Four outcomes, kept apart: it worked; a later rung rescued it; nobody has the day yet; the run
itself broke. The rescue message is a warning rather than a note, deliberately — a ladder that
quietly saves the same failure every evening is a schedule that wants moving, not a schedule that
is working. And the final rung is the loud one precisely because it has no successor to defer to:
it names the sleeves that will refuse in the morning, which is the actionable half.

The schedule grows by exactly two jobs in every mode, and the rungs appear in the legacy schedule
too, because the daily regime file was never Track 1's private input.

### A hole made and closed in the same hour

In the mode meant to avoid side effects, the first version judged itself against a file nothing
had touched and reported a failed refresh for a command that was never sent. A false alarm
invented by dry-run. It was caught by writing the test for it rather than by reading the code
back.

### The daily file, kept apart from the slots

The status command and the dashboard both now carry the daily file as their own line, and it says
whether the day the next session needs is there, in those words. Not folded into the slot
verdicts — and the reason is on the record from yesterday: the overnight window passed every one
of its twenty-two slots while its per-slot diagnostics said the inputs were stale. Two true facts
about different things. Showing the second as the first sends somebody to inspect a window that
worked.

The dashboard's bidirectional pin caught the new row the instant it was added, which is the
second time that pin has earned itself this week.

### The morning watch is still ahead of the clock

It is half past six. The two Calm phases run at half past nine and just after ten, and they have
not run. That is written down as pending rather than dressed up, and the state they will be
compared against is recorded now: the daily file covering the day it should, the slot table
matching the code, no order directory, no intent stream, an empty trade log, and the book and
checkpoint sitting where the overnight window left them.

What the deciding phase must show is a written intention or an explicit statement that the rule
found nothing — silence being the one outcome that is not evidence — with no price of any kind in
it. What the observing phase must show is that it read the earlier record, priced the reference
at the ten o'clock open, and derived the stop from that rather than before it.

And there is now a way to tell a genuine quiet day from a data problem without anyone having to
judge: a no-setup record means the rule looked and said nothing, a freshness refusal means the
rule was never asked, and no record at all means the phase did not run. Today the daily file
covers what is needed, so a freshness refusal would be a surprise worth chasing rather than the
expected outcome it would have been yesterday.

### The restart

Required, for the rungs to exist anywhere but in the source. The running scheduler built its
table before dawn and holds the single old job. Nothing is worse in the meantime — this evening's
refresh will behave exactly as it did yesterday, and the status command will say if it leaves the
file short.

The window is the hour between the midday audit and the afternoon pre-flight, which is measured
rather than chosen: sixty-five minutes with nothing scheduled in them, and late enough that both
morning phases will already have been watched. The command was checked rather than assumed — the
flag the running process carries is the default on that path, so the replacement starts
identically. It is not run here.

---

## Stage 5ZZD — the last look, and the Monday nobody was covering

*2026-08-27, still early. One job added to the schedule and the tests that hold it. Nothing
restarted, no runtime file touched, the daily series read and left alone.*

### Two questions that look like one

The evening ladder asks for the day that has just closed. A job at a quarter to one in the
morning asks something different: the day the sleeves about to run will demand. From Tuesday to
Friday those have the same answer and the difference is invisible. On a Monday they do not — the
day being demanded is the Friday, and the last evening attempt ran at quarter past five on
Friday, thirty-one hours earlier. Nothing in between has ever looked.

That Monday gap is what the new job is for. The weekday cases are cheap insurance; the Monday
case is the hole.

It guards more than the overnight window. Everything that runs before the afternoon pre-flight
reads this file — the overnight window and both morning phases — and every one of them refuses
if it is short. Yesterday taught that, and it is written into the failure message rather than
left for someone to work out.

### Asking rather than restating

The day it needs comes from the freshness module, not from arithmetic done locally. A second
copy of "which day is needed" drifts from the gate that actually refuses, and then the job
reports everything fine about a morning the gate is about to stop.

And the calendar it reads is the market's, not the machine's. The helper for that carries its own
scar in its docstring: on any machine west of the market the overnight slots land on the previous
local date, with the day it cost recorded. A job running at a quarter to one is exactly where
that bites, and it would have asked for the wrong session by one day precisely when it mattered.

Both choices are held by a test that reads the job's own source and fails if either is swapped
out.

### Three things it can do, and only one of them is loud

If the day is already there it says so and stops — before the command is even built, so no fetch,
no key, and no way for a good night to report a failure. That short-circuit is not decoration: it
is the same one that stopped the evening retries failing on every day that went well.

If the day arrives at this last look, it says so as a warning rather than a note. A last chance
that keeps rescuing the evening is an evening schedule that wants moving, and a quiet success
would hide that.

And if the day is still missing, it is the loudest line in the chain, because nothing after it
looks before the sleeves do. It names the file, the day, who it stops, and the command to run —
and it wears its own label, so the same shortfall reported at five in the afternoon and at a
quarter to one in the morning cannot be mistaken for each other. The first says a morning is at
risk. The second says the morning is lost unless somebody acts now.

### A pin broken and repaired in both directions

Yesterday's work asserted the whole schedule's size, and this work broke it by adding one job
that has nothing to do with what that test is about. That is the anti-pattern already on this
project's record: a check that fails for an unrelated reason teaches its reader that the failure
is noise.

Repaired as a property — the ladder is its three named rungs, in every mode — and the equivalent
check written for this work was rewritten the same way before it had the chance to rot. A job
added tomorrow leaves both alone.

### Two mutations and two guards, told apart

Replacing the calendar so the requirement becomes the session's own day, and so the holiday stops
being skipped: both turn the matching tests red, and both are real mutations.

The other two are not, and are labelled so. The branches they protect live inside a closure that
cannot be reached from outside to be broken, so they assert something about the source instead —
that the final message is still an error rather than a note, and that the comparison deciding
whether to act has not been inverted or narrowed. That catches an edit, not a behaviour. It is
weaker, and saying which is which is cheaper than letting somebody count four of something there
are two of.

### The restart

Required, and it is the same restart the retry ladder is already waiting for. One will bring both
live. Nothing is worse in the meantime: this evening behaves as yesterday did, the status command
says whether the file is short, and today's file already covers what this morning asks for.

The window is the hour between the midday audit and the afternoon pre-flight — measured, and late
enough that both morning phases will have been watched first.

---

## Stage 5ZZE — the account check was vouching for an account that no longer existed

*2026-08-27, mid-morning. A new baseline layer, one read-only look at the broker, and one record
written. Nothing restarted here, no order path built, and no shadow or dashboard evidence
cleared.*

### The measurement, taken before anything was written

The account check that guards this route had passed the previous morning and was still inside its
own twenty-four-hour window — under twenty hours old. The equity it carried was nine hundred and
ninety-six thousand, against a stated baseline of two hundred and fifty thousand. Three hundred
per cent away. And no currency was recorded anywhere in the row.

The paper account had been reset underneath a pass. The check's freshness window is about
positions and orders, and a reset changes neither, so it went on saying "flat and safe" about an
account that no longer existed and nothing in it could have said otherwise.

Both books were genuinely flat, then and now. Flatness was never the problem. **Identity was.**

### And the obvious way to read the balance could not have helped

The broker wrapper's equity call returns a bare number. Its own docstring says it accepts any
currency, and the code prefers a base figure, then whichever of the two it recognises the broker
happens to list first, then anything at all. A baseline built on it would record two hundred and
fifty thousand for an account holding that many Canadian dollars, and nobody could tell
afterwards.

So the new probe reads the account values directly and keeps every currency-tagged balance, with
the label attached to the number all the way into the record. A number whose unit was lost is the
whole defect.

### What the account actually said

Read-only, on a client identity distinct from every other one this project connects with, and
stated out loud before connecting: two hundred and fifty thousand eight hundred and seventeen US
dollars, a single currency, no positions, no working orders, both books flat and route-stamped.
Eight hundred dollars above the expected figure — a third of one per cent — and comfortably
inside the band.

Which confirms the finding exactly: yesterday's record said nine hundred and ninety-six
thousand; today the account holds two hundred and fifty.

### The contract, decided rather than left to judgement

Not the expected currency, or nothing in the account, or a balance a quarter away from what it
should be: those are failures. Between five and twenty-five per cent away is a warning — plausible
but not expected. Inside five per cent is a pass, and five per cent of two hundred and fifty
thousand is twelve and a half thousand: wide enough for fees and marks, narrow enough that a
mis-funded account cannot hide in it. Anything unread is unknown, and unknown is never flat and
never funded.

Only a pass opens the gate. A warning refuses too — the difference between the two is what an
operator does next, not what the gate does, because a gate with a maybe in it is a gate somebody
argues with.

The books are consulted through the existing check rather than read again here. Two
implementations of "is it flat" is how they come to disagree on the morning it matters.

### Where it lives, and what it never claims

Beside the route's other runtime evidence rather than in a report, because a baseline the gate
cannot read is not a baseline. Append-only, so "when did this account last look right" stays
answerable. And every row carries the caveat this project has kept since the shared login was
first noticed: zero positions is attributable to every route, and a non-zero count is
attributable to none.

### The panel, checked against the process rather than the file

Its own block and its own row, apart from the shadow evidence and apart from the slot verdicts —
the third separation this panel has needed stated, and the reason is the same each time.

And a mistake worth recording. The scheduler and the backend had been restarted mid-work, and
every file this stage touched was written a quarter of an hour afterwards. From the file times
alone the conclusion was obvious: the running backend could not be serving the new block. Asking
it directly returned the block, correctly filled in. An inference from file times is not a
measurement of a process — which is the lesson two stages back, applied here to its own author.

The same request confirmed the historical evidence survived the account reset untouched.

### Two faults in the new code, both found by trying to break it

The line that reports the baseline to an operator formatted the balance unconditionally, and
raised on a passing record that carried no account block — which would have taken the whole
readiness call down with it. A reporting function that can crash turns a mild problem into no
report at all.

And a constant that looked like the setting was not one: the age limit was written into the
function's signature, evaluated once when the function was defined, so changing it changed
nothing and a stale record still read back as a pass. Both were found by mutations rather than by
reading, which is the argument for writing them.

### Where the route stands

Orders remain impossible and the same two gates block. The account is now proven rather than
assumed, and that proof expires in twenty-four hours by design. The restart the two previous
stages were waiting for turns out to have happened already, so the evening retry ladder and the
overnight last look are both live. The morning phases have still not run.

---

## Stage 5ZZF — the page was subtracting across a currency boundary, three days late

*2026-08-27, mid-morning. Source, tests and documents. Nothing restarted, no runtime evidence
touched, and no broker asked — the already-served interface had everything needed.*

### What the page was saying, and the two reasons it could

One line under the equity header read: the broker account holds nine hundred and ninety-six
thousand, and is down three and a half thousand since the eighth of July.

Both halves of that were wrong, and for different reasons.

The subtraction crossed a currency boundary. The starting figure carries its own note saying it
was recorded in Canadian dollars; the current figure carries no currency at all. The difference
between them was printed with a dollar sign, on a page where every other money figure is US
dollars, about an account that now holds US dollars.

And the number it was drawing from was three days old while the page had no way to know. The
payload's envelope reported that its next update was not expected yet — not that it was stale —
because in this mode the legacy runner is never scheduled, so the expected time keeps sliding
forward and nothing ever calls the payload old. The page's own staleness guard, which watches for
"missing", "unknown" or "stale", therefore never fired once in three days. **A freshness model
that assumes its producer still runs cannot report a producer that has stopped.**

### What is authoritative now

The account this route would start from comes from the recorded baseline, which was proven
against the broker the previous stage. A live broker reading sits beside it as a separate,
labelled fact and is allowed to differ by ordinary drift — when measured, the two differed by
twenty-seven cents, which is exactly the drift the label exists to permit.

The legacy runner's own last view may still appear, but only under its own name, and only with
its age attached. And when it differs materially from the baseline the line says so outright and
turns negative, rather than leaving two numbers on one page with nothing between them.

The account line no longer asks the runner whether it is fresh. It asks how old it is — which is
a fact, where the freshness is, in this mode, a fiction.

### The open issues were relabelled, and not one was removed

Five in, five out. Each keeps its status, its evidence, its occurrence count and its place in the
list. What each gained is a sentence saying whose problem it is: three of them compare the legacy
paper ledger against broker statements and read no Track 1 artefact at all, which is now written
on the chip and in its tooltip rather than left for a reader to work out from a title.

The scope is derived from the issue's own key rather than from a list of titles kept beside it —
this project already has the scar for a list maintained next to the thing it describes.

And the reader now declares, in the payload, that it does not decide what blocks anything: the
route's gate is the only thing that says what stops orders, and a log parser holding a second
opinion is how two answers come to disagree.

Visually it is one chip in the badge lane that already existed, the same shape as the status
beside it, with the legacy and debt lanes deliberately quieter so they stay visible without
competing for the eye with a live incident.

### Whether the page needs restarting, measured rather than assumed

The backend does, for the issue chips only, and the reason is worth writing down because it
corrects the previous stage.

One reader is imported at the top of the application and bound when the process starts; the other
is imported inside its request handler. The first cannot see an edit made after boot. The second
was picked up — but only because nothing had called that endpoint between the restart and the
edit, leaving the module unloaded.

So the previous stage's conclusion that no restart was needed was true for the block it measured
and too general as a rule. It was served by the luck of import ordering, not by any reload
mechanism, and the same cannot be relied upon.

The page's own script and styles are static files; a refresh is enough for those. Only the
interface field needs the process replaced, and nothing is worse in the meantime — every issue is
still listed, simply without its chip.

### Four faults found by running the tests rather than reading them

A substring assertion found the old label inside the comment written to record that the old label
was wrong. That trap has now caught this project four times, so the reader strips comments — and
a second assertion insists the explanatory comment is still there, so the record cannot be tidied
away either.

A slice taken with a fixed length ran past the function it was about and into the next one, so an
assertion about one piece of code was reading another's.

A cached reader turned a deliberate breakage into no change at all: the answer was memoised, the
builder was never called, and the test passed while proving nothing.

And in the production code, one function was calling another for its side effect and then reading
the original list again. That works while the second function edits in place and fails silently
the day it returns something new — which is precisely what the breakage did, turning a wrong
answer into an error.

### Where the route stands

Unmoved. Orders remain impossible, the same two gates block, and nothing here touches either. One
pre-existing test was rewritten rather than deleted: it had pinned the very behaviour this work
removed, including the cross-currency subtraction, and its underlying concern — that a sharp
divergence must be visible rather than averaged away — is now measured from the baseline instead.

---

## Stage 5ZZG — the step that sends now exists, and the proof that it is shut

*2026-08-27, late morning. No order was sent, no approval was set, no confirmation was written,
and the order directory is still not there. Nothing was restarted.*

### Why building it now, rather than when it is needed

Everything an order needs was already built — the thing that talks to the broker, the ledger that
records what was attempted, the mapping from a decision to an order, the stop that goes with it —
and nothing called any of it. That was safe, and it was also a hole: *"the wire is missing"* is
not a state anybody can write a test about. A wire built later, under the pressure of wanting to
start, is a wire built without the tests written here.

### The shape, and the one thing that makes it provable

The slot writes its coverage row, and only then offers its decisions to a single function. If the
gate is shut that function returns before importing anything at all. If it is open it builds the
executor, hands it the broker the caller already holds, and sends the decisions the cap gate
admitted.

**The gate check sits above the import**, and that ordering is the contract rather than a matter
of taste. A test run in a separate process asserts that after a closed-gate call the order layer
is not loaded — which only means something while the import stays below the check — and a second
test reads the function's own structure and pins the order, so the first cannot quietly stop
proving anything.

It never builds a broker. The path that fetches bars already holds one, and the send uses that
same object; armed with none it refuses rather than making a second. A second connection on a
second identity is how this project once lost six entry slots in a morning, and an order path the
gate does not govern is worse than no order path at all.

And it decides nothing. Not what to trade, not how large, not whether a candidate was admitted —
the word for "admitted" is asked of the layer that owns it rather than spelled again here.

### A claim replaced by a measurement

The shadow branch used to end by printing that it had made no order calls. That was true every
day it appeared, and true because nothing *could* — not because anything had counted. A claim
nobody measures goes on being printed after it stops being true. It is now the send pass's own
summary, and on a shut gate it says so in words rather than as a number.

### Failure is never a refusal

If a send throws, the ledger records the outcome as unknown and the error travels outward. This
counts it as unknown, never as refused, marks the run fatal, and the process exits with its own
code carrying the sentence that matters: the order may be live and simply invisible, and that is
not the same thing as an order the broker declined. A slot with two decisions reports both; one
bad send does not hide a good one.

### A bug I put in, and the measurement that bounded it

I added the new argument to the wrong function. It landed on the explanation writer instead of
the slot, so the slot was being handed arguments it did not accept — and **every shadow slot
would have crashed**.

It was found by running the real entry point rather than by reading the patch back. And the
damage was bounded by asking the log rather than the clock: the last shadow slot before the broken
window had finished at two minutes past ten, the next was not due until twenty-five past, and
today's scheduler log holds no Track 1 failure line at all. No live slot hit it.

### What the morning phases actually did

Two earlier stages left this pending, and it has now happened. Both halves of the morning sleeve
ran for the first time in production, and **both refused** — the deciding one at half past nine,
the observing one just after ten, each recording a refusal in the intent stream and each leaving
the day classified as incomplete rather than counted. That is the machinery working: the refusal
is the record.

It was not the daily file, which had been repaired before the window and does not appear among
the reasons. The gate says the session's own bars were not in the frame it was handed. **Why is
not traced here and is not guessed at** — it is the next thing to measure, and it belongs to a
stage that can measure it.

While diagnosing it I misread the hour and briefly took those rows for my own test runs. They are
the scheduler's, and the row timestamps say so. Corrected by reading them rather than trusting a
sense of the time.

### The old promise, restated rather than dropped

Four tests held that nothing in production reached the order layer, and that the slot carried no
gate. Both were true while the wire did not exist and both are now false on purpose. Weakening
them to "anyone may" would have thrown away the only thing that would ever notice a second road
to a broker, so they now say what is actually the case: the order layer may be named by exactly
two modules, one walled behind a broker that refuses everything and one gated behind the check;
and the slot's gate argument exists, defaults to shut, and the scheduler passes nothing.

The second is a better test than the one it replaced. Nobody was watching that default before,
because there was no default to watch.

### Where the route stands

Orders remain impossible. The same two gates block, the approval flag is unset, no confirmation
exists, and the order directory has never been created. What changed is that the last missing
piece is now present and held shut by something that can be tested, rather than absent and held
shut by not existing.

---

## Stage 5ZZI — the morning the feed went quiet, and the field that could not say so

*2026-08-27. No orders, no approvals, no confirmation file, no orders directory, nothing
restarted, no runtime evidence touched. One read-only connection, reported before it was made.*

### What the previous stage left open

Both halves of the morning sleeve ran in production for the first time and both refused. The
record said the session's own bars were not in the frame the gate was handed, and that was as
far as anyone had traced it.

### The answer, and it is a short one

There were no bars. Not dropped by the join, not filtered, not too late — never delivered. The
frame the gate received ended at yesterday's append boundary because nothing had been laid on
top of it, and every condition the gate reported is a restatement of that one fact.

The refusal was correct, and it is worth saying plainly: the machinery did the right thing all
morning. It asked, it was given nothing, it refused, and it wrote down that it refused.

### Not the sleeve, and not the schedule

The overnight sleeve fetched normally for its entire window, thousands of bars a slot. Then
between five to three and five past three in the morning the feed stopped answering, and it has
not answered since — the morning sleeve, both phases, and the sleeve after it, all zero. The
route's own records hold the boundary to within ten minutes, and the day before, the same
instruments fetched without complaint. The contract roll is nowhere near.

### What the feed was actually saying

A read-only request, on an identity kept apart from anything that trades, got a named answer
back: the historical data service is declining because this account's session is held from
another address. One login at a time, and something else is holding it. Nothing about this
route caused that and nothing in this route can fix it.

### The part that is ours

The refusal was correct. **The silence was not.**

The layer that talks to the broker returns an empty frame when the market was quiet, and an
empty frame when the request failed. The library underneath does not raise on this class of
error — it announces it on the side and hands back an empty list. So the two arrive as the
same value, and by the time anything downstream could write the difference down, there is no
difference left to write. Every record for three days said *there were no bars*, when the truth
was *the service declined to give any*.

This is the failure family this project keeps rediscovering: **an empty answer standing in for
an error.** It is the same shape as the process scan that answered "none running" and "I could
not look" with the identical empty list, and it fails the same way — open, quietly, in the
direction that looks fine.

The fix is three short hops and nothing else. The thing that fetches now listens while its
request is in flight and keeps what the feed said about it; the joined frame carries that
along; the record prints it, or prints nothing at all when the feed genuinely had nothing to
say. Those two must not print the same, and that is the whole change.

It is deliberately deaf to everything else the feed chatters about — a record that collected
all of it would fill with connection notices and stop being read — and it is soft in every
direction that could hurt: a broker with no session, a listener that will not attach, an
attribute that throws. All of them leave the fetch exactly as it was. A diagnostic that can
break the thing it is watching is worse than no diagnostic.

**No requirement, threshold, window or strategy rule was touched.** Shadow and paper still read
the identical path.

### Proved both ways, offline

With no provider and no network, the refusal reproduces exactly — same conditions, same names,
from the same code. And with the fetch answering in the shape it is configured to ask for, both
halves **pass**. That second run is the one that settles it: the rule is not impossible and the
clock is not wrong. It passes the moment the bars exist.

One detail is worth keeping, because a shortcut here would have manufactured a bug. History on
disk stops at the early-afternoon append boundary, so the *previous* day's closing stretch also
arrives on the live fetch — which is why the request asks for two days rather than one. A test
offering only today leaves a coverage complaint standing on yesterday, and would have "found" a
defect that is really the test's own shape.

### What is verified, and what is not

Kept apart on purpose. Verified: that every fetch after three in the morning came back empty,
where the boundary sits, what the gate reported, and what the read-only request was told.
Inferred: that the same named refusal was the answer to the two morning fetches *specifically*.
The request that got the name ran later, and those two records cannot say — **because the field
did not exist yet.** The inference is strong, and it is exactly the inference nobody should have
to make. From the next fetch onward the record says it outright.

### What has to happen now, and it is not code

No change here will bring the bars back. Something else is holding this account's session; until
it lets go, every slot will keep refusing — which is the correct outcome, and the day classifies
as incomplete rather than counting. Nothing needs restarting here, and none of the refusals
should be cleared away. They are the record of a day the feed was down, and that is worth
keeping as exactly that.

### Two things the tests caught in my own work

The new field was added to the frame and left out of the thing that hands the frame's contents
onward — a field carried by nobody, which is the same defect one storey up from the one being
fixed.

And the tool measuring the tests silently skipped a third of its own checks. These files use
Windows line endings, so every anchor written with a plain newline matched nothing, and each
skip printed as a line that reads like *we tried*. It proves precisely as much as not running
it. Caught by reading the tool's output rather than its summary line — which is the same reason
this stage exists.

---

## Stage 5ZZH — the biggest number on the page belonged to a different route

*2026-08-27. No orders, no approvals, no confirmation file, no orders directory, nothing
restarted, no trading file written. Read-only calls against the running backend.*

### What the card was saying

At the top of the page, in the largest type on it, sat a figure just over fifty thousand, a
small gain beside it, and a base it was measured from. Every one of those came from the legacy
runner — the equity from a snapshot taken three days earlier, the base from the legacy runner's
own idea of what it started with. The account this route would actually open from, a quarter of
a million dollars proven flat against the broker that same morning, was the small grey line
underneath.

An earlier stage fixed that small grey line. It did not touch the figure above it, and the
figure above it is what anybody sees first.

### The rule now, and where it is decided

In Track 1 mode the headline is Track 1's or it is nothing. It carries its currency in words,
because this same card once subtracted a figure in one currency from a figure in another and
printed the result with a dollar sign. And when the baseline cannot stand — unreadable, or
failing — the card says which and stops there.

That last part is the whole point. Reaching for the other number on the page is exactly what
produced the confusion, and a fallback that fires without saying so is worse than a blank space.

The decision is made in the reader rather than in the page's markup. A policy written as string
interpolation is a policy nothing can test; written as a field, it can be asserted, and it can
be broken on purpose to check that something notices.

### A figure that is correct and would still be misread

The account holds a little more than it was funded with. Showing that difference beside the
headline would be arithmetically right and would be read as this route making money — and this
route has not sent a single order. The gap is whatever the paper account happened to hold. So
the slot stays empty and explains itself on hover, and the legacy runner's own realised figure
and return are held back in the same mode for the same reason: they are another route's day.

### Two things measurement found on the way

The endpoint that serves the legacy runner's state described a payload eighty hours old as
current. Its freshness comes from asking the schedule whether a publication was due, and in this
mode the legacy runner is never due — so nothing is ever late and nothing is ever called stale.
The whole zone dims on that judgement, so it never dimmed. **A freshness model that assumes its
producer still runs cannot report a producer that has stopped.** The legacy contract is left
alone because other panels read it, but this card no longer trusts it: it measures the age
itself, against a line drawn where one missed daily publication becomes a producer that has
stopped rather than one running late.

And the recorded account note still ended with the words "read zero minutes ago" about a reading
taken almost four hours earlier. True when written, and it had walked away from what it
described — the same thing this project has now watched happen to a comment, a stored figure, a
scheduler job and its own measurement from earlier the same day. Anything that needs the age now
computes it when asked.

### The one that would have made things worse

The endpoint loads its reader inside the request, which reads like it picks up a change every
time. It does not — the module is cached — so a backend started before this stage keeps serving
the old shape forever. Asked directly, the running process returned nothing at all for the three
new fields.

Read carelessly, "nothing" is "no", and the page would have stamped **failure across a funded,
reconciled, passing account** the moment it shipped ahead of a restart. A worse lie than the one
being fixed.

So the page separates *absent* from *refused*: a field the backend never sends is not a field the
backend declined. Absent means work it out here from what the old shape does carry; refused means
the backend decided, and that decision stands. This is the second time in two days that asking
the running process corrected an assumption about it — the first time the assumption came from
file timestamps.

**A backend restart is needed** before the new fields appear. The scheduler must not be
restarted and was not.

### The issue list, sorted by whose problem it is

Every issue is still there and the count still counts all of them. They now arrive in three
groups instead of one column: this route's, the shared machinery's, and the old route's. Carried
debt joins the old route's group rather than claiming a heading of its own, and anything with an
unfamiliar label lands in the shared group where it stays visible rather than falling out of all
three.

The chip that used to say "scheduler" now says "shared", because "scheduler" names a component
and the chip answers a different question. And the panel itself now states where its blockers
come from: four of the five open issues belong to the old route, nothing said so at panel level,
and the natural reading was that this route was blocked by five things. It is blocked by two,
and those come from the gate registry — never from the prose of an issue, which cannot open or
close a gate and has twice been written as though it could.

### Width

The longer headline made the card overflow its column at narrow widths — measured, forty-one
pixels at phone width and fifty-nine at tablet. Two rules forbidding wrapping met there, both
written when the headline was shorter and the note underneath held one figure instead of three.
Both now wrap. Wrapping rather than trimming: a money figure with its end cut off still looks
like a money figure.

A small remainder belongs to a tooltip and is identical whichever headline renders, so rather
than blessing it with a number the test asserts the thing this stage is answerable for — the new
headline is never wider than the one it replaced.

### Tests

Every guard above was broken on purpose and every break was caught, including the two about
absent-versus-refused. One did not fail the first time, and the fault was in the test's own
fixture rather than in the code: the figure it was watching for was empty in both branches, so
the test happily agreed with the mutation that deleted the guard. That is twice this week that
breaking something found a test proving less than its name promised.

Four older tests pinned the exact wording of the legacy line, which this stage rewrote so that it
says *why* that figure is not the account rather than only that it is old. They were restated
rather than dropped: the figure still has to appear under its own name, never without its age,
and nowhere outside its own clause — checked by cutting the clause out and looking again. Editing
them needed care, because the one asserting the phrase is absent contains the one asserting it is
present, and doing those in the wrong order would have left a plausible sentence testing
something else.

---

## Stage 5ZZJ — the decision that a person has to make, measured and previewed but not yet signed

*2026-08-27. No orders, no approval, no order directory, no order journal, no scheduler restart,
legacy books read only. One read-only broker connection on an identity kept apart from anything
that trades, announced before it was opened.*

### Where this stopped, and why that is the honest place to stop

Everything except the signature is done. The account was re-measured, the decision was previewed
against the real gate registry, the dashboard now shows the gate's state, and the tests hold every
way it must still refuse. **The file itself was not placed** — the harness declined, and the file
is the one that opens a go-live gate, so rather than reaching for a different tool to put the same
bytes in the same place, the work stops here and asks.

### One gate the machinery cannot close

Every other blocker on this route is a measurement: run the thing, read the answer, the gate opens
or it does not. This one is a decision about the world — either the old route stops trading on this
login, or the new route gets a login of its own — and no amount of code can settle it. An earlier
stage gave it a second half so a signature alone would no longer be enough: the account has to be
observed flat as well. Both halves were checked here, in that order.

### The measurement was stale, and that came first

The status command opened by saying the last account audit was too old to count. That is the
condition under which nothing may be signed, so the account was asked again before anything else
happened: the old route's book empty, the new route's book empty, the broker reporting no
positions and no working orders, and a quarter of a million dollars sitting in the paper account.
The new book carried the right schema and the right route stamp. Everything the decision asserts
was true at the moment it was asserted, and the reading expires in a day.

### What the preview said, including the part nobody wants to hear

It validated. It would release exactly the gate it is for and nothing else. The evidence gate would
still hold, and orders would still be impossible — which is the whole reason signing this is safe.

And then the warning the tool exists to give:

> the old route is **dormant, not retired**. It is quiet because of one flag on the running
> scheduler's command line, and a restart without that flag registers its entry jobs again —
> forty-five of them — while the recorded decision goes on reading as true.

That does not block the decision; it is the operator's call and the operator has made it. But it is
the thing to carry forward, and it is why the running mode is now pinned by a test rather than left
as something everyone remembers. Retiring the old route properly is the switch-over runbook's
ordered procedure, not a command-line flag.

### A contradiction in the instructions, said out loud

The stage asks for the decision to be recorded, and also expects a particular status field to stay
false afterwards. Those are the same file. Recording the decision necessarily flips that field, and
there is no arrangement in which both hold. The reading taken here is that the expectation was
carried over from earlier stages where the file was forbidden outright — and the thing that
actually matters, that orders stay impossible, holds either way and was proved before anything was
written. But it is the operator's call, not something to be quietly resolved in favour of the
convenient reading.

### The gate now appears where the route appears

Until now this gate was printed by the status command and shown nowhere on the page, so an operator
had to leave the dashboard to find out whether the route's most consequential gate was open. It now
has its own block: what was decided and by whom, the measurement behind it with its age and its
expiry, the counts that measurement rests on, and what is still blocking.

Three states rather than two, for a reason this project keeps rediscovering. A file that exists and
does not validate grants exactly what an absent file grants — nothing — and means something
completely different to whoever has to fix it. And whether the gate is actually closed is asked of
the registry rather than worked out from the two halves, because a second opinion computed nearby
is a second thing that has to be kept in step, and a restated sentence has already gone stale twice
on this route.

### The tests, and a wording correction

Several of the stage's test items ask that the decision cannot be *written* without this or that.
There is no writer, deliberately — the module that previews the decision has no code path that
writes anything at all, and says so in its own opening lines. So what is asserted instead is that
the decision does not *open the gate* without those things, tested where that is actually enforced,
with one more test holding the preview to never growing a writer.

Every guard was broken on purpose and every break was caught. Two of them came back at first
labelled as guards that had failed to notice — when in fact the mutation had broken the file's
syntax and nothing had run at all. That label is the worst one available: it reports a sleeping
guard where there was no run to guard. It is the same family as counting an empty collection as a
pass, which this project has now met three times, and the harness names it properly now.

One test caught a fault in itself: the proof that the preview writes nothing built its own file
*after* setting the trap, so the trap fired on the test's own write and blamed the preview. A green
version of that would have proved nothing.

Two older tests failed for a reason unrelated to any of this — they had frozen a list of which
gates were still blocking, and one of those gates had since been opened by its own measurement.
Rewritten as the property each was really about.

---

## Stage 5ZZK — the gate could not see the decision

*2026-08-27. No orders, no approval, no order directory, no scheduler restart, no broker
connection, and no runtime trading file touched.*

### What happened

The operator placed the decision. The file was byte-for-byte what had been previewed, it
validated, and every measurement behind it passed. The status command went on listing the gate
as blocking, and it would have gone on listing it forever.

### Why

The function that answers "what is still holding the order gate shut" took, as its default, a
standing object meaning *nothing has been signed*. So called with no arguments — which is how
almost everything calls it — it answered a question nobody was asking: what would still block if
the operator had never decided.

Exactly one caller in the repository passed the real confirmations, and it was the live-shadow
entry point. The status command, the readiness report, the dashboard, the ledger and the order
executor all took the default. **The operator's decision was invisible to every one of them.**

This is the same shape the project keeps finding: a default value standing in for a real answer,
indistinguishable from the real answer, and wrong only in the case nobody had exercised. It
failed safe — everything that could act on it also read the blind default and refused — but a
gate that cannot be seen to open is a gate nobody can finish.

The fix is one line of intent: with no argument, read what the operator actually signed. An
unreadable or half-parsed file still grants nothing, so the failure direction is unchanged. The
unsigned view is still available to anything that genuinely wants it, and the preview now asks
for it by name — because a preview run while a decision is already in place was otherwise
comparing the signed state against itself and reporting that the candidate would change nothing.

### And while the gate was open on the bench

The decision does not merely claim the account is empty. It claims **this route owns this
login**. Only the first half had ever been checked. So the requirement was widened to cover what
the sentence actually says: the account measurement still has to pass, and now so does the
route stamp on the book, and the account baseline, and the two records have to be talking about
the same account.

Strictly more than before. Nothing that used to be required stopped being required.

### A check that could never have failed

The first version of that widened requirement compared a route and an account taken from the
audit record. Neither is recorded there. Both comparisons were written as *if the value is
present and differs, refuse* — so both were skipped every single time, while appearing in the
list of reasons exactly as though something had been verified.

It was caught by printing the reasons and noticing that two of them had produced no words at
all. The route is now read from the book file the audit itself names, and a missing stamp is a
refusal rather than a shrug.

One comparison genuinely cannot be made yet: the account audit does not record which account it
talked to, so it cannot be checked against the baseline. That is now printed as an unchecked
item rather than quietly counted as a passing one — the distinction this route has had to learn
in four separate places.

### Ten tests that had quietly stopped testing their own names

Widening the requirement changed which measurement the gate consults, and a good number of
existing tests worked by replacing the old one. Their replacements stayed exactly where they
were put — and the gate walked straight past them to the real evidence. Five tests whose names
promise that a decision without a usable measurement still refuses would have gone on passing
for reasons they had not chosen.

All of them were repointed at the measurement the gate now asks for. This is the second time in
three stages that changing a name left a suite green and hollow, and both times it was found by
running the suite against a deliberately broken build rather than by reading the diff.

### Five tests restated, because the world changed

The operator signed, and the gate genuinely closed. Tests asserting that it still blocks were
true only for as long as nobody had decided. They were restated rather than deleted, and one of
them came out better than it went in: instead of "this gate still blocks", it now says the gate
is closed **and never by a signature alone** — take the measurement away and it must come
straight back.

### Two faults in the fix itself, both caught by tests

A path was bound as a function default, so it froze at import and every attempt to point it
somewhere else changed nothing while appearing to. Three tests were quietly reading the real
production file and passing for the wrong reason. This is the identical trap that cost a stage
two days earlier, one module over.

And a test that meant to assert the gate registry does not read the order-approval variable did
so by searching the source for its name — which appears in the registry's own explanatory text
describing what that variable is for. Rewritten to set the variable and check that nothing
moves.

### An unreachable guard, which is worse than a sleeping one

Every guard here was broken on purpose to check that something noticed, and one of them did not
go red. The reason was not that a test was asleep — it was that the code being broken never
runs. The confirmation loader answers unreadable input by returning nothing-granted rather than
by throwing, so the catch-all wrapped around it has no path that reaches it. Rewriting that
catch-all changed nothing, and could not have.

That is worse than a guard that failed to notice. It reads in the source like a safety net, and
a real failure later would find nothing underneath it. The answer was not to aim the break
somewhere easier: it was to make the guard reachable on purpose, with a test that forces the
loader itself to throw and checks the gate still grants nothing. With that in place the original
break turns red, because there is finally a path that runs it.

### Where the route stands

One gate left. The account question is settled, by a decision and by evidence that has to keep
passing. Orders remain impossible, and the thing that holds them is now the only thing that
should: whether the shadow record is good enough to justify one.

---

## Stage 5ZZL — a picture of the window, and the honesty about what is not in it

*2026-08-27. No orders, no approval, no order directory, no scheduler restart, no broker call,
and no strategy, threshold, slot or gate rule touched.*

### Two things had to be measured before any of this could be drawn

**Today's bars are not kept.** The instrument stores are appended once a day, and the live half
of each session is joined on in memory inside the slot's own process and then discarded. So on
the day this was built, the overnight sleeve had fetched and traded off nearly two thousand of
that morning's bars, and not one of them existed anywhere on disk. A chart captioned "today"
would be empty on every ordinary day, which is a chart nobody would look at twice.

So each sleeve draws the most recent session the store actually holds, and says which session
that is — in the summary line and in the payload. Quietly substituting it would make a stale
picture look current, and that is a worse failure than an empty one.

**Nothing publishes a price.** Every rule the sleeves record carries the same note: evaluated
inside the detector, value not returned. There is no entry, no stop, no target, no reference
level anywhere in the evidence. And the regime model hands back a word — there is no score
underneath it, and no threshold to measure a distance to.

Both of those are now said on the page in plain words rather than approximated. A line drawn at
a level nobody published is a line somebody would trade against.

### The chart library that was asked for, and was not added

The instruction named a specific charting library, and the first thing to establish was whether
this repository can take a frontend dependency at all. It cannot, in the way that matters: there
is no package manifest, no installed modules and no build step anywhere; the operator's page
loads two scripts and both are its own. Exactly one page in the tree pulls a library off a public
CDN, and the code that uses it already guards for its absence and falls back to a hand-drawn
shape.

Putting a third-party script tag on *this* page is a different proposition from putting one on a
report page. This is the page somebody watches a live route on, and a remote host becomes a
dependency at precisely the moment something has gone wrong. Committing the library into the
tree instead is a supply-chain decision that belongs to the owner rather than to a stage.

So the candles, the crosshair, the tooltip, the price scale and the time axis are drawn here, in
the same idiom as the sparkline the shared code already contains. The cost is honest and it is
the whole cost: roughly two hundred lines that a library would have supplied. The payload was
shaped to match what that library consumes, so swapping it in later is small.

### The regime is recorded, not computed when the page asks

Labelling the series takes eight and a half seconds. An endpoint that did it on demand would
freeze the operator's page for that long after every daily refresh and on every cold start. So
it joins the pattern the rest of this route already uses — the account check, the flat-book
check, the label-drift check are all built the same way: something measures, writes down what it
saw, and a reader reads the record.

It fails to *unknown*, never to a label. The calm regime is the permissive one, and a labeller
that could not run must not read like one that answered "safe". And the record carries the
window it was fitted over, because a label without that is a number nobody can reproduce — a
mistake this project has already made once with a frozen metric.

### Four things measurement caught that reading would not have

**Two meanings of one word.** The summary counted its own markers and reported a sleeve as
having observed every slot, while the window ledger recorded six fewer — because a refused slot
leaves a record in one place and is not an observation in the other. Two definitions of the same
word on one page is how somebody comes to trust the wrong one. The count now comes from the
ledger and the markers only draw.

**A data problem reported over a working feed.** Anything the provider said was being treated as
a refusal, so the afternoon sleeve — which had simply not opened yet — was painted as a feed
failure. Not having looked is now distinct from having looked and been refused.

**A whole panel rendered unstyled.** The label-and-value rules were written for the runtime
panel only, so the regime panel reused the markup and inherited none of the styling: its labels
came out at the wrong size and on the same line as their values, running two words together.
Found by comparing the computed styles of the two panels, which a screenshot would have shown
and a code read would not.

**And the panels were wired into the wrong place.** The calls to draw them landed inside the
handler that runs when somebody clicks an issue row, rather than in the loop that runs after
every poll — so the whole feature only appeared if you clicked something unrelated first. The
browser tests found it by timing out waiting for tabs that were never drawn. Reading the file
would have shown the calls present and looked correct.

### What it answers

Which slots ran and which refused, what price did while the sleeve was allowed to act, whether
the entry levels are known — they are not — and what regime the model last labelled, with how
old that reading is. It deliberately does not repeat the rule-by-rule detail the job panel
already owns.

Nothing on it is computed by the page. Every value is decided somewhere else and rendered here,
and where nothing was decided it says so.

---

## Stage 5ZZM — the same facts, in the words somebody would use

*2026-08-27. No orders, no approval, no order directory, no broker call, nothing restarted by
this stage, and no strategy, threshold, window or gate rule touched.*

### The thing that happened while this was being written

A test from the B1 stage went red during the regression run, and it was not a test problem.
Between that stage and this one the scheduler was restarted — by somebody else — into the mode
that registers the old route's entry jobs. So the login the operator signed a decision about,
declaring the old route retired on it, now has that route's entry jobs scheduled against it
again, while the gate goes on reading the signed decision as true.

The preview written for that decision said this would happen, in almost those words: the old
route was dormant because of a flag on a command line, not because it had been retired, and a
restart without the flag brings it back while the record stays as it was.

Nothing can execute — the evidence gate still holds and no order path is armed. But the signed
claim and the running configuration disagree, and that deserves a decision rather than a
footnote. **The test was left red on purpose.** It is the only thing on the route that notices
this, and adjusting it to pass would have removed the alarm and left the condition.

### What the polish actually was

The previous stage got the contract right and drew something honest. It also read like a debug
panel: a comma-joined sentence where the rest of the page uses small badges, the same phrase
about missing strategy levels printed twice on one panel, slot markers dropped on the floor of
the chart, and a regime row quoting a log line at the reader.

None of the facts changed. The summary is now a row of badges in the shape the page already
uses everywhere else, so nobody is learning a second badge language two panels down. The chart
was given room on its left edge, where candles had been running into the border, and the slot
markers were lifted onto their own baseline above the time axis — which is the difference
between a row of outcomes and stray ink. A key underneath names the marker colours, laid over
the chart's fixed box rather than added below it, so a sleeve with bars and one without still
occupy the same height.

The regime label became the anchor of its panel, at a size that says it is the most important
thing there without claiming to be the most important thing on the page. It is never shown
alone: the date it describes and the age of the reading sit beside it, because the same word
from a reading nobody refreshed in three days is a different statement.

### The words

The phrase about strategy levels was accurate and named an internal idea — "exposed by sleeve
evidence" — that means nothing to somebody deciding whether to trust a chart. It now says the
levels are unavailable, and a tooltip says what the chart is still showing, so the absence does
not read as breakage. The regime panel stopped quoting its own record's sentence and now says
the check passed, how many days were compared, and that nothing drifted.

A handful of internal tokens travel from the route's records straight into a tooltip, and they
are now translated in one place. A token nobody has translated yet is shown with its
underscores removed rather than folded into "unknown" — a phrase that has not been given words
should be visible so somebody gives it words, not swallowed where it disappears.

And the footer is empty on the ordinary path, because it had been restating what the badges now
carry.

### Three faults introduced here, and measured back out

The new regime heading overflowed its panel by a wide margin at two of the three widths, because
a grid child that is never told it may shrink refuses to go narrower than its contents — and
this one holds a large figure and two clauses.

Two tooltips pushed their panels sideways: the rightmost cell of a fact grid, and the last badge
in the summary row, both open their bubble past the panel edge. The page already solves this for
the header strip, so the same flip was reused rather than a second remedy invented.

The second of those is worth keeping in mind. It appeared **only after** the shorter wording let
the badges reflow onto fewer lines — this kind of overflow moves when the text moves, which is
why the three widths are measured after every copy change and not once at the end.

And the browser fixture had a copy of the old phrase typed into it, so the layout probe went on
reporting the old wording as visible after the backend had stopped emitting it. It reads the
constant now, and cannot drift from what the page is actually handed.

### Six older tests restated

All six pinned wording this stage deliberately changed, and each kept the thing it was really
about: the panel still says the levels are missing, the refusal is still findable, the empty
state is still one intentional state, and the absent score is still named rather than left out.
None was weakened.

---

## Stage 5ZZN — the guard that pushed the operator into the unsafe mode

*2026-08-27. No orders, no approval, no order directory, the confirmation untouched, the
scheduler not restarted, and no strategy, slot, threshold or evidence rule changed.*

### What actually happened

A guard in the operations tool refused to start the route's clean validation mode **because the
operator's decision file existed**. Its reason, written into the code, was that the file arms
the route — and that was true on the day it was written, when a signature was the only thing
between this route and an order.

It stopped being true twice over: once when a measured evidence gate was added, and again when
the account decision itself was given a measured half. Neither change came back to this guard,
and nothing failed loudly when its premise expired.

So the sequence ran: the operator signed, the clean mode began refusing, and the scheduler was
restarted with no route flag at all — which registers forty-five of the old route's entry jobs
on the very login the signature had just declared retired. **The guard pushed the operator out
of the only safe mode and into the unsafe one.**

That is worth naming precisely. It was not a missing check. It was a check whose reason had gone
stale, still enforcing confidently, and the enforcement pointed the wrong way.

### Measured before it was touched

The running scheduler's own command line carried no route flag, so forty-five entry jobs were
scheduled and none of this route's seventy-one were. An earlier probe had printed that command
line one character at a time, which — if it had been true — would have meant the mode reading
was confused and the whole alarm a false positive. It was checked rather than assumed: the
reading is sound and the command line is real.

A second thing surfaced while reproducing. The status command was reporting the schedule as
current, quoting a registration count from the log — and that line had been written by a
process that had already exited hours earlier. The scheduler running now had registered none of
them. A freshness check that compares the code against a dead process's log reports on the wrong
system with complete confidence.

### The fix, and why it is the smaller one

The guard now asks whether an order is **actually possible** rather than whether a file exists,
because the gate registry reads that file *and* the measurement behind every blocker — it is the
part that knows. The half of the old guard that was right is kept: if every blocker really is
clear, then a shadow start is starting something nobody asked for. And the question fails
closed, so a registry that cannot be read makes the guard refuse rather than wave a start
through on an answer it never got.

No new mode was invented. There was nothing wrong with the clean validation mode — it already
registers none of the old route's entry jobs, keeps the old route's safety sweeps draining its
book, and cannot send an order. A second mode name would have been one more thing to explain and
one more thing to keep in step.

### The guard that had never existed

Nothing had ever asked whether starting the *old* route was safe. That answer stopped being
"always" the moment somebody signed a decision saying this login belongs to the new one.

A start that would register those entry jobs is now refused, and the refusal names four things:
what the decision says, what this start would do, which mode to use instead, and what to do if
the old route genuinely must run again — retire the decision, rather than leave a signature
saying something the configuration contradicts.

It refuses **before anything is stopped**. A restart kills the running process first, and a
guard that fired after that would leave the operator with nothing running at all. The transitional
mode is deliberately not exempt: it keeps every one of the old entry jobs, which is exactly the
collision the account decision exists to prevent.

Both guards count those jobs from the same table the scheduler's own removal step reads, so the
number in the refusal cannot drift away from the number actually registered.

### Status says which it is

Compatible, incompatible, or unknown — and the third is the one that matters. A mode nobody
could read is not a compatible mode, and printing it as one would be the same fail-open this
route keeps finding in other clothes. When it disagrees, the status prints the conflict and the
exact command that resolves it, rather than leaving it as a line to scroll past.

Two other sentences were repaired while there. One reported a schedule as current on a dead
process's evidence. The other said orders were impossible "because the account gate is open and
there is no confirmation file" — both halves false the moment the operator signed, and still
printing. It now asks the registry and names whichever blocker is actually holding.

### Left deliberately red

The alarm that caught all this is still failing, because the scheduler itself has not been
restarted. The enforcement is in the code; the running process is still the one that was started
wrong. That is the correct state to hand over in, and it clears with the one command the status
line now prints.

### Three mistakes of my own, all found by running rather than reading

I compared job identifiers from two different namespaces and asserted they matched. I built a
test argument object missing a field, so it ran past the thing it was testing. And I put a live
process lookup *inside* a function that other tests hand a fixture to — so two of them began
failing because the real scheduler outside had started after their fixture's timestamp. A
function that reads ambient state cannot be asked a hypothetical; what it needs is now passed in,
and the real caller supplies it.

Four older tests about starting and stopping processes were **isolated, not weakened**: they
describe starting the old route, and they had been reading this machine's real decision file, so
they began failing for a reason with nothing to do with what they test. They now point at a file
that does not exist — the world they were written for — and the refusal they would otherwise have
hit is asserted in this stage's own suite.

---

## Stage 5ZZO — a guard that fired where nothing was starting

*2026-08-27. No orders, no approval, no order directory, the confirmation untouched, the
scheduler untouched, no broker call.*

### What went wrong with the fix from the stage before

The previous stage taught the operations tool to refuse a scheduler start that would bring the
old route's entry jobs back onto a login the operator had signed away. It was the right guard.
It ran in the wrong place: at the top of the command, before anything had decided whether a
scheduler was being started at all.

So the one command that means *leave the scheduler alone and rebuild the dashboard backend* was
refused, and refused with a sentence about forty-five jobs that nothing was about to register.

That is worse than a confusing message. It was the only route to a backend restart, and the
previous stage had just written that command down as the way to pick up a new API route. A guard
that fires where nothing is starting does not make anything safer — it teaches whoever hits it
to go around, and the way around here was to restart the live scheduler in order to rebuild a
read-only dashboard. The stricter-looking guard was pushing toward the more dangerous act, which
is the same shape as the mistake it had just fixed, one command over.

### The fix

The check now happens where a scheduler is actually started, and there are two such places, not
one. The obvious one is the explicit restart, and it is still checked before anything is
stopped — a refusal that arrives after the kill leaves the operator with nothing running.

The second is easier to miss and matters more. When no scheduler is running at all, the branch
that is supposed to *leave one alone* starts one instead — in the old route's mode, with no
route flag on the call. Both the plain start command and the leave-it-alone command reach it. So
a backend-only restart on a machine with nothing running is a genuine old-route start, and it is
still refused. Nothing has been stopped on that path, so checking there costs nothing.

Nothing was relaxed. The guard covers exactly the same set of real starts as before, and the
matrix was measured against a fully stubbed process world: in every refusal, nothing was started
and nothing was stopped.

### Verified on the running system

The backend-only restart now does what it says. The scheduler kept its process id and its mode;
the backend got a new one. The route mode stayed compatible, the schedule stayed current, and
the order gate stayed shut on the evidence blocker it has been shut on all along.

The dashboard route added two stages ago is now actually served. Its first request timed out,
and that is worth saying precisely rather than leaving as a failure: it was the cold import
chain on a freshly started backend, not the endpoint. Measured straight afterwards it answered
in about a second and a half cold and a tenth of a second warm, which is the day-slice cache
doing what it was added for.

### The alarm went green on its own terms

The check that caught the whole scheduler-mode problem two stages ago was deliberately left
failing, because the enforcement was in the code and not yet in the running process. It passes
now — not because anything was loosened, but because the scheduler is genuinely in the mode the
signed decision describes and registers none of the old route's entry jobs. That is the outcome
that sequence was set up to produce.

### One older test restated

A test from the previous stage had pinned a literal line of source, and this stage rewrote that
line. A pin on source text goes stale the first time the code around it moves, and then fails
for a reason unrelated to what it was protecting. It asks the question behaviourally now: request
the transitional mode, watch it be refused, and confirm nothing was touched.

---

## Stage 5ZZP — "not published" was never the same as "not computed"

*2026-08-28. No orders, no approval, no order directory, the confirmation untouched, the
scheduler untouched, no broker call — and no trading decision moved, which is measured rather
than asserted.*

### The mistake two stages back

The stage that built the market view read the **return types** of the sleeve detectors and of
the regime labeller, found verdicts and strings, and reported that neither published anything
underneath. That reading went into the panel as "not exposed", into the tests as an assertion,
and into a module docstring as a statement of fact.

Reading the **implementations** shows something else. The stress sleeve compared four named
quantities against four named limits and returned a yes-or-no; every quantity was computed and
every limit was declared, and only the joining of the two was discarded — one call frame below
a slot that was writing "not exposed by the sleeve" into its own record. The regime engine has
a method that returns the posterior probability of each state. And the volume column was sitting
in every instrument store, simply never aggregated.

None of that was missing. It was unpublished, which is a different word.

### What the stress sleeve can now say when it says nothing

Before, a quiet slot reported no signal and offered nothing behind it, which sends somebody to
look for a data problem. On the last completed session it now reports that every instrument in
the basket was below its open and its average price — the breadth condition fully met — and that
none of them gapped down against a requirement of three, while the basket as a whole gapped **up**
half a percent against a limit of minus a tenth. That is an answer about the market, and it was
computed all along.

Two extractions made it available, and both were done so that one computation has two readers
rather than two computations having one answer each. The decision function is now derived from
the breakdown instead of restating it, and the opening of the detector — which built the whole
picture and threw it away on the way to returning nothing — is now a named step that both the
decision and the diagnostic read.

**Nothing moved.** The decision function was swept over every combination of its four inputs
against five parameter sets — nearly six thousand cases — with no disagreement against the
version it replaced, and the detector was run over six hundred and fifty slot-days with no
difference. That second number needed care: the first sample was forty recent days, and the
basket had not set up on any of them, so the comparison would have been between two empty lists.
It was widened until it contained more than two hundred real setups.

### The regime has a number after all, and genuinely has no threshold

The label is chosen by a path decode. Beside it, the same model on the same window will report
how probable each state is, and the labelled state currently stands at ninety-nine point eight
percent, nearly a full point clear of the next. Those are real numbers and they are recorded.

There is no threshold, and that is a statement about how the model works rather than about how
far this work could see. A path decode compares states against one another; it never compares
anything against a fixed line, so there is no line to be near, and a display promising distance
to one would be describing a procedure the model does not use. What stands in its place is the
lead over the runner-up — named as a lead, never as a distance to a threshold, and a test reads
the engine to make sure that sentence cannot quietly become untrue.

The eight-and-a-half-second reason for recording rather than computing still holds, and a test
keeps the labeller out of the reader.

### What was deliberately left alone

The other two sleeves share a detector that returns an entry and a stop when a setup exists and
nothing when it does not. On a signal day those values are already published; on a quiet day
there is genuinely nothing to publish, because the entry is produced by a per-bar signal
function rather than by a comparison against a standing level. Reporting a distance to an entry
would mean forming an entry the detector never formed, so the field says instead that it is not
computed until entry, and says why.

The morning sleeve does return its own values, but the live path reaches them through the
two-phase contract, and the deciding half must never be shown a number the observing half
produces. Wiring it without honouring that split would put a ten o'clock reference price on a
half-past-nine decision. Left unwired rather than wired wrongly.

### A statement in the source that had become false

The module that records the regime carried a paragraph saying the model published no score and
no probability. That was written from the return type and it had become wrong. It was corrected
where it lives, with the engine's own calls quoted underneath it — not annotated somewhere else
and left standing for the next reader.

Four test assertions asserting the same defunct claim were corrected with it. That is the right
number to expect: a wrong belief, once written down, propagates into everything built on top of
it, and correcting only the code would have left the tests defending the error.

### Two of my own misreadings

I took a diagnostic reporting no bars for the session as a defect. It was two in the morning on
the market's clock and the session had not opened — the diagnostic was right and my reading of
it was wrong, which is the three-clock trap this project keeps a note about. And one browser
assertion was case-sensitive against a label the stylesheet uppercases, which is exactly the
trap the previous stage hit on a different heading.

---

## Stage 5ZZQ — what would have to happen, and why the model said Calm

*2026-08-28. No orders, no approval, no order directory, the confirmation untouched, the
scheduler untouched, no broker call, and no trading decision changed.*

### Two questions the panel could not answer

It could say a sleeve found nothing. It could not say how close the day came, and it could not
say what about the market had made the model call the regime what it called it. Both answers
existed in code; neither had ever been asked for.

### How close the day came

The stress sleeve does not wait for a price. It counts how many of four instruments are trading
below their own open and their own average price, how many gapped down, how wide their ranges
are, and what the basket's average gap was — and it compares those four numbers with four
declared limits at half past ten. There is no line on a chart that any of that corresponds to,
so the panel shows the four conditions as cards rather than drawing one. Inventing a price line
there would put a trigger on the screen that the strategy does not have, and somebody would
eventually trade against it.

On the last completed session it reports that the breadth condition was fully met, that none of
the four gapped down against a requirement of three, and that the basket gapped **up** half a
percent against a limit of minus a tenth. It names the nearest of the two failures rather than
the first — which one is declared first is an accident of how the code was written, and the
question being asked is how close, not which came earliest.

The other two intraday sleeves work differently: their entry is produced by a per-bar signal
function rather than by a level that exists beforehand, so on a quiet day there is genuinely
nothing to be a given distance from. The panel says that in a sentence instead of showing empty
cards, and the sentence carries its proof — the classification for every sleeve travels in the
payload beside the data, so the claim cannot drift away from the code it describes.

### Why the model said what it said

The regime model looks at exactly two things: the day's return, and how volatile the last week
has been. Both are now shown with their current value, where they sit in the last sixty days,
and which state each is nearest.

That produces a real answer rather than a restatement of the label. Volatility is at the very
bottom of its sixty-day range and sits closest to the calm state's own centre; the day's return
tells you nothing, because the three states' expected returns sit within a thousandth of each
other. The panel says so — it reports **no lean** for the return rather than picking whichever
state happens to be marginally nearest, because a lean claimed on a quantity that does not
separate the states is invented.

And it is careful about what it is claiming even where it does lean. The number shown is the
distance from the value to a state's own centre, measured in that state's own spread. It is not
an attribution of the label to a feature: this kind of model decodes a path over a joint
distribution and does not break down into per-input contributions, so anything stronger would be
a claim the model cannot support.

The whole distribution is shown as bars beside it, with the uncertainty expressed in bits — a
lead over second place says how far ahead the front-runner is of one rival, while the spread of
the whole distribution is a different question. There is still no threshold, because the model
has none.

### A slowdown I caused, and a number I nearly blamed on the wrong thing

The previous stage's diagnostic recomputed an expensive daily slice on every single request. The
endpoint had been a tenth of a second warm one stage earlier and was approaching four seconds.
It is cached now, keyed on the modification times of the files it reads rather than on a timer —
a timer hands back a stale answer as a fresh one until it expires, which is the failure this
route keeps meeting in other clothes. Warm responses are back to hundredths of a second.

The first measurement after that fix read as ninety-five seconds cold, and the obvious reading
was that the new work had made things much worse. Measured properly, the **first request to a
freshly started backend costs about a minute whichever endpoint it is** — a cheap reader took
the same minute when it went first, and this endpoint took eleven seconds once something else
had paid that cost. The minute belongs to backend startup and predates all of this. It is
recorded as its own finding rather than folded into a figure that would have made this stage
look responsible for it.

### What the tests caught

The feature table did not fit a phone — four columns carrying a long input name overflowed by
two hundred pixels. Wrapping it in a scrolling box would have hidden the overflow rather than
removed it, and the row would still have been unreadable, so below a certain width each row
becomes a block with the input's name on its own line.

And, for the third time in these panels, one of my assertions was case-sensitive against a
heading the stylesheet uppercases. Three occurrences in three stages is no longer a slip; it is
a property of this page that any text assertion has to account for.


## Stage 5ZZR — three strategies wearing one chart

The Market View gave every sleeve the same panel: five-minute candles with room for entry, stop
and target lines. That shape assumed all three sleeves are price-trigger strategies differing
only in their hours. Reading the detectors says otherwise. NKD and Swing share one detector and
differ only by a trend period — ten bars against fifty — and neither has a standing level to
draw; entry forms only once a setup bar appears. Stress is a different strategy, and it is the
only one of the three that looks at breadth, gap-down counts and basket gap.

So the panel now shows, per sleeve, the variables that sleeve's detector actually consumes. NKD
and Swing name their four — the trend filter at their own period, volume against the ten-bar
average, daily ATR, and regime — and say plainly that the detector does not report the values.
It computes them inside its scan window and returns none of them, which is the same shape the
Stress rule values had before Stage 5ZZP and is fixable the same way. Saying "not reported by
detector" keeps that separate from "the market gave us nothing" and from "nobody looked", which
remain distinct answers in the payload rather than collapsing into one blank.

### The level that was there all along

Stage 5ZZQ recorded that a metric boundary publishes no price level, and pinned it with a test.
That record was wrong. The session context hands back the pre-session low and high for every
judgeable session, gate or no gate, and the entry scan looks for the first one-minute low
through that low. On 2026-08-27 — a day the basket gate **failed** — the trigger was a real
published price of 29,575.25, with a planned stop at 29,662.38.

Withholding it was not a safe default; it hid a number the operator wants to read. Drawing it
solid would have been worse: a live-looking line on a day nothing is trading is a line someone
would trade against. The rule that protects the operator was never *no level* — it is **no armed
level**. A published level on a failed gate is now drawn dashed and dimmed, labelled "not
armed", with a note saying the gate did not pass. Only a passed gate draws it solid. The 5ZZQ
test has been rewritten from "publishes nothing" to "arms nothing", carrying the measurement
that disproved it.

### Reading the model instead of repeating it

The regime panel shows exactly the two features the model takes, and says "No published shift
threshold" — the label comes from a Viterbi decode, which compares states against each other
rather than against a cut, so there is nothing to be near. My first cut wrote that sentence into
the page. That is the drift failure this project keeps meeting in new clothes, and it was caught
by an adjacent test that had been asserting on the model's own wording. The sentence now lives
with the model, the page reads it, and the test asserts the page does **not** contain the words.
A fixture that held its own transcription of that string had already gone stale, so it derives
from the constant now too.

### What the tests caught

A real layout defect, found by measuring rather than by looking: `max-width: 100%` on a
content-box pseudo-element means 100% *plus* its own padding and border. At a 375-pixel viewport
the chip row is 343 wide and the tooltip rendered 367 — the twenty-four pixels are nine and
eleven of padding and a one-pixel border on each side. Two earlier attempts each shrank the
overflow without removing it, which is the tell that neither had found the cause.

And, for the fourth time in these panels, one of my assertions was case-sensitive against a
heading the stylesheet uppercases — something my own redesign spec had already written down as a
property of this page. It is handled once now, by a helper every text assertion goes through.

Eight mutations were attempted against the new rules and all eight turned the right test red.
Nothing about strategy, schedule, gate or order path changed; orders remain impossible with
`PAPER_SHADOW_EVIDENCE` the sole blocker, and the scheduler was not restarted.

### An alarm left ringing on purpose

Ten tests in the ops suites are red, and this stage did not break them. They assert the pre-B1
world — that the go-live confirmation file does not exist, and that B1 is still a blocker — and
Stage 5ZZJ created that file a day earlier as a deliberate operator decision. Inside the failing
test, the safety assertion itself still passes: orders are impossible. What is stale is the
claim about which gate is blocking. Repairing that quietly inside a dashboard stage would hide
it; it is recorded here and needs its own stage, because ten permanently-red tests are an alarm
people learn to ignore.


## Stage 5ZZS — ten red tests that were not one problem

They looked like one family: ten ops tests still describing the world as it was before the
operator signed the B1 decision. Six of them were. The other four had nothing to do with B1 at
all, and reading them as one group would have hidden the more interesting half.

The six asserted the old world plainly — three of them that the confirmation file does not
exist, which is not a safety claim but a claim that nobody had decided anything. What replaced
them is stronger than what was removed. Orders are impossible and something *measured* is what
holds them. B1 stays closed only while both halves hold: take the signature away and it returns,
and leave the signature in place while its measurement fails and it returns too. A confirmation
on disk must be signed, and being signed must never be enough to open an order.

The other four were left behind by a refactor. An earlier stage moved the post-close SPY refresh
out of its job function and into a shared helper, and the tests were reading the job body. One
of them failed with the message "the post-close refresh no longer runs strict, so a drift exits
0 again" — which would have been a serious finding had it been true. The flag is exactly where
the refactor put it, one call deeper. A test that reads one function body cannot survive that
body moving, so these now follow the delegation instead.

### The gap the classifier had been announcing for days

Three jobs added by two earlier stages — the two retry rungs of the SPY ladder and the quarter
to one in the morning last look before the Nikkei window — were never named in the table that
says who owns which job. The classifier had been reporting them as unclassified ever since, and
the module's own comment says that is precisely what should happen: a job nobody has thought
about lands there and turns a test red until someone comes and names it. The mechanism worked.
Nobody answered it.

Nothing unsafe followed from it — the retirement set is built only from the legacy bucket, so an
unclassified job was never removable — but the route table did not know three of its own jobs.
They are named now.

The same three are missing from the dashboard's schedule mirror, and that has been left red on
purpose. The panel has no row for them, so if one fails at night nothing there says so. Adding
rows is a different subsystem, and a row for a job that does not fire when expected becomes an
alarm nobody can silence, which is a failure this project has already paid for. It needs its own
stage, with the times measured rather than assumed, and until then the parity test keeps ringing.

### What the mutations found in my own work

Every repair here removed an assertion that used to fail, so the cheap way to make ten tests
green would have been to assert less. Eleven mutations went looking for that, and three of them
came back green in a way that was worth listening to.

One waived the B1 measurement entirely and nothing noticed. The suite had been showing that the
signature is necessary — remove it and the gate returns — and I had taken that to cover the
measurement as well. It does not: a decision gate reappears unsigned whatever the measurement
says, so one half of the rule was being asserted twice and the other half not at all.

Another opened orders whenever the approval variable was set, and nothing noticed either,
because every test asserted the variable was unset and none asserted what would happen if it
were. An assertion about the environment is not an assertion about the gate. What replaced it
never sets the variable at all: it asserts that whatever is holding orders shut is held by a
measurement no signature lists, and that the gate registry does not read the environment on its
way to that answer.

The third came back green honestly and stayed that way. Breaking the unclassified fallback
proves nothing now that every registered job is named — the edit lands on a line nothing
reaches. A mutation on a path the tests never execute is not a passing test; it is a mutation
that never ran, and the harness was right to say so both times.

Nothing about strategy, schedule, gate or order path changed. Orders remain impossible with
`PAPER_SHADOW_EVIDENCE` the sole blocker, the scheduler was not restarted, and the two mutations
that break the scheduler's own file ran against a copy — "it is restored a few seconds later" is
not an answer when a killed process would leave that file broken on disk while the thing is
running.


## Stage 5ZZT — three jobs the panel could not see, and a sweep that closed a failure it never touched

Stage 5ZZS left two parity tests red on purpose, because adding a dashboard row for a job at the
wrong minute produces an overdue alarm that never clears, and the times had not been measured.
Running them first showed the count was wrong: four tests were red, in two files, all saying the
same thing. Three jobs the scheduler runs — the two retry rungs of the post-close SPY ladder and
the quarter to one in the morning last look — had no row on the schedule panel at all.

Before changing anything, the journal was read for the days around it, and the gap turned out to
have already cost something. On the twenty-seventh **every rung of the evening ladder failed**,
and the last look the next morning is what brought the series up to date — exactly the case it
was built for. Three separate defects sit in those few lines.

The first is the one worth the stage on its own. Both failed retries were reported as recovered,
at 22:20:14, and listing every job of that type on that day says which one that was: a
stop-repair sweep. A sweep of broker stops had closed a failed data refresh. The mechanism is
plain once seen — a job is treated as recovered when a later job of the same type completes, and
both of these sat in the catch-all bucket. A catch-all is not a stream, and it had been acting
as one.

The second is what the operator was told. The retries read "the job emitted an unclassified
error" and advised reconciling broker state, for a job that never touches the broker. The
classifier's own comment describes that bucket as saying something true of anything, which tells
a reader nothing. The third is simply that none of it appeared on the panel, so neither the
failures nor the recovery that saved the next session were visible.

### One stream for the ladder, and a separate one for the last look

The three refresh rungs now share a type, which is not cosmetic: recovery is expressed by a
later job of the same type completing, so a rung that missed and a later rung that succeeded now
reads as a recovery through the machinery that already existed for the stop-repair sweeps.

The last look gets its own, because it asks a different question — the previous trading day
rather than today's close — and letting it mark an evening rung recovered would be a recovery for
a question that rung never asked.

The wording splits the same way. A rung caught by a later rung says so and asks for no action; a
rung nothing caught keeps the original sentence about tomorrow's slots meeting a freshness
refusal. That condition is the whole point. An earlier stage in this ladder was titled for the
measurement that stopped it becoming an alarm nobody reads, having found that two retries
reporting failure on every good day is exactly such an alarm; copying the sixteen-twenty wording
onto the rungs would have rebuilt it through a different door. Making the softer wording
unconditional would have been the opposite mistake, a total failure reading mild. Both directions
are held by tests.

### The check parity could not make

Parity compares slot names. A row at the wrong minute passes it and then reports overdue every
day forever, which is worse than no row at all. So the new suite reads the schedule out of the
scheduler's own decorators and compares clocks, in both directions — and the mutation that moves
a rung an hour early passes parity and is caught only there.

Nine mutations, all caught. Nothing about strategy, gates or order path changed: the three jobs
are shared infrastructure, none of them is a strategy slot, the slot count is the same before and
after, and orders remain impossible with the same single blocker. Reverting both edits and
diffing the failure sets says this stage caused none of the five failures that remain and fixed
four.

The dashboard will not show the new rows until the backend is restarted — it started an hour and
a half before these files were edited, and a module is imported once per process. That restart
was not done here.

### What is left

Removing the SPY jobs from the catch-all fixes the case that was measured, not the mechanism.
The Track 1 stop-repair and audit jobs are deliberately kept away from the legacy prefixes and
were never given types of their own, so they sit in that same bucket together. Every one of them
completed today, so nothing is being falsely closed right now; the next time one of those sweeps
fails, an unrelated audit finishing afterwards will close it. Same defect, different jobs.

And the recovery that actually mattered is still invisible: the journal reads one day at a time,
so the twenty-seventh shows three open failures with no sign of the job that repaired them at a
quarter to one the next morning.


## Stage 5ZZU — a bucket that two readers were treating as a stream, in opposite directions

Stage 5ZZT split the SPY ladder out of the catch-all and said plainly that the mechanism
remained: Track 1's own maintenance jobs were still in there together, and the next failed sweep
would be closed by an unrelated audit. That turned out to be half the story.

The catch-all is read by two lanes, and they were wrong in opposite ways. The journal lane
grouped everything in it into one stream, so any of those jobs completing closed any other that
had failed — a stop-repair sweep closing an audit, an audit closing a max-hold check. The issue
lane did the reverse: when the type was missing it fell back to the job's own identifier, so
each sweep stood entirely alone and a Track 1 sweep that failed at twenty past six could never
be closed by the identical sweep two hours later, while its legacy counterpart always could. One
lane gave a false all-clear; the other opened something nothing could ever clear. Both were
reproduced with a fixture before anything was touched, and only the first half had been noticed.

A real type answers both at once, which is why the fix is three names rather than a rule at each
call site. The sweeps, the max-hold check and the window audits each have their own stream now,
and every test that says one of them must not close another has a test beside it saying which
one must. That pairing is the point: the laziest way to stop things being closed by the wrong
job is to stop closing anything, and that would have been worse than the bug, because it is
precisely how the issue lane was already broken. One mutation exists solely to make that
unshippable.

The wording changed with the types. A failed window audit used to tell an operator to reconcile
broker state; it now says that no evidence record was written for that window, that nothing is
at risk in the book, and that the gate which reads that record is the thing affected. The
stop-repair sweep names the Track 1 book and its stops.

### What a type change costs at its call sites

Four readers consume the job type and two of them needed work. The dashboard decides whether a
failure belongs to the scheduler or the runner from a list of types, and these jobs were on that
list only by virtue of being untyped — giving them types without naming them there would have
quietly blamed a missed sweep on a runner that never ran. And the identifier was serving as the
row's visible label, so it moved to the tooltip and a readable name took its place.

That relabelling is deliberately confined to the three types this stage introduces. The first
attempt covered the strategy slots and the legacy sweep too, and broke six tests in an operator
view that addresses a row by its identifier. Renaming a taxonomy is a design change of its own.

A scope error of mine was caught the same way: the label helper went in three scopes deep inside
a render function, so the journal panel threw and nineteen tests errored with no rows at all —
the same mistake as an earlier stage, where render calls landed inside a click handler. The
patch that moved it now asserts the destination's brace depth rather than trusting indentation.

### Something else moved while this ran

Partway through, the status line began reporting two blockers instead of one. B1 had reopened,
and nothing here caused it: the account baseline record had passed its twenty-four hour freshness
policy eighty-one seconds before the reading. That is the gate doing exactly what it was built to
do — B1 stays closed only while a signature and a passing measurement both hold — and orders
remained impossible throughout. The operator needs to rerun the baseline check; nothing is at
risk while it stands open.

It also caught three tests written the day before that had pinned a live, ageing state as though
it were a fixed fact: two asserting the blocker list by equality, one asserting today's
measurement passes, and one using "B1 is closed right now" as a precondition. They now drive the
rule in both directions instead of reading it off the day's records, and the earlier stage's
mutation harness still catches every one of its cases, so they were made time-independent rather
than weaker. A twelfth instance of the older pre-B1 staleness surfaced in a suite that stage had
not run, and was restated the same way.

Nothing about strategy, schedule, gates or orders changed. Fourteen mutations, all caught, and
reverting the edits and diffing the failure sets says this stage caused none of the six that
remain. The dashboard will not show any of it until the backend is restarted, which was not done
here.


## Stage 5ZZW — two readers, one machine, and a rail that described the wrong route

The rail said the scheduler needed attention and that runner state was stale. The status command
said the scheduler was healthy and the Track 1 slot table fresh, seventy-one of seventy-one. Both
were reading real data. They were reading it about different routes.

The status command asks the scheduler what mode it is in, by reading its command line out of the
process table. The dashboard backend asked its OWN environment variable — which is how the ops
tooling tells a backend it starts what mode to answer in, and which nobody had set on the process
that happened to be serving. So the backend answered "legacy" about a machine running
track1-only, and everything downstream followed it.

Two separate things then lit the rail. The suppression that exists precisely for this — a legacy
snapshot is stale in this mode because nothing writes it, and an alarm for the whole shadow
period is an alarm nobody reads — is gated on a flag that came out false, so it never fired. And
the slot mirror, believing it was watching a legacy machine, expected twenty-two slots the
scheduler does not register and reported every one of them overdue. The machinery built for this
was correct; only its input was wrong.

The backend now asks the scheduler, and keeps three answers rather than two. "Could not read the
scheduler" is carried as unknown and shown as unknown, never as legacy — the difference between
"legacy is running" and "I could not check" is the whole point of the line it feeds.

Where that resolution happens turned out to matter as much as the resolution itself. The first
version put it inside the payload builder, which made the live page right and twenty-six tests
wrong: every suite that describes a machine by clearing the environment began reading the real
process table and answering about whatever happened to be running. A test that is not isolated is
worse than no test, and this repository already has the scar. So the mode is a parameter now. The
live endpoints pass what the scheduler says, because there the scheduler is the authority; every
other caller keeps exactly the behaviour it had.

### Retiring what is retired, without hiding it

The backend already labelled every issue with whose route it belongs to. What was missing was a
measured answer to whether legacy is actually retired on this login, and that needs three facts
together: the operator signed the decision, the running mode agrees with it, and it registers no
legacy entry job. Any one of them unreadable and the answer is "not retired" — a legacy issue
shown beside Track 1's is noise, but a legacy issue hidden while legacy could still trade is the
one that costs money.

Three of the six issues are legacy ledger comparisons that read no Track 1 artefact, and they
have left the number at the top of the page for a collapsed history below it. Not one of them
left the payload; each carries the flag and the reason beside it. This project has already paid
once for a change that made rows vanish from a screen without saying where they went.

The carried model-age debt was sitting inside the legacy group. That was survivable while both
were shown and became a hazard the instant the legacy group stopped counting, because the debt
would have gone quiet along with it — and it is a model fact that applies to Track 1 whatever
legacy is doing. It has its own group now.

### The panel that was reading a file nobody writes

Model Inputs took its regime label from the legacy runner snapshot, so in this mode it was
showing a label from whenever legacy last ran, presented as today's. It reads the Track 1 regime
record now — the label, the session it belongs to, the fitted window it is anchored to, and the
route's own label check. The fit-end field turned out to have no setter at all: a dead field
showing two dashes since the day it was added.

### What the tests found

That the retirement answer had been computed inside a memoised builder, keyed on log signatures
and the date. Whether legacy is retired is a fact about the running scheduler and can change with
no log line written anywhere near here, so the answer would have stayed frozen while legacy came
back. It is recomputed on every read now. The cache key two lines above carries a comment about
the same trap, for a different field.

Fourteen mutations, all caught, and deliberately pointed in both directions: one that stops the
suppression firing and one that makes it unconditional, so a real legacy fault going quiet fails
too; one that hides too few issues and one that hides too many. Nothing about gates, schedule,
strategy or orders changed, and the only Track 1 blocker is still the measured one.

The dashboard will show none of it until the backend is restarted, which was not done here.


## Stage 5ZZX — a console reporting questions rather than answers

The complaint was that the backend window looks like jobs are running continuously, and the
suspicion fell on the APScheduler lines about adding jobs tentatively. Counting the retained log
first put that in proportion. Of three hundred and fifty-eight thousand lines, ninety-four per
cent are successful GETs from the dashboard polling itself, and the APScheduler lines are under a
fifth of one per cent — and they are not continuous at all. They arrive in bursts on six separate
days.

So the flood is the access log, and an access log records that a question was asked, not that
anything happened. A page polling every eight seconds writes ten thousand successful GETs a day
whether the system is healthy or on fire.

The bursts turned out not to be this process either. Today's burst is timestamped four minutes
before the backend logged its own startup, which places it in the ops command that was doing the
restart, whose console output lands in the same file. Attaching a handler in this process and
calling each polled endpoint once confirms it from the other side: not one APScheduler record
between them, and every endpoint answers two hundred.

And the backend does not start a scheduler. Parsing every module in the tree finds exactly one
call that starts one, inside the scheduler's own main. The mirror builds a scheduler object and
reads its job list; nothing is started, and even a fired job would execute nothing in the mode it
is built in.

### Quietening without going deaf

Two filters, installed in the backend's own module and therefore in that process alone. One drops
access lines whose status says the request succeeded. The other drops the tentative-add chatter,
attached at both the parent and the child logger, because a filter on the parent is never
consulted for a record the child made.

What survives is everything that could be the first sign of a problem: every failed request,
every warning and error including on a successful request, tracebacks, the backend's own startup
lines, and — deliberately — the line a real scheduler would print if one ever started here.
An access line the filter cannot parse is kept rather than discarded, because a filter that
swallows what it cannot read hides exactly the malformed cases worth seeing. Nothing global is
disabled; that would have silenced the scheduler's own log too if the code ever ran there, and
a mutation adds such a call to prove the tests would catch it.

The mirror still builds a real scheduler object. Replacing it with a hand-written list of slots
is precisely what that code exists to avoid — a second list is how two descriptions of one
schedule drift apart, and a previous stage was spent entirely on that. It costs two lines per
backend start, not per request, which is not noise.

The polling interval was left alone. The stage asked for a measurement before touching it, and
the measurement says the interval was never the problem: at zero lines per request the same eight
seconds now costs nothing.

Measured after a backend-only restart, with the scheduler untouched: forty warm requests across
the four polled endpoints, all answering two hundred, and zero new lines in the log. Before the
change those same forty requests would have written at least forty.


## Stage 5ZZY — a polled endpoint that opened a console

Two of this stage's three code changes were already on disk when it began, made between the end
of the previous stage and the start of this one. The mode helper existed, both readers already
used it, and neither called the ops reader any more. What this stage did was verify that work,
write the tests for it, and find the thing underneath the last item.

The regression itself belonged to an earlier stage of mine. Making the backend ask the scheduler
which mode it is in was right; reaching for the ops reader to do the asking was not, because that
reader runs PowerShell. Measured: one call spawns two PowerShell processes and costs nearly three
seconds. On a page polling every eight seconds that is a console window flashing several times a
minute, and the log filters added the stage before could never have helped, because the noise was
never in the log. The backend already had the answer in a cached psutil scan whose own docstring
says never to call the uncached version on a request path.

One measurement had to be thrown away and redone. The first probe reported zero subprocess calls
from every endpoint, which would have meant there was no regression at all. A zero that convenient
is a reason to check the instrument rather than the system: a deliberate call proved the spy was
live, and calling the ops reader directly showed the two spawns. The endpoints were clean because
the fix was already applied — but that was not knowable from the zero, and every measurement in
the report now carries a self-check.

### The green test that was watching the wrong lane

The last item asked, among other things, that a failed Calm phase must not be recovered by a
Stress run. The test making that claim was passing. It guards the incidents lane, which keys on
the slot id and has never been wrong about this. The journal and issue lanes key on the job type,
and every Track 1 strategy slot shares one — so a completed Stress run at half past ten was
closing a Calm failure from half past nine, and the passing test could not have seen it.

That is the same defect as the maintenance-job stage before it, one layer up: a bucket being read
as a stream. Recovery keys on the sleeve now, through a single function the issue lane defers to
so the two lanes cannot drift apart. Both Calm phases stay in one stream on purpose — the later
one covering the earlier is a real recovery, not a coincidence — and a mutation splits the streams
per slot to prove that separating the sleeves has not separated a sleeve from itself. The job type
is untouched, so everything that asks whether something is a strategy slot still gets the same
answer.

### Verified

Twenty warm requests across the four polled endpoints with no subprocess call of any kind. After a
backend-only restart with the scheduler left alone, thirty-two more requests all answering two
hundred while the count of shell processes on the machine did not move at all. Ten mutations, all
caught, including one that pushes an unreadable command line back to reporting legacy instead of
unknown.

Nine tests from the previous stage were moved to the new seam. They patched the ops reader and
expected the resolver to consult it, which it no longer does; each keeps its property and asserts
it against the cached scan instead, and the retirement fixture now writes its confirmation into a
temporary directory so those tests can no longer be answered by the production file.


## Stage 5ZZZ-A — a signature is not an armed order

The shadow audit had been failing every sleeve on every day since the operator signed the B1
decision, and its reason was that the confirmation file exists. When that rule was written it was
right: the signature really was the last thing between this route and an order, so finding it
during a shadow period meant the route could send.

It stopped being right in stages. A measured evidence gate arrived, then B1 acquired a measured
half of its own, and when the operator signed on the twenty-seventh the possibility of sending an
order never became true for a moment. From then on the file records that a decision was made, and
whether an order could be sent is a different question that has its own answer. The audit asks
that question directly now, and it asks two more that the old rule was standing in for: whether
the out-of-band approval is set, and whether an order journal exists. Neither is implied by a
signature, and the gate registry deliberately does not read the environment, so without them an
approved shadow run would have passed an audit whose whole subject is whether an order could have
been sent.

Calm and the overnight window both turn from failing to passing on the twenty-eighth, and the two
sleeves whose windows had not opened yet say so rather than passing.

### What the stale rule had been costing

Two things, and the second is worse than the noise.

It was hiding real failures. The twenty-seventh recorded one reason for all four sleeves — the
confirmation file — and anyone reading that record would have seen a known stale policy and moved
on. Re-evaluated with the rule removed, that day fails for four different and genuine reasons:
two checkpoints written for the wrong day, and coverage gaps on Calm and Stress. It still fails,
and it should. What changed is that the reasons are visible.

And it was feeding the only gate still holding this route. The paper-evidence blocker counts
failing days and requires none of them; a rule that fails every day from the signature onward does
not merely make noise, it manufactures the failures that keep the last gate shut.

### The records on disk were left alone

The stage could have appended corrected rows. It did not, for two measured reasons. Today's rows
will be rewritten by the scheduled audits from the fixed code within hours, and a hand-written row
would carry a process id and a trigger that no other row in that file means. Yesterday's would be
FAIL either way, so a corrected row would state the same verdict with different reasons and change
no count and no decision. The stored rows stay as a true record of what the audit said under the
old policy.

### Removing a failure is the shape of change that needs the most proof

Most of the mutations here re-arm the route some other way and require the suite to notice each:
orders genuinely possible, the approval marker set, an order journal on disk, an order mark on a
record. Two put the stale rule back. Two came back green before they were right, and both verdicts
were honest — one dropped a condition that the fixture was flipping in lockstep with another, and
one forced a branch false into an else that produced the same answer.

Six tests across five suites were still asserting the pre-B1 world, the same family two earlier
stages restated elsewhere. Four claimed the confirmation file does not exist; they now claim that
the things which arm an order do not exist, and that any decision on disk is a signed one.

Nothing about strategy, schedule, gates or order sending changed — only what the audit calls a
failure. The confirmation file was not deleted, orders remain impossible, and one production file
was edited.


## Stage 5ZZZ-C — what was underneath the stale reason

The previous stage removed a rule that had been failing every sleeve on every day since the
operator signed the B1 decision, and reported that the twenty-seventh still failed for four real
reasons that the rule had been hiding. This stage went and looked at them.

Two of the four are genuine, and they are the same kind of thing. Calm could not evaluate either
of its phases: no session, stale data, partial coverage, and on the deciding phase no entry quote.
Stress lost the first half hour of its window to the same two conditions, six slots between
twenty-five past ten and eleven, with the remaining eighteen deciding normally. Neither is a
strategy fault or a code fault. Both are the data not being there when the sleeve looked.

The other two are not findings about that day at all. The checkpoint check compares the day under
judgment against the live positions book, and that book is a single file overwritten on every run
— today it carries this morning's cut, and there is no dated copy of it anywhere in the tree. So
re-judging any past day compares it against today and disagrees, every time, forever. A verdict
that is guaranteed regardless of what happened is not evidence about what happened.

For the overnight window there is better evidence than a re-evaluation: its own row from that day,
written when the window closed, says PASS. A later sweep overwrote it, and that sweep's only
failing reason was the rule that has since been removed. The readiness reader keeps the last row
for each sleeve and day, which is why the gate still lists that sleeve as never having passed.

### Classification, and the line it does not cross

The stored rows were not edited. A project that rewrites its own evidence when the policy changes
has no evidence, so what this stage added instead is a reader that reports three things side by
side and never writes: the record verbatim, which of its reasons came from a rule that has since
been removed, and what the current code says together with whether it is entitled to say it.

The registry of removed rules is checked against the code rather than trusted, and that check
immediately earned itself: the previous stage had removed the rule but left the branch that maps
its reason, unreachable only because nothing emits the string it matches on. Unreachable by string
is a thin thing to rest on, and it made the reason look alive to anything reading the file to find
out what the code can still produce. It is gone now.

The reader is deliberately not on the order gate's import path, and a test asserts that by reading
the import graph rather than the comment claiming it. Turning a stored failure into a pass moves
the only gate still holding this route, and that has to be an operator's decision with the
reasoning in front of them. On this particular day it would change nothing anyway, because two
sleeves failed for real.

### What actually stands between here and paper orders

The evidence gate did not move, and that is the intended outcome. It wants one more judgeable day,
which is time rather than a defect. It wants no failing days and has four, three of them failing
for reasons nobody disputes. It wants Calm decision evidence that two of those days do not carry.
And it wants every sleeve to have passed at least once inside the window — which is the single
place the removed rule still costs something, because the overnight sleeve did pass, in a row that
was overwritten.


## Stage 5ZZZ-B — the variables a sleeve decided on

An earlier stage gave the dashboard a strategy-native panel and could then only name the four
things the two trend sleeves decide on, printing "not reported by detector" beside every one. The
values had been there the whole time. The scan computes a trend filter, an average true range and
a ten-bar average volume for every bar it looks at, and threw all three away at the end of the
loop.

So the detector was given a listener. It reports each gate it passes or stops at, and what it
computed at each bar; the listener's answer is discarded and its exceptions are swallowed inside
the detector. Nothing in the new module computes a strategy value, and that is not fastidiousness
— the detector's own docstring says a second implementation of an entry rule proves nothing about
the first, and an average recomputed elsewhere would drift from the one the committed artifacts
were generated with. That the listener changes no decision is asserted across both sleeves and
two sessions, including with a listener that raises on every event.

The panel now carries real numbers for both sleeves and, where there is no setup, the detector's
own reason for it: one sleeve trades only in a regime today is not in, and the other has no
regime label at all yet because the afternoon pre-flight that publishes it has not run. Both are
answers about the decision rather than sentences composed for the screen.

A reconstruction stops where it was asked to stop. Asked about nine in the morning it reports no
bars; asked about twenty past two it reports three, ending exactly there; asked about the evening
it reports the whole window. Threading that instant through was a gap found while writing the
tests: the reconstruction had hardcoded the present, which would have made the whole property
untestable, since no test could have asked it about any other moment.

Where a gate stops the detector before it reaches any bar, the window is walked a second time
through the same scan, deciding nothing and discarding the result, purely so the four variables
can still be shown. On a quiet morning "this sleeve trades in a different regime" is a complete
answer about the decision and tells an operator nothing about the instrument.

Runtime evidence is wired as a third observability block in the slot, placed and wrapped exactly
like the two already there, after the coverage row, because that row is the evidence the audit
counts and nothing below it may be the reason a slot loses it. Nothing has been written yet, and
that is expected: no slot has run since the change.

### A minute per request, and how it was found

The first working version made a polled endpoint take fifty-seven seconds. Measuring rather than
guessing put the blame precisely: reading the three-million-row store costs a seventh of a second,
and the detector's own pass over it costs fourteen seconds and is not memoised — and the
reconstruction called it four times.

Shortening the frame is not available as a fix, because the trend filter is recursive over the
full history and a truncated frame would produce numbers the detector never saw. A reconstruction
that does not match what the detector would see is worth nothing. So the answer is served
stale and refreshed out of band, which is the pattern this backend already uses for its process
scan, and the key is deliberately stable rather than including the clock or the file's timestamp:
a key that changed every bar would have nothing to serve stale, so every appended bar would pay
the full minute in front of a waiting page.

Two tests written earlier the same day had to be rewritten here, both for the same reason: they
pinned a state the clock moves. That is the third time in one sitting, which makes it a habit
rather than three accidents, and it is written down as one.

---

## Stage 5ZZZ-E — Calm, without the earlier phase learning what the later one knows

Calm is not one decision. It is two, half an hour apart: at 09:32 the sleeve decides whether a
setup exists, and at 10:02 it reads the price the rule transacts at. Making it observable means
publishing both — and the whole difficulty is that the first card must not show anything the
second one learned, or the panel would quietly claim the sleeve knew at half past nine what it
only found out at ten.

### The runtime half already existed

Reading the live path before building anything changed what this stage is. The slot already
appends a DECIDE row at 09:32 and an OBSERVE row at 10:02, on every path including the refusals —
its own docstring says silence is the one outcome not allowed. It already carries the parameter
signature, the data identity, the risk inputs and the refusal codes.

So this stage is a reader, and no runtime trading file was touched. A second writer would have
put two accounts of one phase on disk, and on the day they disagreed nobody could say which one
was the sleeve.

### Where the line is, and why nobody drew it by hand

The detector answers this itself. Its full-day entry routine *is* its pre-entry routine plus an
entry price and an entry timestamp — so what is knowable at DECIDE is exactly the fields of the
pre-entry record, and what is OBSERVE-only is exactly what the entry bar adds. Both sets are read
off those two structures at runtime rather than typed into a list, because a hand-kept list of
forbidden values is a list that will one day be missing the value somebody just added.

One field is worth naming: the location of the open within the previous day's range reads like a
price feature and is computed entirely from the 09:30 open, so it belongs to DECIDE. The detector
flags it for that reason, and a test now pins it on the correct side.

The stop appears at DECIDE as its rule and its distance, never as a level. The rule is fully known
at half past nine; the number it evaluates to is the single thing that phase may not know.

### A mutation that came back green, and what it was hiding

Every test agreed the DECIDE card carried no price level. It carried none because a DECIDE row on
disk happens never to hold an entry-reference block — the level was built from whatever the row
contained, with no mention of which phase was asking. The leak was being held off by the data
rather than by the code, and one malformed row would have printed a stop price at 09:32.

The gate now names the phase, and a test feeds exactly that poisoned row. Six mutations, six red,
every file restored byte-identical — but the one that mattered is the one that survived, because
asking why it survived is what found the defect. A green mutation treated as a pass would have
left it in place.

### Which source answers, and when

A phase whose instant has not been reached says so, and is never reconstructed. A phase that has
passed and left a row reads the row. A phase that has passed and left none is replayed, labelled,
and carries the warning that a replay is not runtime evidence. The instant is checked before the
record — a caller asking what 09:32 looked like at 09:00 is asking about something that had not
happened, and handing back the row written half an hour later would answer a different question
with a real artefact, which is the most convincing way to be wrong.

A replayed OBSERVE with no matching DECIDE refuses, exactly as the live path does. Standing alone
it would report a reference price and imply a decision nobody can point to — the collapse the two
phases exist to prevent.

### On the page

Two cards, outside the sleeve tabs, each with its own source badge. Calm was deliberately not
folded into the sleeve list: every entry there is a continuous window on one instrument with a
bar chart, and squeezing two instants under a separation contract into that shape would have
meant one card — and one card is where the leak would live.

Nothing about the split is decided in the browser. The page prints the rows the backend put in
each phase, and a test pins that it never reaches across to the other phase to fill a gap.

### Nothing moved

No gate, threshold, schedule, or trading decision changed. No runtime writer was added. Orders
remain impossible, blocked by shadow evidence, and a test asserts by import graph that no gate
can reach the diagnostics module at all.

---

## Stage 5ZZZ-F — the panel that contradicted itself

Four stages put strategy values into the payload. This one is about what the page does with
them, and it opened on a measurement rather than on a reading of the code: build the payload,
print it, and look at what the sleeves actually say.

The first sleeve settled it. The Stress card published a trigger at 29,592.50, a planned stop
at 29,652.62 and a session open at 29,615.25 — and the chip directly above them read "Strategy
levels unavailable". The note was computed from the signal rows, which is where levels came
from before the diagnostics stages started publishing them somewhere else, and it had gone on
answering a question that was now being answered elsewhere.

A panel that contradicts itself in two places costs more than one that says nothing. The reader
has to work out which half to believe, and the page gives them no way to do it.

The note now describes what the panel can actually show, from any source, and keeps three
states apart because an operator needs all three: levels that are armed, levels that were
computed for a gate that did not pass, and no levels at all. The payload-wide version of the
same note is derived from the sleeves rather than asserted before any of them is built, and it
stays silent when they disagree — one string cannot describe three sleeves that no longer say
the same thing.

### What else had gone quiet

Every strategy block was unlabelled. The source was reachable only one level down, so anything
reading the block itself got an answer with no provenance on it — and an unlabelled
reconstruction reads as a recorded one, which is the single distinction these stages exist to
keep. The Stress gate had stopped saying which hour it was decided at, so four metric values
read as this minute's when they are the half-past-ten bar's. And the regime panel had stopped
naming its absent shift threshold: the only surviving mention was a fallback that never renders,
because the record always supplies the field it falls back from. A reader looking for the number
that says how close the label is to flipping was left to notice its absence.

All three are published again, each from the place that owns the fact — the detector's own
parameter for the hour, the model record's own sentence for the threshold.

### Two heights, and a measurement that had to be attributed

The plot's height came from its content: a populated tab measured 437px and a tab whose session
had no bars measured 116px, so switching between them moved every panel underneath. The
stylesheet meant to prevent exactly this says so in its own comment, and it was pinned to an
element that the rebuild stopped being the one that holds the plot.

Giving the plot a box left 1.5px, and that residual was attributed rather than tolerated: the
card head is a line box that grows when it has a price in it. Not much to look at, and it is
still the whole card moving under the pointer on every tab switch, from the same cause. The
legend needed the same treatment by a second route — it renders only when there are bars, so in
the flow it added 40px to one tab and nothing to the other.

A chip carrying a sentence could not wrap, and ran past the right edge at the narrow width. The
fix carries `box-sizing: border-box` deliberately: a max-width on a content box resolves to that
width plus its padding and border, which is how an earlier stage shrank an overflow twice
without removing it. And adding the decision hour pushed the card head 20px past its own box,
because a flex item will not shrink below its own text and wrapping cannot save a row whose
single item has nowhere to wrap to.

### Calm, and the fourth word

Calm was already outside the sleeve tabs. It was still rendering inside the market-view band at
the end of the sleeve renderer, so it sat under whichever sleeve was selected and read as part
of it. It has its own headed band now, rendered once, hidden rather than left standing empty —
an empty headed band reads as a panel that failed, and Calm having nothing to say is not a
failure.

The page also gained the word it was missing. It could say recorded, reconstructed and not yet,
and it had no way to say the backend could not read something at all. "I could not check" and "I
checked and there was nothing" are opposite facts about whether a panel can be trusted, and a
page that renders them identically has thrown the difference away. The word is shown only on an
explicit error from the backend, never inferred from an empty payload, and both directions are
tested so the rule cannot be satisfied by never showing it.

### Nineteen restatements, five of which were real

The market view was rebuilt between stages and nineteen assertions across three earlier suites
were still describing the panel that came before it. Each was classified before it was touched.
Fourteen were stale selectors or wording. Five were tests that were right: the chart height, the
legend, the absent threshold, the gate's decision hour, and the dimming of the sixty-day regime
run — which had been reset to full strength by a rule whose comment explains the height and the
gap and says nothing about the opacity, which is the tell that it was collateral rather than a
decision.

Two restatements changed a claim rather than a selector, and both are written down. The strip
legend printed a fixed four-word list including a state a three-state model cannot emit; it is
derived from the payload now. And one fixture was feeding the page wording the backend had
stopped emitting two stages earlier, then demanding the page not show it — which is asking a
page to censor its own data source. The fixture was the stale thing.

### Four mutations came back green, and that was the useful part

Twelve mutations; eight red on the first pass. The four survivors were all findings about the
tests: a text slice that could not tell inside a div from just after it, a substring that
outlived the branch it stood for, a mutation that removed one of the two rules a fix was made
of, and a fixture in which both phases were present so a cross-phase fallback could never fire.
Three tests were rewritten to measure the rendered page instead of the source, a fixture with a
deliberately missing phase was added, and one mutation was retargeted. Twelve of twelve after
that.

One of those rewrites then failed on its own instrument. Measuring content spill reported four
overflows that were not overflows, because a tooltip's pseudo-element is an overlay and is
legitimately wider than the badge it hangs off. Confirmed by measurement rather than argued:
stripping the tooltip class took the offending head from 484 to exactly 462.

### Left open

The panel showed one sleeve's regime as Calm and another's as unavailable, on the same day, from
the same detector. The mechanism is that one reads its label through a deliberate one-day lag
and the other is handed a map in which it looks up the current day — a row that does not exist
during its own trading window, because it is computed from that day's close. The live path
already carries a helper whose docstring calls reading that row "six hours of the future", and
it guards the outer gate while the detector's own lookup does the thing the helper exists to
prevent.

That is reported and not concluded. It was raised as an open question two days earlier and left
unresolved there; this stage's reading advances it by one observation without closing it. It
touches a runtime trading file and a live-versus-backtest divergence, and it belongs to a stage
of its own.

### Nothing moved

No gate, threshold, schedule or trading decision changed, and no runtime trading file was
modified. Orders remain impossible, blocked by shadow evidence. The dashboard backend does need
restarting for any of this to reach the page, because it serves the module it imported at
startup — that is the operator's call and was not done here, and the scheduler is a different
process that stays untouched.

---

## Stage 5ZZZ-G — which regime object the Swing detector is handed

The previous stage left a question open: the panel showed one sleeve's regime as Calm and
another's as unavailable, on the same session, from the same detector. This stage was opened to
fix it by handing the Swing detector a causal, one-day-lagged label object, on the understanding
that this is what the Track 1 Swing backtest already uses.

Half of that turned out to be right and half of it did not, so the fix was not made.

### What is confirmed

The Swing sleeve's live path hands the detector the raw label map, and the detector looks up the
session's own row. A label for a session is computed from that session's close, and the Swing
window runs from five past two until five to four — so the row does not exist while the sleeve is
deciding. On the evening of the twenty-eighth the map's last entry was still the twenty-seventh.

Run through the detector itself, same bars, same parameters, same day, the two objects report
what you would expect: the raw map gives no label at all, the lagged object gives Calm. Both
refuse, and that nuance is worth keeping — this sleeve trades one regime and the label is not it,
so today the outcome is the same and only the reason differs. On a day when the previous session
was Normal and the current row is missing, the outcome would differ.

### What is not

The Track 1 Swing backtest is not causal either. It runs the same lookup against the same raw
map, and the engine's own entry point states the split in as many words: R4 reads the SPY labels
directly, MNKD reads them through a one-day lag. Every caller that produced the record follows
it.

So handing Swing a lagged object would not restore parity with the backtest — it would break it.
Measured rather than asserted, by running the sleeve's own backtest twice over the full store
with nothing different but the labels object: a hundred and eighty-six trades against a hundred
and ninety-one, forty-four entries that exist only under one and forty-nine only under the other.
The two objects disagree on eleven percent of all days. That is a decision with a number attached,
and the brief that proposed it also required historical decision parity to remain unchanged.

The real defect is the mirror image of the one described. In the backtest the lookup returns a
label built from the session's own close and uses it to decide that session's two o'clock entry —
information from after the decision. In live the same call returns nothing, so the sleeve fails
closed rather than reproducing it. The live path is the honest one; the backtest is the one that
cannot be reproduced. The live source already carries a helper whose docstring says exactly this,
and it guards the outer gate only.

Whether this has cost anything in the shadow window is **not measurable**: Swing has produced no
signal in any recorded session, but the regime has been Calm throughout and the sleeve trades
Normal, so it would have refused either way. The confound is total and no live impact is claimed.

### What was implemented

The part that is safe, and that the brief also asked for: the diagnostics now report which regime
object the detector was handed, so the panel can explain the disagreement rather than merely
display it. NKD reports "previous session (lag 1)", Swing reports "this session's own label", and
the Regime row's value is the detector's own gate value rather than a second lookup done for the
display.

The description is derived from the object — it reads the lag off the object itself — because a
hand-written map from sleeve to basis is a map that goes stale the first time a call site changes
and then says the opposite of what the detector saw. A block built without a basis reports none
rather than guessing one.

A guard test now fails if any sleeve changes which object it hands the detector, carrying the
forty-four-against-forty-nine measurement in its message, so that swap cannot arrive as a quiet
edit.

### The decision that is left

The Swing gate reads a label that live cannot have at decision time and that the backtest draws
from after the decision. Making the sleeve causal means re-earning its numbers; keeping the
identity means a sleeve whose rule the live route can never execute; and there is a prior open
question about whether the current session's row could legitimately exist earlier in the day,
which would change the premise. Choosing among those moves a gate, and it is the operator's.

---

## Stage 5ZZZ-H — the whole candidate, with Swing reading a causal label

The previous stage ended with a question nobody could answer from the sleeve alone: Swing decides
on a regime label that live cannot have and that the backtest draws from after the decision, so
what happens to the actual candidate if it reads the previous session instead? This stage
measures it in the full stack, because a sleeve's own numbers do not survive contact with the
portfolio's caps — and this run contains a clean example of that.

### The baseline first

The handoff document's two tables were reproduced from a fresh run of the script that produced
them. Thirty numbers, thirty matches. The inputs were taken from each window's own recorded
arguments rather than from a command-line default: fifty thousand dollars, one micro, two ticks a
side, the family cap at five and four-tenths, and an HMM fit end that differs per window by
walk-forward design — which is why the three rows are never added together.

### One thing changed

The labels object handed to the swing basket, and nothing else. Two checks had to pass or the run
would have been measuring something other than what it claimed: NKD's trade list had to come back
byte-identical, because it never goes through the patched seam and any movement would mean the
change had reached further than intended; and at least one swing instrument had to move, because
otherwise a finding of "no difference" would just be a no-op wearing a result's clothes. Both held
in all three windows. The shared baseline artifacts were copied out before each run and restored,
and their checksums confirm it.

### What it costs

Every window is worse. Ten percent off the in-sample floor, five percent off 2025, thirteen
percent off 2026 — and the same dollar figure under both the full stack and the risk-clean
fallback in each window, which is the arithmetic check that the change touched only what it was
supposed to.

The sleeve table says where it went. Stress and NKD move by exactly zero in all six cells. Calm
moves slightly, and that is real rather than leakage — Calm and Swing interact through same-symbol
suppression, so a different swing entry changes which Calm entry survives. Swing itself gives up
seven thousand two hundred in the floor, seven hundred and eighty in 2025, and in 2026 it stops
contributing at all: it turns negative, a loss of four hundred and sixty-four against a gain of
seven hundred and nineteen.

### The row that justifies not judging a sleeve alone

In 2025, before portfolio caps, the causal sleeve is *better* by a thousand and eighty-one dollars.
After the caps and the overrides it is *worse* by seven hundred and eighty-four. Reading the sleeve
on its own would have inverted the sign of the answer, which is exactly what the brief warned
against and the reason the whole stack had to be re-run rather than the sleeve.

### Why "worse" was the expected direction

The same-day label is built from the session's four o'clock close and gates an entry that happens
between two and four. A rule that reads six hours of the future ought to look better. So the
decline is a measurement of how much the baseline was flattered, not evidence that reading the
previous session is a bad idea.

What it does not settle is whether the sleeve is any good under a causal label, because its
parameters and its context filter thresholds were all chosen while the same-day label was in play.
This run puts new labels through an old filter. That is the fairest single-variable comparison
available and it is also not a fair test of the design.

### Where that leaves the sleeve

Same-day is not live-tradable, so the choice was never between the two label sets — it is between
the causal one and nothing. Under the causal one the sleeve is materially weaker and, in the most
recent out-of-sample window, negative on forty-five trades over eight months. That is not enough
to put it into the paper route and not enough to call it dead.

So: disable it in the paper route, and re-run the selection under causal labels before
reconsidering. Disabling changes nothing operationally — the previous stage measured that live
Swing already refuses every session, because it looks up a row that does not exist yet. What it
changes is that the silence becomes explicit instead of looking like a sleeve that is switched on
and never fires. And re-running the selection is not curve fitting: the original was made on an
information set the live route cannot have, so it has to be redone on inputs that exist.

### One mistake worth recording

The replay was re-run while the regeneration was still overwriting the shared artifact files, and
it reported a floor figure for the *baseline* that was seven thousand dollars low. The checksums
showed the baselines had been restored correctly, the run was repeated with nothing else touching
those files, and all thirty numbers came back. It is written down because a number that appeared
once and then vanished is exactly the kind that gets quoted later by someone who did not see it
vanish.

---

## Stage 5ZZZ-I — retuning Swing under a causal label

The operator's instruction was to keep the sleeve and make it live-tradable by re-running its
tuning against the previous session's regime label. The tuning ran. It did not produce a sleeve
worth promoting, and the reason is worth more than the verdict.

### Recovering the original process

The frozen swing parameters are credited in the code to a pooled walk-forward: a nine-point grid
over the trend period and the trailing-stop multiple, judged on the training fold's Calmar with a
minimum sample, rolling eighteen months of training into six months of test, one shared parameter
per fold across the whole basket.

Running that protocol on its own configuration reproduces the fold geometry exactly — six folds,
matching the recorded "five of six" — and does not reproduce the parameter. Under the fold vote it
selects a shorter trend period; under a pooled whole-region reading it selects a different one
again; and the frozen pair places fourth and third respectively. Three readings, none of them the
recorded answer.

That is reported as **could not be reproduced**, not as wrong. The distinction matters because the
sleeve is running those parameters today, and the gap belongs to whoever owns that decision
regardless of what happens to the causal question. What it changed here is the claim this stage is
allowed to make: not "the original tuning was re-run", but "one protocol, one configuration, one
dataset, applied identically to both label sets, so the difference is the label".

### What the retune chose, and how weakly

Under causal labels the procedure selects the shortest trend period in the grid with the tightest
trailing stop, in four folds out of ten. The control — same protocol, same-day labels — selects the
same pair, also four out of ten, with a second parameter tied at four. Neither arm produces a
majority, the winning parameter changes almost every fold, and one fold is negative. A procedure
that cannot pick stably under the label it was designed for is weak evidence about the other label,
and that is stated before any performance number is read.

### The result

The retuned sleeve is worse than the parameters it replaces, out of sample, on every measure. In
2025 it gives up nearly seven thousand dollars against the current identity and six against its own
predecessor, while taking more trades — the signature of a parameter fitted to the window it was
chosen on. In both out-of-sample windows the sleeve's own contribution is negative.

The fourth route is the one that reframes the question. Removing the sleeve entirely beats every
live-tradable version of it in 2026 on net, profit factor, Sharpe, Calmar and drawdown; and in 2025
it gives up some net in exchange for a profit factor of three against two, a Sharpe of nearly four,
and a maximum drawdown a third the size. The one thing the sleeve clearly does is carry the
in-sample floor — which is the window its parameters were chosen on.

### Where it lands

Not promoted: the bar was out-of-sample evidence, and out-of-sample evidence points the other way.
The sleeve stays enabled in shadow, as instructed, and is not paper-orderable. Nothing in the live
route changed — the frozen parameters are untouched, the detector still receives the object it
always did, and no identity document was rewritten, because none of that is warranted by a result
that failed its own promotion test.

Nor is this a case for dropping the sleeve, yet. Two out-of-sample windows, one of them eight
months and forty-odd trades; a grid of nine points that never contained the hold cap or the context
filter; no bootstrap; and an unstable selection under both labels. The case for dropping is now
materially stronger than it was, and what would settle it is a selection over a wider grid with a
day-level bootstrap and a threshold committed in advance. That is a stage, not a paragraph.

---

## Stage 5ZZZ-J — a regime label read at two o'clock instead of at four

The idea was a good one and it is worth writing down why it fails, because the reason is not
about tuning and will not change with a better model.

Swing decides between two and four in the afternoon on a regime label that is computed from the
market's four o'clock close. Stage 5ZZZ-G showed the live route cannot have that label at
decision time; Stage 5ZZZ-I showed that falling back to yesterday's label does not produce a
sleeve worth promoting. The proposal here was to build something in between: a proxy for today's
label using only what is known by two o'clock, preserving some of the same-day information while
staying causal.

### The data question, asked first

There are half a million SPY five-minute bars on disk covering nineteen hundred and ninety-nine
sessions, and they stop on the thirtieth of December 2024. The floor window is covered almost
completely — seventeen hundred and thirty-two of about seventeen hundred and sixty-three sessions
have a two o'clock bar. Twenty twenty-five has none. Twenty twenty-six has none.

The promotion bar in the brief required the proxy to beat the previous-day label out of sample and
to hold its own against deleting the sleeve, out of sample. Neither was measurable. Promotion was
unreachable from the first measurement, and what remained worth doing was establishing whether the
idea deserves revisiting when the data exists.

### The cheap test, run before any backtest

The proxy's entire job is to stand in for today's label without reading today's close. So the bar
it has to clear is not "is it informative" — it is "does it beat simply carrying yesterday's label
forward", because that is already available, already causal, and already measured.

Carrying yesterday forward recovers today's label ninety-one and a half times in a hundred. The
proxy, built from the gap, the return and range and realised volatility through two o'clock, and
two strictly-prior context features, manages eighty-three. It is nearly nine points worse at the
one thing it exists to do.

The decomposition is the whole story. On the hundred and fifteen sessions where yesterday's label
is wrong, the proxy fixes about half — fifty-six sessions gained. On the twelve hundred and
fifty-five where yesterday's label is already right, it breaks one in seven — a hundred and
seventy-seven sessions lost. Net, a hundred and twenty-one sessions worse.

That is structural. The label is defined by the four o'clock close, so a two o'clock vantage is
missing the last two hours by construction; and the label is enormously persistent, so persistence
is a very strong baseline that intraday movement actively degrades. No amount of model choice
moves either of those facts.

### And in the book

Run through the same replay, on the only window where it can be run, the proxy is last of five
routes and below the route that deletes the sleeve entirely. Swing's own contribution under it is
negative — in sample, on the window it was built on.

The eighteen-month warm-up is the obvious objection: the proxy has no labels before the middle of
2019, so the sleeve refused there and lost trades it would otherwise have taken. But the no-Swing
route refuses on every session of all seven years and still finishes nearly four thousand dollars
ahead. What sank the proxy is not the trades it missed; it is the ones it took.

### Why not simply use ES

The futures data covers every window and would remove the data obstacle entirely. It was not
substituted in, because the floor result says the obstacle is not the instrument: the same
two-hour gap and the same persistent baseline apply to any pre-two-o'clock view of the same
underlying. If that deserves confirming rather than arguing, it is an affordable next step — and
it should be run as a label-recovery test first, which costs minutes, rather than as a backtest,
which costs an afternoon and answers second.

### Where it lands

Swing stays where the operator put it: enabled in shadow, not orderable in paper. No live route
code changed, no gate moved, and the proxy's in-sample numbers are recorded with a warning
attached, because a figure produced on the only window available has a way of being quoted later
as though it had been tested.

---

## Stage 5ZZZ-K — the same test, on the instrument that has the data

The previous stage could not run its own out-of-sample half: SPY intraday stops at the end of
2024, so the proxy idea was judged on the floor alone and left with an obvious objection attached
— maybe the instrument was the problem. The futures data covers everything through last week, so
the objection is answerable cheaply, and answering it cheaply is the whole point of running a
label-recovery test before a backtest.

### Coverage, and a clock settled by measurement

Nearly every session is there: ninety-eight and a half percent of the floor, ninety-nine and a
half of 2025, all of 2026 to the nineteenth of August. The proxy could finally be scored out of
sample.

The parquet's index carries no timezone, and this repo has already paid once for two loaders
disagreeing about which clock a file is on, so it was settled by looking at where the volume
lands rather than by reading a comment. Treated as universal time, four fifths of the volume falls
inside the trading session with the peak in the closing hour, which is what the contract actually
does; treated as New York time, two fifths does and the peak sits overnight. Universal time, then.

### The answer

It loses in every window, including both out-of-sample ones. Ninety-one and a half against
eighty-two on the floor, eighty-seven and a half against eighty-two in 2025, eighty-seven against
seventy-six in 2026. The promotion bar's first clause was that it must beat persistence out of
sample, and it does not, so no backtest was run.

The shape is the same everywhere: it repairs about half of persistence's mistakes and breaks
several times as many of its successes. Twenty twenty-six shows it most clearly — the proxy is at
its best there at fixing errors, correcting nearly two thirds of them, and still finishes eleven
points behind because it broke thirty-one of the hundred and thirty-eight days persistence already
had right.

### The part that matters for the sleeve

Swing trades one regime and no other, so the state to judge on is Normal — and Normal precision
falls in every window, by eight, ten and eighteen points. In the two out-of-sample windows the
proxy buys a little Normal recall and pays for it with much more Normal precision, which for a
single-regime sleeve is the worst trade on offer: it fires on more sessions and a larger share of
them are not the regime it trades.

Twenty twenty-six makes it concrete. The proxy called Normal on a hundred and twenty-four
sessions; eighty-eight of them were Normal, thirty-two were Calm and four were Stress. It never
predicted Stress at all, and Calm recall halved. The sleeve would have traded thirty-two calm
sessions it should have sat out, inside eight months — and the separation between the quiet and
the violent states is not merely dented, it is gone.

### What two instruments agreeing tells us

SPY lost to persistence by nearly nine points on the floor; the futures lose by nearly ten on the
same window. Two independent measurements landing in the same place is itself the finding: **the
limit is not the instrument.** The target is defined by the four o'clock close, so a two o'clock
vantage is two hours short by construction, and the label is persistent enough that yesterday's
answer is very hard to beat. Adding the overnight session — real information the equity has no
access to — moved nothing.

That does not make the idea dead, only unpromising in this form. A later cut would sit closer to
the close and stay causal, though not for a sleeve that starts at five past two. Predicting
whether a trade would have worked, rather than predicting the label, skips the two-hour gap
altogether. And an objective weighted toward precision would give up recall on purpose instead of
by accident. Each of those is another minutes-long recovery test, and the last two stages have
both shown that is the right thing to run first.

### One tooling failure, recorded

The probe's first run reported zero usable sessions in all three windows. That is not a data
finding; it is an empty result, and an empty result is a reason to suspect the instrument before
believing it. The overnight join had been grouped on raw values, which strips the timezone, so
every lookup against the session index produced nothing and the final drop emptied the frame. It
now carries two assertions that make the same mistake loud rather than silent.

---

## Stage 5ZZZ-L — the wider grid, and what it found underneath

The narrow retune in Stage 5ZZZ-I searched nine points and concluded the sleeve did not improve.
The objection was fair: nine points in two dimensions, with the hold cap and the context filter
frozen, does not settle whether a causal Swing exists. This stage searched forty-eight, on a
wider range in both dimensions plus the hold cap, and committed the grid and the promotion
thresholds to a file before any out-of-sample number was produced.

It found a better answer to the tuning question and a worse problem underneath it.

### Two engines called the same thing

The class that generates the promotion artifacts imports one implementation of the swing
backtest. The script the repository credits for the frozen parameters — and the retune in the
previous stage — used a different one. They are not the same object, and on identical inputs they
are not the same behaviour: same day, same instrument, same labels, and the trade counts and
profits differ by four figures.

So the previous tuning was selecting parameters with an engine that is not the engine that
trades. This stage tuned on the one that makes the artifacts, and the mismatch is very likely
part of why the frozen parameters' provenance could not be reproduced two stages ago.

### The selection

Forty-eight candidates, ten folds, floor only. The winner is a trend period of fifty with a
trailing multiple of two and a five-day hold, chosen in five of ten folds — and in the first five
consecutively, rather than as a plurality scattered across the run. That clears the stability
threshold committed in advance, and it is a better answer than the previous stage's four in ten
with a tie.

The more interesting fact is where the winners live. Every combination that won a fold used a
trailing multiple of two or two and a half, and eight of the ten used two — a value the old grid
did not contain, because it started at two and a half. The previous search had excluded the
region its own objective prefers.

### And then the hashes

The winner then has to be run through the full stack, which means regenerating the promotion
artifacts with those parameters. The regeneration reported, from the call site that reads them,
that the engine had been handed exactly the requested values. The artifact it produced was
byte-identical to the one produced by the default parameters — over the seven-year floor window,
with about a hundred and ninety trades per instrument.

That is not a coincidence and it is not a result. Checking further: a trend period of fifty and
one of thirty produce the same artifact, while ten and twenty each produce different ones. The
regeneration installs an engine of its own, configured with its own trend period and stop basis,
and whatever it does with the parameters it is passed, it is not the pass-through the last two
stages assumed.

I did not resolve the mechanism, and I did not report full-stack numbers produced by a path I
cannot show is doing what it is told. The regeneration now refuses to finish if an override
produces an artifact identical to the unoverridden run, so the same silence cannot happen again.

The cost of this is not confined to the present stage. The previous stage's retuned arm did change
its artifact, so something moved — but it can no longer be claimed that what moved was cleanly the
one parameter it named. That conclusion is now provisional.

### What could still be measured

One arm was safe, because it needs no parameter override at all: every artifact already carries a
second trade table built with the stricter volume feature, the one that does not read the entry
bar's own volume. Swapping that table in is a data substitution, not a tuning change.

It is the only Swing arm that has ever beaten the same-day reference out of sample — better net in
2025, a larger sleeve contribution, and a smaller drawdown than the previous-day baseline. And in
2026 it is worse than that baseline and worse than deleting the sleeve on every risk measure. One
good window, one bad one, which is the pattern every arm has shown so far.

### Where it leaves the sleeve

Unchanged: enabled in shadow, not orderable in paper. The parameter question is no longer blocked
on evidence but on tooling, and the order of work is now fixed — understand why the regeneration
ignores the parameter, re-run the previous stage's arm, and only then judge the new winner against
the thresholds that were committed before any of this was seen.

---

## Stage 5ZZZ-M — the parameter was obeyed; nobody wrote down that it had been translated

The previous stage asked the artifact regeneration for a trend period of fifty, watched it
produce a file byte-identical to the one made with the default of thirty, and stopped — correctly,
because reporting performance from a path that might be ignoring its instructions is worse than
reporting nothing. This stage found out why, and the answer is not disobedience.

### The line

Inside the replacement engine the regeneration installs, there is a rule: when the caller asks for
a trend period of thirty, use the configured one instead. The regeneration configures fifty. So a
request for thirty *is* a run at fifty, while ten, twenty and fifty all pass through untouched.

That accounts for every observation exactly. Thirty and fifty give one artifact because they are
one run. Ten and twenty give their own because nothing rewrites them. Four regenerations, each
recording what the engine received, land precisely where the rule predicts.

The substitution is deliberate. The Rổ 4 basket's frozen trend period is thirty; Track 1's own is
fifty, and the rewrite exists so the basket runs Track 1's. What was missing is that **nothing
anywhere recorded that the translation had happened** — the artifact carries the arguments it was
called with and never the parameters it ran with. A documented translation and a broken pipeline
looked identical from outside, and it cost a stage to tell them apart.

### The cache was not the culprit

Worth stating because it was the obvious suspect. There is a cache, and it is keyed on the frame's
identity alone, which would be a serious defect if it held anything the parameters change. It does
not: daily volatility, the day list, per-day price arrays, per-day five-minute frames. Its own
docstring says it is keyed that way so a walk-forward can reuse it across parameter calls. The key
is complete for what it holds, and that is now asserted twice — once by reading the code, and once
by pushing the same frame object through the engine at two trend periods and confirming the trades
still differ.

### The fix, and why it is a sidecar

The promotion artifacts are hash-pinned baselines that several stages reproduce against, so adding
a field to them would break the very reproductions that give them value. The effective parameters
go in a small file beside each generated artifact instead: what was asked, what was run, whether a
substitution occurred, and the stop basis and ratchet setting that decide whether the trailing
multiple means anything at all.

The previous stage's guard is corrected too. It compared digests and fired on a true equivalence.
What has to hold is narrower and two-directional: artifacts match if and only if the effective
parameters match.

### What it does to the record

Nothing measured is wrong. Every number came from a pipeline doing what it was built to do. The
labels were wrong, and in one place that matters a great deal: every arm called "the D-1 old
parameters, trend period thirty" across the last three stages was in fact running fifty.

Which means the full grid search's winner — a trend period of fifty with a trailing multiple of
two — is, in this pipeline, *the configuration the route already runs*. The trailing multiple
changes nothing here, because with the ratchet off and a stop basis set the day loop never
recomputes the stop; that is stated in the parameters' own docstring and is now measured rather
than trusted.

So the previous stage's numbers were not unobtainable after all: the winner's numbers are the
existing arm's, and its promotion thresholds can finally be scored. Three of five pass. Two fail —
the sleeve does not pay for itself in the more recent out-of-sample window, and its risk-adjusted
return sits at about two fifths of what deleting the sleeve achieves. The verdict is unchanged and
is now evidence rather than an apparatus failure, and the search has a cleaner headline than it
appeared to have: forty-eight candidates under a causal label converged on what is already
deployed.

Neither of the previous two stages needs re-running. Both needed a correction to what their arms
were called, and that is now written down where the next reader will find it.

---

## Stage 5ZZZ-N — the canonical baselines, reproduced, and the paper decision

Ten stages produced numbers under four regime bases and five parameter sets, and the most
expensive mistake in that sequence was a label rather than a measurement. So this stage does not
copy a single figure forward. Both baselines were regenerated or replayed from code in this
sitting, and the parameters they actually ran under are recorded beside them.

### Two baselines, and they are not the same baseline

The historical reference — the numbers the handoff document has carried since August — reproduce
exactly, all thirty of them. They are the **same-day** figures: seventy-four thousand on the
in-sample floor, seventeen and nine on the two out-of-sample windows. They are also **not
tradable**, because the regime label they depend on is computed from the four o'clock close and
cannot exist while the sleeve is deciding at five past two. They stay in the record as a
reference and nothing more.

The live-tradable baseline is the causal one, and it was rebuilt from the engine rather than read
off a shelf: sixty-six thousand eight hundred on the floor, sixteen thousand one hundred and
eighty-one in 2025, eight thousand one hundred and five in 2026, with the sleeve contributing
eighteen thousand, four thousand, and minus four hundred and sixty-four. The regenerated
artifacts came back byte-identical to the ones the previous stages used, which is what makes the
reproduction a proof rather than a re-run.

Three things are now on the record that were not before. The parameters the engine ran with —
fifty, not the thirty that was asked for — sit in a file beside each artifact. The regime basis is
proven rather than asserted: on all one hundred and forty-seven sessions in the floor window where
the same-day and previous-day labels disagree, the object handed to the engine returned the
previous day's value, every time. And the promotion artifacts' checksums are identical before and
after, so nothing that other stages reproduce against was disturbed.

### The decision

Swing goes into paper scope by explicit operator risk acceptance, on the causal previous-day
label at an effective trend period of fifty. That is a decision, not a result, and the report says
so in those words — because the thresholds committed before the search was run come out two-fifths
short. The sleeve does not pay for itself in the most recent out-of-sample window, and the route
without it is better risk-adjusted in both. Writing the override down without writing that down
next to it would be the kind of half-record that costs a later stage a week.

What the evidence does support is the *choice among* the tradable options. Forty-eight candidates
under the causal label, searched on the engine that actually builds the artifacts, converged back
onto the configuration the route already runs. The narrower retune is worse in both out-of-sample
windows. The equity proxy has no out-of-sample data to be judged on and sits below deleting the
sleeve in-sample. The futures proxy loses to simple persistence in every window. The stricter
volume filter posts the best 2025 of anything measured and the weakest 2026 with a larger
drawdown, which is one good window rather than a case.

### Eight variants, one table, and the gaps left as gaps

The canonical table carries all eight arms with their regime basis, what was requested, what was
effective, whether each is tradable, and what was decided. Where a window was never run — the two
proxies, for different reasons — the cell says so instead of holding a zero. A zero would read as
a measured result, and the difference between "we looked and found nothing" and "we could not
look" is exactly the distinction these stages have spent themselves defending.

### Still not ready

Orders remain impossible, the shadow-evidence blocker is untouched, the confirmation file
approves nothing about orders, and no broker was contacted. All four sleeves are in scope by
decision and not one of them has paper evidence yet. What stands between here and paper orders is
unchanged: real shadow sessions across all four sleeves, an account baseline fresh enough to close
the other blocker, and the operator's override recorded in the route's own decision trail rather
than only in a report.

---

## Stage 5ZZZ-O — the override moves out of the report and into the route

The previous stage ended with the operator accepting the risk of carrying Swing into paper, and
with that acceptance living in a document. A report is the one place a route cannot read, so the
decision was, in every operational sense, not recorded at all. This stage puts it somewhere the
route can see it and nowhere it can be mistaken for permission.

### Following the pattern that already exists

The route has a decision mechanism worth imitating rather than working around: a signed
confirmation file that only a person writes, and a preview module that reads it with no code path
capable of writing anything, asserted by its own test. The new record and its reader hold
themselves to the same contract — strict validation, fail closed, and an assertion that walks the
module's syntax tree looking for a write and finds none.

### Measured before it was built

Before the module existed, the gates answered: orders not possible, one blocker, and no mention
anywhere in the gate source of any swing override. That measurement is what makes the central
claim of this stage a fact rather than an intention.

### What the record says, and what it refuses to say

It names the decision, who accepted it and when, the route, the sleeve, the regime basis and the
selected identity — and it carries the four reasons against the decision as validated content
rather than as commentary. Drop any one of them and the record is refused: an override whose
reasons-against have gone missing reads as an endorsement, and this one must never be quotable
without them.

Two claims it is forbidden to make. A record asserting a parameter promotion is refused; so is one
asserting an evidence promotion. Those are the claims this whole sequence of stages declined to
make, and a file that could assert them would let a later reader undo that by editing JSON.

### That it grants nothing is measured, not asserted

Three ways. The object itself reports no authority on any of four fields, valid or not. The gate
source contains no reference to the module, matching what was measured before it was written. And
the strongest form: a test moves the record aside, asks the gates again, restores it, and requires
the two answers to be identical. If the gates move when the record leaves, it is not inert, and
that test says so.

A valid record and a corrupt one grant exactly the same thing. The only difference is what an
operator is told.

### Where it shows

In the readiness report, above the legacy block rather than after it, with all four caveats
printed and two sentences saying in plain words that this is not a parameter promotion and does
not satisfy the evidence gate. The position is pinned by a test — a change that buries it under
the legacy section turns red — because "do not bury this" is a property, not an intention.

### One thing worth recording about the harness

The mutation run reported that the new module had not been restored byte-identical. It had been
restored; the round-trip had converted its line endings to the convention the rest of the package
already uses. Content verified unchanged, no mutation text surviving, every test passing. Written
down rather than waved away, because a restore check is only worth having if the one time it fires
gets an explanation instead of a shrug.

### Still not ready

Orders remain impossible, the shadow-evidence blocker is untouched and cannot be satisfied by this
record, the confirmation file approves nothing about orders, and no broker was contacted. All four
sleeves are in paper scope; not one of them has paper evidence. What the route gained today is not
permission — it is the ability to say, out of its own files, that one of its sleeves is there
because a person accepted a risk, and exactly which risk that was.

---

## Stage 5ZZZ-P — did the live slot decide what the code decides?

Every stage so far has proved something about the code or about the numbers. This one asks a
different question: when a slot actually ran, did it decide what a replay of the same context
decides? A dashboard showing that evidence exists is not the same as evidence that the two agree.

### The answer is that nobody can know yet, and that is the answer

The newest live slot ran at a quarter to one on Friday afternoon. The newest of the changes this
parity is about landed at half past midnight on Saturday. Nothing has run since, and today is a
Saturday. So all four sleeves come back as not yet observed.

A corroborating fact rather than an inference: the runtime diagnostics directory that Stage
5ZZZ-B wired does not exist on disk. It would have been created by the first slot to run after
that change. Its absence is the same statement as the timestamps, arrived at independently.

Not-yet-observed is not a soft pass, and the tool is built so it cannot become one. A slot older
than the code it is meant to exercise proves nothing about that code however well its fields
line up.

### The harness, and why it reuses what already exists

The replay side runs the market view's reconstruction rather than a new one. Two earlier stages
established that reconstruction mirrors the live call sites exactly — the same parameters, the
same labels object, the same detector. A parity check whose two halves come from two
implementations is comparing the implementations, not the route.

Four verdicts, and one rule that carries the weight: a partial match is unknown, never a pass. A
slot missing a field is not a slot that agreed; it is a slot that cannot be checked, and those
are different facts about a route about to trade.

### What the older slots showed anyway

Run against Friday regardless — informationally, counting for nothing — so the harness is proven
to work and the gaps are visible now rather than after the next session.

Three of the four agree on everything comparable, and Calm's two phase-isolation checks pass: the
decide card carries no observe-only value and no price level. Swing does not agree. The paper
identity signed into the decision trail yesterday says the regime basis is the previous day's
label; the detector reads the session's own. Both of those statements were already known
separately, and this is the first place they have been put against each other.

The distinction worth keeping straight: the artifact and backtest identity really is the previous
day's label — proven last stage on a hundred and forty-seven sessions where the two labels
disagree. The live detector is not. The signed record describes the first of those. It changes no
number and does not invalidate the override, but an operator reading "causal D-1" in the decision
trail deserves to know the live path does not yet read that way, and there is now a check that
will keep saying so.

### Three gaps, all left as gaps

No live row records a parameter hash. No live row records a regime basis — which means the two
sleeves whose identity turns on it cannot reach a pass at all today, however well everything else
lines up; that is pinned by its own test so it is never mistaken for a passing sleeve. And the
data identity is spelled two ways, a full path on one side and a bare file name on the other. The
comparison now matches on the file, because a false failure is worse than an honest unknown —
someone acts on it — and the inconsistency is written down here instead of being hidden by the
fix that stopped it misreporting.

None of the three is fixable from the reading side. They need the live writer to record more.

### Where it leaves the route

Nothing was wired as a gate, nothing was marked satisfied, and the tool declares in a field of its
own output that it counts toward no evidence. What is needed to answer the question is one Track 1
session after half past midnight on Saturday — which is Monday — and two more fields on the row
the slot already writes.

---

## Stage 5ZZZ-Q — the live Swing detector reads yesterday's label

For eight stages the route said one thing about Swing and did another. The signed paper identity
recorded that the sleeve decides on the previous session's regime label. The backtest, the
artifact and the regeneration all genuinely did. The live detector did not: it was handed the raw
label map and looked up the session's own row — a row computed from that session's four o'clock
close, which does not exist at five past two. So the outer gate passed on yesterday's label and
the detector immediately refused on a missing one, every session, silently.

### The conflict, resolved before the edit

The brief asked for the fix and also forbade editing runtime trading files, and the fix is one
line inside a runtime trading file. That is not an ambiguity to be resolved by preference, so it
went back to the operator, who authorised the change. Every edit below follows that.

### What actually changed

Three lines of substance. The live path now wraps the labels in the same one-day lag the NKD path
forty lines above already used and the artifact regeneration already applied — so the outer gate
and the detector finally read the same object. The signal row gained a field naming which regime
object each sleeve's detector was handed. And the market view's reconstruction lags Swing's labels
too, because a replay handed a different object from the slot shows what the slot did not see.

Proven from the call rather than from the code: the detector was intercepted on the live path and
asked what it received. Four instruments, all `RegimeLabels(lag=1)`, all resolving to the previous
session's label where the same call used to resolve nothing. NKD unchanged. And independently, on
all hundred and ninety floor sessions where the two labels disagree, the object returns the
previous one and never the session's own.

### The hash that stayed empty, on purpose

The previous stage found the parameter hash blank on every live row and flagged it as a gap.
Trying to fill it turned up the reason, and it is a contract rather than an oversight: the
canonical identity refuses any config missing one of its twenty-seven fields, and one of those is
a checksum of the parquet. Hashing a multi-gigabyte file on every slot would put real work on the
decision path for a diagnostics field — which is exactly why the neighbouring helper records the
path alone.

So a cheap hash would be the partial identity that module explicitly forbids. The helper now
returns empty deliberately, says why, and points at the explanation record, which already writes
the full identity for the same run. That is where a parity check should join it from, and until it
does, a post-fix slot is capped at unknown. Named, not papered over.

### Nothing else moved

The artifact path runs through the simulator and the basket engine, not through the live source,
so the live change cannot reach it — and that was verified rather than assumed. The artifacts came
back byte-identical and the selected baseline reproduced on all six figures. No parameter changed.

Four earlier tests were restated and none deleted. One of them was a guard written three stages
ago that asked, of exactly this change, "who decided?" — it is now inverted rather than removed:
Swing must keep the causal object and NKD must never lose it. Another asserted the two sleeves
disagree on the regime; it now asserts they agree, because removing that disagreement at its
source is what this stage was for.

### The part the operator should keep in view

Live Swing used to refuse every session because its detector could not resolve a label. It will
now decide. Orders remain impossible and nothing can be sent, but the sleeve's shadow decisions —
the input to the evidence gate — change from always refusing to actually deciding from the next
session onward. This is the first change in the whole sequence that alters what the live route
does rather than what it writes down.

---

## Stage 5ZZZ-R — restarting a scheduler that had already been restarted

The stage was written to put the previous stage's Swing fix into a running scheduler that was
assumed to still be holding the old code. The first measurement said otherwise. The process
table reported a scheduler that did not match the pid closed out an hour earlier, and the
operations log carried the reason: a restart had run from outside this session at just before
nine, replacing both the scheduler and the backend. The fix had therefore been live since then,
not since anything done here. Who ran it is not recoverable from the evidence, so it is left
unattributed.

The restart still went ahead, on a Saturday with no session, nothing running, the next job of
any kind more than a day away and the books flat on every count. It produced one correction
worth keeping: the brief expected the backend to survive the command, and the command is
defined as replacing the scheduler, its children and the backend. The backend was replaced, as
designed, and the same thing had happened in the earlier external run.

Proving the fix is actually loaded took two independent lines, because a start time only shows
what a process would have imported. The process side is clean — it started after the last edit
and nothing on disk moved afterwards. The behavioural side is better: the freshly started
read-only backend reports the Swing sleeve's regime basis as the previous session, lagged by a
day, which is the whole substance of the fix. That path was located precisely in the payload
rather than accepted from a substring match across the whole document, after a careless scan
earlier in the same stage had matched its own search terms and reported five running slot
processes that did not exist.

Nothing has run on the new code yet. Saturday is not a trading day, so parity reports the only
honest verdict available, which is that no post-fix slot has been observed, on any of the four
sleeves. The first one that matters is Monday afternoon in New York, which is Tuesday morning
for the operator and, for the night sleeve, Sunday evening on the machine's own clock.

The evidence gate was not touched and still blocks. It fails on two counts, and underneath both
sits a fact that neither of them states: every day in the qualifying window was recorded before
the fix, and the window admits no failures at all, so it cannot become a post-fix window until
a full five post-fix trading days have run. Whether those days will pass is not something this
stage is in a position to say, and it does not say it.

Five tests in an old suite fail. They pin values written on the twenty-third against a system
that legitimately changed on the twenty-seventh, when the SPY ladder added jobs and the operator
signed the retirement confirmation. None of them reads the process table, so the restart cannot
be their cause. They have been left failing rather than quietly re-pinned, because re-pinning
asserts the new numbers are the right ones, and that is a decision belonging to the operator
rather than a side effect of restarting a scheduler.

---

## Stage 5ZZZ-S — a cold-start cost reported as a steady-state one

The stage began from a number the previous stage had produced, and the first job was to check
it. Re-measured on a quiet machine, the two endpoints answered in about a second each, nowhere
near the twenty-three seconds on record. The earlier readings had been taken while an abandoned
request was still running inside the server, so they measured the machine competing with itself
rather than the cost of answering. Half the premise was an artefact of how it had been measured,
and that half was mine.

The other half held. In a fresh process the market view took seventy-one seconds to build and
just over one second to build again, a sixty-fold cliff. The cause is a full pass over the bar
history — a five-minute resample repeated more than eleven thousand times — cached on the
identity of the frame object, so a new process pays for all of it and a warm one pays for none.

What turned an expensive computation into a dashboard fault was where it ran. It was computed on
the request path, so the first page load after a backend restart waited for it, and so did every
other panel on the page, including the ones that did not depend on it. That was a deliberate
choice by whoever wrote it, recorded in a comment: pay once rather than show an empty panel. It
was not changed silently. The reasoning now sits beside the new behaviour, and it turns on a
distinction the original trade did not have available — an empty panel says nothing, while a
panel that says what it is doing and that it will fill in shortly is not the thing that trade was
trying to avoid.

Three expensive sections now compute in the background and report an explicit waiting state until
they are ready. The one that already had a well-designed cache keyed on file modification times
kept that key untouched; only the moment of computation moved, never the thing that invalidates
it, because a timer there had been considered and rejected upstream for a sound reason.

Warm, the market view now answers in a hundredth of a second and the payload is identical to
before, key for key, including the regime basis the previous stage had just corrected. Cold, the
first request is eighteen seconds instead of more than three hundred.

One cost was left in place with its reasons stated. The runtime endpoint spends most of its two
seconds re-parsing source files to verify that every live bar path is joined through the guard, a
safety check that runs twice per request. Speeding it up properly means memoising a pure function
inside a runtime trading file, which this stage was not permitted to touch, and caching it in the
dashboard instead would mean serving a safety display stale. So it stands, named, with the fix
that would work written down for whoever authorises it.

A change of mine did break something, and an existing guard caught it: the stress panel stopped
honouring a caller that names a specific instant, which is a convention the route holds to
everywhere else. Five contract tests failed on exactly that, and after the fix the suite is
whole again. Five other failures remain, and none of them belong to this stage. Three were
re-run with the old inline behaviour restored in memory and fail there too; two pin values that
later stages deliberately superseded. They are left failing rather than quietly re-pinned,
because re-pinning would assert the new values are the right ones, and that is not this stage's
call to make.

---

## Stage 5ZZZ-T — remembering what a file said, never what the gate concluded

The previous stage found the order gate re-parsing forty modules on every request and left it
alone, because the file it lives in is a safety file and that stage had no mandate to touch it.
This one had the mandate, and the bar was higher than making it faster: the gate had to give the
same answer, and it had to stay unable to call a file clean when it cannot read the file.

The scan is now remembered against the identity of the file it read — the resolved path, the
modification time in nanoseconds, and the size. Each part covers what the others cannot.
Nanoseconds rather than seconds, because a coarse clock lets two edits inside one second look
like the same file. Size as well as time, because a rewrite can restore a timestamp. Slipping
past both at once would take two files of the same length carrying the same nanosecond stamp,
which is not a thing that happens by accident.

The order matters as much as the key. The file is stated before the cache is consulted, so a
module that has gone missing raises exactly where it used to and is never answered from an
earlier reading. That is the whole point: not seeing a file and seeing a clean file are the two
answers this gate exists to keep apart, and a cache that blurred them would be worse than a slow
one.

What is remembered is only the set of names parsed out of a file, and it is frozen so a later
caller cannot edit what the next one measures. No decision is cached. No blocker list, no
measurement, nothing that depends on state a file timestamp cannot speak for.

The gate answers six times faster and the dashboard endpoint went from just under two seconds to
about two thirds of one. The proof that it answers the same thing is not a summary comparison but
the whole ledger, every blocker with its live measurement, captured before the change and after,
and identical byte for byte.

Seven tests in older suites fail alongside this work, and none of them belong to it. Each was
re-run against the original uncached function and fails there too; they pin a confirmation file
that did not exist when they were written, and a slot count that has since grown by one. They are
left failing rather than quietly re-pinned.

The scheduler was not restarted and still holds the older module. That costs it the speed-up
until it next starts, and nothing else — the two processes compute the same verdict, so they
cannot disagree about whether orders are possible.

---

## Stage 5ZZZ-U — an index, and the difference between what a sleeve earned and what it adds

Track 1 had accumulated five hundred and fifty-eight files that look like baselines. Most of them
contain real numbers, and that is the problem: a measured variant, a rejected proxy, a retune that
was never promoted, all sit in the same directory as the figures the route actually runs on.
Nothing was deleted or moved. Instead there is now one index that says which numbers are official,
and a manifest that gives every other file a status and a reason not to quote it directly.

The stage arrived with the numbers to publish already written out. They were checked anyway, field
by field, against the recorded reproduction, because an index is the one document people quote
without re-deriving, and a figure retyped into it becomes canonical by default. All thirty-six
headline numbers matched.

One label did not. Three figures had been handed over as Swing's contribution, and they are
instead Swing's own profit and loss — an accounting split of the total, not a measure of what the
sleeve adds. The difference is available in the same artifact, because a run without Swing had
already been measured: removing the sleeve costs about a thousand dollars less than its own P&L
suggests, since the other three earn a little more when it is not competing with them for
capacity. On the most recent window, the one the operator's risk acceptance is most exposed to,
the marginal figure is the worse of the two. Both are now published side by side and labelled,
because publishing one of them alone is how they get confused.

The classification itself needed a guard. Ten high-risk files were curated by hand, and four of
those paths turned out not to exist — filenames written from memory rather than read from disk, so
the curation was quietly doing nothing for them. The script now refuses to run if a curated path
is missing, which is the only reason this surfaced before it shipped rather than after.

The validation suite checks the index against the artifact rather than against pinned literals, so
the document cannot drift from the thing it describes without a test going red. It also checks for
absences: the index may never say the same-day variant is tradable, and may never claim orders are
possible. And it confirms every file the index points at exists, which is the failure the guard
above had just demonstrated is real.

---

## Stage 5ZZZ-V — a cleanup that stopped at the first measurement

The stage was to archive more than a thousand tracked artifacts left behind by the Track 1 work.
Asking git rather than the filesystem gave a different picture: eight hundred and twenty-nine
tracked files, three of them in the scratch directory, and none of those three anything to do with
Track 1. The Track 1 material — every stage report, the canonical index, the pipeline document and
both decision records — is untracked. Archiving stale tracked artifacts and archiving the Track 1
backlog turned out to be two separate jobs that the brief had treated as one.

What is tracked is overwhelmingly alive: source, tests, operational documentation, runtime
evidence, and a hundred files already sitting in the archive from an earlier sweep. Forty-six
files looked genuinely stale, and all forty-six are old one-off diagnostics from the stocks and
futures work rather than anything from this sequence.

Two things then happened that are worth recording for their own sake.

The first was a bug in the tool doing the classifying. Its reference scan read code, markdown,
json, javascript and html, and not stylesheets — so every font file in the dashboard came back as
referenced by nothing, and eighteen of them landed on the list of things to archive. They are
referenced, from the stylesheet the scan could not see. It surfaced because the list was read
rather than counted: eighteen fonts sitting in a list of stale diagnostics does not look like a
list of stale diagnostics.

The second was the guard doing its job. Twenty-three of the remaining candidates are top-level
diagnostic scripts, which the classifier calls source, and the brief forbids moving source. The
easy path was to reclassify root scripts until the guard stopped objecting. On a stage whose whole
purpose is not breaking anything, that is the wrong instinct, so the judgement went to the
operator instead — who chose to archive nothing yet, and to keep the repo's existing archive
convention over the new dated directories the brief proposed.

An accident then supplied the argument for that decision. Collecting the test suites turns up two
long-standing failures, and one of them is a test importing a module that an earlier cleanup moved
into the archive. The move was never written into the archive log the way the futures moves were,
with a reason, a replacement, and a check that nothing imported it. The test has been broken ever
since. It is the precise failure the checks in this stage exist to prevent, already present in the
repository, and it was found while confirming that this stage had broken nothing.

The history report was written regardless, since it depends on none of that: thirteen sections
tracing how Track 1 reached its current numbers, and why the ones it publishes are the ones to
quote. It carries both of the Swing figures rather than one, because the difference between what
the sleeve earned and what it adds is the distinction the previous stage had to correct in a
hand-off.

---

## Stage 5ZZZ-W — planning an archive, and finding the route was never committed

The stage was to plan an archive for the untracked Track 1 backlog, and it produced one: twelve
hundred and twenty untracked files inventoried, six hundred and thirty-five of them Track 1, three
hundred and seventy-nine proposed for archiving, nothing moved. But the thing worth carrying out
of it has nothing to do with tidying.

The Track 1 route is not in version control. Forty source files under the global index, including
the order gate itself, have never been committed — not on this branch, not on any branch. The
market view and the runtime reader in the monitor backend are in the same state, as are the B1
evidence files and the signed override that puts the Swing sleeve in paper scope.

This is not the same thing as the two paths that are kept out of git deliberately. The
confirmation record and the runtime evidence directory are both excluded on purpose, and the
ignore file says why in each case: one arms the route and must never be something a checkout can
create, the other is append-only output measured in megabytes. Those are decisions with reasons
attached. The forty source files were simply never added, and the two cases are distinguishable
because the listing that produced them already excludes anything ignored.

There is an inconsistency inside that, too. The confirmation record is deliberately ignored and
documented. The override record sitting beside it is neither ignored nor committed. Two decision
records of the same kind, treated two different ways, and only one of the treatments looks
intended.

The cost is not hypothetical and has already been paid once. An earlier stage in this sequence
tried to attribute a test regression using git and could not, because the file it wanted to
compare against does not exist in any commit; it had to neutralise its own change at runtime
instead to find out whether the failures were its doing. Committing the route is a decision with
real consequences and it should not ride along inside a cleanup, so it is measured, raised, and
left where it belongs.

The plan itself earned its keep twice over. Two active tests import the very modules the first
pass had listed for archiving — the same failure that broke a test in an earlier sweep and left
it broken to this day. And two pairs of files share a basename, so flattening them into a single
archive directory would have had one silently overwrite the other, which is data loss rather than
a broken link. Neither was visible from the outside. Both were only findable by writing the plan
down before acting on it.
