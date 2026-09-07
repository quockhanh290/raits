# Track 1 Stage 1 — offline infrastructure, executed — 2026-08-22

Offline only. No scheduler, runner, monitor backend or IBKR connection was started. No live or paper
order. No scheduler job. Nothing committed.

**Result: Stage 1A, 1B, 1D and 1E complete. 144 tests green. One defect found in my own test suite by
mutation-checking, and fixed.**

---

## 1. Files created — all new, none edited

| File | Stage | Purpose |
|---|---|---|
| `global_index/route_params.py` | 1B | strategy identity: config → readable string + `sha256` hash |
| `global_index/route_checkpoint.py` | 1A / 1C | schema v2, keyed `route / sleeve / instrument`, scoped merge, refusals with codes |
| `global_index/window_ledger.py` | 1D | append-only window-coverage ledger, off by default |
| `scratch/test_track1_route_checkpoint_stage1_20260822.py` | 1E | 77 offline tests |

## 2. Legacy files — untouched, verified

| File | Status |
|---|---|
| `global_index/runner.py` | **clean** — no diff |
| `global_index/signal_layer.py` | **clean** |
| `global_index/replay_checkpoint.py` | **clean** — imported read-only |
| `global_index/run_live_day.py` | shows `M`, but **only** the telemetry patch from an earlier pass |
| `global_index/run_scheduler.py` | same |

Verified rather than asserted: the diff on those last two was filtered for any line not belonging to
the telemetry patch, and the only survivors are that patch's own re-indent of the `_shadow(...)` call
and the `subprocess.run` reflow. **Nothing in this pass touched any of the five.**

`fingerprint()` is **imported** from `replay_checkpoint`, never copied — its docstring records a
tz-stripping subtlety paid for in production, and a copy would drift exactly where the original says
drift is fatal.

## 3. Tests

| Suite | Result |
|---|---|
| `scratch/test_track1_route_checkpoint_stage1_20260822.py` | **77 passed** |
| `scratch/test_slot_telemetry_20260822.py` | **23 passed** |
| the five baseline files | **44 passed** — unchanged from the pre-Stage-1 baseline |
| `global_index/test_event_playback.py` | **not run** — known pre-existing hang |

Coverage against the required list: v2 round-trip · v1 refused by v2 · v2 refused by legacy · params
mismatch · route mismatch · sleeve mismatch as `no_entry` · rowcount vs content categorised separately
· missing checkpoint fails closed · stale checkpoint · save preserves other routes byte-identically ·
two sleeves on one instrument · interleaved writers · hash stable across processes (real subprocess)
· per-field hash mutation · ledger `unobserved` vs `complete + no_signal` · ledger disabled writes
nothing · ledger write failure never raises. Plus: flat position is usable not a miss; missing field
refused not defaulted; float precision cannot split equal configs; empty payload lists the
same-session sleeves.

## 4. Mutation checks — run, not deferred

Each guard was broken on disk, the suite re-run, and the file restored.

| Mutation | Expected | Result |
|---|---|---|
| M1 remove the write-scope assertion in `save_route` | scoping tests fail | **2 failed** ✓ |
| M2 collapse `FINGERPRINT_ROWCOUNT` into `FINGERPRINT_CONTENT` | categorisation test fails | **1 failed** ✓ |
| M3 delete `ratchet` from the params identity | its field test fails | **all 50 green** ✗ → see below |
| M4 make a missing `window_closed` read as complete | `unobserved` test fails | **1 failed** ✓ |
| all restored | | **77 passed** ✓ |

### The defect M3 found, in my own tests

`test_every_params_field_moves_the_hash` was parametrised over `rp.ALL_FIELDS`, which is *derived from*
`route_params.FIELDS`. Deleting `ratchet` from the module therefore deleted its test case too: the
suite **shrank from 50 tests to 49 and stayed green**. The fixture was reading its expectations from
the thing under test, so every assertion agreed with itself — the same shape as a test that reads its
constants from the production table it is supposed to pin.

Fixed by adding `EXPECTED_PARAM_FIELDS`, a literal list in the test file, independent of the module,
plus a test that compares the two sets and a second parametrisation driven by the literal. Re-running
M3 with the fix in place now gives **3 failed** — the set comparison, the `ratchet` case, and the
missing-field refusal. The suite grew 50 → 77 as a result.

This is worth recording because the first run passed 50/50 on the first attempt, which is exactly when
a suite deserves the least trust.

## 5. Design decisions worth naming

**Refusals are values, not `None`.** `usable()` returns `Resumed(last_day, pos)` or
`Refusal(code, detail)`. `Refusal.__bool__` is `False`, so `if usable(...)` cannot accidentally pass —
and the seven codes mean a caller can log a sentence rather than "unusable". Legacy returns a bare
`None` for four distinct conditions, which is why this session had to reconstruct the historical
skip categories by string-diffing hashes out of log lines.

**`fingerprint_rowcount` and `fingerprint_content` are separate on evidence, not taste.** In the
recorded skips those two had different causes: 48 were a stale/half-held day, 4 were bars rewritten
underneath. One code for both loses the distinction that identifies the bug.

**`pos = None` is a usable answer, not a miss.** A checkpoint recording that nothing was open is as
valid as one recording a position; treating it as a miss would replay in full on every flat day. That
is legacy's behaviour and it is deliberate, so it is preserved and tested.

**Write scoping is asserted, not intended.** `save_route` serialises the whole file under a lock,
merges only under the caller's own route, then compares a canonical rendering of every *other* route
before and after and raises `ScopeViolation` if it moved. M1 confirms that assertion is what holds the
property.

**Staleness is a separate axis from the fingerprint.** A stale entry can have a perfectly matching
fingerprint — the history just stopped growing — so `stale()` is its own function with a
caller-declared limit.

**The ledger's fail-closed rule is the absence of a record.** `status()` returns `unobserved` when no
`window_closed` exists, whatever else is present. A ledger that required a positive "I was down"
record would be silent in the one case it is built for: a suspended host writes nothing at all.

**`roska4_stress` and `roska4_calm` are created empty on purpose.** They are same-session sleeves
needing no historical checkpoint. Present-but-empty says "accounted for"; absent would say "nobody
thought about it".

## 6. Blockers

**None.** No required change needed any of the five legacy files.

One item deferred by design rather than blocked: **Stage 1C's live wiring**. `run_live_day` already
has `--checkpoint-path` (`:179`), so pointing a route at
`global_index/replay_checkpoint.track1.json` needs no edit — but doing so is Stage 2, because it means
a route that runs. Stage 1 uses the path only from tests.

## 7. What remains for Stage 2

| | |
|---|---|
| **1E full harness** | the *equivalence* harness against real parquet is not built. Stage 1 delivered the unit-level tests; the harness must first reproduce the existing shadow record — **91 matched / 0 diverged, 2026-08-10 → 08-21** — before it is used to judge anything new |
| **1F telemetry phases** | names declared (`ckpt_load`, `ckpt_verify`, `bars_fetch_incremental`, `sleeve_update`, `ckpt_advance_write`, `oracle_replay`); implementation belongs with the route code that has the phases to time. `oracle_replay` must be excluded from the route p95 |
| **1G scheduler** | review only, no edit. `_catch_up_maxhold` is startup-only, so a running scheduler that sleeps through 09:31 and is never restarted still gets neither path. `_maxhold_done` / `_preflight_ok` are date-keyed and persisted and need a route dimension before a second route shares the process |
| **Bootstrap** | nothing writes a Track 1 checkpoint from real bars yet. That is the first Stage 2 step, offline, mirroring `replay_checkpoint --bootstrap` |
| **R0 host availability** | unchanged and still governing: 8 of the 9 most recent trading days had an S3 suspend, and the idle timer is already off, so `STANDBYIDLE 0` is not the remedy for this host |
| **Runtime** | Stage 1 is offline and produces no p95. The margin at stake is 84 s |

## 8. Verification commands, as run

```
python -m pytest scratch/test_track1_route_checkpoint_stage1_20260822.py -q     ->  77 passed
python -m pytest scratch/test_slot_telemetry_20260822.py -q                     ->  23 passed
python -m pytest global_index/test_slot_overlap.py global_index/test_log_hygiene.py \
                global_index/test_scheduler_heartbeat.py \
                global_index/test_dashboard_live_snapshot.py \
                global_index/test_scheduler_shadow_verify.py -q                 ->  44 passed
```

`global_index/test_event_playback.py` deliberately not run — pre-existing hang, unrelated to this work.
