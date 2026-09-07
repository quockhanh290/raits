# Prompt for Claude Code — Track 1 resume-primary Stage 1 implementation plan — 2026-08-22

Bạn đang ở `D:\raits`.

Không start scheduler, không connect IBKR, không start dashboard/monitor, không tạo live route,
không sửa production code trong lượt này. Đây là **implementation plan only** cho Stage 1 của route
Track 1 theo hướng **resume-primary / replay-verified**.

Đọc trước:

- `scratch/track1_checkpoint_resume_audit_20260822.md`
- `scratch/track1_checkpoint_resume_audit_20260822.json`
- `scratch/track1_resume_primary_route_plan_20260822.md`
- `scratch/track1_legacy_telemetry_collection_runbook_20260822.md`
- `scratch/maxhold_misfire_risk_log_20260822.md`
- `docs/futures/NORMAL_STRESS_CALM_HANDOFF_2026-08-22.md`
- `global_index/replay_checkpoint.py`
- `global_index/run_live_day.py`
- `global_index/run_scheduler.py`
- `global_index/runner.py`
- `global_index/signal_layer.py`

Preserve these corrected facts:

- The `64 no usable checkpoint` rows are **not** current coverage debt. They were confined to
  2026-08-06 and 2026-08-07; 2026-08-10 through 2026-08-21 had 85 matches, 0 skips, 100% coverage.
- The real checkpoint blockers are:
  - params-mismatch refusal has never fired in production;
  - params identity is too narrow for Track 1;
  - current checkpoint key is instrument-only;
  - `ckpt.save()` rewrites the whole dict, so sharing one file across routes is a lost-update risk;
  - Stress/Calm A need window-coverage records, not historical checkpoints.
- G3 changed: idle sleep is already disabled; the host still enters S3 via manual/lid/button suspend.
  Do not recommend `STANDBYIDLE 0` as the fix for this host.
- 2026-08-04 `MAX_HOLD exit 09:31 ET` did not run; APScheduler dropped it beyond grace. Startup
  catch-up closes the observed sequence, but a running scheduler sleeping through 09:31 without
  restart is still a residual scheduler hole.

Tasks:

1. Produce a staged implementation plan, not code.
   - Stage 1A: checkpoint schema v2 module/adapter in scratch or new route-only module.
   - Stage 1B: params hash builder and offline refusal tests.
   - Stage 1C: route-specific checkpoint file/path and key space.
   - Stage 1D: window-coverage ledger for Stress/Calm A.
   - Stage 1E: resume-vs-full-replay equivalence harness.
   - Stage 1F: telemetry phases for resume-primary.
   - Stage 1G: scheduler catch-up/availability review.

2. For each stage, specify:
   - exact files likely touched;
   - why the stage is isolated from legacy;
   - tests required;
   - rollback;
   - pass/fail gate.

3. Define checkpoint schema v2 in detail.
   - Proposed JSON shape.
   - Key space: route + sleeve + instrument.
   - Fields: `last_day`, `fingerprint`, readable `params`, `params_hash`, `data_source`, `pos`.
   - Refusal reason codes: `no_entry`, `bad_last_day`, `fingerprint_rowcount`,
     `fingerprint_content`, `params_mismatch`, `route_mismatch`, `schema_mismatch`.
   - How to avoid lost updates given current `save()` rewrites whole dict.

4. Define `params_hash` content for Track 1.
   Include at least: ema, max hold, stop basis, stop multiple, ratchet, arm time/timezone, filter set,
   SPY short filter, regime identity, label lag, caps/family cap, cost/slippage, data source identity.

5. Define window-coverage ledger.
   - Separate from checkpoint.
   - For Calm A 10:00 and Stress 10:35-12:30.
   - Must distinguish `window_unobserved` from `no_signal`.
   - `window_open`, observed slot count, `window_closed`, expected slot count.
   - Missing `window_closed` is a fail-closed signal.
   - Cross-check with scheduler `HEARTBEAT STALLED` and optionally Windows Power-Troubleshooter.

6. Define equivalence harness.
   - Resume-primary vs full replay.
   - 100% coverage over declared window.
   - Any skipped comparison = failed day.
   - Exact comparison of open positions and post-checkpoint trades.
   - One divergence resets promotion counter.

7. Define deliberate offline tests.
   - Params mismatch must refuse.
   - Route mismatch must refuse.
   - Sleeve mismatch must refuse.
   - Fingerprint rowcount/content mismatch categorizes correctly.
   - Missing/stale checkpoint fail-closed.
   - Save does not lose another route/sleeve state.

8. Do not implement. Do not patch production. This is a plan/gate document only.

Deliverables:

- `scratch/track1_resume_primary_stage1_implementation_plan_20260822.md`
- optional `.json` summary
- append-only short note to `docs/futures/NORMAL_STRESS_CALM_HANDOFF_2026-08-22.md` if useful

Do not modify production code. Do not start services. Do not commit.
