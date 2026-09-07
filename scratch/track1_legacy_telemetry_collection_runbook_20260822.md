# Legacy telemetry collection runbook + sleep checklist — 2026-08-22

Preparation only. Nothing was started: no scheduler, no runner, no monitor backend, no IBKR
connection. No power setting was changed. No Track 1 route or job was created. Nothing committed.

---

## Part 1 — Windows sleep: the remedy I recommended is already applied

### Correction, before the checklist

My Stage 0 readiness report said: *"Apply the `powercfg` setting the scheduler recommends, then prove
it."* The scheduler's own warning names:

```
powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0
```

**Measured, read-only, on this machine — it is already in effect:**

| setting | AC | DC |
|---|---|---|
| `SUB_SLEEP / STANDBYIDLE` (Sleep after) | **0** | **0** |
| `SUB_SLEEP / HIBERNATEIDLE` | 0 | 0 |
| `SUB_SLEEP / HYBRIDSLEEP` | 0 (off) | 0 (off) |

Active scheme: `52521609-…` *Legion Performance Mode*.

**Running that command would change nothing**, and following the scheduler's advice would have
produced a false "fixed" signal. The idle-sleep timer is not what is suspending this machine.

### What is actually suspending it — measured

| | |
|---|---|
| Sleep states available | **S3 Standby**, Hibernate, Fast Startup. **S0 Low Power Idle not supported**, so this is not modern standby |
| OS suspend events in the 40-day window | **120** |
| Overlapping the scheduler audit window | **39 events, 22.0 h of suspend** |
| Wake sources in that window | **Power Button 24**, USB host controller 13, Unknown 2 — **zero wake-timer wakes** |
| Scheduler `HEARTBEAT STALLED` events matched to a real OS suspend | **28 of 28** |

The 28-of-28 match is exact and one-to-one: e.g. the scheduler's `STALLED 2160s` at 2026-08-19
01:16 local pairs with an OS suspend of 2,155 s ending at the same instant, 99% agreement. **The
scheduler's stall line is a faithful proxy for OS suspend** — that is now verified against the OS's
own event log rather than assumed.

Note the scheduler *under*-reports: 39 suspends / 22.0 h in the window against 28 stalls / 17.2 h,
because a suspend while the scheduler is not running leaves no stall line. True exposure is larger
than the scheduler log shows.

With the idle timer disabled and the wake source almost always the power button, the mechanism is
**deliberate or lid-triggered suspend by a person**, not an idle timeout. The Start-menu power button
action is set to **Sleep** on both AC and DC.

### Checklist — operator actions, none run here

> **Nothing below has been executed.** These need your approval, and two of them are not `powercfg`
> commands at all.

| # | Action | Command / step | Why |
|---|---|---|---|
| 1 | **Confirm the idle timer is already off** | `powercfg /query SCHEME_CURRENT SUB_SLEEP` | Already verified: `STANDBYIDLE` = 0 on AC and DC. **Do not** run the `setdcvalueindex` command expecting a change |
| 2 | Set lid-close to do nothing, both AC and DC | `powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0`<br>`powercfg /setdcvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0`<br>`powercfg /setactive SCHEME_CURRENT` | `LIDACTION` did not appear in this machine's `SUB_BUTTONS` output, so it may be hidden by the OEM. Query it first; if absent, the lid setting lives in Lenovo Vantage |
| 3 | Set the Start-menu power button away from Sleep | `powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS UIBUTTON_ACTION 3`<br>(3 = Do nothing) + `setactive` | Currently **Sleep** on AC and DC; that is the most likely path a person takes |
| 4 | **Stop manually sleeping the machine during the collection window** | operating practice, not a setting | 24 of 39 wakes are the power button. No setting prevents a person choosing Sleep |
| 5 | Verify | after ≥1 full day: `powercfg /query SCHEME_CURRENT SUB_SLEEP` unchanged, **and** zero new `HEARTBEAT STALLED` lines in `scheduler_*.log` | The measurable gate — see G3 |
| 6 | Consider the alternative that removes the whole class | `docs/futures/VPS_DEPLOY_PLAN.md` (written 2026-08-18) | That plan's argument is exactly this: certify on machine A, run money on machine B is the wrong order. The 22 h of suspend measured here is direct evidence for it |

**Recommendation.** Items 2–4 are worth doing, but they are behavioural mitigations on a laptop that
someone carries. Item 6 removes the failure class instead of managing it, and a plan for it already
exists. If the Track 1 collection window is going to be trusted as the baseline for a live route, the
VPS is the better host to collect it on.

---

## Part 2 — Legacy telemetry collection runbook

### Enable

```
set RAITS_TELEMETRY_DIR=D:\raits
python -m global_index.run_scheduler --port 4002
```

That is the whole switch.

| | |
|---|---|
| `RAITS_TELEMETRY_DIR` | **the only thing that enables writes.** Unset = off, for the scheduler parent and every child alike — the scheduler invents no default |
| `RAITS_ROUTE` | leave at its default **`legacy`**. Do not set it to anything else during collection: this run *is* the baseline, and tagging it otherwise makes the later comparison meaningless |
| `RAITS_SLOT_ID` | set automatically per slot by the scheduler; identity only, enables nothing |
| argv | unchanged — telemetry identity travels in the environment, so the command logged before each spawn stays byte-identical |
| Turning it off | unset the variable; or, if it is already exported, point it at a path that does not exist (`_dir()` requires an existing directory) |

### Output

| | |
|---|---|
| File | `slot_timing_YYYYMMDD.jsonl` in `RAITS_TELEMETRY_DIR` |
| Volume | one line per slot, ~70 lines/day. No per-bar, no per-order lines |
| Fields | `ts, route, slot_id, pid, outcome, runtime_s, phases{}` + any `mark()` scalars |
| Phases | `frozen_check, data_load, hmm_labels, setup, ibkr_connect, runner_init, run_day, shadow_replay` |
| Outcomes | `ok, error, dry_run, print_signals, lock_held, incomplete, skipped_mutex, skipped_preflight` |
| Written by | the child for real runs; the **scheduler parent** for `skipped_mutex` / `skipped_preflight` |

**Do not join to `runner_events_*.jsonl` by filename.** This channel stamps the filename in **UTC**;
`runner_events_*.jsonl` stamps in **ET** (`runner.py:2671`). Every slot that goes through
`run_live_day` is unaffected — the NKD night window at 01:10–02:55 ET is 05:10–06:55 UTC the same
date — but the 23:55 ET session-report job lands in the next UTC day file. **Join on `ts`.**

### How long

**Minimum 10 trading days.** The current-regime sample is only 10 days and has never contained a
high-volatility session with many simultaneous entries; `ibkr_broker.py:730-737` models a worst-case
blocking peak of **265 s** on an all-cluster stress day, which alone exceeds the 84 s of margin.

Also collect at least one `skipped_mutex` or `skipped_preflight` record, to confirm the parent-side
write path works in production and not only under pytest.

### Gates

| # | Gate | Pass condition | How to check |
|---|---|---|---|
| **G1** | Legacy baseline collected | ≥10 trading days of `slot_timing_*.jsonl`; p95 computed from the runner's own `runtime_s`, **not** inferred from APScheduler lines | count distinct dates; `outcome == "ok"` rows only |
| **G2** | p95 confirms the current regime | p95 in the region of **216 s**. Materially higher means the 2026-08-11 improvement has reverted and the margin is gone before Track 1 spends any of it | compare against `scratch/shadow_resume_timing_audit_20260822.json` → `regimes.from_2026_08_11` |
| **G3** | **Machine sleep eliminated** | **zero** `HEARTBEAT STALLED` lines across the whole window | `grep -c STALLED scheduler_*.log` over the window. Cross-check against the OS: zero Power-Troubleshooter suspend events |
| **G4** | Track 1 shadow runtime | **p95 < 300 s hard, < 240 s target**, with Calm A and the Stress detector wired in shadow | same computation, after |
| **G5** | `run_day` attribution | if `run_day` grows enough to threaten G4, phase markers inside `runner.py` / `signal_layer.py` first — one opaque number cannot be optimised | inspect the `phases` block |
| **G6** | Outcome accounting closes per day | `ok + dry_run + print_signals + lock_held + error + skipped_mutex + skipped_preflight + incomplete` == scheduled slots for that date. Any `incomplete` is investigated, never averaged away | group the JSONL by date |
| **G7** | Legacy unchanged | artifact sha256 reproduction still matches; scheduler job-table and per-slot argv diffs empty; the five baseline test files stay at 44 passed | re-run `normal_promotion_regen_audit`; `run_scheduler --dry-run` diff |

G3 is the one that decides whether the window is worth collecting at all. Collecting a baseline on a
machine that suspends means G1 and G3 both have to be redone later.

### If G4 lands between 240 s and 300 s

An explicit decision, not a default: optimise runtime, or widen the Stress window to 10-minute
spacing. Coarser spacing halves the entry-timing resolution of a detector that fires on a low break
at an unknown minute — a cost to measure, not to assume.

---

## Verification run this pass

| Check | Result |
|---|---|
| `pytest scratch/test_slot_telemetry_20260822.py -q` | **23 passed** |
| `pytest` on the 5 baseline files | **44 passed** |
| `global_index/test_event_playback.py` | **not run — known pre-existing hang** |
| `RAITS_TELEMETRY_DIR` in this environment | unset |
| `slot_timing_*.jsonl` anywhere in the repo | none — telemetry still inert |
| Production route / Track 1 jobs / `runner.py` / `signal_layer.py` | untouched |
| Power settings | read-only queries only; **nothing changed** |
