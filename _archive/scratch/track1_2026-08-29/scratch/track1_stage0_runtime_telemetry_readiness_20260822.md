# Track 1 — Stage 0 readiness: runtime + telemetry gate — 2026-08-22

Audit and preparation only. Nothing was started: no scheduler, no runner, no monitor backend, no
IBKR connection. No Track 1 route code was written. Nothing committed.

---

## 1. Where the gate stands today

### Runtime — the number Track 1 has to live inside

Current regime, from 2026-08-11 (`scratch/shadow_resume_timing_audit_20260822.json`):

| | value |
|---|---:|
| live-day slot runs measured | **207** |
| median | 191 s |
| p90 | 206 s |
| **p95** | **216 s** |
| max | 311 s |
| runs over the 300 s slot spacing | **1 of 207** |
| mutex skips logged since 2026-08-11 | **0** |

Slot spacing is 300 s and the behaviour at that line is a **step, not a slope**: a fixed 216 s runtime
skips nothing, a fixed 311 s skips every second slot. **Margin is 84 s.**

### Slot contention — not the blocker

Simulated on the measured sample, sweeping **all 207 possible phasings**, replaying the real rule
(a slot that fires while a run is in flight is *skipped*, not queued):

| scenario | slots | worst-case skips |
|---|---:|---:|
| Track 1 window alone (10:00 + 10:35–12:30) | 25 | **1 (4.0%)** |
| current 14:05–15:55 **+** Track 1 windows | 48 | **1 (2.1%)** |

The simulator was anchored before being trusted: fed the pre-08-11 sample it predicts 11 skipped
slots, and the logs recorded exactly 11 mutex skips on each of the four contended days.

### Hard gate after Track 1 shadow

| | threshold |
|---|---|
| **Hard** | **p95 < 300 s** |
| **Target** | **p95 < 240 s** |

Measured on legacy first, then re-measured with Track 1's two sleeves wired in shadow. The gate is a
number, not an argument: Track 1 adds Calm A and the Stress detector to the same `run_live_day`
process and nobody has measured what they cost per run. ~85 s of added work puts the schedule back in
the pre-08-11 regime, where the same simulator says 48% of slots are lost.

---

## 2. Two items that are NOT runtime, and must not be filed as such

### 2.1 Machine sleep — operational blocker before a second live continuous window

| | value |
|---|---:|
| `HEARTBEAT STALLED` events | **28** |
| days with at least one | **13 of 18** |
| total stalled scheduler time | **17.2 h** |
| worst single stall | **3.6 h** |

Sharper than the headline: of the **9 trading days in the current regime, 8 had a machine-sleep
stall.** Only 2026-08-13 was clean. This is not a historical artefact of the old regime — it is
happening now, on essentially every day, and the most recent stall in the sample is dated 2026-08-22.

Every stall in this sample fell outside 14:05–15:55, which is why no day-window slot misfired and why
the Track 1 *timing* conclusion is unaffected. **Nothing makes that structural.** A suspend inside a
trading window skips slots for a reason no runtime budget can absorb, and Track 1 proposes adding a
*second* window — 10:35–12:30 — to a machine that suspends on essentially every day.

> **Corrected 2026-08-22 (later the same day).** The remedy below was measured read-only and is
> **already applied on this machine**: `STANDBYIDLE` is 0 on both AC and DC. Running it changes
> nothing. The machine is not sleeping from idle — 28 of 28 stalls match a real OS suspend woken by
> the power button. See `scratch/track1_legacy_telemetry_collection_runbook_20260822.md` Part 1.

`run_scheduler.py` prints this remedy in its own warning, and it is stale advice for this host:

```
powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0
```

**Requirement: sleep must be disabled and verified before a second continuous window goes live.**
Verification is measurable — zero `HEARTBEAT STALLED` lines over the collection window — so it should
be a gate condition, not a note.

### 2.2 The 2026-08-04 max-hold misfire is a trading-job incident

> **Corrected.** "Fired 41 minutes late" describes the warning line, not the event. The grace is
> 300 s (`run_scheduler.py:363`), the delay was 2,475 s, so APScheduler **dropped the run**: there is
> no `Running job` and no `executed successfully` line for it that day. **The 09:31 close did not run
> at all.** Full reconstruction: `scratch/maxhold_misfire_risk_log_20260822.md`.

`MAX_HOLD exit 09:31 ET`, 2026-08-04, was reported missed by **2,476 s** and, being 8x past the
misfire grace, **never executed**. No machine-sleep stall covers the delay itself — the scheduler had
woken by then. A catch-up for exactly this was added three days later (commit `91dbc0e`,
2026-08-07); it did not exist on the day.

This is a **trading** job: the 09:31 close is what exits a position at the RTH open it is designed to
exit at. A close that never happens is not a different fill — it is a position left open.

The first version of the timing report called all 52 misfires "all on NKD night slots… the machine
being unavailable overnight". That sentence is wrong twice: 9 of 52 are not NKD night, and it filed a
missed trading job under overnight maintenance. **It belongs in a trading-risk log of its own, not in
a scheduler-maintenance line.** For context, 2026-08-04 is also the day the pre-flight failed and all
23 day-window slots were skipped — that day was broken end to end, in more than one place.

Misfire breakdown, corrected: 52 total, **43** on NKD night slots, **9** elsewhere, **33** covered by
a machine-sleep stall. Eight of the nine non-NKD are maintenance jobs, each explained by a stall. The
ninth is the one above.

---

## 3. Telemetry is in place and verifiably inert

### Verification run for this readiness check

| Command | Result |
|---|---|
| `pytest scratch/test_slot_telemetry_20260822.py -q` | **23 passed** |
| `pytest` on the 5 baseline files (`test_slot_overlap`, `test_log_hygiene`, `test_scheduler_heartbeat`, `test_dashboard_live_snapshot`, `test_scheduler_shadow_verify`) | **44 passed** |
| `global_index/test_event_playback.py` | **not run — known pre-existing hang**, unrelated to this work |

Inertness confirmed by observation, not by reading the code: `RAITS_TELEMETRY_DIR` is unset in this
environment, and there is **no `slot_timing_*.jsonl` anywhere in the repo**.

### Doc correction made in this pass

`scratch/runtime_telemetry_patch_plan_20260822.md` §7 Rollback still said the scheduler sets
`RAITS_TELEMETRY_DIR` "with `setdefault`". It no longer does — that default was the R1 defect and was
removed in revision 2. The paragraph now carries a correction marker and states the true rollback:
leaving the variable unset is genuinely off for parent **and** every child, because nothing invents a
value for it.

---

## 4. Next-step plan for the Track 1 route shadow

Preparation only. None of this is implementation.

### 4.1 How to enable telemetry safely

One export, before the scheduler starts:

```
set RAITS_TELEMETRY_DIR=D:\raits
python -m global_index.run_scheduler --port 4002
```

Why that is the whole switch, and why it is safe:

- **Parent and child are on or off together.** The scheduler does not invent a default; it forwards
  the variable to children only when it has one. There is no half-instrumented state.
- **`RAITS_SLOT_ID` and `RAITS_ROUTE` are identity only** and enable nothing on their own.
  `RAITS_ROUTE` defaults to `legacy`.
- **argv is untouched.** The child's command is logged one line before the spawn and remains
  byte-identical to every historical run.
- **A failure cannot escape.** Every write is wrapped; one failure latches the channel off for that
  process.
- **To turn it off**: unset the variable. To pin it off while the variable is exported, point it at a
  path that does not exist.

Do **not** set `RAITS_ROUTE` to anything but `legacy` during collection. Legacy runtime is the
baseline the Track 1 measurement will be compared against; tagging it otherwise makes the comparison
meaningless.

### 4.2 What telemetry writes

| | |
|---|---|
| File | `slot_timing_YYYYMMDD.jsonl` in `RAITS_TELEMETRY_DIR` |
| Volume | one line per slot, roughly **70 lines a day** — no per-bar or per-order lines |
| Fields | `ts, route, slot_id, pid, outcome, runtime_s, phases{}` plus any `mark()` scalars |
| Phases | `frozen_check, data_load, hmm_labels, setup, ibkr_connect, runner_init, run_day, shadow_replay` |
| Outcomes | `ok, error, dry_run, print_signals, lock_held, incomplete, skipped_mutex, skipped_preflight` |
| Written by | the child for real runs; the **scheduler parent** for `skipped_mutex` / `skipped_preflight` |

**One convention difference to know before joining files:** this channel stamps its filename in
**UTC**, while `runner_events_*.jsonl` stamps in **ET** (`runner.py:2671`). Every slot that goes
through `run_live_day` is unaffected — the NKD night window at 01:10–02:55 ET is 05:10–06:55 UTC on
the same date — but the 23:55 ET session-report job lands in the next UTC day file. Join on the `ts`
field, not on the filename.

### 4.3 How much to collect

| | |
|---|---|
| Minimum | **10 trading days** of instrumented legacy |
| Why 10 | the current-regime sample is only 10 days, and it has never contained a high-volatility session with many simultaneous entries. `ibkr_broker.py:730-737` models a worst-case blocking peak of **265 s** on an all-cluster stress day — that alone exceeds the 84 s of margin |
| Also collect | at least one day with a `skipped_mutex` or `skipped_preflight` record, to confirm the parent-side path writes in production and not only in tests |

### 4.4 Pass / fail gates before any live route

Ordered. Each is a measurement, and each can fail.

| # | Gate | Pass condition |
|---|---|---|
| G1 | Legacy baseline collected | ≥10 trading days of `slot_timing_*.jsonl`, p95 computed from the runner's own `runtime_s`, **not** inferred from APScheduler lines |
| G2 | Legacy p95 confirms the current regime | p95 within the measured band (~216 s). A materially higher number means the 2026-08-11 improvement has reverted and the margin is already gone |
| G3 | **Machine sleep eliminated** | **zero** `HEARTBEAT STALLED` lines across the whole collection window |
| G4 | Track 1 shadow runtime | **p95 < 300 s hard, < 240 s target**, measured with Calm A and the Stress detector wired in shadow |
| G5 | `run_day` attribution | if `run_day` grows enough to threaten G4, phase markers inside `runner.py` / `signal_layer.py` are required before proceeding — a single opaque number cannot be optimised |
| G6 | Slot outcome accounting closes | `ok + dry_run + lock_held + error + skipped_* + incomplete` equals the scheduled slot count for each day; any `incomplete` is investigated, not averaged away |
| G7 | Legacy unchanged | the artifact sha256 reproduction still matches, the scheduler job table and per-slot argv diff empty, and the five baseline test files stay at 44 passed |

If G4 lands between 240 s and 300 s, the choice between runtime optimisation and 10-minute spacing in
the Stress window is an explicit decision, not a default. Coarser spacing halves the entry-timing
resolution of a detector that fires on a low break at an unknown minute — a cost to measure, not
assume.

### 4.5 Power / sleep mitigation — corrected after G1/G3 preparation

> **Correction, 2026-08-22:** the scheduler's suggested idle-sleep command is already in effect on
> this host. `STANDBYIDLE` is 0 on both AC and DC, so running
> `powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0` would change nothing and create
> a false "fixed" signal. The measured suspend mechanism is deliberate or lid/button-triggered S3
> sleep, not idle timeout.

G3 above is therefore **not** "run powercfg". It is: prevent manual/lid/button sleep during the
collection window, or collect on an always-on host (see `docs/futures/VPS_DEPLOY_PLAN.md`), then
prove it with zero stall lines over the window. Rationale in §2.1: 8 of the 9 current-regime trading
days had a stall, and Track 1 adds a second continuous window.

### 4.6 What remains unchanged — confirmed this pass

| | Status |
|---|---|
| Production route | **no Track 1 route exists or was created** |
| Scheduler job ids, triggers, times | **unchanged** |
| Child argv | **unchanged**, asserted against the real `_run` with a captured `subprocess.run` |
| Event schema (`runner_events_*.jsonl`) | **untouched** — telemetry uses its own file |
| Monitor readers | **untouched** — none knows about `slot_timing_*.jsonl` |
| `runner.py` | **not modified** |
| Trading decisions, signals, guard, broker behaviour | **not modified** |

---

## 5. Readiness verdict

**Stage 0 is ready to run, with one prerequisite that is not about runtime.**

- Instrumentation is in place, tested (23 + 44 passed), mutation-checked, and provably inert until one
  environment variable is set.
- Slot contention is **not** a blocker: worst case 1 skipped slot in 48 across every tested phasing.
- The runtime gate is defined and measurable: p95 < 300 s hard, < 240 s target.
- **The blocker is machine sleep**, on 8 of the 9 most recent trading days. It should be fixed and
  proven before the collection window, so the baseline is measured on a machine that stays awake —
  otherwise G1 and G3 have to be re-run anyway.
- Separately, the 2026-08-04 max-hold misfire needs a home in a trading-risk log. It is not a
  scheduler-maintenance line and the first version of the timing report wrongly filed it as one.

## Artifacts

- `scratch/shadow_resume_timing_audit_20260822.{py,json,_report.md}` — the measurements and addendum
- `scratch/runtime_telemetry_patch_plan_20260822.md` — patch, revision 2, rollback corrected here
- `global_index/slot_telemetry.py`, `run_scheduler.py`, `run_live_day.py` — uncommitted
- `scratch/test_slot_telemetry_20260822.py` — 23 tests
- `scratch/track1_stage0_runtime_telemetry_readiness_20260822.json` — the numbers above, machine-readable
