# Stage 5ZL — "I could not check" stops meaning "I checked and it was fine"

**2026-08-26, ET 01:30–02:15.** No orders · no confirmation file · `TRACK1_ORDERS_APPROVED`
unset · no `--allow-orders` · **nothing restarted** · no strategy, rule, cap or
backtest-identity change · no historical regime label rewritten.

```text
UTC 2026-08-26 05:51 · ET 2026-08-26 01:51 EDT · Calgary 2026-08-25 23:51 MDT
```

*Two read-first paths do not exist under the names given: the 5ZK report is dated `20260826`,
and there is no `track1_stage5q5_freshness_boundary_20260824.md` — the nearest are
`track1_stage5q5_freshness_boundary_report_20260824.md` and `..._fix_20260824.md`, which is
what was read.*

---

## ⚠ Read this first — a test of mine overwrote a production file, and I could not repair it

**What happened.** My first version of the scheduler-job test helper fired the pre-flight job
body with the *subprocess runner* replaced but not the *state path*. The job then did exactly
what it is built to do: it wrote its own state. `global_index/preflight_state.json` went from

```json
{"2026-08-17": true, "2026-08-18": true, "2026-08-19": true, "2026-08-20": true,
 "2026-08-21": true, "2026-08-24": true, "2026-08-25": true}
```

to

```json
{"2026-08-26": true}
```

at **2026-08-25 23:42:02 Calgary**. Caught by this suite's own *"no production file was
written"* test — the only reason it was noticed.

**Why it matters.** The second file is not merely shorter. It asserts that today's pre-flight
passed, and today's pre-flight has not run — it fires at 13:45 ET. That is a fabricated
clearance for a day nothing has checked.

**How bad, precisely.** The running scheduler (pid 18096) loaded the real seven days at
startup and holds them in memory; it reads the file only at startup, so it is unaffected, and
its own save at 13:45 ET today will rewrite the file correctly from memory. **The file
self-heals in about twelve hours.** The exposure is a scheduler restart before then, which
would load the fabricated clearance and let today's slots run without a pre-flight.

**What I did.** Fixed the helper so it cannot recur — every state path is redirected into
`tmp_path` first, with the incident recorded in the test's own docstring, because replacing
the process runner does not make a job body safe when the persistence happens in the parent.

**What I could not do.** I attempted to restore the file and the action was **blocked**, which
is correct: it is production runtime state and the standing constraint forbids editing it. I
did not work around the block.

**The restoration, if you want it.** Reconstructed from the scheduler logs, not guessed. The
file's mtime was 11:47:28 on 08-25, the instant of that day's `[PRE-FLIGHT] OK`;
`_save_preflight_state` keeps the last `_PREFLIGHT_KEEP = 7` sorted days; every pre-flight that
ran was OK — no `FAILED` line exists in any of those days' logs — and the last seven OK days
ending 2026-08-25 are exactly the seven the scheduler reported restoring at 22:03:38.

```powershell
python -c "import json,os; from pathlib import Path; p=Path('global_index/preflight_state.json'); d={k:True for k in ['2026-08-17','2026-08-18','2026-08-19','2026-08-20','2026-08-21','2026-08-24','2026-08-25']}; t=p.with_suffix('.tmp'); open(t,'w',encoding='utf-8').write(json.dumps(d,indent=2)); os.replace(t,p); print(p.read_text(encoding='utf-8'))"
```

`2026-08-26` is deliberately absent: today's pre-flight has not run. Doing nothing is also
defensible — the file heals itself at 13:45 ET — provided the scheduler is not restarted first.

---

## The eleven answers

| | |
|---|---|
| 1. statuses | **PASS · DRIFT · UNKNOWN**, with ten codes, each belonging to exactly one status |
| 2. old collapses | **five**, not four — all now UNKNOWN (§2) |
| 3. does DRIFT block readiness? | **yes** |
| 4. does UNKNOWN block readiness? | **yes** — including "no record at all" |
| 5. reaches job status / exit code? | **yes, for the 16:20 post-close refresh.** Deliberately not for the 13:45 pre-flight (§4) |
| 6. post-close failure visible on its own? | **yes**, and it no longer writes the pre-flight record — asserted |
| 7. freshness semantics changed? | **no** — the module was not touched and does not import the verifier, both asserted |
| 8. runtime/live file changed? | **yes, one, by a test of mine** — see the box above. Nothing else |
| 9. orders still impossible? | **yes** |
| 10. next shadow window READY? | **yes** — tonight's NKD window ran through this stage untouched |
| 11. what remains, is 5ZM next? | four items; **yes, 5ZM** |

---

## 1. Baseline

```text
scheduler pid 18096   backend pid 30604   track1-only-shadow   orders_possible False
blocking  B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE
```

`spy_daily_live.csv` 14:20:01 · `preflight_state.json` 11:47:28 · checkpoint and book 13:56:19
· no regime label cache anywhere: labels are computed on read and never persisted, which 5ZF
established and this stage did not change.

The NKD window (01:10–02:55 ET) was open throughout. Nothing was restarted and no slot was
interfered with.

## 2. The five collapses

`verify_regime_labels` returned a **count**, and returned **0** from five places that had
verified nothing:

| path | old | now |
|---|---|---|
| `futures._validated_core` cannot be imported | `0` | `UNKNOWN / engine_unavailable` |
| either CSV fails to load | `0` | `UNKNOWN / inputs_unreadable` |
| `label_regimes` raises | `0` | `UNKNOWN / labelling_failed` |
| **no overlapping dates** | `0`, logged *"HMM stable"* | `UNKNOWN / no_overlapping_dates` |
| no snapshot to compare against | — | `UNKNOWN / no_snapshot` |

Zero is also what a clean run returns.

The fourth is the one worth naming: with nothing to compare, the old code took the INFO branch
and printed **"Regime labels unchanged (0 dates verified) — HMM stable"**. A statement about
nothing, phrased as reassurance. Its replacement says *"zero labels were compared — 'no
differences found' here means 'nothing was looked at'."*

The fifth was found while writing this and did not exist as a branch at all: a missing snapshot
fell through to whatever the loader did with it.

And the result went nowhere. The one call site discarded it; `__main__` called `main()` bare so
the return value never reached the exit code; the scheduler keeps only CRITICAL and ERROR from
a child that exited 0, and the drift line was a WARNING. **Invisible from end to end.**

## 3. The contract

`global_index/regime_verify.py`, route-neutral because the check is shared infra — legacy's
pre-flight runs the same verification.

`VerifyResult(status, code, detail, checked_at, inputs, counts)`, where the constructor refuses
a code that belongs to another status: *a code that can mean two things is a code nobody can act
on*. `inputs` carries paths only, never contents. `counts` carries what was compared, what
changed, and up to ten dates — and is `{"compared": 0}` on the no-overlap path, which is the
finding rather than an omission.

The record lands in `global_index/regime_verify/regime_verify_YYYYMMDD.jsonl`, append-only and
dated like every other evidence file here, because **a verification whose answer exists only in
a log line is a verification nobody can gate on**. `latest()` returns UNKNOWN for no record, an
unreadable record, a foreign status, or a record older than seven days — absence is never a
pass.

The module decides nothing. Whether a DRIFT stops a job, skips a day or holds the paper gate is
each caller's decision, stated out loud, because the 13:45 pre-flight gates a whole trading day
and the 16:20 refresh gates nothing.

## 4. Where it blocks, and where it deliberately does not

| surface | DRIFT | UNKNOWN |
|---|---|---|
| **paper readiness** | blocks | blocks |
| **16:20 post-close refresh** | exit 1, job failed | exit 1, job failed |
| **13:45 pre-flight** | recorded, exit unchanged | recorded, exit unchanged |
| shadow slot execution | no effect | no effect |
| freshness gate | untouched | untouched |

The pre-flight exclusion is the one judgement call in the stage and it is written into the
`--verify-strict` help text, the scheduler comment and the blocker's own evidence. A
verification that could not run must not skip every slot of a trading day — the brief is
explicit that UNKNOWN must not block shadow execution — and the 16:20 job runs after everything
today has finished, so a non-zero exit there costs a visible failure and no trading.

The two are told apart in the scheduler's failure branch too: it reads the recorded status and
says *label drift*, *could not be verified*, or *the series is still short* — three different
operator actions.

`REGIME_LABEL_VERIFICATION` is a new measured blocker, released only by a PASS, with no
confirmation flag able to wave it through and failing closed on any exception. Measured now:

```text
blocking: B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE,
          REGIME_LABEL_VERIFICATION
  UNKNOWN (no_record): no verification has been recorded — a check that never ran is not
  a check that passed
```

That is the honest answer today. Nothing has ever verified these labels in a way anyone can
read, and the gate now says so instead of being silent.

The dashboard gains a `regime_verify` block giving status, code, detail, counts and a plain
reading per status — never collapsed into "ok" and "stale", because a DRIFT is a finding about
the data and an UNKNOWN is the absence of one, and an operator acts differently on each.

## 5. A live finding, in this stage's own subject

While checking the freshness path I read the 16:20 job's own log line from 2026-08-25:

```text
14:20:13 [SPY_REFRESH_PM] OK — the daily series now covers 2026-08-25, which is what
                             tomorrow's sessions need.
```

**The series ends on 2026-08-24.** Measured: `spy_daily_live.csv`, last row `2026-08-24`, mtime
14:20:01 — written by that very run.

The job printed the sentence on any exit-0, having checked nothing. Polygon's SPY daily
aggregate is not always final at 16:20 ET, so the run genuinely succeeded and genuinely added
nothing — and the success line asserted a fact nobody had verified. The same defect this stage
exists to remove, one job over.

Fixed: the branch now reads the series' last date and either confirms the coverage or says the
close was not available yet, with the consequence stated — tomorrow's sessions ask for the last
trading day *before* them, so it is only a problem if it is still true tomorrow. An unreadable
file returns `""`, meaning *could not tell*, never *up to date*.

No harm came of it. Tonight's nine NKD slots all decided, none refused on freshness, because
the requirement at 01:10 ET on the 26th is the 24th and the series has it.

## 6. Tests

**48 tests**, `scratch/test_track1_stage5zl_regime_tristate_20260826.py`. All ten items the
brief lists, plus the branches the code suggested.

The engine is stubbed for the PASS and DRIFT cases so the outcome is *chosen* rather than hoped
for — a test that passes because today's data happens to be clean would go green for the wrong
reason and stay green through a real drift. The CLI cases run the real `main()` in a
**subprocess**, because an exit code cannot be asserted in-process. Structural assertions use
AST, not substrings: that the call site no longer discards the result, that `__main__` is
`sys.exit(main())`, that the post-close job does not touch the pre-flight record, that the
pre-flight does not run strict, and that the freshness module does not import the verifier.

## 7. Regression

**523 passed, 0 failed** across 5ZL, 5ZF, 5S, 5Q5, 5ZK, 5ZG, 5ZH, 5O, the dashboard backend and
the realtime contract.

Two 5ZF tripwires fired and were inverted, exactly as 5ZG inverted its predecessor:
`test_26_label_verification_is_currently_only_a_warning` carried *"if this now raises, the
finding is closed and the report needs updating"* — it did, a day later — and `test_27` said a
drift is not visible as a job failure, which is no longer true for the post-close job.

Two 5S gate tests were updated because this stage added a measured gate: a control that
satisfies only the gates that existed the day it was written stops being a control.

One 5ZK test was narrowed. Its runtime-tree scan asked whether *anything* under the runtime
root was written during the run — true only when nothing else is running, and the live NKD
window was open and writing. mtime cannot distinguish a concurrent live write from a test
write, so it now asks only about the paths that suite touches.

Three `test_track1_stage5z_freshness_root_20260823` failures are **not caused by this stage**
and I am not claiming to have diagnosed them: `track1_freshness.py` was not touched (mtime
2026-08-24 10:24) and a passing test asserts it does not import the verifier. The tests pin a
fixed instant against the live SPY series, which has moved since they were written. Cause not
established; recorded rather than waved at.

## 8. Files changed

| file | change |
|---|---|
| `global_index/regime_verify.py` | **new** — the tri-state, the codes, the record, `latest()` |
| `global_index/update_spy_csv.py` | `verify_regime_labels` returns a result; `UpdateOutcome`; both early returns carry UNKNOWN; `--verify-strict`, `--verify-root`; `sys.exit(main())` |
| `global_index/run_scheduler.py` | 16:20 runs strict with three distinct failure messages; 13:45 documented as deliberately not strict; the success line verifies its claim |
| `global_index/track1_gates.py` | `regime_labels_verified` measurement; `REGIME_LABEL_VERIFICATION` blocker |
| `monitor/backend/track1_runtime_reader.py` | a `regime_verify` block, three readings |
| `scratch/test_track1_stage5zl_…py` | new, 48 tests |
| `scratch/test_track1_stage5zf_…py` | two tripwires inverted |
| `scratch/test_track1_stage5s_…py` | two gate tests updated for the new measured gate |
| `scratch/test_track1_stage5zk_…py` | runtime scan narrowed |

**Runtime files changed: one**, `global_index/preflight_state.json`, by a test of mine — see the
box at the top. `spy_daily_live.csv`, the checkpoint, the book and every audit record still
carry their baseline mtimes. `global_index/regime_verify/` does not exist yet; the 16:20 job
creates it on its next run.

## 9. Liveness

Nothing restarted. The changed modules are imported by subprocesses — the scheduler spawns
`python -m global_index.update_spy_csv` for both SPY jobs — so the verification and the strict
exit are live at the next spawn, and the 13:45 pre-flight today will be the first to record a
status.

Two exceptions to state plainly. The scheduler's own job bodies live in **pid 18096**, so the
`--verify-strict` flag and the corrected success line do not apply until it restarts; today's
16:20 job will run the new verification and record its status, but with the old argv and the
old success line. And the **backend still serves the old reader** — `/api/v1/track1-runtime`
will not carry the `regime_verify` block until it restarts.

Neither restart was performed: the NKD window was open, and neither change is urgent enough to
interrupt it.

## 10. What remains before paper

| | item | class |
|---|---|---|
| 1 | machine sleep | **operator** |
| 2 | B1 — separate account or a proven-flat legacy book | **operator decision** |
| 3 | route-aware P&L, open-position parity, legacy-reader split | **5ZM** |
| 4 | planned stop not journalled; `close_position` and `place_protective_stop` unbuilt; no cross-day book | **5ZN** |

Plus the new gate itself, which is a machine gate rather than work: it opens the first time the
16:20 job records a PASS.

**Removed:** *"regime verification is warn-only and its return is discarded"*.

**Next is 5ZM**, route-aware reporting and P&L — with 5ZI's dependency correction still
standing: have it read the dry run's journal output rather than waiting for real orders.
