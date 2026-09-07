# Prompt for Claude Code — Track 1 checkpoint/resume route audit — 2026-08-22

Bạn đang ở `D:\raits`.

Không start scheduler, không connect IBKR, không start dashboard/monitor, không tạo Track 1 route,
không sửa production code. Đây là **read-only design audit** cho hướng route mới:
**resume/checkpoint-primary, full replay as oracle**.

Đọc trước:

- `scratch/track1_resume_primary_route_plan_20260822.md`
- `scratch/track1_legacy_telemetry_collection_runbook_20260822.md`
- `scratch/maxhold_misfire_risk_log_20260822.md`
- `scratch/shadow_resume_timing_audit_20260822_report.md`
- `scratch/runtime_telemetry_patch_plan_20260822.md`
- `docs/futures/NORMAL_STRESS_CALM_HANDOFF_2026-08-22.md`
- `global_index/replay_checkpoint.py`
- relevant call sites in `global_index/run_live_day.py`, `global_index/run_scheduler.py`,
  `global_index/runner.py`, `global_index/signal_layer.py`

Context you must preserve:

- Track 1 should **not** copy the legacy shape of rebuilding the whole historical desired basket every
  slot. Legacy full replay stays as oracle/audit.
- Existing evidence: shadow-resume has `91` matches, `0` divergences, but `64` skipped comparisons
  with no usable checkpoint. This is promising but not enough to flip primary.
- G3 changed: idle sleep is already disabled. The host still enters S3 via manual/lid/button suspend.
  Pass condition is zero `HEARTBEAT STALLED` over the collection/shadow window, or use an always-on
  host/VPS. Do not recommend the old `STANDBYIDLE 0` line as if it fixes this machine.
- 2026-08-04 `MAX_HOLD exit 09:31 ET` did **not** run; APScheduler dropped it because the miss was
  2,475 s versus 300 s grace. Startup catch-up added later closes the observed sequence, but not the
  residual case where a running scheduler sleeps through 09:31 and is not restarted.

Tasks:

1. Inventory existing checkpoint/resume infrastructure.
   - What exactly is stored in `replay_checkpoint.json` / `replay_checkpoint.py`?
   - What identity keys exist today: instrument, cluster, route, regime, params?
   - What is missing for a separate Track 1 route?

2. Explain the `64 no usable checkpoint` cases.
   - Parse logs/read code to classify reason categories.
   - If logs do not contain enough information, state exactly what reason codes should be added.
   - Do not call coverage "good" until skipped comparisons are explainable.

3. Define route-specific checkpoint design for Track 1.
   - Separate state path / keys from legacy.
   - No shared mutable checkpoint state between legacy and Track 1.
   - Include strategy params/hash in checkpoint identity so parameter changes cannot silently reuse
     stale state.

4. Define equivalence checks.
   - Resume-primary vs full replay must match open positions and post-checkpoint trades.
   - Specify fields compared: inst, direction, qty, cluster/sleeve, entry day/time/price, stop,
     target, exit reason, P&L where applicable.
   - Define how mismatches block promotion.

5. Define fail-closed behavior.
   - Missing checkpoint.
   - Stale checkpoint.
   - Param/hash mismatch.
   - Divergence against oracle.
   - Broker/state mismatch.
   - Host slept through a Track 1 detection window.

6. Estimate which Track 1 sleeves can be incremental without full replay.
   - Normal-R4 filtered.
   - Stress-MNQ `mnq_only_g3_q7`.
   - Current NKD/MNKD.
   - Calm A PCLoc with ATR15 disaster stop.
   For each: list required state, bars needed, and whether D-1/precomputed context is sufficient.

7. Runtime/telemetry implications.
   - What should telemetry measure for resume-primary?
   - Which phases are enough now?
   - When would deeper markers inside `runner.py` / `signal_layer.py` become necessary?

8. Operational availability.
   - Confirm checkpoint logic cannot repair missed observations when the host sleeps through a
     time-sensitive Stress window.
   - Propose where to record "host unavailable / window missed" so it fails closed instead of looking
     like "no signal".

Deliverables:

- `scratch/track1_checkpoint_resume_audit_20260822.md`
- optional `.json` summary
- append-only note to `docs/futures/NORMAL_STRESS_CALM_HANDOFF_2026-08-22.md` only if it clarifies
  the gate

Do not modify production code. Do not start services. Do not commit.
