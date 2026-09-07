# Track 1 — Stage 4: production-clean promotion

**Date:** 2026-08-23 (host clock Calgary MDT; market times ET unless stated)
**Contract kept:** no scheduler or service started · no IBKR connection · no live order · no
dashboard write · nothing committed · legacy not retired · legacy behaviour unchanged ·
`global_index/test_event_playback.py` not run.

---

## A. Verdict

> **A — PRODUCTION-CLEAN BLOCKERS CLOSED. Ready for shadow scheduler wiring.**

The three things this stage was asked to do are done, and each is closed by exact
reproduction rather than by acceptance:

| decision | what was asked | result |
|---|---|---|
| 1 | promote Normal-R4 with **no monkeypatching** | **exact on all three windows — 1,223 rows**, and a test asserts by object identity that five production symbols and `DEFAULT_CONFIG` are untouched |
| 2 | implement a real Calm A detector | **exact on all three windows — 421 of 421 rows**, plus its four recorded feature columns to 1e-9, and a guard test fails the run if the frozen CSV is opened |
| 3 | prepare scheduler/dashboard wiring, no orders | built, **off by default**, parity green in both modes, legacy argv byte-identical |

**Seven of the eight Track 1 blockers are now CLOSED. One remains: B1.**

### The one thing that changed about safety, and it deserves saying plainly

Because B1 is now the last blocker, **a valid confirmation file plus `TRACK1_ORDERS_APPROVED=1`
genuinely arms the order gate.** Before this stage, releasing B1 still left three gates shut.
It no longer does. That is the designed end state — but it means the confirmation file has
stopped being one safeguard among several and has become *the* safeguard. A test now asserts
both halves: the file alone does not arm the gate, and both factors together do.

The file still does not exist, and nothing in this build creates it.

---

## B. Tests

| suite | result |
|---|---|
| `scratch/test_track1_stage4_production_clean_20260823.py` (vault2026) | **25 passed, 484 s** |
| same, `TRACK1_STAGE4_ALL=1` (all three windows) | **32 passed, 1004 s (16:44)** |
| `scratch/test_track1_stage3b_blockers_20260822.py` | **72 passed, 1 skipped, 24 s** |
| `scratch/test_track1_stage3_route_20260822.py` | **41 passed, 1 skipped, 32 s** |
| Stage 3 floor equivalence (`TRACK1_EQUIV_FLOOR=1`) | **3 passed, 128 s** |
| the eight that must stay green | **156 passed, 5.7 s** — unchanged since Stage 2D |

`global_index/test_event_playback.py` was not run.

Four Stage 3B tests were **rewritten**, not deleted: they encoded the old world (blockers
open, Calm A frozen, Normal-R4 monkeypatching). Each now asserts the new truth and keeps its
teeth — see §F.

### B.1 One test of mine was stale, and the all-window run caught it

The first all-window run came back **1 failed, 30 passed in 958 s**. The failure was not the
code: it was `test_b_the_calendar_decides_which_session_is_prior`, written while the Calm A
session rule was still `exclude_non_trading_days` and never updated when the rule became
`require_full_rth_session`. It called a keyword that no longer exists.

It is worth recording rather than quietly fixing, for two reasons. The vault2026-only run had
30 tests pass without touching it, so the shorter gate could not have caught it. And the test
had been asserting the *rejected* design — the calendar — which is precisely the kind of test
that keeps a superseded idea alive. It was replaced by two: one that asserts the shipped rule
in both directions (every dropped session genuinely lacks the 15:59 bar, every kept one has
it), and one that pins the Presidents' Day row that found the rule.

**The rerun after the fix: 32 passed in 1004 s, nothing failed.** That is the run that carries
the all-window verdict; the 25-test vault2026 figure above is the fast gate.

---

## C. Normal-R4 — promoted

### The result

Reproduces the committed rows **exactly**, per instrument, row for row:

| window | MES | MNQ | MYM | M2K | MNKD | total |
|---|---:|---:|---:|---:|---:|---:|
| floor 2018-2024 | 188 | 186 | 200 | 178 | 228 | **980** |
| vault2025 | 26 | 27 | 26 | 26 | 31 | **136** |
| vault2026 | 22 | 18 | 24 | 17 | 26 | **107** |

Compared on `(day, exit_day, direction, entry, exit, pnl)` — the same six fields the existing
anchor uses.

### What replaced what

| the scratch path did | the promoted module does |
|---|---|
| `tf.TrendFollowStrategy.generate_signal = gated_generate` (class-level) | `make_signal_fn()` — the CALLER gates the strategy's own return value |
| a second wrapper on the instance for the stop basis | the same callable re-anchors the stop, so the cache path *and* the rescan path both get it |
| `tf.DEFAULT_CONFIG["allowed_regimes"] = ["Normal"]` | `ALLOWED_REGIMES`, a local constant |
| `force_all_bars_gappable()` replacing `_swing_cache` | `_cache_for()` post-processes a **copy**; the production cache is left as found |
| `model_sameday_stop.run_loop` (a root-level script) | `_replay()`, carrying only the branches this sleeve reaches |
| `ST.SwingTFEngine` / `SM.StressMidEngine` replaced | not needed — nothing has to be silenced |

**The no-monkeypatch claim is tested by object identity**, not by equality. The scratch path
restores every symbol in a `finally`, so an afterwards-only check would pass on it too. The
test captures `id()` of `backtest_swing_tf`, `_swing_cache`,
`TrendFollowStrategy.generate_signal`, `SwingTFEngine`, `StressMidEngine` and a copy of
`DEFAULT_CONFIG`, runs the generator, and requires all six unchanged.

The two context filters were **promoted, not re-derived** — the scratch library's header says
there is one implementation on purpose, and a re-derivation would have broken that. A test
requires the promoted copy and the scratch original to return the same verdict for **every
5-minute bar** of a real instrument (>5,000 bars) and the same block counters, and asserts the
filter neither passes everything nor nothing.

### Two divergences, measured rather than tuned

The first pass matched MNQ exactly and diverged on the other four. Both causes were found by
measuring the specific failing row.

**1. Same-day re-entry after an exit.** MES exits MAX_HOLD at 09:30 on 2026-01-26 and
**re-enters at 15:20 the same session**. `run_loop` rescans the window *after* the exit rather
than reading the signal cache — because `avgv` is positional inside the 14:00-15:55 window, so
a truncated window genuinely produces different averages. My first pass refused any entry on a
day that had exited: 20 trades where the record has 22.

**2. The daily-ATR warm-up.** The cache builder DROPS a day whose daily ATR is missing, while
the signal wrapper KEEPS such a signal with its original stop. Since almost every entry comes
through the cache, dropping is the effective rule. It bites at the start of a clipped window:
without it vault2025 gained trades on 2025-01-02 and 2025-01-10, and the record's first trade
is 2025-01-21 — about fourteen sessions in, exactly the warm-up.

A third was mine and simpler: the first run gave MNKD `ema_period=50` and it produced a LONG
where the record says SHORT. MNKD runs at ema 10. `generate()` now takes labels and params
**per instrument** for that reason.

### The fill law is a parameter

`_swing_cache` flags a bar gap-eligible after a >15-minute break. The committed artifacts were
built with **every** bar eligible. Both laws are selectable and the default is the artifact
law, because that is what an equivalence test has to reproduce.

**Worth carrying forward:** `track1_params.fill_law` declares
`production_gap_after_15min_break`, while the rows every Track 1 number rests on were built
under the artifact law. The three-blockers report measured the book-level difference at $0 to
+$6 over seven years, so it is immaterial in P&L — but the declared identity and the actual
data disagree, and that is worth resolving before the identity is used to accept a checkpoint.

---

## D. Calm A — a detector, not a list

### The result

Reproduces the frozen list **exactly on all three windows**:

| window | MES | MNQ | total |
|---|---:|---:|---:|
| floor (IS 2018-2024) | 164 | 185 | **349** |
| vault2025 (OOS 2025) | 26 | 18 | **44** |
| vault2026 (SANITY 2026) | 14 | 14 | **28** |
| | | | **421 of 421** |

Not just the same days: a test matches the four recorded feature columns —
`gap_from_prev_rth_close`, `prev_close_loc`, `prev_rth_ret`, `open_loc_prev_range` — **to
1e-9**, which a wrong feature with a compensating threshold could not do. A guard test fails
the run if the detector path so much as opens the CSV.

### The rule, and where every number came from

    regime      the SPY HMM label at the PRIOR session is "Calm"
    pcloc       (prior close - prior low) / prior range  <=  1/3
    down        prior close / prior open - 1  <=  0
    not_deep    current RTH open / prior RTH close - 1  >=  -0.010
    trade       LONG only, MES and MNQ, entry at the 10:00 OPEN, exit at the 15:55 OPEN

Thresholds were **read off the artifact**, not fitted: `prev_close_loc` tops out at exactly
0.333333 and `prev_rth_ret` at exactly 0.000000 across all 421 rows, and the audit states the
gap filter verbatim. `open_loc_prev_range` ranges −1.53 to +2.05 across selected rows, so it is
a diagnostic and not a criterion — computed anyway, because a column that exists in the record
and not in the code is the next thing somebody mistakes for a rule.

### Three conventions the definition did not state

Each was found by a divergence and settled by reading the record, not by adjusting a number.

**1. Entry and exit are bar OPENs.** Verified against MNQ 2018-01-05: the 10:00 bar's open is
8753.00 and the 15:55 bar's open is 8791.75, matching the row exactly.

**2. The prior session's RTH window ends at 15:59, not 16:00.** One bar. The frozen row implies
a prior close of 8724.50; [09:30, 16:00] closes at 8725.75 and [09:30, 15:59] at 8724.50 —
which moves close-location from 0.3675 to 0.3248, **across the 1/3 threshold**. That single
bar decides whether the day sets up.

**3. A session counts only if it RAN TO that close.** The record's own `prev_session_day`
column names it four times:

| day | record's prior session | what was skipped |
|---|---|---|
| 2019-12-26 | 2019-12-23 | Christmas Eve (early close) |
| 2020-12-28 | 2020-12-23 | Christmas Eve |
| 2023-11-27 | 2023-11-22 | Black Friday (early close) |
| 2025-02-18 | 2025-02-14 | Presidents' Day (shortened session) |

A calendar was tried first and is the **wrong tool**: `raits.live.trading_calendar` calls
Christmas Eve and Black Friday trading days, which they are — the exchange is open. What this
detector cannot use is a session with no 15:59 bar, because its close and range would be
measured at 13:00 and mean something else. With the calendar rule floor lost 5 rows and gained
2; with the ran-to-close rule it is exact. The bars answer the question themselves, and no
calendar library can disagree with them.

**One more, about frames:** the window is a filter on the RESULT, not a slice of the frame.
Clipping the start lost 2026-01-02 (no prior session) and clipping the end lost 2026-08-19 (the
end clip is a midnight boundary, so the last day has no 10:00 bar).

---

## E. Scheduler and dashboard wiring

**Off by default, and off means unchanged.**

| | Track 1 off | Track 1 on |
|---|---|---|
| scheduler jobs | **60** — the same 60 as always | 84 |
| `STOP_REPAIR_1220` | present | removed (inside the Stress window) |
| `_ENTRY_WINDOWS` | 2 windows | 3, gaining `((10,35),(12,30))` |
| dashboard mirror | 58 rows | 82 rows |
| parity | **green** | **green** |

* `run_scheduler.make_scheduler(track1_shadow=False)` and CLI `--track1-shadow`.
* The mirror gates on `RAITS_TRACK1_SHADOW=1` and subtracts from the **same constant** —
  `run_scheduler._TRACK1_STRESS_WINDOW`, asserted equal to
  `track1_slots.REQUIRED_ENTRY_WINDOW` and `schedule_status.TRACK1_STRESS_WINDOW`. The window
  exists once, not three times.
* `parity_report(track1_shadow=…)` flips **both** sides together — flipping one side only is
  the drift the check exists to catch — and is still shown able to go red.
* A Track 1 slot calls `run_live_day_track1` with **no `--allow-orders` and no broker port**.
* The legacy argv is asserted byte-identical, field by field. Three log readers parse it.

**Scope: this closes the WIRING, not the running of it.** No scheduler was started; no Track 1
slot has ever fired.

One test had to be fixed rather than the code: it drove the legacy slot expecting an argv, but
the slot fails closed on a missing pre-flight record first. The flag is now seeded **in memory**
for the ET date — nothing calls `_save_preflight_state`, so the operator's file is untouched.

---

## F. Gates and the ledger

| blocker | before | after |
|---|---|---|
| `B1_broker_account_or_legacy_retirement` | GATE | **GATE** — the only one left |
| `B3_intraday_freshness` | CLOSED | CLOSED |
| `SLEEVE_normal_r4` | GATE | **CLOSED** |
| `SLEEVE_nkd_mnkd` | CLOSED | CLOSED — now generated from bars too |
| `SLEEVE_calm_a` | GATE | **CLOSED** |
| `SLEEVE_stress_mnq` | CLOSED | CLOSED |
| `CHECKPOINT_bootstrap_under_track1_params` | CLOSED | CLOSED |
| `WIRING_scheduler_dashboard_paper` | GATE | **CLOSED** |

**Three confirmation flags were removed** — `normal_generator_isolation_accepted`,
`calm_a_detector_accepted_frozen`, `scheduler_wiring_approved` — because the blockers they
existed to release are closed. Removed rather than left unused: a flag that releases nothing is
a flag somebody will one day set and believe something happened. The confirmation file refuses
unknown keys, so a file naming one of them now fails validation, which is correct.

The ledger JSON is regenerated from the registry and the parity test passes. The markdown was
updated in place.

### The four Stage 3B tests that were rewritten

Each encoded the old world. None was weakened:

| test | was | now |
|---|---|---|
| `..._closes_b1_and_the_others_still_block` | asserted three named gates still block | asserts **exactly B1** moves (against the registry, not a hand-written list), that nothing else blocks, and that the file alone does **not** arm while both factors do |
| `..._each_one_has_a_named_call_chain_and_a_verdict` | expected two sleeves ready | expects all four, every kind `computed_from_bars`, and **no side effect that replaces a `futures.`/`raits.` symbol** |
| `..._calm_a_names_the_frozen_file_that_stops_it` | asserted the CSV is a frozen input | asserts it is **not** an input any more, and that the CSV still exists as the thing the detector is measured against |
| `..._normal_r4_names_every_symbol_it_replaces` | asserted five replaced symbols | asserts **nothing** is replaced and `model_sameday_stop` is out of the chain |

The side-effect assertion was deliberately narrowed after it fired on Stress: Stress sets one
scratch constant for a call and restores it in a `finally`, which is a different thing from
replacing a production function for a run. Banning both would have made the test say something
it does not mean.

---

## G. Files

**Created — production package**

| file | lines | what |
|---|---:|---|
| `global_index/track1_normal_r4.py` | 424 | the Normal-R4 sleeve, from bars, no monkeypatching |
| `global_index/track1_normal_filters.py` | 213 | R4 context filter + SPY short gate, promoted from scratch |
| `global_index/track1_calm_a.py` | 261 | the Calm A detector |

**Created — scratch**

| file | lines |
|---|---:|
| `scratch/test_track1_stage4_production_clean_20260823.py` | 474 |
| `scratch/_stage4_legacy_baseline.json` | — |
| `scratch/_stage4_normal_equiv.json`, `scratch/_stage4_calm_equiv.json` | — |

**Changed — legacy production, additive and gated (task C authorised these two)**

| file | change |
|---|---|
| `global_index/run_scheduler.py` | +81/−1: `track1_shadow` parameter, `--track1-shadow` flag, `_TRACK1_STRESS_WINDOW`, the gated slot block. Default path unchanged — 60 jobs, same ids, byte-identical argv, all asserted |
| `monitor/backend/schedule_status.py` | +37/−2: `track1_shadow_enabled()`, `TRACK1_STRESS_WINDOW`, `_stop_repair_slots()`. Default path unchanged — asserted |

**Changed — Track 1 files**

`global_index/track1_gates.py` (three closures, three flags removed),
`global_index/track1_live_sleeves.py` (all four sleeves now computed-from-bars),
`scratch/track1_blocking_ledger_20260822.{md,json}`,
`scratch/test_track1_stage3b_blockers_20260822.py` (four tests rewritten).

**Legacy untouched:** every runtime-state artifact and every other legacy code file is
byte-identical and mtime-identical to the pre-Stage-4 snapshot — `live_positions.json`,
`trade_log.jsonl`, `slip_stats.json`, `replay_checkpoint.json`, `live_state_data.js`,
`preflight_state.json`, `maxhold_state.json`, `paper_history.json`, `signal_layer.py`,
`run_live_day.py`, `runner.py`, `ibkr_broker.py`, `live_decision.py`, `net_exposure_multi.py`,
`replay_checkpoint.py`, `model_sameday_stop.py`, `futures/_validated_core.py`,
`futures/swing_tf.py`, `futures/basket.py`, `monitor/backend/app.py`,
`job_journal_reader.py`, `paper_evidence_reader.py`. `runner.pid` and `STOP_TRADING` are still
absent, and so is `track1_go_live_confirmation.json`.

---

## H. What remains, and what I would not claim

**The only blocker: B1.** One IB Gateway login is one position book. Retire legacy first — the
stated end state and the cheaper of the two — or fund a dedicated account. The runbook is
`docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md`.

**Next step, now unblocked:** run the shadow scheduler with `--track1-shadow` and
`RAITS_TRACK1_SHADOW=1`, with the window ledger on, for a measured period. That is a decision
to change what a running production process does, so it is yours to make; the code no longer
stands in the way.

**Verified, with a number:** every test result above; 1,223 Normal-R4 rows and 421 Calm A rows
reproduced exactly across three windows; object-identity proof that no production symbol is
replaced; bar-for-bar agreement between the promoted filters and the scratch originals; 60-job
default schedule and byte-identical legacy argv; parity green in both modes.

**Reasoned from the code path, not executed:** that the promoted sleeves behave identically on
a LIVE frame — one with today's partial session spliced onto the parquet — as they do on the
measured frames. Every reproduction here is on historical frames. The splice is the seam that
has bitten this project before, and no test covers it yet.

**Not examined:** whether `track1_params.fill_law` should be changed to the artifact law or the
committed rows regenerated under the production law. They currently disagree, immaterially in
P&L ($0 to +$6 over seven years) but not in identity.

**Out of scope and not started:** retiring legacy, starting any scheduler, firing any Track 1
slot, and creating any confirmation file.
