# Track 1 — Stage 3B: closing the blockers

**Date:** 2026-08-22 (host clock Calgary MDT; market times ET unless stated)
**Contract kept:** no scheduler or service started · no IBKR connection · no live order · no
dashboard write · nothing committed · legacy not retired · legacy behaviour and files unchanged
· `global_index/test_event_playback.py` not run.

---

## A. Final verdict

> **B — ONLY USER_DECISION_GATE REMAINS.**

Eight blockers. **Four are CLOSED** with code and a test that goes red when the code is
removed. **Four are held by a decision only the project owner can make**, and each of those is
a hard code gate — not a note in a report — that refuses to arm the order path until an
explicit, schema-checked confirmation exists on disk.

**No blocker is prose-only. There is no `OPEN` status**, by construction: `track1_gates.py`
allows exactly two, and a self-check refuses a `USER_DECISION_GATE` that nothing can release,
a `CLOSED` one that still blocks, or a `CLOSED` one with no evidence.

| # | blocker | status | what closed it / what is needed |
|---|---|---|---|
| 1 | `B1_broker_account_or_legacy_retirement` | **GATE** | retire legacy **or** fund a second account |
| 2 | `B3_intraday_freshness` | **CLOSED** | a real, source-agnostic bar validator, 13 refusal codes |
| 3 | `SLEEVE_normal_r4` | **GATE** | accept subprocess isolation **or** fund a real promotion |
| 4 | `SLEEVE_nkd_mnkd` | **CLOSED** | it is already production code; rows anchored |
| 5 | `SLEEVE_calm_a` | **GATE** | write the detector **or** accept replay-only |
| 6 | `SLEEVE_stress_mnq` | **CLOSED** | computed from bars end to end, `mnq_only_g3_q7` |
| 7 | `CHECKPOINT_bootstrap_under_track1_params` | **CLOSED** | new bootstrap accepted, resume exact |
| 8 | `WIRING_scheduler_dashboard_paper` | **GATE** | approve scheduling; slots + mirror + `_ENTRY_WINDOWS` together |

### The exact decisions needed before anything proceeds

Four flags, in `track1_go_live_confirmation.json` — **which this build did not create**:

| flag | the decision |
|---|---|
| `legacy_retired_confirmed` **or** `separate_account_confirmed` | one IB login is one position book. Retire legacy first (the stated end state, and cheaper) or fund a second account. |
| `normal_generator_isolation_accepted` | the Normal-R4 generator reproduces the committed rows exactly, but replaces five production symbols while it runs. Accept subprocess isolation, or fund a promotion. |
| `calm_a_detector_accepted_frozen` | Calm A's setup list is a frozen CSV; the detector exists as prose and a column, not a function. Write it, or accept that Calm A is replay-only. |
| `scheduler_wiring_approved` | scheduling Track 1 slots changes what a running production process does. |

Plus `TRACK1_ORDERS_APPROVED=1` in the environment — a second, independent factor, so one flag
on a command line can never reach an exchange. A test asserts the full set **would** open the
gate: a ledger where some gate can never be released is one that says "never" while looking
like "not yet".

---

## B. Tests

| suite | command | result |
|---|---|---|
| Stage 3B (new) | `pytest scratch/test_track1_stage3b_blockers_20260822.py -q` | **72 passed, 1 skipped, 26.6 s** |
| Stage 3B regeneration gate | `TRACK1_REGEN=1 … -k regenerates` | **1 passed, 39.8 s** |
| Stage 3 route | `pytest scratch/test_track1_stage3_route_20260822.py -q` | **41 passed, 1 skipped** |
| Stage 3 floor equivalence | `TRACK1_EQUIV_FLOOR=1 … -k "floor or test_1_"` | **3 passed, 127 s** (re-run; Stage 3 measured 142 s) |
| the eight that must stay green | (unchanged command) | **156 passed, 6.6 s** |

`global_index/test_event_playback.py` was not run.

---

## C. Blocker 1 — B1, and why it is a gate rather than a fix

**What is true, read end to end.** `IBKRBroker.__init__` takes `host`, `port`, `client_id`,
`bar_duration` and no account. `get_positions()` reads `ib.positions()` unfiltered;
`get_equity()` reads `NetLiquidation` unfiltered. One Gateway login is one position book. A
legacy LONG 1 beside a Track 1 SHORT 1 on the same symbol reconciles as broker × 0 against two
file rows — `B3 MISMATCH` — and halts entries for **both** routes. It is the mechanism that put
the legacy `STRESS_MID` cron behind `if False:`. A different `client_id` does not help; it
decides who may cancel an order, not whose positions are counted.

**What was built.**

* `docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md` — seven checkable preconditions, eight ordered
  steps, a rollback. Every step names its check. The precondition that cannot be rushed is
  legacy being flat: it holds swing positions up to five days, so switching while it holds
  anything hands the new route positions it has no book for.
* `global_index/track1_gates.py` — the confirmation file, its schema, and the gate.

**How it fails closed, measured.** Eight invalid-file cases, each refusing the file **whole**
rather than honouring the parts that parsed: wrong `schema_version`, missing `confirmed_by`,
blank `confirmed_by`, a non-boolean flag, a **misspelled** flag, an unknown extra key,
unparseable JSON, and a JSON array. The misspelling case is the one that matters most —
silently dropping `legacy_retired_confirm` (no `d`) would leave the operator believing a gate
is open that is shut.

**Absent is not an error**, deliberately. The file's normal state is "not there", it grants
nothing, and the gated blockers refuse on their own. Reporting absence as a file error too
would make every refusal carry a complaint about a file nobody asked for.

**Tested:** refuses without confirmation (and `main --allow-orders` exits 2); a valid
`legacy_retired_confirmed` **closes B1 while the other three still block**; `separate_account_
confirmed` releases it too; the gate genuinely opens with no blockers **and** the environment
approval, and refuses with either one missing.

---

## D. Blocker 2 — B3 intraday freshness, CLOSED

`global_index/track1_intraday.py` validates a bar frame against a declared requirement per
sleeve. It is **source-agnostic** — it takes a frame and an instant — which is what makes it
real gate logic now rather than a promise about a source that does not exist yet.

The requirements, stated exactly rather than implied:

| | Calm A | Stress-MNQ |
|---|---|---|
| today's span the decision reads | 09:30–10:00 contiguous | 09:30–10:30 contiguous — that **is** the detector's input |
| decision bar | 10:00 must exist; its OPEN is the entry price | none; entry is a break inside the window |
| clock | at or after 10:00, and not after it | at or after 10:35, at or before 12:30 |
| prior session | 09:30–16:00 complete — the gate reads it | not required |
| observation | — | the window ledger must not report `incomplete` |

**Thirteen refusal codes**, and 18 fail-closed cases measured: no bars · not a frame · wrong
timezone · duplicate timestamps · out of order · missing session · partial coverage · a hole in
coverage · stale · too early · too late · decision bar absent · window unobserved. Plus one
passing case per sleeve, so the gate is not simply refusing everything.

**Two refusals that could have been repairs, and were not.** A duplicated timestamp survives
sorting and the last one wins on a reindex — which is how 1,050 of 1,590 NKD live bars once
overwrote frozen history with a 13-hour clock error. And a tz-aware frame in the wrong zone is
refused rather than converted: converting is how a frame ends up right by accident and wrong
the next time the offset moves.

**One check reports that it did not run.** When the caller supplies no window-ledger status,
the check says "not supplied by the caller, so not checked — this is a statement that the check
did not run, not that it passed", and a test asserts that wording. Silent passes are how
"unverified" becomes "verified OK".

---

## E. Blocker 3–6 — one verdict per sleeve

The single blocker "no sleeve has a live generator" named a wall rather than four doors. Traced
end to end, the four are in genuinely different states, and two of them are essentially ready.

| sleeve | kind | live-ready | anchor |
|---|---|---|---|
| `roska4_stress` | **computed from bars** | **yes** | `mnq_only_g3_q7`, qty 7 on the rows |
| `global_nkd` | already production code | **yes** | 228 / 31 / 26 rows reproduced exactly |
| `roska4_swing` | anchored regeneration | no | 980 / 136 / 107 rows reproduced exactly |
| `roska4_calm` | **frozen input** | no | the computed half anchors; the frozen half has nothing to anchor |

**Stress-MNQ (CLOSED).** Fully computed: `load_window` → `build_day_cache` →
`build_rule_with_levels(make_rule(Scenario('mnq_only_g3_q7', ('MNQ',), 7)))`. No frozen trade
table anywhere in the chain, no monkeypatching. Its one side effect is scoped and reversed in a
`finally`. Confirmed **not** `futures/stress_liquidation_1020.py` — a test asserts both that
the chain names `mnq_only_g3_q7` and that the other module still says of itself that it is not
wired.

**NKD/MNKD (CLOSED).** The sleeve *is* `futures.swing_tf.SwingTFEngine` at ema 10 / 2.5 /
hold 5 with `RegimeLabels(lag_days=1)` — production code today. Its route identity differs from
the Stage 2B bootstrap only in **rendering**: zero strategy differences, measured field by
field.

**Normal-R4 (GATE).** Re-anchored during this stage: **33.3 s, all_ok, 107 of 107 rows** on
vault2026, and the pytest gate re-ran it in **39.8 s** in a subprocess. What blocks it is not
correctness — it is that getting there replaces `futures._validated_core.backtest_swing_tf`,
`_swing_cache`, `TrendFollowStrategy.generate_signal`, `SwingTFEngine` and `StressMidEngine`
for the duration of the run, and depends on `model_sameday_stop.run_loop`, a root-level script.
**While it runs, the production engine IS the patched one.** The test drives it in a subprocess
on purpose, which is both the safe way to measure it and a working demonstration of the
mitigation the gate is asking about.

**Calm A (GATE).** The computed half — ATR15 disaster stop, exit simulation, risk, P&L — is
callable and deterministic. The **setup list** is `scratch/calm_pcloc_not_deep_gap_trade_list
.csv`: which days set up, in which direction, at what entry price. The detector rule is written
down and is a column in that CSV and **no function anywhere**. Today has no answer. Recording
`calm_a_detector_accepted_frozen` does not make it live-capable — it records that the
limitation is understood.

---

## F. Blocker 7 — the Track 1 checkpoint, CLOSED

`global_index/track1_bootstrap.py` writes two artefacts, because Stage 2C established that the
per-instrument checkpoint is not enough: the **book** carries more across a day boundary, and
each carried value changes which trades are *admitted*.

**Measured:** resume is exact on both a bare-date cut and an explicit mid-day instant — 91
events split 39 head + 52 tail, equity identical to the cent, the same two positions open at the
end. The cut is always an **instant**; `restore()` refuses a bootstrap with no `cut_instant`,
and refuses one missing `equity`, `peak_equity` or `positions`. The Stage 2B file is still
refused with `params_mismatch`, and the test proving it is kept. A new bootstrap written under
`track1_params` is accepted by `route_checkpoint.usable`, and moving one setting turns that
acceptance back into a `params_mismatch` refusal. Writing the route never touches another
route's keys.

### F.1 The finding: what Stage 2C could not prove is now proved

Stage 2C reported honestly that two mutations — a carried position in the wrong cluster, and
its risk × 20 — **would not** make the comparison diverge, and concluded the fields were not
shown to be load-bearing on its window. **My own Stage 2D Addendum 1 then overwrote that honest
"not proved" with an unmeasured "proved".** That is corrected in Addendum 2 of the Stage 2D
report, and the correction is the important half of this section.

Measured here, by sweeping cuts instead of picking one: **the reason was the cut, not the
field.** A carried position's `cluster` and `risk_dollars` are read by exactly one thing — the
cap gate, when a same-cluster candidate arrives *while that position is still open*. Stage 2C
placed its cuts to make the breaker's peak bind, a few sessions before the deepest drawdown, and
at those instants no same-cluster candidate followed before the carried position exited.
Measured directly at one such cut: both carried positions had **zero** same-cluster candidates
before they exited. Carried, restored, never consulted.

With a cut that does consult them, every carried field diverges — on all three windows:

| carried field | vault2026 | vault2025 | floor |
|---|---|---|---|
| `cluster` | 2026-01-26 14:30 | 2025-01-21 14:15 | 2018-10-31 14:35 |
| `risk_dollars` | 2026-01-26 14:30 | 2025-02-03 15:25 | 2018-02-22 14:45 |
| `day_start_equity` | 2026-01-26 14:30 | 2025-02-05 14:20 JST | 2018-02-22 14:45 |
| `equity` | 2026-06-29 14:55 | 2025-05-22 14:20 | any floor cut tested |
| `peak_equity`, `positions` | any cut carrying anything | " | " |

`equity` needed its own hunt: resetting it to the account base only bites once the book has
**grown** enough that the reset manufactures a drawdown crossing a breaker threshold.

The condition now lives in code — `track1_bootstrap.binding_cuts()` returns the instants where a
carried position's cluster is consulted again — so the next mutation test picks a cut that *can*
bind instead of hoping an arbitrary one does. A companion test asserts the *opposite* half: at
the ordinary 2026-03-31 cut, no carried position is consulted again, so if that ever changes the
explanation goes red rather than quietly becoming folklore.

`booked` remains a double-settlement counter and is correctly inert.

---

## G. Blocker 8 — scheduler and dashboard readiness

**Track 1's 25 slots are declared and none is registered**: 1 Calm at 10:00, 24 Stress at
five-minute spacing 10:35→12:30, derived from the same window table the admission gate and the
window ledger read — so a window change moves all three together. A test asserts no Track 1 slot
appears in a built scheduler, that `TRACK1_STRESS_1235` does not exist, and that
`as_dict()["scheduled_live"]` is False.

**The parity test found something on its first run.** The scheduler and its dashboard mirror key
on **two different namespaces**: APScheduler keys by job `id`; the dashboard parses
`scheduler_*.log` and keys on the `[BRACKETED]` label. They coincide for **56 of 58** timed
jobs. Two do not — job `live_day` logs as `LIVE_DAY_1405`, job `maxhold_exit` logs as
`MAX_HOLD_EXIT`. Nothing has ever gone wrong because of it. The alias table is now asserted, so
a **third** divergence goes red, and a test also asserts the table still has exactly two entries
and that both jobs still exist.

The parity check is itself shown to be able to fail: removing one job from the comparison turns
it red.

**Named, not applied:** `run_scheduler._ENTRY_WINDOWS` needs `((10,35),(12,30))`, or
`STOP_REPAIR_1220` runs a B3 reconcile inside the Stress window — an extra chance to halt
entries on a false mismatch, at the worst moment. A test asserts 12:20 is the one sweep inside
the window and that it is currently **not** excluded.

**The paper-output policy, per channel**, asserted as data: runner events share a file with a
route field (readers tolerate unknown keys); `trade_log.jsonl` stays **separate** until
`paper_evidence_reader` can split on route, because it aggregates the whole file and would fold
Track 1 rows into legacy's fill-quality and P&L gates; live state is route-scoped; slot timing
and window coverage already carry route.

---

## H. Ledger / code parity

`scratch/track1_blocking_ledger_20260822.json` is **generated from**
`global_index/track1_gates.BLOCKERS`, and a test compares them byte for byte. The markdown twin
is checked for naming every blocker id. Additional structural tests: no status outside the two
allowed; every gate is releasable and names its decision; every closed blocker carries evidence
and does not block; and the full confirmation set **would** open the route.

The sleeve table and the blocker registry are cross-checked against each other: a sleeve marked
live-ready whose blocker is still a gate — or the reverse — fails `track1_live_sleeves
.self_check()`.

---

## I. Files

**Created — production package**

| file | what it is |
|---|---|
| `global_index/track1_gates.py` | the blocker registry, the confirmation schema, the go-live gate |
| `global_index/track1_intraday.py` | the intraday bar validator, 13 refusal codes |
| `global_index/track1_live_sleeves.py` | one readiness verdict per sleeve, cross-checked against the registry |
| `global_index/track1_bootstrap.py` | book + checkpoint bootstrap, resume verification, `binding_cuts()` |
| `global_index/track1_slots.py` | Track 1's slot table, the legacy parity check, the paper-output policy |

**Created — docs and scratch**

| file | what it is |
|---|---|
| `docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md` | preconditions, ordered steps, rollback |
| `scratch/test_track1_stage3b_blockers_20260822.py` | 73 tests |
| `scratch/track1_blocking_ledger_20260822.md` / `.json` | the ledger; the JSON is generated |
| `scratch/_stage3b_legacy_baseline.json` | the pre-build hash/mtime snapshot |

**Changed — Track 1 files only**

| file | change |
|---|---|
| `global_index/track1_signal_layer.py` | **additive**: `restore()`, `cut_instant_for()`, `BootstrapRefused`, and `stop_after`/`resume_from` on `run_candidates`. Existing callers unaffected — the Stage 3 suite is unchanged and green. |
| `global_index/run_live_day_track1.py` | `OrderGate` now delegates to the registry; `OPEN_ORDER_BLOCKERS` is derived rather than hand-written; `book_state`/`--persist-book` unchanged |
| `scratch/track1_stage2d_full_production_route_audit_20260822.md` | **appended** Addendum 2 (correction) |

**No legacy production file was modified.** Section J proves it.

---

## J. Legacy untouched

**26 of 26 artifacts identical by content hash and mtime**, snapshotted before any write:

* runtime state — `live_positions.json`, `slip_stats.json`, `trade_log.jsonl`,
  `global_index/replay_checkpoint.json`, `live_state_data.js`, `preflight_state.json`,
  `maxhold_state.json`, `paper_history.json`
* legacy code — `signal_layer.py`, `run_live_day.py`, `runner.py`, `run_scheduler.py`,
  `ibkr_broker.py`, `live_decision.py`, `net_exposure_multi.py`, `replay_checkpoint.py`
* the route's shared modules — `route_checkpoint.py`, `route_params.py`, `window_ledger.py`,
  `slot_telemetry.py`
* dashboard — `app.py`, `schedule_status.py`, `job_journal_reader.py`,
  `paper_evidence_reader.py`
* still absent — `runner.pid`, `STOP_TRADING`

`track1_go_live_confirmation.json` does not exist, and a test asserts it does not.

---

## K. What I would still not claim

**Verified, with a number:** every test result above; the 33.3 s / 107-row re-anchor; the
per-field binding cuts on three windows; the 56-of-58 namespace coincidence; the identity diff
against the Stage 2B bootstrap; 26 of 26 legacy artifacts unchanged.

**Reasoned from the code path, not executed:** that the intraday validator's requirements match
what a live sleeve will actually read. The Calm A and Stress requirements are derived from the
strategies' entry and exit definitions, and no live source exists to disagree with them yet. If
the promoted detector turns out to read one more bar than the requirement declares, the gate
would pass a frame that is one bar short.

**Not examined:** whether the Normal-R4 generator is safe to run in a subprocess *concurrently*
with a trading process — the test runs it alone. Memory and parquet-cache contention were not
measured.

**Out of scope and not started:** retiring legacy, scheduling any Track 1 slot, and creating any
confirmation. Nothing in this build changes what the running scheduler does.
