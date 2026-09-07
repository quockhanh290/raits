# Track 1-only shadow — dashboard monitor wiring audit and fix

**Session 2026-08-24 · live scheduler PID 33868 left running throughout · nothing committed**

---

## Root cause

Two children of one `ops.py up` disagreed about which route was running, because only one of
them was told.

```python
start_scheduler(...)  ->  env=_env(track1_shadow=track1_shadow, track1_only=track1_only)
start_backend(...)    ->  env=_env()          # no arguments
```

`ops.py status` reads the mode off the **running scheduler's own command line**, so it was
right: `track1_mode=track1-only-shadow`. The backend had no command line to read — the
environment is its only channel — and it was handed a legacy one. Measured on the live box
at port 5002 before any change:

```
/api/v1/schedule-status : state_slot_count = 45      next_decision_job = MAX_HOLD_EXIT
/api/v1/track1-runtime  : route = track1_candidate   coverage present = True
```

The operator's dashboard was describing a system that was not the one running.

### Two more defects found while fixing it

Neither was in the brief; both would have made the first fix worse rather than better.

**A. The transitional flag never set anything.** `_env` set `RAITS_TRACK1_SHADOW` *inside*
the `track1_only` branch. A `--track1-shadow` start therefore gave its children the ledger
and telemetry homes but never the variable naming the mode. Harmless for the scheduler
(argv), silent failure for the backend. My own test caught this, not inspection.

**B. Propagating the env alone would have lit the dashboard up with phantom incidents.**
`_pipeline_slots_for` has dropped the 45 legacy strategy slots in track1-only mode since
Stage 5M-D. The **health** table had not — so the two halves of one mirror disagreed.
Measured on a synthetic but perfectly clean Track 1 day:

| | before | after |
|---|---|---|
| `state_slot_count` | 115 | **70** |
| legacy slots reported `unexplained_overdue` | **32** | **0** |
| `freshness` | `late` | **`fresh`** |

Fixing env propagation and stopping there would have replaced a dashboard that showed the
wrong route with one that showed the right route in permanent false alarm.

**C. There was no safe command to apply the fix.** `restart --no-scheduler
--track1-only-shadow` **refused**, and its advice was `restart --scheduler
--track1-only-shadow` — bounce a live scheduler to correct a dashboard. The refusal was
written when the flag genuinely had no effect without a scheduler start; that premise stopped
being true the moment the flag started reaching the backend.

---

## Files changed

| File | Change |
|---|---|
| `monitor/ops.py` | `start_backend` takes and propagates `track1_shadow`/`track1_only`; call site passes them; `_env` sets `RAITS_TRACK1_SHADOW` for **both** modes; the Track 1 refusal no longer fires under an explicit `restart --no-scheduler` |
| `monitor/backend/schedule_status.py` | `_slots_for` and `_state_slot_table_size` drop the legacy strategy slots in track1-only mode |
| `global_index/dash/realtime/realtime.js` | fetches `/api/v1/track1-runtime`; `renderTrack1()`; legacy positions labelled `legacy(drain)` |
| `global_index/dash/realtime/index.html` | Track 1 Runtime panel; `Open Positions — legacy / drain` |
| `global_index/dash/realtime-next/index.html` | same panel ids (shared renderer, no second fetch) |
| `global_index/dash/realtime/realtime.css` | one rule scoped to `#track1Facts` for long blocker ids |
| `monitor/test_dashboard_backend.py` | stub widened + 7 new tests |
| `monitor/test_schedule_status_track1_20260823.py` | 5 track1-only health tests |
| `monitor/test_realtime_contract.py` | endpoint contract + 3 frontend tests |
| `monitor/test_realtime_dom.py` | fixture payload for the new endpoint |

**No scheduler logic changed.** `run_scheduler` never reads `RAITS_TRACK1_SHADOW` /
`RAITS_TRACK1_ONLY` — verified by grep across `global_index/`; the only consumer is
`monitor/backend/schedule_status.py`. Widening `_env` cannot arm anything: it still strips
`TRACK1_ORDERS_APPROVED` from every child, asserted by test.

---

## Behaviour, measured

`_env` across all three modes:

```
legacy    SHADOW=None  ONLY=None  ledger=-    orders_env=stripped
shadow    SHADOW='1'   ONLY=None  ledger=set  orders_env=stripped
only      SHADOW='1'   ONLY='1'   ledger=set  orders_env=stripped
```

Health table:

```
legacy      size= 45  slots_for= 45   overdue(legacy)=32  freshness=late
t1-shadow   size=115  slots_for=115   overdue(legacy)=32  freshness=late
t1-only     size= 70  slots_for= 70   overdue(legacy)= 0  freshness=fresh
```

(The 32 in the first two rows are correct — that synthetic log contains no legacy lines, and
in those modes legacy slots *are* expected.)

Command paths, driven through `main()` with every process call stubbed:

```
restart --no-scheduler --track1-only-shadow --yes  ->  rc=0  scheduler NOT restarted  backend(True, True)
restart --no-scheduler --track1-shadow      --yes  ->  rc=0  scheduler NOT restarted  backend(True, False)
up --yes --track1-only-shadow                      ->  rc=2  still refuses (correct: operator never said --no-scheduler)
```

---

## Frontend

`realtime.js` fetches the endpoint alongside the others via `allSettled`, so a backend not
serving it leaves every other panel untouched. `renderTrack1()` shows route, orders_possible,
blocking gate, window coverage (present + day count + latest), slot timing (present + days),
book, checkpoint, safety positions path and client id.

**Absence is stated in three distinct forms**, never silence:

- endpoint unreachable → *"Track 1 runtime endpoint did not answer … This says nothing about
  whether the route is running — it says this dashboard could not ask."*
- reachable, nothing recorded → *"Track 1 runtime not yet observed — no slot has written
  coverage or timing yet. This is the expected state before the first slot fires."*
- book absent → *"absent (expected in shadow — no orders)"*

`realtime-next` reuses the shared renderer through matching DOM ids: no second fetch, no
second renderer, nothing to drift.

The legacy book is labelled on both routes — heading `Open Positions — legacy / drain` and
the source line now reads `legacy(drain) runner qty`. During a track1-only period
`live_positions.json` is the *draining* legacy book and must not be read as Track 1 state;
Track 1 keeps its own at `live_positions.track1.json` and the two are never merged.

---

## Tests

```
monitor/test_dashboard_backend.py
monitor/test_schedule_status_track1_20260823.py
monitor/test_ops.py
monitor/test_realtime_contract.py                        259 passed
monitor/test_realtime_dom.py
monitor/test_paper_dom.py
global_index/test_dashboard_live_snapshot.py
global_index/test_log_hygiene.py                          72 passed
monitor/test_realtime_skin.py                             10 passed
```

`global_index/test_event_playback.py` was not run.

Two failures were found and fixed during the run, both genuine:
- the DOM console-error test caught a **404** — proof the page really does fetch the endpoint
  at runtime; the stub fixture needed the payload.
- the overlap test caught the 38-character blocker id `B1_broker_account_or_legacy_retirement`
  colliding with the neighbouring value at 1440×900; fixed with a rule scoped to `#track1Facts`.

### Mutation-checked

| Mutation | Assertion that should fail | Result |
|---|---|---|
| `start_backend` back to a bare `_env()` | backend carries the Track 1 env | red |
| `RAITS_TRACK1_SHADOW` back inside the `track1_only` branch | transitional shadow sets the flag | red |
| blanket Track 1 refusal restored | backend-only restart path exists | red |
| `--no-scheduler` discriminator dropped | `up` still refuses the flag | red |
| track1-only health subtraction reverted | no phantom legacy overdue | red |
| frontend fetch removed | page fetches the endpoint | red |
| legacy/drain label removed | legacy panel is labelled | red |

All seven red; all three mutated files restored byte-for-byte afterwards.

---

## Operator action required — backend restart, NOT scheduler

The running backend still holds the old environment, so it will keep serving
`state_slot_count=45` until it is replaced. **I did not restart it.**

```
python monitor\ops.py restart --no-scheduler --yes --track1-only-shadow
```

`--no-scheduler` is what makes this safe: it leaves PID 33868 alone and rebuilds only the
backend. That path refused before this change and works now. Expect afterwards:

```
/api/v1/schedule-status : state_slot_count = 70   (Track 1 slots only)
/realtime               : a "Track 1 Runtime" panel; Open Positions labelled legacy / drain
```

Do **not** use `restart --scheduler` or plain `restart` for this — both replace the live
scheduler, which is not needed and is the riskier act.

---

## Side effects: none

| Check | Result |
|---|---|
| scheduler PID | `[{"pid": 33868, "started_epoch": 1787560344.3002172}]` — identical to the value recorded before any edit |
| scheduler restarted | no |
| orders placed | none — the backend is read-only and `TRACK1_ORDERS_APPROVED` is stripped from every child |
| `track1_go_live_confirmation.json` | absent |
| `STOP_TRADING`, `STOP_TRADING.track1` | absent |
| staged files | 0 |
| commits | none (`HEAD` still `601970b`) |
| real `scratch/track1_shadow` | not written |

---

## Verdict

- **Root cause fixed?** Yes — plus two adjacent defects that would have made the first fix
  worse, and one that left no safe way to apply it.
- **Dashboard correct now?** Not yet on the live box: the code is right, the running backend
  is not. One operator command away, and that command does not touch the scheduler.
- **Legacy default unchanged?** Yes — `_env()` with no flags sets neither variable, and the
  45-slot legacy table is asserted by test.

## Next step

1. Operator runs the `restart --no-scheduler` command above, then re-checks
   `/api/v1/schedule-status` for `state_slot_count = 70`.
2. After the first Track 1 slot fires, confirm the panel flips from *"not yet observed"* to a
   coverage day count — that is the first end-to-end proof the whole chain works on real
   evidence rather than on tests.
3. Still open from the earlier collision audit and untouched here: `run_live_day_track1.py`
   remains **untracked in git**, so no audit can diff it against a baseline.
