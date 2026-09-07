# Prompt for Claude Code — execute Track 1 Stage 1 offline infrastructure — 2026-08-22

Bạn đang ở `D:\raits`.

Mục tiêu: thực hiện **Stage 1 offline infrastructure** cho Track 1 resume-primary, theo kế hoạch đã
duyệt. Không live route, không scheduler job, không IBKR, không dashboard, không commit.

## Hard rules

1. **Only create new files.**
2. Do **not** edit these legacy files:
   - `global_index/runner.py`
   - `global_index/signal_layer.py`
   - `global_index/replay_checkpoint.py`
   - `global_index/run_live_day.py`
   - `global_index/run_scheduler.py`
3. Do not modify current legacy checkpoint behavior.
4. Do not start scheduler / runner / monitor / IBKR.
5. If any required change appears to need touching the five legacy files, stop and write the blocker
   instead of patching.

## Read first

- `scratch/track1_resume_primary_stage1_implementation_plan_20260822.md`
- `scratch/track1_resume_primary_stage1_implementation_plan_20260822.json`
- `scratch/track1_checkpoint_resume_audit_20260822.md`
- `scratch/track1_checkpoint_resume_audit_20260822.json`
- `scratch/track1_resume_primary_route_plan_20260822.md`
- `docs/futures/NORMAL_STRESS_CALM_HANDOFF_2026-08-22.md`
- `global_index/replay_checkpoint.py` read-only only

## Implement Stage 1 in new files only

### 1A — checkpoint schema v2 module

Create a new module, suggested path:

- `global_index/route_checkpoint.py`

Requirements:

- Schema version 2.
- Separate path default: `global_index/replay_checkpoint.track1.json`.
- Key space: `routes[route].sleeves[sleeve].instruments[inst]`.
- Import `fingerprint()` from `global_index.replay_checkpoint`; do not copy it.
- Preserve atomic whole-file write.
- Add lock-file guarded read/modify/write.
- Merge only under caller's own route.
- Assert keys outside caller's route are byte-identical before/after merge.
- `usable()` must return either a usable value or a structured refusal reason, not bare `None`.
- Reason codes:
  - `no_entry`
  - `bad_last_day`
  - `fingerprint_rowcount`
  - `fingerprint_content`
  - `params_mismatch`
  - `route_mismatch`
  - `schema_mismatch`

### 1B — params hash builder

Create a new module, suggested path:

- `global_index/route_params.py`

Requirements:

- Pure functions only: config dict -> readable params string + stable `sha256` hash.
- Never use Python `hash()`.
- Canonical sorted rendering.
- Fixed precision for floats.
- Include at least:
  - signal: `ema_period`, `max_hold_days`
  - stop: `stop_basis`, `stop_multiple`, `stop_anchor`, `ratchet`
  - arming: `arm_hour`, `arm_timezone`
  - filters: R4 threshold and derivation window, rel-volume max, SPY short filter + lookback
  - regime: `hmm_fit_end`, regime CSV identity, label lag, Calm gate definition
  - caps: per-sleeve caps and Normal+Calm family cap
  - cost: slippage ticks and commission basis
  - data: data source identity per instrument and fill law

### 1D — window coverage ledger

Create a new module, suggested path:

- `global_index/window_ledger.py`

Requirements:

- Append-only JSONL, separate from checkpoint.
- Off unless an env var names an existing output directory.
- Never raises.
- Never decides trading by itself.
- Records:
  - `window_open`
  - `slot_observed`
  - `window_closed`
- Must distinguish:
  - observed quiet window: `complete + no_signal`
  - observed traded window: `complete + entered`
  - partial observed window: `incomplete`
  - no `window_closed`: `unobserved`
- Calm A expected slots: 1 at 10:00 ET.
- Stress expected slots: 24 from 10:35 to 12:30 ET every 5 minutes.

### 1E — offline tests / harness

Create scratch tests, suggested path:

- `scratch/test_track1_route_checkpoint_stage1_20260822.py`

Tests must be offline and must not start services.

Required test coverage:

1. v2 round-trip save/load.
2. v1 file refused by v2 loader.
3. v2 file refused by legacy `replay_checkpoint.load()`.
4. params mismatch refuses.
5. route mismatch refuses.
6. sleeve mismatch refuses as `no_entry`.
7. fingerprint rowcount mismatch vs content mismatch are categorized separately.
8. missing checkpoint fails closed: no entries proposed, no silent full replay.
9. stale checkpoint fails closed.
10. save preserves other route/sleeve keys byte-identically.
11. two sleeves on the same instrument coexist.
12. concurrent/interleaved writer simulation loses nothing.
13. params hash is stable across processes.
14. every params-hash field has a mutation-style assertion: remove/change that one field and the hash
    moves.
15. window ledger distinguishes `unobserved` from `complete + no_signal`.
16. window ledger disabled writes nothing.
17. window ledger write failure never raises.

If full mutation-checking is too much for one pass, implement the tests in a way that can go red and
document which mutation checks remain to be run manually.

## Optional but useful

Create a small scratch report:

- `scratch/track1_stage1_execute_report_20260822.md`
- optional JSON summary

Report must state:

- files created;
- legacy files untouched;
- tests run and result;
- any blocker;
- what remains for Stage 2.

## Verification

Run only safe local tests:

```powershell
python -m pytest scratch/test_track1_route_checkpoint_stage1_20260822.py -q
python -m pytest scratch/test_slot_telemetry_20260822.py -q
python -m pytest global_index/test_slot_overlap.py global_index/test_log_hygiene.py global_index/test_scheduler_heartbeat.py global_index/test_dashboard_live_snapshot.py global_index/test_scheduler_shadow_verify.py -q
```

Do **not** run `global_index/test_event_playback.py`; it is a known pre-existing hang.

## Deliverables

- `global_index/route_checkpoint.py` new
- `global_index/route_params.py` new
- `global_index/window_ledger.py` new
- `scratch/test_track1_route_checkpoint_stage1_20260822.py` new
- `scratch/track1_stage1_execute_report_20260822.md` optional but recommended
- optional JSON summary
- append-only note to `docs/futures/NORMAL_STRESS_CALM_HANDOFF_2026-08-22.md` only if useful

Again: no production route, no service startup, no edit to the five legacy files, no commit.
