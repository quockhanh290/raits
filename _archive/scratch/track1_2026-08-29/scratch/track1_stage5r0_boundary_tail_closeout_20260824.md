# Stage 5R-0 — B-5R-H: never persist a minute still in progress

**2026-08-24, ~22:15–23:10 ET ·** *(corrected in Stage 5R-1: this header originally read "2026-08-25, 00:40–02:10 ET", which was wrong by a date. The file's own mtime is 23:10 ET on 2026-08-24. Nothing else in the report depended on it, but a dated runtime record on a three-clock system has to carry the right date.)* · no scheduler or backend started or stopped (pids 28696 /
11720 unchanged since 09:25 ET) · **no IBKR connection** · no parquet, CSV, sidecar or runtime
evidence written · no order · no confirmation file · `TRACK1_ORDERS_APPROVED` unset · B1 still
blocking · overlap guard untouched · strategy rules, Track 1 identity, sizing basis, cap logic
and order gate all untouched · no commit.

*(One item on the read list, `scratch/track1_stage5q7_mnkd_identity_boundary_20260824.md`, does
not exist under that name. The Stage 5Q-7 report is
`scratch/track1_stage5q7_apply_boundary_restart_mnkd_identity_20260824.md`, and that is what
was read.)*

---

## Verdict: **READY_FOR_TRACK1_SHADOW_RESTART_WITH_IDENTITY_MATCHED**

### The direct answers

| question | answer |
|---|---|
| **Is B-5R-H closed?** | **Yes, going forward** — the updater no longer stores an open final minute. The three partial bars *already* in the files from 2026-08-24 are not fixed by this; they still need `--repair-boundary` |
| **Did the 5Q-9 identity remain unchanged?** | **Yes.** All four sleeve hashes pinned by test and unchanged |
| **Did any real data file change?** | **No.** Byte-identical, asserted at the end of the suite |
| **Was the scheduler or backend touched?** | **No.** Same pids all evening |
| **Are orders still impossible, B1 still blocking?** | **Yes.** `orders_possible=False`, `track1_blocking=['B1_broker_account_or_legacy_retirement']` |
| **Next operator command?** | The two restarts still outstanding from 5Q-7 — see the last section |

---

## The defect, and why repairing it was never going to be enough

`--repair-boundary` (Stage 5Q-5) repairs the partial bar the **previous** run left behind. It
cannot help the one the **current** run is about to create: the fetch asks for "now", IBKR
answers with the minute in progress, and the append stores that snapshot as a finished bar.

Stage 5Q-7 measured both halves of that on one evening. The approved repair fixed the 13:45
bars in MNQ, MYM and M2K — and the very same run left new partial bars at 20:20 and 20:21. The
re-probe came back `repairable_dry_run` instead of `nothing_to_repair`.

**Repairing moves the defect one minute later. Only refusing to store it removes it.**

---

## The fix

```python
drop_open_final_bar(fetched, *, observed_utc) -> (bars, dropped_ts_or_None, reason)
```

A bar stamped `T` covers `[T, T+1min)`, so it is complete exactly when the observation instant
has reached `T + 60s`. **No threshold to tune, and no prices inspected** — a partial bar is not
detectably wrong from its own values, which is what let this survive every price check the
route has.

Only the **final** bar is ever a candidate. An interior bar cannot be in progress, and a
function that could drop one would be a filter rather than a tail guard.

### The clock is stamped BEFORE the request, and that is the whole design

```python
requested_at = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
bars = ib.reqHistoricalData(...)
```

The snapshot IBKR answers with is at or after the moment we asked. Stamping *afterwards*
instead would let a minute that closed **during the round trip** look complete — while the row
we hold for it is still the partial one the snapshot contained. That is B-5R-H arriving through
the front door.

Using the earlier instant means every bar kept had already closed before we asked, so the value
we hold for it is final. The cost is at most one just-closed minute deferred to the next run,
which appends it as an ordinary new bar. A test parses the AST and requires the stamp to
precede the request.

`_fetch_contfuture` now returns `(bars, contract, requested_at)`; the one other caller,
`fix_offset_step.py`, was updated in the same edit and ignores the instant by name — it
measures an offset over ten days and never appends.

### What the operator sees

```text
  MES: final-bar check — kept: final bar had closed before the fetch
  MNQ: final-bar check — dropped: 2026-08-25 00:20:00 is still open at 2026-08-25 00:20:31
                                  (complete at 2026-08-25 00:21:00)
...
IN-PROGRESS FINAL MINUTES NOT STORED (Stage 5R-0, intentional):
  MNQ   2026-08-25 00:20:00  — still open at fetch; it arrives on the next run
```

A silently shorter file is how a missing bar becomes a mystery. The skip is reported as a
decision.

---

## Tests

`scratch/test_track1_stage5r0_boundary_tail_20260824.py` — **21 passed**.

Tests 1, 2, 4 and 5 drive the pure function. Tests 3, 8 and the convention checks drive the
**real `main()`** end to end against a stubbed `ib_insync` and parquets under `tmp_path` — the
whole append path, including the clock stamp, the splice, the join-jump guard, the history
invariant and the convention assertion. A test that stubbed the append would be testing the
stub, and the append is where the defect lives.

| # | required | test |
|---|---|---|
| 1 | fetch ending inside the final minute drops it | `test_1_…` — plus `test_2b` pinning that `T+60s` is complete and `T+59s` is not |
| 2 | fetch ending after the final minute keeps it | `test_2_…`, and again through the real append |
| 3 | `--repair-boundary` repairs the previous bar **and** appends only closed newer ones | `test_3_…` — stored history ends on a partial 17:45, the run repairs it and stops at 17:49 with 17:50 absent |
| 4 | no closed bar is accidentally dropped | `test_4_…` — at four observation offsets, and exactly one bar goes in the drop case |
| 5 | tz-naive parquet stays tz-naive | `test_5_…` on the function, `test_5c_…` on the written file, `test_5b` on an aware observation |
| 6 | a missing required frozen column still refuses; extra provider columns unchanged | `test_6_…`, `test_6b_…` (`average`/`barcount` still projected away) |
| 7 | NKD/MNKD identity correct | `test_7_…` bars **NKD**, orders **MNK**, pv 0.50; `test_7b_…` pins all four 5Q-9 hashes |
| 8 | a repair run no longer leaves a fresh partial tail | `test_8_…` — every shared bar must match the feed to 1e-9 |
| 9 | no real file changes | `test_9_…` fingerprints at import and compares; plus no confirmation file, no order env, and the updater contains no order path at all |

### Mutations — 8 red, 0 still green

| | mutation | test that went red |
|---|---|---|
| M1 / M1b | the tail drop removed entirely | the pure rule, **and** the real append |
| M2 / M2b | the final bar dropped even when closed | the append keeps it, **and** the rule's own contract |
| M3 | the boundary repair skipped | the previous partial bar survives |
| M4 | the parquet index rewritten tz-aware | the convention check (the Stage 5Q-6 near miss) |
| M5 | the overlap guard neutered | a behavioural refusal test, added for this |
| M6 | the clock stamped *after* the request | the AST order check |

M5 needed a new **behavioural** test: the existing guard check parses the source, so
monkeypatching it could never turn that red. A mutation with no test to fail is a mutation that
proves nothing.

### Two fixture bugs the real guards caught

Worth recording, because in both cases production was right and the test was cheap:

1. The fake `reqHistoricalData` returned a DataFrame. ib_insync returns a **list of BarData**,
   and `_fetch_contfuture` does `if not bars:` — which raises "truth value is ambiguous" on a
   frame. The fake now mirrors the real shape; the first version was testing a code path
   production never takes.
2. Synthetic bars ramping one point per minute from a base of 100 are a **0.365%** step at a
   price of 205, which trips the real `JOIN_JUMP_MAX_PCT` guard at 0.35% and refuses the
   append. The base is now 5000. Synthetic data has to sit in the range the production
   thresholds were measured for, or the test measures the fixture.

---

## Regression

| | result |
|---|---|
| 15 suites — 5R-0, 5Q-9, 5Q-8, 5Q-7, 5Q-5, 5Q-4, 5Q-3, 4C, 4B, 5E, 5F, 5L, checkpoint stage 1, stage 2, 5N | **492 passed, 1 skipped** |
| Stage 5R-0 mutations | 8 red, 0 green |

`test_event_playback.py` was not run — still on the known-hanging list.

The freshness and audit suites were not re-run because nothing they read was touched:
`run_scheduler.py`, `track1_freshness.py`, `track1_shadow_acceptance.py` and
`track1_shadow_audit.py` are all unchanged in this stage.

---

## What is live, and what still is not

The pre-flight runs the updater as a **fresh subprocess** —
`_run([sys.executable, "-m", "global_index.update_ibkr_daily", …])` via `subprocess.run` — so
it imports the corrected source on every invocation.

| | live |
|---|---|
| **5R-0: no in-progress final minute is stored** | **yes** — from tomorrow's 13:45, with no restart |
| `--repair-boundary` in the pre-flight argv | no — the job argv was fixed when the schedule was built at 09:25 ET |
| `spy_refresh_pm` at 16:20 | no — same restart |

### The three partial bars already in the files are NOT fixed by this

```text
NQ_continuous_1m_8y.parquet    last bar 2026-08-25 00:20:00  (partial, from the 5Q-7 repair run)
YM_continuous_1m_8y.parquet    last bar 2026-08-25 00:21:00  (partial)
RTY_continuous_1m_8y.parquet   last bar 2026-08-25 00:21:00  (partial)
```

5R-0 prevents new ones; it does not repair old ones. Two consequences to expect rather than be
surprised by:

- **tomorrow morning's Calm and Stress windows will still refuse** on those bars, exactly as
  predicted in Stage 5Q-7 — one bar per basket instrument. MES and NKD are clean.
- **`--repair-boundary` is still needed**, once, to clear them. After that it becomes a no-op
  in normal operation, which is the right end state: a repair path that never has anything to
  repair because nothing partial is ever written.

---

## Files

**Production**

```text
global_index/update_ibkr_daily.py   + drop_open_final_bar(), BAR_SECONDS, TAIL_KEPT/TAIL_NO_BARS;
                                    _fetch_contfuture stamps requested_at BEFORE the request and
                                    returns it; the append drops an open tail and reports it
global_index/fix_offset_step.py     unpacks the third return value (measures only, never appends)
```

**Scratch**

```text
scratch/test_track1_stage5r0_boundary_tail_20260824.py   21 tests
scratch/track1_stage5r0_mutations_20260824.py            8 mutations, all red
scratch/_track1_stage5r0_mutations.json
scratch/track1_stage5r0_boundary_tail_closeout_20260824.md / .json
```

Nothing else in the package was touched. No strategy rule, no identity field, no sizing basis,
no cap, no order gate.

---

## Operator — the next commands are the ones already outstanding

```powershell
# 1. Bring the corrected scheduler up: spy_refresh_pm at 16:20 and --repair-boundary at 13:45.
python monitor\ops.py restart --scheduler --track1-only-shadow

# 2. Let the dashboard learn about the new job.
python monitor\ops.py restart --no-scheduler --track1-only-shadow

# 3. Confirm.
python monitor\ops.py status
```

**After the restart, check:** job count **101** in track1-only mode · `spy_refresh_pm` at 16:20
ET · `SPY_REFRESH_PM` in the dashboard mirror · `--repair-boundary` in the 13:45 pre-flight argv
· legacy strategy jobs **0** · Track 1 strategy/safety/audit **70 / 11 / 5** ·
`orders_possible=False` with B1 still blocking.

**At tomorrow's 13:45**, the pre-flight log should show a `final-bar check` line per instrument,
and — if it runs while the market is trading, which it does — an
`IN-PROGRESS FINAL MINUTES NOT STORED` block naming the minutes deliberately skipped.

**Then re-probe:** each of MNQ, MYM and M2K should report `nothing_to_repair`, and that is the
observation that closes B-5R-H on the live files rather than only in the code.

```powershell
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ
```
