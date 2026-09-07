# Runtime / slot / route telemetry — patch plan and applied diff — 2026-08-22

> **Sections 1-5 describe revision 1. Five of its claims were wrong; read *Revision 2* at the end
> before acting on anything here.** The lines that changed are marked inline.

Nothing was started: no scheduler, no runner, no monitor backend, no IBKR connection.
Nothing was committed. No trading decision, guard rule, signal or broker behaviour was changed.

## Why

The shadow-resume timing audit could only recover slot runtime by parsing APScheduler's own INFO
lines, and could not split a run into phases at all — `live_day_*.log` carries no timing marker
anywhere. It also had to tell real runs from no-op runs by thresholding at ~0 seconds, because a
pre-flight skip and a mutex skip emit an identical `Running`/`executed` pair; **76 pairs had to be
filtered that way**. Two gaps, both closed here.

The gate this feeds: Track 1 shadow may only be built once p95 runtime can be measured, target
**p95 < 240 s**, hard limit **p95 < 300 s**. Today's margin is 84 s (p95 216 s against 300 s
spacing) and the boundary is a step function, not a slope.

## 1. Current logging path, as inspected

| Producer | File | What it carries | Gap |
|---|---|---|---|
| APScheduler | `scheduler_*.log` | `Running job` / `executed successfully` / `was missed by` | runtime only inferable, depends on log level and two message strings staying byte-stable |
| Scheduler body | `run_scheduler.py:255` mutex line, `:812`/`:837` pre-flight lines | the skip happened | no machine-readable record; a skipped slot looks like a run |
| `run_live_day` | `live_day_*.log` | narrative INFO lines | **no timing marker at all** — 191 s cannot be split into connect / fetch / signal / decide / order / shadow |
| Runner | `runner.py:2640 _emit_event` → `:2658 _append_event_log` → `runner_events_*.jsonl` | `ts / level / category / message` | **`context` is empty in all 911 records**; no slot id, no route, no runtime |
| Shadow | `run_live_day.py:520/529` | `DOI CHIEU KHOP` / `LECH` | verdict only, no duration, and the 64 "no usable checkpoint" cases carry no reason code |

## 2. Design

A new module, `global_index/slot_telemetry.py`, plus one added line at each phase boundary.

- **Off by default.** Nothing is written unless `RAITS_TELEMETRY_DIR` is set. With it unset every
  function is a no-op, so an unflagged run is byte-identical to before the module existed.
  *(Revision 1 broke this in the scheduler — see R1.)*
- **Never raises.** Every filesystem touch is wrapped; one failure latches the channel off for the
  process and cannot escape into a trading path.
- **Never decides.** Nothing reads it — not the engine, guard, runner or broker.
- **One record per slot.** ~70 lines a day. No per-bar or per-order lines.
- **Identity travels in the environment, not argv.** `RAITS_SLOT_ID`, `RAITS_ROUTE`,
  `RAITS_TELEMETRY_DIR`. The scheduler logs the child's full command one line before spawning it, and
  that line stays byte-identical to every historical run.

Record shape, one JSON object per line in `slot_timing_YYYYMMDD.jsonl`:

```json
{"ts":"…Z","route":"legacy","slot_id":"LIVE_DAY_1410","pid":1234,
 "outcome":"ok","runtime_s":191.4,
 "phases":{"frozen_check":0.1,"data_load":12.3,"hmm_labels":4.1,"setup":0.2,
           "ibkr_connect":12.6,"runner_init":38.9,"run_day":121.8,"shadow_replay":9.7}}
```

`outcome` ∈ `ok | error | dry_run | print_signals | incomplete | skipped_mutex | skipped_preflight`.

## 3. Applied diff

**30 insertions, 2 deletions across two files; one new file.**

### New — `global_index/slot_telemetry.py`

`begin() · split(name) · add(name, secs) · timer(name) · mark(k,v) · set_outcome(name) · emit(outcome)
· record_skip(slot, outcome, **extra) · route() · slot_id() · enabled()`

`begin()` registers an `atexit` net so a record lands on **every** exit path including early returns
and exceptions — otherwise the runs that matter most for diagnosing a slow day, the failed ones,
would be the ones with no record.

`split()` rather than a context manager, deliberately: a context manager means re-indenting existing
blocks, and a telemetry change must not move trading code.

### `global_index/run_scheduler.py` (+14 / −1)

| Line | Change |
|---|---|
| 66-69 | import, after the stdlib block |
| 255 | `_tel.record_skip(slot_id, "skipped_mutex", inflight_s=…)` in `_run_guarded`'s skip branch |
| 507-517 | `_env` built from `os.environ`; sets `RAITS_SLOT_ID` and `RAITS_ROUTE` (default `legacy`), passed as `env=_env` to the existing `subprocess.run`. **Revision 1 also defaulted `RAITS_TELEMETRY_DIR` to `_CWD` here — removed in R1** |
| 812, 837 | `_tel.record_skip(slot_id, "skipped_preflight", reason=…)` on the two early returns |

**`args` is untouched**, so `log.info("[%s] %s", label, " ".join(args))` still logs the identical
command. No job id, trigger, time or argv changed — verified by grepping the diff for
`add_job|scheduled_job|cron|hour=|minute=|"--|args`: zero hits.

### `global_index/run_live_day.py` (+16 / −1)

| Line | Change |
|---|---|
| 75-77 | import |
| after `parse_args()` | `_tel.begin()` |
| after each existing log line | `_tel.split("frozen_check" / "data_load" / "hmm_labels" / "setup" / "ibkr_connect" / "runner_init" / "run_day")` |
| shadow call | wrapped in `with _tel.timer("shadow_replay"):` — the only re-indented line in the patch |
| dry-run / print-signals / lock / exception / success | `_tel.set_outcome(…)` — *revision 1 was missing `lock_held` and `error` and let `ok` overwrite `dry_run`; see R3-R5* |

`runner_init` deliberately brackets `FuturesRunner(...)` because that constructor is where B1–B5 run
and where B4 can place stops — the phase most likely to be blamed and least visible today.

### Not patched, deliberately

`runner.py` was left alone. The task listed adding `route` to `_emit_event`'s `context`, and that is a
four-line change — but `runner.py` is the most load-bearing file in the tree and the same information
now arrives on a channel that cannot break a monitor reader. Adding it there is a Stage-0 item for the
route work, not a prerequisite for measuring runtime.

## 4. Compatibility

| Requirement | Status |
|---|---|
| Event schema backward compatible | **Untouched.** `runner_events_*.jsonl` is not modified at all; telemetry uses its own file |
| New fields inside `context`, not top-level | N/A — no field added to the event schema |
| Monitor readers unaffected | **Yes.** No reader knows about `slot_timing_*.jsonl`; `runner_event_reader` and `runner_positions_reader` see no change |
| `--route` defaults to `legacy` | **Yes**, via `RAITS_ROUTE`, and no CLI flag was added |
| No job id / trigger / argv change | **Verified** by diff grep |
| No trading behaviour change | Every added line is a timer, a dict write or a file append; none is inside a branch that decides anything |

## 5. Verification performed

Safe checks only. Nothing connected, nothing started.

| Check | Result |
|---|---|
| AST parse of all three files | OK |
| Pre-patch baseline: `test_slot_overlap`, `test_log_hygiene`, `test_scheduler_heartbeat`, `test_dashboard_live_snapshot`, `test_scheduler_shadow_verify` | **44 passed** |
| Post-patch, same five files | **44 passed** — identical |
| New `scratch/test_slot_telemetry_20260822.py` | **8 passed** *(now 23 — see R6)* |
| Telemetry files leaked into the repo | none — tests write only into `tmp_path` |

The new tests assert both halves of the claim, and are written so they can go red:

- **disabled means disabled** — with the env unset, `begin/split/mark/timer/emit/record_skip` are all
  called and then the assertion is `list(tmp_path.rglob("*")) == []`, i.e. *nothing anywhere*, not
  merely no `slot_timing` file;
- a mutation test enables the directory and asserts a file **does** appear, so the disabled test is
  provably not vacuous;
- a skip record is distinguishable from a real run (the exact gap the audit papered over);
- an unwritable directory and an `open()` that raises are both swallowed, and the channel latches off.

### Pre-existing condition found, not caused by this patch

`global_index/test_event_playback.py` **hangs**: it emits 8 dots and then stops, killed at 60 s, both
before and after the patch. It was excluded from the baseline for that reason. Worth its own look —
a hanging test file also means any full-suite run silently stalls.

## 6. What this does not yet give you

- **No route field in `runner_events_*.jsonl`.** Deliberate, see above.
- **No sub-phase inside `run_day`.** `run_day` is one number (typically the largest). Splitting it into
  fetch / signal / decide / order needs markers inside `runner.py` and `signal_layer.py`. If the Track 1
  measurement shows `run_day` growing, that is the next place to instrument.
- **No checkpoint reason codes.** The 64 "no usable checkpoint" shadow cases still do not say why.
- **Nothing reads the new file yet.** A reader belongs with the monitor work, not here.

## 7. Rollback

> **Corrected in revision 2.** This paragraph originally said the scheduler sets
> `RAITS_TELEMETRY_DIR` "with `setdefault`". It no longer does — that default was the R1 defect and
> was removed. Rollback is simpler than the original text implied, not harder.

Delete `global_index/slot_telemetry.py` and revert the two files — 39 insertions, 2 deletions. Or,
without touching code at all: **leave `RAITS_TELEMETRY_DIR` unset**. Nothing in the scheduler or the
runner invents a value for it, so unset is genuinely off for the parent and every child, and every
telemetry call becomes a no-op.

If the variable is already exported in an operator's shell and you want it off for one run without
editing the environment, point it at a path that does not exist: `_dir()` requires an existing
directory and returns `None` otherwise.

## Artifacts

- `global_index/slot_telemetry.py` (new)
- `global_index/run_scheduler.py`, `global_index/run_live_day.py` (patched, uncommitted)
- `scratch/test_slot_telemetry_20260822.py`
- this plan


---

## Revision 2 — after review, 2026-08-22

A reviewer read the patch against its own documentation and found five defects. All five were real.
They are fixed below, and each now has a test that goes red on the original defect.

### R1 — "off by default" was false

`run_scheduler._run` did `_env.setdefault("RAITS_TELEMETRY_DIR", str(_CWD))`, which switched child
telemetry **on for every spawn** while `slot_telemetry.py` still claimed to be off unless the
variable is set. Worse than the contradiction: the parent writes its own skip records from **its**
environment, which the child default never touched — so a normal day would have produced child
records and no skip records, and the two would have disagreed about whether the day was instrumented
at all.

**Fixed** — the invented default is gone. `RAITS_TELEMETRY_DIR` is inherited from `os.environ` or
absent. Parent and child are now on or off together, by construction.

`RAITS_SLOT_ID` and `RAITS_ROUTE` are still always passed: they are **identity only and enable
nothing**. `RAITS_ROUTE` still defaults to `legacy`.

### R2 — parent/child consistency, now documented

Both the parent's `record_skip` and the child's `emit` write only when the **scheduler process** has
`RAITS_TELEMETRY_DIR`. Turning it on is one export before the scheduler starts; there is no partial
state. Asserted by `test_parent_skip_records_follow_the_parent_env`.

### R3, R4 — `lock_held` and `error` were documented and never emitted

Both appeared in the module docstring and at **no call site**. The lock branch returned without
setting anything and the exception path re-raised without setting anything, so both would have been
written by the atexit net as `incomplete` — the two outcomes most worth telling apart in a slow-day
post-mortem, landing in the same bucket.

**Fixed** — `set_outcome("lock_held", sticky=True)` before the lock return,
`set_outcome("error", force=True)` before the re-raise.

### R5 — `dry_run` was relabelled `ok`

A dry run still executes `run_day`, so the success path overwrote the mode and the record claimed a
normal trading run. Same for `print_signals`.

**Fixed** with three-case outcome semantics in `slot_telemetry.set_outcome`, because last-writer-wins
gets two of the three wrong:

| call | meaning |
|---|---|
| `set_outcome("ok")` | ordinary success; loses to a sticky mode already set |
| `set_outcome(mode, sticky=True)` | a MODE a later success must not erase — `dry_run`, `print_signals`, `lock_held` |
| `set_outcome("error", force=True)` | overrides anything including sticky: a run that raised did not end the way any earlier line claimed |

`mark("mode", "dry_run")` is also set, so the mode is visible regardless of how outcome evolves.

### R6 — tests added, and mutation-checked

`scratch/test_slot_telemetry_20260822.py`: **8 to 23 tests, all passing.** New coverage:

- scheduler does **not** inject `RAITS_TELEMETRY_DIR` when its own env has none;
- scheduler **does** forward it when the parent has one;
- identity vars are always passed and enable nothing;
- **argv is byte-identical** through `_run` — asserted against the real function with a captured
  `subprocess.run`, not a re-implementation of it;
- parent `record_skip` follows the parent env;
- sticky mode survives a later success; `error` overrides sticky; a plain outcome still overwrites a
  plain one; the atexit net writes what stands and does not double-write;
- **every outcome named in the docstring has a production call site** — the exact defect R3/R4 were.

**Mutation-checked, not assumed.** The two guards that matter were tested by re-introducing the
original defects on disk and confirming the right tests fail:

| mutation | result |
|---|---|
| re-add `_env.setdefault("RAITS_TELEMETRY_DIR", str(_CWD))` | `test_scheduler_does_not_invent_a_telemetry_dir` **FAILED** |
| delete the `lock_held` call site | `test_every_documented_outcome_has_a_call_site[lock_held]` and `test_module_docstring_outcomes_all_reachable` **FAILED** |
| both restored | **23 passed** |

### Re-verification after revision

| Check | Result |
|---|---|
| AST parse, all three files | OK |
| `scratch/test_slot_telemetry_20260822.py` | **23 passed** |
| `test_slot_overlap`, `test_log_hygiene`, `test_scheduler_heartbeat`, `test_dashboard_live_snapshot`, `test_scheduler_shadow_verify` | **44 passed** — same as the pre-patch baseline |
| `test_event_playback` | **excluded — hangs, pre-existing**, before and after the patch |

Unchanged from revision 1: no job id, trigger or argv changed; the event schema and every monitor
reader are untouched; `runner.py` is not touched.

### How to switch it on

```
set RAITS_TELEMETRY_DIR=D:\raits      # before starting the scheduler; nothing else needed
```

Off is the default and requires no action. To pin it off with the variable present, point it at a
path that does not exist — `_dir()` rejects it and the channel stays silent.
