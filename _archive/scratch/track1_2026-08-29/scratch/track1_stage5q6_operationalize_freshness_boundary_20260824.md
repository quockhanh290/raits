# Stage 5Q-6 — operationalizing 5Q-5: what the live day actually showed

**2026-08-24, 19:45–20:10 ET ·** scheduler **not** started, stopped or restarted (pid 28696,
started 07:25:31 local = 09:25 ET, unchanged) · backend **not** restarted (pid 11720) · **one
read-only IBKR fetch made, disclosed below** · no order · no confirmation file ·
`TRACK1_ORDERS_APPROVED` unset · **no parquet, CSV or state file mutated** · no evidence row
deleted or rewritten · overlap guard **not** weakened · no commit.

---

## Verdict: **NOT_READY for 5R**

Four things were answered. Two of them are worse than 5Q-5 assumed, and one is better.

| question | answer |
|---|---|
| Is MNQ repair still needed and safe? | **The Friday bar is gone from the overlap. A NEW one was created today, plus MYM and M2K.** Bounded and safe to repair; the apply was **blocked by this environment's permission gate**, correctly |
| Enable `--repair-boundary` permanently? | **Yes — enabled in code.** Not on principle: one pre-flight today corrupted 3 of 5 instruments |
| Is the scheduler running the corrected 5Q-5 code? | **Partly.** Slot children yes; the scheduler's own job table no — it still has 100 jobs |
| Can the next windows be judged cleanly? | **No.** Today was a total refusal, and tomorrow will repeat unless the repair is applied |

---

## Part A — live state, read-only

```text
ET 19:45   all Track 1 windows closed; next slot NKD 01:10 tomorrow
scheduler  pid 28696   started 07:25:31 local = 09:25 ET   --track1-only-shadow
backend    pid 11720   connected=True  freshness=fresh  age 0.18s
track1_mode=track1-only-shadow
track1_blocking=['B1_broker_account_or_legacy_retirement']   orders_possible=False
track1_stop_trading=False  confirmation=False  track1_orders_approved=False
```

**B1 is the only order blocker, and it is still blocking.** Nothing else is active.

**The running scheduler has 100 jobs.** `spy_refresh_pm` is absent — it started at 09:25 ET,
before the job existed. The dashboard mirror likewise. While neither has it, the two agree.

Today's evidence, all durable:

```text
window_coverage_20260824.jsonl   52 rows
slot_timing_20260824.jsonl       42 rows   p50 2.41s  p95 2.78s  max 3.27s  all outcome=ok
audits/track1_audit_20260824.jsonl  8 records
```

The 13:45 pre-flight ran and succeeded (11:45–11:47 local), so the parquets and the SPY CSV
were both updated today.

### The audit pipeline worked, on a real day, with no false PASS

```text
14:10Z  roska4_calm    FAIL                 coverage_unobserved, missing_slot_ids, no_timing_records
16:40Z  roska4_stress  FAIL   p95 3.1       coverage_incomplete, slot_could_not_evaluate,
                                            slot_without_timing, no_candidates_to_explain
20:05Z  roska4_swing   FAIL   p95 2.4       coverage_incomplete, slot_could_not_evaluate
20:15Z  global_nkd     NOT_ENOUGH_DATA_YET  window_closed_before_scheduler_start
20:15Z  DAY            FAIL                 + the committed gate reported verbatim
```

Every reason is true. NKD is correctly pending rather than failed. The p95 gate has real
numbers for the first time — **2.78 s against a 240 s target**.

`slot_without_timing` on five Stress slots is honest and explainable: those slots ran between
10:35 and 10:55, before the telemetry wiring landed mid-morning. A code change during a
session, correctly reported rather than hidden.

### One thing is better than 5Q-5 expected

```text
csv last date            2026-08-21
required daily close     2026-08-21
freshness allow          TRUE   — every check ok, preflight_consistency ok
```

The 13:45 pre-flight brought the CSV to Friday, and the corrected requirement asks for Friday.
**B-5R-E's requirement half is not just live, it is passing.**

It will go stale again tomorrow morning: `required_daily_close_through(Tue 09:00)` is
2026-08-24 and the CSV holds 2026-08-21 until tomorrow's 13:45. That is precisely the gap
`spy_refresh_pm` at 16:20 closes, and it is the reason the restart matters.

---

## Part B — the measurement

**Method, disclosed:** one **read-only** IBKR fetch per instrument through the existing
provider path, on **client id 95** — chosen so a measurement can never contend with the Track 1
data client (89), the Track 1 safety client (90), legacy (1) or the daily updater (2). Two
clients on one id has already cost this system six entry slots. Run at 19:48 ET with every
window closed. **The tool writes nothing in this mode**, and no parquet mtime changed.

```text
MNQ    last bar 2026-08-24 13:45   disagreements 1   repairable
         high    29123.0 -> 29125.0   (+2.0)
         close   29123.0 -> 29125.0   (+2.0)
         volume    738.0 -> 1801.0    (+1063)      open, low IDENTICAL
MYM    last bar 2026-08-24 13:45   disagreements 1   repairable
         volume    137.0 ->  182.0    (+45)
M2K    last bar 2026-08-24 13:46   disagreements 1   repairable
         high     2997.6 -> 2997.7    (+0.1)
         volume      2.0 ->   15.0    (+13)
MES    last bar 2026-08-24 13:44   disagreements 0   nothing_to_repair
MNKD   REFUSED — disagreement_outside_the_window: 1052 bar(s) disagree outside the last
       120 minutes; the first is 2026-08-24 07:01:00+09:00
```

parquet sha256 (MNQ, before): `d231a9574a5579acd073bd173ba97c26d537b5e1ed9b9d10aed749a8add70539`

### Three findings

**1. The Friday MNQ bar is no longer in the overlap.** `shared_disagreements_total: 1`, and
that one is *today's* bar. The 2026-08-21 13:45 disagreement that refused 23 Stress slots this
morning has fallen out of the fetch window. It is still wrong in history — nothing repaired it
— but it is no longer causing refusals, and no tool can now measure it because the feed does
not reach back that far.

**2. Today's pre-flight created three new partial boundary bars.** MNQ, MYM and M2K, each at
its own file's last minute, each matching the completion signature exactly: `open` and `low`
unchanged, `high` risen, `volume` grown. MNQ's stored bar holds **41% of the minute's real
volume** (738 of 1801). This is B-5R-F predicted on Friday and observed on Monday, from the
run driven by the very line that creates it.

**3. MNKD is a different and much larger problem.** 1052 bars disagree, starting at
2026-08-24 07:01 JST. The tool refused rather than calling it a boundary repair, which is what
the window bound is for. **This is unquantified and is a new blocker — B-5R-G.** It is not a
partial bar; a contract roll, a back-adjustment difference or a clock question are all
consistent with what little is measured, and guessing between them here would be exactly the
move this stage exists to avoid.

Today's ledger corroborates the mechanism on a second instrument independently:

```text
x23  roska4_stress  MNQ  'low'   2026-08-21 13:45  29400.2500 -> 29395.7500   1 of 1186
x23  roska4_swing   M2K  'high'  2026-08-21 13:46   3019.9000 ->  3020.5000   2 of 2567
```

M2K's Friday boundary minute was 13:46 — its own file's last bar — and the feed's `high` is
*higher*, the one direction a partial bar's high can be wrong in.

---

## Part C — the repair decision, and why nothing was written

**Decision: apply, using the production appender.** The measurement confirms exactly the
bounded case: one bar per instrument, inside the window, monotonic completion.

```powershell
python -m global_index.update_ibkr_daily --repair-boundary --symbols MNQ MYM M2K
```

**It was not applied. This environment's permission gate blocked the command**, which is the
correct outcome: it mutates shared history and opens a broker connection, and this stage's own
rules require operator approval for exactly that. The command is handed over rather than
worked around.

### And a latent corruption was found on the way — in my own Stage 5Q-4 tool

Before applying anything I checked what the write would actually produce, and the answer was
alarming:

```text
raw parquet index   tz-NAIVE, UTC wall clock   (2026-08-24 17:45:00)
frozen_frame index  tz-AWARE America/New_York  (2026-08-24 13:45:00-04:00)
```

The 5Q-4 scratch tool's `--apply` path wrote `frozen_frame`'s output straight back. That would
have **rewritten the storage convention of an eight-year, 3.3-million-row file** that
`_core.load_parquet`, `assert_utc_convention` and every backtest depend on — one bar repaired,
the whole file's convention changed.

Its 26 tests did not catch it because the fixture wrote a tz-**aware** UTC parquet, so the
round trip preserved awareness in the test and would not have on disk. **A fixture that did not
match the file it stood in for** — the same family as every other "fixture agrees with itself"
lesson in these stages, and the reason the rule is to measure the real artifact before writing
to it.

Fixed: the tool now reads the file's own convention, writes back in it, refuses if the column
shape would change, and re-checks the convention after the write. A new test builds a
**naive** parquet — like the real ones — and requires it to come back naive.

This is also why the appender is the right instrument: it concatenates onto the raw frame and
runs `assert_utc_convention` before writing, so it never had this problem.

---

## Part D — permanent boundary repair: **enabled**

`--repair-boundary` is now passed to `update_ibkr_daily` in the 13:45 pre-flight.

Enabled on measured recurrence, not on principle. **One pre-flight today corrupted three of
five instruments**, and Friday's equivalents refused 46 Track 1 slots (23 Stress + 23 Swing).
This is not a risk profile; it is the observed daily behaviour of the job that now repairs it.

All six conditions the decision required are verified by test:

| condition | evidence |
|---|---|
| no write unless `boundary_replacement` accepts | the block is under `if a.repair_boundary` and `if boundary is not None`; mutation P9 |
| unchanged days byte-identical, no snapshot | `test_without_a_replacement_the_result_is_byte_identical_to_before`; the snapshot is inside the replacement branch |
| a legitimate partial is replaced and verified | snapshot + re-read verify; a write that did not land is `failed`, not assumed |
| wrong-contract / `open_changed` / `low_rose` / `high_fell` / `volume_shrank` / `moved_too_far` refuse | mutations P10–P13, one per rule |
| **a failure marks the pre-flight FAILED, not silently ok** | every refusal takes `failed.append(name)`, and `update_ibkr_daily` ends `sys.exit(1)  # pre-flight detects failure via returncode != 0`, which sets `_preflight_ok[today] = False` |
| the docs say this job can rewrite the last boundary bar by design | the pre-flight block carries it, and the runbook section below says it |

**Not live.** The pre-flight's argv is fixed when the schedule is built, so today's scheduler
still calls it without the flag. It engages on the same restart that brings `spy_refresh_pm`.

---

## Part E — restart: not performed, and the right moment is tonight

`spy_refresh_pm` is absent from the running scheduler. It needs a restart, and **the cheapest
moment is now, this evening** — better than tomorrow morning:

- every Track 1 window for 2026-08-24 has already closed **and been audited**; the eight audit
  records are written and durable;
- the next window is **NKD at 01:10 ET**, so a scheduler started this evening covers it
  completely — restarting tomorrow morning instead would make NKD `NOT_ENOUGH_DATA_YET` for a
  second consecutive day;
- `spy_refresh_pm` fires at 16:20 tomorrow, which is what makes Wednesday morning's freshness
  pass;
- `--repair-boundary` engages at tomorrow's 13:45, stopping the recurrence.

**The cost, named exactly.** After a restart, any *future* audit of 2026-08-24 will report its
closed windows as `window_closed_before_scheduler_start` — pre-start, not judgeable. Today's
verdicts must therefore be read from the eight records already written, not re-derived. Nothing
is deleted; the re-derivation simply stops being meaningful for that day. Today's day-verdict
is already `FAIL` and already recorded.

```powershell
python monitor\ops.py restart --scheduler --track1-only-shadow
python monitor\ops.py restart --no-scheduler --track1-only-shadow
```

*(`restart --help` verified: there is no `--backend` flag.)*

**After the restart, verify:**

```text
scheduler job count            101 in track1-only mode
spy_refresh_pm                 present, 16:20 ET
backend mirror                 SPY_REFRESH_PM present
track1_mode                    track1-only-shadow
legacy strategy jobs           0
Track1 strategy/safety/audit   70 / 11 / 5
orders_possible                False, blocking ['B1_broker_account_or_legacy_retirement']
```

---

## Part F — tests and the acceptance probe

| Suite | Result |
|---|---|
| Stage 5Q-5 (now 45), 5Q-4 (now 27), 5Q-3, 5Q, 5P ×2, 5O, 5M-D, 5L, 5Z, 4C, schedule-status, ops | **472 passed** |

The live acceptance audit, **dry run, wrote nothing**:

```text
global_nkd     NOT_ENOUGH_DATA_YET  window_closed_before_scheduler_start
roska4_calm    FAIL   coverage_unobserved, missing_slot_ids, no_timing_records
roska4_stress  FAIL   p95 3.1   slot_could_not_evaluate (gate_refused:stale, overlap_disagreement)
roska4_swing   FAIL   p95 2.4   slot_could_not_evaluate (overlap_disagreement)
DAY 2026-08-24 FAIL   + the committed gate verbatim
```

No false PASS. NKD is pending, not failed. Every failing sleeve names which slots and why.

---

## Blockers before 5R

| id | what | state |
|---|---|---|
| **B-5R-G** *(new)* | MNKD: 1052 bars disagree with the feed, first 2026-08-24 07:01 JST. Not a boundary bar — unquantified | **open, unmeasured** |
| **B-5R-D/F recurrence** | three partial boundary bars created today (MNQ, MYM, M2K); the repair is decided and blocked pending approval | **open** — one command |
| **B-5R-E** refresh half | `spy_refresh_pm` exists but is not registered | **open** — needs the restart |
| **B-5R-F** prevention | `--repair-boundary` is in the pre-flight argv in code | **open** — needs the same restart |
| **B-5R-C** | NKD after 2026-11-01 | open, reported as WARN |
| **B1** | the order gate | open by design; **orders remain impossible** |

`B-5R-G` is the one that cannot be scheduled away. Everything else has a command.

---

## Files

**Changed (production)**

```text
global_index/run_scheduler.py     the 13:45 pre-flight now passes --repair-boundary
```

**Changed (scratch)**

```text
scratch/track1_stage5q4_repair_boundary_bar_20260824.py   writes back in the FILE'S OWN index
                                                          convention; refuses a column reshape;
                                                          re-checks the convention after writing;
                                                          + --client-id, default 95
scratch/test_track1_stage5q4_overlap_and_repair_20260824.py   + the naive-parquet test
scratch/test_track1_stage5q5_freshness_boundary_20260824.py   + the three Part D conditions
```

**Added**

```text
scratch/track1_stage5q6_operationalize_freshness_boundary_20260824.md    this report
scratch/track1_stage5q6_operationalize_freshness_boundary_20260824.json
```

No production data file was written. No evidence row was deleted or rewritten.

---

## Operator page — exact next commands

```powershell
# 1. Repair today's three partial boundary bars. Snapshots each file, verifies by re-reading,
#    and refuses anything that is not a completion of the stored bar.
python -m global_index.update_ibkr_daily --repair-boundary --symbols MNQ MYM M2K

# 2. Confirm the repair landed. Writes nothing.
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MYM
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst M2K
#    each should print   verdict: nothing_to_repair

# 3. Restart TONIGHT, before the 01:10 NKD window.
python monitor\ops.py restart --scheduler --track1-only-shadow
python monitor\ops.py restart --no-scheduler --track1-only-shadow

# 4. Confirm.
python monitor\ops.py status          # track1-only-shadow, orders_possible=False, B1 blocking
```

**Do not** run step 1 while a Track 1 window is open. Right now nothing is open until 01:10 ET.

**Still needing a decision, not a command:** MNKD's 1052-bar disagreement (**B-5R-G**). It
should be audited the way MNQ was in Stage 5Q-4 — measure first, decide which side is wrong,
and do not widen any guard to make it quiet.
