# Track 1 route plan update — checkpoint/resume-first, full replay as oracle — 2026-08-22

This is a planning update only. No scheduler, runner, monitor, IBKR connection, or Track 1 route was
started or modified.

## Why the plan changes

The legacy route is expensive because each slot asks for today's desired basket by rebuilding the
historical path. That makes the output easy to audit, but it is exactly why a slot can take minutes.

Track 1 should not copy that shape by default. The intended shape is:

- **Research / audit oracle:** full replay remains the source of truth for validation.
- **Production route candidate:** checkpoint/resume becomes the primary computation path.
- **Safety net:** full replay runs in shadow or periodic audit to detect divergence, not every slot.

This matches the reason `--shadow-resume` exists: it is already proving whether a resumed state can
match the full replay before it is trusted to trade.

## Current evidence

From `scratch/shadow_resume_timing_audit_20260822_report.md`:

| Shadow-resume outcome | Count |
|---|---:|
| comparison matched (`DOI CHIEU KHOP`) | 91 |
| comparison diverged | 0 |
| no usable checkpoint, comparison skipped | 64 |
| checkpoint failed to advance | 0 |

Interpretation, corrected after the checkpoint/resume audit:

- The resume path has not disagreed with full replay in recorded evidence.
- The blended `91 / 64` figure is misleading as a current coverage number. All 64 skips were confined
  to two bootstrap days, 2026-08-06 and 2026-08-07; the next ten trading days were 85 matched,
  0 skipped, 100% covered.
- It is **not ready to become primary** for different reasons: the params-mismatch refusal path has
  never fired in production, the current params identity is too narrow for Track 1, checkpoint state
  is keyed only by instrument, and the checkpoint file is rewritten as a whole dict.
- The next route design should widen identity and exercise refusal/fail-closed paths rather than add
  another full replay workload.

## Updated route principle

Track 1 route should be designed as **resume-primary / replay-verified**:

1. Build or load route-specific checkpoint state.
2. Fetch only new bars needed since the checkpoint.
3. Update rolling indicators / sleeve state incrementally.
4. Compute desired Track 1 positions from the resumed state.
5. Reconcile with broker + route state before any order decision.
6. Compare against full replay in shadow until gates pass.
7. If checkpoint is missing, stale, or divergent, fail closed or run a controlled full-replay repair;
   do not silently trade from a guessed state.

## What should not happen

- Do not implement Track 1 by replaying the full historical basket every 5 minutes unless this is an
  explicit fallback path with telemetry and a hard runtime gate.
- Do not treat current `91/0` shadow evidence as enough to flip primary.
- Do not put Track 1 into the existing legacy route and then rename it later. Build a separate route
  shape, keep legacy untouched, and only promote after equivalence gates pass.

## New gates before resume-primary can trade

| Gate | Requirement |
|---|---|
| R0 host availability | Collection and shadow windows run on a host that does not enter S3 sleep. On this laptop, idle sleep is already disabled; the measured failure class is manual/lid/button suspend, so the pass condition is zero scheduler `HEARTBEAT STALLED` lines or use of an always-on host |
| R1 checkpoint coverage | 100% comparison coverage sustained over the declared window. A skipped comparison is a failed day, not neutral. The historical 64 skips are treated as a fixed bootstrap incident, not current coverage debt |
| R2 no divergence | `resume == full replay` for positions and post-checkpoint trades over the collection window |
| R3 restart recovery | Kill/restart simulation resumes from checkpoint without changing desired positions or double-settling trades |
| R4 stale/missing checkpoint behavior | Missing/stale/divergent checkpoint fails closed or triggers an explicitly measured repair path |
| R5 identity/refusal coverage | Track 1 checkpoint identity includes route/sleeve/instrument plus a params hash covering stop basis, ratchet, arm time, filters, regime identity, caps, and costs; params-mismatch refusal is deliberately exercised offline before promotion |
| R6 broker/state reconcile | Route state, live position state, and broker positions reconcile before entries |
| R7 runtime | Resume-primary p95 stays below the same runtime gate: hard `<300s`, target `<240s` |
| R8 periodic oracle | Full replay still runs as scheduled audit and any mismatch blocks promotion |

## Scheduler incident clarification

The 2026-08-04 `MAX_HOLD exit 09:31 ET` incident is not evidence that the scheduler executed late.
It did not execute: the miss was 2,475 s against a 300 s grace window, so APScheduler dropped it. The
observed sequence is now closed by startup catch-up (`_catch_up_maxhold`, commit `91dbc0e`), but a
residual hole remains if an already-running scheduler sleeps through 09:31 and is not restarted.

That matters for Track 1 because the Stress window is more timing-sensitive than swing max-hold: a
suspend inside 10:35-12:30 can miss detector opportunities, and there may be no equivalent next-slot
repair. Resume-primary design must therefore include host-availability gates; it cannot rely on
checkpoint logic to repair a window the host never observed.

## Relationship to current telemetry collection

Telemetry is still useful, but the question changes:

- Legacy telemetry establishes the cost of the current full-replay route.
- Track 1 shadow telemetry should measure the cost of the resume-primary candidate, not merely ask
  whether another full replay can fit.
- If the `run_day` phase grows, add deeper markers in `runner.py` / `signal_layer.py`; if
  resume-primary stays small, avoid instrumenting hot trading code prematurely.

## Next prompt impact

The checkpoint/resume audit has now been run:
`scratch/track1_checkpoint_resume_audit_20260822.md`.

Follow-up should move from audit to a scoped implementation plan, still without building live route:

- route-specific checkpoint file and schema v2;
- widened params hash;
- deliberate offline test of params-mismatch refusal;
- window-coverage ledger for Calm A / Stress;
- startup plus heartbeat-style catch-up review for scheduler jobs whose cron run can be dropped after
  S3 suspend.
